"""REST + Server-Sent Events API for the Next.js frontend.  Run: jobscout serve"""
import asyncio
import csv
import hmac
import io
import json
from datetime import date
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from jobscout.config import get_settings
from jobscout.db.models import (
    Account,
    Contact,
    ContactPost,
    EmailOutreach,
    EmailStatus,
    Platform,
    Post,
    ScrapeRun,
    User,
)
from jobscout.db.session import new_session
from jobscout.extract.dates import PRESETS, now, resolve
from jobscout.web.auth import current_user
from jobscout.web.auth import profile_router
from jobscout.web.auth import router as auth_router
from jobscout.web.email_api import router as email_router
from jobscout.web.telegram_api import router as telegram_router
from jobscout.web.jobs import Job, manager

_settings = get_settings()
_docs = _settings.api_docs and not _settings.internal_api_key
app = FastAPI(title="jobscout API", docs_url="/docs" if _docs else None, redoc_url=None,
              openapi_url="/openapi.json" if _docs else None)


@app.middleware("http")
async def require_internal_key(request: Request, call_next):
    """Only the Next.js server may call this API (it adds X-Internal-Key). There is no CORS setup on
    purpose: browsers never call this API directly, they call the Next.js route handlers."""
    key = get_settings().internal_api_key
    if key and request.url.path.startswith("/api"):
        given = request.headers.get("x-internal-key", "")
        if not hmac.compare_digest(given.encode(), key.encode()):
            return JSONResponse({"detail": "Not found"}, status_code=404)
    return await call_next(request)

app.include_router(auth_router)
app.include_router(profile_router)
app.include_router(email_router)
app.include_router(telegram_router)
Me = Depends(current_user)
BROWSER_JOBS = ("scrape", "login")  # share the LinkedIn browser profile: one at a time


def _own(obj, user: User, what: str):
    """404 unless the row exists and belongs to this user."""
    if obj is None or obj.user_id != user.id:
        raise HTTPException(404, f"{what} not found")
    return obj


def _uses_browser(job: Job) -> bool:
    return job.kind == "login" or (job.kind == "scrape" and job.params.get("source", "linkedin") == "linkedin")


def _check_server_capacity() -> None:
    if manager.count_running(BROWSER_JOBS, where=_uses_browser) >= get_settings().max_browser_jobs:
        raise HTTPException(503, "The server is busy with other searches. Try again in a few minutes.",
                            headers={"Retry-After": "120"})


