"""Persist workflow dependencies, attempts, and schedule claims.

Revision ID: b1c4e8a02d11
Revises: a6d8e2f019bc
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b1c4e8a02d11"
down_revision = "a6d8e2f019bc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workflow_steps", sa.Column(
        "depends_on", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
    ))
    op.add_column("workflow_steps", sa.Column("condition", sa.String(length=128), nullable=True))
    op.add_column("workflow_steps", sa.Column("waiting_for", sa.String(length=64), nullable=True))
    op.add_column("workflow_steps", sa.Column("run_after", sa.DateTime(timezone=True), nullable=True))
    op.add_column("workflow_steps", sa.Column(
        "attempts", sa.Integer(), nullable=False, server_default="0"
    ))
    op.add_column("workflow_steps", sa.Column("provider_reference", sa.String(length=128), nullable=True))
    op.add_column("scheduled_actions", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("scheduled_actions", sa.Column("idempotency_key", sa.String(length=128), nullable=True))
    op.create_index(
        "uq_scheduled_actions_idempotency",
        "scheduled_actions",
        ["workspace_id", "job_type", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_scheduled_actions_idempotency", table_name="scheduled_actions")
    op.drop_column("scheduled_actions", "idempotency_key")
    op.drop_column("scheduled_actions", "claimed_at")
    op.drop_column("workflow_steps", "provider_reference")
    op.drop_column("workflow_steps", "attempts")
    op.drop_column("workflow_steps", "run_after")
    op.drop_column("workflow_steps", "waiting_for")
    op.drop_column("workflow_steps", "condition")
    op.drop_column("workflow_steps", "depends_on")
