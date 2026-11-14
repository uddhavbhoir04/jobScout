"""Telegram as a source: 'telegram' platform value + per-user telegram_channels

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-14
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A new enum value can't be used in the transaction that adds it, so add it on its own.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE platform ADD VALUE IF NOT EXISTS 'telegram'")
    op.create_table(
        "telegram_channels",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), index=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("title", sa.Text),
        sa.Column("subscribers", sa.Text),
        sa.Column("posts_checked", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("contact_pct", sa.Integer),
        sa.Column("posts_per_day", sa.Text),
        sa.Column("last_post_at", sa.DateTime(timezone=True)),
        sa.Column("checked_at", sa.DateTime(timezone=True)),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "name", name="uq_telegram_channels_user_name"),
    )


def downgrade() -> None:
    op.drop_table("telegram_channels")
    # PostgreSQL can't drop a single enum value; 'telegram' stays in the type (harmless).