def _job(job_id: str, user: User) -> Job:
    job = manager.get(job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(404, "job not found")
    return job


def _iso(dt):
    return dt.isoformat() if dt else None


# ---------------------------------------------------------------- accounts
class AccountIn(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=1)
    platform: Platform = Platform.linkedin


def _account_dict(a: Account) -> dict:
    return {"id": a.id, "platform": a.platform.value, "email": a.login_email, "active": a.is_active,
            "last_login_at": _iso(a.last_login_at), "last_status": a.last_status}


@app.get("/api/accounts")
def list_accounts(user: User = Me):
    with new_session() as s:
        q = select(Account).where(Account.user_id == user.id).order_by(Account.id)
        return [_account_dict(a) for a in s.scalars(q)]


@app.post("/api/accounts", status_code=201)
def add_account(body: AccountIn, user: User = Me):
    from jobscout.security.crypto import encrypt

    with new_session() as s:
        acc = Account(user_id=user.id, platform=body.platform, login_email=body.email.strip().lower(), password_enc=encrypt(body.password))
        s.add(acc)
        try:
            s.commit()
        except IntegrityError:
            raise HTTPException(409, "You already connected this LinkedIn account.")
        return _account_dict(acc)


@app.patch("/api/accounts/{account_id}")
def set_account_active(account_id: int, active: bool, user: User = Me):
    with new_session() as s:
        acc = _own(s.get(Account, account_id), user, "account")
        acc.is_active = active
        s.commit()
        return _account_dict(acc)


@app.delete("/api/accounts/{account_id}", status_code=204)
def delete_account(account_id: int, user: User = Me):
    with new_session() as s:
        acc = _own(s.get(Account, account_id), user, "account")
        s.delete(acc)
        s.commit()


@app.post("/api/accounts/{account_id}/login")
def login_account(account_id: int, user: User = Me):
    """Opens a visible browser on this computer; the user completes OTP/CAPTCHA there."""
    if manager.running(BROWSER_JOBS, user_id=user.id):
        raise HTTPException(409, "Another job is running. Wait for it to finish.")
    _check_server_capacity()
    with new_session() as s:
        _own(s.get(Account, account_id), user, "account")

    def target(job: Job) -> None:
        from jobscout.browser.manager import open_context
        from jobscout.scrapers import get_scraper
        from jobscout.security.crypto import decrypt

        job.emit({"type": "log", "level": "info",
                  "message": "Browser opened. Finish any OTP / CAPTCHA there (5 minutes)."})
        with new_session() as s:
            acc = s.get(Account, account_id)
            with open_context(acc, headless=False) as ctx:
                ok = get_scraper(acc.platform, ctx).ensure_logged_in(acc.login_email, decrypt(acc.password_enc), True)
            acc.last_status = "ok" if ok else "login_failed"
            if ok:
                acc.last_login_at = now()
            s.commit()
        job.emit({"type": "login", "ok": ok})
        if not ok:
            job.status = "error"

    return manager.start("login", {"account_id": account_id}, target, user_id=user.id).summary()


# ---------------------------------------------------------------- scraping
class ScrapeIn(BaseModel):
    tags: list[str] = []              # role hashtags: post must contain AT LEAST ONE (searched together)
    required_tags: list[str] = []     # extra must-have hashtags; #hiring is always required
    date_filter: str = "today"
    date_from: date | None = None
    date_to: date | None = None
    limit: int = Field(20, ge=1, le=100)
    account_ids: list[int] | None = None
    headless: bool = False
    # Telegram source (ignored for LinkedIn)
    source: Literal["linkedin", "telegram"] = "linkedin"
    keywords: list[str] = Field(default=[], max_length=30)
    channel_ids: list[int] | None = None
    exp_min: int | None = Field(default=None, ge=0, le=50)
    exp_max: int | None = Field(default=None, ge=0, le=50)
    location: str | None = Field(default=None, max_length=200)   # comma-separated, any one matches
    work_types: list[Literal["remote", "hybrid", "on-site"]] = []  # empty = any


@app.get("/api/scrape/options")
def scrape_options():
    return {"date_presets": list(PRESETS), "max_limit": 100}


@app.post("/api/scrape")
def start_scrape(body: ScrapeIn, user: User = Me):
    if manager.running(BROWSER_JOBS, user_id=user.id):
        raise HTTPException(409, "A job is already running.")
    if body.exp_min is not None and body.exp_max is not None and body.exp_min > body.exp_max:
        raise HTTPException(422, "Minimum experience can't be more than the maximum.")
    if body.source == "linkedin":
        from jobscout.pipeline.scrape import HIRING_TAG, normalise_tags

        if not [t for t in normalise_tags(body.tags) if t != HIRING_TAG]:
            raise HTTPException(422, "Add at least one role hashtag.")
        _check_server_capacity()
    try:
        dr = resolve(body.date_filter, body.date_from, body.date_to)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if body.source == "telegram":
        return _start_telegram_scrape(body, dr, user)

    def target(job: Job) -> None:
        from jobscout.pipeline.scrape import run_scrape

        job.emit({"type": "start", "date_range": {"label": dr.label, "start": _iso(dr.start), "end": _iso(dr.end)},
                  "limit": body.limit})

        def progress(r):
            job.emit({"type": "progress", "scanned": r.scanned, "saved": r.saved, "collected": r.collected,
                      "limit": body.limit})

        res = run_scrape(user_id=user.id, platform=Platform.linkedin, tags=body.tags, use_ai=user.is_paid,
                         required_tags=body.required_tags, date_range=dr, limit=body.limit,
                         account_ids=body.account_ids or None, headless=body.headless,
                         exp_min=body.exp_min, exp_max=body.exp_max, location=body.location,
                         work_types=body.work_types,
                         on_progress=progress, on_event=job.emit, should_stop=lambda: job.stop_requested)
        job.emit({"type": "summary", "run_id": res.run_id, "scanned": res.scanned, "saved": res.saved,
                  "collected": res.collected, "limit": body.limit, "stop_reason": res.stop_reason,
                  "skipped": res.skipped, "failed_accounts": res.failed_accounts,
                  "unprocessed_tags": res.unprocessed_tags, "stopped": res.stopped})

    return manager.start("scrape", body.model_dump(mode="json"), target, user_id=user.id).summary()


def _start_telegram_scrape(body: ScrapeIn, dr, user: User):
    """Free plan: reads public channel pages over plain HTTP (no browser, no LinkedIn account, no AI)."""
    def target(job: Job) -> None:
        from jobscout.pipeline.telegram import run_telegram_scrape

        job.emit({"type": "start", "source": "telegram",
                  "date_range": {"label": dr.label, "start": _iso(dr.start), "end": _iso(dr.end)}, "limit": body.limit})

        def progress(r):
            job.emit({"type": "progress", "scanned": r.scanned, "saved": r.saved, "collected": r.collected,
                      "limit": body.limit})

        res = run_telegram_scrape(user_id=user.id, keywords=body.keywords, date_range=dr, limit=body.limit,
                                  channel_ids=body.channel_ids or None, exp_min=body.exp_min, exp_max=body.exp_max,
                                  location=body.location, work_types=body.work_types,
                                  on_progress=progress, on_event=job.emit, should_stop=lambda: job.stop_requested)
        job.emit({"type": "summary", "run_id": res.run_id, "scanned": res.scanned, "saved": res.saved,
                  "collected": res.collected, "limit": body.limit, "stop_reason": res.stop_reason,
                  "skipped": res.skipped, "failed_accounts": res.failed_accounts,
                  "unprocessed_tags": [], "stopped": res.stopped})

    return manager.start("scrape", body.model_dump(mode="json"), target, user_id=user.id).summary()


@app.get("/api/jobs/current")
def current_job(kind: str = "scrape", user: User = Me):
    kind = tuple(k for k in kind.split(",") if k) or ("scrape",)
    job = manager.running(kind, user_id=user.id) or manager.latest(kind, user_id=user.id)
    return job.summary() if job else None


@app.post("/api/jobs/{job_id}/stop")
def stop_job(job_id: str, user: User = Me):
    job = _job(job_id, user)
    job.stop_requested = True
    job.emit({"type": "log", "level": "info", "message": "Stopping after the current post…"})
    return job.summary()


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str, since: int = 0, user: User = Me):
    job = _job(job_id, user)

    async def stream():
        seq = since
        idle = 0
        while True:
            events = job.since(seq)
            for ev in events:
                yield f"data: {json.dumps(ev, default=str)}\n\n"
            seq += len(events)
            if job.status != "running" and seq >= len(job.events):
                break
            idle = 0 if events else idle + 1
            if idle and idle % 40 == 0:
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.25)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------- data
@app.get("/api/stats")
def stats(user: User = Me):
    with new_session() as s:
        email_rows = dict(s.execute(
            select(EmailOutreach.status, func.count()).join(Contact).where(Contact.user_id == user.id)
            .group_by(EmailOutreach.status)).all())
        mine = select(func.count()).select_from(Contact).where(Contact.user_id == user.id)
        return {
            "posts": s.scalar(select(func.count()).select_from(Post).where(Post.user_id == user.id)),
            "contacts": s.scalar(mine),
            "with_email": s.scalar(mine.where(Contact.email.is_not(None))),
            "with_phone": s.scalar(mine.where(Contact.phone.is_not(None))),
            "emails": {st.value: email_rows.get(st, 0) for st in EmailStatus},
        }


