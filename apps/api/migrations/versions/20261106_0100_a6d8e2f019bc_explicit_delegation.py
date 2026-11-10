"""Require explicit delegation for low-risk autopilot actions.

Revision ID: a6d8e2f019bc
Revises: f3b7c2a91e04
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a6d8e2f019bc"
down_revision = "f3b7c2a91e04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("financial_policies", sa.Column(
        "delegated_action_types", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
    ))


def downgrade() -> None:
    op.drop_column("financial_policies", "delegated_action_types")
