"""Read-only PayPal capability checks.

The only POST this module makes is the OAuth token request. It does not
create invoices, orders, or payouts.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.core.config import Settings
from app.integrations.paypal.capability import (
    INVOICING_SCOPES,
    ORDERS_SCOPES,
    PAYOUTS_SCOPE,
    payout_capability,
)
from app.integrations.paypal.client import PayPalClient
from app.integrations.paypal.errors import (
    PayPalAuthError,
    PayPalError,
    PayPalNotFoundError,
    PayPalPermissionError,
)


class CapabilityCheck(BaseModel):
    name: str
    status: str
    detail: str


class CapabilityReport(BaseModel):
    paypal_env: str
    base_url: str
    credentials_configured: bool
    payouts_execution_enabled: bool
    limitation: str | None
    checks: list[CapabilityCheck]


def _blocked(name: str, detail: str) -> CapabilityCheck:
    return CapabilityCheck(name=name, status="blocked", detail=detail)


async def _probe(client: PayPalClient, name: str, path: str, *, params: dict | None = None) -> CapabilityCheck:
    try:
        await client.call("GET", path, params=params)
    except PayPalNotFoundError:
        return CapabilityCheck(
            name=name,
            status="available",
            detail="The API accepted the request. The diagnostic id does not exist, and no payment was created.",
        )
    except PayPalPermissionError:
        return CapabilityCheck(
            name=name,
            status="unavailable",
            detail="The sandbox app is not permitted to call this API.",
        )
    except PayPalAuthError:
        return CapabilityCheck(name=name, status="unavailable", detail="PayPal rejected the access token.")
    except PayPalError as exc:
        return CapabilityCheck(name=name, status="unknown", detail=exc.safe_message)
    return CapabilityCheck(name=name, status="available", detail="The API accepted a read request.")


async def build_capability_report(settings: Settings, client: PayPalClient) -> CapabilityReport:
    if not settings.paypal_configured:
        capability = payout_capability(settings, None)
        detail = capability.reason
        return CapabilityReport(
            paypal_env=settings.paypal_env.value,
            base_url=settings.paypal_base_url,
            credentials_configured=False,
            payouts_execution_enabled=False,
            limitation=capability.reason,
            checks=[
                _blocked("authentication", detail),
                _blocked("invoicing", detail),
                _blocked("orders", detail),
                _blocked("webhooks", detail),
                _blocked("payouts", detail),
            ],
        )

    checks: list[CapabilityCheck] = []
    scopes: frozenset[str] | None = None
    try:
        token = await client.access_token()
        scopes = token.scopes
        checks.append(CapabilityCheck(name="authentication", status="available", detail="Sandbox OAuth token issued."))
    except PayPalError as exc:
        checks.append(CapabilityCheck(name="authentication", status="unavailable", detail=exc.safe_message))
        scopes = frozenset()

    if scopes and scopes & INVOICING_SCOPES:
        checks.append(
            await _probe(
                client,
                "invoicing",
                "/v2/invoicing/invoices",
                params={"page": 1, "page_size": 1, "total_required": "false"},
            )
        )
    elif scopes is not None and "authentication" in {item.name for item in checks if item.status == "available"}:
        checks.append(
            CapabilityCheck(
                name="invoicing",
                status="unavailable",
                detail=(
                    "The access token does not include https://uri.paypal.com/services/invoicing. "
                    "In PayPal Developer → Apps & Credentials → your Sandbox app → Features, "
                    "enable Invoicing, save, then restart the API so the cached token refreshes."
                ),
            )
        )
    else:
        checks.append(_blocked("invoicing", "Authentication did not succeed, so invoicing was not called."))

    if scopes and scopes & ORDERS_SCOPES:
        checks.append(await _probe(client, "orders", "/v2/checkout/orders/DIAGNOSTICORDER0001"))
    elif scopes:
        checks.append(
            CapabilityCheck(
                name="orders",
                status="unavailable",
                detail=(
                    "The access token does not include a payments scope required by Orders v2 "
                    "(https://uri.paypal.com/services/payments/payment)."
                ),
            )
        )
    else:
        checks.append(_blocked("orders", "Authentication did not succeed, so Orders was not called."))

    if not settings.paypal_webhook_id.strip():
        checks.append(
            _blocked("webhooks", "PAYPAL_WEBHOOK_ID is not configured. Signature verification cannot succeed.")
        )
    else:
        checks.append(await _probe(client, "webhooks", f"/v1/notifications/webhooks/{settings.paypal_webhook_id}"))

    if scopes and PAYOUTS_SCOPE in scopes:
        checks.append(await _probe(client, "payouts", "/v1/payments/payouts/DIAGNOSTICBATCH"))
    elif scopes:
        checks.append(
            CapabilityCheck(
                name="payouts",
                status="unavailable",
                detail="The access token does not include https://uri.paypal.com/payments/payouts.",
            )
        )
    else:
        checks.append(_blocked("payouts", "Authentication did not succeed, so Payouts was not called."))

    capability = payout_capability(settings, scopes)
    return CapabilityReport(
        paypal_env=settings.paypal_env.value,
        base_url=settings.paypal_base_url,
        credentials_configured=True,
        payouts_execution_enabled=capability.execution_enabled,
        limitation=None if capability.execution_enabled else capability.reason,
        checks=checks,
    )