@app.get("/api/posts")
def list_posts(q: str | None = Query(None, max_length=200), run_id: int | None = None,
               limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
               user: User = Me):
    with new_session() as s:
        stmt = select(Post).where(Post.user_id == user.id).order_by(Post.id.desc())
        if run_id:
            stmt = stmt.where(Post.run_id == run_id)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(or_(Post.description.ilike(like), Post.author_name.ilike(like),
                                  Post.hiring_for.ilike(like)))
        total = s.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = s.scalars(stmt.limit(min(limit, 500)).offset(offset)).all()
        return {"total": total, "items": [{
            "id": p.id, "author": p.author_name, "author_url": p.author_profile_url, "url": p.url,
            "hiring_for": p.hiring_for, "contact_name": p.contact_name, "emails": p.emails, "phones": p.phones,
            "hashtags": p.matched_hashtags, "posted_at": _iso(p.posted_at), "scraped_at": _iso(p.scraped_at),
            "run_id": p.run_id, "text": p.description,
        } for p in rows]}


def _contacts_query(user_id: int, q: str | None):
    stmt = (select(Contact, EmailOutreach, Post)
            .outerjoin(EmailOutreach, EmailOutreach.contact_id == Contact.id)
            .outerjoin(Post, Post.id == Contact.first_seen_post_id)
            .where(Contact.user_id == user_id)
            .order_by(Contact.id.desc()))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Contact.name.ilike(like), Contact.email.ilike(like), Contact.phone.ilike(like),
                              Post.hiring_for.ilike(like)))
    return stmt


