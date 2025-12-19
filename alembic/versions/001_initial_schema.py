"""Initial schema

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create users table
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("language_code", sa.String(length=10), server_default="ru", nullable=True),
        sa.Column("timezone", sa.String(length=50), server_default="Europe/Moscow", nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_users_username", "users", ["username"], unique=False)

    # Create contacts table
    op.create_table(
        "contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=True),
        sa.Column("reminder_frequency", sa.String(length=50), server_default="biweekly", nullable=True),
        sa.Column("custom_interval_days", sa.Integer(), nullable=True),
        sa.Column("next_reminder_date", sa.Date(), nullable=True),
        sa.Column("last_contacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=True),
        sa.Column("one_time_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.CheckConstraint("status IN ('active', 'paused', 'one_time')", name="check_status"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "username", name="unique_user_contact"),
    )
    op.create_index("idx_contacts_user_id", "contacts", ["user_id"], unique=False)
    op.create_index("idx_contacts_status", "contacts", ["status"], unique=False)
    op.create_index("idx_contacts_next_reminder", "contacts", ["next_reminder_date"], unique=False)
    op.create_index("idx_contacts_tags", "contacts", ["tags"], unique=False, postgresql_using="gin")

    # Create contact_history table
    op.create_table(
        "contact_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_history_contact_id", "contact_history", ["contact_id"], unique=False)
    op.create_index("idx_history_created_at", "contact_history", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_table("contact_history")
    op.drop_table("contacts")
    op.drop_table("users")
