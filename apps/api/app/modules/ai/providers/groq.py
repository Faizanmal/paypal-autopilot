"""Groq OpenAI-compatible structured-output adapter."""

from __future__ import annotations

from app.modules.ai.providers.compatible import CompatibleChatPlanner

# Supported production replacement: https://console.groq.com/docs/models
GROQ_PLANNING_MODEL = "openai/gpt-oss-120b"
GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"


class GroqPlanner(CompatibleChatPlanner):
    # https://console.groq.com/docs/structured-outputs#supported-models
    supports_json_schema = True
    provider = "groq"
    provider_label = f"Groq {GROQ_PLANNING_MODEL}"
    model = GROQ_PLANNING_MODEL
    endpoint = GROQ_ENDPOINT