@app.get("/api/contacts")
def list_contacts(q: str | None = Query(None, max_length=200), limit: int = Query(200, ge=1, le=1000),
                  offset: int = Query(0, ge=0), user: User = Me):
    with new_session() as s:
        stmt = _contacts_query(user.id, q)
        total = s.scalar(select(func.count()).select_from(stmt.subquery()))
        post_counts = dict(s.execute(
            select(ContactPost.contact_id, func.count()).join(Contact, Contact.id == ContactPost.contact_id)
            .where(Contact.user_id == user.id).group_by(ContactPost.contact_id)).all())
        items = []
        for c, o, p in s.execute(stmt.limit(min(limit, 1000)).offset(offset)).all():
            items.append({
                "id": c.id, "name": c.name, "email": c.email, "phone": c.phone,
                "hiring_for": p.hiring_for if p else None, "author_url": p.author_profile_url if p else None,
                "posts": post_counts.get(c.id, 0), "created_at": _iso(c.created_at),
                "email_status": o.status.value if o else None, "sent_at": _iso(o.sent_at) if o else None,
            })
        return {"total": total, "items": items}


@app.get("/api/contacts.csv")
def export_contacts(user: User = Me):
    with new_session() as s:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "name", "email", "phone", "hiring_for", "email_status", "created_at"])
        for c, o, p in s.execute(_contacts_query(user.id, None)).all():
            w.writerow([c.id, c.name, c.email, c.phone, p.hiring_for if p else "", o.status.value if o else "",
                        _iso(c.created_at)])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=contacts.csv"})


XLSX_COLUMNS = ("SNo", "Name", "Email", "Title", "Company")
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _run_contacts_query(user_id: int, run_id: int):
    """(contact, post) for every contact found in one scrape run, with the run's post they came from."""
    return (select(Contact, Post)
            .join(ContactPost, ContactPost.contact_id == Contact.id)
            .join(Post, Post.id == ContactPost.post_id)
            .where(Contact.user_id == user_id, Post.user_id == user_id, Post.run_id == run_id)
            .order_by(Contact.id, Post.id))


@app.get("/api/contacts.xlsx")
def export_contacts_xlsx(run_id: int | None = Query(None, ge=1), user: User = Me):
    """Excel sheet: SNo, Name, Email, Title, Company. Anything not found is left blank.
    With `run_id`, only the contacts found in that scrape run."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    from jobscout.extract.rules import find_company, find_title

    wb = Workbook()
    ws = wb.active
    ws.title = "Contacts"
    ws.append(XLSX_COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.freeze_panes = "A2"
    with new_session() as s:
        if run_id is None:
            rows = [(c, p) for c, _o, p in s.execute(_contacts_query(user.id, None)).all()]
        else:
            if not s.scalar(select(ScrapeRun.id).where(ScrapeRun.id == run_id, ScrapeRun.user_id == user.id)):
                raise HTTPException(404, "Search not found.")
            first: dict[int, tuple] = {}  # one row per contact, using its first post in the run
            for c, p in s.execute(_run_contacts_query(user.id, run_id)).all():
                first.setdefault(c.id, (c, p))
            rows = list(first.values())
        for n, (c, p) in enumerate(rows, start=1):
            title = company = None
            if p is not None:
                title = find_title(p.description or "") or ((p.hiring_for or "").split(" | ")[0] or None)
                company = find_company(p.description or "", p.author_name, p.author_profile_url)
            ws.append([n, c.name, c.email, title, company])  # None -> empty cell
    for col, width in zip("ABCDE", (6, 28, 34, 40, 30)):
        ws.column_dimensions[col].width = width
    buf = io.BytesIO()
    wb.save(buf)
    name = f"contacts-run-{run_id}.xlsx" if run_id else "contacts.xlsx"
    return Response(buf.getvalue(), media_type=XLSX_TYPE,
                    headers={"Content-Disposition": f"attachment; filename={name}"})


@app.get("/api/runs")
def list_runs(limit: int = Query(20, ge=1, le=200), user: User = Me):
    with new_session() as s:
        return [{"id": r.id, "hashtags": r.hashtags, "date_filter": r.date_filter, "limit": r.requested_limit,
                 "scanned": r.posts_scanned, "saved": r.posts_saved, "status": r.status.value, "error": r.error,
                 "started_at": _iso(r.started_at), "finished_at": _iso(r.finished_at)}
                for r in s.scalars(select(ScrapeRun).where(ScrapeRun.user_id == user.id)
                                   .order_by(ScrapeRun.id.desc()).limit(limit))]


@app.get("/api/health")
def health():
    return {"ok": True}

