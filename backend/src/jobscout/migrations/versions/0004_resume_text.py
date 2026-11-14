"""store extracted resume text for the AI email writer

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-14
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("email_settings", sa.Column("resume_text", sa.Text))


def downgrade() -> None:
    op.drop_column("email_settings", "resume_text")
