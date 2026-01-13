"""Add display_name to contacts

Revision ID: 002
Revises: 001
Create Date: 2026-01-13

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('contacts', sa.Column('display_name', sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column('contacts', 'display_name')
