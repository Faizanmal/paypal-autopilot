from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.modules.finance.engine import (
    FailureFact,
    InvoiceFact,
    MilestoneFact,
    OpeningBalance,
    PaymentFact,
    PayoutFact,
    evaluate,
)

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def _invoice(**overrides) -> InvoiceFact:
    values = {
        "id": "inv-1",
        "amount": Decimal("10.00"),
        "currency": "USD",
        "status": "sent",
        "due_at": NOW + timedelta(days=3),
        "customer_id": None,
        "customer_name": None,
    }
    values.update(overrides)
    return InvoiceFact(**values)


def _payment(**overrides) -> PaymentFact:
    values = {
        "invoice_id": "inv-1",
        "amount": Decimal("10.00"),
        "currency": "USD",
        "external_id": "PAY-1",
        "received_at": NOW,
    }
    values.update(overrides)
    return PaymentFact(**values)


def _snapshot(**overrides):
    values = {
        "invoices": [],
        "payments": [],
        "milestones": [],
        "payouts": [],
        "now": NOW,
        "horizon_days": 30,
    }
    values.update(overrides)
    return evaluate(**values)


def test_decimal_cents_do_not_use_binary_floats():
    paid = _invoice(id="paid", status="paid", due_at=NOW - timedelta(days=1))
    result = _snapshot(
        invoices=[paid],
        payments=[
            _payment(invoice_id="paid", amount=Decimal("0.10"), external_id="A"),
            _payment(invoice_id="paid", amount=Decimal("0.20"), external_id="B"),
        ],
    )
    assert result.total_paid == "0.30"
    assert result.confirmed_payments == "0.30"


def test_other_currencies_are_excluded_from_usd_totals():
    result = _snapshot(
        invoices=[
            _invoice(amount=Decimal("5.00")),
            _invoice(id="eur", amount=Decimal("80.00"), currency="EUR"),
        ],
        payments=[_payment(amount=Decimal("40.00"), currency="EUR", invoice_id="eur")],
    )
    assert result.total_invoiced == "5.00"
    assert result.total_paid == "0.00"
    assert result.excluded_by_currency == {"EUR": 2}


def test_due_at_the_current_instant_is_not_overdue():
    on_time = _snapshot(invoices=[_invoice(due_at=NOW)])
    late = _snapshot(invoices=[_invoice(due_at=NOW - timedelta(microseconds=1))])
    upcoming = _snapshot(invoices=[_invoice(due_at=NOW + timedelta(seconds=1))])
    assert on_time.overdue_receivables == "0.00"
    assert late.overdue_receivables == "10.00"
    assert upcoming.overdue_receivables == "0.00"
    assert upcoming.expected_payments == "10.00"


def test_overdue_uses_the_unpaid_remainder():
    result = _snapshot(
        invoices=[_invoice(amount=Decimal("10.00"), due_at=NOW - timedelta(days=1), status="partially_paid")],
        payments=[_payment(amount=Decimal("4.00"))],
    )
    assert result.overdue_receivables == "6.00"
    assert result.outstanding_receivables == "6.00"
    assert result.total_paid == "4.00"


def test_duplicate_payment_event_is_counted_once():
    result = _snapshot(
        invoices=[_invoice(status="paid", due_at=NOW - timedelta(days=2))],
        payments=[_payment(amount=Decimal("10.00")), _payment(amount=Decimal("10.00"))],
    )
    assert result.total_paid == "10.00"
    assert result.duplicate_payment_events == 1
    assert any(alert.kind == "unreconciled" and "Duplicate" in alert.message for alert in result.alerts)


