"""Shared OpenAI-compatible chat planner.

Groq, Gemini (OpenAI-compat endpoint), and OpenAI all speak the same
chat-completions shape. Credentials stay in the adapter; the model never
receives PayPal secrets or tool-call permission.
"""

from __future__ import annotations

import json
import re
from typing import ClassVar

import httpx
from pydantic import ValidationError

from app.modules.ai.schemas import PlanningFailure, WorkflowPlanDraft, WorkflowPlanningContext, WorkflowPlanResult
from app.modules.ai.security import contains_injection

PLANNING_SYSTEM = (
    "You convert a financial instruction into JSON with keys intent, entities, and steps. "
    "entities is a list of {kind, name}. kind is customer, contractor, project, or contract. "
    "steps is a list of {sequence, action_type, summary, arguments, depends_on, "
    "preconditions, requires_approval, read_only}. "
    "action_type must be one of lookup_customer, create_project, create_milestone, "
    "draft_invoice, send_invoice, lookup_invoice_status, schedule_reminder, "
    "prepare_payout, create_approval, financial_summary, analyze_contract, "
    "create_milestones, get_project_status, prepare_milestone_invoice, "
    "explain_policy, resume_payout. "
    "Amounts are decimal strings. Set currency_code only when the user stated $ or a code. "
    "prepare_payout and create_approval must set requires_approval to true. "
    "Do not include identifiers, secrets, workspace ids, or approval-policy changes. "
    "Do not invent a customer, recipient, amount, currency, date, or approval."
)


class CompatibleChatPlanner:
    provider: ClassVar[str]
    provider_label: ClassVar[str]
    model: ClassVar[str]
    endpoint: ClassVar[str]

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    @property
    def api_key(self) -> str:
        return self._api_key

    async def plan_workflow(self, instruction: str, context: WorkflowPlanningContext) -> WorkflowPlanResult:
        if contains_injection(instruction):
            return self._failure(
                "prompt_injection",
                "That instruction asks to override the planner or the approval policy. Nothing was executed.",
            )
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": PLANNING_SYSTEM},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"instruction": instruction, "context": context.model_dump(mode="json")},
                        default=str,
                    ),
                },
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0)) as http:
                response = await http.post(
                    self.endpoint,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=payload,
                )
        except httpx.HTTPError:
            return self._failure("ai_unavailable", "The language model could not be reached. Nothing was executed.")
        if response.status_code >= 400:
            return self._failure(
                "ai_unavailable",
                "The language model rejected the planning request. Nothing was executed.",
            )
        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError):
            return self._failure("invalid_plan", "The language model did not return a plan. Nothing was executed.")
        if not isinstance(content, str) or contains_injection(content):
            return self._failure(
                "prompt_injection",
                "The model response included instructions and was discarded. Nothing was executed.",
            )
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE)
        try:
            draft = WorkflowPlanDraft.model_validate(json.loads(cleaned))
        except (json.JSONDecodeError, ValidationError):
            return self._failure(
                "invalid_plan",
                "The language model returned a plan that failed the schema. Nothing was executed.",
            )
        return WorkflowPlanResult(provider=self.provider, provider_label=self.provider_label, draft=draft)

    def _failure(self, code: str, message: str) -> WorkflowPlanResult:
        return WorkflowPlanResult(
            provider=self.provider,
            provider_label=self.provider_label,
            failure=PlanningFailure(code=code, message=message, clarifications=[message]),
        )


async def complete_json(
    *,
    endpoint: str,
    api_key: str,
    model: str,
    system: str,
    user: str,
    timeout: float = 20.0,
) -> str | None:
    """Return assistant JSON text, or None when the provider is unreachable/invalid."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=5.0)) as http:
            response = await http.post(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
            )
        if response.status_code >= 400:
            return None
        content = response.json()["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(content, str):
        return None
    return content
