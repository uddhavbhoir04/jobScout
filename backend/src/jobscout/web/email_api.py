"""Email outreach API: sender settings (Gmail + App Password), drafts, sending."""
import base64
import re
import smtplib
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from jobscout.config import get_settings
from jobscout.db.models import Contact, EmailOutreach, EmailStatus, Post, User
from jobscout.db.session import new_session
from jobscout.extract.dates import now
from jobscout.mailer import worker
from jobscout.mailer.resume import extract_text
from jobscout.mailer.sender_config import (
    SenderNotConfigured,
    daily_cap_for,
    get_or_create_settings,
    load_sender,
)
from jobscout.mailer.smtp import AuthFailed, ConnectionBlocked, GmailSender
from jobscout.security.crypto import encrypt
from jobscout.web.auth import paid_user
from jobscout.web.jobs import Job, manager

router = APIRouter(prefix="/api", tags=["email"])
Me = Depends(paid_user)  # RBAC: the whole email module is paid-only
EMAIL_JOBS = ("draft", "send")
MAX_RESUME_BYTES = 5 * 1024 * 1024
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _iso(dt):
    return dt.isoformat() if dt else None


# ------------------------------------------------------------------ sender settings
class SettingsIn(BaseModel):
    gmail_address: str | None = Field(default=None, max_length=320)
    app_password: str | None = Field(default=None, max_length=100)  # omitted/empty = keep current
    sender_name: str | None = Field(default=None, max_length=120)
    daily_cap: int | None = Field(default=None, ge=1, le=200)
    profile_text: str | None = Field(default=None, max_length=8000)


def _settings_dict(row) -> dict:
    return {
        "gmail_address": row.gmail_address,
        "has_app_password": bool(row.app_password_enc),
        "sender_name": row.sender_name,
        "daily_cap": row.daily_cap,
        "profile_text": row.profile_text or "",
        "resume_filename": row.resume_filename,
        "resume_text_chars": len(row.resume_text or ""),
        "verified_at": _iso(row.verified_at),
        "last_error": row.last_error,
        "connected": bool(row.gmail_address and row.app_password_enc),
    }


@router.get("/email/settings")
def get_email_settings(user: User = Me):
    with new_session() as s:
        row = get_or_create_settings(s, user.id)
        s.commit()
        return _settings_dict(row)


@router.put("/email/settings")
def save_email_settings(body: SettingsIn, user: User = Me):
    with new_session() as s:
        row = get_or_create_settings(s, user.id)
        if body.gmail_address is not None:
            addr = body.gmail_address.strip().lower()
            if addr and not _EMAIL_RE.match(addr):
                raise HTTPException(422, "Enter a valid email address.")
            if addr != (row.gmail_address or ""):
                row.verified_at = None
            row.gmail_address = addr or None
        if body.app_password:
            pw = body.app_password.replace(" ", "")
            if len(pw) < 8:
                raise HTTPException(422, "That doesn't look like a Gmail App Password (16 letters).")
            row.app_password_enc = encrypt(pw)
            row.verified_at = None
        if body.sender_name is not None:
            row.sender_name = body.sender_name.strip() or None
        if body.daily_cap is not None:
            row.daily_cap = body.daily_cap
        if body.profile_text is not None:
            row.profile_text = body.profile_text.strip() or None
        s.commit()
        return _settings_dict(row)


@router.delete("/email/settings/password", status_code=204)
def disconnect_gmail(user: User = Me):
    with new_session() as s:
        row = get_or_create_settings(s, user.id)
        row.app_password_enc = None
        row.verified_at = None
        s.commit()


