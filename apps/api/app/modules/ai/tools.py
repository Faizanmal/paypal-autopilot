"""Typed tools. Workspace and user identity come from the principal, never from plan text."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, ValidationFailedError
from app.core.money import money_to_api, parse_money
from app.integrations.paypal.client import get_paypal_client
from app.modules.ai.schemas import READ_ONLY_ACTIONS, ActionType, MilestonePlanDraft
from app.modules.ai.security import display_provider_error
from app.modules.autopilot.models import Invoice, ScheduledAction
from app.modules.autopilot.reminders import INVOICE_REMINDER_JOB
from app.modules.autopilot.schemas import InvoiceCreate
from app.modules.autopilot.service import create_invoice, list_invoices, send_invoice
from app.modules.identity.deps import Principal
from app.modules.spendpilot.approvals import assert_approver_authorized, assert_consumable
from app.modules.spendpilot.models import Approval, PayoutRequest
from app.modules.spendpilot.policy import committed_spend, ensure_workflow_enabled, evaluate, get_policy
from app.modules.spendpilot.schemas import PayoutIntentCreate
from app.modules.spendpilot.service import create_payout_intent, list_payout_requests
from app.modules.trustflow.billing import prepare_milestone_invoice
from app.modules.trustflow.contracts import apply_contract, get_contract
from app.modules.trustflow.extract import NOT_LEGALLY_VERIFIED, ContractExtractionDraft
from app.modules.trustflow.models import Contractor, Customer, Milestone, Project
from app.modules.trustflow.schemas import ContractApply, MilestoneCreate, ProjectCreate
from app.modules.trustflow.service import create_milestone, create_project, get_project_detail, list_projects

_CLOSED = ("paid", "marked_as_paid", "cancelled", "refunded", "partially_refunded", "marked_as_refunded")


@dataclass
class ToolOutcome:
    status: str
    result: dict | None = None
    error: str | None = None
    provider_reference: str | None = None


def step_key(run_id: uuid.UUID, sequence: int) -> str:
    return f"agent:{run_id}:{sequence}"


async def execute_tool(
    session: AsyncSession,
    principal: Principal,
    *,
    run_id: uuid.UUID,
    sequence: int,
    action_type: str,
    arguments: dict,
    trusted: dict,
    preconditions: list[str],
    outputs: dict[int, dict],
    depends_on: list[int],
) -> ToolOutcome:
    inherited = dict(trusted)
    for dependency in depends_on:
        previous = outputs.get(dependency)
        if previous is None or previous.get("status") != "succeeded":
            return ToolOutcome(status="skipped", error="A required earlier step did not succeed.")
        for key, value in previous.items():
            if key.endswith("_id") and isinstance(value, str):
                inherited.setdefault(key, value)
    if "client payment cleared" in preconditions:
        for dependency in depends_on:
            previous = outputs.get(dependency) or {}
            if isinstance(previous.get("invoice_id"), str):
                inherited["invoice_id"] = previous["invoice_id"]
    try:
        kind = ActionType(action_type)
    except ValueError:
        return ToolOutcome(status="failed", error="This step uses an unsupported action.")
    try:
        if kind not in READ_ONLY_ACTIONS:
            policy_action = {
                ActionType.CREATE_PROJECT: "project",
                ActionType.CREATE_MILESTONE: "milestone",
                ActionType.CREATE_MILESTONES: "milestone",
                ActionType.DRAFT_INVOICE: "invoice",
                ActionType.PREPARE_MILESTONE_INVOICE: "invoice",
                ActionType.SCHEDULE_REMINDER: "send_invoice",
                ActionType.PREPARE_PAYOUT: "payout",
                ActionType.CREATE_APPROVAL: "payout",
            }.get(kind, str(kind))
            await ensure_workflow_enabled(session, principal, policy_action)
        if kind is ActionType.CREATE_PROJECT:
            return await _project(session, principal, run_id, sequence, arguments, inherited)
        if kind is ActionType.CREATE_MILESTONE:
            return await _milestone(session, principal, arguments, inherited)
        if kind is ActionType.DRAFT_INVOICE:
            return await _draft_invoice(session, principal, run_id, sequence, arguments, inherited)
        if kind is ActionType.SEND_INVOICE:
            return await _send(session, principal, inherited)
        if kind is ActionType.SCHEDULE_REMINDER:
            return await _schedule(session, principal, run_id, sequence, arguments, inherited)
        if kind is ActionType.PREPARE_PAYOUT:
            return await _payout(session, principal, run_id, sequence, arguments, inherited, preconditions)
        if kind is ActionType.CREATE_APPROVAL:
            return await _approval(session, principal, inherited)
        if kind is ActionType.LOOKUP_CUSTOMER:
            return await _lookup_customer(session, principal, arguments)
        if kind is ActionType.LOOKUP_INVOICE_STATUS:
            return await _overdue(session, principal, arguments)
        if kind is ActionType.FINANCIAL_SUMMARY:
            return await _summary(session, principal)
        if kind is ActionType.ANALYZE_CONTRACT:
            return await _analyze_contract(session, principal, inherited)
        if kind is ActionType.CREATE_MILESTONES:
            return await _create_milestones(session, principal, arguments, inherited)
        if kind is ActionType.GET_PROJECT_STATUS:
            return await _project_status(session, principal, inherited)
        if kind is ActionType.PREPARE_MILESTONE_INVOICE:
            return await _milestone_invoice(session, principal, inherited)
        if kind is ActionType.EXPLAIN_POLICY:
            return await _explain_policy(session, principal, arguments, inherited)
        if kind is ActionType.RESUME_PAYOUT:
            return await _resume_payout(session, principal, inherited)
    except AppError as exc:
        return ToolOutcome(status="failed", error=display_provider_error(exc.message))
    return ToolOutcome(status="failed", error="This step uses an unsupported action.")


async def _project(session, principal, run_id, sequence, arguments, trusted) -> ToolOutcome:
    marker = f"agent-step:{run_id}:{sequence}"
    existing = await session.scalar(
        select(Project).where(Project.workspace_id == principal.workspace_id, Project.description.contains(marker))
    )
    if existing is not None:
        return ToolOutcome(status="succeeded", result=_project_result(existing))
    amount, currency = parse_money(str(arguments["amount"]), str(arguments["currency_code"]))
    customer_id = _uuid(trusted.get("customer_id"))
    description = f"{arguments.get('description') or 'Created from a confirmed agent plan.'}\n{marker}"
    project = await create_project(
        session,
        principal,
        ProjectCreate(
            name=str(arguments["project_name"]),
            description=description,
            currency_code=currency,
            total_amount=amount,
            customer_id=customer_id,
        ),
    )
    return ToolOutcome(status="succeeded", result=_project_result(project))


def _project_result(project: Project) -> dict:
    return {
        "project_id": str(project.id),
        "name": project.name,
        "currency_code": project.currency_code,
        "amount": money_to_api(project.total_amount),
        "status": project.status,
    }


async def _milestone(session, principal, arguments, trusted) -> ToolOutcome:
    project_id = _uuid(trusted.get("project_id"))
    if project_id is None:
        return ToolOutcome(status="failed", error="The milestone has no project from an earlier step.")
    name = str(arguments["milestone_name"]).strip()
    existing = await session.scalar(
        select(Milestone).where(
            Milestone.workspace_id == principal.workspace_id,
            Milestone.project_id == project_id,
            Milestone.name == name,
        )
    )
    if existing is not None:
        if (
            existing.amount != Decimal(str(arguments["amount"]))
            or existing.currency_code != str(arguments["currency_code"]).upper()
            or existing.trigger_kind != str(arguments.get("trigger_kind") or "on_event")
            or (existing.due_on.isoformat() if existing.due_on else None) != arguments.get("due_on")
        ):
            return ToolOutcome(status="failed", error="An existing milestone has different terms; review a new plan.")
        return ToolOutcome(status="succeeded", result=_milestone_result(existing))
    amount, currency = parse_money(str(arguments["amount"]), str(arguments["currency_code"]))
    milestone = await create_milestone(
        session,
        principal,
        project_id,
        MilestoneCreate(
            name=name,
            amount=amount,
            currency_code=currency,
            trigger_kind=str(arguments.get("trigger_kind") or "on_event"),
            due_on=arguments.get("due_on"),
        ),
    )
    return ToolOutcome(status="succeeded", result=_milestone_result(milestone))


def _milestone_result(milestone: Milestone) -> dict:
    return {
        "milestone_id": str(milestone.id),
        "project_id": str(milestone.project_id),
        "name": milestone.name,
        "amount": money_to_api(milestone.amount),
        "currency_code": milestone.currency_code,
        "trigger_kind": milestone.trigger_kind,
    }


async def _draft_invoice(session, principal, run_id, sequence, arguments, trusted) -> ToolOutcome:
    customer_id = _uuid(trusted.get("customer_id"))
    if customer_id is None:
        return ToolOutcome(status="failed", error="The invoice has no customer in this workspace.")
    amount, currency = parse_money(str(arguments["amount"]), str(arguments["currency_code"]))
    invoice = await create_invoice(
        session,
        principal,
        InvoiceCreate(
            customer_id=customer_id,
            project_id=_uuid(trusted.get("project_id")),
            currency_code=currency,
            amount=amount,
            description=str(arguments.get("description") or "Services")[:200],
            idempotency_key=step_key(run_id, sequence),
        ),
        get_paypal_client(),
        get_settings(),
    )
    if not invoice.paypal_invoice_id:
        return ToolOutcome(
            status="failed",
            result={"invoice_id": str(invoice.id), "paypal_invoice_id": None},
            error=invoice.last_provider_error or "PayPal did not return an invoice id.",
        )
    return ToolOutcome(
        status="succeeded",
        provider_reference=invoice.paypal_invoice_id,
        result={
            "invoice_id": str(invoice.id),
            "paypal_invoice_id": invoice.paypal_invoice_id,
            "status": invoice.status,
            "amount": money_to_api(invoice.amount),
            "currency_code": invoice.currency_code,
        },
    )


async def _send(session, principal, trusted) -> ToolOutcome:
    invoice_id = _uuid(trusted.get("invoice_id"))
    if invoice_id is None:
        return ToolOutcome(status="failed", error="There is no drafted invoice to send.")
    invoice = await send_invoice(session, principal, invoice_id, get_paypal_client(), get_settings())
    return ToolOutcome(
        status="succeeded",
        provider_reference=invoice.paypal_invoice_id,
        result={
            "invoice_id": str(invoice.id),
            "status": invoice.status,
            "paypal_invoice_id": invoice.paypal_invoice_id,
        },
    )


async def _schedule(session, principal, run_id, sequence, arguments, trusted) -> ToolOutcome:
    invoice_id = _uuid(trusted.get("invoice_id"))
    if invoice_id is None:
        return ToolOutcome(status="blocked", error="There is no invoice to remind.")
    key = step_key(run_id, sequence)
    existing = await session.scalar(
        select(ScheduledAction).where(
            ScheduledAction.workspace_id == principal.workspace_id,
            ScheduledAction.job_type == INVOICE_REMINDER_JOB,
            ScheduledAction.payload.contains({"idempotency_key": key}),
        )
    )
    if existing is None:
        days = int(arguments["days"])
        existing = ScheduledAction(
            workspace_id=principal.workspace_id,
            job_type=INVOICE_REMINDER_JOB,
            run_after=datetime.now(UTC) + timedelta(days=days),
            status="pending",
            payload={
                "idempotency_key": key,
                "actor_user_id": str(principal.user_id),
                "invoice_id": str(invoice_id),
            },
            related_entity_type="invoice",
            related_entity_id=invoice_id,
            idempotency_key=key,
        )
        session.add(existing)
        await session.commit()
    return ToolOutcome(
        status="succeeded",
        result={
            "scheduled_action_id": str(existing.id),
            "invoice_id": str(invoice_id),
            "run_after": existing.run_after.isoformat(),
            "status": existing.status,
            "sent": False,
        },
    )


async def _payout(session, principal, run_id, sequence, arguments, trusted, preconditions) -> ToolOutcome:
    if "client payment cleared" in preconditions and not trusted.get("invoice_id"):
        return ToolOutcome(
            status="blocked",
            error="No cleared client payment is on record. The payout was not created.",
        )
    contractor_id = _uuid(trusted.get("contractor_id"))
    if contractor_id is None:
        return ToolOutcome(status="failed", error="The payout has no recipient in this workspace.")
    invoice_id = _uuid(trusted.get("invoice_id"))
    if invoice_id is not None:
        invoice = await session.scalar(
            select(Invoice).where(Invoice.id == invoice_id, Invoice.workspace_id == principal.workspace_id)
        )
        if invoice is None or invoice.status not in {"paid", "marked_as_paid"}:
            if invoice is not None and "client payment cleared" in preconditions:
                return ToolOutcome(
                    status="waiting",
                    result={"invoice_id": str(invoice.id), "waiting_for": "invoice.paid", "status": "waiting"},
                    error="Waiting for a verified client payment.",
                )
            return ToolOutcome(
                status="blocked",
                error="The client payment has not cleared. The payout was not created.",
            )
    amount, currency = parse_money(str(arguments["amount"]), str(arguments["currency_code"]))
    payout = await create_payout_intent(
        session,
        principal,
        PayoutIntentCreate(
            contractor_id=contractor_id,
            currency_code=currency,
            amount=amount,
            note=str(arguments.get("note") or "Prepared by the finance agent."),
            trigger_invoice_id=invoice_id,
            idempotency_key=step_key(run_id, sequence),
        ),
        proposed_by_ai=True,
    )
    return ToolOutcome(
        status="succeeded",
        provider_reference=payout.paypal_payout_batch_id,
        result={
            "payout_request_id": str(payout.id),
            "invoice_id": str(invoice_id) if invoice_id else None,
            "status": payout.status,
            "amount": money_to_api(payout.amount),
            "currency_code": payout.currency_code,
            "recipient_email": payout.recipient_email,
            "paypal_payout_batch_id": payout.paypal_payout_batch_id,
            "execution": "not_attempted",
        },
    )


async def _approval(session, principal, trusted) -> ToolOutcome:
    payout_id = _uuid(trusted.get("payout_request_id"))
    if payout_id is None:
        return ToolOutcome(status="skipped", error="There is no payout intent to attach an approval to.")
    approval = await session.scalar(
        select(Approval).where(
            Approval.payout_request_id == payout_id,
            Approval.workspace_id == principal.workspace_id,
        )
    )
    if approval is None:
        return ToolOutcome(status="failed", error="The payout intent did not create an approval.")
    return ToolOutcome(
        status="succeeded",
        result={
            "approval_id": str(approval.id),
            "payout_request_id": str(payout_id),
            "status": approval.status,
            "execution": "not_attempted",
        },
    )


async def _lookup_customer(session, principal, arguments) -> ToolOutcome:
    name = str(arguments.get("customer_name") or "").strip()
    rows = list(await session.scalars(select(Customer).where(Customer.workspace_id == principal.workspace_id)))
    folded = name.casefold()
    exact = [row for row in rows if row.name.casefold() == folded]
    matches = exact or [row for row in rows if folded and folded in row.name.casefold()]
    return ToolOutcome(
        status="succeeded",
        result={
            "matches": [{"customer_id": str(row.id), "name": row.name, "email": row.email} for row in matches],
            "selected": len(matches) == 1,
        },
    )


async def _overdue(session, principal, arguments) -> ToolOutcome:
    days = int(arguments["min_days_overdue"])
    cutoff = datetime.now(UTC) - timedelta(days=days)
    rows = list(
        await session.scalars(
            select(Invoice)
            .where(
                Invoice.workspace_id == principal.workspace_id,
                Invoice.due_at.is_not(None),
                Invoice.due_at < cutoff,
                Invoice.status.notin_(_CLOSED),
            )
            .order_by(Invoice.due_at.asc())
        )
    )
    return ToolOutcome(
        status="succeeded",
        result={
            "count": len(rows),
            "min_days_overdue": days,
            "invoices": [
                {
                    "invoice_id": str(row.id),
                    "status": row.status,
                    "amount": money_to_api(row.amount),
                    "currency_code": row.currency_code,
                    "due_at": row.due_at.isoformat() if row.due_at else None,
                }
                for row in rows
            ],
        },
    )


async def _summary(session, principal) -> ToolOutcome:
    invoices = await list_invoices(session, principal)
    projects = await list_projects(session, principal)
    payouts = await list_payout_requests(session, principal)
    open_total = Decimal("0.00")
    for invoice in invoices:
        if invoice.currency_code == "USD" and invoice.status not in _CLOSED:
            open_total += Decimal(invoice.amount)
    return ToolOutcome(
        status="succeeded",
        result={
            "invoice_count": len(invoices),
            "open_invoice_total": money_to_api(open_total),
            "open_invoice_currency": "USD",
            "project_count": len(projects),
            "payouts_pending_approval": sum(1 for payout in payouts if payout.status == "pending_approval"),
        },
    )


def _uuid(value: object) -> uuid.UUID | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


async def _analyze_contract(session, principal, trusted) -> ToolOutcome:
    contract_id = _uuid(trusted.get("contract_id"))
    if contract_id is None:
        return ToolOutcome(status="failed", error="No contract in this workspace was selected.")
    contract, extraction = await get_contract(session, principal, contract_id)
    payload = dict(extraction.payload)
    payload["legally_verified"] = False
    return ToolOutcome(
        status="succeeded",
        result={
            "contract_id": str(contract.id),
            "filename": contract.filename,
            "provider_label": extraction.provider_label,
            "legally_verified": False,
            "disclaimer": NOT_LEGALLY_VERIFIED,
            "findings": list(extraction.findings or []),
            "parties": payload.get("parties") or [],
            "scope": payload.get("scope"),
            "total_amount": payload.get("total_amount"),
            "currency_code": payload.get("currency_code"),
            "milestones": payload.get("milestones") or [],
        },
    )


async def _create_milestones(session, principal, arguments, trusted) -> ToolOutcome:
    contract_id = _uuid(trusted.get("contract_id"))
    if arguments.get("contract_name") and arguments.get("milestones"):
        return ToolOutcome(status="failed", error="Choose contract-derived or direct milestones, not both.")
    if not arguments.get("contract_name"):
        project_id = _uuid(trusted.get("project_id"))
        rows = arguments.get("milestones")
        if project_id is None or not isinstance(rows, list) or not rows:
            return ToolOutcome(status="failed", error="Review explicit milestones linked to an earlier project step.")
        from pydantic import ValidationError

        try:
            items = [MilestonePlanDraft.model_validate(row) for row in rows]
        except ValidationError:
            return ToolOutcome(status="failed", error="The direct milestone proposal is invalid; review a new plan.")
        detail = await get_project_detail(session, principal, project_id)
        amounts = [parse_money(item.amount, item.currency_code) for item in items]
        names = [item.name.strip().casefold() for item in items]
        if (
            sum((amount for amount, _currency in amounts), Decimal(0)) != detail.total_amount
            or any(currency != detail.currency_code for _amount, currency in amounts)
            or len(names) != len(set(names))
            or any(not name for name in names)
        ):
            raise ValidationFailedError("Unique milestone amounts must sum to the project total in its currency.")
        results = []
        for item in items:
            outcome = await _milestone(
                session,
                principal,
                {
                    "milestone_name": item.name,
                    "amount": item.amount,
                    "currency_code": item.currency_code,
                    "trigger_kind": item.trigger_kind or "on_event",
                    **({"due_on": item.due_on.isoformat()} if item.due_on else {}),
                },
                {"project_id": str(project_id)},
            )
            if outcome.status != "succeeded":
                return outcome
            results.append(outcome.result)
        return ToolOutcome(
            status="succeeded",
            result={
                "project_id": str(project_id),
                "milestone_count": len(results),
                "milestones": results,
            },
        )
    customer_id = _uuid(trusted.get("customer_id"))
    if contract_id is None or customer_id is None:
        return ToolOutcome(status="failed", error="The contract is not ready to turn into milestones.")
    _contract, extraction = await get_contract(session, principal, contract_id)
    draft = ContractExtractionDraft.model_validate(extraction.payload)
    if draft.apply_blocked():
        return ToolOutcome(
            status="failed",
            error="The contract findings must be reviewed before milestones can be created.",
        )
    project = await apply_contract(session, principal, contract_id, ContractApply(customer_id=customer_id))
    detail = await get_project_detail(session, principal, project.id)
    return ToolOutcome(
        status="succeeded",
        result={
            "project_id": str(project.id),
            "milestone_count": detail.progress.milestone_count,
            "legally_verified": False,
        },
    )


async def _project_status(session, principal, trusted) -> ToolOutcome:
    project_id = _uuid(trusted.get("project_id"))
    if project_id is None:
        return ToolOutcome(status="failed", error="No project in this workspace was selected.")
    detail = await get_project_detail(session, principal, project_id)
    return ToolOutcome(status="succeeded", result=json.loads(detail.model_dump_json()))


async def _milestone_invoice(session, principal, trusted) -> ToolOutcome:
    milestone_id = _uuid(trusted.get("milestone_id"))
    if milestone_id is None:
        return ToolOutcome(status="failed", error="No accepted milestone was selected.")
    invoice = await prepare_milestone_invoice(session, principal, milestone_id, get_paypal_client(), get_settings())
    if not invoice.paypal_invoice_id:
        return ToolOutcome(
            status="failed",
            result={"invoice_id": str(invoice.id), "paypal_invoice_id": None, "milestone_id": str(milestone_id)},
            error=invoice.last_provider_error or "PayPal did not return an invoice id.",
        )
    return ToolOutcome(
        status="succeeded",
        provider_reference=invoice.paypal_invoice_id,
        result={
            "invoice_id": str(invoice.id),
            "paypal_invoice_id": invoice.paypal_invoice_id,
            "milestone_id": str(milestone_id),
            "amount": money_to_api(invoice.amount),
            "currency_code": invoice.currency_code,
            "status": invoice.status,
        },
    )


async def _explain_policy(session, principal, arguments, trusted) -> ToolOutcome:
    contractor_id = _uuid(trusted.get("contractor_id"))
    if contractor_id is None:
        return ToolOutcome(status="failed", error="The payout has no recipient in this workspace.")
    contractor = await session.scalar(
        select(Contractor).where(Contractor.id == contractor_id, Contractor.workspace_id == principal.workspace_id)
    )
    if contractor is None:
        return ToolOutcome(status="failed", error="The payout has no recipient in this workspace.")
    amount, currency = parse_money(str(arguments["amount"]), str(arguments["currency_code"]))
    recipient = (contractor.paypal_email or contractor.email).strip()
    policy = await get_policy(session, principal.workspace_id)
    spent_today, spent_month, spent_total = await committed_spend(session, principal.workspace_id, currency)
    decision = evaluate(
        policy,
        action_type="payout",
        amount=amount,
        currency=currency,
        recipient=recipient,
        mode="prepare",
        spent_today=spent_today,
        spent_month=spent_month,
        spent_total=spent_total,
    )
    return ToolOutcome(
        status="succeeded",
        result={
            "allowed": decision.allowed,
            "requires_approval": decision.requires_approval,
            "violations": list(decision.violations),
            "suggestion": decision.suggestion,
            "autonomy_level": decision.autonomy_level,
            "execution": "not_attempted",
            "policy_changed": False,
        },
    )


async def _resume_payout(session, principal, trusted) -> ToolOutcome:
    contractor_id = _uuid(trusted.get("contractor_id"))
    if contractor_id is None:
        return ToolOutcome(status="failed", error="The payout has no recipient in this workspace.")
    payout = await session.scalar(
        select(PayoutRequest)
        .where(PayoutRequest.workspace_id == principal.workspace_id, PayoutRequest.contractor_id == contractor_id)
        .order_by(PayoutRequest.created_at.desc())
    )
    if payout is None:
        return ToolOutcome(
            status="succeeded",
            result={
                "can_resume": False,
                "reason": "No payout is waiting for this recipient.",
                "execution": "not_attempted",
            },
        )
    approval = await session.scalar(
        select(Approval).where(
            Approval.payout_request_id == payout.id,
            Approval.workspace_id == principal.workspace_id,
        )
    )
    now = datetime.now(UTC)
    can_resume = False
    reason = "A fresh owner approval is required before this payout can continue."
    if (
        approval is not None
        and approval.status == "approved"
        and approval.consumed_at is None
        and approval.expires_at >= now
    ):
        try:
            assert_consumable(approval, payout, now=now)
            await assert_approver_authorized(session, approval)
        except AppError as exc:
            reason = exc.message
        else:
            can_resume = True
            reason = "The approval still matches this payout. Execution was not attempted."
    if can_resume:
        policy = await get_policy(session, principal.workspace_id)
        today, month, total = await committed_spend(session, principal.workspace_id, payout.currency_code)
        decision = evaluate(
            policy,
            action_type="payout",
            amount=payout.amount,
            currency=payout.currency_code,
            recipient=payout.recipient_email,
            mode="execute",
            spent_today=today,
            spent_month=month,
            spent_total=total,
            reserved_amount=payout.amount,
        )
        if not decision.allowed:
            can_resume = False
            reason = " ".join(decision.violations)
    return ToolOutcome(
        status="succeeded",
        result={
            "can_resume": can_resume,
            "reason": reason,
            "payout_request_id": str(payout.id),
            "approval_id": str(approval.id) if approval is not None else None,
            "approval_status": approval.status if approval is not None else None,
            "execution": "not_attempted",
            "paypal_payout_batch_id": payout.paypal_payout_batch_id,
        },
    )
