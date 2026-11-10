"""Insert-only audit records. Callers commit the surrounding transaction."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog


def record(
    session: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    details: dict | None = None,
) -> AuditLog:
    """Append one audit row. There is no update or delete helper on this module."""
    entry = AuditLog(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        details=details or {},
    )
    session.add(entry)
    return entry


def financial_details(
    *,
    status: str,
    proposed_by_ai: bool = False,
    approval_id: str | None = None,
    approver_id: str | None = None,
    policy_evaluated: str | None = None,
    paypal_operation: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Normalize the audit fields the financial dashboard expects to show."""
    payload: dict[str, Any] = {
        "status": status,
        "proposed_by_ai": proposed_by_ai,
    }
    if approval_id is not None:
        payload["approval_id"] = approval_id
    if approver_id is not None:
        payload["approver_id"] = approver_id
    if policy_evaluated is not None:
        payload["policy_evaluated"] = policy_evaluated
    if paypal_operation is not None:
        payload["paypal_operation"] = paypal_operation
    for key, value in extra.items():
        if value is not None:
            payload[key] = value
    return payload
