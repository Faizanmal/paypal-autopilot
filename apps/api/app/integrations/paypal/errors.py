"""Typed PayPal HTTP failures.

Messages returned to API callers use `safe_message` and a debug id.
Raw PayPal bodies are not copied into logs or HTTP responses.
"""

from __future__ import annotations


class PayPalError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        name: str | None = None,
        debug_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.name = name
        self.debug_id = debug_id

    @property
    def safe_message(self) -> str:
        label = self.name or "request"
        code = self.status_code if self.status_code is not None else "error"
        suffix = f" debug_id={self.debug_id}" if self.debug_id else ""
        return f"PayPal {label} failed ({code}).{suffix}"


class PayPalAuthError(PayPalError):
    pass


class PayPalPermissionError(PayPalError):
    pass


class PayPalNotFoundError(PayPalError):
    pass


class PayPalValidationError(PayPalError):
    pass


class PayPalConflictError(PayPalError):
    pass


class PayPalRateLimitError(PayPalError):
    pass


class PayPalUnavailableError(PayPalError):
    pass
