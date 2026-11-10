"""FastAPI application factory.

Registers authentication, financial workflows, PayPal integrations, reporting,
and health routes with shared security headers and safe error responses.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.api.system import router as system_router
from app.core.config import AppEnv, get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging

configure_logging()
logger = logging.getLogger("app")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="PayPal Autopilot API",
        version="0.1.0",
        description=(
            "AI-planned, validated, approval-gated financial workflows for "
            "freelancers and small businesses, built on PayPal. Sandbox only."
        ),
        docs_url=None if settings.app_env is AppEnv.PRODUCTION else "/docs",
        redoc_url=None if settings.app_env is AppEnv.PRODUCTION else "/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-Id", "X-Idempotency-Key"],
    )

    @app.middleware("http")
    async def request_id_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if settings.app_env is AppEnv.PRODUCTION:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        # Typed, safe error translation — never leaks raw third-party error
        # bodies or internal exception text (docs/SECURITY.md §7, §9).
        logger.warning(
            "app_error",
            extra={"context": {"code": exc.code, "path": request.url.path}},
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Keep the same envelope as AppError so the web client can show a useful message
        # instead of a bare "Request failed (422)." for EmailStr / Field failures.
        messages: list[str] = []
        for error in exc.errors():
            loc = ".".join(str(part) for part in error.get("loc", ()) if part != "body")
            msg = str(error.get("msg", "Invalid value"))
            messages.append(f"{loc}: {msg}" if loc else msg)
        message = "; ".join(messages) if messages else "Request validation failed."
        logger.warning(
            "validation_error",
            extra={"context": {"path": request.url.path, "count": len(messages)}},
        )
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_failed",
                    "message": message,
                    "details": {"issues": exc.errors()},
                }
            },
        )

    app.include_router(system_router)
    app.include_router(api_router)

    return app


app = create_app()
