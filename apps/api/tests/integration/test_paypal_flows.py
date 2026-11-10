from __future__ import annotations

import json

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.integrations.paypal.client import reset_paypal_client

BASE = "https://api-m.sandbox.paypal.com"


class AcceptWebhook:
    async def verify(self, raw_body: bytes, headers: dict[str, str]) -> None:
        return None


class RejectWebhook:
    async def verify(self, raw_body: bytes, headers: dict[str, str]) -> None:
        from app.core.errors import WebhookVerificationError

        raise WebhookVerificationError("PayPal webhook signature is invalid.")


@pytest.fixture
def paypal_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "client-id")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "client-secret-value")
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "WH-TEST")
    monkeypatch.setenv("PAYPAL_SANDBOX_BUSINESS_EMAIL", "merchant@example.com")
    monkeypatch.setenv("PAYPAL_PAYOUTS_EXECUTION", "false")
    get_settings.cache_clear()
    reset_paypal_client()
    yield
    get_settings.cache_clear()
    reset_paypal_client()


def _token(scope: str) -> httpx.Response:
    return httpx.Response(200, json={"access_token": "token-abc", "expires_in": 3600, "scope": scope})


async def _register(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "ada.paypal@example.com",
            "password": "correct-horse-battery",
            "full_name": "Ada Lovelace",
            "workspace_name": "Analytical Engines",
        },
    )
    assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_invoice_webhook_order_and_payout_capability(app, clean_db, paypal_env):
    app.state.paypal_webhook_verifier = AcceptWebhook()
    scope = "https://uri.paypal.com/services/invoicing/invoices/readwrite"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await _register(client)
        customer = await client.post("/api/v1/customers", json={"name": "Acme", "email": "billing@acme.example"})
        assert customer.status_code == 201, customer.text
        customer_id = customer.json()["id"]

        async with respx.mock(assert_all_called=False) as paypal:
            paypal.post(f"{BASE}/v1/oauth2/token").mock(return_value=_token(scope))
            paypal.post(f"{BASE}/v2/invoicing/invoices").mock(
                return_value=httpx.Response(
                    201,
                    json={
                        "id": "INV2-TEST",
                        "status": "DRAFT",
                        "links": [{"rel": "payer-view", "href": "https://www.sandbox.paypal.com/invoice/p/INV2-TEST"}],
                    },
                )
            )
            created = await client.post(
                "/api/v1/invoices",
                json={
                    "customer_id": customer_id,
                    "amount": "100.00",
                    "currency_code": "USD",
                    "description": "Website redesign",
                    "idempotency_key": "invoice-1",
                },
            )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["paypal_invoice_id"] == "INV2-TEST"
        assert body["status"] == "draft"
        assert body["provider_status"] == "DRAFT"
        assert body["amount"] == "100.00"
        invoice_id = body["id"]

        paid = {
            "id": "WH-PAID",
            "event_type": "INVOICING.INVOICE.PAID",
            "resource": {"id": "INV2-TEST", "status": "PAID"},
        }
        async with respx.mock(assert_all_called=False) as paypal:
            paypal.post(f"{BASE}/v1/oauth2/token").mock(return_value=_token(scope))
            paypal.get(f"{BASE}/v2/invoicing/invoices/INV2-TEST").mock(
                return_value=httpx.Response(200, json={"id": "INV2-TEST", "status": "PAID"})
            )
            first = await client.post(
                "/api/v1/webhooks/paypal",
                content=json.dumps(paid),
                headers={"content-type": "application/json"},
            )
            assert first.status_code == 200, first.text
            assert first.json()["status"] == "processed"
            duplicate = await client.post(
                "/api/v1/webhooks/paypal", content=json.dumps(paid), headers={"content-type": "application/json"}
            )
        assert duplicate.status_code == 200
        assert duplicate.json()["status"] == "duplicate"

        delayed = {
            "id": "WH-SENT",
            "event_type": "INVOICING.INVOICE.SENT",
            "resource": {"id": "INV2-TEST", "status": "SENT"},
        }
        late = await client.post(
            "/api/v1/webhooks/paypal",
            content=json.dumps(delayed),
            headers={"content-type": "application/json"},
        )
        assert late.status_code == 200, late.text
        listed = await client.get("/api/v1/invoices")
        assert listed.status_code == 200
        invoice = listed.json()["items"][0]
        assert invoice["status"] == "paid"
        assert invoice["provider_status"] == "PAID"
        assert invoice["id"] == invoice_id

        async with respx.mock(assert_all_called=False) as paypal:
            paypal.post(f"{BASE}/v1/oauth2/token").mock(return_value=_token("https://uri.paypal.com/services/payments/payment"))
            paypal.post(f"{BASE}/v2/checkout/orders").mock(
                return_value=httpx.Response(
                    201,
                    json={
                        "id": "ORDER1",
                        "status": "CREATED",
                        "links": [{"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER1"}],
                    },
                )
            )
            paypal.get(f"{BASE}/v2/checkout/orders/ORDER1").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "id": "ORDER1",
                        "status": "CREATED",
                        "links": [{"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER1"}],
                    },
                )
            )
            capture = paypal.post(f"{BASE}/v2/checkout/orders/ORDER1/capture").mock(
                return_value=httpx.Response(201, json={"id": "ORDER1", "status": "COMPLETED"})
            )
            order = await client.post(
                "/api/v1/checkout/orders",
                json={
                    "amount": "25.00",
                    "currency_code": "USD",
                    "description": "Deposit",
                    "idempotency_key": "order-1",
                },
            )
            assert order.status_code == 201, order.text
            assert order.json()["approval_url"].startswith("https://www.sandbox.paypal.com/")
            refused = await client.post(f"/api/v1/checkout/orders/{order.json()['id']}/capture")
            assert refused.status_code == 409, refused.text
            assert "approval" in refused.json()["error"]["message"].lower()
            assert capture.call_count == 0

        contractor = await client.post(
            "/api/v1/contractors",
            json={"name": "Grace", "email": "grace@example.com", "paypal_email": "grace.paypal@example.com"},
        )
        assert contractor.status_code == 201, contractor.text
        async with respx.mock(assert_all_called=False) as paypal:
            payout_post = paypal.post(f"{BASE}/v1/payments/payouts").mock(return_value=httpx.Response(201, json={}))
            intent = await client.post(
                "/api/v1/payout-requests",
                json={"contractor_id": contractor.json()["id"], "amount": "40.00", "currency_code": "USD"},
            )
            assert intent.status_code == 201, intent.text
            assert intent.json()["status"] == "pending_approval"
            approved = await client.post(f"/api/v1/payout-requests/{intent.json()['id']}/approve")
            assert approved.status_code == 200, approved.text
            assert approved.json()["status"] == "approved"
            raised = await client.patch("/api/v1/financial-policy", json={"autonomy_level": 2})
            assert raised.status_code == 200, raised.text
            executed = await client.post(f"/api/v1/payout-requests/{intent.json()['id']}/execute")
            assert executed.status_code == 403, executed.text
            assert executed.json()["error"]["code"] == "paypal_capability_unavailable"
            message = executed.json()["error"]["message"].lower()
            assert "disabled" in message or "not configured" in message
            assert payout_post.call_count == 0


@pytest.mark.asyncio
async def test_invalid_webhook_signature_is_rejected(app, clean_db):
    app.state.paypal_webhook_verifier = RejectWebhook()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/webhooks/paypal",
            content=json.dumps({"id": "WH-BAD", "event_type": "INVOICING.INVOICE.PAID", "resource": {}}),
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "webhook_verification_failed"


@pytest.mark.asyncio
async def test_diagnostics_reports_missing_credentials_without_calling_paypal(app, clean_db, monkeypatch):
    monkeypatch.delenv("PAYPAL_CLIENT_ID", raising=False)
    monkeypatch.delenv("PAYPAL_CLIENT_SECRET", raising=False)
    get_settings.cache_clear()
    reset_paypal_client()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await _register(client)
        async with respx.mock(assert_all_called=False) as mock:
            mock.route().mock(return_value=httpx.Response(500))
            response = await client.get("/api/v1/integrations/paypal/diagnostics")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["credentials_configured"] is False
    assert body["payouts_execution_enabled"] is False
    assert mock.calls.call_count == 0
    get_settings.cache_clear()
    reset_paypal_client()
