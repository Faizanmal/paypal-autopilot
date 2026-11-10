"""Try LLM providers in priority order, then the rule-based parser.

Order: groq → gemini → openai → fallback_rules.
Cascade continues on transport/schema failures, not on prompt injection.
"""

from __future__ import annotations

import logging
import re

from app.modules.ai.providers.compatible import CompatibleChatPlanner
from app.modules.ai.providers.fallback import RuleBasedFallbackProvider
from app.modules.ai.schemas import WorkflowPlanningContext, WorkflowPlanResult

_RETRYABLE = frozenset({"ai_unavailable", "invalid_plan"})
logger = logging.getLogger("app.ai.providers")


class CascadingPlanner:
    provider = "auto"
    provider_label = "AI cascade (groq → gemini → openai → rules)"

    def __init__(self, planners: list[CompatibleChatPlanner]) -> None:
        self._planners = planners
        self._fallback = RuleBasedFallbackProvider()

    async def plan_workflow(self, instruction: str, context: WorkflowPlanningContext) -> WorkflowPlanResult:
        failures: list[str] = []
        labels: list[str] = []
        for planner in self._planners:
            result = await planner.plan_workflow(instruction, context)
            if result.draft is not None:
                return result
            if result.failure is None:
                # A malformed adapter result is a real provider failure.
                failures.append(f"{planner.provider_label}: no plan or error returned")
                labels.append(f"{planner.provider_label}: empty response")
                logger.warning("ai_provider_empty_result", extra={"context": {"provider": planner.provider}})
                continue
            logger.warning("ai_provider_failed", extra={"context": {
                "provider": planner.provider, "code": result.failure.code, "reason": result.failure.message,
            }})
            if result.failure.code == "prompt_injection":
                return result
            if result.failure.code not in _RETRYABLE:
                return result
            failures.append(f"{planner.provider_label}: {result.failure.message}")
            status = re.search(r"HTTP \d{3}", result.failure.message)
            reason = status.group() if status else (
                "timeout" if "timed out" in result.failure.message else result.failure.code
            )
            labels.append(f"{planner.provider_label}: {reason}")
        result = await self._fallback.plan_workflow(instruction, context)
        if failures:
            reason = "; ".join(failures)
            result.provider_label = f"Fallback parser ({'; '.join(labels)})"
            logger.warning("ai_rules_fallback", extra={"context": {"reason": reason}})
        return result