def test_full_refund_reverses_recorded_cash_and_partial_refund_is_not_guessed():
    refunded = _snapshot(
        invoices=[_invoice(status="refunded")],
        payments=[_payment(amount=Decimal("10.00"))],
    )
    partial = _snapshot(
        invoices=[_invoice(status="partially_refunded")],
        payments=[_payment(amount=Decimal("10.00"))],
    )
    assert refunded.total_paid == "0.00"
    assert refunded.refunds_reversed == "10.00"
    assert refunded.outstanding_receivables == "0.00"
    assert partial.total_paid == "0.00"
    assert partial.refunds_reversed == "0.00"
    assert partial.outstanding_receivables == "0.00"
    assert any("partially refunded" in alert.message for alert in partial.alerts)


def test_missing_records_produce_zero_figures_and_no_invented_insight():
    result = _snapshot()
    assert result.total_invoiced == "0.00"
    assert result.total_paid == "0.00"
    assert result.outstanding_receivables == "0.00"
    assert result.net_cash_flow_estimate is None
    assert result.projected_available is None
    assert result.paypal_balance_available is False
    assert result.paypal_balance_amount is None
    assert result.insights == []
    assert result.uncertainty


def test_future_invoice_amount_is_not_cash_received():
    result = _snapshot(invoices=[_invoice(status="sent", due_at=NOW + timedelta(days=2), amount=Decimal("25.00"))])
    assert result.total_paid == "0.00"
    assert result.confirmed_payments == "0.00"
    assert result.upcoming_expected_payments == "25.00"
    assert result.expected_payments == "25.00"


def test_paid_invoice_without_a_payment_record_is_unreconciled():
    result = _snapshot(invoices=[_invoice(status="marked_as_paid", amount=Decimal("15.00"))])
    assert result.total_paid == "0.00"
    assert any("no payment record" in alert.message for alert in result.alerts)


def test_opening_balance_date_ignores_earlier_payments_and_can_show_a_shortfall():
    early = _snapshot(
        invoices=[_invoice(status="paid", due_at=NOW - timedelta(days=10))],
        payments=[_payment(received_at=datetime(2026, 11, 1, tzinfo=UTC))],
        opening=OpeningBalance(Decimal("100.00"), datetime(2026, 11, 6, tzinfo=UTC).date()),
    )
    assert early.total_paid == "0.00"
    assert early.net_cash_flow_estimate == "100.00"

    short = _snapshot(
        opening=OpeningBalance(Decimal("100.00"), None),
        payouts=[
            PayoutFact("pay-1", Decimal("40.00"), "USD", "succeeded"),
            PayoutFact("pay-2", Decimal("80.00"), "USD", "pending_approval"),
        ],
        payments=[_payment(amount=Decimal("10.00"), invoice_id="paid")],
        invoices=[_invoice(id="paid", status="paid")],
    )
    assert short.total_paid == "10.00"
    assert short.completed_payouts == "40.00"
    assert short.pending_contractor_obligations == "80.00"
    assert short.net_cash_flow_estimate == "70.00"
    assert short.projected_available == "-10.00"
    assert any(
        "exceed projected available funds of USD 70.00" in insight.message for insight in short.insights
    )
    assert any(alert.kind == "cash_shortfall" for alert in short.alerts)
    assert any(alert.kind == "pending_approval" for alert in short.alerts)


def test_undated_expected_amounts_stay_out_of_the_projection():
    result = _snapshot(
        invoices=[_invoice(due_at=None, amount=Decimal("8.00"))],
        opening=OpeningBalance(Decimal("20.00"), None),
        milestones=[
            MilestoneFact("ms-1", "Design", Decimal("12.00"), "USD", "accepted", None, False),
            MilestoneFact("ms-2", "Build", Decimal("9.00"), "USD", "accepted", NOW.date(), True),
        ],
    )
    assert result.undated_expected_payments == "20.00"
    assert result.expected_payments == "0.00"
    assert result.projected_available == "20.00"
    assert all(entry.included is False or entry.direction == "outflow" for entry in result.projection)


