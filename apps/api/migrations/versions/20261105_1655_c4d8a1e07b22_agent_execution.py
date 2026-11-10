"""agent plan, validation, and execution columns

Revision ID: c4d8a1e07b22
Revises: b7c2e91a4d08
Create Date: 2026-11-05 16:55:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4d8a1e07b22"
down_revision: str | Sequence[str] | None = "b7c2e91a4d08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("plan", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("agent_runs", sa.Column("validation", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("agent_runs", sa.Column("explanation", sa.Text(), nullable=True))
    op.add_column("agent_runs", sa.Column("provider_label", sa.String(length=160), nullable=True))
    op.add_column(
        "agent_actions",
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
    )
    op.add_column("agent_actions", sa.Column("arguments", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("agent_actions", sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("agent_actions", sa.Column("provider_reference", sa.String(length=128), nullable=True))
    op.add_column("agent_actions", sa.Column("error", sa.Text(), nullable=True))
    op.add_column("agent_actions", sa.Column("attempts", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("agent_actions", "attempts")
    op.drop_column("agent_actions", "error")
    op.drop_column("agent_actions", "provider_reference")
    op.drop_column("agent_actions", "result")
    op.drop_column("agent_actions", "arguments")
    op.drop_column("agent_actions", "status")
    op.drop_column("agent_runs", "provider_label")
    op.drop_column("agent_runs", "explanation")
    op.drop_column("agent_runs", "validation")
    op.drop_column("agent_runs", "plan")
