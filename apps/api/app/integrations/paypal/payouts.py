"""Payouts API v1. Callers must check payout capability before create_batch."""

from __future__ import annotations

from decimal import Decimal

from app.core.money import money_to_api
from app.integrations.paypal.client import PayPalCall, PayPalClient


class PayoutsApi:
    def __init__(self, client: PayPalClient) -> None:
        self._client = client

    async def create_batch(
        self,
        *,
        sender_batch_id: str,
        recipient_email: str,
        currency_code: str,
        amount: Decimal,
        idempotency_key: str,
        note: str,
    ) -> PayPalCall:
        return await self._client.call(
            "POST",
            "/v1/payments/payouts",
            idempotency_key=idempotency_key,
            json_body={
                "sender_batch_header": {
                    "sender_batch_id": sender_batch_id,
                    "email_subject": "You have a payout",
                    "recipient_type": "EMAIL",
                },
                "items": [
                    {
                        "recipient_type": "EMAIL",
                        "receiver": recipient_email,
                        "sender_item_id": sender_batch_id[:63],
                        "note": note[:4000],
                        "amount": {"currency": currency_code, "value": money_to_api(amount)},
                    }
                ],
            },
        )

    async def get_batch(self, payout_batch_id: str) -> PayPalCall:
        return await self._client.call("GET", f"/v1/payments/payouts/{payout_batch_id}")
