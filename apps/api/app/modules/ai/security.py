"""Reject instructions that try to override policy or smuggle a new command.

Untrusted text from a user, a contract, or a provider response is data.
It is never passed back into the planner and never changes approval rules.
"""

from __future__ import annotations

import re

_INJECTION = re.compile(
    "|".join(
        [
            r"ignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above)\s+instructions",
            r"disregard\s+(?:all\s+|the\s+)?(?:previous|prior|above)",
            r"system\s+prompt",
            r"you\s+are\s+now",
            r"developer\s+message",
            r"bypass\s+(?:the\s+)?(?:approval|spending)",
            r"skip\s+(?:the\s+)?approval",
            r"without\s+approval",
            r"disable\s+(?:the\s+)?(?:payout\s+)?approval",
            r"require_payout_approval",
            r"approval\s+polic(?:y|ies)",
            r"spending\s+limit",
            r"autonomy\s+level",
            r"mark\s+(?:the\s+)?(?:invoice\s+)?(?:as\s+)?paid",
            r"set\s+status\s+to\s+paid",
            r"workspace_id\s*[:=]",
            r"client_secret",
            r"paypal_client_secret",
            r"reveal\s+(?:the\s+)?(?:secret|api\s+key)",
        ]
    ),
    re.IGNORECASE,
)

_FORBIDDEN_ARGUMENT_KEYS = frozenset(
    {
        "id",
        "api_key",
        "access_token",
        "refresh_token",
        "password",
        "secret_key",
        "milestone_id",
        "contract_id",
        "paypal_invoice_id",
        "workspace_id",
        "user_id",
        "customer_id",
        "contractor_id",
        "project_id",
        "invoice_id",
        "payout_id",
        "approval_id",
        "secret",
        "token",
        "client_secret",
        "authorization",
        "require_payout_approval",
        "autonomy_level",
        "approved_recipients",
        "paypal_client_id",
        "paypal_client_secret",
    }
)


def contains_injection(text: str) -> bool:
    return _INJECTION.search(text) is not None


def injection_rejection(text: str) -> str | None:
    if contains_injection(text):
        return (
            "That instruction asks to override the planner, the approval policy, "
            "or a recorded payment status. Nothing was executed."
        )
    return None


def forbidden_argument_key(key: str) -> bool:
    return key.strip().lower() in _FORBIDDEN_ARGUMENT_KEYS


def display_provider_error(message: str) -> str:
    """Provider and contract text can contain instructions. Do not surface or follow them."""
    if contains_injection(message):
        return "The provider response included instructions and was ignored."
    return message
