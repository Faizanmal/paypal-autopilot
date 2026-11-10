from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class PayoutIntentCreate(BaseModel):
    contractor_id: uuid.UUID
    currency_code: str = "USD"
    amount: Decimal
    note: str | None = Field(default=None, max_length=4000)
    trigger_invoice_id: uuid.UUID | None = None
    idempotency_key: str | None = Field(default=None, max_length=128)


class PayoutRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    contractor_id: uuid.UUID
    recipient_email: str | None
    currency_code: str
    amount: Decimal
    status: str
    provider_status: str | None
    paypal_payout_batch_id: str | None
    sender_batch_id: str | None
    last_provider_error: str | None
    decision_reason: str | None = None


class PayoutCapabilityOut(BaseModel):
    execution_enabled: bool
    reason: str
    credentials_configured: bool
    scope_present: bool | None


class RejectPayout(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class ItemList[T](BaseModel):
    items: list[T]


class PolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    autonomy_level: int
    require_payout_approval: bool
    currency_code: str
    approval_threshold_amount: Decimal | None
    per_transaction_limit: Decimal | None
    daily_limit: Decimal | None
    monthly_limit: Decimal | None
    workspace_spending_limit: Decimal | None
    allowed_currencies: list[str]
    approved_recipients: list[str]
    restricted_action_types: list[str]
    delegated_action_types: list[str]
    paused_at: datetime | None


class PolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    autonomy_level: int | None = Field(default=None, ge=0, le=3)
    per_transaction_limit: Decimal | None = None
    daily_limit: Decimal | None = None
    monthly_limit: Decimal | None = None
    workspace_spending_limit: Decimal | None = None
    approval_threshold_amount: Decimal | None = None
    allowed_currencies: list[str] | None = None
    approved_recipients: list[str] | None = None
    restricted_action_types: list[str] | None = None
    delegated_action_types: list[str] | None = None
    paused: bool | None = None
