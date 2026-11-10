"""Orders API v2. Capture is a separate call and requires buyer approval."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.money import money_to_api
from app.integrations.paypal.client import PayPalCall, PayPalClient


def approval_url(body: dict[str, Any]) -> str | None:
    links = body.get("links")
    if not isinstance(links, list):
        return None
    for rel in ("payer-action", "approve"):
        for link in links:
            if isinstance(link, dict) and link.get("rel") == rel and isinstance(link.get("href"), str):
                return link["href"]
    return None


def capture_from_order(body: dict[str, Any]) -> tuple[str | None, str | None]:
    units = body.get("purchase_units")
    if not isinstance(units, list):
        return None, None
    for unit in units:
        if not isinstance(unit, dict):
            continue
        payments = unit.get("payments")
        if not isinstance(payments, dict):
            continue
        captures = payments.get("captures")
        if isinstance(captures, list) and captures and isinstance(captures[0], dict):
            capture = captures[0]
            capture_id = capture.get("id") if isinstance(capture.get("id"), str) else None
            capture_status = capture.get("status") if isinstance(capture.get("status"), str) else None
            return capture_id, capture_status
    return None, None


def authorization_from_order(body: dict[str, Any]) -> tuple[str | None, str | None]:
    units = body.get("purchase_units")
    if not isinstance(units, list):
        return None, None
    for unit in units:
        if not isinstance(unit, dict):
            continue
        payments = unit.get("payments")
        if not isinstance(payments, dict):
            continue
        authorizations = payments.get("authorizations")
        if isinstance(authorizations, list) and authorizations and isinstance(authorizations[0], dict):
            auth = authorizations[0]
            auth_id = auth.get("id") if isinstance(auth.get("id"), str) else None
            auth_status = auth.get("status") if isinstance(auth.get("status"), str) else None
            return auth_id, auth_status
    return None, None


class OrdersApi:
    def __init__(self, client: PayPalClient) -> None:
        self._client = client

    async def create_order(
        self,
        *,
        intent: str,
        currency_code: str,
        amount: Decimal,
        description: str,
        idempotency_key: str,
    ) -> PayPalCall:
        return await self._client.call(
            "POST",
            "/v2/checkout/orders",
            idempotency_key=idempotency_key,
            json_body={
                "intent": intent,
                "purchase_units": [
                    {
                        "description": description[:127],
                        "amount": {"currency_code": currency_code, "value": money_to_api(amount)},
                    }
                ],
            },
        )

    async def get_order(self, paypal_order_id: str) -> PayPalCall:
        return await self._client.call("GET", f"/v2/checkout/orders/{paypal_order_id}")

    async def capture_order(self, paypal_order_id: str, *, idempotency_key: str) -> PayPalCall:
        return await self._client.call(
            "POST",
            f"/v2/checkout/orders/{paypal_order_id}/capture",
            idempotency_key=idempotency_key,
            json_body={},
        )

    async def authorize_order(self, paypal_order_id: str, *, idempotency_key: str) -> PayPalCall:
        return await self._client.call(
            "POST",
            f"/v2/checkout/orders/{paypal_order_id}/authorize",
            idempotency_key=idempotency_key,
            json_body={},
        )

    async def capture_authorization(self, authorization_id: str, *, idempotency_key: str) -> PayPalCall:
        return await self._client.call(
            "POST",
            f"/v2/payments/authorizations/{authorization_id}/capture",
            idempotency_key=idempotency_key,
            json_body={},
        )
