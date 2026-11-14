"""Draft and send outreach emails for one user, tracking status in email_outreach."""
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import joinedload

from jobscout.config import get_settings
from jobscout.db.models import Contact, EmailOutreach, EmailStatus
from jobscout.db.session import new_session
from jobscout.extract.ai import Gemini
from jobscout.extract.dates import now
from jobscout.mailer.composer import compose
from jobscout.mailer.sender_config import load_sender, profile_for
from jobscout.mailer.smtp import AuthFailed, ConnectionBlocked, GmailSender, PermanentSendError

log = logging.getLogger(__name__)
STALE_SENDING = timedelta(minutes=30)
RETRY_BACKOFF = timedelta(minutes=15)


@dataclass
class SendResult:
    sent: int = 0
    failed: int = 0
    retry_later: int = 0
    previews: list[tuple[str, str, str]] = field(default_factory=list)  # (to, subject, body)
    budget: int = 0
    sent_today: int = 0
    daily_cap: int = 0
    stopped: bool = False


def _mine(stmt, user_id: int | None):
    """Limit an EmailOutreach query (already joined to Contact) to one user's contacts."""
    return stmt.where(Contact.user_id == user_id) if user_id is not None else stmt


def draft_pending(limit: int = 50, on_item=None, user_id: int | None = None, ids: list[int] | None = None,
                  env_fallback: bool = False, should_stop=None) -> dict[str, int]:
    """Write subject/body for 'pending' rows (or re-write the given ids) and mark them 'drafted'."""
    counts = {"ai": 0, "template": 0}
    with new_session() as session:
        writer = profile_for(session, user_id, env_fallback)
        session.commit()  # keeps resume text extracted on first use
        ai = Gemini()
        stmt = (select(EmailOutreach).join(Contact)
                .options(joinedload(EmailOutreach.contact), joinedload(EmailOutreach.post))
                .where(Contact.email.is_not(None)))
        if ids:
            stmt = stmt.where(EmailOutreach.id.in_(ids),
                              EmailOutreach.status.in_([EmailStatus.pending, EmailStatus.drafted,
                                                        EmailStatus.failed, EmailStatus.skipped]))
        else:
            stmt = stmt.where(EmailOutreach.status == EmailStatus.pending)
        rows = session.scalars(_mine(stmt, user_id).order_by(EmailOutreach.id).limit(limit)).all()
        for row in rows:
            if should_stop and should_stop():
                break
            draft, source = compose(ai, row.contact, row.post, sender=writer.sender_name, profile=writer.profile,
                                    has_resume=writer.has_resume, resume_text=writer.resume_text)
            row.subject, row.body = draft.subject, draft.body
            row.status = EmailStatus.drafted
            row.attempts, row.scheduled_at = 0, None
            session.commit()
            counts[source] += 1
            if on_item:
                on_item(row, source)
    return counts


def _release_stale(session) -> None:
    session.execute(
        update(EmailOutreach)
        .where(EmailOutreach.status == EmailStatus.sending, EmailOutreach.updated_at < now() - STALE_SENDING)
        .values(status=EmailStatus.drafted)
    )
    session.commit()


def sent_today(session, user_id: int | None = None) -> int:
    """Emails this user sent today (each user sends from their own Gmail, with their own daily cap)."""
    midnight = now().replace(hour=0, minute=0, second=0, microsecond=0)
    return session.scalar(_mine(
        select(func.count()).select_from(EmailOutreach).join(Contact)
        .where(EmailOutreach.status == EmailStatus.sent, EmailOutreach.sent_at >= midnight),
        user_id,
    )) or 0


def _due_query(user_id: int | None = None, ids: list[int] | None = None):
    stmt = (select(EmailOutreach).join(Contact)
            .where(EmailOutreach.status == EmailStatus.drafted, Contact.email.is_not(None)))
    if ids:
        stmt = stmt.where(EmailOutreach.id.in_(ids))  # explicit "send now": ignore retry schedule
    else:
        stmt = stmt.where(or_(EmailOutreach.scheduled_at.is_(None), EmailOutreach.scheduled_at <= now()))
    return _mine(stmt, user_id).order_by(EmailOutreach.id)


