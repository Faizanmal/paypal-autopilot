from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from app.api.deps import CurrentPrincipal, DbSession
from app.core.config import AppEnv, get_settings
from app.core.errors import NotFoundError, PolicyViolationError
from app.integrations.paypal.client import get_paypal_client
from app.integrations.paypal.diagnostics import CapabilityReport, build_capability_report
from app.integrations.paypal.webhooks import PayPalWebhookVerifier
from app.modules.autopilot.schemas import (
    InvoiceCreate,
    InvoiceOut,
    ItemList,
    OrderCreate,
    OrderOut,
    PaymentOut,
    WebhookIngestOut,
)
from app.modules.autopilot.service import (
    capture_order,
    create_invoice,
    create_order,
    get_invoice,
    ingest_webhook,
    list_invoice_payments,
    list_invoices,
    list_orders,
    remind_invoice,
    send_invoice,
    sync_invoice,
    sync_known_invoices,
    sync_order,
)

router = APIRouter(tags=["paypal"])


@router.get("/invoices", response_model=ItemList[InvoiceOut])
async def get_invoices(principal: CurrentPrincipal, db: DbSession) -> ItemList[InvoiceOut]:
    rows = await list_invoices(db, principal)
    return ItemList(items=[InvoiceOut.model_validate(row) for row in rows])


@router.get("/invoices/{invoice_id}", response_model=InvoiceOut)
async def get_one_invoice(invoice_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> InvoiceOut:
    return InvoiceOut.model_validate(await get_invoice(db, principal, invoice_id))


@router.get("/invoices/{invoice_id}/payments", response_model=ItemList[PaymentOut])
async def get_invoice_payments(
    invoice_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession
) -> ItemList[PaymentOut]:
    rows = await list_invoice_payments(db, principal, invoice_id)
    return ItemList(items=[PaymentOut.model_validate(row) for row in rows])


@router.post("/invoices", response_model=InvoiceOut, status_code=201)
async def post_invoice(body: InvoiceCreate, principal: CurrentPrincipal, db: DbSession) -> InvoiceOut:
    invoice = await create_invoice(db, principal, body, get_paypal_client(), get_settings())
    return InvoiceOut.model_validate(invoice)


@router.post("/invoices/{invoice_id}/send", response_model=InvoiceOut)
async def post_send_invoice(invoice_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> InvoiceOut:
    invoice = await send_invoice(db, principal, invoice_id, get_paypal_client(), get_settings())
    return InvoiceOut.model_validate(invoice)


@router.post("/invoices/{invoice_id}/remind", response_model=InvoiceOut)
async def post_remind_invoice(invoice_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> InvoiceOut:
    invoice = await remind_invoice(db, principal, invoice_id, get_paypal_client(), get_settings())
    return InvoiceOut.model_validate(invoice)


@router.post("/invoices/{invoice_id}/sync", response_model=InvoiceOut)
async def post_sync_invoice(invoice_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> InvoiceOut:
    invoice = await sync_invoice(db, principal, invoice_id, get_paypal_client(), get_settings())
    return InvoiceOut.model_validate(invoice)


@router.post("/invoices/sync", response_model=ItemList[InvoiceOut])
async def post_sync_invoices(principal: CurrentPrincipal, db: DbSession) -> ItemList[InvoiceOut]:
    rows = await sync_known_invoices(db, principal, get_paypal_client(), get_settings())
    return ItemList(items=[InvoiceOut.model_validate(row) for row in rows])


@router.get("/checkout/orders", response_model=ItemList[OrderOut])
async def get_orders(principal: CurrentPrincipal, db: DbSession) -> ItemList[OrderOut]:
    rows = await list_orders(db, principal)
    return ItemList(items=[OrderOut.model_validate(row) for row in rows])


@router.post("/checkout/orders", response_model=OrderOut, status_code=201)
async def post_order(body: OrderCreate, principal: CurrentPrincipal, db: DbSession) -> OrderOut:
    order = await create_order(db, principal, body, get_paypal_client(), get_settings())
    return OrderOut.model_validate(order)


@router.post("/checkout/orders/{order_id}/sync", response_model=OrderOut)
async def post_sync_order(order_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> OrderOut:
    order = await sync_order(db, principal, order_id, get_paypal_client(), get_settings())
    return OrderOut.model_validate(order)


@router.post("/checkout/orders/{order_id}/capture", response_model=OrderOut)
async def post_capture_order(order_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> OrderOut:
    order = await capture_order(db, principal, order_id, get_paypal_client(), get_settings())
    return OrderOut.model_validate(order)


@router.get("/integrations/paypal/diagnostics", response_model=CapabilityReport)
async def get_paypal_diagnostics(principal: CurrentPrincipal) -> CapabilityReport:
    settings = get_settings()
    if settings.app_env is AppEnv.PRODUCTION:
        raise NotFoundError("Not found.")
    if principal.role != "owner":
        raise PolicyViolationError("Only the workspace owner can view PayPal diagnostics.")
    return await build_capability_report(settings, get_paypal_client())


@router.post("/webhooks/paypal", response_model=WebhookIngestOut)
async def post_paypal_webhook(request: Request, db: DbSession) -> WebhookIngestOut:
    raw = await request.body()
    settings = get_settings()
    verifier = getattr(request.app.state, "paypal_webhook_verifier", None)
    if verifier is None:
        verifier = PayPalWebhookVerifier(get_paypal_client(), settings.paypal_webhook_id)
    result = await ingest_webhook(
        db,
        raw_body=raw,
        headers=dict(request.headers),
        verifier=verifier,
        webhook_id=settings.paypal_webhook_id,
    )
    return WebhookIngestOut.model_validate(result)
