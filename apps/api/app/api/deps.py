"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.identity.deps import Principal, get_current_principal

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def current_principal(request: Request, db: DbSession) -> Principal:
    return await get_current_principal(request, db)


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]
