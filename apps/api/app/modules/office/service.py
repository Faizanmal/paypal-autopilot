"""Workspace reads for audit, workflows, schedules, and membership."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.audit.service import record
from app.core.errors import ConflictError, NotFoundError
from app.modules.autopilot.models import ScheduledAction
from app.modules.identity.deps import Principal
from app.modules.identity.models import User, WorkspaceMember
from app.modules.office.schemas import AuditEntryOut, MemberOut, WorkflowOut, WorkflowStepOut
from app.modules.workflows.models import Workflow, WorkflowStep


async def list_audit_entries(session: AsyncSession, principal: Principal) -> list[AuditEntryOut]:
    rows = list(
        (
            await session.execute(
                select(AuditLog, User.full_name, User.email)
                .outerjoin(User, User.id == AuditLog.actor_user_id)
                .where(AuditLog.workspace_id == principal.workspace_id)
                .order_by(AuditLog.created_at.desc())
                .limit(100)
            )
        ).all()
    )
    entries: list[AuditEntryOut] = []
    for entry, name, email in rows:
        details = entry.details if isinstance(entry.details, dict) else {}
        entries.append(
            AuditEntryOut(
                id=entry.id,
                created_at=entry.created_at,
                actor_name=name if isinstance(name, str) else None,
                actor_email=email if isinstance(email, str) else None,
                action=entry.action,
                entity_type=entry.entity_type,
                entity_id=entry.entity_id,
                result=_result(entry.action, details),
                provider_reference=_text(details.get("provider_reference")),
                approval_id=_text(details.get("approval_id")),
                proposed_by_ai=_proposed_by_ai(entry.action, details),
                policy_evaluated=_policy_evaluated(entry.action, details),
                paypal_operation=_paypal_operation(entry.action, details),
            )
        )
    return entries


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _proposed_by_ai(action: str, details: dict) -> bool:
    if details.get("proposed_by_ai") is True:
        return True
    return action.startswith("agent.")


def _result(action: str, details: dict) -> str:
    status = details.get("status")
    if isinstance(status, str) and status:
        return status
    if details.get("reconciliation_required") is True:
        return "reconciliation_required"
    reason = _text(details.get("reason")) or _text(details.get("code"))
    if reason:
        return reason
    provider_status = _text(details.get("provider_status"))
    if provider_status:
        return provider_status
    return action


def _policy_evaluated(action: str, details: dict) -> str | None:
    explicit = _text(details.get("policy_evaluated"))
    if explicit:
        return explicit
    if action.startswith("policy."):
        return _text(details.get("action_type")) or action
    if details.get("violations"):
        return "financial_policy"
    if details.get("action_hash"):
        return "exact_action_approval"
    return None


def _paypal_operation(action: str, details: dict) -> str | None:
    explicit = _text(details.get("paypal_operation"))
    if explicit:
        return explicit
    invoice_id = _text(details.get("paypal_invoice_id"))
    if invoice_id:
        if "remind" in action:
            return f"invoicing.remind:{invoice_id}"
        if "sent" in action:
            return f"invoicing.send:{invoice_id}"
        if "draft" in action or "created" in action:
            return f"invoicing.create:{invoice_id}"
        return f"invoicing:{invoice_id}"
    batch_id = _text(details.get("paypal_payout_batch_id"))
    if batch_id:
        return f"payouts.create_batch:{batch_id}"
    provider = _text(details.get("provider_reference"))
    if provider:
        return provider
    debug_id = _text(details.get("debug_id"))
    if debug_id:
        return f"paypal.debug:{debug_id}"
    return None


async def list_workflows(session: AsyncSession, principal: Principal) -> list[WorkflowOut]:
    workflows = list(
        await session.scalars(
            select(Workflow)
            .where(Workflow.workspace_id == principal.workspace_id)
            .order_by(Workflow.created_at.desc())
            .limit(40)
        )
    )
    if not workflows:
        return []
    ids = [workflow.id for workflow in workflows]
    steps = list(
        await session.scalars(
            select(WorkflowStep)
            .where(WorkflowStep.workspace_id == principal.workspace_id, WorkflowStep.workflow_id.in_(ids))
            .order_by(WorkflowStep.sequence.asc())
        )
    )
    grouped: dict[uuid.UUID, list[WorkflowStepOut]] = {workflow.id: [] for workflow in workflows}
    for step in steps:
        grouped.setdefault(step.workflow_id, []).append(
            WorkflowStepOut(
                sequence=step.sequence,
                step_type=step.step_type,
                status=step.status,
                condition=step.condition,
                waiting_for=step.waiting_for,
                attempts=step.attempts,
                provider_reference=step.provider_reference,
                error=step.error,
            )
        )
    return [
        WorkflowOut(
            id=workflow.id,
            status=workflow.status,
            agent_run_id=workflow.agent_run_id,
            project_id=workflow.project_id,
            confirmed_at=workflow.confirmed_at,
            steps=grouped.get(workflow.id, []),
        )
        for workflow in workflows
    ]


async def list_scheduled_actions(session: AsyncSession, principal: Principal) -> list[ScheduledAction]:
    rows = await session.scalars(
        select(ScheduledAction)
        .where(ScheduledAction.workspace_id == principal.workspace_id)
        .order_by(ScheduledAction.run_after.asc())
        .limit(100)
    )
    return list(rows)


async def transition_scheduled_action(
    session: AsyncSession, principal: Principal, action_id: uuid.UUID, decision: str
) -> ScheduledAction:
    row = await session.scalar(
        select(ScheduledAction).where(
            ScheduledAction.id == action_id, ScheduledAction.workspace_id == principal.workspace_id
        )
    )
    if row is None:
        raise NotFoundError("Scheduled action not found.")
    if decision == "pause" and row.status == "pending":
        row.status = "paused"
    elif decision == "resume" and row.status == "paused":
        row.status = "pending"
    elif decision == "cancel" and row.status in {"pending", "paused", "failed"}:
        row.status = "cancelled"
    else:
        raise ConflictError("This scheduled action cannot take that transition.")
    record(
        session,
        action=f"schedule.{decision}",
        entity_type="scheduled_action",
        entity_id=row.id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        details={"status": row.status, "job_type": row.job_type},
    )
    await session.commit()
    return row


async def list_members(session: AsyncSession, principal: Principal) -> list[MemberOut]:
    rows = list(
        (
            await session.execute(
                select(WorkspaceMember.role, User)
                .join(User, User.id == WorkspaceMember.user_id)
                .where(WorkspaceMember.workspace_id == principal.workspace_id)
                .order_by(User.full_name.asc())
            )
        ).all()
    )
    return [
        MemberOut(user_id=user.id, full_name=user.full_name, email=user.email, role=role) for role, user in rows
    ]
