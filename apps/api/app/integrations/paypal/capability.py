"""Payout execution is off unless sandbox access has actually been confirmed."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings

PAYOUTS_SCOPE = "https://uri.paypal.com/payments/payouts"
# PayPal issues the product scope below; older docs/tests also use the
# invoices/readwrite and invoices/read variants.
INVOICING_SCOPE = "https://uri.paypal.com/services/invoicing"
INVOICING_READWRITE_SCOPE = "https://uri.paypal.com/services/invoicing/invoices/readwrite"
INVOICING_READ_SCOPE = "https://uri.paypal.com/services/invoicing/invoices/read"
INVOICING_SCOPES = frozenset({INVOICING_SCOPE, INVOICING_READWRITE_SCOPE, INVOICING_READ_SCOPE})
ORDERS_SCOPE = "https://uri.paypal.com/services/payments/payment"
ORDERS_AUTHCAPTURE_SCOPE = "https://uri.paypal.com/services/payments/payment/authcapture"
ORDERS_SCOPES = frozenset({ORDERS_SCOPE, ORDERS_AUTHCAPTURE_SCOPE})

CREDENTIALS_MISSING = (
    "PayPal sandbox credentials are not configured. No live PayPal call has been made, "
    "and Payouts API access has not been confirmed."
)
EXECUTION_FLAG_OFF = (
    "Payout execution is disabled. PAYPAL_PAYOUTS_EXECUTION is false, so this API will "
    "not send a payout even if the sandbox app later includes the Payouts scope."
)
SCOPE_MISSING = (
    "The sandbox access token does not include the Payouts scope "
    "https://uri.paypal.com/payments/payouts. Payout execution is disabled."
)
EXECUTION_ENABLED = "Sandbox Payouts execution is enabled for this app."


@dataclass(frozen=True, slots=True)
class PayoutCapability:
    execution_enabled: bool
    reason: str
    credentials_configured: bool
    scope_present: bool | None


def payout_capability(settings: Settings, scopes: frozenset[str] | None) -> PayoutCapability:
    if not settings.paypal_configured:
        return PayoutCapability(
            execution_enabled=False,
            reason=CREDENTIALS_MISSING,
            credentials_configured=False,
            scope_present=None,
        )
    scope_present = None if scopes is None else PAYOUTS_SCOPE in scopes
    if not settings.paypal_payouts_execution:
        return PayoutCapability(
            execution_enabled=False,
            reason=EXECUTION_FLAG_OFF,
            credentials_configured=True,
            scope_present=scope_present,
        )
    if scope_present is not True:
        return PayoutCapability(
            execution_enabled=False,
            reason=SCOPE_MISSING,
            credentials_configured=True,
            scope_present=False if scopes is not None else None,
        )
    return PayoutCapability(
        execution_enabled=True,
        reason=EXECUTION_ENABLED,
        credentials_configured=True,
        scope_present=True,
    )
