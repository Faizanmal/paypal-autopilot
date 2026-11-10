"""Read-only cash-risk report, runnable as an official Render task."""

from __future__ import annotations

import asyncio
from decimal import Decimal

from pydantic import BaseModel, Field
from render import RenderAsync

from app.core.config import AppEnv, get_settings
from app.modules.ai.studio import IntegrationUnavailable
from app.modules.finance.schemas import FinanceSnapshotOut


class CashRiskReport(BaseModel):
    currency: str
    horizon_days: int = Field(ge=1, le=366)
    overdue_receivables: str
    total_receivables: str
    overdue_percent: str
    planned_expenses: str
    projected_available: str | None
    alert_count: int = Field(ge=0)
    excluded_projection_count: int = Field(ge=0)
    warnings: list[str]


def build_cash_report(data: dict) -> dict:
    snapshot = FinanceSnapshotOut.model_validate(data)
    overdue = Decimal(snapshot.overdue_receivables)
    receivables = Decimal(snapshot.outstanding_receivables)
    percentage = overdue * 100 / receivables if receivables > 0 else Decimal(0)
    return CashRiskReport(
        currency=snapshot.currency,
        horizon_days=snapshot.horizon_days,
        overdue_receivables=snapshot.overdue_receivables,
        total_receivables=snapshot.outstanding_receivables,
        overdue_percent=str(percentage.quantize(Decimal("0.01"))),
        planned_expenses=snapshot.planned_expenses,
        projected_available=snapshot.projected_available,
        alert_count=len(snapshot.alerts),
        excluded_projection_count=sum(not row.included for row in snapshot.projection),
        warnings=[*snapshot.assumptions, *snapshot.uncertainty],
    ).model_dump()


async def run_cash_report(snapshot: FinanceSnapshotOut) -> dict:
    settings = get_settings()
    local = settings.render_use_local_dev or bool(settings.render_local_dev_url)
    if (local and settings.app_env is AppEnv.PRODUCTION) or not settings.render_report_task:
        raise IntegrationUnavailable("Configure a Render report task before running background reports.")
    if not local and not settings.render_api_key.get_secret_value():
        raise IntegrationUnavailable("Background reports require a server-side RENDER_API_KEY.")
    try:
        client = RenderAsync(
            token="" if local else settings.render_api_key.get_secret_value(),
            base_url=(settings.render_local_dev_url or "http://localhost:8120") if local else "https://api.render.com",
        )
        async with client.client.internal.get_async_httpx_client():
            # Keep the response within ordinary web proxy timeouts. Polling
            # also avoids holding an SDK SSE connection across a web request.
            async with asyncio.timeout(20):
                task = await client.workflows.start_task(
                    settings.render_report_task,
                    [snapshot.model_dump(mode="json")],
                )
                while True:
                    result = await client.workflows.get_task_run(task.id)
                    if result.status.value in ("completed", "succeeded"):
                        break
                    if result.status.value in ("failed", "canceled"):
                        raise ValueError("report task failed")
                    await asyncio.sleep(0.5)
        if len(result.results) != 1:
            raise ValueError("unexpected task result count")
        report = CashRiskReport.model_validate(result.results[0])
        # Reject unexpected/cross-request results rather than displaying stale financial facts.
        if report.model_dump() != build_cash_report(snapshot.model_dump(mode="json")):
            raise ValueError("report mismatch")
        return {"run_id": result.id, "report": report.model_dump()}
    except Exception as exc:
        raise IntegrationUnavailable(
            "The background report did not complete within the request window. Try again later."
        ) from exc
