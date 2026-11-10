from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.modules.autopilot.models import Invoice, PaymentRecord
from app.modules.identity.models import MemberRole, Session, User, WorkspaceMember
from app.modules.identity.security import hash_session_token, new_session_token
from app.modules.spendpilot.models import PayoutRequest
from app.modules.trustflow.models import Contractor, Customer


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


async def _seed_cash_rows(workspace_id: str) -> None:
    factory = get_session_factory()
    now = datetime.now(UTC)
    wid = uuid.UUID(workspace_id)
    async with factory() as session:
        customer = Customer(
            workspace_id=wid,
            name="Acme",
            email="billing@acme.example",
        )
        contractor = Contractor(
            workspace_id=wid,
            name="Grace Hopper",
            email="dev@example.com",
            paypal_email="dev@example.com",
        )
        session.add_all([customer, contractor])
        await session.flush()
        invoice = Invoice(
            workspace_id=wid,
            customer_id=customer.id,
            currency_code="USD",
            amount=Decimal("120.00"),
            status="sent",
            due_at=now - timedelta(days=3),
        )
        paid = Invoice(
            workspace_id=wid,
            customer_id=customer.id,
            currency_code="USD",
            amount=Decimal("40.00"),
            status="paid",
            due_at=now - timedelta(days=10),
        )
        session.add_all([invoice, paid])
        await session.flush()
        session.add(
            PaymentRecord(
                workspace_id=wid,
                invoice_id=paid.id,
                currency_code="USD",
                amount=Decimal("40.00"),
                source="paypal_webhook",
                external_id="PAY-40",
                received_at=now - timedelta(days=9),
            )
        )
        session.add(
            PayoutRequest(
                workspace_id=wid,
                contractor_id=contractor.id,
                currency_code="USD",
                amount=Decimal("25.00"),
                status="pending_approval",
                recipient_email="dev@example.com",
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_finance_snapshot_separates_confirmed_from_expected(app, clean_db):
    async with await _client(app) as client:
        created = await _register(client, "cash@example.com", "Cash Co")
        await _seed_cash_rows(created["workspace"]["id"])

        empty_open = await client.get("/api/v1/finance/snapshot")
        assert empty_open.status_code == 200, empty_open.text
        body = empty_open.json()
        assert body["currency"] == "USD"
        assert body["total_invoiced"] == "160.00"
        assert body["confirmed_payments"] == "40.00"
        assert body["total_paid"] == "40.00"
        assert body["outstanding_receivables"] == "120.00"
        assert body["overdue_receivables"] == "120.00"
        assert body["pending_contractor_obligations"] == "25.00"
        assert body["net_cash_flow_estimate"] is None
        assert body["paypal_balance_available"] is False
        assert body["paypal_balance_amount"] is None
        assert any(insight["kind"] == "overdue" for insight in body["insights"])
        assert any(alert["kind"] == "overdue" for alert in body["alerts"])
        assert any(alert["kind"] == "pending_approval" for alert in body["alerts"])
        assert body["uncertainty"]

        saved = await client.put(
            "/api/v1/finance/assumptions",
            json={"opening_balance": "200.00", "as_of": None},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["opening_balance"] == "200.00"

        snap = await client.get("/api/v1/finance/snapshot?horizon_days=30")
        assert snap.status_code == 200, snap.text
        projected = snap.json()
        assert projected["opening_balance"] == "200.00"
        assert projected["net_cash_flow_estimate"] == "240.00"
        assert projected["projected_available"] == "215.00"
        assert projected["pending_contractor_obligations"] == "25.00"

        logs = await client.get("/api/v1/audit-logs")
        assert logs.status_code == 200, logs.text
        finance_rows = [row for row in logs.json()["items"] if row["action"] == "finance.assumption_set"]
        assert finance_rows
        assert finance_rows[0]["proposed_by_ai"] is False
        assert finance_rows[0]["policy_evaluated"] == "owner_opening_balance"
        assert finance_rows[0]["result"] == "stored"


@pytest.mark.asyncio
async def test_only_owner_can_set_opening_balance(app, clean_db):
    async with await _client(app) as owner, await _client(app) as member_client:
        created = await _register(owner, "owner.cash@example.com", "Owner Cash")
        member = await _register(member_client, "member.cash@example.com", "Temp Workspace")
        workspace_id = uuid.UUID(created["workspace"]["id"])
        raw = new_session_token()
        factory = get_session_factory()
        async with factory() as session:
            user = await session.scalar(select(User).where(User.email == "member.cash@example.com"))
            assert user is not None
            session.add(
                WorkspaceMember(
                    workspace_id=workspace_id,
                    user_id=user.id,
                    role=MemberRole.MEMBER.value,
                )
            )
            session.add(
                Session(
                    user_id=uuid.UUID(member["user"]["id"]),
                    workspace_id=workspace_id,
                    token_hash=hash_session_token(raw, get_settings().secret_key.get_secret_value()),
                    expires_at=datetime.now(UTC) + timedelta(days=1),
                )
            )
            await session.commit()
        member_client.cookies.set("autopilot_session", raw)
        denied = await member_client.put("/api/v1/finance/assumptions", json={"opening_balance": "10.00"})
        assert denied.status_code == 403, denied.text

        allowed = await owner.put("/api/v1/finance/assumptions", json={"opening_balance": "10.00"})
        assert allowed.status_code == 200, allowed.text