class ResumeIn(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    content_base64: str


def store_resume(user_id: int, body: "ResumeIn"):
    """Save the CV file and its text (shared by the Emails page and Auto apply). Returns the settings row."""
    name = Path(body.filename).name
    if not name.lower().endswith((".pdf", ".doc", ".docx")):
        raise HTTPException(422, "Upload a PDF or Word file.")
    try:
        data = base64.b64decode(body.content_base64, validate=True)
    except ValueError:
        raise HTTPException(422, "Could not read the file.")
    if not data or len(data) > MAX_RESUME_BYTES:
        raise HTTPException(422, "Resume must be under 5 MB.")
    folder = get_settings().data_dir / "resumes" / f"user_{user_id}"
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.iterdir():
        old.unlink()
    safe = re.sub(r"[^\w.\- ]", "_", name)
    path = folder / safe
    path.write_bytes(data)
    s = new_session()
    row = get_or_create_settings(s, user_id)
    row.resume_filename, row.resume_path = safe, str(path)
    row.resume_text = extract_text(path) or None
    s.commit()
    return s, row


@router.post("/email/settings/resume")
def upload_resume(body: ResumeIn, user: User = Me):
    s, row = store_resume(user.id, body)
    with s:
        return _settings_dict(row)


@router.delete("/email/settings/resume")
def delete_resume(user: User = Me):
    with new_session() as s:
        row = get_or_create_settings(s, user.id)
        if row.resume_path and Path(row.resume_path).is_file():
            Path(row.resume_path).unlink()
        row.resume_filename = row.resume_path = row.resume_text = None
        s.commit()
        return _settings_dict(row)


class TestIn(BaseModel):
    send_to_self: bool = False


@router.post("/email/test")
def test_gmail(body: TestIn, user: User = Me):
    """Log in to Gmail with the saved App Password; optionally send a test email to yourself."""
    with new_session() as s:
        row = get_or_create_settings(s, user.id)
        try:
            cfg = load_sender(s, user.id)
            with GmailSender(cfg) as sender:
                via = " (via port 465; port 587 is blocked on this PC)" if sender.used_fallback else ""
                if body.send_to_self:
                    sender.send(cfg.gmail, "jobscout test email",
                                "This is a test from jobscout. Your Gmail sender is connected.\n\n"
                                + (f"Your resume ({row.resume_filename}) is attached." if cfg.resume_path else
                                   "No resume uploaded yet."))
            row.verified_at, row.last_error = now(), None
            s.commit()
            msg = f"Test email sent to {cfg.gmail}" if body.send_to_self else "Gmail login works"
            return {"ok": True, "message": msg + via + "."}
        except (AuthFailed, SenderNotConfigured, ConnectionBlocked) as e:
            row.last_error = str(e)
        except (smtplib.SMTPException, OSError) as e:
            row.last_error = f"Could not reach Gmail ({type(e).__name__}: {e}). Is port 587 blocked by a firewall?"
        row.verified_at = None
        s.commit()
        return {"ok": False, "message": row.last_error}


# ------------------------------------------------------------------ outreach list / edit
def _outreach_dict(o: EmailOutreach) -> dict:
    c, p = o.contact, o.post
    return {
        "id": o.id, "status": o.status.value, "subject": o.subject, "body": o.body,
        "attempts": o.attempts, "last_error": o.last_error, "scheduled_at": _iso(o.scheduled_at),
        "sent_at": _iso(o.sent_at), "updated_at": _iso(o.updated_at),
        "contact": {"id": c.id, "name": c.name, "email": c.email, "phone": c.phone},
        "post": {"id": p.id, "hiring_for": p.hiring_for, "author": p.author_name,
                 "author_url": p.author_profile_url, "text": p.description} if p else None,
    }


@router.get("/emails")
def list_emails(status: str | None = Query(None, max_length=200), q: str | None = Query(None, max_length=200),
                limit: int = Query(200, ge=1, le=500), offset: int = Query(0, ge=0),
                user: User = Me):
    with new_session() as s:
        stmt = (select(EmailOutreach).join(Contact).outerjoin(Post, Post.id == EmailOutreach.post_id)
                .options(joinedload(EmailOutreach.contact), joinedload(EmailOutreach.post))
                .where(Contact.user_id == user.id))
        if status:
            try:
                stmt = stmt.where(EmailOutreach.status.in_([EmailStatus(x) for x in status.split(",")]))
            except ValueError:
                raise HTTPException(422, f"Unknown status {status!r}")
        if q:
            like = f"%{q}%"
            stmt = stmt.where(or_(Contact.name.ilike(like), Contact.email.ilike(like), Post.hiring_for.ilike(like),
                                  EmailOutreach.subject.ilike(like)))
        total = s.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = s.scalars(stmt.order_by(EmailOutreach.updated_at.desc(), EmailOutreach.id.desc())
                         .limit(min(limit, 500)).offset(offset)).unique().all()
        return {"total": total, "items": [_outreach_dict(o) for o in rows]}


@router.get("/email/stats")
def email_stats(user: User = Me):
    with new_session() as s:
        cap = daily_cap_for(s, user.id)
    out = worker.stats(user.id)
    out["daily_cap"] = cap
    return out


EDITABLE = {EmailStatus.pending, EmailStatus.drafted, EmailStatus.skipped, EmailStatus.failed,
            EmailStatus.replied, EmailStatus.bounced}


class OutreachPatch(BaseModel):
    subject: str | None = Field(default=None, max_length=300)
    body: str | None = Field(default=None, max_length=20000)
    status: EmailStatus | None = None


@router.patch("/emails/{outreach_id}")
def edit_email(outreach_id: int, body: OutreachPatch, user: User = Me):
    with new_session() as s:
        o = s.get(EmailOutreach, outreach_id)
        if o is None or o.contact.user_id != user.id:
            raise HTTPException(404, "email not found")
        if o.status in (EmailStatus.sending,):
            raise HTTPException(409, "This email is being sent right now.")
        if (body.subject is not None or body.body is not None) and o.status == EmailStatus.sent:
            raise HTTPException(409, "Already sent; it can't be edited.")
        if body.subject is not None:
            o.subject = body.subject.strip()
        if body.body is not None:
            o.body = body.body.rstrip()
        if body.status is not None:
            if body.status not in EDITABLE:
                raise HTTPException(422, f"Can't set status to {body.status.value}.")
            if body.status == EmailStatus.drafted and not (o.subject and o.body):
                raise HTTPException(422, "Write a subject and body first.")
            o.status = body.status
            if body.status == EmailStatus.drafted:
                o.scheduled_at, o.last_error = None, None
            if body.status == EmailStatus.skipped:
                o.last_error = o.last_error or "skipped by you"
        elif (body.subject is not None or body.body is not None) and o.status in (EmailStatus.pending, EmailStatus.failed):
            o.status = EmailStatus.drafted if (o.subject and o.body) else o.status
        s.commit()
        s.refresh(o)
        return _outreach_dict(o)


# ------------------------------------------------------------------ jobs: draft / send
class DraftIn(BaseModel):
    ids: list[int] | None = None
    limit: int = Field(50, ge=1, le=200)


class SendIn(BaseModel):
    ids: list[int] | None = None
    limit: int = Field(10, ge=1, le=200)


def _row_event(row: EmailOutreach, outcome: str, **extra) -> dict:
    return {"type": "email", "id": row.id, "outcome": outcome, "to": row.contact.email,
            "name": row.contact.name, "subject": row.subject, "error": row.last_error, **extra}


@router.post("/emails/draft")
def start_drafting(body: DraftIn, user: User = Me):
    if manager.running(EMAIL_JOBS, user_id=user.id):
        raise HTTPException(409, "An email job is already running.")

    def target(job: Job) -> None:
        job.emit({"type": "log", "level": "info", "message": "Writing drafts…"})
        counts = worker.draft_pending(body.limit, user_id=user.id, ids=body.ids,
                                      should_stop=lambda: job.stop_requested,
                                      on_item=lambda row, src: job.emit(_row_event(row, "drafted", source=src)))
        job.emit({"type": "summary", "drafted": sum(counts.values()), **counts})

    return manager.start("draft", body.model_dump(), target, user_id=user.id).summary()


@router.post("/emails/send")
def start_sending(body: SendIn, user: User = Me):
    if manager.running(EMAIL_JOBS, user_id=user.id):
        raise HTTPException(409, "An email job is already running.")
    with new_session() as s:
        try:
            load_sender(s, user.id)
        except SenderNotConfigured as e:
            raise HTTPException(409, str(e))

    def target(job: Job) -> None:
        job.emit({"type": "log", "level": "info", "message": "Connecting to Gmail…"})
        try:
            res = worker.send_drafted(body.limit, user_id=user.id, ids=body.ids,
                                      should_stop=lambda: job.stop_requested,
                                      on_item=lambda row, outcome: job.emit(_row_event(row, outcome)))
        except (AuthFailed, ConnectionBlocked) as e:
            job.emit({"type": "error", "message": str(e)})
            job.status = "error"
            return
        if res.budget == 0:
            job.emit({"type": "log", "level": "warning",
                      "message": f"Daily limit reached ({res.sent_today}/{res.daily_cap} sent today). Try tomorrow."})
        job.emit({"type": "summary", "sent": res.sent, "failed": res.failed, "retry_later": res.retry_later,
                  "sent_today": res.sent_today + res.sent, "daily_cap": res.daily_cap, "stopped": res.stopped})

    return manager.start("send", body.model_dump(), target, user_id=user.id).summary()
