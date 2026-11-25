"""Naukri / Indeed job boards: 'naukri' platform value + structured job columns on posts

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-25
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

COLUMNS = ("job_title", "company", "job_location", "experience", "salary", "work_mode")


def upgrade() -> None:
    # A new enum value can't be used in the transaction that adds it, so add it on its own.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE platform ADD VALUE IF NOT EXISTS 'naukri'")
    for col in COLUMNS:
        op.add_column("posts", sa.Column(col, sa.Text))


def downgrade() -> None:
    for col in COLUMNS:
        op.drop_column("posts", col)
    # PostgreSQL can't drop a single enum value; 'naukri' stays in the type (harmless).
