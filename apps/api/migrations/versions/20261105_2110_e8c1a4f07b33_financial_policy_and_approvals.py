"""financial policy limits and exact-action approvals

Revision ID: e8c1a4f07b33
Revises: d5f0b8c31a77
Create Date: 2026-11-05 21:10:00

"""

from collections.abc import Sequence
from decimal import Decimal

import sqlalchemy as sa
from alembic import op

from app.modules.spendpilot.fingerprint import action_hash, approval_hash

revision: str = "e8c1a4f07b33"
down_revision: str | Sequence[str] | None = "d5f0b8c31a77"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "financial_policies",
        sa.Column("autonomy_level", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column("financial_policies", sa.Column("per_transaction_limit", sa.Numeric(14, 2), nullable=True))
    op.add_column("financial_policies", sa.Column("daily_limit", sa.Numeric(14, 2), nullable=True))
    op.add_column("financial_policies", sa.Column("monthly_limit", sa.Numeric(14, 2), nullable=True))
    op.add_column("financial_policies", sa.Column("workspace_spending_limit", sa.Numeric(14, 2), nullable=True))
    op.add_column(
        "financial_policies",
        sa.Column(
            "allowed_currencies",
            sa.dialects.postgresql.JSONB(),
            server_default=sa.text("'[\"USD\"]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "financial_policies",
        sa.Column(
            "approved_recipients",
            sa.dialects.postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "financial_policies",
        sa.Column(
            "restricted_action_types",
            sa.dialects.postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("financial_policies", sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "payout_approval_required",
        "financial_policies",
        "require_payout_approval IS TRUE",
    )
    op.create_check_constraint("autonomy_level_range", "financial_policies", "autonomy_level BETWEEN 0 AND 3")

    op.add_column(
        "approvals",
        sa.Column("action_type", sa.String(length=64), server_default="payout", nullable=True),
    )
    op.add_column("approvals", sa.Column("target_type", sa.String(length=64), nullable=True))
    op.add_column("approvals", sa.Column("target_id", sa.Uuid(), nullable=True))
    op.add_column("approvals", sa.Column("action_hash", sa.String(length=64), nullable=True))
    op.add_column("approvals", sa.Column("approval_hash", sa.String(length=64), nullable=True))
    op.alter_column("approvals", "payout_request_id", existing_type=sa.Uuid(), nullable=True)
    _backfill_approvals()
    op.alter_column("approvals", "action_type", existing_type=sa.String(length=64), nullable=False)
    op.alter_column("approvals", "target_type", existing_type=sa.String(length=64), nullable=False)
    op.alter_column("approvals", "target_id", existing_type=sa.Uuid(), nullable=False)
    op.alter_column("approvals", "action_hash", existing_type=sa.String(length=64), nullable=False)
    op.create_check_constraint(
        "approval_status",
        "approvals",
        "status IN ('pending', 'approved', 'rejected', 'expired', 'cancelled')",
    )
    op.create_index(
        "uq_approvals_open_action",
        "approvals",
        ["workspace_id", "action_hash"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'approved') AND consumed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_approvals_open_action", table_name="approvals")
    op.drop_constraint("approval_status", "approvals", type_="check")
    op.alter_column("approvals", "payout_request_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_column("approvals", "approval_hash")
    op.drop_column("approvals", "action_hash")
    op.drop_column("approvals", "target_id")
    op.drop_column("approvals", "target_type")
    op.drop_column("approvals", "action_type")
    op.drop_constraint("autonomy_level_range", "financial_policies", type_="check")
    op.drop_constraint("payout_approval_required", "financial_policies", type_="check")
    op.drop_column("financial_policies", "paused_at")
    op.drop_column("financial_policies", "restricted_action_types")
    op.drop_column("financial_policies", "approved_recipients")
    op.drop_column("financial_policies", "allowed_currencies")
    op.drop_column("financial_policies", "workspace_spending_limit")
    op.drop_column("financial_policies", "monthly_limit")
    op.drop_column("financial_policies", "daily_limit")
    op.drop_column("financial_policies", "per_transaction_limit")
    op.drop_column("financial_policies", "autonomy_level")


def _backfill_approvals() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT id, workspace_id, payout_request_id, recipient_email, amount, currency_code,
                   decided_by_user_id, status
            FROM approvals
            """
        )
    ).mappings()
    for row in rows:
        target_id = row["payout_request_id"]
        digest = action_hash(
            action_type="payout",
            recipient=row["recipient_email"],
            amount=Decimal(row["amount"]),
            currency=row["currency_code"],
            target_type="payout_request",
            target_id=target_id,
            workspace_id=row["workspace_id"],
        )
        decided = row["decided_by_user_id"]
        identity = approval_hash(digest, decided) if decided is not None and row["status"] == "approved" else None
        connection.execute(
            sa.text(
                """
                UPDATE approvals
                SET action_type = 'payout',
                    target_type = 'payout_request',
                    target_id = :target_id,
                    action_hash = :action_hash,
                    approval_hash = :approval_hash
                WHERE id = :id
                """
            ),
            {
                "id": row["id"],
                "target_id": target_id,
                "action_hash": digest,
                "approval_hash": identity,
            },
        )
