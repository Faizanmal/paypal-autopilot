"""Plan, confirm, and retry. The planner never calls PayPal."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record
from app.core.config import SUPPORTED_CURRENCIES, get_settings
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.modules.ai.models import AgentAction, AgentRun
from app.modules.ai.providers import get_planner
from app.modules.ai.providers.fallback import FALLBACK_LABEL
from app.modules.ai.resolve import resolve_plan
from app.modules.ai.schemas import (
    AgentRunOut,
    AgentStepOut,
    PlanRevisionRequest,
    WorkflowPlanDraft,
    WorkflowPlanningContext,
)
from app.modules.ai.tools import execute_tool
from app.modules.ai.validate import validate_plan
from app.modules.identity.deps import Principal
from app.modules.trustflow.service import list_contractors, list_customers
from app.modules.workflows.models import Workflow, WorkflowStep

logger = logging.getLogger("app.ai")

_CLARIFICATION = {
    "missing_amount",
    "missing_currency",
    "missing_required",
    "unsupported_instruction",
    "ambiguous",
}
_RETRY_STATUSES = {"failed", "blocked", "executing", "waiting"}
_CANCEL_STATUSES = {"pending_confirmation", "failed", "blocked", "executing", "waiting"}


async def create_plan(session: AsyncSession, principal: Principal, instruction: str) -> AgentRunOut:
    text = instruction.strip()
    settings = get_settings()
    planner = get_planner(settings)
    customers = await list_customers(session, principal)
    contractors = await list_contractors(session, principal)
    context = WorkflowPlanningContext(
        workspace_name=principal.workspace.name,
        customer_names=[customer.name for customer in customers],
        contractor_names=[contractor.name for contractor in contractors],
        supported_currencies=sorted(SUPPORTED_CURRENCIES),
    )
    planned = await planner.plan_workflow(text, context)
    logger.info(
        "agent_plan",
        extra={"context": {"provider": planned.provider, "provider_label": planned.provider_label}},
    )
    if planned.failure is not None:
        status = "needs_clarification" if planned.failure.code in _CLARIFICATION else "rejected"
        return await _persist(
            session,
            principal,
            instruction=text,
            provider=planned.provider,
            provider_label=planned.provider_label,
            status=status,
            error_code=planned.failure.code,
            explanation=_join(planned.provider_label, planned.failure.message, planned.failure.clarifications),
            clarifications=planned.failure.clarifications,
            draft=None,
            trusted={},
        )
    draft = planned.draft
    if draft is None:
        return await _persist(
            session,
            principal,
            instruction=text,
            provider=planned.provider,
            provider_label=planned.provider_label,
            status="rejected",
            error_code="invalid_plan",
            explanation=_join(planned.provider_label, "The planner did not return a plan."),
            clarifications=["The planner did not return a plan."],
            draft=None,
            trusted={},
        )
    validation = validate_plan(draft, text)
    if not validation.ok:
        status = "needs_clarification" if validation.code in _CLARIFICATION else "rejected"
        return await _persist(
            session,
            principal,
            instruction=text,
            provider=planned.provider,
            provider_label=planned.provider_label,
            status=status,
            error_code=validation.code,
            explanation=_join(planned.provider_label, validation.message or "", validation.clarifications),
            clarifications=validation.clarifications,
            draft=draft if status == "needs_clarification" else None,
            trusted={},
        )
    resolution = await resolve_plan(session, principal, draft)
    if resolution.clarifications:
        code = (
            "ambiguous"
            if any("more than one" in item for item in resolution.clarifications)
            else "missing_required"
        )
        return await _persist(
            session,
            principal,
            instruction=text,
            provider=planned.provider,
            provider_label=planned.provider_label,
            status="needs_clarification",
            error_code=code,
            explanation=_join(planned.provider_label, *resolution.clarifications),
            clarifications=resolution.clarifications,
            draft=draft,
            trusted=resolution.trusted,
        )
    saved = await _persist(
        session,
        principal,
        instruction=text,
        provider=planned.provider,
        provider_label=planned.provider_label,
        status="pending_confirmation",
        error_code=None,
        explanation=_preview(planned.provider_label, draft),
        clarifications=[],
        draft=draft,
        trusted=resolution.trusted,
    )
    actions = await _actions(session, saved.id, principal)
    if actions and all(bool(action.payload.get("read_only")) for action in actions):
        run = await _owned(session, principal, saved.id)
        return await _execute(session, principal, run, retry=False)
    return saved


async def revise_plan(
    session: AsyncSession, principal: Principal, run_id: uuid.UUID, body: PlanRevisionRequest
) -> AgentRunOut:
    run = await _owned(session, principal, run_id, lock=True)
    if run.status != "pending_confirmation" or not run.plan:
        raise ConflictError("Only an unconfirmed plan can be edited. Create a new plan for another workflow.")
    draft = WorkflowPlanDraft.model_validate(run.plan)
    if set(body.arguments) - {step.sequence for step in draft.steps}:
        raise ValidationFailedError("The revision contains an unknown step.")
    for step in draft.steps:
        if step.sequence in body.arguments:
            if set(body.arguments[step.sequence]) != set(step.arguments):
                raise ValidationFailedError("Edit the existing fields without adding or removing arguments.")
            if step.arguments != body.arguments[step.sequence]:
                fields = body.arguments[step.sequence]
                label = f"User-reviewed {step.action_type.value.replace('_', ' ')}"
                step.summary = (
                    f"{label}: {fields.get('currency_code', '')} {fields['amount']}"[:500]
                    if "amount" in fields else label
                )
            step.arguments = body.arguments[step.sequence]
    instruction = body.instruction.strip()
    validation = validate_plan(draft, instruction)
    if not validation.ok:
        raise ValidationFailedError(validation.message or "The edited plan is invalid.")
    resolution = await resolve_plan(session, principal, draft)
    if resolution.clarifications:
        raise ValidationFailedError(" ".join(resolution.clarifications))
    # Persist a new inert preview. The previous preview cannot subsequently be
    # confirmed with old amounts or stale resolved identities.
    run.status = "cancelled"
    for action in await _actions(session, run.id, principal):
        action.status = "cancelled"
        await _mark_workflow_step(session, principal, run.id, action)
    workflow = await _workflow(session, principal, run.id)
    if workflow is not None:
        workflow.status = "cancelled"
    record(
        session, action="agent.plan_revised", entity_type="agent_run", entity_id=run.id,
        workspace_id=principal.workspace_id, actor_user_id=principal.user_id,
    )
    return await _persist(
        session, principal, instruction=instruction, provider="user_review",
        provider_label="User-reviewed plan", status="pending_confirmation", error_code=None,
        explanation=_preview("User-reviewed plan", draft), clarifications=[], draft=draft,
        trusted=resolution.trusted,
    )


async def confirm_plan(session: AsyncSession, principal: Principal, run_id: uuid.UUID) -> AgentRunOut:
    run = await _owned(session, principal, run_id, lock=True)
    if run.status != "pending_confirmation":
        raise ConflictError("Confirm a plan from its preview. This run is not waiting for confirmation.")
    run.status = "executing"
    workflow = await _workflow(session, principal, run.id)
    if workflow is not None:
        workflow.confirmed_by_user_id = principal.user_id
        workflow.confirmed_at = datetime.now(UTC)
        await session.commit()
    return await _execute(session, principal, run, retry=False)


async def cancel_plan(session: AsyncSession, principal: Principal, run_id: uuid.UUID) -> AgentRunOut:
    run = await _owned(session, principal, run_id)
    if run.status not in _CANCEL_STATUSES:
        raise ConflictError("This plan can no longer be cancelled.")
    actions = await _actions(session, run.id, principal)
    run.status = "cancelled"
    run.error_code = None
    for action in actions:
        if action.status != "succeeded":
            action.status = "cancelled"
            action.error = "Cancelled before this step finished."
        await _mark_workflow_step(session, principal, run.id, action)
        await _cancel_step_schedules(session, principal, action)
    workflow = await _workflow(session, principal, run.id)
    if workflow is not None:
        workflow.status = "cancelled"
    await session.commit()
    return await _out(session, run, principal)


async def resume_run(session: AsyncSession, principal: Principal, run_id: uuid.UUID) -> AgentRunOut:
    run = await _owned(session, principal, run_id)
    if run.status in {"completed", "cancelled", "pending_confirmation", "needs_clarification"}:
        return await _out(session, run, principal)
    if run.status not in _RETRY_STATUSES:
        return await _out(session, run, principal)
    return await _execute(session, principal, run, retry=True)


async def retry_plan(session: AsyncSession, principal: Principal, run_id: uuid.UUID) -> AgentRunOut:
    run = await _owned(session, principal, run_id)
    if run.status not in _RETRY_STATUSES:
        raise ConflictError("This plan has no failed step to retry.")
    return await _execute(session, principal, run, retry=True)


async def get_plan(session: AsyncSession, principal: Principal, run_id: uuid.UUID) -> AgentRunOut:
    run = await _owned(session, principal, run_id)
    return await _out(session, run, principal)


async def list_plans(session: AsyncSession, principal: Principal) -> list[AgentRunOut]:
    rows = list(
        await session.scalars(
            select(AgentRun)
            .where(AgentRun.workspace_id == principal.workspace_id)
            .order_by(AgentRun.created_at.desc())
            .limit(20)
        )
    )
    return [await _out(session, run, principal) for run in rows]


async def _execute(session: AsyncSession, principal: Principal, run: AgentRun, *, retry: bool) -> AgentRunOut:
    actions = await _actions(session, run.id, principal)
    if retry and not any(
        action.status in {"failed", "blocked", "running", "pending", "skipped", "waiting"} for action in actions
    ):
        raise ConflictError("There is no failed step to retry.")
    run.status = "executing"
    workflow = await _workflow(session, principal, run.id)
    if workflow is not None:
        workflow.status = "executing"
    await session.commit()
    outputs: dict[int, dict] = {}
    for action in actions:
        if action.status == "succeeded":
            outputs[action.sequence] = {**(action.result or {}), "status": "succeeded"}
            continue
        if action.status == "cancelled":
            outputs[action.sequence] = {"status": "cancelled"}
            continue
        if not retry and action.status not in {"pending", "running"}:
            outputs[action.sequence] = {**(action.result or {}), "status": action.status}
            continue
        payload = action.payload or {}
        depends = [int(item) for item in payload.get("depends_on") or []]
        if any(outputs.get(dependency, {}).get("status") == "waiting" for dependency in depends):
            waited = _waiting_result(outputs, depends)
            action.status = "waiting"
            action.result = waited
            action.error = "Waiting for a verified client payment."
            outputs[action.sequence] = waited
            await _mark_workflow_step(session, principal, run.id, action)
            await session.commit()
            continue
        action.attempts += 1
        action.status = "running"
        await session.commit()
        payload = action.payload or {}
        outcome = await execute_tool(
            session,
            principal,
            run_id=run.id,
            sequence=action.sequence,
            action_type=action.action_type,
            arguments=action.arguments or {},
            trusted=payload.get("trusted") or {},
            preconditions=list(payload.get("preconditions") or []),
            outputs=outputs,
            depends_on=list(payload.get("depends_on") or []),
        )
        result = dict(outcome.result or {})
        action.status = outcome.status
        action.result = result
        action.error = outcome.error
        action.provider_reference = outcome.provider_reference
        if outcome.status == "waiting" and isinstance(result.get("invoice_id"), str):
            trusted = dict(payload.get("trusted") or {})
            trusted["invoice_id"] = result["invoice_id"]
            action.payload = {**payload, "trusted": trusted}
        outputs[action.sequence] = {**result, "status": outcome.status}
        await _mark_workflow_step(session, principal, run.id, action)
        record(
            session,
            action="agent.step_finished",
            entity_type="agent_action",
            entity_id=action.id,
            workspace_id=principal.workspace_id,
            actor_user_id=principal.user_id,
            details={
                "action_type": action.action_type,
                "status": outcome.status,
                "provider_reference": outcome.provider_reference,
            },
        )
        await session.commit()
    statuses = [action.status for action in actions]
    if any(status == "failed" for status in statuses):
        run.status = "failed"
        run.error_code = "step_failed"
    elif any(status == "waiting" for status in statuses):
        run.status = "waiting"
        run.error_code = None
    elif any(status == "blocked" for status in statuses):
        run.status = "blocked"
        run.error_code = "precondition_unmet"
    else:
        run.status = "completed"
        run.error_code = None
    if workflow is not None:
        workflow.status = run.status
    run.explanation = _execution_explanation(run.provider_label or FALLBACK_LABEL, actions)
    await session.commit()
    return await _out(session, run, principal)


async def _persist(
    session: AsyncSession,
    principal: Principal,
    *,
    instruction: str,
    provider: str,
    provider_label: str,
    status: str,
    error_code: str | None,
    explanation: str,
    clarifications: list[str],
    draft: WorkflowPlanDraft | None,
    trusted: dict[int, dict[str, str]],
) -> AgentRunOut:
    run = AgentRun(
        workspace_id=principal.workspace_id,
        user_id=principal.user_id,
        provider=provider,
        provider_label=provider_label,
        instruction=instruction,
        status=status,
        error_code=error_code,
        plan=draft.model_dump(mode="json") if draft else None,
        validation={"clarifications": clarifications, "accepted": status == "pending_confirmation"},
        explanation=explanation,
    )
    session.add(run)
    await session.flush()
    workflow = Workflow(
        workspace_id=principal.workspace_id,
        agent_run_id=run.id,
        status="pending_confirmation" if status == "pending_confirmation" else status,
    )
    session.add(workflow)
    await session.flush()
    if draft is not None:
        for step in draft.steps:
            payload = {
                "summary": step.summary,
                "arguments": step.arguments,
                "trusted": trusted.get(step.sequence, {}),
                "depends_on": step.depends_on,
                "preconditions": step.preconditions,
                "requires_approval": step.requires_approval,
                "read_only": step.read_only,
            }
            session.add(
                AgentAction(
                    workspace_id=principal.workspace_id,
                    agent_run_id=run.id,
                    sequence=step.sequence,
                    action_type=step.action_type.value,
                    payload=payload,
                    arguments=step.arguments,
                    status="pending" if status == "pending_confirmation" else status,
                )
            )
            session.add(
                WorkflowStep(
                    workspace_id=principal.workspace_id,
                    workflow_id=workflow.id,
                    sequence=step.sequence,
                    step_type=step.action_type.value,
                    status="pending" if status == "pending_confirmation" else status,
                    payload=payload,
                    depends_on=list(step.depends_on),
                    condition="; ".join(step.preconditions)[:128] or None,
                )
            )
    record(
        session,
        action="agent.plan_recorded",
        entity_type="agent_run",
        entity_id=run.id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        details={"provider": provider, "status": status, "provider_label": provider_label},
    )
    await session.commit()
    return await _out(session, run, principal)


async def _owned(
    session: AsyncSession, principal: Principal, run_id: uuid.UUID, *, lock: bool = False
) -> AgentRun:
    query = select(AgentRun).where(AgentRun.id == run_id, AgentRun.workspace_id == principal.workspace_id)
    if lock:
        query = query.with_for_update()
    run = await session.scalar(query)
    if run is None:
        raise NotFoundError("Agent run not found.")
    return run


async def _actions(session: AsyncSession, run_id: uuid.UUID, principal: Principal) -> list[AgentAction]:
    rows = await session.scalars(
        select(AgentAction)
        .where(AgentAction.agent_run_id == run_id, AgentAction.workspace_id == principal.workspace_id)
        .order_by(AgentAction.sequence.asc())
    )
    return list(rows)


async def _workflow(session: AsyncSession, principal: Principal, run_id: uuid.UUID) -> Workflow | None:
    return await session.scalar(
        select(Workflow).where(Workflow.agent_run_id == run_id, Workflow.workspace_id == principal.workspace_id)
    )


async def _mark_workflow_step(
    session: AsyncSession, principal: Principal, run_id: uuid.UUID, action: AgentAction
) -> None:
    workflow = await _workflow(session, principal, run_id)
    if workflow is None:
        return
    step = await session.scalar(
        select(WorkflowStep).where(
            WorkflowStep.workflow_id == workflow.id,
            WorkflowStep.sequence == action.sequence,
            WorkflowStep.workspace_id == principal.workspace_id,
        )
    )
    if step is None:
        return
    step.status = action.status
    step.error = action.error
    step.attempts = action.attempts
    step.provider_reference = action.provider_reference
    result = action.result if isinstance(action.result, dict) else {}
    if isinstance(result.get("waiting_for"), str):
        step.waiting_for = result["waiting_for"]
    run_after = result.get("run_after")
    if isinstance(run_after, str):
        parsed = datetime.fromisoformat(run_after)
        step.run_after = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    payload = action.payload if isinstance(action.payload, dict) else {}
    depends = payload.get("depends_on")
    if isinstance(depends, list):
        step.depends_on = depends


async def _out(session: AsyncSession, run: AgentRun, principal: Principal) -> AgentRunOut:
    actions = await _actions(session, run.id, principal)
    validation = run.validation or {}
    raw_clarifications = validation.get("clarifications")
    clarifications = raw_clarifications if isinstance(raw_clarifications, list) else []
    return AgentRunOut(
        id=run.id,
        instruction=run.instruction,
        status=run.status,
        provider=run.provider,
        provider_label=run.provider_label or FALLBACK_LABEL,
        explanation=run.explanation,
        error_code=run.error_code,
        clarifications=[item for item in clarifications if isinstance(item, str)],
        steps=[_step_out(action) for action in actions],
    )


def _step_out(action: AgentAction) -> AgentStepOut:
    payload = action.payload or {}
    summary = payload.get("summary")
    return AgentStepOut(
        sequence=action.sequence,
        action_type=action.action_type,
        status=action.status,
        summary=summary if isinstance(summary, str) else action.action_type,
        arguments=action.arguments or {},
        result=action.result,
        provider_reference=action.provider_reference,
        error=action.error,
        attempts=action.attempts,
        requires_approval=bool(payload.get("requires_approval")),
        preconditions=[item for item in payload.get("preconditions") or [] if isinstance(item, str)],
        depends_on=[item for item in payload.get("depends_on") or [] if isinstance(item, int)],
    )


def _waiting_result(outputs: dict[int, dict], depends: list[int]) -> dict:
    invoice_id = None
    for dependency in depends:
        candidate = outputs.get(dependency, {}).get("invoice_id")
        if isinstance(candidate, str):
            invoice_id = candidate
    return {"invoice_id": invoice_id, "waiting_for": "invoice.paid", "status": "waiting"}


async def _cancel_step_schedules(session: AsyncSession, principal: Principal, action: AgentAction) -> None:
    from app.modules.autopilot.models import ScheduledAction

    result = action.result if isinstance(action.result, dict) else {}
    scheduled_id = result.get("scheduled_action_id")
    invoice_id = result.get("invoice_id")
    rows = list(
        await session.scalars(
            select(ScheduledAction).where(
                ScheduledAction.workspace_id == principal.workspace_id,
                ScheduledAction.status.in_(("pending", "running", "failed")),
            )
        )
    )
    for row in rows:
        matches_schedule = scheduled_id is not None and str(row.id) == scheduled_id
        matches_invoice = invoice_id is not None and str(row.related_entity_id) == invoice_id
        if matches_schedule or matches_invoice:
            row.status = "cancelled"


def _preview(label: str, draft: WorkflowPlanDraft) -> str:
    lines = [label, "Review this plan. Financial steps wait for confirmation."]
    for step in draft.steps:
        approval = " Approval is required." if step.requires_approval else ""
        lines.append(f"{step.sequence}. {step.summary}{approval}")
    if any(step.action_type.value == "prepare_payout" for step in draft.steps):
        lines.append("Payout execution is not part of this agent. An owner reviews the approval separately.")
    return "\n".join(lines)


def _execution_explanation(label: str, actions: list[AgentAction]) -> str:
    lines = [label]
    for action in actions:
        summary = (action.payload or {}).get("summary") or action.action_type
        lines.append(f"{action.sequence}. {summary} — {action.status}.")
        if action.error:
            lines.append(action.error)
    if any(action.action_type == "prepare_payout" for action in actions):
        lines.append("Payout execution is not part of this agent. An owner reviews the approval separately.")
    return "\n".join(lines)


def _join(label: str, *parts: str | list[str]) -> str:
    lines = [label]
    for part in parts:
        if isinstance(part, str):
            if part and part not in lines:
                lines.append(part)
        else:
            lines.extend(item for item in part if item and item not in lines)
    return "\n".join(lines)
