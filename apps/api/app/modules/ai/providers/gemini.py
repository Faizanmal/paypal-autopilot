"""Gemini via Google's OpenAI-compatible chat endpoint."""

from __future__ import annotations

from app.modules.ai.providers.compatible import CompatibleChatPlanner

# Current compatibility example: https://aistudio.google.com/docs/openai
GEMINI_PLANNING_MODEL = "gemini-3.8-flash"
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"


class GeminiPlanner(CompatibleChatPlanner):
    provider = "gemini"
    provider_label = f"Gemini {GEMINI_PLANNING_MODEL}"
    model = GEMINI_PLANNING_MODEL
    endpoint = GEMINI_ENDPOINT
