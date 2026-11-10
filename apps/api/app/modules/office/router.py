"""Read-only office endpoints plus schedule pause, resume, and cancel."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.deps import CurrentPrincipal, DbSession
from app.core.config import get_settings
from app.modules.office.schemas import (
    AuditEntryOut,
    ItemList,
    MemberOut,
    RuntimeOut,
    ScheduledActionOut,
    WorkflowOut,
)
from app.modules.office.service import (
    list_audit_entries,
    list_members,
    list_scheduled_actions,
    list_workflows,
    transition_scheduled_action,
)

router = APIRouter(tags=["office"])


@router.get("/audit-logs", response_model=ItemList[AuditEntryOut])
async def get_audit_logs(principal: CurrentPrincipal, db: DbSession) -> ItemList[AuditEntryOut]:
    return ItemList(items=await list_audit_entries(db, principal))


@router.get("/workflows", response_model=ItemList[WorkflowOut])
async def get_workflows(principal: CurrentPrincipal, db: DbSession) -> ItemList[WorkflowOut]:
    return ItemList(items=await list_workflows(db, principal))


@router.get("/scheduled-actions", response_model=ItemList[ScheduledActionOut])
async def get_scheduled_actions(principal: CurrentPrincipal, db: DbSession) -> ItemList[ScheduledActionOut]:
    rows = await list_scheduled_actions(db, principal)
    return ItemList(items=[ScheduledActionOut.model_validate(row) for row in rows])


@router.post("/scheduled-actions/{action_id}/pause", response_model=ScheduledActionOut)
async def post_pause_scheduled_action(
    action_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession
) -> ScheduledActionOut:
    return ScheduledActionOut.model_validate(
        await transition_scheduled_action(db, principal, action_id, "pause")
    )


@router.post("/scheduled-actions/{action_id}/resume", response_model=ScheduledActionOut)
async def post_resume_scheduled_action(
    action_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession
) -> ScheduledActionOut:
    return ScheduledActionOut.model_validate(
        await transition_scheduled_action(db, principal, action_id, "resume")
    )


@router.post("/scheduled-actions/{action_id}/cancel", response_model=ScheduledActionOut)
async def post_cancel_scheduled_action(
    action_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession
) -> ScheduledActionOut:
    return ScheduledActionOut.model_validate(
        await transition_scheduled_action(db, principal, action_id, "cancel")
    )


@router.get("/workspace/members", response_model=ItemList[MemberOut])
async def get_members(principal: CurrentPrincipal, db: DbSession) -> ItemList[MemberOut]:
    return ItemList(items=await list_members(db, principal))


@router.get("/workspace/runtime", response_model=RuntimeOut)
async def get_runtime(principal: CurrentPrincipal) -> RuntimeOut:
    del principal
    settings = get_settings()
    return RuntimeOut(
        paypal_env=settings.paypal_env.value,
        paypal_configured=settings.paypal_configured,
        payouts_execution_enabled=settings.paypal_payouts_execution,
        ai_provider=settings.ai_provider.value,
        ai_credentials_configured=settings.ai_credentials_configured,
    )
