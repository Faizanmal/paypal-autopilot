"""SpendPilot tables: payout requests, approvals, financial policies."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.columns import CURRENCY, MONEY


def _currency_list() -> list[str]:
    return ["USD"]


def _empty_list() -> list[str]:
    return []


class FinancialPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "financial_policies"
    __table_args__ = (
        CheckConstraint("require_payout_approval IS TRUE", name="payout_approval_required"),
        CheckConstraint("autonomy_level BETWEEN 0 AND 3", name="autonomy_level_range"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    require_payout_approval: Mapped[bool] = mapped_column(
        nullable=False, default=True, server_default="true"
    )
    currency_code: Mapped[str] = mapped_column(CURRENCY, nullable=False, default="USD", server_default="USD")
    approval_threshold_amount: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    autonomy_level: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    per_transaction_limit: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    daily_limit: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    monthly_limit: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    workspace_spending_limit: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    allowed_currencies: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=_currency_list, server_default=text("'[\"USD\"]'::jsonb")
    )
    approved_recipients: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=_empty_list, server_default=text("'[]'::jsonb")
    )
    restricted_action_types: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=_empty_list, server_default=text("'[]'::jsonb")
    )
    delegated_action_types: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=_empty_list, server_default=text("'[]'::jsonb")
    )
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PayoutRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payout_requests"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_payout_requests_workspace_idempotency"
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    milestone_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("milestones.id", ondelete="SET NULL"), nullable=True
    )
    contractor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("contractors.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    trigger_invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True
    )
    currency_code: Mapped[str] = mapped_column(CURRENCY, nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending_approval", server_default="pending_approval"
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    recipient_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    sender_batch_id: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    paypal_payout_batch_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    provider_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_provider_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Approval(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "approvals"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired', 'cancelled')",
            name="approval_status",
        ),
        Index(
            "uq_approvals_open_action",
            "workspace_id",
            "action_hash",
            unique=True,
            postgresql_where=text("status IN ('pending', 'approved') AND consumed_at IS NULL"),
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    payout_request_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("payout_requests.id", ondelete="CASCADE"),
        nullable=True,
        unique=True,
    )
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", server_default="pending")
    currency_code: Mapped[str] = mapped_column(CURRENCY, nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    recipient_email: Mapped[str] = mapped_column(String(320), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False, default="payout", server_default="payout")
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    action_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    approval_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
