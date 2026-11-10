"""store the reason an owner rejects a payout

Revision ID: f3b7c2a91e04
Revises: e8c1a4f07b33
Create Date: 2026-11-05 22:10:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3b7c2a91e04"
down_revision: str | Sequence[str] | None = "e8c1a4f07b33"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("approvals", sa.Column("decision_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("approvals", "decision_reason")
