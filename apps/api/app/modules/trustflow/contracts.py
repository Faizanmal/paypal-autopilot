"""Contract upload, review, and application.

Applying an extraction creates real project and milestone rows. It does that
only after a person confirms, and only when the extracted amounts agree.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record
from app.core.errors import NotFoundError, ValidationFailedError
from app.core.money import parse_money
from app.modules.ai.security import contains_injection
from app.modules.identity.deps import Principal
from app.modules.trustflow.extract import ContractExtractionDraft, extract_contract_text
from app.modules.trustflow.models import Contract, ContractExtraction, Customer, Milestone, Project
from app.modules.trustflow.schemas import ContractApply, MilestoneCreate, ProjectCreate
from app.modules.trustflow.semantic import enrich_extraction
from app.modules.trustflow.service import create_milestone, create_project

MAX_CONTRACT_BYTES = 1_500_000
PDF_TYPE = "application/pdf"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_ALLOWED = {PDF_TYPE, DOCX_TYPE}


def read_contract_text(content_type: str, data: bytes) -> str:
    if content_type == PDF_TYPE:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    if content_type == DOCX_TYPE:
        from docx import Document

        document = Document(BytesIO(data))
        return "\n".join(paragraph.text for paragraph in document.paragraphs).strip()
    raise ValidationFailedError("Upload a PDF or DOCX contract.")


async def store_contract(
    session: AsyncSession,
    principal: Principal,
    *,
    filename: str,
    content_type: str,
    data: bytes,
    customer_id: uuid.UUID | None,
) -> tuple[Contract, ContractExtraction]:
    if content_type not in _ALLOWED:
        raise ValidationFailedError("Upload a PDF or DOCX contract.")
    if not data or len(data) > MAX_CONTRACT_BYTES:
        raise ValidationFailedError("The contract file is empty or larger than 1.5 MB.")
    safe_name = Path(filename).name.strip()[:200]
    if not safe_name:
        raise ValidationFailedError("The contract needs a filename.")
    if customer_id is not None:
        await _active_customer(session, principal, customer_id)
    digest = hashlib.sha256(data).hexdigest()
    existing = await session.scalar(
        select(Contract).where(Contract.workspace_id == principal.workspace_id, Contract.sha256 == digest)
    )
    if existing is not None:
        extraction = await _latest_extraction(session, principal, existing.id)
        return existing, extraction
    text = read_contract_text(content_type, data)
    if not text:
        raise ValidationFailedError("No text could be read from this contract.")
    draft = extract_contract_text(text[:100_000])
    draft, provider, label = await enrich_extraction(text[:100_000], draft)
    contract = Contract(
        workspace_id=principal.workspace_id,
        customer_id=customer_id,
        filename=safe_name,
        content_type=content_type,
        sha256=digest,
        source_text=text[:100_000],
        status="needs_review",
    )
    session.add(contract)
    await session.flush()
    extraction = ContractExtraction(
        workspace_id=principal.workspace_id,
        contract_id=contract.id,
        provider=provider,
        provider_label=label,
        legally_verified=False,
        payload=draft.model_dump(mode="json"),
        findings=draft.findings,
    )
    session.add(extraction)
    record(
        session,
        action="contract.uploaded",
        entity_type="contract",
        entity_id=contract.id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        details={"filename": safe_name, "legally_verified": False, "findings": draft.findings},
    )
    await session.commit()
    return contract, extraction


async def list_contracts(session: AsyncSession, principal: Principal) -> list[Contract]:
    rows = await session.scalars(
        select(Contract).where(Contract.workspace_id == principal.workspace_id).order_by(Contract.created_at.desc())
    )
    return list(rows)


async def get_contract(
    session: AsyncSession, principal: Principal, contract_id: uuid.UUID
) -> tuple[Contract, ContractExtraction]:
    contract = await session.scalar(
        select(Contract).where(Contract.id == contract_id, Contract.workspace_id == principal.workspace_id)
    )
    if contract is None:
        raise NotFoundError("Contract not found.")
    return contract, await _latest_extraction(session, principal, contract.id)


async def apply_contract(
    session: AsyncSession, principal: Principal, contract_id: uuid.UUID, body: ContractApply
) -> Project:
    contract, extraction = await get_contract(session, principal, contract_id)
    draft = ContractExtractionDraft.model_validate(extraction.payload)
    draft.legally_verified = False
    if draft.apply_blocked():
        raise ValidationFailedError(
            "This contract is not ready to apply. Review the findings. The extraction is not legally verified."
        )
    if draft.total_amount is None or draft.currency_code is None or not draft.milestones:
        raise ValidationFailedError("The contract is missing a total or milestones.")
    customer = await _active_customer(session, principal, body.customer_id)
    if contract.project_id is None:
        amount, currency = parse_money(draft.total_amount, draft.currency_code)
        name = (body.project_name or Path(contract.filename).stem or "Contract project").strip()[:200]
        scope = draft.scope if draft.scope and not contains_injection(draft.scope) else None
        description = scope or "Created from a reviewed contract extraction. This is not a legal verification."
        dates = [item.due_on for item in draft.milestones]
        project = await create_project(
            session,
            principal,
            ProjectCreate(
                name=name,
                description=description[:4000],
                currency_code=currency,
                total_amount=amount,
                customer_id=customer.id,
                starts_on=min(dates) if dates else None,
                ends_on=max(dates) if dates else None,
            ),
        )
        contract.project_id = project.id
        contract.customer_id = customer.id
        await session.commit()
    else:
        found = await session.scalar(
            select(Project).where(Project.id == contract.project_id, Project.workspace_id == principal.workspace_id)
        )
        if found is None:
            raise NotFoundError("Project not found.")
        if found.customer_id != customer.id:
            raise ValidationFailedError("This contract is already applied to a different customer.")
        project = found
    existing_names = {item.name.casefold() for item in await milestones_for_project(session, principal, project.id)}
    acceptance = draft.acceptance_conditions
    if not acceptance or contains_injection(acceptance):
        acceptance = None
    for item in draft.milestones:
        if item.name.casefold() in existing_names:
            continue
        milestone_amount, milestone_currency = parse_money(item.amount, item.currency_code)
        await create_milestone(
            session,
            principal,
            project.id,
            MilestoneCreate(
                name=item.name,
                amount=milestone_amount,
                currency_code=milestone_currency,
                trigger_kind=item.trigger_kind,
                due_on=item.due_on,
                acceptance_condition=acceptance,
            ),
        )
        existing_names.add(item.name.casefold())
    contract.status = "reviewed"
    extraction.reviewed_by_user_id = principal.user_id
    extraction.reviewed_at = datetime.now(UTC)
    extraction.legally_verified = False
    record(
        session,
        action="contract.applied",
        entity_type="contract",
        entity_id=contract.id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        details={"project_id": str(project.id), "legally_verified": False},
    )
    await session.commit()
    return project


async def _active_customer(session: AsyncSession, principal: Principal, customer_id: uuid.UUID) -> Customer:
    customer = await session.scalar(
        select(Customer).where(Customer.id == customer_id, Customer.workspace_id == principal.workspace_id)
    )
    if customer is None:
        raise NotFoundError("Customer not found.")
    if customer.archived_at is not None:
        raise ValidationFailedError("Archived customers cannot be linked to a new project.")
    return customer


async def _latest_extraction(
    session: AsyncSession, principal: Principal, contract_id: uuid.UUID
) -> ContractExtraction:
    extraction = await session.scalar(
        select(ContractExtraction)
        .where(
            ContractExtraction.contract_id == contract_id,
            ContractExtraction.workspace_id == principal.workspace_id,
        )
        .order_by(ContractExtraction.created_at.desc())
    )
    if extraction is None:
        raise NotFoundError("Contract extraction not found.")
    extraction.legally_verified = False
    return extraction


async def milestones_for_project(session: AsyncSession, principal: Principal, project_id: uuid.UUID) -> list[Milestone]:
    rows = await session.scalars(
        select(Milestone)
        .where(Milestone.project_id == project_id, Milestone.workspace_id == principal.workspace_id)
        .order_by(Milestone.sequence.asc())
    )
    return list(rows)
