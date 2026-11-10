"""Milestone lifecycle. A state changes only through this table."""

from __future__ import annotations

from app.core.errors import ValidationFailedError

MILESTONE_STATES = frozenset({"draft", "active", "submitted", "accepted", "invoiced", "paid", "cancelled"})

TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"active", "cancelled"}),
    "active": frozenset({"submitted", "cancelled"}),
    "submitted": frozenset({"accepted", "active", "cancelled"}),
    "accepted": frozenset({"invoiced", "cancelled"}),
    "invoiced": frozenset({"paid"}),
    "paid": frozenset(),
    "cancelled": frozenset(),
}


def assert_transition(current: str, target: str) -> None:
    if target not in MILESTONE_STATES:
        raise ValidationFailedError(f"Milestone status {target} is not a known state.")
    allowed = TRANSITIONS.get(current)
    if allowed is None:
        raise ValidationFailedError(f"Milestone status {current} cannot be changed.")
    if target not in allowed:
        raise ValidationFailedError(f"A milestone cannot move from {current} to {target}.")


def project_status_for(statuses: set[str]) -> str:
    """Derive a project status from its milestone states.

    draft: nothing has started. active: work or billing is underway.
    completed: every milestone is paid or cancelled, and at least one is paid.
    cancelled: every milestone was cancelled.
    """
    known = statuses & MILESTONE_STATES
    if not known:
        return "draft"
    if known == {"cancelled"}:
        return "cancelled"
    unfinished = known & {"draft", "active", "submitted", "accepted", "invoiced"}
    if "paid" in known and not unfinished:
        return "completed"
    if known & {"active", "submitted", "accepted", "invoiced", "paid"}:
        return "active"
    return "draft"


async def refresh_project_status(session, workspace_id, project_id) -> None:
    from sqlalchemy import select

    from app.modules.trustflow.models import Milestone, Project

    project = await session.scalar(
        select(Project).where(Project.id == project_id, Project.workspace_id == workspace_id)
    )
    if project is None:
        return
    rows = list(
        await session.scalars(
            select(Milestone.status).where(
                Milestone.project_id == project_id, Milestone.workspace_id == workspace_id
            )
        )
    )
    project.status = project_status_for(set(rows))


async def record_milestone_paid(session, workspace_id, milestone_id) -> None:
    """Move an invoiced milestone to paid after its PayPal invoice is paid.

    The caller owns the transaction. This does not import the invoice service.
    """
    from sqlalchemy import select

    from app.modules.trustflow.models import Milestone

    milestone = await session.scalar(
        select(Milestone).where(Milestone.id == milestone_id, Milestone.workspace_id == workspace_id)
    )
    if milestone is None or milestone.status != "invoiced":
        return
    assert_transition(milestone.status, "paid")
    milestone.status = "paid"
    await refresh_project_status(session, workspace_id, milestone.project_id)
