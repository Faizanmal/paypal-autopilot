"""Try LLM providers in priority order, then the rule-based parser.

Order: groq → gemini → openai → fallback_rules.
Cascade continues on transport/schema failures, not on prompt injection.
"""

from __future__ import annotations

from app.modules.ai.providers.compatible import CompatibleChatPlanner
from app.modules.ai.providers.fallback import RuleBasedFallbackProvider
from app.modules.ai.schemas import WorkflowPlanningContext, WorkflowPlanResult

_RETRYABLE = frozenset({"ai_unavailable", "invalid_plan"})


class CascadingPlanner:
    provider = "auto"
    provider_label = "AI cascade (groq → gemini → openai → rules)"

    def __init__(self, planners: list[CompatibleChatPlanner]) -> None:
        self._planners = planners
        self._fallback = RuleBasedFallbackProvider()

    async def plan_workflow(self, instruction: str, context: WorkflowPlanningContext) -> WorkflowPlanResult:
        for planner in self._planners:
            result = await planner.plan_workflow(instruction, context)
            if result.draft is not None:
                return result
            if result.failure is None:
                continue
            if result.failure.code == "prompt_injection":
                return result
            if result.failure.code not in _RETRYABLE:
                return result
        return await self._fallback.plan_workflow(instruction, context)
