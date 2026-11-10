"""Load workspace records and evaluate the cash snapshot. Redis is not consulted."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import financial_details, record
from app.core.config import MONEY_QUANTIZE, SUPPORTED_CURRENCIES
from app.core.errors import PolicyViolationError, ValidationFailedError
from app.modules.autopilot.models import Invoice, PaymentRecord, ScheduledAction
from app.modules.finance.engine import (
    FailureFact,
    FinanceSnapshot,
    InvoiceFact,
    MilestoneFact,
    OpeningBalance,
    PaymentFact,
    PayoutFact,
    evaluate,
)
from app.modules.finance.models import CashAssumption
from app.modules.finance.schemas import AssumptionOut, FinanceSnapshotOut
from app.modules.identity.deps import Principal
from app.modules.spendpilot.models import PayoutRequest
from app.modules.trustflow.models import Customer, Milestone


async def snapshot(
    session: AsyncSession, principal: Principal, *, now: datetime | None = None, horizon_days: int = 30
) -> FinanceSnapshotOut:
    if horizon_days < 1 or horizon_days > 366:
        raise ValidationFailedError("Horizon must be between 1 and 366 days.")
    moment = now or datetime.now(UTC)
    workspace_id = principal.workspace_id
    invoices = list(
        await session.scalars(select(Invoice).where(Invoice.workspace_id == workspace_id))
    )
    payments = list(
        await session.scalars(select(PaymentRecord).where(PaymentRecord.workspace_id == workspace_id))
    )
    milestones = list(
        await session.scalars(select(Milestone).where(Milestone.workspace_id == workspace_id))
    )
    payouts = list(
        await session.scalars(select(PayoutRequest).where(PayoutRequest.workspace_id == workspace_id))
    )
    customers = list(
        await session.scalars(select(Customer).where(Customer.workspace_id == workspace_id))
    )
    names = {str(customer.id): customer.name for customer in customers}
    invoiced_milestones = {invoice.milestone_id for invoice in invoices if invoice.milestone_id}
    failures = [
        FailureFact(
            f"Scheduled {row.job_type} failed: {_safe_failure_detail(row.last_error)}."
        )
        for row in await session.scalars(
            select(ScheduledAction).where(
                ScheduledAction.workspace_id == workspace_id, ScheduledAction.status == "failed"
            )
        )
    ]
    assumption = await session.scalar(
        select(CashAssumption).where(CashAssumption.workspace_id == workspace_id)
    )
    opening = None
    if assumption is not None and assumption.opening_balance is not None:
        opening = OpeningBalance(amount=assumption.opening_balance, as_of=assumption.as_of)
    result = evaluate(
        invoices=[
            InvoiceFact(
                id=str(row.id),
                amount=row.amount,
                currency=row.currency_code,
                status=row.status,
                due_at=row.due_at,
                customer_id=str(row.customer_id) if row.customer_id else None,
                customer_name=names.get(str(row.customer_id)) if row.customer_id else None,
                provider_error=row.last_provider_error,
            )
            for row in invoices
        ],
        payments=[
            PaymentFact(
                invoice_id=str(row.invoice_id),
                amount=row.amount,
                currency=row.currency_code,
                external_id=row.external_id,
                received_at=row.received_at,
            )
            for row in payments
        ],
        milestones=[
            MilestoneFact(
                id=str(row.id),
                name=row.name,
                amount=row.amount,
                currency=row.currency_code,
                status=row.status,
                due_on=row.due_on,
                invoiced=row.id in invoiced_milestones or row.status in {"invoiced", "paid"},
            )
            for row in milestones
        ],
        payouts=[
            PayoutFact(
                id=str(row.id),
                amount=row.amount,
                currency=row.currency_code,
                status=row.status,
                provider_status=row.provider_status,
                last_error=row.last_provider_error,
            )
            for row in payouts
        ],
        failures=failures,
        opening=opening,
        now=moment,
        horizon_days=horizon_days,
    )
    return _out(result)


async def save_assumption(
    session: AsyncSession, principal: Principal, raw_amount: str | None, as_of: date | None
) -> AssumptionOut:
    if principal.role != "owner":
        raise PolicyViolationError("Only the workspace owner can change the opening balance.")
    amount = None if raw_amount is None else _parse_opening(raw_amount)
    if amount is None:
        as_of = None
    row = await session.scalar(
        select(CashAssumption).where(CashAssumption.workspace_id == principal.workspace_id)
    )
    if row is None:
        row = CashAssumption(workspace_id=principal.workspace_id, currency_code="USD")
        session.add(row)
    row.opening_balance = amount
    row.as_of = as_of
    row.currency_code = "USD"
    await session.flush()
    record(
        session,
        action="finance.assumption_set",
        entity_type="cash_assumption",
        entity_id=row.id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        details=financial_details(
            status="stored",
            proposed_by_ai=False,
            policy_evaluated="owner_opening_balance",
            opening_balance=None if amount is None else format(amount, "f"),
            as_of=None if as_of is None else as_of.isoformat(),
        ),
    )
    await session.commit()
    return AssumptionOut(
        opening_balance=None if amount is None else format(amount, "f"),
        as_of=as_of,
        currency_code="USD",
    )


_MAX_OPENING = Decimal("100000000.00")


def _parse_opening(raw: str) -> Decimal:
    text = raw.strip()
    if any(char.isalpha() for char in text):
        raise ValidationFailedError("Opening balance must be a decimal amount, not a currency code.")
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValidationFailedError("Opening balance is not a decimal value.") from exc
    if not value.is_finite():
        raise ValidationFailedError("Opening balance must be a finite decimal.")
    if value < 0:
        raise ValidationFailedError("Opening balance cannot be negative.")
    if value > _MAX_OPENING:
        raise ValidationFailedError("Opening balance exceeds the allowed maximum of USD 100000000.00.")
    if value != value.quantize(MONEY_QUANTIZE):
        raise ValidationFailedError("Opening balance must have at most 2 decimal places.")
    if "USD" not in SUPPORTED_CURRENCIES:
        raise ValidationFailedError("USD is not supported.")
    return value.quantize(MONEY_QUANTIZE)


def _safe_failure_detail(raw: str | None) -> str:
    """Keep scheduled-failure alerts short and free of provider payload text."""
    if not raw:
        return "no error text stored"
    text = " ".join(raw.split())
    if len(text) > 160:
        return f"{text[:157]}..."
    return text


def _out(result: FinanceSnapshot) -> FinanceSnapshotOut:
    return FinanceSnapshotOut.model_validate(result, from_attributes=True)
