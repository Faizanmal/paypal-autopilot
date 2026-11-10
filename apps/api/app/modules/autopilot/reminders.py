"""Run scheduled invoice reminders, due checks, and overdue notices.

A row is claimed in PostgreSQL before the provider call. A second worker skips
rows that are already running. Paid invoices are skipped. A missing PayPal
invoice or credential is a failure, never a sent reminder.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record
from app.core.config import get_settings
from app.core.errors import AppError
from app.integrations.paypal.client import get_paypal_client
from app.modules.autopilot.models import Invoice, ScheduledAction
from app.modules.autopilot.service import remind_invoice
from app.modules.identity.deps import Principal
from app.modules.identity.models import User, Workspace, WorkspaceMember

INVOICE_REMINDER_JOB = "invoice_reminder"
INVOICE_DUE_JOB = "invoice_due_check"
INVOICE_OVERDUE_JOB = "invoice_overdue_notice"
_CLOSED = {"paid", "marked_as_paid", "cancelled", "refunded", "partially_refunded", "marked_as_refunded"}
_MAX_ATTEMPTS = 3
_STALE_AFTER = timedelta(minutes=5)


def _retryable(message: str | None) -> bool:
    if not message:
        return False
    lowered = message.lower()
    if "timed out" in lowered:
        return True
    return any(token in lowered for token in ("(500)", "(502)", "(503)", "(504)"))


async def run_due_invoice_reminders(
    session: AsyncSession, *, stale_after: timedelta = _STALE_AFTER
) -> dict[str, int]:
    await _requeue_retryable(session, INVOICE_REMINDER_JOB)
    await _recover_stale(session, INVOICE_REMINDER_JOB, stale_after)
    claimed = await _claim(session, [INVOICE_REMINDER_JOB])
    counts = {"attempted": 0, "sent": 0, "failed": 0, "skipped": 0}
    for action_id in claimed:
        row = await session.get(ScheduledAction, action_id)
        if row is None:
            continue
        counts["attempted"] += 1
        try:
            await _run_one(session, row)
        except AppError as exc:
            row.status = "failed"
            row.last_error = exc.message
        if row.status == "succeeded":
            counts["sent"] += 1
        elif row.status == "skipped":
            counts["skipped"] += 1
        else:
            counts["failed"] += 1
        await session.commit()
    return counts


async def run_due_invoice_checks(session: AsyncSession) -> dict[str, int]:
    """Record due and overdue notices once. This does not call PayPal."""
    created = await ensure_due_schedules(session)
    await session.commit()
    claimed = await _claim(session, [INVOICE_DUE_JOB, INVOICE_OVERDUE_JOB])
    recorded = 0
    for action_id in claimed:
        row = await session.get(ScheduledAction, action_id)
        if row is None:
            continue
        await _run_notice(session, row)
        if row.status == "succeeded":
            recorded += 1
        await session.commit()
    return {"scheduled": created, "recorded": recorded}


async def ensure_due_schedules(session: AsyncSession) -> int:
    already_scheduled = select(ScheduledAction.related_entity_id).where(
        ScheduledAction.job_type == INVOICE_DUE_JOB,
        ScheduledAction.related_entity_id.is_not(None),
    )
    invoices = list(
        await session.scalars(
            select(Invoice)
            .where(
                Invoice.due_at.is_not(None),
                Invoice.status.notin_(tuple(_CLOSED)),
                Invoice.id.notin_(already_scheduled),
            )
            .order_by(Invoice.due_at.asc())
            .limit(50)
        )
    )
    created = 0
    for invoice in invoices:
        if invoice.due_at is None:
            continue
        created += await _ensure_one(
            session,
            invoice,
            job_type=INVOICE_DUE_JOB,
            run_after=invoice.due_at,
            idempotency_key=f"due:{invoice.id}",
        )
        created += await _ensure_one(
            session,
            invoice,
            job_type=INVOICE_OVERDUE_JOB,
            run_after=invoice.due_at + timedelta(days=1),
            idempotency_key=f"overdue:{invoice.id}",
        )
    return created


async def _ensure_one(
    session: AsyncSession,
    invoice: Invoice,
    *,
    job_type: str,
    run_after: datetime,
    idempotency_key: str,
) -> int:
    existing = await session.scalar(
        select(ScheduledAction.id).where(
            ScheduledAction.workspace_id == invoice.workspace_id,
            ScheduledAction.job_type == job_type,
            ScheduledAction.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return 0
    session.add(
        ScheduledAction(
            workspace_id=invoice.workspace_id,
            job_type=job_type,
            run_after=run_after,
            status="pending",
            payload={"invoice_id": str(invoice.id)},
            related_entity_type="invoice",
            related_entity_id=invoice.id,
            idempotency_key=idempotency_key,
        )
    )
    await session.flush()
    return 1


async def _requeue_retryable(session: AsyncSession, job_type: str) -> None:
    rows = list(
        await session.scalars(
            select(ScheduledAction).where(
                ScheduledAction.job_type == job_type,
                ScheduledAction.status == "failed",
                ScheduledAction.attempts < _MAX_ATTEMPTS,
            )
        )
    )
    for row in rows:
        if _retryable(row.last_error):
            row.status = "pending"
    await session.commit()


async def _recover_stale(session: AsyncSession, job_type: str, stale_after: timedelta) -> None:
    cutoff = datetime.now(UTC) - stale_after
    rows = list(
        await session.scalars(
            select(ScheduledAction).where(
                ScheduledAction.job_type == job_type,
                ScheduledAction.status == "running",
            )
        )
    )
    for row in rows:
        if row.claimed_at is not None and row.claimed_at > cutoff:
            continue
        if row.attempts >= _MAX_ATTEMPTS:
            row.status = "failed"
            row.last_error = row.last_error or "Worker stopped before the reminder finished."
        else:
            row.status = "pending"
    await session.commit()


async def _claim(session: AsyncSession, job_types: list[str]) -> list[uuid.UUID]:
    now = datetime.now(UTC)
    rows = list(
        await session.scalars(
            select(ScheduledAction)
            .where(
                ScheduledAction.status == "pending",
                ScheduledAction.job_type.in_(job_types),
                ScheduledAction.run_after <= now,
            )
            .order_by(ScheduledAction.run_after.asc())
            .limit(25)
            .with_for_update(skip_locked=True)
        )
    )
    claimed: list[uuid.UUID] = []
    for row in rows:
        row.status = "running"
        row.claimed_at = now
        row.attempts += 1
        claimed.append(row.id)
    await session.commit()
    return claimed


async def _run_notice(session: AsyncSession, row: ScheduledAction) -> None:
    invoice = await session.get(Invoice, row.related_entity_id) if row.related_entity_id else None
    if invoice is None or invoice.workspace_id != row.workspace_id:
        row.status = "failed"
        row.last_error = "Invoice not found in this workspace."
        return
    if invoice.status in _CLOSED:
        row.status = "skipped"
        row.last_error = None
        return
    action = "invoice.due_reached" if row.job_type == INVOICE_DUE_JOB else "invoice.overdue_notice"
    record(
        session,
        action=action,
        entity_type="invoice",
        entity_id=invoice.id,
        workspace_id=invoice.workspace_id,
        details={"scheduled_action_id": str(row.id), "status": invoice.status},
    )
    row.status = "succeeded"
    row.last_error = None


async def _run_one(session: AsyncSession, row: ScheduledAction) -> None:
    invoice_id = row.related_entity_id
    invoice = await session.get(Invoice, invoice_id) if invoice_id else None
    if invoice is None or invoice.workspace_id != row.workspace_id:
        row.status = "failed"
        row.last_error = "Invoice not found in this workspace."
        return
    if invoice.status in _CLOSED:
        row.status = "skipped"
        row.last_error = None
        return
    if not invoice.paypal_invoice_id:
        row.status = "failed"
        row.last_error = "This invoice has not been created in PayPal."
        return
    actor = row.payload.get("actor_user_id") if isinstance(row.payload, dict) else None
    if not isinstance(actor, str):
        row.status = "failed"
        row.last_error = "The scheduled reminder has no workspace member."
        return
    principal = await _principal(session, row.workspace_id, uuid.UUID(actor))
    await remind_invoice(
        session,
        principal,
        invoice.id,
        get_paypal_client(),
        get_settings(),
        idempotency_key=f"scheduled:{row.id}",
    )
    row.status = "succeeded"
    row.last_error = None


async def _principal(session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID) -> Principal:
    user = await session.get(User, user_id)
    workspace = await session.get(Workspace, workspace_id)
    membership = await session.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    )
    if user is None or not user.is_active or workspace is None or membership is None:
        raise AppError("The scheduled reminder has no active workspace member.")
    return Principal(user=user, workspace=workspace, role=membership.role)
