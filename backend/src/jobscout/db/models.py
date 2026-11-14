import enum
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Platform(str, enum.Enum):
    linkedin = "linkedin"
    indeed = "indeed"
    wellfound = "wellfound"
    telegram = "telegram"  # public channel web previews (t.me/s/<channel>); no account needed


class RunStatus(str, enum.Enum):
    running = "running"
    completed = "completed"
    failed = "failed"


class EmailStatus(str, enum.Enum):
    pending = "pending"      # contact has an email, no draft yet
    drafted = "drafted"      # subject/body ready, waiting to be sent
    sending = "sending"      # claimed by the send worker
    sent = "sent"
    failed = "failed"        # gave up after MAX_SEND_ATTEMPTS
    bounced = "bounced"
    replied = "replied"
    skipped = "skipped"      # no email address (phone/name only) or opted out


def _pg_enum(e: type[enum.Enum], name: str) -> SAEnum:
    return SAEnum(e, name=name, values_callable=lambda x: [m.value for m in x])


class Base(DeclarativeBase):
    pass


class User(Base):
    """A person using jobscout. Everything they scrape is stored under their id."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)  # stored lower-case
    name: Mapped[str | None] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text)
    # Plan / role: paid users get the features that call paid APIs (AI email writing + sending).
    is_paid: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserSession(Base):
    """Login session; the browser holds the token in an httpOnly cookie, we store only its hash."""

    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EmailSettings(Base):
    """Per-user outreach setup: the Gmail account emails are sent from, plus what the AI writes about them."""

    __tablename__ = "email_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    gmail_address: Mapped[str | None] = mapped_column(String(320))
    app_password_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    sender_name: Mapped[str | None] = mapped_column(Text)
    daily_cap: Mapped[int] = mapped_column(Integer, default=30, server_default=text("30"))
    profile_text: Mapped[str | None] = mapped_column(Text)
    resume_filename: Mapped[str | None] = mapped_column(Text)
    resume_path: Mapped[str | None] = mapped_column(Text)
    resume_text: Mapped[str | None] = mapped_column(Text)  # extracted on upload; fed to the AI
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


def _owner() -> Mapped[int | None]:
    return mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "platform", "login_email", name="uq_accounts_user_platform_email"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = _owner()
    platform: Mapped[Platform] = mapped_column(_pg_enum(Platform, "platform"))
    login_email: Mapped[str] = mapped_column(String(320))
    password_enc: Mapped[bytes] = mapped_column(LargeBinary)
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TelegramChannel(Base):
    """A public Telegram job channel a user searches. Quality numbers come from the last check."""
    __tablename__ = "telegram_channels"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_telegram_channels_user_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = _owner()
    name: Mapped[str] = mapped_column(Text)                      # lower-case username, e.g. "itreferral_jobs"
    title: Mapped[str | None] = mapped_column(Text)
    subscribers: Mapped[str | None] = mapped_column(Text)        # as Telegram shows it, e.g. "18.7K subscribers"
    posts_checked: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    contact_pct: Mapped[int | None] = mapped_column(Integer)     # % of recent posts with an email or phone
    posts_per_day: Mapped[str | None] = mapped_column(Text)
    last_post_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"
    __table_args__ = (
        CheckConstraint("requested_limit BETWEEN 1 AND 100", name="ck_scrape_runs_limit"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = _owner()
    platform: Mapped[Platform] = mapped_column(_pg_enum(Platform, "platform"))
    account_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), server_default=text("'{}'"))
    hashtags: Mapped[list[str]] = mapped_column(ARRAY(Text))
    date_filter: Mapped[str] = mapped_column(Text)
    requested_limit: Mapped[int] = mapped_column(Integer)
    posts_scanned: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    posts_saved: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    status: Mapped[RunStatus] = mapped_column(
        _pg_enum(RunStatus, "run_status"), default=RunStatus.running, server_default="running"
    )
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        UniqueConstraint("user_id", "platform", "external_id", name="uq_posts_user_platform_external_id"),
        Index("ix_posts_posted_at", "posted_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = _owner()
    platform: Mapped[Platform] = mapped_column(_pg_enum(Platform, "platform"))
    external_id: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    author_name: Mapped[str | None] = mapped_column(Text)
    author_profile_url: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    hiring_for: Mapped[str | None] = mapped_column(Text)
    contact_name: Mapped[str | None] = mapped_column(Text)
    emails: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    phones: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    matched_hashtags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("scrape_runs.id", ondelete="SET NULL"))
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Contact(Base):
    """One row per HR / recruiter. Per user, email and phone are each unique when present."""

    __tablename__ = "contacts"
    __table_args__ = (
        Index("uq_contacts_user_email", "user_id", "email", unique=True, postgresql_where=text("email IS NOT NULL")),
        Index("uq_contacts_user_phone", "user_id", "phone", unique=True, postgresql_where=text("phone IS NOT NULL")),
        CheckConstraint("email = lower(email)", name="ck_contacts_email_lower"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = _owner()
    name: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)  # E.164, e.g. +919876543210
    first_seen_post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    outreach: Mapped["EmailOutreach | None"] = relationship(back_populates="contact", uselist=False)


class ContactPost(Base):
    __tablename__ = "contact_posts"

    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True)


class EmailOutreach(Base):
    __tablename__ = "email_outreach"
    __table_args__ = (Index("ix_email_outreach_status_scheduled", "status", "scheduled_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), unique=True
    )
    post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id", ondelete="SET NULL"))
    subject: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    status: Mapped[EmailStatus] = mapped_column(
        _pg_enum(EmailStatus, "email_status"), default=EmailStatus.pending, server_default="pending"
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    smtp_message_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    contact: Mapped[Contact] = relationship(back_populates="outreach")
    post: Mapped[Post | None] = relationship()
