"""Cash snapshot returned to the workspace. Amounts are decimal strings."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class AssumptionIn(BaseModel):
    opening_balance: str | None = Field(default=None, max_length=20)
    as_of: date | None = None


class AssumptionOut(BaseModel):
    opening_balance: str | None
    as_of: date | None
    currency_code: str


class AlertOut(BaseModel):
    kind: str
    message: str
    amount: str | None


class InsightOut(BaseModel):
    kind: str
    message: str
    figures: dict[str, str]


class ProjectionEntryOut(BaseModel):
    on: str | None
    direction: str
    amount: str
    label: str
    included: bool
    reason: str


class FinanceSnapshotOut(BaseModel):
    currency: str
    horizon_days: int
    total_invoiced: str
    total_paid: str
    outstanding_receivables: str
    overdue_receivables: str
    upcoming_expected_payments: str
    pending_contractor_obligations: str
    completed_payouts: str
    net_cash_flow_estimate: str | None
    confirmed_payments: str
    expected_payments: str
    undated_expected_payments: str
    planned_expenses: str
    in_flight_expenses: str
    executed_expenses: str
    refunds_reversed: str
    paypal_balance_available: bool
    paypal_balance_amount: str | None
    paypal_balance_reason: str
    projected_available: str | None
    opening_balance: str | None
    opening_as_of: str | None
    pending_approval_count: int
    duplicate_payment_events: int
    excluded_by_currency: dict[str, int]
    insights: list[InsightOut]
    alerts: list[AlertOut]
    assumptions: list[str]
    uncertainty: list[str]
    projection: list[ProjectionEntryOut]
