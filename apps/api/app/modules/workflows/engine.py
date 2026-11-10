"""Durable invoice-to-payout orchestration.

PostgreSQL holds workflow steps, schedule rows, attempts, and provider ids.
Redis is only the Celery broker. A missed webhook is not treated as unpaid:
reconciliation reads the invoice from PayPal and then advances the same path
as INVOICING.INVOICE.PAID.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.integrations.paypal.client import get_paypal_client
from app.integrations.paypal.errors import PayPalError
from app.modules.ai.models import AgentAction, AgentRun
from app.modules.autopilot.models import Invoice, ScheduledAction
from app.modules.identity.deps import Principal
from app.modules.identity.models import User, Workspace, WorkspaceMember

_PAID = {"paid", "marked_as_paid"}
_OPEN_SCHEDULE = {"pending", "running", "failed"}
_WAIT_STATUSES = {"waiting", "running"}


async def cancel_schedules_for_invoice(session: AsyncSession, invoice_id: uuid.UUID) -> int:
    rows = list(
        await session.scalars(
            select(ScheduledAction).where(
                ScheduledAction.related_entity_id == invoice_id,
                ScheduledAction.status.in_(_OPEN_SCHEDULE),
            )
        )
    )
    for row in rows:
        row.status = "cancelled"
        row.last_error = None
    return len(rows)


async def on_invoice_paid(session: AsyncSession, invoice: Invoice) -> None:
    """Cancel reminders and resume the payout step that waits on this invoice."""
    if invoice.status not in _PAID:
        return
    await cancel_schedules_for_invoice(session, invoice.id)
    run_ids = await _runs_waiting_on(session, invoice)
    for run_id in run_ids:
        run = await session.get(AgentRun, run_id)
        if run is None or run.status in {"cancelled", "completed"}:
            continue
        principal = await principal_for(session, run.workspace_id, run.user_id)
        from app.modules.ai.service import resume_run

        await resume_run(session, principal, run.id)


async def reconcile_open_invoices(session: AsyncSession) -> dict[str, int]:
    """Read PayPal for invoices that are still open locally.

    A missing webhook leaves the invoice unchanged until PayPal itself reports
    a paid status. Provider errors are recorded and do not mark the invoice unpaid.
    """
    counts = {"checked": 0, "paid": 0, "unavailable": 0}
    settings = get_settings()
    if not settings.paypal_configured:
        return counts
    from app.modules.autopilot.service import sync_invoice_from_provider

    client = get_paypal_client()
    cursor: uuid.UUID | None = None
    while True:
        query = (
            select(Invoice)
            .where(
                Invoice.paypal_invoice_id.is_not(None),
                Invoice.status.notin_(
                    (
                        "paid",
                        "marked_as_paid",
                        "cancelled",
                        "refunded",
                        "partially_refunded",
                        "marked_as_refunded",
                    )
                ),
            )
            .order_by(Invoice.id)
            .limit(25)
        )
        if cursor is not None:
            query = query.where(Invoice.id > cursor)
        rows = list(await session.scalars(query))
        if not rows:
            break
        # Advance even when a provider call fails. OFFSET would skip rows when
        # paid invoices disappear from the query after each committed batch.
        cursor = rows[-1].id
        for invoice in rows:
            counts["checked"] += 1
            try:
                applied_paid = await sync_invoice_from_provider(session, invoice, client)
            except (PayPalError, AppError):
                counts["unavailable"] += 1
                continue
            await session.commit()
            if applied_paid or invoice.status in _PAID:
                counts["paid"] += 1
                await on_invoice_paid(session, invoice)
                await session.commit()
    return counts


async def resume_interrupted_runs(session: AsyncSession) -> int:
    """Finish steps left running when a worker stopped. Waiting steps stay waiting."""
    run_ids = set(
        await session.scalars(select(AgentRun.id).where(AgentRun.status == "executing"))
    )
    running_actions = list(
        await session.scalars(select(AgentAction.agent_run_id).where(AgentAction.status == "running"))
    )
    run_ids.update(running_actions)
    resumed = 0
    for run_id in run_ids:
        run = await session.get(AgentRun, run_id)
        if run is None or run.status in {"cancelled", "completed", "pending_confirmation"}:
            continue
        principal = await principal_for(session, run.workspace_id, run.user_id)
        from app.modules.ai.service import resume_run

        await resume_run(session, principal, run.id)
        resumed += 1
    return resumed


async def _runs_waiting_on(session: AsyncSession, invoice: Invoice) -> list[uuid.UUID]:
    actions = list(
        await session.scalars(
            select(AgentAction).where(
                AgentAction.workspace_id == invoice.workspace_id,
                AgentAction.status.in_(_WAIT_STATUSES),
            )
        )
    )
    found: list[uuid.UUID] = []
    needle = str(invoice.id)
    for action in actions:
        result = action.result if isinstance(action.result, dict) else {}
        payload = action.payload if isinstance(action.payload, dict) else {}
        raw_trusted = payload.get("trusted")
        trusted = raw_trusted if isinstance(raw_trusted, dict) else {}
        matched = result.get("invoice_id") == needle or trusted.get("invoice_id") == needle
        if matched and action.agent_run_id not in found:
            found.append(action.agent_run_id)
    return found


async def principal_for(session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID) -> Principal:
    user = await session.get(User, user_id)
    workspace = await session.get(Workspace, workspace_id)
    membership = await session.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    )
    if user is None or not user.is_active or workspace is None or membership is None:
        raise AppError("The workflow has no active workspace member.")
    return Principal(user=user, workspace=workspace, role=membership.role)
