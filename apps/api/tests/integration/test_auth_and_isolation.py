from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient


async def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


async def _register(client: AsyncClient, email: str, workspace: str) -> dict:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "correct-horse-battery",
            "full_name": "Ada Lovelace",
            "workspace_name": workspace,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_register_login_me_and_logout(app, clean_db):
    async with await _client(app) as client:
        created = await _register(client, "ada@example.com", "Analytical Engines")
        assert created["workspace"]["role"] == "owner"
        assert "password" not in response_text(created)

        me = await client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["user"]["email"] == "ada@example.com"

        logged_out = await client.post("/api/v1/auth/logout")
        assert logged_out.status_code == 204
        assert (await client.get("/api/v1/auth/me")).status_code == 401

        logged_in = await client.post(
            "/api/v1/auth/login",
            json={"email": "ada@example.com", "password": "correct-horse-battery"},
        )
        assert logged_in.status_code == 200
        assert (await client.get("/api/v1/auth/me")).status_code == 200

        wrong = await client.post(
            "/api/v1/auth/login",
            json={"email": "ada@example.com", "password": "not-the-password"},
        )
        assert wrong.status_code == 401


def response_text(payload: dict) -> str:
    return str(payload)


@pytest.mark.asyncio
async def test_workspace_isolation_and_milestone_total(app, clean_db):
    async with await _client(app) as owner, await _client(app) as other:
        await _register(owner, "owner@example.com", "Owner Co")
        await _register(other, "other@example.com", "Other Co")

        created = await owner.post(
            "/api/v1/customers",
            json={"name": "Acme", "email": "billing@acme.example"},
        )
        assert created.status_code == 201, created.text
        customer_id = created.json()["id"]

        hidden = await other.get("/api/v1/customers")
        assert hidden.status_code == 200
        assert hidden.json()["items"] == []

        project = await owner.post(
            "/api/v1/projects",
            json={
                "name": "Acme site",
                "currency_code": "USD",
                "total_amount": "100.00",
                "customer_id": customer_id,
            },
        )
        assert project.status_code == 201, project.text
        body = project.json()
        assert body["total_amount"] == "100.00"
        assert isinstance(body["total_amount"], str)
        project_id = body["id"]

        missing = await other.get(f"/api/v1/projects/{project_id}/milestones")
        assert missing.status_code == 404

        first = await owner.post(
            f"/api/v1/projects/{project_id}/milestones",
            json={
                "name": "Upfront",
                "amount": "60.00",
                "currency_code": "USD",
                "trigger_kind": "upfront",
            },
        )
        assert first.status_code == 201, first.text

        overflow = await owner.post(
            f"/api/v1/projects/{project_id}/milestones",
            json={
                "name": "Delivery",
                "amount": "50.00",
                "currency_code": "USD",
                "trigger_kind": "on_delivery",
            },
        )
        assert overflow.status_code == 422

        async with await _client(app) as anonymous:
            anonymous_response = await anonymous.get("/api/v1/projects")
            assert anonymous_response.status_code == 401


@pytest.mark.asyncio
async def test_readiness_reports_database(app, clean_db):
    async with await _client(app) as client:
        response = await client.get("/api/v1/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ready", "database": "ok"}


def test_decimal_import_guard():
    assert Decimal("100.00") + Decimal("0.10") == Decimal("100.10")
