"""OpenAI structured-output adapter."""

from __future__ import annotations

from app.modules.ai.providers.compatible import CompatibleChatPlanner

OPENAI_PLANNING_MODEL = "gpt-4o-mini"
OPENAI_ENDPOINT = "https://api.openai.com/v1/chat/completions"


class OpenAIPlanner(CompatibleChatPlanner):
    supports_json_schema = True
    provider = "openai"
    provider_label = f"OpenAI {OPENAI_PLANNING_MODEL}"
    model = OPENAI_PLANNING_MODEL
    endpoint = OPENAI_ENDPOINT
