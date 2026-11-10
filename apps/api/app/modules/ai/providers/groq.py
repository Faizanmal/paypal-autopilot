"""Groq OpenAI-compatible structured-output adapter."""

from __future__ import annotations

from app.modules.ai.providers.compatible import CompatibleChatPlanner

GROQ_PLANNING_MODEL = "llama-3.3-70b-versatile"
GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"


class GroqPlanner(CompatibleChatPlanner):
    provider = "groq"
    provider_label = f"Groq {GROQ_PLANNING_MODEL}"
    model = GROQ_PLANNING_MODEL
    endpoint = GROQ_ENDPOINT
