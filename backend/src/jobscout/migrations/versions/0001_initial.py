"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-11-13
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

PLATFORMS = ("linkedin", "indeed", "wellfound")
RUN_STATUSES = ("running", "completed", "failed")
EMAIL_STATUSES = ("pending", "drafted", "sending", "sent", "failed", "bounced", "replied", "skipped")


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(name=name, create_type=False)


def _ts(name: str, default: bool = False) -> sa.Column:
    return sa.Column(
        name, sa.DateTime(timezone=True), nullable=not default,
        server_default=sa.func.now() if default else None,
    )


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(*PLATFORMS, name="platform").create(bind, checkfirst=True)
    postgresql.ENUM(*RUN_STATUSES, name="run_status").create(bind, checkfirst=True)
    postgresql.ENUM(*EMAIL_STATUSES, name="email_status").create(bind, checkfirst=True)

    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("platform", _enum("platform"), nullable=False),
        sa.Column("login_email", sa.String(320), nullable=False),
        sa.Column("password_enc", sa.LargeBinary, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        _ts("last_login_at"),
        sa.Column("last_status", sa.Text),
        _ts("created_at", default=True),
        sa.UniqueConstraint("platform", "login_email", name="uq_accounts_platform_email"),
    )

    op.create_table(
        "scrape_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("platform", _enum("platform"), nullable=False),
        sa.Column("account_ids", postgresql.ARRAY(sa.Integer), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("hashtags", postgresql.ARRAY(sa.Text), nullable=False),
        sa.Column("date_filter", sa.Text, nullable=False),
        sa.Column("requested_limit", sa.Integer, nullable=False),
        sa.Column("posts_scanned", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("posts_saved", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("status", _enum("run_status"), nullable=False, server_default="running"),
        sa.Column("error", sa.Text),
        _ts("started_at", default=True),
        _ts("finished_at"),
        sa.CheckConstraint("requested_limit BETWEEN 1 AND 100", name="ck_scrape_runs_limit"),
    )

    op.create_table(
        "posts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("platform", _enum("platform"), nullable=False),
        sa.Column("external_id", sa.Text, nullable=False),
        sa.Column("url", sa.Text),
        sa.Column("author_name", sa.Text),
        sa.Column("author_profile_url", sa.Text),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("hiring_for", sa.Text),
        sa.Column("contact_name", sa.Text),
        sa.Column("emails", postgresql.ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("phones", postgresql.ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("matched_hashtags", postgresql.ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'")),
        _ts("posted_at"),
        sa.Column("run_id", sa.Integer, sa.ForeignKey("scrape_runs.id", ondelete="SET NULL")),
        _ts("scraped_at", default=True),
        sa.UniqueConstraint("platform", "external_id", name="uq_posts_platform_external_id"),
    )
    op.create_index("ix_posts_posted_at", "posts", ["posted_at"])

    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text),
        sa.Column("email", sa.Text),
        sa.Column("phone", sa.Text),
        sa.Column("first_seen_post_id", sa.Integer, sa.ForeignKey("posts.id", ondelete="SET NULL")),
        _ts("created_at", default=True),
        _ts("updated_at", default=True),
        sa.CheckConstraint("email = lower(email)", name="ck_contacts_email_lower"),
    )
    op.create_index("uq_contacts_email", "contacts", ["email"], unique=True,
                    postgresql_where=sa.text("email IS NOT NULL"))
    op.create_index("uq_contacts_phone", "contacts", ["phone"], unique=True,
                    postgresql_where=sa.text("phone IS NOT NULL"))

    op.create_table(
        "contact_posts",
        sa.Column("contact_id", sa.Integer, sa.ForeignKey("contacts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("post_id", sa.Integer, sa.ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True),
    )

    op.create_table(
        "email_outreach",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("contact_id", sa.Integer, sa.ForeignKey("contacts.id", ondelete="CASCADE"),
                  nullable=False, unique=True),
        sa.Column("post_id", sa.Integer, sa.ForeignKey("posts.id", ondelete="SET NULL")),
        sa.Column("subject", sa.Text),
        sa.Column("body", sa.Text),
        sa.Column("status", _enum("email_status"), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.Text),
        _ts("scheduled_at"),
        _ts("sent_at"),
        sa.Column("smtp_message_id", sa.Text),
        _ts("created_at", default=True),
        _ts("updated_at", default=True),
    )
    op.create_index("ix_email_outreach_status_scheduled", "email_outreach", ["status", "scheduled_at"])


def downgrade() -> None:
    for t in ("email_outreach", "contact_posts", "contacts", "posts", "scrape_runs", "accounts"):
        op.drop_table(t)
    bind = op.get_bind()
    for name in ("email_status", "run_status", "platform"):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
