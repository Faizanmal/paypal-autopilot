"""Registration, login, and session issuance. One transaction per call."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record
from app.core.config import get_settings
from app.core.errors import ConflictError, UnauthorizedError
from app.modules.identity.models import MemberRole, Session, User, Workspace, WorkspaceMember
from app.modules.identity.schemas import (
    AuthSessionOut,
    LoginRequest,
    RegisterRequest,
    UserOut,
    WorkspaceOut,
)
from app.modules.identity.security import (
    SESSION_TTL_SECONDS,
    hash_password,
    hash_session_token,
    new_session_token,
    verify_password,
)
from app.modules.spendpilot.models import FinancialPolicy

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    slug = _SLUG_RE.sub("-", name.strip().lower()).strip("-")
    return slug[:160] or "workspace"


async def _unique_slug(session: AsyncSession, name: str) -> str:
    base = _slugify(name)
    candidate = base
    suffix = 2
    while await session.scalar(select(Workspace.id).where(Workspace.slug == candidate)):
        candidate = f"{base[:160]}-{suffix}"
        suffix += 1
    return candidate


def _auth_out(user: User, workspace: Workspace, role: str) -> AuthSessionOut:
    return AuthSessionOut(
        user=UserOut.model_validate(user),
        workspace=WorkspaceOut(id=workspace.id, name=workspace.name, slug=workspace.slug, role=role),
    )


async def _issue_session(
    session: AsyncSession, *, user_id, workspace_id
) -> str:
    raw = new_session_token()
    settings = get_settings()
    now = datetime.now(UTC)
    session.add(
        Session(
            user_id=user_id,
            workspace_id=workspace_id,
            token_hash=hash_session_token(raw, settings.secret_key.get_secret_value()),
            expires_at=now + timedelta(seconds=SESSION_TTL_SECONDS),
            created_at=now,
        )
    )
    return raw


async def register(session: AsyncSession, body: RegisterRequest) -> tuple[AuthSessionOut, str]:
    email = body.email.lower()
    existing = await session.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise ConflictError("An account with that email already exists.")

    user = User(email=email, password_hash=hash_password(body.password), full_name=body.full_name.strip())
    workspace = Workspace(name=body.workspace_name.strip(), slug=await _unique_slug(session, body.workspace_name))
    session.add_all([user, workspace])
    await session.flush()

    membership = WorkspaceMember(
        workspace_id=workspace.id, user_id=user.id, role=MemberRole.OWNER.value
    )
    policy = FinancialPolicy(
        workspace_id=workspace.id,
        require_payout_approval=True,
        currency_code="USD",
        autonomy_level=1,
        allowed_currencies=["USD"],
        approved_recipients=[],
        restricted_action_types=[],
    )
    session.add_all([membership, policy])
    raw = await _issue_session(session, user_id=user.id, workspace_id=workspace.id)
    record(
        session,
        action="user.registered",
        entity_type="user",
        entity_id=user.id,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        details={"workspace_slug": workspace.slug},
    )
    await session.commit()
    return _auth_out(user, workspace, MemberRole.OWNER.value), raw


async def login(session: AsyncSession, body: LoginRequest) -> tuple[AuthSessionOut, str]:
    email = body.email.lower()
    user = await session.scalar(select(User).where(User.email == email))
    if user is None or not user.is_active or not verify_password(user.password_hash, body.password):
        raise UnauthorizedError("Email or password is incorrect.")

    membership = await session.scalar(
        select(WorkspaceMember)
        .where(WorkspaceMember.user_id == user.id)
        .order_by(WorkspaceMember.created_at.asc())
    )
    if membership is None:
        raise UnauthorizedError("This account is not a member of a workspace.")
    workspace = await session.get(Workspace, membership.workspace_id)
    if workspace is None:
        raise UnauthorizedError("This account is not a member of a workspace.")

    raw = await _issue_session(session, user_id=user.id, workspace_id=workspace.id)
    record(
        session,
        action="user.logged_in",
        entity_type="user",
        entity_id=user.id,
        workspace_id=workspace.id,
        actor_user_id=user.id,
    )
    await session.commit()
    return _auth_out(user, workspace, membership.role), raw


async def revoke_session(session: AsyncSession, token_hash: str) -> None:
    row = await session.scalar(select(Session).where(Session.token_hash == token_hash))
    if row is not None and row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        record(
            session,
            action="user.logged_out",
            entity_type="session",
            entity_id=row.id,
            workspace_id=row.workspace_id,
            actor_user_id=row.user_id,
        )
        await session.commit()
