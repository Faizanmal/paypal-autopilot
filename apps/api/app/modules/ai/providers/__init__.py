from __future__ import annotations

from app.core.config import AIProviderName, Settings
from app.modules.ai.providers.cascade import CascadingPlanner
from app.modules.ai.providers.compatible import CompatibleChatPlanner
from app.modules.ai.providers.fallback import RuleBasedFallbackProvider
from app.modules.ai.providers.gemini import GeminiPlanner
from app.modules.ai.providers.groq import GroqPlanner
from app.modules.ai.providers.openai import OpenAIPlanner

# Auto priority; a pinned provider goes first, followed by the other configured providers.
LLM_CHAIN: tuple[AIProviderName, ...] = (
    AIProviderName.GROQ,
    AIProviderName.GEMINI,
    AIProviderName.OPENAI,
)

Planner = RuleBasedFallbackProvider | CompatibleChatPlanner | CascadingPlanner


def _build_llm(name: AIProviderName, key: str) -> CompatibleChatPlanner:
    if name is AIProviderName.GROQ:
        return GroqPlanner(key)
    if name is AIProviderName.GEMINI:
        return GeminiPlanner(key)
    return OpenAIPlanner(key)


def configured_llm_keys(settings: Settings) -> dict[AIProviderName, str]:
    return {
        AIProviderName.GROQ: settings.groq_api_key.get_secret_value().strip(),
        AIProviderName.GEMINI: settings.gemini_api_key.get_secret_value().strip(),
        AIProviderName.OPENAI: settings.openai_api_key.get_secret_value().strip(),
    }


def llm_planners_for(settings: Settings) -> list[CompatibleChatPlanner]:
    keys = configured_llm_keys(settings)
    if settings.ai_provider is AIProviderName.FALLBACK_RULES:
        return []
    if settings.ai_provider is AIProviderName.AUTO:
        names = list(LLM_CHAIN)
    elif settings.ai_provider in LLM_CHAIN:
        names = [settings.ai_provider, *(name for name in LLM_CHAIN if name is not settings.ai_provider)]
    else:
        names = []
    return [_build_llm(name, keys[name]) for name in names if keys[name]]


def get_planner(settings: Settings) -> Planner:
    planners = llm_planners_for(settings)
    if not planners:
        fallback = RuleBasedFallbackProvider()
        if settings.ai_credentials_configured and settings.ai_provider is AIProviderName.FALLBACK_RULES:
            fallback.provider_label = "Fallback parser (AI_PROVIDER=fallback_rules explicitly selected)"
        return fallback
    if len(planners) == 1 and settings.ai_provider is not AIProviderName.AUTO:
        # Still wrap so transport failures fall through to rules.
        return CascadingPlanner(planners)
    return CascadingPlanner(planners)
