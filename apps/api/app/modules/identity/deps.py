"""Request dependencies that resolve the signed-in user and workspace.

Every protected query takes `Principal` and filters by `principal.workspace_id`.
A missing or foreign row is a 404 at the service layer, not a cross-workspace read.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import UnauthorizedError
from app.modules.identity.models import Session, User, Workspace, WorkspaceMember
from app.modules.identity.security import SESSION_COOKIE, hash_session_token


@dataclass(frozen=True, slots=True)
class Principal:
    user: User
    workspace: Workspace
    role: str

    @property
    def user_id(self) -> uuid.UUID:
        return self.user.id

    @property
    def workspace_id(self) -> uuid.UUID:
        return self.workspace.id


async def get_current_principal(request: Request, db: AsyncSession) -> Principal:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        raise UnauthorizedError("Sign in to continue.")
    settings = get_settings()
    token_hash = hash_session_token(raw, settings.secret_key.get_secret_value())
    now = datetime.now(UTC)
    session_row = await db.scalar(
        select(Session).where(
            Session.token_hash == token_hash,
            Session.revoked_at.is_(None),
            Session.expires_at > now,
        )
    )
    if session_row is None:
        raise UnauthorizedError("Sign in to continue.")

    user = await db.get(User, session_row.user_id)
    workspace = await db.get(Workspace, session_row.workspace_id)
    if user is None or not user.is_active or workspace is None:
        raise UnauthorizedError("Sign in to continue.")

    membership = await db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.workspace_id == workspace.id,
        )
    )
    if membership is None:
        raise UnauthorizedError("Sign in to continue.")
    return Principal(user=user, workspace=workspace, role=membership.role)
