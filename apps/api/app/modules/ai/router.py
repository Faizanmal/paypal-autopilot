from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.deps import CurrentPrincipal, DbSession
from app.modules.ai.schemas import AgentRunOut, ItemList, PlanRequest, PlanRevisionRequest
from app.modules.ai.service import cancel_plan, confirm_plan, create_plan, get_plan, list_plans, retry_plan, revise_plan

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/plans", response_model=AgentRunOut, status_code=201)
async def post_plan(body: PlanRequest, principal: CurrentPrincipal, db: DbSession) -> AgentRunOut:
    return await create_plan(db, principal, body.instruction)


@router.get("/runs", response_model=ItemList[AgentRunOut])
async def get_runs(principal: CurrentPrincipal, db: DbSession) -> ItemList[AgentRunOut]:
    return ItemList(items=await list_plans(db, principal))


@router.get("/runs/{run_id}", response_model=AgentRunOut)
async def get_run(run_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> AgentRunOut:
    return await get_plan(db, principal, run_id)


@router.post("/runs/{run_id}/confirm", response_model=AgentRunOut)
async def post_confirm(run_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> AgentRunOut:
    return await confirm_plan(db, principal, run_id)


@router.post("/runs/{run_id}/revise", response_model=AgentRunOut, status_code=201)
async def post_revision(
    run_id: uuid.UUID, body: PlanRevisionRequest, principal: CurrentPrincipal, db: DbSession
) -> AgentRunOut:
    return await revise_plan(db, principal, run_id, body)


@router.post("/runs/{run_id}/retry", response_model=AgentRunOut)
async def post_retry(run_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> AgentRunOut:
    return await retry_plan(db, principal, run_id)


@router.post("/runs/{run_id}/cancel", response_model=AgentRunOut)
async def post_cancel(run_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> AgentRunOut:
    return await cancel_plan(db, principal, run_id)
