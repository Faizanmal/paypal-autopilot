"""Typed application errors.

Project rule: "No silent exception swallowing or false success states."
All domain-level failures should raise one of these (or a subclass),
never a bare `Exception`/`except: pass`. A FastAPI exception handler
(registered in `app.main`) translates these into safe, typed JSON
responses without leaking internal details or third-party error bodies
that might contain sensitive request context.
"""

from __future__ import annotations


class AppError(Exception):
    """Base class for all expected, typed application errors."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class ValidationFailedError(AppError):
    """A structured plan or request failed business-rule validation (Layer 2)."""

    status_code = 422
    code = "validation_failed"


class PolicyViolationError(AppError):
    """An action is blocked by SpendPilot policy (e.g. missing approval)."""

    status_code = 403
    code = "policy_violation"


class IdempotencyConflictError(AppError):
    """Same idempotency key reused with a different request payload."""

    status_code = 409
    code = "idempotency_conflict"


class WebhookVerificationError(AppError):
    status_code = 400
    code = "webhook_verification_failed"


class ExternalServiceError(AppError):
    """A third-party API (e.g. PayPal) call failed, timed out, or returned
    an unexpected shape. Never silently treated as success."""

    status_code = 502
    code = "external_service_error"


class AIPlanningError(AppError):
    """The AI layer could not produce a valid WorkflowPlanDraft."""

    status_code = 422
    code = "ai_planning_failed"


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"


class PayPalNotConfiguredError(AppError):
    """Sandbox credentials are absent. No PayPal call was made."""

    status_code = 503
    code = "paypal_not_configured"


class PayPalCapabilityError(AppError):
    """The sandbox app cannot perform this PayPal operation."""

    status_code = 403
    code = "paypal_capability_unavailable"


class WebhookProcessingError(AppError):
    """The event was stored, but applying it failed. PayPal may retry."""

    status_code = 500
    code = "webhook_processing_failed"
