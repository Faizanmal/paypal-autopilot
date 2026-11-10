"""Resolve names inside the signed-in workspace. Model text never supplies an id."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.schemas import ActionType, WorkflowPlanDraft
from app.modules.autopilot.models import Invoice
from app.modules.identity.deps import Principal
from app.modules.trustflow.extract import ContractExtractionDraft
from app.modules.trustflow.models import Contract, ContractExtraction, Contractor, Customer, Milestone, Project

_CLOSED = ("paid", "marked_as_paid", "cancelled", "refunded", "partially_refunded", "marked_as_refunded")


@dataclass
class Resolution:
    clarifications: list[str] = field(default_factory=list)
    trusted: dict[int, dict[str, str]] = field(default_factory=dict)


class _Named(Protocol):
    id: uuid.UUID
    name: str
    email: str


def _matches(rows: Sequence[_Named], name: str) -> list[_Named]:
    folded = name.casefold()
    exact = [row for row in rows if str(row.name).casefold() == folded]
    if exact:
        return exact
    return [row for row in rows if folded in str(row.name).casefold()]


async def resolve_plan(session: AsyncSession, principal: Principal, draft: WorkflowPlanDraft) -> Resolution:
    customers = list(
        await session.scalars(select(Customer).where(Customer.workspace_id == principal.workspace_id))
    )
    contractors = list(
        await session.scalars(select(Contractor).where(Contractor.workspace_id == principal.workspace_id))
    )
    resolution = Resolution()
    contracts = list(await session.scalars(select(Contract).where(Contract.workspace_id == principal.workspace_id)))
    projects = list(await session.scalars(select(Project).where(Project.workspace_id == principal.workspace_id)))
    for step in draft.steps:
        trusted: dict[str, str] = {}
        if isinstance(step.arguments.get("customer_name"), str) and step.action_type is not ActionType.LOOKUP_CUSTOMER:
            chosen = _choose(resolution, customers, "customer", step.arguments["customer_name"])
            if chosen is not None:
                trusted["customer_id"] = str(chosen.id)
                if step.action_type is ActionType.SCHEDULE_REMINDER and not step.depends_on:
                    await _one_unpaid_invoice(session, principal, resolution, trusted, chosen)
        if step.action_type in {
            ActionType.PREPARE_PAYOUT,
            ActionType.EXPLAIN_POLICY,
            ActionType.RESUME_PAYOUT,
        } and isinstance(step.arguments.get("recipient_name"), str):
            chosen = _choose(resolution, contractors, "contractor", step.arguments["recipient_name"])
            if chosen is not None:
                trusted["contractor_id"] = str(chosen.id)
            if step.action_type is ActionType.PREPARE_PAYOUT and "client payment cleared" in step.preconditions:
                await _cleared_payment(session, principal, resolution, trusted)
        if isinstance(step.arguments.get("contract_name"), str):
            await _one_contract(
                session,
                principal,
                resolution,
                trusted,
                contracts,
                step.arguments["contract_name"],
                step.action_type,
            )
        if isinstance(step.arguments.get("project_name"), str) and step.action_type in {
            ActionType.GET_PROJECT_STATUS,
            ActionType.PREPARE_MILESTONE_INVOICE,
        }:
            await _project_and_milestone(session, principal, resolution, trusted, projects, step)
        resolution.trusted[step.sequence] = trusted
    return resolution


def _choose(resolution: Resolution, rows: Sequence[_Named], kind: str, name: str) -> _Named | None:
    matches = _matches(rows, name)
    if len(matches) == 1:
        return matches[0]
    if not matches:
        resolution.clarifications.append(
            f"No {kind} named {name} is in this workspace. Which {kind} should be used?"
        )
        return None
    labels = ", ".join(f"{row.name} <{row.email}>" for row in matches)
    resolution.clarifications.append(
        f"{kind.capitalize()} {name} matches more than one record ({labels}). Which one should be used?"
    )
    return None


async def _one_unpaid_invoice(
    session: AsyncSession,
    principal: Principal,
    resolution: Resolution,
    trusted: dict[str, str],
    customer: _Named,
) -> None:
    rows = list(
        await session.scalars(
            select(Invoice).where(
                Invoice.workspace_id == principal.workspace_id,
                Invoice.customer_id == customer.id,
                Invoice.status.notin_(_CLOSED),
            )
        )
    )
    if len(rows) == 1:
        trusted["invoice_id"] = str(rows[0].id)
        return
    if not rows:
        resolution.clarifications.append(
            f"{customer.name} has no unpaid invoice to remind. Which invoice should the reminder use?"
        )
        return
    resolution.clarifications.append(
        f"{customer.name} has more than one unpaid invoice. Which invoice should the reminder use?"
    )


async def _cleared_payment(
    session: AsyncSession,
    principal: Principal,
    resolution: Resolution,
    trusted: dict[str, str],
) -> None:
    rows = list(
        await session.scalars(
            select(Invoice).where(
                Invoice.workspace_id == principal.workspace_id,
                Invoice.status.in_(("paid", "marked_as_paid")),
            )
        )
    )
    if len(rows) == 1:
        trusted["invoice_id"] = str(rows[0].id)
    elif len(rows) > 1:
        resolution.clarifications.append(
            "More than one client payment has cleared. Which invoice should this payout follow?"
        )


def _by_name(rows: Sequence[Project], name: str) -> list[Project]:
    folded = name.casefold()
    exact = [row for row in rows if row.name.casefold() == folded]
    if exact:
        return exact
    return [row for row in rows if folded in row.name.casefold()]


def _by_filename(rows: Sequence[Contract], name: str) -> list[Contract]:
    folded = name.casefold()

    def names(row: Contract) -> tuple[str, str]:
        return row.filename.casefold(), Path(row.filename).stem.casefold()

    exact = [row for row in rows if folded in names(row)]
    if exact:
        return exact
    return [row for row in rows if any(folded in label for label in names(row))]


async def _one_contract(
    session: AsyncSession,
    principal: Principal,
    resolution: Resolution,
    trusted: dict[str, str],
    contracts: Sequence[Contract],
    name: str,
    action_type: ActionType,
) -> None:
    matches = _by_filename(contracts, name)
    if len(matches) != 1:
        if not matches:
            resolution.clarifications.append(
                f"No contract named {name} is in this workspace. Which contract should be used?"
            )
        else:
            labels = ", ".join(row.filename for row in matches)
            resolution.clarifications.append(
                f"Contract {name} matches more than one record ({labels}). Which one should be used?"
            )
        return
    contract = matches[0]
    trusted["contract_id"] = str(contract.id)
    if action_type is not ActionType.CREATE_MILESTONES:
        return
    extraction = await session.scalar(
        select(ContractExtraction)
        .where(
            ContractExtraction.contract_id == contract.id,
            ContractExtraction.workspace_id == principal.workspace_id,
        )
        .order_by(ContractExtraction.created_at.desc())
    )
    if extraction is None:
        resolution.clarifications.append(f"{contract.filename} has no extraction to review.")
        return
    draft = ContractExtractionDraft.model_validate(extraction.payload)
    if draft.apply_blocked():
        resolution.clarifications.append(
            f"{contract.filename} has findings that must be reviewed before milestones can be created."
        )
        trusted.pop("contract_id", None)
        return
    if contract.customer_id is None:
        resolution.clarifications.append(f"Which customer should {contract.filename} bill?")
        return
    trusted["customer_id"] = str(contract.customer_id)


async def _project_and_milestone(
    session: AsyncSession,
    principal: Principal,
    resolution: Resolution,
    trusted: dict[str, str],
    projects: Sequence[Project],
    step,
) -> None:
    name = str(step.arguments["project_name"])
    matches = _by_name(projects, name)
    if len(matches) != 1:
        if not matches:
            resolution.clarifications.append(
                f"No project named {name} is in this workspace. Which project should be used?"
            )
        else:
            labels = ", ".join(row.name for row in matches)
            resolution.clarifications.append(
                f"Project {name} matches more than one record ({labels}). Which one should be used?"
            )
        return
    project = matches[0]
    trusted["project_id"] = str(project.id)
    if step.action_type is not ActionType.PREPARE_MILESTONE_INVOICE:
        return
    milestone_name = str(step.arguments.get("milestone_name") or "")
    milestones = list(
        await session.scalars(
            select(Milestone).where(
                Milestone.workspace_id == principal.workspace_id, Milestone.project_id == project.id
            )
        )
    )
    folded = milestone_name.casefold()
    chosen = [item for item in milestones if item.name.casefold() == folded]
    if len(chosen) != 1:
        chosen = [item for item in milestones if folded and folded in item.name.casefold()]
    if len(chosen) != 1:
        if not chosen:
            resolution.clarifications.append(
                f"No milestone named {milestone_name} is on {project.name}. Which milestone should be invoiced?"
            )
        else:
            labels = ", ".join(item.name for item in chosen)
            resolution.clarifications.append(
                f"Milestone {milestone_name} matches more than one record ({labels}). Which one should be used?"
            )
        return
    milestone = chosen[0]
    if milestone.status != "accepted":
        resolution.clarifications.append(
            f"Milestone {milestone.name} is {milestone.status}, so it cannot be invoiced until it is accepted."
        )
        return
    trusted["milestone_id"] = str(milestone.id)
