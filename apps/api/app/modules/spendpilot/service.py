"""Payout intents stay local until sandbox Payouts access is confirmed."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import financial_details, record
from app.core.config import Settings
from app.core.errors import (
    AppError,
    ConflictError,
    ExternalServiceError,
    IdempotencyConflictError,
    NotFoundError,
    PayPalCapabilityError,
    PolicyViolationError,
)
from app.core.money import parse_money
from app.integrations.paypal.capability import payout_capability
from app.integrations.paypal.client import PayPalClient
from app.integrations.paypal.errors import PayPalError
from app.integrations.paypal.payouts import PayoutsApi
from app.integrations.paypal.status import map_payout_batch_status
from app.modules.identity.deps import Principal
from app.modules.spendpilot.approvals import (
    assert_approver_authorized,
    assert_consumable,
    request_approval,
    transition_approval,
)
from app.modules.spendpilot.models import Approval, PayoutRequest
from app.modules.spendpilot.policy import ensure_allowed, get_policy
from app.modules.spendpilot.schemas import PayoutCapabilityOut, PayoutIntentCreate, PayoutRequestOut
from app.modules.trustflow.models import Contractor


async def get_payout_capability(settings: Settings, client: PayPalClient) -> PayoutCapabilityOut:
    scopes = None
    if settings.paypal_configured and settings.paypal_payouts_execution:
        try:
            token = await client.access_token()
            scopes = token.scopes
        except PayPalError:
            scopes = frozenset()
    capability = payout_capability(settings, scopes)
    return PayoutCapabilityOut(
        execution_enabled=capability.execution_enabled,
        reason=capability.reason,
        credentials_configured=capability.credentials_configured,
        scope_present=capability.scope_present,
    )


async def payout_out(session: AsyncSession, payout: PayoutRequest) -> PayoutRequestOut:
    reason = await session.scalar(select(Approval.decision_reason).where(Approval.payout_request_id == payout.id))
    body = PayoutRequestOut.model_validate(payout)
    return body.model_copy(update={"decision_reason": reason})


async def list_payout_requests(session: AsyncSession, principal: Principal) -> list[PayoutRequest]:
    rows = await session.scalars(
        select(PayoutRequest)
        .where(PayoutRequest.workspace_id == principal.workspace_id)
        .order_by(PayoutRequest.created_at.desc())
    )
    return list(rows)


async def create_payout_intent(
    session: AsyncSession,
    principal: Principal,
    body: PayoutIntentCreate,
    *,
    proposed_by_ai: bool = False,
) -> PayoutRequest:
    amount, currency = parse_money(body.amount, body.currency_code)
    contractor = await session.scalar(
        select(Contractor).where(
            Contractor.id == body.contractor_id, Contractor.workspace_id == principal.workspace_id
        )
    )
    if contractor is None:
        raise NotFoundError("Contractor not found.")
    recipient = (contractor.paypal_email or contractor.email).strip()
    key = (body.idempotency_key or str(uuid.uuid4())).strip()
    # The policy row is the workspace budget mutex. Hold it through reservation.
    await get_policy(session, principal.workspace_id, lock=True)
    existing = await session.scalar(
        select(PayoutRequest).where(
            PayoutRequest.workspace_id == principal.workspace_id, PayoutRequest.idempotency_key == key
        )
    )
    if existing is not None:
        if (
            existing.amount != amount or existing.contractor_id != contractor.id
            or existing.currency_code != currency or existing.recipient_email != recipient
            or existing.trigger_invoice_id != body.trigger_invoice_id
        ):
            raise IdempotencyConflictError("This idempotency key was already used for a different payout.")
        return existing
    try:
        await ensure_allowed(
            session,
            principal,
            action_type="payout",
            amount=amount,
            currency=currency,
            recipient=recipient,
            mode="prepare",
        )
    except PolicyViolationError as exc:
        _deny(session, principal, exc, mode="prepare")
        await session.commit()
        raise
    if body.trigger_invoice_id is not None:
        from app.modules.autopilot.models import Invoice

        invoice = await session.scalar(select(Invoice).where(
            Invoice.id == body.trigger_invoice_id, Invoice.workspace_id == principal.workspace_id
        ))
        if invoice is None:
            raise NotFoundError("Trigger invoice not found in this workspace.")
        if invoice.status not in {"paid", "marked_as_paid"}:
            raise PolicyViolationError("The client payment has not cleared.")
    payout = PayoutRequest(
        workspace_id=principal.workspace_id,
        contractor_id=contractor.id,
        currency_code=currency,
        amount=amount,
        status="pending_approval",
        idempotency_key=key,
        recipient_email=recipient,
        trigger_invoice_id=body.trigger_invoice_id,
    )
    session.add(payout)
    await session.flush()
    payout.sender_batch_id = str(payout.id)
    await request_approval(
        session,
        workspace_id=principal.workspace_id,
        user_id=principal.user_id,
        action_type="payout",
        recipient=recipient,
        amount=amount,
        currency=currency,
        target_type="payout_request",
        target_id=payout.id,
        payout_request_id=payout.id,
        reason=body.note,
        commit=False,
    )
    record(
        session,
        action="payout.intent_created",
        entity_type="payout_request",
        entity_id=payout.id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        details=financial_details(
            status="pending_approval",
            proposed_by_ai=proposed_by_ai,
            policy_evaluated="financial_policy",
            recipient_email=recipient,
            execution="not_attempted",
        ),
    )
    await session.commit()
    return payout


async def approve_payout(session: AsyncSession, principal: Principal, payout_id: uuid.UUID) -> PayoutRequest:
    return await transition_approval(session, principal, payout_id, "approve")


async def reject_payout(
    session: AsyncSession, principal: Principal, payout_id: uuid.UUID, reason: str
) -> PayoutRequest:
    return await transition_approval(session, principal, payout_id, "reject", reason)


async def cancel_payout(session: AsyncSession, principal: Principal, payout_id: uuid.UUID) -> PayoutRequest:
    return await transition_approval(session, principal, payout_id, "cancel")


async def expire_payout(session: AsyncSession, principal: Principal, payout_id: uuid.UUID) -> PayoutRequest:
    return await transition_approval(session, principal, payout_id, "expire")


async def execute_payout(
    session: AsyncSession, principal: Principal, payout_id: uuid.UUID, client: PayPalClient, settings: Settings
) -> PayoutRequest:
    workspace_id, actor_id = principal.workspace_id, principal.user_id
    try:
        return await _execute_payout(session, principal, payout_id, client, settings)
    except AppError as exc:
        await session.rollback()
        record(
            session, action="payout.execution_denied" if exc.status_code < 500 else "payout.execution_failed",
            entity_type="payout_request", entity_id=payout_id,
            workspace_id=workspace_id, actor_user_id=actor_id,
            details={"code": exc.code, "reason": exc.message},
        )
        await session.commit()
        raise


async def _execute_payout(
    session: AsyncSession, principal: Principal, payout_id: uuid.UUID, client: PayPalClient, settings: Settings
) -> PayoutRequest:
    if principal.role != "owner":
        raise PolicyViolationError("Only the workspace owner can execute a payout.")
    await get_policy(session, principal.workspace_id, lock=True)
    payout = await _locked_payout(session, principal, payout_id)
    if payout.paypal_payout_batch_id:
        return payout
    try:
        await ensure_allowed(
            session,
            principal,
            action_type="payout",
            amount=payout.amount,
            currency=payout.currency_code,
            recipient=payout.recipient_email,
            mode="execute",
        )
    except PolicyViolationError as exc:
        _deny(session, principal, exc, mode="execute")
        await session.commit()
        raise
    capability = await get_payout_capability(settings, client)
    if not capability.execution_enabled:
        payout.last_provider_error = capability.reason
        await session.commit()
        raise PayPalCapabilityError(capability.reason)
    if payout.status == "succeeded":
        return payout
    if payout.status not in {"approved", "submitted"}:
        raise ConflictError("Approve the payout before execution.")
    approval = await session.scalar(
        select(Approval).where(Approval.payout_request_id == payout.id).with_for_update()
    )
    if approval is None:
        raise ConflictError("A fresh owner approval is required before execution.")
    assert_consumable(approval, payout, now=datetime.now(UTC))
    if payout.trigger_invoice_id is not None:
        from app.modules.autopilot.models import Invoice

        trigger = await session.scalar(select(Invoice).where(
            Invoice.id == payout.trigger_invoice_id, Invoice.workspace_id == principal.workspace_id
        ).with_for_update())
        if trigger is None or trigger.status not in {"paid", "marked_as_paid"}:
            raise PolicyViolationError("The client payment is no longer cleared. The payout was not executed.")
    await assert_approver_authorized(session, approval)
    if not payout.recipient_email or not payout.sender_batch_id:
        raise ConflictError("This payout is missing a recipient or batch id.")
    # Durable, single-use authorization precedes the external side effect.
    # An interrupted/ambiguous submission must be reconciled, never resubmitted.
    approval.consumed_at = datetime.now(UTC)
    payout.status = "executing"
    record(
        session,
        action="payout.execution_started",
        entity_type="payout_request",
        entity_id=payout.id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        details=financial_details(
            status="executing",
            proposed_by_ai=False,
            approval_id=str(approval.id),
            approver_id=str(approval.decided_by_user_id) if approval.decided_by_user_id else None,
            policy_evaluated="exact_action_approval",
            paypal_operation="payouts.create_batch:pending",
            action_hash=approval.action_hash,
            sender_batch_id=payout.sender_batch_id,
        ),
    )
    await session.commit()
    try:
        result = await PayoutsApi(client).create_batch(
            sender_batch_id=payout.sender_batch_id,
            recipient_email=payout.recipient_email,
            currency_code=payout.currency_code,
            amount=payout.amount,
            idempotency_key=payout.sender_batch_id,
            note="Autopilot payout",
        )
    except PayPalError as exc:
        payout.status = "execution_unknown"
        payout.last_provider_error = exc.safe_message
        record(
            session,
            action="payout.execution_unknown",
            entity_type="payout_request",
            entity_id=payout.id,
            workspace_id=principal.workspace_id,
            actor_user_id=principal.user_id,
            details=financial_details(
                status="execution_unknown",
                proposed_by_ai=False,
                approval_id=str(approval.id),
                policy_evaluated="exact_action_approval",
                paypal_operation="payouts.create_batch:unknown",
                debug_id=exc.debug_id,
                reconciliation_required=True,
            ),
        )
        await session.commit()
        raise ExternalServiceError(exc.safe_message, details={"debug_id": exc.debug_id}) from exc
    header = result.body.get("batch_header") if isinstance(result.body.get("batch_header"), dict) else {}
    batch_id = header.get("payout_batch_id") if isinstance(header, dict) else None
    batch_status = header.get("batch_status") if isinstance(header, dict) else None
    if not isinstance(batch_id, str) or not batch_id.strip():
        payout.status = "execution_unknown"
        payout.last_provider_error = "PayPal did not return a payout batch id."
        record(
            session,
            action="payout.execution_unknown",
            entity_type="payout_request",
            entity_id=payout.id,
            workspace_id=principal.workspace_id,
            actor_user_id=principal.user_id,
            details=financial_details(
                status="execution_unknown",
                proposed_by_ai=False,
                approval_id=str(approval.id),
                policy_evaluated="exact_action_approval",
                paypal_operation="payouts.create_batch:missing_batch_id",
                reconciliation_required=True,
            ),
        )
        await session.commit()
        raise ExternalServiceError("PayPal did not return a payout batch id. The payout was not marked successful.")
    payout.paypal_payout_batch_id = batch_id
    payout.provider_status = batch_status.upper() if isinstance(batch_status, str) else "PENDING"
    payout.provider_details = {"payout_batch_id": batch_id, "batch_status": payout.provider_status}
    mapped = map_payout_batch_status(payout.provider_status)
    payout.status = mapped or "submitted"
    record(
        session,
        action="payout.submitted",
        entity_type="payout_request",
        entity_id=payout.id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        details=financial_details(
            status=payout.status,
            proposed_by_ai=False,
            approval_id=str(approval.id),
            policy_evaluated="exact_action_approval",
            paypal_operation=f"payouts.create_batch:{batch_id}",
            paypal_payout_batch_id=batch_id,
            provider_status=payout.provider_status,
        ),
    )
    await session.commit()
    return payout


async def sync_payout(
    session: AsyncSession, principal: Principal, payout_id: uuid.UUID, client: PayPalClient, settings: Settings
) -> PayoutRequest:
    payout = await _payout(session, principal, payout_id)
    if not payout.paypal_payout_batch_id:
        raise ConflictError("This payout has not been submitted to PayPal.")
    if not settings.paypal_configured:
        raise PayPalCapabilityError("PayPal sandbox credentials are not configured. Status was not refreshed.")
    try:
        result = await PayoutsApi(client).get_batch(payout.paypal_payout_batch_id)
    except PayPalError as exc:
        payout.last_provider_error = exc.safe_message
        await session.commit()
        raise ExternalServiceError(exc.safe_message, details={"debug_id": exc.debug_id}) from exc
    header = result.body.get("batch_header") if isinstance(result.body.get("batch_header"), dict) else {}
    batch_status = header.get("batch_status") if isinstance(header, dict) else None
    if isinstance(batch_status, str):
        payout.provider_status = batch_status.upper()
        mapped = map_payout_batch_status(batch_status)
        if mapped:
            payout.status = mapped
    payout.provider_details = {"payout_batch_id": payout.paypal_payout_batch_id, "batch_status": payout.provider_status}
    await session.commit()
    return payout


def _deny(session: AsyncSession, principal: Principal, exc: PolicyViolationError, *, mode: str) -> None:
    record(
        session,
        action="policy.denied",
        entity_type="financial_policy",
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        details={"mode": mode, "violations": exc.details.get("violations", [])},
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


async def _payout(session: AsyncSession, principal: Principal, payout_id: uuid.UUID) -> PayoutRequest:
    payout = await session.scalar(
        select(PayoutRequest).where(
            PayoutRequest.id == payout_id, PayoutRequest.workspace_id == principal.workspace_id
        )
    )
    if payout is None:
        raise NotFoundError("Payout request not found.")
    return payout
