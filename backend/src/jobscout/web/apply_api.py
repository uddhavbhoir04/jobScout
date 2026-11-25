"""Auto apply: the answers sheet + daily cap, and the list of applications.
Starting a run is POST /api/apply in web/app.py (it shares the browser-job bookkeeping with scraping)."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from jobscout.db.models import Application, ApplyStatus, EmailSettings, Platform, User
from jobscout.db.session import new_session
from jobscout.pipeline.apply import SITES, applied_today, get_or_create_apply_settings
from jobscout.web.auth import current_user
from jobscout.web.email_api import ResumeIn, store_resume

router = APIRouter(prefix="/api", tags=["apply"])
Me = Depends(current_user)
MAX_LEARNED = 500


def _iso(dt):
    return dt.isoformat() if dt else None


class CustomQA(BaseModel):
    q: str = Field(min_length=1, max_length=300)
    a: str = Field(min_length=1, max_length=1000)


class AnswersIn(BaseModel):
    """The answers sheet. Every field is optional: what's missing is asked of the AI (paid plan) or
    makes a job 'needs you'."""
    notice_period_days: int | None = Field(default=None, ge=0, le=365)
    current_ctc: str | None = Field(default=None, max_length=60)
    expected_ctc: str | None = Field(default=None, max_length=60)
    total_experience_years: float | None = Field(default=None, ge=0, le=60)
    skills_experience: dict[str, float] = Field(default_factory=dict, max_length=60)
    relocate: bool | None = None
    authorized_to_work: bool | None = None
    needs_sponsorship: bool | None = None
    phone: str | None = Field(default=None, max_length=30)
    city: str | None = Field(default=None, max_length=80)
    linkedin_url: str | None = Field(default=None, max_length=300)
    portfolio_url: str | None = Field(default=None, max_length=300)
    custom: list[CustomQA] = Field(default_factory=list, max_length=50)


class ApplySettingsIn(BaseModel):
    answers: AnswersIn | None = None
    learned: dict[str, str] | None = None        # edit / delete learned answers (replaces the whole set)
    daily_cap: int | None = Field(default=None, ge=1, le=50)


def _settings_dict(row, user_id: int, s) -> dict:
    es = s.scalar(select(EmailSettings).where(EmailSettings.user_id == user_id))
    return {
        "answers": row.answers or {}, "learned": row.learned or {}, "daily_cap": row.daily_cap,
        "applied_today": {p.value: applied_today(s, user_id, p) for p in SITES},
        "resume_filename": es.resume_filename if es else None,
        "resume_chars": len(es.resume_text or "") if es else 0,
    }


@router.post("/apply/resume")
def upload_apply_resume(body: ResumeIn, user: User = Me):
    """Your CV for auto apply (all plans): its text answers screening questions, the file fills upload fields."""
    s, _ = store_resume(user.id, body)
    with s:
        row = get_or_create_apply_settings(s, user.id)
        s.commit()
        return _settings_dict(row, user.id, s)


@router.get("/apply/settings")
def get_apply_settings(user: User = Me):
    with new_session() as s:
        row = get_or_create_apply_settings(s, user.id)
        s.commit()
        return _settings_dict(row, user.id, s)


@router.put("/apply/settings")
def save_apply_settings(body: ApplySettingsIn, user: User = Me):
    with new_session() as s:
        row = get_or_create_apply_settings(s, user.id)
        if body.answers is not None:
            a = body.answers.model_dump(mode="json")
            a["skills_experience"] = {k.strip().lower(): v for k, v in a["skills_experience"].items() if k.strip()}
            for k in ("current_ctc", "expected_ctc", "phone", "city", "linkedin_url", "portfolio_url"):
                a[k] = (a[k] or "").strip() or None
            row.answers = a
        if body.learned is not None:
            if len(body.learned) > MAX_LEARNED:
                raise HTTPException(422, f"At most {MAX_LEARNED} learned answers.")
            row.learned = {k: v.strip() for k, v in body.learned.items() if k.strip() and v.strip()}
        if body.daily_cap is not None:
            row.daily_cap = body.daily_cap
        s.commit()
        return _settings_dict(row, user.id, s)


def _app_dict(a: Application) -> dict:
    return {"id": a.id, "platform": a.platform.value, "external_id": a.external_id, "url": a.url, "title": a.title,
            "company": a.company, "location": a.location, "status": a.status.value, "reason": a.reason,
            "questions": a.questions or [], "run_id": a.run_id, "created_at": _iso(a.created_at),
            "updated_at": _iso(a.updated_at)}


@router.get("/applications")
def list_applications(status: ApplyStatus | None = None, platform: Literal["linkedin", "naukri", "indeed"] | None = None,
                      limit: int = Query(200, ge=1, le=1000), user: User = Me):
    with new_session() as s:
        q = select(Application).where(Application.user_id == user.id)
        if status:
            q = q.where(Application.status == status)
        if platform:
            q = q.where(Application.platform == Platform(platform))
        total = s.scalar(select(func.count()).select_from(q.subquery()))
        rows = s.scalars(q.order_by(Application.updated_at.desc(), Application.id.desc()).limit(limit)).all()
        return {"total": total, "items": [_app_dict(a) for a in rows]}


class ApplicationPatch(BaseModel):
    status: Literal["applied", "skipped"]   # "I applied by hand" / "not interested"


@router.patch("/applications/{app_id}")
def update_application(app_id: int, body: ApplicationPatch, user: User = Me):
    with new_session() as s:
        a = s.get(Application, app_id)
        if a is None or a.user_id != user.id:
            raise HTTPException(404, "Application not found.")
        a.status = ApplyStatus(body.status)
        a.reason = "marked by you"
        s.commit()
        return _app_dict(a)
