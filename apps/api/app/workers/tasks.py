"""Celery tasks.

Due invoice reminders call the PayPal remind service. A reminder is marked
succeeded only after that call returns. Other scheduled rows are counted and
left untouched. Payouts are never sent from this task.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.db.session import get_engine, get_session_factory
from app.modules.autopilot.models import ScheduledAction
from app.modules.autopilot.reminders import run_due_invoice_checks, run_due_invoice_reminders
from app.modules.workflows.engine import reconcile_open_invoices, resume_interrupted_runs
from app.workers.celery_app import celery_app

logger = logging.getLogger("app.workers")


async def count_due_scheduled_actions() -> int:
    now = datetime.now(UTC)
    session_factory = get_session_factory()
    async with session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(ScheduledAction)
            .where(
                ScheduledAction.status == "pending",
                ScheduledAction.run_after <= now,
            )
        )
        return int(count or 0)


async def _dispatch() -> int:
    session_factory = get_session_factory()
    async with session_factory() as session:
        counts = await run_due_invoice_reminders(session)
        checks = await run_due_invoice_checks(session)
        reconciled = await reconcile_open_invoices(session)
        resumed = await resume_interrupted_runs(session)
    due = await count_due_scheduled_actions()
    logger.info(
        "scheduled_actions_due",
        extra={"context": {"due": due, **counts, **checks, **reconciled, "resumed": resumed}},
    )
    return due


@celery_app.task(name="app.workers.dispatch_due_scheduled_actions")
def dispatch_due_scheduled_actions() -> int:
    return asyncio.run(_dispatch_once())


async def _dispatch_once() -> int:
    try:
        return await _dispatch()
    finally:
        # Each synchronous Celery invocation creates its own event loop. Close
        # pooled asyncpg connections before that loop ends, including on failure.
        await get_engine().dispose()
