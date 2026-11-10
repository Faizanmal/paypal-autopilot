"""Read models for the workspace office screens."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ItemList[T](BaseModel):
    items: list[T]


class AuditEntryOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    actor_name: str | None
    actor_email: str | None
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    result: str
    provider_reference: str | None
    approval_id: str | None
    proposed_by_ai: bool
    policy_evaluated: str | None
    paypal_operation: str | None


class WorkflowStepOut(BaseModel):
    sequence: int
    step_type: str
    status: str
    condition: str | None
    waiting_for: str | None
    attempts: int
    provider_reference: str | None
    error: str | None


class WorkflowOut(BaseModel):
    id: uuid.UUID
    status: str
    agent_run_id: uuid.UUID | None
    project_id: uuid.UUID | None
    confirmed_at: datetime | None
    steps: list[WorkflowStepOut]


class ScheduledActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_type: str
    status: str
    run_after: datetime
    attempts: int
    last_error: str | None
    related_entity_type: str | None
    related_entity_id: uuid.UUID | None


class MemberOut(BaseModel):
    user_id: uuid.UUID
    full_name: str
    email: str
    role: str


class RuntimeOut(BaseModel):
    paypal_env: str
    paypal_configured: bool
    payouts_execution_enabled: bool
    ai_provider: str
    ai_credentials_configured: bool
