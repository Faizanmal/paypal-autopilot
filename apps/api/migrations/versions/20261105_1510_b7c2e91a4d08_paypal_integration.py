"""paypal integration columns and checkout orders

Revision ID: b7c2e91a4d08
Revises: 666a6156b99f
Create Date: 2026-11-05 15:10:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7c2e91a4d08"
down_revision: str | Sequence[str] | None = "666a6156b99f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("provider_status", sa.String(length=64), nullable=True))
    op.add_column("invoices", sa.Column("provider_details", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("invoices", sa.Column("hosted_url", sa.Text(), nullable=True))
    op.add_column("invoices", sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("invoices", sa.Column("last_provider_error", sa.Text(), nullable=True))
    op.add_column(
        "invoices",
        sa.Column("reminders_sent", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("invoices", sa.Column("reminder_window_started_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column(
        "webhook_events",
        sa.Column("processing_status", sa.String(length=32), server_default="received", nullable=False),
    )
    op.add_column("webhook_events", sa.Column("attempts", sa.Integer(), server_default="0", nullable=False))
    op.add_column("webhook_events", sa.Column("last_error", sa.Text(), nullable=True))
    op.create_index(op.f("ix_webhook_events_processing_status"), "webhook_events", ["processing_status"], unique=False)

    op.add_column("payout_requests", sa.Column("recipient_email", sa.String(length=320), nullable=True))
    op.add_column("payout_requests", sa.Column("sender_batch_id", sa.String(length=128), nullable=True))
    op.add_column("payout_requests", sa.Column("paypal_payout_batch_id", sa.String(length=64), nullable=True))
    op.add_column("payout_requests", sa.Column("provider_status", sa.String(length=64), nullable=True))
    op.add_column(
        "payout_requests", sa.Column("provider_details", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column("payout_requests", sa.Column("last_provider_error", sa.Text(), nullable=True))
    op.create_index(op.f("ix_payout_requests_sender_batch_id"), "payout_requests", ["sender_batch_id"], unique=True)
    op.create_index(
        op.f("ix_payout_requests_paypal_payout_batch_id"),
        "payout_requests",
        ["paypal_payout_batch_id"],
        unique=True,
    )
    op.alter_column("payout_requests", "status", server_default="pending_approval")

    op.create_table(
        "checkout_orders",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("paypal_order_id", sa.String(length=36), nullable=True),
        sa.Column("intent", sa.String(length=16), nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="created", nullable=False),
        sa.Column("provider_status", sa.String(length=64), nullable=True),
        sa.Column("provider_details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("approval_url", sa.Text(), nullable=True),
        sa.Column("authorization_id", sa.String(length=64), nullable=True),
        sa.Column("authorization_status", sa.String(length=32), nullable=True),
        sa.Column("capture_id", sa.String(length=64), nullable=True),
        sa.Column("capture_status", sa.String(length=32), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_provider_error", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("amount > 0", name=op.f("ck_checkout_orders_amount_positive")),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_checkout_orders_workspace_id_workspaces"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_checkout_orders")),
        sa.UniqueConstraint("paypal_order_id", name=op.f("uq_checkout_orders_paypal_order_id")),
        sa.UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_checkout_orders_workspace_idempotency"
        ),
    )
    op.create_index(op.f("ix_checkout_orders_workspace_id"), "checkout_orders", ["workspace_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_checkout_orders_workspace_id"), table_name="checkout_orders")
    op.drop_table("checkout_orders")
    op.alter_column("payout_requests", "status", server_default="draft")
    op.drop_index(op.f("ix_payout_requests_paypal_payout_batch_id"), table_name="payout_requests")
    op.drop_index(op.f("ix_payout_requests_sender_batch_id"), table_name="payout_requests")
    op.drop_column("payout_requests", "last_provider_error")
    op.drop_column("payout_requests", "provider_details")
    op.drop_column("payout_requests", "provider_status")
    op.drop_column("payout_requests", "paypal_payout_batch_id")
    op.drop_column("payout_requests", "sender_batch_id")
    op.drop_column("payout_requests", "recipient_email")
    op.drop_index(op.f("ix_webhook_events_processing_status"), table_name="webhook_events")
    op.drop_column("webhook_events", "last_error")
    op.drop_column("webhook_events", "attempts")
    op.drop_column("webhook_events", "processing_status")
    op.drop_column("invoices", "reminder_window_started_at")
    op.drop_column("invoices", "reminders_sent")
    op.drop_column("invoices", "last_provider_error")
    op.drop_column("invoices", "last_synced_at")
    op.drop_column("invoices", "hosted_url")
    op.drop_column("invoices", "provider_details")
    op.drop_column("invoices", "provider_status")
