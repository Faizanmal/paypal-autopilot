"""Workspace-scoped invoice, checkout, and webhook workflows."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import financial_details, record
from app.core.config import Settings
from app.core.errors import (
    AppError,
    ConflictError,
    ExternalServiceError,
    IdempotencyConflictError,
    NotFoundError,
    PayPalNotConfiguredError,
    ValidationFailedError,
    WebhookProcessingError,
    WebhookVerificationError,
)
from app.core.money import parse_money
from app.integrations.paypal.client import PayPalClient
from app.integrations.paypal.errors import PayPalError
from app.integrations.paypal.invoicing import InvoicingApi, hosted_url
from app.integrations.paypal.orders import (
    OrdersApi,
    approval_url,
    authorization_from_order,
    capture_from_order,
)
from app.integrations.paypal.status import (
    capture_block_reason,
    invoice_status_from_event,
    map_invoice_status,
    map_order_status,
    next_invoice_status,
)
from app.modules.autopilot.models import CheckoutOrder, Invoice, PaymentRecord, WebhookEvent
from app.modules.autopilot.schemas import InvoiceCreate, OrderCreate
from app.modules.identity.deps import Principal
from app.modules.spendpilot.policy import ensure_workflow_enabled
from app.modules.trustflow.models import Customer, Milestone, Project
from app.modules.trustflow.transitions import refresh_project_status


class WebhookVerifier(Protocol):
    async def verify(self, raw_body: bytes, headers: Mapping[str, str]) -> None: ...


def _paypal_failure(exc: PayPalError) -> AppError:
    if exc.status_code is None and "not configured" in exc.message:
        return PayPalNotConfiguredError(exc.message)
    message = "PayPal request timed out." if "timed out" in exc.message.lower() else exc.safe_message
    return ExternalServiceError(
        message,
        details={"paypal_name": exc.name, "debug_id": exc.debug_id, "status_code": exc.status_code},
    )


def _require_paypal(settings: Settings) -> None:
    if not settings.paypal_configured:
        raise PayPalNotConfiguredError("PayPal sandbox credentials are not configured. No PayPal call was made.")


async def _customer(session: AsyncSession, principal: Principal, customer_id: uuid.UUID) -> Customer:
    customer = await session.scalar(
        select(Customer).where(Customer.id == customer_id, Customer.workspace_id == principal.workspace_id)
    )
    if customer is None:
        raise NotFoundError("Customer not found.")
    return customer


async def _invoice(session: AsyncSession, principal: Principal, invoice_id: uuid.UUID) -> Invoice:
    invoice = await session.scalar(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.workspace_id == principal.workspace_id)
    )
    if invoice is None:
        raise NotFoundError("Invoice not found.")
    return invoice


async def list_invoices(session: AsyncSession, principal: Principal) -> list[Invoice]:
    rows = await session.scalars(
        select(Invoice).where(Invoice.workspace_id == principal.workspace_id).order_by(Invoice.created_at.desc())
    )
    return list(rows)


async def get_invoice(session: AsyncSession, principal: Principal, invoice_id: uuid.UUID) -> Invoice:
    return await _invoice(session, principal, invoice_id)


async def list_invoice_payments(
    session: AsyncSession, principal: Principal, invoice_id: uuid.UUID
) -> list[PaymentRecord]:
    invoice = await _invoice(session, principal, invoice_id)
    rows = await session.scalars(
        select(PaymentRecord)
        .where(PaymentRecord.invoice_id == invoice.id, PaymentRecord.workspace_id == principal.workspace_id)
        .order_by(PaymentRecord.received_at.desc())
    )
    return list(rows)


async def create_invoice(
    session: AsyncSession,
    principal: Principal,
    body: InvoiceCreate,
    client: PayPalClient,
    settings: Settings,
) -> Invoice:
    await ensure_workflow_enabled(session, principal, "invoice")
    _require_paypal(settings)
    if not settings.paypal_sandbox_business_email.strip():
        raise ValidationFailedError("PAYPAL_SANDBOX_BUSINESS_EMAIL is not configured.")
    amount, currency = parse_money(body.amount, body.currency_code)
    customer = await _customer(session, principal, body.customer_id)
    milestone = None
    if body.milestone_id is not None:
        milestone = await session.scalar(
            select(Milestone).where(Milestone.id == body.milestone_id, Milestone.workspace_id == principal.workspace_id)
        )
        if milestone is None:
            raise NotFoundError("Milestone not found.")
        if body.project_id is not None and body.project_id != milestone.project_id:
            raise ValidationFailedError("The milestone does not belong to that project.")
        body = body.model_copy(update={"project_id": milestone.project_id})
    if body.project_id is not None:
        project = await session.scalar(
            select(Project).where(Project.id == body.project_id, Project.workspace_id == principal.workspace_id)
        )
        if project is None:
            raise NotFoundError("Project not found.")
        if milestone is not None and project.customer_id != customer.id:
            raise ValidationFailedError("The invoice customer must be the customer on the project.")
    key = (body.idempotency_key or str(uuid.uuid4())).strip()
    customer_id = customer.id
    recipient_email = customer.billing_email or customer.email
    recipient_name = customer.name
    existing = await session.scalar(
        select(Invoice).where(Invoice.workspace_id == principal.workspace_id, Invoice.idempotency_key == key)
    )
    if milestone is not None:
        linked = await session.scalar(select(Invoice).where(Invoice.milestone_id == milestone.id))
        if linked is not None and (existing is None or linked.id != existing.id):
            if existing is not None:
                raise ConflictError("This milestone already has an invoice.")
            existing = linked
    if existing is not None:
        if (
            existing.amount != amount
            or existing.customer_id != customer_id
            or existing.milestone_id != body.milestone_id
        ):
            raise IdempotencyConflictError("This idempotency key was already used for a different invoice.")
        if existing.paypal_invoice_id:
            await _mark_milestone_invoiced(session, principal.workspace_id, milestone)
            await session.commit()
            return existing
        invoice = existing
    else:
        if customer.archived_at is not None:
            raise ValidationFailedError("Archived customers cannot receive a new invoice.")
        if milestone is not None and milestone.status != "accepted":
            raise ValidationFailedError("Only an accepted milestone can generate an invoice draft.")
        invoice = Invoice(
            workspace_id=principal.workspace_id,
            customer_id=customer_id,
            project_id=body.project_id,
            milestone_id=body.milestone_id,
            currency_code=currency,
            amount=amount,
            status="draft",
            idempotency_key=key,
        )
        session.add(invoice)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            recovered = await _invoice_for_duplicate(session, principal.workspace_id, key, body.milestone_id)
            if recovered is None:
                raise
            if (
                recovered.amount != amount
                or recovered.customer_id != customer_id
                or recovered.milestone_id != body.milestone_id
            ):
                raise IdempotencyConflictError(
                    "This idempotency key was already used for a different invoice."
                ) from None
            if recovered.paypal_invoice_id:
                if body.milestone_id is not None:
                    fresh = await session.scalar(
                        select(Milestone).where(
                            Milestone.id == body.milestone_id,
                            Milestone.workspace_id == principal.workspace_id,
                        )
                    )
                    await _mark_milestone_invoiced(session, principal.workspace_id, fresh)
                    await session.commit()
                return recovered
            invoice = recovered
            if body.milestone_id is not None:
                milestone = await session.scalar(
                    select(Milestone).where(
                        Milestone.id == body.milestone_id,
                        Milestone.workspace_id == principal.workspace_id,
                    )
                )

    paypal_key = invoice.idempotency_key or key
    try:
        result = await InvoicingApi(client).create_draft(
            invoicer_email=settings.paypal_sandbox_business_email.strip(),
            recipient_email=recipient_email,
            recipient_name=recipient_name,
            currency_code=currency,
            amount=amount,
            description=body.description,
            idempotency_key=paypal_key,
        )
    except PayPalError as exc:
        invoice.last_provider_error = exc.safe_message
        await session.commit()
        raise _paypal_failure(exc) from exc

    paypal_id = result.body.get("id")
    if not isinstance(paypal_id, str) or not paypal_id:
        invoice.last_provider_error = "PayPal did not return an invoice id."
        await session.commit()
        raise ExternalServiceError("PayPal did not return an invoice id.")
    _apply_invoice_body(invoice, result.body)
    if milestone is not None and invoice.paypal_invoice_id and milestone.status == "accepted":
        await _mark_milestone_invoiced(session, principal.workspace_id, milestone)
    record(
        session,
        action="invoice.paypal_draft_created",
        entity_type="invoice",
        entity_id=invoice.id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        details=financial_details(
            status=invoice.status,
            proposed_by_ai=False,
            approval_id="not required: draft",
            policy_evaluated="policy: invoice_draft_allowed",
            paypal_operation=f"invoicing.create:{paypal_id}",
            paypal_invoice_id=paypal_id,
            provider_status=invoice.provider_status,
        ),
    )
    await session.commit()
    return invoice


async def _mark_milestone_invoiced(session: AsyncSession, workspace_id: uuid.UUID, milestone: Milestone | None) -> None:
    if milestone is None or milestone.status != "accepted":
        return
    milestone.status = "invoiced"
    await refresh_project_status(session, workspace_id, milestone.project_id)


async def _invoice_for_duplicate(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    idempotency_key: str,
    milestone_id: uuid.UUID | None,
) -> Invoice | None:
    if milestone_id is not None:
        linked = await session.scalar(select(Invoice).where(Invoice.milestone_id == milestone_id))
        if linked is not None and linked.workspace_id == workspace_id:
            return linked
    return await session.scalar(
        select(Invoice).where(Invoice.workspace_id == workspace_id, Invoice.idempotency_key == idempotency_key)
    )


def _apply_invoice_body(invoice: Invoice, body: dict[str, Any]) -> bool:
    provider_status = body.get("status") if isinstance(body.get("status"), str) else None
    status, applied = next_invoice_status(invoice.status, provider_status)
    invoice.status = status
    if applied and provider_status:
        invoice.provider_status = provider_status.upper()
    summary = body.get("_summary")
    if isinstance(summary, dict):
        invoice.provider_details = summary
    else:
        invoice.provider_details = {"id": body.get("id"), "status": provider_status}
    link = hosted_url(body)
    if link:
        invoice.hosted_url = link
    paypal_id = body.get("id")
    if isinstance(paypal_id, str):
        invoice.paypal_invoice_id = invoice.paypal_invoice_id or paypal_id
    invoice.last_synced_at = datetime.now(UTC)
    invoice.last_provider_error = None
    return applied


async def _sync_invoice(session: AsyncSession, invoice: Invoice, client: PayPalClient) -> Invoice:
    if not invoice.paypal_invoice_id:
        raise ConflictError("This invoice has not been created in PayPal.")
    try:
        result = await InvoicingApi(client).get_invoice(invoice.paypal_invoice_id)
    except PayPalError as exc:
        invoice.last_provider_error = exc.safe_message
        await session.commit()
        raise _paypal_failure(exc) from exc
    applied = _apply_invoice_body(invoice, result.body)
    if applied and invoice.status in {"paid", "marked_as_paid"}:
        await _ensure_payment(session, invoice, invoice.paypal_invoice_id)
        if invoice.milestone_id is not None:
            from app.modules.trustflow.transitions import record_milestone_paid

            await record_milestone_paid(session, invoice.workspace_id, invoice.milestone_id)
        from app.modules.workflows.engine import on_invoice_paid

        # Same side effects as INVOICING.INVOICE.PAID (cancel reminders, resume waits).
        await on_invoice_paid(session, invoice)
    return invoice


async def send_invoice(
    session: AsyncSession, principal: Principal, invoice_id: uuid.UUID, client: PayPalClient, settings: Settings
) -> Invoice:
    await ensure_workflow_enabled(session, principal, "send_invoice")
    _require_paypal(settings)
    invoice = await _invoice(session, principal, invoice_id)
    if not invoice.paypal_invoice_id:
        raise ConflictError("This invoice has not been created in PayPal.")
    key = invoice.idempotency_key or str(invoice.id)
    try:
        send_result = await InvoicingApi(client).send_invoice(invoice.paypal_invoice_id, idempotency_key=f"{key}:send")
    except PayPalError as exc:
        invoice.last_provider_error = exc.safe_message
        await session.commit()
        raise _paypal_failure(exc) from exc
    payer_link = hosted_url(send_result.body)
    await _sync_invoice(session, invoice, client)
    if payer_link:
        invoice.hosted_url = payer_link

    record(
        session,
        action="invoice.paypal_sent",
        entity_type="invoice",
        entity_id=invoice.id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        details=financial_details(
            status=invoice.status,
            proposed_by_ai=False,
            paypal_operation=(
                f"invoicing.send:{invoice.paypal_invoice_id}" if invoice.paypal_invoice_id else "invoicing.send"
            ),
            paypal_invoice_id=invoice.paypal_invoice_id,
            provider_status=invoice.provider_status,
        ),
    )
    await session.commit()
    return invoice


async def remind_invoice(
    session: AsyncSession,
    principal: Principal,
    invoice_id: uuid.UUID,
    client: PayPalClient,
    settings: Settings,
    *,
    idempotency_key: str | None = None,
) -> Invoice:
    await ensure_workflow_enabled(session, principal, "send_invoice")
    _require_paypal(settings)
    invoice = await _invoice(session, principal, invoice_id)
    if not invoice.paypal_invoice_id:
        raise ConflictError("This invoice has not been created in PayPal.")
    now = datetime.now(UTC)
    window = invoice.reminder_window_started_at
    if window is not None and window.date() == now.date() and invoice.reminders_sent >= 2:
        raise ValidationFailedError("PayPal allows at most 2 reminders for an invoice per day.")
    if window is None or window.date() != now.date():
        invoice.reminders_sent = 0
        invoice.reminder_window_started_at = now
    key = idempotency_key or f"{invoice.idempotency_key or invoice.id}:remind:{invoice.reminders_sent + 1}"
    try:
        await InvoicingApi(client).remind(invoice.paypal_invoice_id, idempotency_key=key)
    except PayPalError as exc:
        invoice.last_provider_error = exc.safe_message
        await session.commit()
        raise _paypal_failure(exc) from exc
    invoice.reminders_sent += 1
    await session.commit()
    return invoice


async def sync_invoice_from_provider(session: AsyncSession, invoice: Invoice, client: PayPalClient) -> bool:
    """Refresh one local invoice from PayPal. Returns true when PayPal reports it paid."""
    await _sync_invoice(session, invoice, client)
    return invoice.status in {"paid", "marked_as_paid"}


async def sync_invoice(
    session: AsyncSession, principal: Principal, invoice_id: uuid.UUID, client: PayPalClient, settings: Settings
) -> Invoice:
    _require_paypal(settings)
    invoice = await _invoice(session, principal, invoice_id)
    await _sync_invoice(session, invoice, client)
    await session.commit()
    return invoice


async def sync_known_invoices(
    session: AsyncSession, principal: Principal, client: PayPalClient, settings: Settings
) -> list[Invoice]:
    """Refresh local invoices from PayPal. Unknown PayPal invoices are not imported."""
    _require_paypal(settings)
    local = await list_invoices(session, principal)
    by_paypal = {row.paypal_invoice_id: row for row in local if row.paypal_invoice_id}
    if not by_paypal:
        return local
    try:
        listed = await InvoicingApi(client).list_invoices(page_size=100)
    except PayPalError as exc:
        raise _paypal_failure(exc) from exc
    items = listed.body.get("items")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"] in by_paypal:
                invoice = by_paypal[item["id"]]
                applied = _apply_invoice_body(invoice, item)
                if applied and invoice.status in {"paid", "marked_as_paid"} and invoice.paypal_invoice_id:
                    await _ensure_payment(session, invoice, invoice.paypal_invoice_id)
                    from app.modules.workflows.engine import on_invoice_paid

                    await on_invoice_paid(session, invoice)
    await session.commit()
    return await list_invoices(session, principal)


async def _ensure_payment(session: AsyncSession, invoice: Invoice, external_id: str) -> None:
    existing = await session.scalar(
        select(PaymentRecord.id).where(PaymentRecord.invoice_id == invoice.id, PaymentRecord.external_id == external_id)
    )
    if existing is not None:
        return
    session.add(
        PaymentRecord(
            workspace_id=invoice.workspace_id,
            invoice_id=invoice.id,
            currency_code=invoice.currency_code,
            amount=invoice.amount,
            source="paypal",
            external_id=external_id,
            received_at=datetime.now(UTC),
        )
    )


async def list_orders(session: AsyncSession, principal: Principal) -> list[CheckoutOrder]:
    rows = await session.scalars(
        select(CheckoutOrder)
        .where(CheckoutOrder.workspace_id == principal.workspace_id)
        .order_by(CheckoutOrder.created_at.desc())
    )
    return list(rows)


async def _order(session: AsyncSession, principal: Principal, order_id: uuid.UUID) -> CheckoutOrder:
    order = await session.scalar(
        select(CheckoutOrder).where(CheckoutOrder.id == order_id, CheckoutOrder.workspace_id == principal.workspace_id)
    )
    if order is None:
        raise NotFoundError("Checkout order not found.")
    return order


def _apply_order_body(order: CheckoutOrder, body: dict[str, Any]) -> None:
    provider_status = body.get("status") if isinstance(body.get("status"), str) else None
    if provider_status:
        order.provider_status = provider_status.upper()
        mapped = map_order_status(provider_status)
        if mapped != "unknown":
            order.status = mapped
    paypal_id = body.get("id")
    if isinstance(paypal_id, str):
        order.paypal_order_id = paypal_id
    link = approval_url(body)
    if link:
        order.approval_url = link
    capture_id, capture_status = capture_from_order(body)
    if capture_id:
        order.capture_id = capture_id
    if capture_status:
        order.capture_status = capture_status
        if capture_status.upper() == "COMPLETED":
            order.status = "completed"
    auth_id, auth_status = authorization_from_order(body)
    if auth_id:
        order.authorization_id = auth_id
    if auth_status:
        order.authorization_status = auth_status
        if order.intent == "AUTHORIZE" and auth_status.upper() == "CREATED" and order.status != "completed":
            order.status = "authorized"
    order.provider_details = {
        "id": order.paypal_order_id,
        "status": order.provider_status,
        "intent": body.get("intent"),
    }
    order.last_synced_at = datetime.now(UTC)
    order.last_provider_error = None


async def create_order(
    session: AsyncSession,
    principal: Principal,
    body: OrderCreate,
    client: PayPalClient,
    settings: Settings,
) -> CheckoutOrder:
    await ensure_workflow_enabled(session, principal, "order")
    _require_paypal(settings)
    amount, currency = parse_money(body.amount, body.currency_code)
    key = (body.idempotency_key or str(uuid.uuid4())).strip()
    existing = await session.scalar(
        select(CheckoutOrder).where(
            CheckoutOrder.workspace_id == principal.workspace_id, CheckoutOrder.idempotency_key == key
        )
    )
    if existing is not None:
        if existing.amount != amount or existing.intent != body.intent:
            raise IdempotencyConflictError("This idempotency key was already used for a different order.")
        if existing.paypal_order_id:
            return existing
        order = existing
    else:
        order = CheckoutOrder(
            workspace_id=principal.workspace_id,
            intent=body.intent,
            currency_code=currency,
            amount=amount,
            description=body.description,
            status="created",
            idempotency_key=key,
        )
        session.add(order)
        await session.flush()
    try:
        result = await OrdersApi(client).create_order(
            intent=body.intent,
            currency_code=currency,
            amount=amount,
            description=body.description,
            idempotency_key=key,
        )
    except PayPalError as exc:
        order.last_provider_error = exc.safe_message
        await session.commit()
        raise _paypal_failure(exc) from exc
    if not isinstance(result.body.get("id"), str):
        order.last_provider_error = "PayPal did not return an order id."
        await session.commit()
        raise ExternalServiceError("PayPal did not return an order id.")
    _apply_order_body(order, result.body)
    if not order.approval_url and order.provider_status not in {"APPROVED", "COMPLETED"}:
        order.last_provider_error = "PayPal did not return a buyer approval link."
    await session.commit()
    return order


async def sync_order(
    session: AsyncSession, principal: Principal, order_id: uuid.UUID, client: PayPalClient, settings: Settings
) -> CheckoutOrder:
    _require_paypal(settings)
    order = await _order(session, principal, order_id)
    if not order.paypal_order_id:
        raise ConflictError("This checkout has not been created in PayPal.")
    try:
        result = await OrdersApi(client).get_order(order.paypal_order_id)
    except PayPalError as exc:
        order.last_provider_error = exc.safe_message
        await session.commit()
        raise _paypal_failure(exc) from exc
    _apply_order_body(order, result.body)
    await session.commit()
    return order


async def capture_order(
    session: AsyncSession, principal: Principal, order_id: uuid.UUID, client: PayPalClient, settings: Settings
) -> CheckoutOrder:
    """Capture only after PayPal reports buyer approval. This never approves on the buyer's behalf."""
    await ensure_workflow_enabled(session, principal, "capture_order")
    _require_paypal(settings)
    order = await _order(session, principal, order_id)
    if not order.paypal_order_id:
        raise ConflictError("This checkout has not been created in PayPal.")
    api = OrdersApi(client)
    try:
        current = await api.get_order(order.paypal_order_id)
    except PayPalError as exc:
        order.last_provider_error = exc.safe_message
        await session.commit()
        raise _paypal_failure(exc) from exc
    _apply_order_body(order, current.body)
    if (order.provider_status or "").upper() == "COMPLETED" or (order.capture_status or "").upper() == "COMPLETED":
        await session.commit()
        return order
    reason = capture_block_reason(
        intent=order.intent,
        provider_status=order.provider_status,
        authorization_status=order.authorization_status,
    )
    if reason:
        await session.commit()
        raise ConflictError(
            reason,
            details={"approval_url": order.approval_url, "provider_status": order.provider_status},
        )
    try:
        if order.intent == "AUTHORIZE" and (order.authorization_status or "").upper() != "CREATED":
            result = await api.authorize_order(
                order.paypal_order_id,
                idempotency_key=f"{order.idempotency_key}:authorize",
            )
        elif order.intent == "AUTHORIZE" and order.authorization_id:
            result = await api.capture_authorization(
                order.authorization_id, idempotency_key=f"{order.idempotency_key}:capture-auth"
            )
        else:
            result = await api.capture_order(order.paypal_order_id, idempotency_key=f"{order.idempotency_key}:capture")
    except PayPalError as exc:
        order.last_provider_error = exc.safe_message
        await session.commit()
        raise _paypal_failure(exc) from exc
    _apply_order_body(order, result.body)
    await session.commit()
    return order


