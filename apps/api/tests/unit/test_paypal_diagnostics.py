import httpx
import pytest
import respx

from app.core.config import Settings
from app.integrations.paypal.client import PayPalClient
from app.integrations.paypal.diagnostics import build_capability_report

BASE = "https://api-m.sandbox.paypal.com"


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "test",
        "secret_key": "test-secret-key-not-for-production",
        "paypal_env": "sandbox",
        "paypal_client_id": "client-id",
        "paypal_client_secret": "client-secret-value",
        "paypal_webhook_id": "WH-TEST",
        "paypal_payouts_execution": False,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_diagnostics_without_credentials_makes_no_http_calls():
    settings = _settings(paypal_client_id="", paypal_client_secret="")
    client = PayPalClient(settings, retry_sleep_seconds=0)
    async with respx.mock(assert_all_called=False) as router:
        report = await build_capability_report(settings, client)
        assert len(router.calls) == 0
    assert report.credentials_configured is False
    assert report.payouts_execution_enabled is False
    assert {item.status for item in report.checks} == {"blocked"}
    assert report.limitation


@pytest.mark.asyncio
async def test_diagnostics_only_reads_and_does_not_create_payments():
    settings = _settings()
    client = PayPalClient(settings, retry_sleep_seconds=0)
    scope = " ".join(
        [
            "https://uri.paypal.com/services/invoicing/invoices/readwrite",
            "https://uri.paypal.com/services/payments/payment",
            "https://uri.paypal.com/payments/payouts",
        ]
    )
    async with respx.mock() as router:
        router.post(f"{BASE}/v1/oauth2/token").mock(
            return_value=httpx.Response(200, json={"access_token": "token-abc", "expires_in": 3600, "scope": scope})
        )
        router.get(url__regex=r".*/v2/invoicing/invoices").mock(
            return_value=httpx.Response(200, json={"items": [], "total_items": 0})
        )
        router.get(url__regex=r".*/v2/checkout/orders/").mock(
            return_value=httpx.Response(404, json={"name": "RESOURCE_NOT_FOUND", "message": "missing"})
        )
        router.get(url__regex=r".*/v1/notifications/webhooks/").mock(
            return_value=httpx.Response(200, json={"id": "WH-TEST", "url": "https://example.com/hook"})
        )
        router.get(url__regex=r".*/v1/payments/payouts/").mock(
            return_value=httpx.Response(404, json={"name": "RESOURCE_NOT_FOUND", "message": "missing"})
        )
        report = await build_capability_report(settings, client)
        posts = [call for call in router.calls if call.request.method == "POST"]
        assert len(posts) == 1
        assert posts[0].request.url.path == "/v1/oauth2/token"
    by_name = {item.name: item.status for item in report.checks}
    assert by_name["authentication"] == "available"
    assert by_name["invoicing"] == "available"
    assert by_name["orders"] == "available"
    assert by_name["webhooks"] == "available"
    assert by_name["payouts"] == "available"
    assert report.payouts_execution_enabled is False
