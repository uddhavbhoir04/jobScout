"""Database writes/reads used by the scraper and mailer."""
from collections.abc import Iterable

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from jobscout.db.models import (
    Contact,
    ContactPost,
    EmailOutreach,
    EmailStatus,
    Platform,
    Post,
)


def existing_external_ids(session: Session, user_id: int, platform: Platform, ids: Iterable[str]) -> set[str]:
    ids = list(ids)
    if not ids:
        return set()
    rows = session.scalars(
        select(Post.external_id).where(Post.user_id == user_id, Post.platform == platform,
                                       Post.external_id.in_(ids))
    )
    return set(rows)


def insert_post(session: Session, **values) -> Post | None:
    """Insert a post (values must include user_id). Returns None if this user already has it."""
    stmt = (
        pg_insert(Post)
        .values(**values)
        .on_conflict_do_nothing(constraint="uq_posts_user_platform_external_id")
        .returning(Post.id)
    )
    post_id = session.execute(stmt).scalar()
    return session.get(Post, post_id) if post_id else None


def upsert_contact(
    session: Session, *, user_id: int, name: str | None, email: str | None, phone: str | None, post_id: int
) -> tuple[Contact, int]:
    """Find this user's contact by email OR phone and merge, or create a new one.

    Per user, emails and phones stay unique (partial unique indexes back this up).
    Also links the contact to the post and makes sure an outreach row exists.
    Returns (contact, number of email/phone values that were new for this user: 0, 1 or 2).
    """
    email = email.lower().strip() if email else None
    contact: Contact | None = None
    new_values = 0

    conds = []
    if email:
        conds.append(Contact.email == email)
    if phone:
        conds.append(Contact.phone == phone)

    if conds:
        matches = list(session.scalars(
            select(Contact).where(Contact.user_id == user_id, or_(*conds)).order_by(Contact.id)))
        if matches:
            contact = matches[0]
            others = matches[1:]
            if name and not contact.name:
                contact.name = name
            # Only fill a missing field if no other contact already owns that value.
            if email and not contact.email and not any(o.email == email for o in others):
                contact.email = email
                new_values += 1
            if phone and not contact.phone and not any(o.phone == phone for o in others):
                contact.phone = phone
                new_values += 1

    if contact is None:
        contact = Contact(user_id=user_id, name=name, email=email, phone=phone, first_seen_post_id=post_id)
        try:
            with session.begin_nested():
                session.add(contact)
                session.flush()
            new_values = int(bool(email)) + int(bool(phone))
        except IntegrityError:
            # Someone else inserted the same email/phone in the meantime: merge into it.
            session.expunge(contact)
            contact = session.scalars(select(Contact).where(Contact.user_id == user_id, or_(*conds))).first()
            assert contact is not None

    session.flush()
    session.execute(
        pg_insert(ContactPost)
        .values(contact_id=contact.id, post_id=post_id)
        .on_conflict_do_nothing()
    )
    ensure_outreach(session, contact, post_id)
    return contact, new_values


def ensure_outreach(session: Session, contact: Contact, post_id: int) -> None:
    outreach = session.scalars(
        select(EmailOutreach).where(EmailOutreach.contact_id == contact.id)
    ).first()
    if outreach is None:
        session.add(
            EmailOutreach(
                contact_id=contact.id,
                post_id=post_id,
                status=EmailStatus.pending if contact.email else EmailStatus.skipped,
            )
        )
    elif (
        outreach.status == EmailStatus.skipped
        and contact.email
        and outreach.sent_at is None
        and not outreach.last_error  # manual skips (e.g. opted out) carry a reason; keep them
    ):
        # We now know an email for a contact that previously had only a phone/name.
        outreach.status = EmailStatus.pending
        outreach.post_id = post_id
    session.flush()
