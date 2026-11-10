from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Form, UploadFile

from app.api.deps import CurrentPrincipal, DbSession
from app.core.config import get_settings
from app.integrations.paypal.client import get_paypal_client
from app.modules.autopilot.schemas import InvoiceOut
from app.modules.trustflow.billing import prepare_milestone_invoice
from app.modules.trustflow.contracts import (
    DOCX_TYPE,
    PDF_TYPE,
    apply_contract,
    get_contract,
    list_contracts,
    store_contract,
)
from app.modules.trustflow.extract import NOT_LEGALLY_VERIFIED
from app.modules.trustflow.models import Contract, ContractExtraction
from app.modules.trustflow.schemas import (
    ContractApply,
    ContractorCreate,
    ContractorOut,
    ContractOut,
    CustomerCreate,
    CustomerOut,
    CustomerUpdate,
    ItemList,
    MilestoneCreate,
    MilestoneOut,
    MilestoneTransition,
    ProjectCreate,
    ProjectDetail,
    ProjectOut,
)
from app.modules.trustflow.service import (
    archive_customer,
    create_contractor,
    create_customer,
    create_milestone,
    create_project,
    get_project_detail,
    list_contractors,
    list_customers,
    list_milestones,
    list_projects,
    transition_milestone,
    update_customer,
)

router = APIRouter(tags=["trustflow"])


@router.get("/customers", response_model=ItemList[CustomerOut])
async def get_customers(principal: CurrentPrincipal, db: DbSession) -> ItemList[CustomerOut]:
    rows = await list_customers(db, principal)
    return ItemList(items=[CustomerOut.model_validate(row) for row in rows])


@router.post("/customers", response_model=CustomerOut, status_code=201)
async def post_customer(
    body: CustomerCreate, principal: CurrentPrincipal, db: DbSession
) -> CustomerOut:
    return CustomerOut.model_validate(await create_customer(db, principal, body))


@router.patch("/customers/{customer_id}", response_model=CustomerOut)
async def patch_customer(
    customer_id: uuid.UUID, body: CustomerUpdate, principal: CurrentPrincipal, db: DbSession
) -> CustomerOut:
    return CustomerOut.model_validate(await update_customer(db, principal, customer_id, body))


@router.post("/customers/{customer_id}/archive", response_model=CustomerOut)
async def post_archive_customer(
    customer_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession
) -> CustomerOut:
    return CustomerOut.model_validate(await archive_customer(db, principal, customer_id))


@router.get("/contractors", response_model=ItemList[ContractorOut])
async def get_contractors(principal: CurrentPrincipal, db: DbSession) -> ItemList[ContractorOut]:
    rows = await list_contractors(db, principal)
    return ItemList(items=[ContractorOut.model_validate(row) for row in rows])


@router.post("/contractors", response_model=ContractorOut, status_code=201)
async def post_contractor(
    body: ContractorCreate, principal: CurrentPrincipal, db: DbSession
) -> ContractorOut:
    return ContractorOut.model_validate(await create_contractor(db, principal, body))


@router.get("/projects", response_model=ItemList[ProjectOut])
async def get_projects(principal: CurrentPrincipal, db: DbSession) -> ItemList[ProjectOut]:
    rows = await list_projects(db, principal)
    return ItemList(items=[ProjectOut.model_validate(row) for row in rows])


@router.post("/projects", response_model=ProjectOut, status_code=201)
async def post_project(
    body: ProjectCreate, principal: CurrentPrincipal, db: DbSession
) -> ProjectOut:
    return ProjectOut.model_validate(await create_project(db, principal, body))


@router.get("/projects/{project_id}", response_model=ProjectDetail)
async def get_project(project_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> ProjectDetail:
    return await get_project_detail(db, principal, project_id)


@router.get("/projects/{project_id}/milestones", response_model=ItemList[MilestoneOut])
async def get_milestones(
    project_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession
) -> ItemList[MilestoneOut]:
    rows = await list_milestones(db, principal, project_id)
    return ItemList(items=[MilestoneOut.model_validate(row) for row in rows])


@router.post("/projects/{project_id}/milestones", response_model=MilestoneOut, status_code=201)
async def post_milestone(
    project_id: uuid.UUID, body: MilestoneCreate, principal: CurrentPrincipal, db: DbSession
) -> MilestoneOut:
    return MilestoneOut.model_validate(await create_milestone(db, principal, project_id, body))


@router.post("/milestones/{milestone_id}/transition", response_model=MilestoneOut)
async def post_milestone_transition(
    milestone_id: uuid.UUID, body: MilestoneTransition, principal: CurrentPrincipal, db: DbSession
) -> MilestoneOut:
    return MilestoneOut.model_validate(await transition_milestone(db, principal, milestone_id, body.status))


@router.post("/milestones/{milestone_id}/invoice", response_model=InvoiceOut, status_code=201)
async def post_milestone_invoice(
    milestone_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession
) -> InvoiceOut:
    invoice = await prepare_milestone_invoice(db, principal, milestone_id, get_paypal_client(), get_settings())
    return InvoiceOut.model_validate(invoice)


def _contract_out(contract: Contract, extraction: ContractExtraction) -> ContractOut:
    payload = dict(extraction.payload)
    payload["legally_verified"] = False
    return ContractOut(
        id=contract.id,
        filename=contract.filename,
        content_type=contract.content_type,
        status=contract.status,
        customer_id=contract.customer_id,
        project_id=contract.project_id,
        provider_label=extraction.provider_label,
        legally_verified=False,
        disclaimer=NOT_LEGALLY_VERIFIED,
        extraction=payload,
        findings=list(extraction.findings or []),
    )


@router.get("/contracts", response_model=ItemList[ContractOut])
async def get_contracts(principal: CurrentPrincipal, db: DbSession) -> ItemList[ContractOut]:
    items = []
    for contract in await list_contracts(db, principal):
        stored, extraction = await get_contract(db, principal, contract.id)
        items.append(_contract_out(stored, extraction))
    return ItemList(items=items)


@router.post("/contracts", response_model=ContractOut, status_code=201)
async def post_contract(
    principal: CurrentPrincipal,
    db: DbSession,
    file: UploadFile = File(...),  # noqa: B008
    customer_id: uuid.UUID | None = Form(default=None),  # noqa: B008
) -> ContractOut:
    data = await file.read()
    filename = file.filename or "contract"
    content_type = file.content_type or ""
    lowered = filename.lower()
    if content_type not in {PDF_TYPE, DOCX_TYPE}:
        if lowered.endswith(".pdf"):
            content_type = PDF_TYPE
        elif lowered.endswith(".docx"):
            content_type = DOCX_TYPE
    contract, extraction = await store_contract(
        db,
        principal,
        filename=filename,
        content_type=content_type,
        data=data,
        customer_id=customer_id,
    )
    return _contract_out(contract, extraction)


@router.get("/contracts/{contract_id}", response_model=ContractOut)
async def get_one_contract(contract_id: uuid.UUID, principal: CurrentPrincipal, db: DbSession) -> ContractOut:
    contract, extraction = await get_contract(db, principal, contract_id)
    return _contract_out(contract, extraction)


@router.post("/contracts/{contract_id}/apply", response_model=ProjectOut, status_code=201)
async def post_apply_contract(
    contract_id: uuid.UUID, body: ContractApply, principal: CurrentPrincipal, db: DbSession
) -> ProjectOut:
    return ProjectOut.model_validate(await apply_contract(db, principal, contract_id, body))
