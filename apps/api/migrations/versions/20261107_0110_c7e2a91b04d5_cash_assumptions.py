"""Store a user-supplied opening balance for cash projections.

Revision ID: c7e2a91b04d5
Revises: b1c4e8a02d11
"""

import sqlalchemy as sa
from alembic import op

revision = "c7e2a91b04d5"
down_revision = "b1c4e8a02d11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cash_assumptions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("currency_code", sa.String(length=3), server_default="USD", nullable=False),
        sa.Column("opening_balance", sa.Numeric(14, 2), nullable=True),
        sa.Column("as_of", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_cash_assumptions_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cash_assumptions")),
        sa.UniqueConstraint("workspace_id", name=op.f("uq_cash_assumptions_workspace_id")),
    )


def downgrade() -> None:
    op.drop_table("cash_assumptions")
