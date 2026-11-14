"""users.is_paid: paid vs free plan (paid unlocks AI email outreach)

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-14
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("is_paid", sa.Boolean, nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    op.drop_column("users", "is_paid")