def test_invoiced_milestone_is_not_added_again():
    result = _snapshot(
        invoices=[_invoice(amount=Decimal("30.00"), due_at=NOW + timedelta(days=1))],
        milestones=[MilestoneFact("ms", "Launch", Decimal("30.00"), "USD", "invoiced", NOW.date(), True)],
    )
    assert result.upcoming_expected_payments == "30.00"


def test_repeated_late_payments_name_the_customer_and_the_count():
    first_due = NOW - timedelta(days=20)
    second_due = NOW - timedelta(days=5)
    result = _snapshot(
        invoices=[
            _invoice(id="a", status="paid", due_at=first_due, customer_id="cust", customer_name="Acme"),
            _invoice(id="b", status="paid", due_at=second_due, customer_id="cust", customer_name="Acme"),
        ],
        payments=[
            _payment(invoice_id="a", external_id="A", received_at=first_due + timedelta(days=2)),
            _payment(invoice_id="b", external_id="B", received_at=second_due + timedelta(days=1)),
        ],
    )
    assert [insight.message for insight in result.insights] == ["Acme has paid after the due date 2 times."]
    assert result.insights[0].figures["late_payment_count"] == "2"


def test_a_payment_on_the_due_date_is_not_late():
    due = datetime(2026, 11, 1, 23, 0, tzinfo=UTC)
    result = _snapshot(
        invoices=[
            _invoice(id="a", status="paid", due_at=due, customer_id="cust", customer_name="Acme"),
            _invoice(id="b", status="paid", due_at=due, customer_id="cust", customer_name="Acme"),
        ],
        payments=[
            _payment(invoice_id="a", external_id="A", received_at=datetime(2026, 11, 1, 23, 30, tzinfo=UTC)),
            _payment(invoice_id="b", external_id="B", received_at=datetime(2026, 11, 1, 1, 0, tzinfo=UTC)),
        ],
    )
    assert result.insights == []


def test_failed_payout_and_scheduled_failure_are_alerts():
    result = _snapshot(
        payouts=[PayoutFact("pay", Decimal("5.00"), "USD", "denied", "DENIED", "recipient refused")],
        failures=[FailureFact("Scheduled invoice_reminder failed: timeout.")],
    )
    kinds = [alert.kind for alert in result.alerts]
    assert kinds.count("failed_action") == 2
    assert result.executed_expenses == "0.00"
    assert result.planned_expenses == "0.00"


def test_overdue_insight_cites_calculated_figures():
    result = _snapshot(
        invoices=[
            _invoice(id="a", amount=Decimal("12.00"), due_at=NOW - timedelta(days=2)),
            _invoice(id="b", amount=Decimal("8.00"), due_at=NOW - timedelta(days=1)),
        ]
    )
    overdue = next(insight for insight in result.insights if insight.kind == "overdue")
    assert overdue.message == "2 invoices are overdue, totaling USD 20.00."
    assert overdue.figures["overdue_receivables"] == "20.00"
    assert overdue.figures["overdue_count"] == "2"


def test_in_flight_and_undated_insights_reference_amounts():
    result = _snapshot(
        invoices=[_invoice(due_at=None, amount=Decimal("15.00"))],
        payouts=[PayoutFact("pay", Decimal("7.50"), "USD", "submitted")],
        opening=OpeningBalance(Decimal("100.00"), None),
    )
    kinds = {insight.kind for insight in result.insights}
    assert "in_flight" in kinds
    assert "undated_expected" in kinds
    assert any("USD 7.50" in insight.message for insight in result.insights)
    assert any(item.startswith("USD 15.00 of expected payments lacks a due date") for item in result.uncertainty)


def test_projection_assumptions_are_listed_when_opening_balance_exists():
    result = _snapshot(opening=OpeningBalance(Decimal("50.00"), None))
    assert any("opening balance" in line.lower() for line in result.assumptions)
    assert any("PayPal balance" in line or "PayPal account balance" in line for line in result.assumptions)
    assert result.uncertainty
