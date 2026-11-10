"""Strict plan shapes. Provider output is data, never a credential or a tool call."""

from __future__ import annotations

import uuid
from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ActionType(StrEnum):
    LOOKUP_CUSTOMER = "lookup_customer"
    CREATE_PROJECT = "create_project"
    CREATE_MILESTONE = "create_milestone"
    DRAFT_INVOICE = "draft_invoice"
    SEND_INVOICE = "send_invoice"
    LOOKUP_INVOICE_STATUS = "lookup_invoice_status"
    SCHEDULE_REMINDER = "schedule_reminder"
    PREPARE_PAYOUT = "prepare_payout"
    CREATE_APPROVAL = "create_approval"
    FINANCIAL_SUMMARY = "financial_summary"
    ANALYZE_CONTRACT = "analyze_contract"
    CREATE_MILESTONES = "create_milestones"
    GET_PROJECT_STATUS = "get_project_status"
    PREPARE_MILESTONE_INVOICE = "prepare_milestone_invoice"
    EXPLAIN_POLICY = "explain_policy"
    RESUME_PAYOUT = "resume_payout"


READ_ONLY_ACTIONS = frozenset(
    {
        ActionType.LOOKUP_CUSTOMER,
        ActionType.LOOKUP_INVOICE_STATUS,
        ActionType.FINANCIAL_SUMMARY,
        ActionType.ANALYZE_CONTRACT,
        ActionType.GET_PROJECT_STATUS,
        ActionType.EXPLAIN_POLICY,
        ActionType.RESUME_PAYOUT,
    }
)
APPROVAL_ACTIONS = frozenset({ActionType.PREPARE_PAYOUT, ActionType.CREATE_APPROVAL})
MONEY_ACTIONS = frozenset(
    {
        ActionType.CREATE_PROJECT,
        ActionType.CREATE_MILESTONE,
        ActionType.DRAFT_INVOICE,
        ActionType.PREPARE_PAYOUT,
        ActionType.EXPLAIN_POLICY,
    }
)

ALLOWED_ARGUMENT_KEYS = frozenset(
    {
        "customer_name",
        "recipient_name",
        "amount",
        "currency_code",
        "description",
        "days",
        "min_days_overdue",
        "project_name",
        "milestone_name",
        "contract_name",
        "trigger_kind",
        "note",
        "name_is_default",
        "milestones",
        "milestone_count",
        "due_on",
    }
)


class EntityMention(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(pattern="^(customer|contractor|project|contract)$")
    name: str = Field(min_length=1, max_length=200)


class MilestonePlanDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    amount: str
    currency_code: str
    trigger_kind: str | None = Field(default=None, pattern="^(upfront|on_event|on_delivery)$")
    due_on: date | None = None


class PlanStepDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1, le=50)
    action_type: ActionType
    summary: str = Field(min_length=1, max_length=500)
    arguments: dict[str, Any]
    depends_on: list[int] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    read_only: bool = False


class WorkflowPlanDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: str = Field(min_length=1, max_length=64)
    entities: list[EntityMention]
    steps: list[PlanStepDraft] = Field(min_length=1, max_length=50)


class PlanningFailure(BaseModel):
    code: str
    message: str
    clarifications: list[str] = Field(default_factory=list)


class WorkflowPlanningContext(BaseModel):
    workspace_name: str
    customer_names: list[str]
    contractor_names: list[str]
    supported_currencies: list[str]


class WorkflowPlanResult(BaseModel):
    provider: str
    provider_label: str
    draft: WorkflowPlanDraft | None = None
    failure: PlanningFailure | None = None


class PlanRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=4000)


class PlanRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruction: str = Field(min_length=1, max_length=4000)
    arguments: dict[int, dict[str, Any]] = Field(max_length=50)


class AgentStepOut(BaseModel):
    sequence: int
    action_type: str
    status: str
    summary: str
    arguments: dict[str, Any]
    result: dict[str, Any] | None
    provider_reference: str | None
    error: str | None
    attempts: int
    requires_approval: bool
    preconditions: list[str]
    depends_on: list[int]


class AgentRunOut(BaseModel):
    id: uuid.UUID
    instruction: str
    status: str
    provider: str
    provider_label: str
    explanation: str | None
    error_code: str | None
    clarifications: list[str]
    steps: list[AgentStepOut]


class ItemList[T](BaseModel):
    items: list[T]
