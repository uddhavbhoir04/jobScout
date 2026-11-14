"""Who sends the emails, resolved per user (web UI settings) with an optional .env fallback (CLI)."""
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from jobscout.config import get_settings
from jobscout.db.models import EmailSettings
from jobscout.mailer.resume import extract_text
from jobscout.security.crypto import decrypt


class SenderNotConfigured(RuntimeError):
    pass


@dataclass
class SenderConfig:
    gmail: str
    app_password: str
    sender_name: str
    daily_cap: int
    profile: str
    resume_path: str | None
    resume_text: str = ""

    @property
    def display_name(self) -> str:
        return self.sender_name or self.gmail.split("@")[0]


DEFAULT_DAILY_CAP = 30


def get_or_create_settings(session: Session, user_id: int) -> EmailSettings:
    """Safe when two requests create the row at the same moment (INSERT ... ON CONFLICT DO NOTHING)."""
    row = session.scalar(select(EmailSettings).where(EmailSettings.user_id == user_id))
    if row is None:
        session.execute(
            pg_insert(EmailSettings).values(user_id=user_id, daily_cap=DEFAULT_DAILY_CAP)
            .on_conflict_do_nothing(index_elements=["user_id"])
        )
        row = session.scalar(select(EmailSettings).where(EmailSettings.user_id == user_id))
    return row


def daily_cap_for(session: Session, user_id: int) -> int:
    cap = session.scalar(select(EmailSettings.daily_cap).where(EmailSettings.user_id == user_id))
    return cap or DEFAULT_DAILY_CAP


def load_sender(session: Session, user_id: int | None, env_fallback: bool = False,
                require_password: bool = True) -> SenderConfig:
    """The user's saved sender. With env_fallback (CLI), fall back to GMAIL_* values in .env."""
    row = session.scalar(select(EmailSettings).where(EmailSettings.user_id == user_id)) if user_id else None
    if row and row.gmail_address and (row.app_password_enc or not require_password):
        resume = row.resume_path if row.resume_path and Path(row.resume_path).is_file() else None
        return SenderConfig(
            gmail=row.gmail_address,
            app_password=decrypt(row.app_password_enc) if row.app_password_enc else "",
            sender_name=row.sender_name or "",
            daily_cap=row.daily_cap,
            profile=row.profile_text or "",
            resume_path=resume,
            resume_text=_resume_text(session, row),
        )
    s = get_settings()
    if env_fallback and s.gmail_user and s.gmail_app_password:
        return SenderConfig(
            gmail=s.gmail_user, app_password=s.gmail_app_password, sender_name=s.sender_name,
            daily_cap=s.daily_email_cap, profile=(row.profile_text if row and row.profile_text else s.profile_text()),
            resume_path=s.resume_path if s.resume_path and Path(s.resume_path).is_file() else None,
            resume_text=(_resume_text(session, row) if row and row.resume_path
                         else extract_text(s.resume_path) if s.resume_path else ""),
        )
    raise SenderNotConfigured("Connect your Gmail first (Emails page → Sender).")


def _resume_text(session: Session, row: EmailSettings) -> str:
    """Stored resume text; extracted (and saved) on first use for resumes uploaded before this existed."""
    if row.resume_text:
        return row.resume_text
    if row.resume_path and Path(row.resume_path).is_file():
        row.resume_text = extract_text(row.resume_path) or None
        session.flush()
        return row.resume_text or ""
    return ""


@dataclass
class WriterProfile:
    """What the AI needs to write emails for a user (no Gmail password required)."""

    sender_name: str
    profile: str
    has_resume: bool
    resume_text: str


def profile_for(session: Session, user_id: int | None, env_fallback: bool = False) -> WriterProfile:
    try:
        cfg = load_sender(session, user_id, env_fallback=env_fallback, require_password=False)
        return WriterProfile(cfg.display_name, cfg.profile, bool(cfg.resume_path), cfg.resume_text)
    except SenderNotConfigured:
        row = session.scalar(select(EmailSettings).where(EmailSettings.user_id == user_id)) if user_id else None
        if row is None:
            return WriterProfile("", "", False, "")
        has_resume = bool(row.resume_path and Path(row.resume_path).is_file())
        return WriterProfile(row.sender_name or "", row.profile_text or "", has_resume, _resume_text(session, row))
