"""Approval requests bind to one action and can be consumed once."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import financial_details, record
from app.core.errors import AppError, ConflictError, NotFoundError, PolicyViolationError, ValidationFailedError
from app.modules.identity.deps import Principal
from app.modules.identity.models import User, WorkspaceMember
from app.modules.spendpilot.fingerprint import action_hash, approval_hash
from app.modules.spendpilot.models import Approval, PayoutRequest

OPEN_STATUSES = ("pending", "approved")
FRESH_APPROVAL = "This approval does not match the payout. Request a fresh approval."


async def request_approval(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    action_type: str,
    recipient: str,
    amount: Decimal,
    currency: str,
    target_type: str,
    target_id: uuid.UUID,
    payout_request_id: uuid.UUID | None,
    reason: str | None,
    commit: bool,
) -> Approval:
    digest = action_hash(
        action_type=action_type,
        recipient=recipient,
        amount=amount,
        currency=currency,
        target_type=target_type,
        target_id=target_id,
        workspace_id=workspace_id,
    )
    existing = await _open_approval(session, workspace_id, digest)
    if existing is not None:
        return existing
    approval = Approval(
        workspace_id=workspace_id,
        payout_request_id=payout_request_id,
        requested_by_user_id=user_id,
        status="pending",
        currency_code=currency,
        amount=amount,
        recipient_email=recipient,
        reason=reason,
        expires_at=datetime.now(UTC) + timedelta(days=7),
        action_type=action_type,
        target_type=target_type,
        target_id=target_id,
        action_hash=digest,
    )
    try:
        # A duplicate request must not roll back unrelated work in the caller.
        async with session.begin_nested():
            session.add(approval)
            await session.flush()
    except IntegrityError:
        existing = await _open_approval(session, workspace_id, digest)
        if existing is None:
            raise
        return existing
    record(
        session,
        action="approval.requested",
        entity_type="approval",
        entity_id=approval.id,
        workspace_id=workspace_id,
        actor_user_id=user_id,
        details=financial_details(
            status="pending",
            proposed_by_ai=False,
            approval_id=str(approval.id),
            policy_evaluated="exact_action_approval",
            action_type=action_type,
            action_hash=digest,
            target_id=str(target_id),
            target_type=target_type,
            amount=format(amount, "f"),
            currency=currency,
            recipient=recipient,
        ),
    )
    if commit:
        await session.commit()
    return approval


async def transition_approval(
    session: AsyncSession,
    principal: Principal,
    payout_id: uuid.UUID,
    decision: str,
    reason: str | None = None,
) -> PayoutRequest:
    workspace_id, actor_id = principal.workspace_id, principal.user_id
    try:
        return await _transition_approval(session, principal, payout_id, decision, reason)
    except AppError as exc:
        await session.rollback()
        record(
            session, action="approval.decision_denied", entity_type="payout_request", entity_id=payout_id,
            workspace_id=workspace_id, actor_user_id=actor_id,
            details={"decision": decision, "code": exc.code, "reason": exc.message},
        )
        await session.commit()
        raise


async def _transition_approval(
    session: AsyncSession, principal: Principal, payout_id: uuid.UUID, decision: str, reason: str | None
) -> PayoutRequest:
    payout = await _locked_payout(session, principal, payout_id)
    approval = await _locked_approval(session, payout)
    now = datetime.now(UTC)
    if decision == "approve":
        _require_owner(principal, "approve")
        if approval.status == "approved" and payout.status == "approved":
            assert_consumable(approval, payout, now=now)
            return payout
        _require_pending(approval)
        if approval.expires_at <= now:
            await _expire(session, principal, approval, payout)
            raise ConflictError("This approval has expired.")
        assert_matches(approval, payout)
        approval.status = "approved"
        approval.decided_by_user_id = principal.user_id
        approval.decided_at = now
        approval.approval_hash = approval_hash(approval.action_hash, principal.user_id)
        payout.status = "approved"
        _audit(
            session,
            principal,
            "payout.approved",
            payout.id,
            financial_details(
                status="approved",
                proposed_by_ai=False,
                approval_id=str(approval.id),
                approver_id=str(principal.user_id),
                policy_evaluated="exact_action_approval",
            ),
        )
        _audit(
            session,
            principal,
            "approval.approved",
            approval.id,
            financial_details(
                status="approved",
                proposed_by_ai=False,
                approval_id=str(approval.id),
                approver_id=str(principal.user_id),
                policy_evaluated="exact_action_approval",
                action_hash=approval.action_hash,
                approval_hash=approval.approval_hash,
                payout_request_id=str(payout.id),
            ),
        )
    elif decision == "reject":
        _require_owner(principal, "reject")
        if approval.status == "rejected":
            return payout
        _require_pending(approval)
        note = (reason or "").strip()
        if len(note) < 3:
            raise ValidationFailedError("A rejection needs a reason.")
        approval.status = "rejected"
        approval.decided_by_user_id = principal.user_id
        approval.decided_at = now
        approval.decision_reason = note
        _cancel_payout(payout)
        _audit(
            session,
            principal,
            "approval.rejected",
            approval.id,
            {"payout_request_id": str(payout.id), "reason": note},
        )
    elif decision == "cancel":
        if principal.role != "owner" and approval.requested_by_user_id != principal.user_id:
            raise PolicyViolationError("Only the requester or the workspace owner can cancel this approval.")
        if approval.status == "cancelled":
            return payout
        _require_revocable(approval)
        approval.status = "cancelled"
        approval.decided_by_user_id = principal.user_id
        approval.decided_at = now
        _cancel_payout(payout)
        _audit(session, principal, "approval.cancelled", approval.id, {"payout_request_id": str(payout.id)})
    elif decision == "expire":
        if principal.role != "owner" and approval.requested_by_user_id != principal.user_id:
            raise PolicyViolationError("Only the requester or the workspace owner can expire this approval.")
        if approval.status == "expired":
            return payout
        _require_revocable(approval)
        if approval.expires_at > now:
            raise ConflictError("This approval has not reached its expiry time.")
        await _expire(session, principal, approval, payout)
        return payout
    else:
        raise ConflictError("This approval decision is not supported.")
    await session.commit()
    return payout


def assert_consumable(approval: Approval, payout: PayoutRequest, *, now: datetime) -> None:
    assert_matches(approval, payout)
    if approval.workspace_id != payout.workspace_id or approval.target_id != payout.id:
        raise ConflictError(FRESH_APPROVAL)
    if approval.action_type != "payout" or approval.target_type != "payout_request":
        raise ConflictError(FRESH_APPROVAL)
    if approval.status != "approved" or approval.consumed_at is not None:
        raise ConflictError("A fresh owner approval is required before execution.")
    if approval.expires_at <= now:
        raise ConflictError("This approval has expired.")
    if approval.decided_by_user_id is None or not approval.approval_hash:
        raise ConflictError("A fresh owner approval is required before execution.")
    identity = approval_hash(approval.action_hash, approval.decided_by_user_id)
    if approval.approval_hash != identity:
        raise ConflictError(FRESH_APPROVAL)


def assert_matches(approval: Approval, payout: PayoutRequest) -> None:
    current = action_hash(
        action_type="payout",
        recipient=payout.recipient_email or "",
        amount=payout.amount,
        currency=payout.currency_code,
        target_type="payout_request",
        target_id=payout.id,
        workspace_id=payout.workspace_id,
    )
    same_terms = (
        approval.action_hash == current
        and approval.workspace_id == payout.workspace_id
        and approval.target_id == payout.id
        and approval.action_type == "payout"
        and approval.target_type == "payout_request"
        and approval.amount == payout.amount
        and approval.currency_code == payout.currency_code
        and approval.recipient_email.casefold() == (payout.recipient_email or "").casefold()
    )
    if not same_terms:
        raise ConflictError(FRESH_APPROVAL)


async def assert_approver_authorized(session: AsyncSession, approval: Approval) -> None:
    approver = await session.scalar(
        select(WorkspaceMember).join(User, User.id == WorkspaceMember.user_id).where(
            WorkspaceMember.workspace_id == approval.workspace_id,
            WorkspaceMember.user_id == approval.decided_by_user_id,
            WorkspaceMember.role == "owner", User.is_active.is_(True),
        )
    )
    if approver is None:
        raise ConflictError("The approving identity is no longer authorized. Request a fresh approval.")


async def _expire(session: AsyncSession, principal: Principal, approval: Approval, payout: PayoutRequest) -> None:
    approval.status = "expired"
    _cancel_payout(payout)
    _audit(session, principal, "approval.expired", approval.id, {"payout_request_id": str(approval.payout_request_id)})
    await session.commit()


async def _open_approval(session: AsyncSession, workspace_id: uuid.UUID, digest: str) -> Approval | None:
    return await session.scalar(
        select(Approval).where(
            Approval.workspace_id == workspace_id,
            Approval.action_hash == digest,
            Approval.status.in_(OPEN_STATUSES),
            Approval.consumed_at.is_(None),
        )
    )


async def _locked_payout(session: AsyncSession, principal: Principal, payout_id: uuid.UUID) -> PayoutRequest:
    payout = await session.scalar(
        select(PayoutRequest)
        .where(PayoutRequest.id == payout_id, PayoutRequest.workspace_id == principal.workspace_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if payout is None:
        raise NotFoundError("Payout request not found.")
    return payout


async def _locked_approval(session: AsyncSession, payout: PayoutRequest) -> Approval:
    approval = await session.scalar(
        select(Approval).where(Approval.payout_request_id == payout.id).with_for_update()
    )
    if approval is None or approval.workspace_id != payout.workspace_id:
        raise NotFoundError("Approval not found.")
    return approval


def _require_owner(principal: Principal, verb: str) -> None:
    if principal.role != "owner":
        raise PolicyViolationError(f"Only the workspace owner can {verb} a payout.")


def _require_pending(approval: Approval) -> None:
    if approval.status != "pending":
        raise ConflictError("This payout is not waiting for approval.")


def _cancel_payout(payout: PayoutRequest) -> None:
    if payout.status in {"pending_approval", "approved"}:
        payout.status = "canceled"


def _require_revocable(approval: Approval) -> None:
    if approval.status not in OPEN_STATUSES or approval.consumed_at is not None:
        raise ConflictError("This approval can no longer be revoked.")


def _audit(session: AsyncSession, principal: Principal, action: str, entity_id: uuid.UUID, details: dict) -> None:
    record(
        session,
        action=action,
        entity_type="payout_request" if action.startswith("payout.") else "approval",
        entity_id=entity_id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        details=details,
    )
