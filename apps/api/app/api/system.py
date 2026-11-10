"""Liveness and readiness. Readiness checks the database and does not report success on failure."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import DbSession
from app.core.config import get_settings
from app.core.errors import ServiceUnavailableError

logger = logging.getLogger("app.system")
router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "paypal_env": settings.paypal_env.value}


@router.get("/ready")
async def ready(db: DbSession) -> dict[str, str]:
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        logger.error("readiness_check_failed", extra={"context": {"error_type": type(exc).__name__}})
        raise ServiceUnavailableError("Database is not ready.") from exc
    return {"status": "ready", "database": "ok"}
