"""Canonical identity of one financial action.

The hash is the approval binding. Amount, recipient, currency, action, target,
and workspace are part of it. The approving person is added only when the
decision is recorded, so two requests for the same action still match.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from decimal import Decimal


def action_hash(
    *,
    action_type: str,
    recipient: str,
    amount: Decimal,
    currency: str,
    target_type: str,
    target_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> str:
    quantized = amount.quantize(Decimal("0.01"))
    payload = json.dumps(
        [
            action_type.strip().casefold(),
            recipient.strip().casefold(),
            format(quantized, "f"),
            currency.strip().upper(),
            target_type.strip().casefold(),
            str(target_id),
            str(workspace_id),
        ], separators=(",", ":"), ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def approval_hash(action_digest: str, approver_id: uuid.UUID) -> str:
    payload = f"{action_digest}|{approver_id}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
