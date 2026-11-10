"""Invoicing API v2. Amounts are decimal strings."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.logging import _redact
from app.core.money import money_to_api
from app.integrations.paypal.client import PayPalCall, PayPalClient

_INVOICE_PATH_MARKER = "/v2/invoicing/invoices/"


def invoice_id_from_create_body(body: dict[str, Any]) -> str | None:
    """PayPal create may return a full invoice or only a self-link object/array."""
    raw = body.get("id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    href = body.get("href")
    if isinstance(href, str):
        extracted = _invoice_id_from_href(href)
        if extracted:
            return extracted
    links = body.get("links")
    if isinstance(links, list):
        for link in links:
            if not isinstance(link, dict):
                continue
            if link.get("rel") not in {None, "self"}:
                continue
            if isinstance(link.get("href"), str):
                extracted = _invoice_id_from_href(link["href"])
                if extracted:
                    return extracted
    return None


def _invoice_id_from_href(href: str) -> str | None:
    marker = _INVOICE_PATH_MARKER
    idx = href.find(marker)
    if idx < 0:
        # Some sandbox hosts omit the /v2 prefix in docs examples; accept /invoicing/invoices/
        marker = "/invoicing/invoices/"
        idx = href.find(marker)
        if idx < 0:
            return None
    tail = href[idx + len(marker) :].split("?", 1)[0].strip("/")
    return tail or None


def _summary(body: dict[str, Any]) -> dict[str, Any]:
    return _redact(
        {
            "id": body.get("id"),
            "status": body.get("status"),
            "detail": body.get("detail") if isinstance(body.get("detail"), dict) else None,
            "links": body.get("links") if isinstance(body.get("links"), list) else [],
            "amount": body.get("amount") if isinstance(body.get("amount"), dict) else None,
        }
    )


def hosted_url(body: dict[str, Any]) -> str | None:
    links = body.get("links")
    if not isinstance(links, list):
        return None
    preferred = ("payer-view", "view")
    found: dict[str, str] = {}
    for link in links:
        if isinstance(link, dict) and isinstance(link.get("rel"), str) and isinstance(link.get("href"), str):
            found[link["rel"]] = link["href"]
    for rel in preferred:
        href = found.get(rel)
        if href and "paypal.com/invoice" in href:
            return href
    # Never treat the Invoicing API "self" URL as a buyer payment link.
    return None


class InvoicingApi:
    def __init__(self, client: PayPalClient) -> None:
        self._client = client

    async def create_draft(
        self,
        *,
        invoicer_email: str,
        recipient_email: str,
        recipient_name: str,
        currency_code: str,
        amount: Decimal,
        description: str,
        idempotency_key: str,
    ) -> PayPalCall:
        result = await self._client.call(
            "POST",
            "/v2/invoicing/invoices",
            idempotency_key=idempotency_key,
            json_body={
                "detail": {
                    "currency_code": currency_code,
                    "payment_term": {"term_type": "DUE_ON_RECEIPT"},
                },
                "invoicer": {"email_address": invoicer_email},
                "primary_recipients": [
                    {"billing_info": {"business_name": recipient_name, "email_address": recipient_email}}
                ],
                "items": [
                    {
                        "name": description[:200],
                        "quantity": "1",
                        "unit_amount": {"currency_code": currency_code, "value": money_to_api(amount)},
                    }
                ],
            },
        )
        invoice_id = invoice_id_from_create_body(result.body)
        # Sandbox often returns only {"rel":"self","href":".../INV2-...","method":"GET"}.
        if invoice_id and result.body.get("id") != invoice_id:
            fetched = await self.get_invoice(invoice_id)
            return fetched
        result.body = {**result.body, "_summary": _summary(result.body)}
        return result

    async def get_invoice(self, paypal_invoice_id: str) -> PayPalCall:
        result = await self._client.call("GET", f"/v2/invoicing/invoices/{paypal_invoice_id}")
        result.body = {**result.body, "_summary": _summary(result.body)}
        return result

    async def send_invoice(self, paypal_invoice_id: str, *, idempotency_key: str) -> PayPalCall:
        result = await self._client.call(
            "POST",
            f"/v2/invoicing/invoices/{paypal_invoice_id}/send",
            idempotency_key=idempotency_key,
            json_body={"send_to_recipient": True, "send_to_invoicer": False},
        )
        # Sandbox often returns a bare payer-view link object instead of the invoice.
        if result.body.get("rel") == "payer-view" and isinstance(result.body.get("href"), str):
            href = result.body["href"]
            result.body = {
                "id": paypal_invoice_id,
                "status": "SENT",
                "links": [{"rel": "payer-view", "href": href, "method": "GET"}],
                "_summary": _summary(
                    {
                        "id": paypal_invoice_id,
                        "status": "SENT",
                        "links": [{"rel": "payer-view", "href": href}],
                    }
                ),
            }
            return result
        result.body = {**result.body, "_summary": _summary(result.body)}
        return result


    async def remind(self, paypal_invoice_id: str, *, idempotency_key: str) -> PayPalCall:
        return await self._client.call(
            "POST",
            f"/v2/invoicing/invoices/{paypal_invoice_id}/remind",
            idempotency_key=idempotency_key,
            json_body={"send_to_recipient": True, "send_to_invoicer": False},
        )

    async def list_invoices(self, *, page: int = 1, page_size: int = 20) -> PayPalCall:
        return await self._client.call(
            "GET",
            "/v2/invoicing/invoices",
            params={"page": page, "page_size": page_size, "total_required": "true"},
        )
