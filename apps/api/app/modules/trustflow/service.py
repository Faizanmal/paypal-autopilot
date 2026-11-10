"""Workspace-scoped TrustFlow reads and writes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.core.money import parse_money
from app.modules.autopilot.models import Invoice
from app.modules.identity.deps import Principal
from app.modules.spendpilot.policy import ensure_workflow_enabled
from app.modules.trustflow.models import Contractor, Customer, Milestone, Project
from app.modules.trustflow.schemas import (
    BillingProgress,
    ContractorCreate,
    CustomerCreate,
    CustomerUpdate,
    MilestoneCreate,
    ProjectCreate,
    ProjectDetail,
    ProjectMilestone,
    ProjectOut,
)
from app.modules.trustflow.transitions import assert_transition, refresh_project_status


async def list_customers(session: AsyncSession, principal: Principal) -> list[Customer]:
    rows = await session.scalars(
        select(Customer)
        .where(Customer.workspace_id == principal.workspace_id)
        .order_by(Customer.created_at.desc())
    )
    return list(rows)


async def create_customer(
    session: AsyncSession, principal: Principal, body: CustomerCreate
) -> Customer:
    email = body.email.lower()
    existing = await session.scalar(
        select(Customer.id).where(
            Customer.workspace_id == principal.workspace_id, Customer.email == email
        )
    )
    if existing is not None:
        raise ConflictError("A customer with that email already exists in this workspace.")
    customer = Customer(
        workspace_id=principal.workspace_id,
        name=body.name.strip(),
        email=email,
        company_name=body.company_name.strip() if body.company_name else None,
        billing_email=body.billing_email.lower() if body.billing_email else None,
        billing_address=body.billing_address,
        notes=body.notes,
    )
    session.add(customer)
    await session.flush()
    record(
        session,
        action="customer.created",
        entity_type="customer",
        entity_id=customer.id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
    )
    await session.commit()
    return customer


async def update_customer(
    session: AsyncSession, principal: Principal, customer_id: uuid.UUID, body: CustomerUpdate
) -> Customer:
    customer = await _customer_in_workspace(session, principal, customer_id)
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes and isinstance(changes["name"], str):
        changes["name"] = changes["name"].strip()
    if "company_name" in changes and isinstance(changes["company_name"], str):
        changes["company_name"] = changes["company_name"].strip()
    if "billing_email" in changes and isinstance(changes["billing_email"], str):
        changes["billing_email"] = changes["billing_email"].lower()
    for key, value in changes.items():
        setattr(customer, key, value)
    record(
        session,
        action="customer.updated",
        entity_type="customer",
        entity_id=customer.id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
    )
    await session.commit()
    return customer


async def archive_customer(session: AsyncSession, principal: Principal, customer_id: uuid.UUID) -> Customer:
    customer = await _customer_in_workspace(session, principal, customer_id)
    if customer.archived_at is None:
        customer.archived_at = datetime.now(UTC)
        record(
            session,
            action="customer.archived",
            entity_type="customer",
            entity_id=customer.id,
            workspace_id=principal.workspace_id,
            actor_user_id=principal.user_id,
        )
        await session.commit()
    return customer


async def _customer_in_workspace(
    session: AsyncSession, principal: Principal, customer_id: uuid.UUID
) -> Customer:
    customer = await session.scalar(
        select(Customer).where(Customer.id == customer_id, Customer.workspace_id == principal.workspace_id)
    )
    if customer is None:
        raise NotFoundError("Customer not found.")
    return customer


async def list_contractors(session: AsyncSession, principal: Principal) -> list[Contractor]:
    rows = await session.scalars(
        select(Contractor)
        .where(Contractor.workspace_id == principal.workspace_id)
        .order_by(Contractor.created_at.desc())
    )
    return list(rows)


async def create_contractor(
    session: AsyncSession, principal: Principal, body: ContractorCreate
) -> Contractor:
    email = body.email.lower()
    existing = await session.scalar(
        select(Contractor.id).where(
            Contractor.workspace_id == principal.workspace_id, Contractor.email == email
        )
    )
    if existing is not None:
        raise ConflictError("A contractor with that email already exists in this workspace.")
    contractor = Contractor(
        workspace_id=principal.workspace_id,
        name=body.name.strip(),
        email=email,
        paypal_email=body.paypal_email.lower() if body.paypal_email else None,
        notes=body.notes,
    )
    session.add(contractor)
    await session.flush()
    record(
        session,
        action="contractor.created",
        entity_type="contractor",
        entity_id=contractor.id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
    )
    await session.commit()
    return contractor


async def _project_in_workspace(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> Project:
    project = await session.scalar(
        select(Project).where(
            Project.id == project_id, Project.workspace_id == principal.workspace_id
        )
    )
    if project is None:
        raise NotFoundError("Project not found.")
    return project


async def list_projects(session: AsyncSession, principal: Principal) -> list[Project]:
    rows = await session.scalars(
        select(Project)
        .where(Project.workspace_id == principal.workspace_id)
        .order_by(Project.created_at.desc())
    )
    return list(rows)


async def create_project(
    session: AsyncSession, principal: Principal, body: ProjectCreate
) -> Project:
    await ensure_workflow_enabled(session, principal, "project")
    amount, currency = parse_money(body.total_amount, body.currency_code)
    if body.starts_on is not None and body.ends_on is not None and body.ends_on < body.starts_on:
        raise ValidationFailedError("The project end date is before the start date.")
    if body.customer_id is not None:
        customer = await _customer_in_workspace(session, principal, body.customer_id)
        if customer.archived_at is not None:
            raise ValidationFailedError("Archived customers cannot be linked to a new project.")
    project = Project(
        workspace_id=principal.workspace_id,
        customer_id=body.customer_id,
        name=body.name.strip(),
        description=body.description,
        currency_code=currency,
        total_amount=amount,
        status="draft",
        starts_on=body.starts_on,
        ends_on=body.ends_on,
    )
    session.add(project)
    await session.flush()
    record(
        session,
        action="project.created",
        entity_type="project",
        entity_id=project.id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        details={"currency_code": currency},
    )
    await session.commit()
    return project


async def list_milestones(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID
) -> list[Milestone]:
    await _project_in_workspace(session, principal, project_id)
    rows = await session.scalars(
        select(Milestone)
        .where(
            Milestone.project_id == project_id,
            Milestone.workspace_id == principal.workspace_id,
        )
        .order_by(Milestone.sequence.asc())
    )
    return list(rows)


async def create_milestone(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID, body: MilestoneCreate
) -> Milestone:
    await ensure_workflow_enabled(session, principal, "milestone")
    project = await _project_in_workspace(session, principal, project_id)
    amount, currency = parse_money(body.amount, body.currency_code)
    if currency != project.currency_code:
        raise ValidationFailedError("Milestone currency must match the project currency.")
    current = await session.scalar(
        select(func.coalesce(func.sum(Milestone.amount), 0)).where(
            Milestone.project_id == project.id,
            Milestone.workspace_id == principal.workspace_id,
        )
    )
    current_sum = Decimal(current or 0)
    if current_sum + amount > project.total_amount:
        raise ValidationFailedError("Milestone amounts cannot exceed the project total.")
    sequence = await session.scalar(
        select(func.coalesce(func.max(Milestone.sequence), 0)).where(Milestone.project_id == project.id)
    )
    milestone = Milestone(
        workspace_id=principal.workspace_id,
        project_id=project.id,
        sequence=int(sequence or 0) + 1,
        name=body.name.strip(),
        currency_code=currency,
        amount=amount,
        trigger_kind=body.trigger_kind,
        status="draft",
        due_on=body.due_on,
        acceptance_condition=body.acceptance_condition,
    )
    session.add(milestone)
    await session.flush()
    await refresh_project_status(session, principal.workspace_id, project.id)
    record(
        session,
        action="milestone.created",
        entity_type="milestone",
        entity_id=milestone.id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        details={"project_id": str(project.id), "sequence": milestone.sequence},
    )
    await session.commit()
    return milestone


def billing_progress(project: Project, milestones: list[Milestone]) -> BillingProgress:
    invoiced = sum((item.amount for item in milestones if item.status in {"invoiced", "paid"}), Decimal("0.00"))
    paid = sum((item.amount for item in milestones if item.status == "paid"), Decimal("0.00"))
    return BillingProgress(
        currency_code=project.currency_code,
        project_total=project.total_amount,
        invoiced_amount=Decimal(invoiced),
        paid_amount=Decimal(paid),
        remaining_amount=project.total_amount - Decimal(paid),
        milestone_count=len(milestones),
    )


async def get_project_detail(session: AsyncSession, principal: Principal, project_id: uuid.UUID) -> ProjectDetail:
    project = await _project_in_workspace(session, principal, project_id)
    milestones = await list_milestones(session, principal, project.id)
    invoices = list(
        await session.scalars(
            select(Invoice).where(Invoice.workspace_id == principal.workspace_id, Invoice.project_id == project.id)
        )
    )
    linked = {invoice.milestone_id: invoice for invoice in invoices if invoice.milestone_id is not None}
    items = []
    for milestone in milestones:
        invoice = linked.get(milestone.id)
        base = ProjectMilestone.model_validate(milestone)
        items.append(
            base.model_copy(
                update={
                    "invoice_id": None if invoice is None else invoice.id,
                    "paypal_invoice_id": None if invoice is None else invoice.paypal_invoice_id,
                }
            )
        )
    return ProjectDetail(
        **ProjectOut.model_validate(project).model_dump(),
        milestones=items,
        progress=billing_progress(project, milestones),
    )


async def transition_milestone(
    session: AsyncSession, principal: Principal, milestone_id: uuid.UUID, target: str
) -> Milestone:
    milestone = await session.scalar(
        select(Milestone).where(Milestone.id == milestone_id, Milestone.workspace_id == principal.workspace_id)
    )
    if milestone is None:
        raise NotFoundError("Milestone not found.")
    if target in {"invoiced", "paid"}:
        raise ValidationFailedError(
            "A milestone becomes invoiced when a PayPal invoice is linked, and paid when that invoice is paid."
        )
    assert_transition(milestone.status, target)
    milestone.status = target
    await refresh_project_status(session, principal.workspace_id, milestone.project_id)
    record(
        session,
        action="milestone.transitioned",
        entity_type="milestone",
        entity_id=milestone.id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        details={"status": target},
    )
    await session.commit()
    return milestone