def _resource(payload: dict[str, Any]) -> dict[str, Any]:
    resource = payload.get("resource")
    return resource if isinstance(resource, dict) else {}


def _event_resource_id(resource: dict[str, Any]) -> str | None:
    if isinstance(resource.get("id"), str):
        return resource["id"]
    invoice = resource.get("invoice")
    if isinstance(invoice, dict) and isinstance(invoice.get("id"), str):
        return invoice["id"]
    header = resource.get("batch_header")
    if isinstance(header, dict) and isinstance(header.get("payout_batch_id"), str):
        return header["payout_batch_id"]
    if isinstance(resource.get("payout_batch_id"), str):
        return resource["payout_batch_id"]
    return None


async def ingest_webhook(
    session: AsyncSession,
    *,
    raw_body: bytes,
    headers: Mapping[str, str],
    verifier: WebhookVerifier,
    webhook_id: str,
) -> dict[str, str]:
    await verifier.verify(raw_body, headers)
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise WebhookVerificationError("PayPal webhook body is not JSON.") from exc
    if not isinstance(payload, dict):
        raise WebhookVerificationError("PayPal webhook body is not an object.")
    event_id = payload.get("id")
    event_type = payload.get("event_type")
    if not isinstance(event_id, str) or not isinstance(event_type, str):
        raise WebhookVerificationError("PayPal webhook is missing an event id.")
    configured_id = webhook_id.strip() or "unconfigured"
    await _ensure_event(session, configured_id, event_id, event_type, payload)
    existing = await session.scalar(
        select(WebhookEvent)
        .where(WebhookEvent.webhook_id == configured_id, WebhookEvent.event_id == event_id)
        .with_for_update()
    )
    if existing is None:
        raise WebhookProcessingError("PayPal webhook was verified but could not be stored.")
    if existing.processing_status == "processed":
        return {"status": "duplicate", "event_id": event_id}
    try:
        note = await _apply_webhook(session, existing)
        existing.processing_status = "processed"
        existing.processed_at = datetime.now(UTC)
        existing.last_error = note
        await session.commit()
    except Exception as exc:
        await session.rollback()
        failed = await session.scalar(
            select(WebhookEvent)
            .where(WebhookEvent.webhook_id == configured_id, WebhookEvent.event_id == event_id)
            .with_for_update()
        )
        if failed is not None and failed.processing_status != "processed":
            failed.processing_status = "failed"
            failed.attempts = (failed.attempts or 0) + 1
            failed.last_error = type(exc).__name__
            await session.commit()
        else:
            await session.rollback()
        raise WebhookProcessingError("PayPal webhook was stored but not applied.") from exc
    return {"status": "processed", "event_id": event_id}


