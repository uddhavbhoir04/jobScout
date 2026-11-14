"""users, login sessions, per-user ownership of all scraped data

Existing rows keep user_id = NULL until the first user signs up; that user adopts them
(see jobscout.security.users.create_user).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-13
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

OWNED = ("accounts", "scrape_runs", "posts", "contacts")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("name", sa.Text),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])

    for table in OWNED:
        op.add_column(table, sa.Column("user_id", sa.Integer, nullable=True))
        op.create_foreign_key(f"fk_{table}_user_id", table, "users", ["user_id"], ["id"], ondelete="CASCADE")
        op.create_index(f"ix_{table}_user_id", table, ["user_id"])

    # uniqueness is now per user
    op.drop_constraint("uq_accounts_platform_email", "accounts", type_="unique")
    op.create_unique_constraint("uq_accounts_user_platform_email", "accounts", ["user_id", "platform", "login_email"])

    op.drop_constraint("uq_posts_platform_external_id", "posts", type_="unique")
    op.create_unique_constraint("uq_posts_user_platform_external_id", "posts", ["user_id", "platform", "external_id"])

    op.drop_index("uq_contacts_email", table_name="contacts")
    op.drop_index("uq_contacts_phone", table_name="contacts")
    op.create_index("uq_contacts_user_email", "contacts", ["user_id", "email"], unique=True,
                    postgresql_where=sa.text("email IS NOT NULL"))
    op.create_index("uq_contacts_user_phone", "contacts", ["user_id", "phone"], unique=True,
                    postgresql_where=sa.text("phone IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("uq_contacts_user_phone", table_name="contacts")
    op.drop_index("uq_contacts_user_email", table_name="contacts")
    op.create_index("uq_contacts_phone", "contacts", ["phone"], unique=True, postgresql_where=sa.text("phone IS NOT NULL"))
    op.create_index("uq_contacts_email", "contacts", ["email"], unique=True, postgresql_where=sa.text("email IS NOT NULL"))
    op.drop_constraint("uq_posts_user_platform_external_id", "posts", type_="unique")
    op.create_unique_constraint("uq_posts_platform_external_id", "posts", ["platform", "external_id"])
    op.drop_constraint("uq_accounts_user_platform_email", "accounts", type_="unique")
    op.create_unique_constraint("uq_accounts_platform_email", "accounts", ["platform", "login_email"])
    for table in OWNED:
        op.drop_index(f"ix_{table}_user_id", table_name=table)
        op.drop_constraint(f"fk_{table}_user_id", table, type_="foreignkey")
        op.drop_column(table, "user_id")
    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_table("user_sessions")
    op.drop_table("users")
