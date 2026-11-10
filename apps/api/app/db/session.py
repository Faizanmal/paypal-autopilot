"""Async SQLAlchemy engine/session management.

`expire_on_commit=False` avoids `MissingGreenlet` errors that occur when
SQLAlchemy's default post-commit attribute expiry triggers an implicit
lazy-load outside of an active greenlet in async code.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import AppEnv, get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    # Tests create a new event loop per test. A pooled asyncpg connection
    # cannot move between loops, so the test engine does not pool.
    options: dict = {"pool_pre_ping": True}
    if settings.app_env is AppEnv.TEST:
        options["poolclass"] = NullPool
    return create_async_engine(settings.database_url, **options)


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped AsyncSession."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
