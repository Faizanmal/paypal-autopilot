"""Deterministic spending policy. This module never calls PayPal."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record
from app.core.config import SUPPORTED_CURRENCIES
from app.core.errors import NotFoundError, PolicyViolationError, ValidationFailedError
from app.modules.identity.deps import Principal
from app.modules.spendpilot.models import Approval, FinancialPolicy, PayoutRequest
from app.modules.spendpilot.schemas import PolicyUpdate

OBSERVER = 0
ASSISTANT = 1
OPERATOR = 2
AUTOPILOT = 3
AUTONOMY_NAMES = {OBSERVER: "observer", ASSISTANT: "assistant", OPERATOR: "operator", AUTOPILOT: "autopilot"}
COMMITTED_STATUSES = ("pending_approval", "approved", "executing", "execution_unknown", "submitted", "succeeded")
KNOWN_ACTIONS = frozenset({"payout", "invoice", "send_invoice", "project", "milestone", "order", "capture_order"})
Mode = Literal["prepare", "execute"]


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    requires_approval: bool
    violations: tuple[str, ...]
    suggestion: str | None
    autonomy_level: int


def evaluate(
    policy: FinancialPolicy,
    *,
    action_type: str,
    amount: Decimal,
    currency: str,
    recipient: str | None,
    mode: Mode,
    spent_today: Decimal,
    spent_month: Decimal,
    spent_total: Decimal,
    reserved_amount: Decimal = Decimal("0.00"),
) -> PolicyDecision:
    """Return every violation. A payout always requires its own approval."""
    violations: list[str] = []
    suggestion: str | None = None
    autonomy = policy.autonomy_level if policy.autonomy_level is not None else ASSISTANT
    code = currency.strip().upper()
    kind = action_type.strip().casefold()
    incoming = amount - reserved_amount

    if kind not in KNOWN_ACTIONS:
        violations.append("This financial action type is not supported.")
    if autonomy not in AUTONOMY_NAMES:
        violations.append("This workspace has an invalid autonomy level.")
    if not amount.is_finite() or amount <= 0:
        return PolicyDecision(False, True, ("The amount must be finite and positive.",), None, autonomy)

    if policy.paused_at is not None:
        violations.append(
            "This workspace is paused. No financial action can be prepared or executed until an owner ends the pause."
        )
        suggestion = "Ask an owner to end the emergency pause. The agent cannot change the pause."
    if autonomy == OBSERVER:
        violations.append("This workspace is in observer mode and can only read financial records.")
        suggestion = suggestion or (
            "An owner can raise the workspace out of observer mode. The agent cannot change autonomy."
        )
    elif mode == "execute" and autonomy < OPERATOR:
        violations.append(
            "This workspace is in assistant mode. It can prepare a payout, and an owner executes it only "
            "after raising autonomy to operator and approving the exact action."
        )
        suggestion = suggestion or (
            "An owner can raise autonomy to operator and approve the exact payout. "
            "The agent cannot approve or execute it."
        )

    stored_currencies = policy.allowed_currencies if policy.allowed_currencies is not None else ["USD"]
    allowed_currencies = [item.strip().upper() for item in stored_currencies]
    if code not in allowed_currencies:
        violations.append(f"{code} is not an allowed currency for this workspace.")
        suggestion = suggestion or "Use an allowed currency. This workspace accepts USD."

    restricted = {item.strip().casefold() for item in (policy.restricted_action_types or [])}
    if kind in restricted:
        violations.append(f"The action {kind} is restricted by this workspace policy.")
        suggestion = suggestion or "This action is restricted. The agent cannot remove the restriction."

    approved = [item.strip().casefold() for item in (policy.approved_recipients or [])]
    recipient_key = (recipient or "").strip().casefold()
    if approved and recipient_key not in approved:
        violations.append("This recipient is not on the approved recipient list.")
        suggestion = suggestion or (
            "Ask an owner to add this recipient or choose a recipient already on the list. "
            "The agent cannot change the list."
        )

    if policy.per_transaction_limit is not None and amount > policy.per_transaction_limit:
        limit = format(policy.per_transaction_limit, "f")
        violations.append(f"The amount exceeds the per-transaction limit of {limit} {code}.")
        suggestion = suggestion or f"Prepare {limit} {code} instead of {format(amount, 'f')} {code}."
    suggestion = _window_limit(
        violations,
        suggestion,
        label="daily limit",
        limit=policy.daily_limit,
        spent=spent_today + incoming,
        currency=code,
    )
    suggestion = _window_limit(
        violations,
        suggestion,
        label="monthly limit",
        limit=policy.monthly_limit,
        spent=spent_month + incoming,
        currency=code,
    )
    suggestion = _window_limit(
        violations,
        suggestion,
        label="workspace spending limit",
        limit=policy.workspace_spending_limit,
        spent=spent_total + incoming,
        currency=code,
    )

    requires_approval = True
    threshold = policy.approval_threshold_amount
    if (
        kind != "payout"
        and kind in (policy.delegated_action_types or [])
        and autonomy == AUTOPILOT
        and threshold is not None
        and amount < threshold
        and not violations
    ):
        requires_approval = False
    if kind == "payout":
        requires_approval = True

    return PolicyDecision(
        allowed=not violations,
        requires_approval=requires_approval,
        violations=tuple(violations),
        suggestion=suggestion,
        autonomy_level=autonomy,
    )


def _window_limit(
    violations: list[str],
    suggestion: str | None,
    *,
    label: str,
    limit: Decimal | None,
    spent: Decimal,
    currency: str,
) -> str | None:
    if limit is None or spent <= limit:
        return suggestion
    violations.append(f"The amount exceeds the {label} of {format(limit, 'f')} {currency}.")
    if suggestion is not None:
        return suggestion
    return f"Stay within the {label} of {format(limit, 'f')} {currency}."


async def get_policy(
    session: AsyncSession, workspace_id: uuid.UUID, *, lock: bool = False
) -> FinancialPolicy:
    statement = select(FinancialPolicy).where(FinancialPolicy.workspace_id == workspace_id)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    policy = await session.scalar(statement)
    if policy is None:
        raise NotFoundError("Financial policy not found.")
    return policy


async def ensure_workflow_enabled(
    session: AsyncSession, principal: Principal, action_type: str
) -> None:
    """Global stop switches also cover non-spending financial workflows."""
    policy = await get_policy(session, principal.workspace_id, lock=True)
    violations = []
    if policy.paused_at is not None:
        violations.append("This workspace is paused. Ask an owner to end the emergency pause.")
    if policy.autonomy_level == OBSERVER:
        violations.append("This workspace is in observer mode and can only read financial records.")
    if action_type in (policy.restricted_action_types or []):
        violations.append(f"The action {action_type} is restricted by this workspace policy.")
    if violations:
        record(
            session, action="policy.denied", entity_type="financial_policy", entity_id=policy.id,
            workspace_id=principal.workspace_id, actor_user_id=principal.user_id,
            details={"action_type": action_type, "violations": violations},
        )
        await session.commit()
        raise PolicyViolationError(violations[0], details={"violations": violations})


async def committed_spend(
    session: AsyncSession, workspace_id: uuid.UUID, currency: str
) -> tuple[Decimal, Decimal, Decimal]:
    now = datetime.now(UTC)
    start_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_month = start_day.replace(day=1)
    today = await _sum(session, workspace_id, currency, start_day)
    month = await _sum(session, workspace_id, currency, start_month)
    total = await _sum(session, workspace_id, currency, None)
    return today, month, total


async def ensure_allowed(
    session: AsyncSession,
    principal: Principal,
    *,
    action_type: str,
    amount: Decimal,
    currency: str,
    recipient: str | None,
    mode: Mode,
) -> PolicyDecision:
    policy = await get_policy(session, principal.workspace_id, lock=True)
    spent_today, spent_month, spent_total = await committed_spend(session, principal.workspace_id, currency)
    decision = evaluate(
        policy,
        action_type=action_type,
        amount=amount,
        currency=currency,
        recipient=recipient,
        mode=mode,
        spent_today=spent_today,
        spent_month=spent_month,
        spent_total=spent_total,
        reserved_amount=amount if mode == "execute" else Decimal("0.00"),
    )
    if decision.allowed:
        return decision
    message = decision.violations[0]
    if decision.suggestion:
        message = f"{message} {decision.suggestion}"
    raise PolicyViolationError(
        message,
        details={"violations": list(decision.violations), "suggestion": decision.suggestion, "mode": mode},
    )


async def update_policy(session: AsyncSession, principal: Principal, body: PolicyUpdate) -> FinancialPolicy:
    if principal.role != "owner":
        raise PolicyViolationError("Only the workspace owner can change financial policy.")
    policy = await get_policy(session, principal.workspace_id, lock=True)
    changes = body.model_dump(exclude_unset=True)
    paused = changes.pop("paused", None)
    if "autonomy_level" in changes:
        level = changes["autonomy_level"]
        if not isinstance(level, int):
            raise ValidationFailedError("Autonomy level must be an integer from 0 to 3.")
        policy.autonomy_level = level
    for field in (
        "per_transaction_limit",
        "daily_limit",
        "monthly_limit",
        "workspace_spending_limit",
        "approval_threshold_amount",
    ):
        if field in changes:
            setattr(policy, field, _money_limit(changes[field]))
    if "allowed_currencies" in changes and changes["allowed_currencies"] is not None:
        policy.allowed_currencies = _currencies(changes["allowed_currencies"])
    if "approved_recipients" in changes and changes["approved_recipients"] is not None:
        policy.approved_recipients = _recipients(changes["approved_recipients"])
    if "restricted_action_types" in changes and changes["restricted_action_types"] is not None:
        policy.restricted_action_types = _actions(changes["restricted_action_types"])
    if "delegated_action_types" in changes and changes["delegated_action_types"] is not None:
        delegated = _actions(changes["delegated_action_types"])
        if "payout" in delegated:
            raise PolicyViolationError("Payout execution cannot be delegated. Approve each exact payout.")
        policy.delegated_action_types = delegated
    if policy.require_payout_approval is not True:
        raise PolicyViolationError("Payouts always require approval of the exact action.")
    if paused is True:
        policy.paused_at = datetime.now(UTC)
        action = "policy.paused"
    elif paused is False:
        policy.paused_at = None
        action = "policy.resumed"
    else:
        action = "policy.updated"
    record(
        session,
        action=action,
        entity_type="financial_policy",
        entity_id=policy.id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        details={"changes": body.model_dump(mode="json", exclude_unset=True),
                 "autonomy_level": policy.autonomy_level, "paused": policy.paused_at is not None},
    )
    await session.commit()
    return policy


def _money_limit(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    quantized = value.quantize(Decimal("0.01"))
    if quantized != value or quantized < 0:
        raise ValidationFailedError("A spending limit must be a non-negative amount with at most 2 decimal places.")
    return quantized


def _currencies(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    for item in values:
        code = item.strip().upper()
        if code not in SUPPORTED_CURRENCIES:
            raise ValidationFailedError(f"Currency {code} is not supported. This workspace accepts USD.")
        if code not in cleaned:
            cleaned.append(code)
    return cleaned


def _recipients(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    for item in values:
        email = item.strip().casefold()
        if "@" not in email or len(email) > 320:
            raise ValidationFailedError("An approved recipient must be an email address.")
        if email not in cleaned:
            cleaned.append(email)
    return cleaned


def _actions(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    for item in values:
        kind = item.strip().casefold()
        if kind not in KNOWN_ACTIONS:
            raise ValidationFailedError(f"The action {kind} cannot be used in a policy.")
        if kind not in cleaned:
            cleaned.append(kind)
    return cleaned


async def _sum(
    session: AsyncSession, workspace_id: uuid.UUID, currency: str, since: datetime | None
) -> Decimal:
    statement = select(func.coalesce(func.sum(PayoutRequest.amount), 0)).outerjoin(
        Approval, Approval.payout_request_id == PayoutRequest.id
    ).where(
        PayoutRequest.workspace_id == workspace_id,
        PayoutRequest.currency_code == currency,
        PayoutRequest.status.in_(COMMITTED_STATUSES),
    )
    if since is not None:
        # Outstanding reservations count in every current window, including
        # intents prepared before midnight. Completed spend uses execution time.
        statement = statement.where(or_(
            PayoutRequest.status.in_(("pending_approval", "approved", "executing", "execution_unknown")),
            func.coalesce(Approval.consumed_at, PayoutRequest.created_at) >= since,
        ))
    value = await session.scalar(statement)
    return Decimal(value or 0).quantize(Decimal("0.01"))
