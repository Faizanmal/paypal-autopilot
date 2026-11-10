"""Cash snapshot and the user-supplied opening balance."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import CurrentPrincipal, DbSession
from app.modules.ai.studio import limit_usage
from app.modules.finance.reports import run_cash_report
from app.modules.finance.schemas import AssumptionIn, AssumptionOut, FinanceSnapshotOut
from app.modules.finance.service import save_assumption, snapshot

router = APIRouter(prefix="/finance", tags=["finance"])


@router.post("/background-report")
async def post_background_report(principal: CurrentPrincipal, db: DbSession) -> dict:
    await limit_usage(principal.workspace_id, "background-report", 10)
    data = await snapshot(db, principal)
    return await run_cash_report(data)


@router.get("/snapshot", response_model=FinanceSnapshotOut)
async def get_snapshot(
    principal: CurrentPrincipal,
    db: DbSession,
    horizon_days: int = Query(default=30, ge=1, le=366),
) -> FinanceSnapshotOut:
    return await snapshot(db, principal, horizon_days=horizon_days)


@router.put("/assumptions", response_model=AssumptionOut)
async def put_assumption(body: AssumptionIn, principal: CurrentPrincipal, db: DbSession) -> AssumptionOut:
    return await save_assumption(db, principal, body.opening_balance, body.as_of)
