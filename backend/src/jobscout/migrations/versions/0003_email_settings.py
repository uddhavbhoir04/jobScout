"""per-user email sender settings (Gmail + App Password), profile text and resume

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-13
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_settings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("gmail_address", sa.String(320)),
        sa.Column("app_password_enc", sa.LargeBinary),
        sa.Column("sender_name", sa.Text),
        sa.Column("daily_cap", sa.Integer, nullable=False, server_default=sa.text("30")),
        sa.Column("profile_text", sa.Text),
        sa.Column("resume_filename", sa.Text),
        sa.Column("resume_path", sa.Text),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("email_settings")