async def _ensure_event(
    session: AsyncSession, webhook_id: str, event_id: str, event_type: str, payload: dict[str, Any]
) -> None:
    existing = await session.scalar(
        select(WebhookEvent).where(WebhookEvent.webhook_id == webhook_id, WebhookEvent.event_id == event_id)
    )
    if existing is not None:
        return
    row = WebhookEvent(
        webhook_id=webhook_id,
        event_id=event_id,
        event_type=event_type,
        payload=payload,
        processing_status="received",
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await session.scalar(
            select(WebhookEvent).where(WebhookEvent.webhook_id == webhook_id, WebhookEvent.event_id == event_id)
        )
        if existing is None:
            raise
        return
    return


async def _apply_webhook(session: AsyncSession, event: WebhookEvent) -> str | None:
    resource = _resource(event.payload)
    resource_id = _event_resource_id(resource)
    if event.event_type.startswith("INVOICING.INVOICE."):
        return await _apply_invoice_event(session, event, resource, resource_id)
    if event.event_type in {"CHECKOUT.ORDER.APPROVED", "CHECKOUT.ORDER.COMPLETED"} or event.event_type.startswith(
        "PAYMENT.CAPTURE."
    ):
        return await _apply_order_event(session, event, resource)
    if event.event_type.startswith("PAYMENT.PAYOUT"):
        return await _apply_payout_event(session, event, resource, resource_id)
    return "ignored_unsupported_event"


async def _apply_invoice_event(
    session: AsyncSession, event: WebhookEvent, resource: dict[str, Any], resource_id: str | None
) -> str | None:
    if not resource_id:
        return "unmatched"
    invoice = await session.scalar(select(Invoice).where(Invoice.paypal_invoice_id == resource_id))
    if invoice is None:
        return "unmatched"
    event.workspace_id = invoice.workspace_id
    provider_status: str | None
    if event.event_type == "INVOICING.INVOICE.PAID":
        verified = await _verified_paid_status(resource_id)
        if verified is None:
            return "provider_not_paid"
        provider_status = verified
    else:
        provider_status = invoice_status_from_event(
            event.event_type, resource.get("status") if isinstance(resource.get("status"), str) else None
        )
    status, applied = next_invoice_status(invoice.status, provider_status)
    invoice.status = status
    if applied and provider_status:
        invoice.provider_status = provider_status
    invoice.last_synced_at = datetime.now(UTC)
    if invoice.status in {"paid", "marked_as_paid"}:
        await _ensure_payment(session, invoice, resource_id)
        if invoice.milestone_id is not None:
            from app.modules.trustflow.transitions import record_milestone_paid

            await record_milestone_paid(session, invoice.workspace_id, invoice.milestone_id)
        from app.modules.workflows.engine import on_invoice_paid

        await on_invoice_paid(session, invoice)
    if not applied:
        return "ignored_out_of_order"
    return None


async def _verified_paid_status(paypal_invoice_id: str) -> str | None:
    """Read the invoice from PayPal. A paid webhook is applied only when PayPal agrees."""
    from app.core.config import get_settings
    from app.integrations.paypal.client import get_paypal_client

    _require_paypal(get_settings())
    result = await InvoicingApi(get_paypal_client()).get_invoice(paypal_invoice_id)
    status = result.body.get("status") if isinstance(result.body, dict) else None
    if not isinstance(status, str):
        return None
    if map_invoice_status(status) not in {"paid", "marked_as_paid"}:
        return None
    return status.upper()


async def _apply_order_event(session: AsyncSession, event: WebhookEvent, resource: dict[str, Any]) -> str | None:
    order_id = None
    supplementary = resource.get("supplementary_data")
    if isinstance(supplementary, dict):
        related = supplementary.get("related_ids")
        if isinstance(related, dict) and isinstance(related.get("order_id"), str):
            order_id = related["order_id"]
    if order_id is None and event.event_type.startswith("CHECKOUT.ORDER.") and isinstance(resource.get("id"), str):
        order_id = resource["id"]
    if order_id is None:
        return "unmatched"
    order = await session.scalar(select(CheckoutOrder).where(CheckoutOrder.paypal_order_id == order_id))
    if order is None:
        return "unmatched"
    event.workspace_id = order.workspace_id
    if event.event_type == "PAYMENT.CAPTURE.COMPLETED":
        capture_id = resource.get("id") if isinstance(resource.get("id"), str) else None
        raw_status = resource.get("status")
        capture_status = raw_status if isinstance(raw_status, str) else "COMPLETED"
        if capture_id:
            order.capture_id = capture_id
        order.capture_status = capture_status
        if capture_status.upper() == "COMPLETED":
            order.provider_status = "COMPLETED"
            order.status = "completed"
        return None
    if isinstance(resource.get("status"), str):
        _apply_order_body(order, resource)
    elif event.event_type == "CHECKOUT.ORDER.APPROVED":
        order.provider_status = "APPROVED"
        order.status = "approved"
    return None


async def _apply_payout_event(
    session: AsyncSession, event: WebhookEvent, resource: dict[str, Any], resource_id: str | None
) -> str | None:
    from app.integrations.paypal.status import map_payout_batch_status
    from app.modules.spendpilot.models import PayoutRequest

    batch_id = resource_id
    if not batch_id:
        return "unmatched"
    payout = await session.scalar(select(PayoutRequest).where(PayoutRequest.paypal_payout_batch_id == batch_id))
    if payout is None:
        payout = await session.scalar(select(PayoutRequest).where(PayoutRequest.sender_batch_id == batch_id))
    if payout is None:
        return "unmatched"
    event.workspace_id = payout.workspace_id
    provider_status = None
    header = resource.get("batch_header")
    if isinstance(header, dict) and isinstance(header.get("batch_status"), str):
        provider_status = header["batch_status"]
    elif isinstance(resource.get("transaction_status"), str):
        provider_status = resource["transaction_status"]
    elif event.event_type.endswith("SUCCEEDED") or event.event_type.endswith("SUCCESS"):
        provider_status = "SUCCESS"
    elif event.event_type.endswith("DENIED") or event.event_type.endswith("FAILED"):
        provider_status = "DENIED"
    if provider_status:
        payout.provider_status = provider_status.upper()
        mapped = map_payout_batch_status(provider_status)
        if mapped:
            payout.status = mapped
    return None
