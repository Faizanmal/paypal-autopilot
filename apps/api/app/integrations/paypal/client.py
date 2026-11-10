"""PayPal REST client: OAuth2, retries, idempotency, and redacted logs.

Only this package may call PayPal. Token values are cached in memory and
never written to logs.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.core.config import Settings
from app.core.logging import _redact
from app.integrations.paypal.errors import (
    PayPalAuthError,
    PayPalConflictError,
    PayPalError,
    PayPalNotFoundError,
    PayPalPermissionError,
    PayPalRateLimitError,
    PayPalUnavailableError,
    PayPalValidationError,
)

logger = logging.getLogger("app.paypal")

_RETRY_STATUSES = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3


@dataclass
class PayPalCall:
    status_code: int
    body: dict[str, Any]
    debug_id: str | None
    correlation_id: str
    request_id: str | None


@dataclass
class AccessToken:
    value: str
    expires_at: datetime
    scopes: frozenset[str]


def _detail_issue_message(body: dict[str, Any]) -> str | None:
    details = body.get("details")
    if not isinstance(details, list):
        return None
    parts: list[str] = []
    for item in details:
        if not isinstance(item, dict):
            continue
        issue = item.get("issue") if isinstance(item.get("issue"), str) else None
        description = item.get("description") if isinstance(item.get("description"), str) else None
        if issue and description:
            parts.append(f"{issue}: {description}")
        elif description:
            parts.append(description)
        elif issue:
            parts.append(issue)
    if not parts:
        return None
    return " ".join(parts)


def _classify(response: httpx.Response) -> PayPalError:
    body: dict[str, Any] = {}
    if response.content:
        try:
            parsed = response.json()
        except ValueError:
            parsed = {}
        if isinstance(parsed, dict):
            body = parsed
    name = body.get("name") if isinstance(body.get("name"), str) else None
    debug_id = body.get("debug_id") if isinstance(body.get("debug_id"), str) else None
    debug_id = debug_id or response.headers.get("paypal-debug-id")
    detail_message = _detail_issue_message(body)
    raw_message = body.get("message")
    if isinstance(raw_message, str) and raw_message:
        message = raw_message
    elif response.reason_phrase:
        message = response.reason_phrase
    else:
        message = "PayPal request failed."
    if detail_message:
        message = f"{message} ({detail_message})"
    kwargs = {"status_code": response.status_code, "name": name, "debug_id": debug_id}
    if response.status_code == 401:
        return PayPalAuthError(message, **kwargs)
    if response.status_code == 403:
        return PayPalPermissionError(message, **kwargs)
    if response.status_code == 404:
        return PayPalNotFoundError(message, **kwargs)
    if response.status_code == 409:
        return PayPalConflictError(message, **kwargs)
    if response.status_code == 429:
        return PayPalRateLimitError(message, **kwargs)
    if response.status_code in {400, 422}:
        return PayPalValidationError(message, **kwargs)
    if response.status_code >= 500:
        return PayPalUnavailableError(message, **kwargs)
    return PayPalError(message, **kwargs)


class PayPalClient:
    def __init__(
        self,
        settings: Settings,
        *,
        http: httpx.AsyncClient | None = None,
        use_redis: bool = False,
        retry_sleep_seconds: float = 0.05,
    ) -> None:
        self._settings = settings
        self._http = http or httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0))
        self._owns_http = http is None
        self._use_redis = use_redis
        self._retry_sleep_seconds = retry_sleep_seconds
        self._token: AccessToken | None = None
        self._lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        return self._settings.paypal_base_url

    @property
    def scopes(self) -> frozenset[str] | None:
        if self._token is None:
            return None
        return self._token.scopes

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    def clear_token(self) -> None:
        self._token = None

    async def access_token(self, *, force_refresh: bool = False) -> AccessToken:
        if not self._settings.paypal_configured:
            raise PayPalAuthError("PayPal sandbox credentials are not configured.", status_code=None)
        async with self._lock:
            now = datetime.now(UTC)
            if not force_refresh and self._token is not None and self._token.expires_at > now:
                return self._token
            token = await self._fetch_token()
            self._token = token
            return token

    async def _fetch_token(self) -> AccessToken:
        secret = self._settings.paypal_client_secret.get_secret_value()
        try:
            response = await self._http.post(
                f"{self.base_url}/v1/oauth2/token",
                data={"grant_type": "client_credentials"},
                auth=(self._settings.paypal_client_id, secret),
                headers={"Accept": "application/json", "Accept-Language": "en_US"},
            )
        except httpx.TimeoutException as exc:
            raise PayPalUnavailableError("PayPal token request timed out.", status_code=None) from exc
        except httpx.HTTPError as exc:
            raise PayPalUnavailableError("PayPal token request failed.", status_code=None) from exc
        logger.info(
            "paypal_token",
            extra={
                "context": {
                    "status": response.status_code,
                    "debug_id": response.headers.get("paypal-debug-id"),
                }
            },
        )
        if response.status_code >= 400:
            raise _classify(response)
        body = response.json()
        raw_token = body.get("access_token")
        if not isinstance(raw_token, str) or not raw_token:
            raise PayPalAuthError(
                "PayPal token response did not include an access token.",
                status_code=response.status_code,
            )
        expires_in = int(body.get("expires_in") or 0)
        skew = 60 if expires_in > 120 else max(expires_in // 2, 1)
        scope_text = body.get("scope") if isinstance(body.get("scope"), str) else ""
        return AccessToken(
            value=raw_token,
            expires_at=datetime.now(UTC) + timedelta(seconds=max(expires_in - skew, 1)),
            scopes=frozenset(part for part in scope_text.split() if part),
        )

    async def call(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> PayPalCall:
        verb = method.upper()
        request_id = idempotency_key
        if verb in {"POST", "PUT", "PATCH"} and request_id is None:
            request_id = str(uuid.uuid4())
        retryable = verb in {"GET", "HEAD"} or request_id is not None
        correlation_id = str(uuid.uuid4())
        refreshed = False
        last_error: PayPalError | None = None

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            token = await self.access_token(force_refresh=refreshed)
            headers = {
                "Authorization": f"Bearer {token.value}",
                "Accept": "application/json",
                "PayPal-Client-Metadata-Id": correlation_id,
            }
            if json_body is not None:
                headers["Content-Type"] = "application/json"
            if request_id is not None and verb in {"POST", "PUT", "PATCH"}:
                headers["PayPal-Request-Id"] = request_id
            try:
                response = await self._http.request(
                    verb,
                    f"{self.base_url}{path}",
                    headers=headers,
                    json=json_body,
                    params=params,
                )
            except httpx.TimeoutException as exc:
                last_error = PayPalUnavailableError("PayPal request timed out.", status_code=None)
                logger.warning(
                    "paypal_http",
                    extra={
                        "context": {
                            "method": verb,
                            "path": path,
                            "attempt": attempt,
                            "error": "timeout",
                            "correlation_id": correlation_id,
                        }
                    },
                )
                if retryable and attempt < _MAX_ATTEMPTS:
                    await asyncio.sleep(self._retry_sleep_seconds)
                    continue
                raise last_error from exc
            except httpx.HTTPError as exc:
                raise PayPalUnavailableError("PayPal request failed.", status_code=None) from exc

            debug_id = response.headers.get("paypal-debug-id")
            logger.info(
                "paypal_http",
                extra={
                    "context": _redact(
                        {
                            "method": verb,
                            "path": path,
                            "status": response.status_code,
                            "attempt": attempt,
                            "debug_id": debug_id,
                            "correlation_id": correlation_id,
                            "request_id": request_id,
                        }
                    )
                },
            )
            if response.status_code == 401 and not refreshed:
                self.clear_token()
                refreshed = True
                continue
            if response.status_code in _RETRY_STATUSES and retryable and attempt < _MAX_ATTEMPTS:
                await asyncio.sleep(self._retry_sleep_seconds)
                continue
            if response.status_code >= 400:
                raise _classify(response)
            body: dict[str, Any] = {}
            if response.content:
                parsed = response.json()
                if isinstance(parsed, dict):
                    body = parsed
            return PayPalCall(
                status_code=response.status_code,
                body=body,
                debug_id=debug_id,
                correlation_id=correlation_id,
                request_id=request_id,
            )
        raise last_error or PayPalUnavailableError("PayPal request failed.", status_code=None)


_client: PayPalClient | None = None


def get_paypal_client() -> PayPalClient:
    global _client
    if _client is None:
        from app.core.config import AppEnv, get_settings

        settings = get_settings()
        _client = PayPalClient(settings, use_redis=settings.app_env is not AppEnv.TEST)
    return _client


def reset_paypal_client() -> None:
    global _client
    _client = None
