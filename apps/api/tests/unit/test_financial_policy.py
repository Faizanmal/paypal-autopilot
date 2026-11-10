"""Policy decisions that do not need a database."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.modules.spendpilot.fingerprint import action_hash, approval_hash
from app.modules.spendpilot.models import FinancialPolicy
from app.modules.spendpilot.policy import AUTOPILOT, evaluate


def _policy(**overrides: object) -> FinancialPolicy:
    values: dict[str, object] = {
        "workspace_id": uuid.uuid4(),
        "require_payout_approval": True,
        "currency_code": "USD",
        "autonomy_level": 1,
        "allowed_currencies": ["USD"],
        "approved_recipients": [],
        "restricted_action_types": [],
    }
    values.update(overrides)
    return FinancialPolicy(**values)


def _decide(policy: FinancialPolicy, *, mode: str = "prepare", amount: str = "25.00", **kwargs: object):
    return evaluate(
        policy,
        action_type=str(kwargs.get("action_type", "payout")),
        amount=Decimal(amount),
        currency="USD",
        recipient=str(kwargs.get("recipient", "ada.paypal@example.com")),
        mode=mode,  # type: ignore[arg-type]
        spent_today=Decimal(str(kwargs.get("spent_today", "0.00"))),
        spent_month=Decimal(str(kwargs.get("spent_month", "0.00"))),
        spent_total=Decimal(str(kwargs.get("spent_total", "0.00"))),
    )


def test_action_hash_changes_when_the_amount_changes() -> None:
    workspace_id = uuid.uuid4()
    target_id = uuid.uuid4()
    shared = {
        "action_type": "payout",
        "recipient": "Ada.PayPal@example.com",
        "currency": "usd",
        "target_type": "payout_request",
        "target_id": target_id,
        "workspace_id": workspace_id,
    }
    first = action_hash(amount=Decimal("40.00"), **shared)
    same = action_hash(amount=Decimal("40.0"), **shared)
    changed = action_hash(amount=Decimal("40.01"), **shared)
    other_target = action_hash(amount=Decimal("40.00"), **{**shared, "target_id": uuid.uuid4()})
    assert first == same
    assert first != changed
    assert first != other_target
    approver = uuid.uuid4()
    assert approval_hash(first, approver) != approval_hash(first, uuid.uuid4())
    assert approval_hash(first, approver) != first


def test_assistant_can_prepare_and_cannot_execute() -> None:
    policy = _policy()
    prepared = _decide(policy, mode="prepare")
    executed = _decide(policy, mode="execute")
    assert prepared.allowed is True
    assert prepared.requires_approval is True
    assert executed.allowed is False
    assert "assistant mode" in executed.violations[0]


def test_autopilot_cannot_waive_payout_approval() -> None:
    policy = _policy(
        autonomy_level=AUTOPILOT,
        approval_threshold_amount=Decimal("10000.00"),
        delegated_action_types=["invoice"],
    )
    decision = _decide(policy, mode="execute", amount="10.00")
    assert decision.allowed is True
    assert decision.requires_approval is True
    invoice = evaluate(
        policy,
        action_type="invoice",
        amount=Decimal("10.00"),
        currency="USD",
        recipient="billing@acme.example",
        mode="execute",
        spent_today=Decimal("0.00"),
        spent_month=Decimal("0.00"),
        spent_total=Decimal("0.00"),
    )
    assert invoice.allowed is True
    assert invoice.requires_approval is False


def test_limits_pause_currency_recipient_and_restricted_actions() -> None:
    paused = _decide(_policy(paused_at=datetime.now(UTC)))
    assert paused.allowed is False
    assert "paused" in paused.violations[0]

    limited = _decide(_policy(per_transaction_limit=Decimal("1000.00")), amount="5000.00")
    assert limited.allowed is False
    assert "per-transaction limit" in limited.violations[0]
    assert limited.suggestion is not None
    assert "1000.00" in limited.suggestion

    daily = _decide(_policy(daily_limit=Decimal("50.00")), amount="20.00", spent_today="40.00")
    assert any("daily limit" in item for item in daily.violations)

    listed = _decide(_policy(approved_recipients=["other@example.com"]))
    assert listed.allowed is False
    assert "approved recipient" in listed.violations[0]
    open_list = _decide(_policy(approved_recipients=[]))
    assert open_list.allowed is True

    blocked_currency = _decide(_policy(allowed_currencies=[]))
    assert blocked_currency.allowed is False
    assert "not an allowed currency" in blocked_currency.violations[0]

    restricted = _decide(_policy(restricted_action_types=["payout"]))
    assert restricted.allowed is False
    assert "restricted" in restricted.violations[0]

    observer = _decide(_policy(autonomy_level=0))
    assert observer.allowed is False
    assert "observer mode" in observer.violations[0]


def test_autopilot_requires_explicit_delegation() -> None:
    policy = _policy(autonomy_level=AUTOPILOT, approval_threshold_amount=Decimal("100.00"))
    assert _decide(policy, action_type="invoice").requires_approval is True
    policy.delegated_action_types = ["invoice"]
    assert _decide(policy, action_type="invoice").requires_approval is False
    assert _decide(policy, action_type="invoice", amount="100.00").requires_approval is True
    policy.delegated_action_types = ["payout"]
    assert _decide(policy).requires_approval is True


@pytest.mark.parametrize("field,value", [
    ("amount", Decimal("25.01")), ("recipient_email", "other@example.com"),
    ("currency_code", "EUR"), ("workspace_id", uuid.uuid4()), ("id", uuid.uuid4()),
])
def test_consumption_rejects_changed_action(field, value) -> None:
    from app.core.errors import ConflictError
    from app.modules.spendpilot.approvals import assert_consumable
    from app.modules.spendpilot.models import Approval, PayoutRequest

    now = datetime.now(UTC)
    payout = PayoutRequest(
        id=uuid.uuid4(), workspace_id=uuid.uuid4(), amount=Decimal("25.00"),
        recipient_email="ada@example.com", currency_code="USD",
    )
    digest = action_hash(
        action_type="payout", recipient=payout.recipient_email, amount=payout.amount,
        currency="USD", target_type="payout_request", target_id=payout.id, workspace_id=payout.workspace_id,
    )
    approver = uuid.uuid4()
    approval = Approval(
        workspace_id=payout.workspace_id, target_id=payout.id, action_type="payout",
        target_type="payout_request", amount=payout.amount, currency_code="USD",
        recipient_email=payout.recipient_email, action_hash=digest, status="approved",
        decided_by_user_id=approver, approval_hash=approval_hash(digest, approver),
        expires_at=now.replace(year=now.year + 1),
    )
    assert_consumable(approval, payout, now=now)
    setattr(payout, field, value)
    with pytest.raises(ConflictError):
        assert_consumable(approval, payout, now=now)
