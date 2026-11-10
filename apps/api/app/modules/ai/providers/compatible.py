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

from app.modules.ai.schemas import (
    ALLOWED_ARGUMENT_KEYS,
    PlanningFailure,
    WorkflowPlanDraft,
    WorkflowPlanningContext,
    WorkflowPlanResult,
)
from app.modules.ai.security import contains_injection
from app.modules.ai.validate import sanitize_plan_arguments

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
    " Only use these argument keys: " + ", ".join(sorted(ALLOWED_ARGUMENT_KEYS)) + ". "
    "Omit unused arguments (or use null if required by the response schema). "
    "For a vague request, use only supported steps with explicitly stated arguments; "
    "missing information will be clarified before execution."
)


def planning_json_schema() -> dict:
    schema = WorkflowPlanDraft.model_json_schema()
    properties = {
        key: {"type": ["integer" if key in {"days", "min_days_overdue"}
                         else "boolean" if key == "name_is_default" else "string", "null"]}
        for key in sorted(ALLOWED_ARGUMENT_KEYS)
    }
    schema["$defs"]["PlanStepDraft"]["properties"]["arguments"] = {
        "type": "object", "properties": properties, "required": list(properties), "additionalProperties": False,
    }

    def strict_objects(node):
        if isinstance(node, dict):
            node.pop("default", None)
            if node.get("type") == "object":
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}))
            for value in node.values():
                strict_objects(value)
        elif isinstance(node, list):
            for value in node:
                strict_objects(value)

    strict_objects(schema)
    return schema


class CompatibleChatPlanner:
    supports_json_schema: ClassVar[bool] = False
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
            "response_format": (
                {"type": "json_schema", "json_schema": {
                    "name": "workflow_plan", "strict": True, "schema": planning_json_schema(),
                }} if self.supports_json_schema else {"type": "json_object"}
            ),
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
        except httpx.TimeoutException:
            return self._failure("ai_unavailable", "The language model request timed out (20s). Nothing was executed.")
        except httpx.HTTPError:
            return self._failure("ai_unavailable", "The language model could not be reached. Nothing was executed.")
        if response.status_code >= 400:
            return self._failure(
                "ai_unavailable",
                f"The language model returned HTTP {response.status_code}. Nothing was executed.",
            )
        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError):
            return self._failure("invalid_plan", "The language model did not return a plan. Nothing was executed.")
        if not isinstance(content, str):
            return self._failure(
                "prompt_injection",
                "The model response included instructions and was discarded. Nothing was executed.",
            )
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE)
        try:
            draft = WorkflowPlanDraft.model_validate(json.loads(cleaned))
        except (json.JSONDecodeError, ValidationError):
            if contains_injection(content):
                return self._failure("prompt_injection", "The model response included instructions and was discarded.")
            return self._failure(
                "invalid_plan",
                "The language model returned a plan that failed the schema. Nothing was executed.",
            )
        sanitized = sanitize_plan_arguments(draft, instruction)
        if not sanitized.ok:
            return self._failure(sanitized.code or "invalid_plan", sanitized.message or "The plan is invalid.")
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
