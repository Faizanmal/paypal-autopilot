"""Map PayPal statuses onto internal states without dropping the provider value.

Callers persist `provider_status` separately. These functions only decide
whether an internal transition is allowed.
"""

from __future__ import annotations

INVOICE_STATUS_MAP: dict[str, str] = {
    "DRAFT": "draft",
    "SENT": "sent",
    "SCHEDULED": "scheduled",
    "UNPAID": "sent",
    "PAYMENT_PENDING": "payment_pending",
    "PARTIALLY_PAID": "partially_paid",
    "PAID": "paid",
    "MARKED_AS_PAID": "marked_as_paid",
    "CANCELLED": "cancelled",
    "REFUNDED": "refunded",
    "PARTIALLY_REFUNDED": "partially_refunded",
    "MARKED_AS_REFUNDED": "marked_as_refunded",
}

INVOICE_EVENT_STATUS: dict[str, str] = {
    "INVOICING.INVOICE.CREATED": "DRAFT",
    "INVOICING.INVOICE.SENT": "SENT",
    "INVOICING.INVOICE.SCHEDULED": "SCHEDULED",
    "INVOICING.INVOICE.PAID": "PAID",
    "INVOICING.INVOICE.CANCELLED": "CANCELLED",
    "INVOICING.INVOICE.REFUNDED": "REFUNDED",
    "INVOICING.INVOICE.UPDATED": "",
}

_INVOICE_RANK: dict[str, int] = {
    "draft": 10,
    "scheduled": 20,
    "sent": 30,
    "payment_pending": 40,
    "partially_paid": 50,
    "paid": 60,
    "marked_as_paid": 60,
    "partially_refunded": 70,
    "refunded": 80,
    "marked_as_refunded": 80,
    "cancelled": 90,
}

_REFUND_STATES = {"partially_refunded", "refunded", "marked_as_refunded"}
_PAID_STATES = {"partially_paid", "paid", "marked_as_paid"}

ORDER_STATUS_MAP: dict[str, str] = {
    "CREATED": "created",
    "SAVED": "created",
    "PAYER_ACTION_REQUIRED": "payer_action_required",
    "APPROVED": "approved",
    "VOIDED": "voided",
    "COMPLETED": "completed",
}

PAYOUT_BATCH_STATUS_MAP: dict[str, str] = {
    "PENDING": "submitted",
    "PROCESSING": "submitted",
    "SUCCESS": "succeeded",
    "DENIED": "denied",
    "CANCELED": "canceled",
}

CAPTURE_BLOCKED_STATUSES = {"CREATED", "SAVED", "PAYER_ACTION_REQUIRED"}


def map_invoice_status(provider_status: str | None) -> str:
    if not provider_status:
        return "unknown"
    return INVOICE_STATUS_MAP.get(provider_status.upper(), "unknown")


def next_invoice_status(current: str, provider_status: str | None) -> tuple[str, bool]:
    """Return (status, applied). A delayed earlier event does not rewind a later one."""
    incoming = map_invoice_status(provider_status)
    if incoming == "unknown":
        return current, False
    if current == incoming:
        return current, True
    if current in _PAID_STATES and incoming in _REFUND_STATES:
        return incoming, True
    if _INVOICE_RANK.get(incoming, 0) < _INVOICE_RANK.get(current, 0):
        return current, False
    if current == "cancelled" and incoming not in _REFUND_STATES:
        return current, False
    return incoming, True


def map_order_status(provider_status: str | None) -> str:
    if not provider_status:
        return "unknown"
    return ORDER_STATUS_MAP.get(provider_status.upper(), "unknown")


def capture_block_reason(*, intent: str, provider_status: str | None, authorization_status: str | None) -> str | None:
    """Why capture must not be called. None means the supported next PayPal call is allowed."""
    status = (provider_status or "").upper()
    intent_name = intent.upper()
    if status in CAPTURE_BLOCKED_STATUSES or status == "":
        return "Buyer approval is required before this order can be captured."
    if status == "VOIDED":
        return "This order is voided and cannot be captured."
    if status == "COMPLETED":
        return None
    if intent_name == "CAPTURE" and status == "APPROVED":
        return None
    if intent_name == "AUTHORIZE" and status == "APPROVED":
        return None
    if intent_name == "AUTHORIZE" and authorization_status == "CREATED":
        return None
    return f"Order status {status or 'unknown'} cannot be captured."


def map_payout_batch_status(provider_status: str | None) -> str | None:
    if not provider_status:
        return None
    return PAYOUT_BATCH_STATUS_MAP.get(provider_status.upper())


def invoice_status_from_event(event_type: str, resource_status: str | None) -> str | None:
    if resource_status:
        return resource_status.upper()
    mapped = INVOICE_EVENT_STATUS.get(event_type)
    return mapped or None
