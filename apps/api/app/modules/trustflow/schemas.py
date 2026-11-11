from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class CustomerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    email: EmailStr
    company_name: str | None = Field(default=None, max_length=160)
    billing_email: EmailStr | None = None
    billing_address: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=4000)


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    company_name: str | None = Field(default=None, max_length=160)
    billing_email: EmailStr | None = None
    billing_address: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=4000)


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: EmailStr
    company_name: str | None
    billing_email: str | None
    billing_address: str | None
    notes: str | None
    archived_at: datetime | None


class ContractorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    email: EmailStr
    paypal_email: EmailStr | None = None
    notes: str | None = Field(default=None, max_length=4000)


class ContractorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: EmailStr
    paypal_email: EmailStr | None
    notes: str | None


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    currency_code: str = Field(min_length=3, max_length=3)
    total_amount: Decimal
    customer_id: uuid.UUID | None = None
    starts_on: date | None = None
    ends_on: date | None = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    customer_id: uuid.UUID | None
    name: str
    description: str | None
    currency_code: str
    total_amount: Decimal
    status: str
    starts_on: date | None
    ends_on: date | None


class MilestoneCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    amount: Decimal
    currency_code: str = Field(min_length=3, max_length=3)
    trigger_kind: str = Field(pattern="^(upfront|on_event|on_delivery)$")
    due_on: date | None = None
    acceptance_condition: str | None = Field(default=None, max_length=2000)


class MilestoneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    sequence: int
    name: str
    currency_code: str
    amount: Decimal
    trigger_kind: str
    status: str
    due_on: date | None
    acceptance_condition: str | None


class MilestoneTransition(BaseModel):
    status: str = Field(pattern="^(draft|active|submitted|accepted|invoiced|paid|cancelled)$")


class BillingProgress(BaseModel):
    currency_code: str
    project_total: Decimal
    invoiced_amount: Decimal
    paid_amount: Decimal
    remaining_amount: Decimal
    milestone_count: int


class ProjectMilestone(MilestoneOut):
    invoice_id: uuid.UUID | None = None
    paypal_invoice_id: str | None = None
    invoice_status: str | None = None


class ProjectDetail(ProjectOut):
    milestones: list[ProjectMilestone]
    progress: BillingProgress


class ContractApply(BaseModel):
    customer_id: uuid.UUID
    project_name: str | None = Field(default=None, max_length=200)


class ContractOut(BaseModel):
    id: uuid.UUID
    filename: str
    content_type: str
    status: str
    customer_id: uuid.UUID | None
    project_id: uuid.UUID | None
    provider_label: str
    legally_verified: bool
    disclaimer: str
    extraction: dict
    findings: list[str]


class ItemList[T](BaseModel):
    items: list[T]
