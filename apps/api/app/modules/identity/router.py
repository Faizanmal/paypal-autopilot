from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.api.deps import CurrentPrincipal, DbSession
from app.core.config import AppEnv, get_settings
from app.modules.identity.schemas import (
    AuthSessionOut,
    LoginRequest,
    RegisterRequest,
    UserOut,
    WorkspaceOut,
)
from app.modules.identity.security import SESSION_COOKIE, SESSION_TTL_SECONDS, hash_session_token
from app.modules.identity.service import login, register, revoke_session

router = APIRouter(prefix="/auth", tags=["auth"])


def _cookie_secure() -> bool:
    return get_settings().app_env is AppEnv.PRODUCTION


def _set_session_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=raw_token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(),
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    # The deletion cookie must match Secure, HttpOnly, and SameSite or a
    # production browser keeps the original session cookie.
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        secure=_cookie_secure(),
        httponly=True,
        samesite="lax",
    )


@router.post("/register", response_model=AuthSessionOut, status_code=201)
async def register_account(body: RegisterRequest, response: Response, db: DbSession) -> AuthSessionOut:
    auth, raw = await register(db, body)
    _set_session_cookie(response, raw)
    return auth


@router.post("/login", response_model=AuthSessionOut)
async def login_account(body: LoginRequest, response: Response, db: DbSession) -> AuthSessionOut:
    auth, raw = await login(db, body)
    _set_session_cookie(response, raw)
    return auth


@router.post("/logout", status_code=204)
async def logout_account(request: Request, response: Response, db: DbSession) -> None:
    raw = request.cookies.get(SESSION_COOKIE)
    if raw:
        settings = get_settings()
        await revoke_session(db, hash_session_token(raw, settings.secret_key.get_secret_value()))
    _clear_session_cookie(response)


@router.get("/me", response_model=AuthSessionOut)
async def me(principal: CurrentPrincipal) -> AuthSessionOut:
    return AuthSessionOut(
        user=UserOut.model_validate(principal.user),
        workspace=WorkspaceOut(
            id=principal.workspace.id,
            name=principal.workspace.name,
            slug=principal.workspace.slug,
            role=principal.role,
        ),
    )
