from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class InvoiceCreate(BaseModel):
    customer_id: uuid.UUID
    project_id: uuid.UUID | None = None
    milestone_id: uuid.UUID | None = None
    currency_code: str = "USD"
    amount: Decimal
    description: str = Field(min_length=1, max_length=200)
    idempotency_key: str | None = Field(default=None, max_length=128)


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    customer_id: uuid.UUID | None
    project_id: uuid.UUID | None
    currency_code: str
    amount: Decimal
    status: str
    paypal_invoice_id: str | None
    provider_status: str | None
    hosted_url: str | None
    due_at: datetime | None
    last_synced_at: datetime | None
    last_provider_error: str | None
    reminders_sent: int
    milestone_id: uuid.UUID | None = None


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    invoice_id: uuid.UUID
    currency_code: str
    amount: Decimal
    source: str
    external_id: str
    received_at: datetime


class OrderCreate(BaseModel):
    currency_code: str = "USD"
    amount: Decimal
    description: str = Field(min_length=1, max_length=200)
    intent: Literal["CAPTURE", "AUTHORIZE"] = "CAPTURE"
    idempotency_key: str | None = Field(default=None, max_length=128)


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    paypal_order_id: str | None
    intent: str
    currency_code: str
    amount: Decimal
    description: str
    status: str
    provider_status: str | None
    approval_url: str | None
    authorization_id: str | None
    authorization_status: str | None
    capture_id: str | None
    capture_status: str | None
    last_synced_at: datetime | None
    last_provider_error: str | None


class ItemList[T](BaseModel):
    items: list[T]


class WebhookIngestOut(BaseModel):
    status: str
    event_id: str
