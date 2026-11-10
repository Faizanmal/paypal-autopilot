from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.deps import CurrentPrincipal, DbSession
from app.core.config import get_settings
from app.integrations.paypal.client import get_paypal_client
from app.modules.spendpilot.policy import get_policy, update_policy
from app.modules.spendpilot.schemas import (
    ItemList,
    PayoutCapabilityOut,
    PayoutIntentCreate,
    PayoutRequestOut,
    PolicyOut,
    PolicyUpdate,
    RejectPayout,
)
from app.modules.spendpilot.service import (
    approve_payout,
    cancel_payout,
    create_payout_intent,
    execute_payout,
    expire_payout,
    get_payout_capability,
    list_payout_requests,
    payout_out,
    reject_payout,
    sync_payout,
)

router = APIRouter(tags=["payouts"])


@router.get("/payouts/capability", response_model=PayoutCapabilityOut)
async def get_capability(principal: CurrentPrincipal) -> PayoutCapabilityOut:
    del principal
    return await get_payout_capability(get_settings(), get_paypal_client())


@router.get("/payout-requests", response_model=ItemList[PayoutRequestOut])
async def get_payout_requests(principal: CurrentPrincipal, db: DbSession) -> ItemList[PayoutRequestOut]:
    rows = await list_payout_requests(db, principal)
    return ItemList(items=[await payout_out(db, row) for row in rows])


@router.post("/payout-requests", response_model=PayoutRequestOut, status_code=201)
async def post_payout_request(
    body: PayoutIntentCreate, principal: CurrentPrincipal, db: DbSession
) -> PayoutRequestOut:
    payout = await create_payout_intent(db, principal, body)
    return await payout_out(db, payout)


@router.get("/financial-policy", response_model=PolicyOut)
async def get_financial_policy(principal: CurrentPrincipal, db: DbSession) -> PolicyOut:
    policy = await get_policy(db, principal.workspace_id)
    return PolicyOut.model_validate(policy)


@router.patch("/financial-policy", response_model=PolicyOut)
async def patch_financial_policy(
    body: PolicyUpdate, principal: CurrentPrincipal, db: DbSession
) -> PolicyOut:
    policy = await update_policy(db, principal, body)
    return PolicyOut.model_validate(policy)


@router.post("/payout-requests/{payout_id}/approve", response_model=PayoutRequestOut)
async def post_approve_payout(
    payout_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession
) -> PayoutRequestOut:
    payout = await approve_payout(db, principal, payout_id)
    return await payout_out(db, payout)


@router.post("/payout-requests/{payout_id}/reject", response_model=PayoutRequestOut)
async def post_reject_payout(
    payout_id: uuid.UUID, body: RejectPayout, principal: CurrentPrincipal, db: DbSession
) -> PayoutRequestOut:
    payout = await reject_payout(db, principal, payout_id, body.reason)
    return await payout_out(db, payout)


@router.post("/payout-requests/{payout_id}/cancel", response_model=PayoutRequestOut)
async def post_cancel_payout(
    payout_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession
) -> PayoutRequestOut:
    payout = await cancel_payout(db, principal, payout_id)
    return await payout_out(db, payout)


@router.post("/payout-requests/{payout_id}/expire", response_model=PayoutRequestOut)
async def post_expire_payout(
    payout_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession
) -> PayoutRequestOut:
    payout = await expire_payout(db, principal, payout_id)
    return await payout_out(db, payout)


@router.post("/payout-requests/{payout_id}/execute", response_model=PayoutRequestOut)
async def post_execute_payout(
    payout_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession
) -> PayoutRequestOut:
    payout = await execute_payout(db, principal, payout_id, get_paypal_client(), get_settings())
    return await payout_out(db, payout)


@router.post("/payout-requests/{payout_id}/sync", response_model=PayoutRequestOut)
async def post_sync_payout(
    payout_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession
) -> PayoutRequestOut:
    payout = await sync_payout(db, principal, payout_id, get_paypal_client(), get_settings())
    return await payout_out(db, payout)
