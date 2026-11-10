from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from app.core.config import Settings
from app.integrations.paypal.client import AccessToken, PayPalClient
from app.integrations.paypal.errors import PayPalAuthError, PayPalNotFoundError, PayPalValidationError

BASE = "https://api-m.sandbox.paypal.com"


def _settings() -> Settings:
    return Settings(
        app_env="test",
        secret_key="test-secret-key-not-for-production",
        paypal_env="sandbox",
        paypal_client_id="client-id",
        paypal_client_secret="client-secret-value",
        paypal_webhook_id="WH-TEST",
        paypal_sandbox_business_email="merchant@example.com",
    )


def _token() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "access_token": "token-abc",
            "expires_in": 3600,
            "scope": "https://uri.paypal.com/services/invoicing/invoices/readwrite",
        },
    )


@pytest.mark.asyncio
async def test_token_is_cached_until_it_expires():
    client = PayPalClient(_settings(), retry_sleep_seconds=0)
    async with respx.mock() as router:
        token_route = router.post(f"{BASE}/v1/oauth2/token").mock(return_value=_token())
        first = await client.access_token()
        second = await client.access_token()
        assert token_route.call_count == 1
    assert first.value == second.value == "token-abc"


@pytest.mark.asyncio
async def test_expired_token_is_refreshed():
    client = PayPalClient(_settings(), retry_sleep_seconds=0)
    client._token = AccessToken("stale-token", datetime.now(UTC) - timedelta(seconds=5), frozenset())
    async with respx.mock() as router:
        token_route = router.post(f"{BASE}/v1/oauth2/token").mock(return_value=_token())
        token = await client.access_token()
        assert token_route.call_count == 1
    assert token.value == "token-abc"


@pytest.mark.asyncio
async def test_unauthorized_call_refreshes_token_once():
    client = PayPalClient(_settings(), retry_sleep_seconds=0)
    async with respx.mock() as router:
        token_route = router.post(f"{BASE}/v1/oauth2/token").mock(return_value=_token())
        invoice_route = router.get(f"{BASE}/v2/invoicing/invoices/INV2-1").mock(
            side_effect=[
                httpx.Response(401, json={"name": "AUTHENTICATION_FAILURE", "message": "expired", "debug_id": "d1"}),
                httpx.Response(200, json={"id": "INV2-1", "status": "DRAFT"}),
            ]
        )
        result = await client.call("GET", "/v2/invoicing/invoices/INV2-1")
        assert token_route.call_count == 2
        assert invoice_route.call_count == 2
    assert result.body["status"] == "DRAFT"


@pytest.mark.asyncio
async def test_retry_reuses_idempotency_key_and_classifies_errors(caplog: pytest.LogCaptureFixture):
    client = PayPalClient(_settings(), retry_sleep_seconds=0)
    seen: list[str | None] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("PayPal-Request-Id"))
        if len(seen) == 1:
            return httpx.Response(503, json={"name": "INTERNAL_SERVER_ERROR", "message": "later", "debug_id": "dbg"})
        return httpx.Response(200, json={"id": "INV2-1", "status": "DRAFT"})

    async with respx.mock() as router:
        router.post(f"{BASE}/v1/oauth2/token").mock(return_value=_token())
        router.post(f"{BASE}/v2/invoicing/invoices").mock(side_effect=respond)
        with caplog.at_level(logging.INFO):
            result = await client.call(
                "POST",
                "/v2/invoicing/invoices",
                json_body={"items": []},
                idempotency_key="same-key",
            )
    assert result.body["id"] == "INV2-1"
    assert seen == ["same-key", "same-key"]
    logged = caplog.text
    assert "token-abc" not in logged
    assert "client-secret-value" not in logged


@pytest.mark.asyncio
async def test_validation_and_not_found_are_not_retried():
    client = PayPalClient(_settings(), retry_sleep_seconds=0)
    async with respx.mock() as router:
        router.post(f"{BASE}/v1/oauth2/token").mock(return_value=_token())
        invalid = router.post(f"{BASE}/v2/invoicing/invoices").mock(
            return_value=httpx.Response(422, json={"name": "UNPROCESSABLE_ENTITY", "message": "bad", "debug_id": "d"})
        )
        with pytest.raises(PayPalValidationError):
            await client.call("POST", "/v2/invoicing/invoices", json_body={}, idempotency_key="once")
        missing = router.get(f"{BASE}/v2/checkout/orders/MISSING").mock(
            return_value=httpx.Response(404, json={"name": "RESOURCE_NOT_FOUND", "message": "missing"})
        )
        with pytest.raises(PayPalNotFoundError):
            await client.call("GET", "/v2/checkout/orders/MISSING")
        assert invalid.call_count == 1
        assert missing.call_count == 1


@pytest.mark.asyncio
async def test_missing_credentials_do_not_call_paypal():
    settings = _settings()
    settings.paypal_client_id = ""
    client = PayPalClient(settings, retry_sleep_seconds=0)
    async with respx.mock(assert_all_called=False) as router:
        with pytest.raises(PayPalAuthError):
            await client.access_token()
        assert len(router.calls) == 0
