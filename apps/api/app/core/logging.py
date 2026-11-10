"""Structured logging configuration with secret redaction.

Project rule: "Never log credentials, access tokens, or sensitive
financial data." This module provides a `logging.Filter` that redacts
values of known secret-shaped keys from structured log records as a
defense-in-depth measure (the primary defense is simply never passing
secrets into a log call in the first place).
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

_REDACT_KEY_SUBSTRINGS = (
    "secret",
    "token",
    "password",
    "authorization",
    "client_secret",
    "api_key",
    "apikey",
)

_REDACTED = "***REDACTED***"


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: (_REDACTED if any(s in k.lower() for s in _REDACT_KEY_SUBSTRINGS) else _redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


class RedactingFilter(logging.Filter):
    """Redacts known secret-shaped fields attached to a LogRecord via `extra=`."""

    def filter(self, record: logging.LogRecord) -> bool:
        context = getattr(record, "context", None)
        if isinstance(context, dict):
            record.context = _redact(context)
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        context = getattr(record, "context", None)
        if context:
            payload["context"] = context
        request_id = getattr(record, "request_id", None)
        if request_id:
            payload["request_id"] = request_id
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactingFilter())
    root.addHandler(handler)
