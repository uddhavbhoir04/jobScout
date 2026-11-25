"""Auto apply: apply_settings, applications, scrape_runs.kind

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-25
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

STATUSES = ("applied", "dry_run", "needs_you", "skipped", "failed")


def upgrade() -> None:
    op.add_column("scrape_runs", sa.Column("kind", sa.Text, nullable=False, server_default="scrape"))
    op.create_table(
        "apply_settings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("answers", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("learned", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("daily_cap", sa.Integer, nullable=False, server_default=sa.text("25")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    status = postgresql.ENUM(*STATUSES, name="apply_status")
    status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "applications",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), index=True),
        sa.Column("platform", postgresql.ENUM(name="platform", create_type=False), nullable=False),
        sa.Column("external_id", sa.Text, nullable=False),
        sa.Column("url", sa.Text),
        sa.Column("title", sa.Text),
        sa.Column("company", sa.Text),
        sa.Column("location", sa.Text),
        sa.Column("status", postgresql.ENUM(name="apply_status", create_type=False), nullable=False),
        sa.Column("reason", sa.Text),
        sa.Column("questions", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("run_id", sa.Integer, sa.ForeignKey("scrape_runs.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "platform", "external_id", name="uq_applications_user_platform_external_id"),
    )
    op.create_index("ix_applications_user_created", "applications", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_table("applications")
    postgresql.ENUM(name="apply_status").drop(op.get_bind(), checkfirst=True)
    op.drop_table("apply_settings")
    op.drop_column("scrape_runs", "kind")