def _sleep(seconds: float, should_stop) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if should_stop and should_stop():
            return
        time.sleep(min(1.0, end - time.monotonic()))


def send_drafted(limit: int = 20, dry_run: bool = False, on_item=None, user_id: int | None = None,
                 ids: list[int] | None = None, env_fallback: bool = False, should_stop=None) -> SendResult:
    s = get_settings()
    result = SendResult()
    with new_session() as session:
        _release_stale(session)
        cfg = load_sender(session, user_id, env_fallback=env_fallback, require_password=not dry_run)
        result.daily_cap = cfg.daily_cap
        result.sent_today = sent_today(session, user_id)
        result.budget = max(0, min(limit, cfg.daily_cap - result.sent_today))
        if result.budget == 0:
            return result

        if dry_run:
            rows = session.scalars(
                _due_query(user_id, ids).options(joinedload(EmailOutreach.contact)).limit(result.budget)
            ).all()
            result.previews = [(r.contact.email, r.subject or "", r.body or "") for r in rows]
            return result

        with GmailSender(cfg) as sender:
            for i in range(result.budget):
                if should_stop and should_stop():
                    result.stopped = True
                    break
                row = session.scalars(
                    _due_query(user_id, ids).limit(1).with_for_update(skip_locked=True, of=EmailOutreach)
                ).first()
                if row is None:
                    break
                row.status = EmailStatus.sending
                row.attempts += 1
                session.commit()
                to = row.contact.email
                try:
                    row.smtp_message_id = sender.send(to, row.subject or "", row.body or "")
                    row.status, row.sent_at, row.last_error = EmailStatus.sent, now(), None
                    result.sent += 1
                    outcome = "sent"
                except PermanentSendError as e:
                    row.status, row.last_error = EmailStatus.failed, f"rejected: {e}"[:1000]
                    result.failed += 1
                    outcome = "failed"
                except AuthFailed:
                    row.status = EmailStatus.drafted
                    session.commit()
                    raise
                except Exception as e:
                    row.last_error = f"{type(e).__name__}: {e}"[:1000]
                    if row.attempts >= s.max_send_attempts:
                        row.status = EmailStatus.failed
                        result.failed += 1
                        outcome = "failed"
                    else:
                        row.status = EmailStatus.drafted
                        row.scheduled_at = now() + RETRY_BACKOFF * row.attempts
                        result.retry_later += 1
                        outcome = "retry"
                session.commit()
                if on_item:
                    on_item(row, outcome)
                planned = min(result.budget, len(ids)) if ids else result.budget
                if i < planned - 1:  # pause between emails, not after the last one
                    _sleep(random.uniform(s.email_min_delay, s.email_max_delay), should_stop)
    return result


def stats(user_id: int | None = None) -> dict[str, int]:
    with new_session() as session:
        rows = session.execute(_mine(
            select(EmailOutreach.status, func.count()).select_from(EmailOutreach).join(Contact), user_id,
        ).group_by(EmailOutreach.status)).all()
        out = {status.value: 0 for status in EmailStatus}
        out.update({st.value: n for st, n in rows})
        out["sent_today"] = sent_today(session, user_id)
        return out


def mark(outreach_id: int, status: EmailStatus, reason: str | None = None, user_id: int | None = None) -> None:
    with new_session() as session:
        row = session.get(EmailOutreach, outreach_id)
        if row is None or (user_id is not None and row.contact.user_id != user_id):
            raise ValueError(f"No email_outreach row with id {outreach_id}")
        row.status = status
        if reason:
            row.last_error = reason
        if status == EmailStatus.drafted:
            row.scheduled_at = None
        session.commit()
