"""Deterministic cash figures. Future invoices are never treated as cash received."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

CENT = Decimal("0.01")
REPORT_CURRENCY = "USD"

OPEN_STATUSES = frozenset({"sent", "scheduled", "payment_pending", "partially_paid"})
PAID_STATUSES = frozenset({"paid", "marked_as_paid"})
FULL_REFUND = frozenset({"refunded", "marked_as_refunded"})
PARTIAL_REFUND = frozenset({"partially_refunded"})
PLANNED_PAYOUTS = frozenset({"pending_approval", "approved"})
IN_FLIGHT_PAYOUTS = frozenset({"executing", "execution_unknown", "submitted"})
EXECUTED_PAYOUTS = frozenset({"succeeded"})
FAILED_PAYOUTS = frozenset({"denied", "execution_unknown"})
EXPECTED_MILESTONES = frozenset({"draft", "active", "submitted", "accepted"})


@dataclass(frozen=True)
class InvoiceFact:
    id: str
    amount: Decimal
    currency: str
    status: str
    due_at: datetime | None
    customer_id: str | None
    customer_name: str | None
    provider_error: str | None = None


@dataclass(frozen=True)
class PaymentFact:
    invoice_id: str
    amount: Decimal
    currency: str
    external_id: str
    received_at: datetime


@dataclass(frozen=True)
class MilestoneFact:
    id: str
    name: str
    amount: Decimal
    currency: str
    status: str
    due_on: date | None
    invoiced: bool


@dataclass(frozen=True)
class PayoutFact:
    id: str
    amount: Decimal
    currency: str
    status: str
    provider_status: str | None = None
    last_error: str | None = None


@dataclass(frozen=True)
class FailureFact:
    message: str


@dataclass(frozen=True)
class OpeningBalance:
    amount: Decimal
    as_of: date | None


@dataclass(frozen=True)
class Alert:
    kind: str
    message: str
    amount: str | None


@dataclass(frozen=True)
class Insight:
    kind: str
    message: str
    figures: dict[str, str]


@dataclass(frozen=True)
class ProjectionEntry:
    on: str | None
    direction: str
    amount: str
    label: str
    included: bool
    reason: str


@dataclass(frozen=True)
class FinanceSnapshot:
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
    insights: list[Insight]
    alerts: list[Alert]
    assumptions: list[str]
    uncertainty: list[str]
    projection: list[ProjectionEntry]


def evaluate(
    *,
    invoices: list[InvoiceFact],
    payments: list[PaymentFact],
    milestones: list[MilestoneFact],
    payouts: list[PayoutFact],
    failures: list[FailureFact] | None = None,
    opening: OpeningBalance | None = None,
    now: datetime,
    horizon_days: int = 30,
) -> FinanceSnapshot:
    """Sum one currency. Other currencies are counted and left out of every total."""
    moment = _aware(now)
    horizon_end = moment + timedelta(days=horizon_days)
    today = moment.astimezone(UTC).date()
    excluded: dict[str, int] = {}
    invoices_by_id = {row.id: row for row in invoices}
    alerts: list[Alert] = []
    projection: list[ProjectionEntry] = []

    invoiced = Decimal("0")
    for invoice in invoices:
        if not _same_currency(invoice.currency, excluded):
            continue
        if invoice.status not in {"draft", "cancelled"}:
            invoiced += invoice.amount
        if invoice.provider_error:
            alerts.append(
                Alert(
                    "failed_action",
                    f"Invoice {invoice.id} last provider error: {_safe_alert_detail(invoice.provider_error)}",
                    _text(invoice.amount),
                )
            )

    confirmed = Decimal("0")
    refunds = Decimal("0")
    duplicates = 0
    seen: set[tuple[str, str]] = set()
    applied: dict[str, Decimal] = {}
    late_by_customer: dict[str, tuple[str, int]] = {}
    paid_invoice_ids: set[str] = set()
    for payment in payments:
        if not _same_currency(payment.currency, excluded):
            continue
        key = (payment.invoice_id, payment.external_id)
        if key in seen:
            duplicates += 1
            alerts.append(
                Alert(
                    "unreconciled",
                    f"Duplicate payment {payment.external_id} on invoice {payment.invoice_id} was ignored.",
                    _text(payment.amount),
                )
            )
            continue
        seen.add(key)
        matched = invoices_by_id.get(payment.invoice_id)
        if matched is None:
            alerts.append(
                Alert(
                    "unreconciled",
                    f"Payment {payment.external_id} has no invoice in this workspace.",
                    _text(payment.amount),
                )
            )
            continue
        paid_invoice_ids.add(matched.id)
        if matched.status in FULL_REFUND:
            refunds += payment.amount
            alerts.append(
                Alert(
                    "unreconciled",
                    (
                        f"Invoice {matched.id} is {matched.status}. "
                        f"USD {_text(payment.amount)} is reversed and is not cash on hand."
                    ),
                    _text(payment.amount),
                )
            )
            continue
        if matched.status in PARTIAL_REFUND:
            alerts.append(
                Alert(
                    "unreconciled",
                    (
                        f"Invoice {matched.id} is partially refunded. The refunded portion is not stored, "
                        f"so USD {_text(payment.amount)} is excluded from confirmed cash."
                    ),
                    _text(payment.amount),
                )
            )
            continue
        applied[matched.id] = applied.get(matched.id, Decimal("0")) + payment.amount
        received = _aware(payment.received_at)
        received_on = received.astimezone(UTC).date()
        if opening is None or opening.as_of is None or received_on >= opening.as_of:
            confirmed += payment.amount
        due_on = _aware(matched.due_at).astimezone(UTC).date() if matched.due_at else None
        if due_on is not None and matched.customer_id and received_on > due_on:
            name = matched.customer_name or "A customer"
            current = late_by_customer.get(matched.customer_id, (name, 0))
            late_by_customer[matched.customer_id] = (current[0], current[1] + 1)

    outstanding = Decimal("0")
    overdue = Decimal("0")
    expected_dated = Decimal("0")
    expected_undated = Decimal("0")
    for invoice in invoices:
        if invoice.currency.upper() != REPORT_CURRENCY:
            continue
        if invoice.status in PAID_STATUSES and invoice.id not in paid_invoice_ids:
            alerts.append(
                Alert(
                    "unreconciled",
                    (
                        f"Invoice {invoice.id} is {invoice.status} but has no payment record, "
                        f"so USD {_text(invoice.amount)} is not counted as received."
                    ),
                    _text(invoice.amount),
                )
            )
        if invoice.status not in OPEN_STATUSES:
            continue
        covered = applied.get(invoice.id, Decimal("0"))
        remaining = invoice.amount - covered
        if remaining < 0:
            alerts.append(
                Alert(
                    "unreconciled",
                    f"Payments on invoice {invoice.id} exceed its amount by USD {_text(-remaining)}.",
                    _text(-remaining),
                )
            )
            remaining = Decimal("0")
        if remaining == 0:
            continue
        outstanding += remaining
        due = _aware(invoice.due_at) if invoice.due_at else None
        if due is not None and due < moment:
            overdue += remaining
            alerts.append(
                Alert(
                    "overdue",
                    f"Invoice {invoice.id} for USD {_text(remaining)} is past due and still {invoice.status}.",
                    _text(remaining),
                )
            )
        elif due is not None and due <= horizon_end:
            expected_dated += remaining
            projection.append(
                ProjectionEntry(
                    due.astimezone(UTC).date().isoformat(),
                    "inflow",
                    _text(remaining),
                    f"Invoice {invoice.id} due",
                    True,
                    "Open invoice with a due date inside the horizon.",
                )
            )
        elif due is None:
            expected_undated += remaining
            projection.append(
                ProjectionEntry(
                    None,
                    "inflow",
                    _text(remaining),
                    f"Invoice {invoice.id} has no due date",
                    False,
                    "Undated open invoices are expected, not included in the projection.",
                )
            )
            alerts.append(
                Alert(
                    "unreconciled",
                    (
                        f"Invoice {invoice.id} is {invoice.status} and has no due date, "
                        "so it is not overdue and not in the projection."
                    ),
                    _text(remaining),
                )
            )

    for milestone in milestones:
        if not _same_currency(milestone.currency, excluded):
            continue
        if milestone.invoiced or milestone.status not in EXPECTED_MILESTONES:
            continue
        if milestone.due_on is None:
            expected_undated += milestone.amount
            projection.append(
                ProjectionEntry(
                    None,
                    "inflow",
                    _text(milestone.amount),
                    f"Milestone {milestone.name} has no due date",
                    False,
                    "Undated milestones are not included in the projection.",
                )
            )
        elif milestone.due_on < today:
            alerts.append(
                Alert(
                    "unreconciled",
                    (
                        f"Milestone {milestone.name} was due on {milestone.due_on.isoformat()} and has no invoice. "
                        f"USD {_text(milestone.amount)} is not treated as receivable or cash."
                    ),
                    _text(milestone.amount),
                )
            )
        elif milestone.due_on <= horizon_end.astimezone(UTC).date():
            expected_dated += milestone.amount
            projection.append(
                ProjectionEntry(
                    milestone.due_on.isoformat(),
                    "inflow",
                    _text(milestone.amount),
                    f"Milestone {milestone.name}",
                    True,
                    "Uninvoiced milestone due inside the horizon.",
                )
            )

    planned = Decimal("0")
    in_flight = Decimal("0")
    executed = Decimal("0")
    pending_count = 0
    for payout in payouts:
        if not _same_currency(payout.currency, excluded):
            continue
        if payout.status in PLANNED_PAYOUTS:
            planned += payout.amount
            if payout.status == "pending_approval":
                pending_count += 1
            projection.append(
                ProjectionEntry(
                    None,
                    "outflow",
                    _text(payout.amount),
                    f"Payout {payout.id} is {payout.status}",
                    True,
                    "Planned payouts reduce projected funds. No send date is stored.",
                )
            )
        elif payout.status in IN_FLIGHT_PAYOUTS:
            in_flight += payout.amount
            projection.append(
                ProjectionEntry(
                    None,
                    "outflow",
                    _text(payout.amount),
                    f"Payout {payout.id} is {payout.status}",
                    True,
                    "Submitted payouts are not verified as paid.",
                )
            )
        elif payout.status in EXECUTED_PAYOUTS:
            executed += payout.amount
        if payout.status in FAILED_PAYOUTS:
            detail = _safe_alert_detail(payout.last_error or payout.provider_status or payout.status)
            alerts.append(
                Alert(
                    "failed_action",
                    f"Payout {payout.id} is {payout.status}: {detail}.",
                    _text(payout.amount),
                )
            )
    if pending_count:
        waiting = _pending_amount(payouts)
        noun = "payout" if pending_count == 1 else "payouts"
        verb = "is" if pending_count == 1 else "are"
        alerts.append(
            Alert(
                "pending_approval",
                f"{pending_count} {noun} {verb} waiting for approval, totaling USD {_text(waiting)}.",
                _text(waiting),
            )
        )

    for failure in failures or []:
        alerts.append(Alert("failed_action", failure.message, None))

    cash_before_obligations: Decimal | None = None
    projected: Decimal | None = None
    net: Decimal | None = None
    if opening is None:
        net = None
    else:
        net = opening.amount + confirmed - executed
        cash_before_obligations = net + expected_dated
        projected = cash_before_obligations - planned - in_flight
        if projected < 0:
            alerts.append(
                Alert(
                    "cash_shortfall",
                    (
                        f"Projected available funds are USD {_text(projected)} "
                        "after dated expected inflows and planned payouts."
                    ),
                    _text(projected),
                )
            )

    insights: list[Insight] = []
    overdue_count = sum(1 for alert in alerts if alert.kind == "overdue")
    if overdue_count:
        noun = "invoice" if overdue_count == 1 else "invoices"
        verb = "is" if overdue_count == 1 else "are"
        insights.append(
            Insight(
                "overdue",
                f"{overdue_count} {noun} {verb} overdue, totaling USD {_text(overdue)}.",
                {
                    "overdue_count": str(overdue_count),
                    "overdue_receivables": _text(overdue),
                    "outstanding_receivables": _text(outstanding),
                },
            )
        )
    if opening is not None and cash_before_obligations is not None and planned > cash_before_obligations:
        insights.append(
            Insight(
                "obligation_gap",
                (
                    f"Planned contractor obligations of USD {_text(planned)} "
                    f"exceed projected available funds of USD {_text(cash_before_obligations)}."
                ),
                {
                    "pending_contractor_obligations": _text(planned),
                    "projected_before_obligations": _text(cash_before_obligations),
                    "projected_available": _text(projected) if projected is not None else "0.00",
                },
            )
        )
    for name, count in late_by_customer.values():
        if count >= 2:
            insights.append(
                Insight(
                    "late_payer",
                    f"{name} has paid after the due date {count} times.",
                    {"customer": name, "late_payment_count": str(count)},
                )
            )
    if in_flight > 0:
        insights.append(
            Insight(
                "in_flight",
                (
                    f"USD {_text(in_flight)} in contractor payouts is submitted or executing "
                    "and is not yet a verified completed payout."
                ),
                {
                    "in_flight_expenses": _text(in_flight),
                    "executed_expenses": _text(executed),
                },
            )
        )
    if refunds > 0:
        insights.append(
            Insight(
                "refunds",
                f"USD {_text(refunds)} in recorded payments was reversed by full refunds.",
                {"refunds_reversed": _text(refunds), "confirmed_payments": _text(confirmed)},
            )
        )
    if expected_undated > 0 and expected_undated >= expected_dated:
        insights.append(
            Insight(
                "undated_expected",
                (
                    f"USD {_text(expected_undated)} in expected payments has no due date "
                    f"and is excluded from the {horizon_days}-day projection "
                    f"(dated expected: USD {_text(expected_dated)})."
                ),
                {
                    "undated_expected_payments": _text(expected_undated),
                    "expected_payments": _text(expected_dated),
                    "horizon_days": str(horizon_days),
                },
            )
        )

    assumptions = [
        "Only USD records are added. Other currencies are counted and are not converted.",
        "Confirmed cash is the sum of payment records. A paid invoice with no payment record is not cash received.",
        "A duplicate payment is the same invoice and the same external id. Later copies are ignored.",
        "A full refund reverses its recorded payment. A partial refund has no stored amount, so it is excluded.",
        "Open invoices and uninvoiced milestones are expected payments, not cash.",
        (
            f"The projection window is {horizon_days} days from {moment.astimezone(UTC).isoformat()}. "
            "Undated items and items outside the window are excluded from the projected total."
        ),
        "Due at the current timestamp is not overdue. The following instant is overdue.",
        "A payment on the UTC due date is on time. The next UTC date is late.",
        "Completed payouts have no execution timestamp, so every succeeded payout is subtracted.",
        "PayPal account balance is not read. No balance figure is estimated.",
    ]
    if opening is None:
        assumptions.append("No opening balance is stored, so net cash flow and projected available funds are omitted.")
    elif opening.as_of is None:
        assumptions.append("The opening balance is added to confirmed payments. It is not a bank statement.")
    else:
        assumptions.append(
            f"Payments received before {opening.as_of.isoformat()} are already included in the opening balance."
        )

    uncertainty = [
        (
            "Projection assumes open invoices pay on their due date. "
            "Late-payer history is reported as an insight, not applied as a haircut."
        ),
        (
            "Uninvoiced milestones may never become invoices. "
            "They are expected inflows only while still draft/active/submitted/accepted."
        ),
        (
            "Planned payouts have no send date, so the projection treats them "
            "as near-term outflows inside the horizon."
        ),
        (
            "Submitted payouts are not verified completions. "
            "They reduce projected funds until a succeeded status is recorded."
        ),
        (
            "Without a PayPal balance read, projected available funds are "
            "relative to the user-supplied opening balance only."
        ),
    ]
    if expected_undated > 0:
        uncertainty.append(
            
                f"USD {_text(expected_undated)} of expected payments lacks a due date "
                "and is omitted from projected available funds."
            
        )
    if excluded:
        uncertainty.append(
            "Non-USD records were counted in excluded_by_currency and are not converted into the USD projection."
        )

    return FinanceSnapshot(
        currency=REPORT_CURRENCY,
        horizon_days=horizon_days,
        total_invoiced=_text(invoiced),
        total_paid=_text(confirmed),
        outstanding_receivables=_text(outstanding),
        overdue_receivables=_text(overdue),
        upcoming_expected_payments=_text(expected_dated + expected_undated),
        pending_contractor_obligations=_text(planned),
        completed_payouts=_text(executed),
        net_cash_flow_estimate=None if net is None else _text(net),
        confirmed_payments=_text(confirmed),
        expected_payments=_text(expected_dated),
        undated_expected_payments=_text(expected_undated),
        planned_expenses=_text(planned),
        in_flight_expenses=_text(in_flight),
        executed_expenses=_text(executed),
        refunds_reversed=_text(refunds),
        paypal_balance_available=False,
        paypal_balance_amount=None,
        paypal_balance_reason="PayPal account balance is not read by this workspace. No balance is estimated.",
        projected_available=None if projected is None else _text(projected),
        opening_balance=None if opening is None else _text(opening.amount),
        opening_as_of=None if opening is None or opening.as_of is None else opening.as_of.isoformat(),
        pending_approval_count=pending_count,
        duplicate_payment_events=duplicates,
        excluded_by_currency=excluded,
        insights=insights,
        alerts=alerts,
        assumptions=assumptions,
        uncertainty=uncertainty,
        projection=projection,
    )


def _pending_amount(payouts: list[PayoutFact]) -> Decimal:
    total = Decimal("0")
    for payout in payouts:
        if payout.currency.upper() == REPORT_CURRENCY and payout.status == "pending_approval":
            total += payout.amount
    return total


def _same_currency(currency: str, excluded: dict[str, int]) -> bool:
    code = currency.upper()
    if code == REPORT_CURRENCY:
        return True
    excluded[code] = excluded.get(code, 0) + 1
    return False


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _text(amount: Decimal) -> str:
    return format(amount.quantize(CENT), "f")


def _safe_alert_detail(raw: str) -> str:
    text = " ".join(raw.split())
    if len(text) > 160:
        return f"{text[:157]}..."
    return text
