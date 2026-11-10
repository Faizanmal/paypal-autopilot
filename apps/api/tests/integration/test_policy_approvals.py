"""Security coverage for spending policy and exact-action approval."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.audit.models import AuditLog
from app.core.config import get_settings
from app.db.session import get_session_factory
from app.integrations.paypal.client import reset_paypal_client
from app.modules.autopilot.models import Invoice
from app.modules.identity.models import MemberRole, Session, WorkspaceMember
from app.modules.identity.security import hash_session_token, new_session_token
from app.modules.spendpilot.approvals import request_approval
from app.modules.spendpilot.models import Approval, FinancialPolicy, PayoutRequest

BASE = "https://api-m.sandbox.paypal.com"
PAYOUTS_SCOPE = "https://uri.paypal.com/payments/payouts"


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


def _enable_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAYPAL_PAYOUTS_EXECUTION", "true")
    get_settings.cache_clear()
    reset_paypal_client()


async def _register(client: AsyncClient, email: str, workspace: str = "Analytical Engines") -> dict:
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


async def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


async def _contractor(client: AsyncClient, name: str = "Ada", email: str = "ada.payee@example.com") -> dict:
    response = await client.post(
        "/api/v1/contractors",
        json={"name": name, "email": email, "paypal_email": "ada.paypal@example.com"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _payout(client: AsyncClient, contractor_id: str, amount: str = "40.00", key: str | None = None) -> dict:
    body: dict[str, str] = {"contractor_id": contractor_id, "amount": amount, "currency_code": "USD"}
    if key:
        body["idempotency_key"] = key
    response = await client.post("/api/v1/payout-requests", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def _patch_policy(client: AsyncClient, payload: dict) -> httpx.Response:
    return await client.patch("/api/v1/financial-policy", json=payload)


def _token() -> httpx.Response:
    return httpx.Response(200, json={"access_token": "token-abc", "expires_in": 3600, "scope": PAYOUTS_SCOPE})


def _batch(batch_id: str = "BATCH-TEST") -> httpx.Response:
    return httpx.Response(201, json={"batch_header": {"payout_batch_id": batch_id, "batch_status": "PENDING"}})


async def _approval_for(payout_id: str) -> Approval:
    factory = get_session_factory()
    async with factory() as session:
        approval = await session.scalar(select(Approval).where(Approval.payout_request_id == uuid.UUID(payout_id)))
        assert approval is not None
        return approval


async def _count(model, *where) -> int:
    factory = get_session_factory()
    async with factory() as session:
        value = await session.scalar(select(func.count()).select_from(model).where(*where))
        return int(value or 0)


@pytest.mark.asyncio
async def test_concurrent_budget_reservations_and_duplicate_intents(app, clean_db, paypal_env):
    async with await _client(app) as client:
        await _register(client, "budget.race@example.com")
        contractor = await _contractor(client)
        assert (await _patch_policy(client, {"daily_limit": "50.00"})).status_code == 200
        cookie = client.cookies.get("autopilot_session")

        async def prepare(key):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://testserver",
                cookies={"autopilot_session": cookie},
            ) as other:
                return await other.post("/api/v1/payout-requests", json={
                    "contractor_id": contractor["id"], "amount": "30.00", "idempotency_key": key,
                })

        raced = await asyncio.gather(prepare("budget-a"), prepare("budget-b"))
        assert sorted(row.status_code for row in raced) == [201, 403]
        assert await _count(PayoutRequest) == 1
        assert (await _patch_policy(client, {"daily_limit": None})).status_code == 200
        duplicates = await asyncio.gather(prepare("same-key"), prepare("same-key"))
        assert [row.status_code for row in duplicates] == [201, 201]
        assert duplicates[0].json()["id"] == duplicates[1].json()["id"]
        assert await _count(PayoutRequest) == 2
        assert await _count(Approval) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", [{"paused": True}, {"autonomy_level": 0}])
async def test_global_stop_blocks_backend_and_agent_mutations(app, clean_db, paypal_env, policy):
    async with await _client(app) as client:
        await _register(client, "global.stop@example.com")
        assert (await _patch_policy(client, policy)).status_code == 200
        async with respx.mock(assert_all_called=False) as paypal:
            provider = paypal.post(f"{BASE}/v2/invoicing/invoices").mock(return_value=httpx.Response(201))
            project = await client.post("/api/v1/projects", json={
                "name": "Blocked project", "total_amount": "30.00", "currency_code": "USD",
            })
            assert project.status_code == 403, project.text
            invoice = await client.post("/api/v1/invoices", json={
                "customer_id": str(uuid.uuid4()), "amount": "30.00", "description": "Blocked draft",
            })
            assert invoice.status_code == 403, invoice.text
            assert provider.call_count == 0
        assert (await client.get("/api/v1/projects")).status_code == 200
        planned = await client.post("/api/v1/agent/plans", json={
            "instruction": "Create a $30 project with three payment milestones.",
        })
        assert planned.status_code == 201, planned.text
        confirmed = await client.post(f"/api/v1/agent/runs/{planned.json()['id']}/confirm")
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["status"] == "failed"
        assert confirmed.json()["steps"][0]["status"] == "failed"


@pytest.mark.asyncio
async def test_revoked_approver_cannot_authorize_execution(app, clean_db, paypal_env, monkeypatch):
    async with await _client(app) as owner, await _client(app) as executor:
        created = await _register(owner, "original.owner@example.com")
        replacement = await _register(executor, "replacement.owner@example.com", "Replacement")
        contractor = await _contractor(owner)
        assert (await _patch_policy(owner, {"autonomy_level": 2})).status_code == 200
        payout = await _payout(owner, contractor["id"])
        assert (await owner.post(f"/api/v1/payout-requests/{payout['id']}/approve")).status_code == 200
        workspace_id = uuid.UUID(created["workspace"]["id"])
        user_id = uuid.UUID(replacement["user"]["id"])
        raw = new_session_token()
        async with get_session_factory()() as session:
            member = await session.scalar(select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == uuid.UUID(created["user"]["id"]),
            ))
            member.role = MemberRole.MEMBER
            session.add(WorkspaceMember(workspace_id=workspace_id, user_id=user_id, role=MemberRole.OWNER))
            session.add(Session(
                workspace_id=workspace_id, user_id=user_id,
                token_hash=hash_session_token(raw, get_settings().secret_key.get_secret_value()),
                expires_at=datetime.now(UTC) + timedelta(days=1),
            ))
            await session.commit()
        executor.cookies.clear()
        executor.cookies.set("autopilot_session", raw)
        resumed = await executor.post("/api/v1/agent/plans", json={
            "instruction": "Resume the payout to Ada after approval.",
        })
        assert resumed.status_code == 201, resumed.text
        outcome = resumed.json()["steps"][0]["result"]
        assert outcome["can_resume"] is False
        assert "no longer authorized" in outcome["reason"]
        _enable_execution(monkeypatch)
        async with respx.mock(assert_all_called=False) as paypal:
            paypal.post(f"{BASE}/v1/oauth2/token").mock(return_value=_token())
            post = paypal.post(f"{BASE}/v1/payments/payouts").mock(return_value=_batch())
            result = await executor.post(f"/api/v1/payout-requests/{payout['id']}/execute")
            assert result.status_code == 409, result.text
            assert "no longer authorized" in result.json()["error"]["message"]
            assert post.call_count == 0
        assert (await _approval_for(payout["id"])).consumed_at is None
        assert await _count(AuditLog, AuditLog.action == "payout.execution_denied") == 1


@pytest.mark.asyncio
async def test_refunded_trigger_payment_blocks_execution(app, clean_db, paypal_env, monkeypatch):
    async with await _client(app) as client:
        registered = await _register(client, "trigger.refund@example.com")
        contractor = await _contractor(client)
        customer = await client.post("/api/v1/customers", json={"name": "Client", "email": "client@example.com"})
        assert customer.status_code == 201, customer.text
        async with get_session_factory()() as session:
            invoice = Invoice(
                workspace_id=uuid.UUID(registered["workspace"]["id"]),
                customer_id=uuid.UUID(customer.json()["id"]),
                status="paid", amount=Decimal("100.00"), currency_code="USD",
            )
            session.add(invoice)
            await session.commit()
            invoice_id = invoice.id
        assert (await _patch_policy(client, {"autonomy_level": 2})).status_code == 200
        created = await client.post("/api/v1/payout-requests", json={
            "contractor_id": contractor["id"], "amount": "40.00", "trigger_invoice_id": str(invoice_id),
        })
        assert created.status_code == 201, created.text
        payout_id = created.json()["id"]
        assert (await client.post(f"/api/v1/payout-requests/{payout_id}/approve")).status_code == 200
        async with get_session_factory()() as session:
            invoice = await session.get(Invoice, invoice_id)
            invoice.status = "refunded"
            await session.commit()
        _enable_execution(monkeypatch)
        async with respx.mock(assert_all_called=False) as paypal:
            paypal.post(f"{BASE}/v1/oauth2/token").mock(return_value=_token())
            post = paypal.post(f"{BASE}/v1/payments/payouts").mock(return_value=_batch())
            result = await client.post(f"/api/v1/payout-requests/{payout_id}/execute")
            assert result.status_code == 403, result.text
            assert "no longer cleared" in result.json()["error"]["message"]
            assert post.call_count == 0
        assert (await _approval_for(payout_id)).consumed_at is None


@pytest.mark.asyncio
async def test_cancel_and_expire_approved_actions_release_budget(app, clean_db, paypal_env):
    async with await _client(app) as client:
        await _register(client, "revoke@example.com")
        contractor = await _contractor(client)
        assert (await _patch_policy(client, {"daily_limit": "40.00"})).status_code == 200
        for decision in ("cancel", "expire"):
            payout = await _payout(client, contractor["id"])
            assert (await client.post(f"/api/v1/payout-requests/{payout['id']}/approve")).status_code == 200
            if decision == "expire":
                async with get_session_factory()() as session:
                    approval = await session.scalar(select(Approval).where(
                        Approval.payout_request_id == uuid.UUID(payout["id"])
                    ))
                    approval.expires_at = datetime.now(UTC) - timedelta(seconds=1)
                    await session.commit()
            revoked = await client.post(f"/api/v1/payout-requests/{payout['id']}/{decision}")
            assert revoked.status_code == 200, revoked.text
            assert revoked.json()["status"] == "canceled"
        await _payout(client, contractor["id"])


@pytest.mark.asyncio
async def test_prior_day_reservation_counts_in_current_budget(app, clean_db, paypal_env):
    async with await _client(app) as client:
        await _register(client, "rollover@example.com")
        contractor = await _contractor(client)
        payout = await _payout(client, contractor["id"])
        async with get_session_factory()() as session:
            row = await session.get(PayoutRequest, uuid.UUID(payout["id"]))
            row.created_at = datetime.now(UTC) - timedelta(days=40)
            await session.commit()
        assert (await _patch_policy(client, {"daily_limit": "50.00"})).status_code == 200
        response = await client.post("/api/v1/payout-requests", json={
            "contractor_id": contractor["id"], "amount": "20.00",
        })
        assert response.status_code == 403, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "missing_batch", "empty_batch"])
async def test_ambiguous_submission_never_reuses_authorization(app, clean_db, paypal_env, monkeypatch, failure):
    async with await _client(app) as client:
        await _register(client, f"ambiguous.{failure}@example.com")
        contractor = await _contractor(client)
        assert (await _patch_policy(client, {"autonomy_level": 2})).status_code == 200
        payout = await _payout(client, contractor["id"])
        assert (await client.post(f"/api/v1/payout-requests/{payout['id']}/approve")).status_code == 200
        _enable_execution(monkeypatch)
        async with respx.mock(assert_all_called=False) as paypal:
            paypal.post(f"{BASE}/v1/oauth2/token").mock(return_value=_token())
            route = paypal.post(f"{BASE}/v1/payments/payouts")
            if failure == "timeout":
                route.mock(side_effect=httpx.ReadTimeout("response lost"))
            elif failure == "empty_batch":
                route.mock(return_value=httpx.Response(201, json={"batch_header": {"payout_batch_id": ""}}))
            else:
                route.mock(return_value=httpx.Response(201, json={"batch_header": {}}))
            first = await client.post(f"/api/v1/payout-requests/{payout['id']}/execute")
            assert first.status_code == 502, first.text
            calls = route.call_count
            again = await client.post(f"/api/v1/payout-requests/{payout['id']}/execute")
            assert again.status_code == 409, again.text
            assert route.call_count == calls
        assert (await _approval_for(payout["id"])).consumed_at is not None
        async with get_session_factory()() as session:
            row = await session.get(PayoutRequest, uuid.UUID(payout["id"]))
            assert row.status == "execution_unknown"
        assert await _count(AuditLog, AuditLog.action == "payout.execution_unknown") == 1


@pytest.mark.asyncio
async def test_default_policy_is_assistant_and_payout_approval_stays_on(app, clean_db, paypal_env):
    async with await _client(app) as client:
        await _register(client, "ada.policy@example.com")
        current = await client.get("/api/v1/financial-policy")
        assert current.status_code == 200, current.text
        body = current.json()
        assert body["autonomy_level"] == 1
        assert body["require_payout_approval"] is True
        refused = await client.patch(
            "/api/v1/financial-policy",
            json={"require_payout_approval": False, "autonomy_level": 3},
        )
        assert refused.status_code == 422, refused.text
        still = await client.get("/api/v1/financial-policy")
        assert still.json()["require_payout_approval"] is True
        assert still.json()["autonomy_level"] == 1


@pytest.mark.asyncio
async def test_spending_limits_block_preparation(app, clean_db, paypal_env):
    async with await _client(app) as client:
        created = await _register(client, "ada.limits@example.com")
        contractor = await _contractor(client)
        workspace_id = uuid.UUID(created["workspace"]["id"])
        limited = await _patch_policy(client, {"per_transaction_limit": "10.00"})
        assert limited.status_code == 200, limited.text
        blocked = await client.post(
            "/api/v1/payout-requests",
            json={"contractor_id": contractor["id"], "amount": "40.00", "currency_code": "USD"},
        )
        assert blocked.status_code == 403, blocked.text
        assert blocked.json()["error"]["code"] == "policy_violation"
        assert "per-transaction limit" in blocked.json()["error"]["message"]
        assert await _count(PayoutRequest, PayoutRequest.workspace_id == workspace_id) == 0

        opened = await _patch_policy(client, {"per_transaction_limit": None, "daily_limit": "50.00"})
        assert opened.status_code == 200, opened.text
        first = await _payout(client, contractor["id"], "40.00")
        assert first["status"] == "pending_approval"
        second = await client.post(
            "/api/v1/payout-requests",
            json={"contractor_id": contractor["id"], "amount": "20.00", "currency_code": "USD"},
        )
        assert second.status_code == 403, second.text
        assert "daily limit" in second.json()["error"]["message"]

        capped = await _patch_policy(client, {"daily_limit": None, "workspace_spending_limit": "50.00"})
        assert capped.status_code == 200, capped.text
        third = await client.post(
            "/api/v1/payout-requests",
            json={"contractor_id": contractor["id"], "amount": "20.00", "currency_code": "USD"},
        )
        assert third.status_code == 403, third.text
        assert "workspace spending limit" in third.json()["error"]["message"]


@pytest.mark.asyncio
async def test_currency_recipient_restriction_and_emergency_pause(app, clean_db, paypal_env, monkeypatch):
    async with await _client(app) as client:
        await _register(client, "ada.pause@example.com")
        contractor = await _contractor(client)
        prepared = await _payout(client, contractor["id"])
        approved = await client.post(f"/api/v1/payout-requests/{prepared['id']}/approve")
        assert approved.status_code == 200, approved.text
        operator = await _patch_policy(
            client,
            {
                "autonomy_level": 3,
                "approval_threshold_amount": "100000.00",
                "allowed_currencies": [],
            },
        )
        assert operator.status_code == 200, operator.text
        currency_blocked = await client.post(
            "/api/v1/payout-requests",
            json={"contractor_id": contractor["id"], "amount": "5.00", "currency_code": "USD"},
        )
        assert currency_blocked.status_code == 403, currency_blocked.text
        assert "not an allowed currency" in currency_blocked.json()["error"]["message"]

        listed = await _patch_policy(
            client,
            {"allowed_currencies": ["USD"], "approved_recipients": ["other@example.com"]},
        )
        assert listed.status_code == 200, listed.text
        recipient_blocked = await client.post(
            "/api/v1/payout-requests",
            json={"contractor_id": contractor["id"], "amount": "5.00", "currency_code": "USD"},
        )
        assert recipient_blocked.status_code == 403, recipient_blocked.text
        assert "approved recipient" in recipient_blocked.json()["error"]["message"]

        paused = await _patch_policy(client, {"approved_recipients": [], "paused": True})
        assert paused.status_code == 200, paused.text
        assert paused.json()["paused_at"] is not None
        while_paused = await client.post(
            "/api/v1/payout-requests",
            json={"contractor_id": contractor["id"], "amount": "5.00", "currency_code": "USD"},
        )
        assert while_paused.status_code == 403, while_paused.text
        assert "paused" in while_paused.json()["error"]["message"]

        _enable_execution(monkeypatch)
        async with respx.mock(assert_all_called=False) as paypal:
            payout_post = paypal.post(f"{BASE}/v1/payments/payouts").mock(return_value=_batch())
            paypal.post(f"{BASE}/v1/oauth2/token").mock(return_value=_token())
            executed = await client.post(f"/api/v1/payout-requests/{prepared['id']}/execute")
            assert executed.status_code == 403, executed.text
            assert "paused" in executed.json()["error"]["message"]
            assert payout_post.call_count == 0


@pytest.mark.asyncio
async def test_expired_and_changed_approvals_cannot_execute(app, clean_db, paypal_env, monkeypatch):
    async with await _client(app) as client:
        await _register(client, "ada.expire@example.com")
        contractor = await _contractor(client)
        raised = await _patch_policy(client, {"autonomy_level": 2})
        assert raised.status_code == 200, raised.text
        stale = await _payout(client, contractor["id"], "15.00")
        factory = get_session_factory()
        async with factory() as session:
            approval = await session.scalar(
                select(Approval).where(Approval.payout_request_id == uuid.UUID(stale["id"]))
            )
            assert approval is not None
            approval.expires_at = datetime.now(UTC) - timedelta(minutes=1)
            await session.commit()
        expired = await client.post(f"/api/v1/payout-requests/{stale['id']}/approve")
        assert expired.status_code == 409, expired.text
        assert "expired" in expired.json()["error"]["message"]
        stored = await _approval_for(stale["id"])
        assert stored.status == "expired"

        current = await _payout(client, contractor["id"], "16.00")
        approved = await client.post(f"/api/v1/payout-requests/{current['id']}/approve")
        assert approved.status_code == 200, approved.text
        async with factory() as session:
            payout = await session.get(PayoutRequest, uuid.UUID(current["id"]))
            assert payout is not None
            payout.amount = Decimal("99.00")
            await session.commit()
        _enable_execution(monkeypatch)
        async with respx.mock(assert_all_called=False) as paypal:
            payout_post = paypal.post(f"{BASE}/v1/payments/payouts").mock(return_value=_batch("BATCH-CHANGED"))
            paypal.post(f"{BASE}/v1/oauth2/token").mock(return_value=_token())
            executed = await client.post(f"/api/v1/payout-requests/{current['id']}/execute")
            assert executed.status_code == 409, executed.text
            assert "fresh approval" in executed.json()["error"]["message"]
            assert payout_post.call_count == 0
        changed = await _approval_for(current["id"])
        assert changed.consumed_at is None
        assert changed.amount == Decimal("16.00")


@pytest.mark.asyncio
async def test_member_cannot_approve_and_autopilot_cannot_skip_approval(app, clean_db, paypal_env, monkeypatch):
    async with await _client(app) as owner:
        created = await _register(owner, "ada.owner@example.com")
        contractor = await _contractor(owner)
        payout = await _payout(owner, contractor["id"], "18.00")
        workspace_id = uuid.UUID(created["workspace"]["id"])
        async with await _client(app) as member_client:
            member = await _register(member_client, "grace.member@example.com", "Other Engines")
            raw = new_session_token()
            factory = get_session_factory()
            async with factory() as session:
                session.add(
                    WorkspaceMember(
                        workspace_id=workspace_id,
                        user_id=uuid.UUID(member["user"]["id"]),
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
            denied = await member_client.post(f"/api/v1/payout-requests/{payout['id']}/approve")
            assert denied.status_code == 403, denied.text
            assert denied.json()["error"]["code"] == "policy_violation"
            policy_denied = await member_client.patch("/api/v1/financial-policy", json={"autonomy_level": 3})
            assert policy_denied.status_code == 403, policy_denied.text

        autopilot = await _patch_policy(
            owner, {"autonomy_level": 3, "approval_threshold_amount": "100000.00"}
        )
        assert autopilot.status_code == 200, autopilot.text
        _enable_execution(monkeypatch)
        async with respx.mock(assert_all_called=False) as paypal:
            payout_post = paypal.post(f"{BASE}/v1/payments/payouts").mock(return_value=_batch("BATCH-SKIP"))
            paypal.post(f"{BASE}/v1/oauth2/token").mock(return_value=_token())
            skipped = await owner.post(f"/api/v1/payout-requests/{payout['id']}/execute")
            assert skipped.status_code == 409, skipped.text
            assert "Approve the payout" in skipped.json()["error"]["message"]
            assert payout_post.call_count == 0
        approval = await _approval_for(payout["id"])
        assert approval.status == "pending"
        assert approval.consumed_at is None


@pytest.mark.asyncio
async def test_reject_requires_a_reason_and_keeps_it(app, clean_db, paypal_env):
    async with await _client(app) as client:
        await _register(client, "ada.reject@example.com")
        contractor = await _contractor(client, email="ada.reject.payee@example.com")
        payout = await _payout(client, contractor["id"], "9.00")
        missing = await client.post(f"/api/v1/payout-requests/{payout['id']}/reject", json={})
        assert missing.status_code == 422, missing.text
        short = await client.post(
            f"/api/v1/payout-requests/{payout['id']}/reject",
            json={"reason": "no"},
        )
        assert short.status_code == 422, short.text
        rejected = await client.post(
            f"/api/v1/payout-requests/{payout['id']}/reject",
            json={"reason": "The milestone was not accepted."},
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["status"] == "canceled"
        assert rejected.json()["decision_reason"] == "The milestone was not accepted."
        listed = await client.get("/api/v1/payout-requests")
        match = next(item for item in listed.json()["items"] if item["id"] == payout["id"])
        assert match["decision_reason"] == "The milestone was not accepted."
        assert match["paypal_payout_batch_id"] is None


@pytest.mark.asyncio
async def test_duplicate_execution_consumes_approval_once(app, clean_db, paypal_env, monkeypatch):
    async with await _client(app) as client:
        await _register(client, "ada.replay@example.com")
        contractor = await _contractor(client)
        raised = await _patch_policy(client, {"autonomy_level": 2})
        assert raised.status_code == 200, raised.text
        payout = await _payout(client, contractor["id"], "21.00")
        approved = await client.post(f"/api/v1/payout-requests/{payout['id']}/approve")
        assert approved.status_code == 200, approved.text
        failed = await _payout(client, contractor["id"], "22.00", key="failure-key")
        failed_approved = await client.post(f"/api/v1/payout-requests/{failed['id']}/approve")
        assert failed_approved.status_code == 200, failed_approved.text
        _enable_execution(monkeypatch)
        async with respx.mock(assert_all_called=False) as paypal:
            payout_post = paypal.post(f"{BASE}/v1/payments/payouts").mock(
                side_effect=[
                    httpx.Response(422, json={"message": "The payout was not accepted.", "name": "VALIDATION_ERROR"}),
                    _batch("BATCH-ONCE"),
                    _batch("BATCH-ONCE"),
                ]
            )
            paypal.post(f"{BASE}/v1/oauth2/token").mock(return_value=_token())
            rejected = await client.post(f"/api/v1/payout-requests/{failed['id']}/execute")
            assert rejected.status_code == 502, rejected.text
            first = await client.post(f"/api/v1/payout-requests/{payout['id']}/execute")
            assert first.status_code == 200, first.text
            assert first.json()["paypal_payout_batch_id"] == "BATCH-ONCE"
            second = await client.post(f"/api/v1/payout-requests/{payout['id']}/execute")
            assert second.status_code == 200, second.text
            assert second.json()["paypal_payout_batch_id"] == "BATCH-ONCE"
            assert payout_post.call_count == 2
        consumed = await _approval_for(payout["id"])
        assert consumed.consumed_at is not None
        unconsumed = await _approval_for(failed["id"])
        assert unconsumed.consumed_at is not None
        assert unconsumed.status == "approved"

        factory = get_session_factory()
        async with factory() as session:
            row = await session.get(PayoutRequest, uuid.UUID(payout["id"]))
            assert row is not None
            row.paypal_payout_batch_id = None
            await session.commit()
        async with respx.mock(assert_all_called=False) as paypal:
            replay = paypal.post(f"{BASE}/v1/payments/payouts").mock(return_value=_batch("BATCH-REPLAY"))
            paypal.post(f"{BASE}/v1/oauth2/token").mock(return_value=_token())
            again = await client.post(f"/api/v1/payout-requests/{payout['id']}/execute")
            assert again.status_code == 409, again.text
            assert replay.call_count == 0


@pytest.mark.asyncio
async def test_simultaneous_approval_and_execution(app, clean_db, paypal_env, monkeypatch):
    async with await _client(app) as client:
        created = await _register(client, "ada.race@example.com")
        contractor = await _contractor(client)
        raised = await _patch_policy(client, {"autonomy_level": 2})
        assert raised.status_code == 200, raised.text
        payout = await _payout(client, contractor["id"], "30.00")
        cookie = client.cookies.get("autopilot_session")
        assert cookie

        async def approve_once() -> httpx.Response:
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://testserver",
                cookies={"autopilot_session": cookie},
            ) as other:
                return await other.post(f"/api/v1/payout-requests/{payout['id']}/approve")

        approved = await asyncio.gather(approve_once(), approve_once())
        assert [item.status_code for item in approved] == [200, 200]
        assert await _count(
            AuditLog,
            AuditLog.action == "payout.approved",
            AuditLog.entity_id == uuid.UUID(payout["id"]),
        ) == 1

        workspace_id = uuid.UUID(created["workspace"]["id"])
        user_id = uuid.UUID(created["user"]["id"])
        target_id = uuid.uuid4()

        async def request_once() -> uuid.UUID:
            factory = get_session_factory()
            async with factory() as session:
                approval = await request_approval(
                    session,
                    workspace_id=workspace_id,
                    user_id=user_id,
                    action_type="payout",
                    recipient="ada.paypal@example.com",
                    amount=Decimal("12.00"),
                    currency="USD",
                    target_type="payout_request",
                    target_id=target_id,
                    payout_request_id=None,
                    reason="Same action",
                    commit=True,
                )
                return approval.id

        ids = await asyncio.gather(request_once(), request_once())
        assert ids[0] == ids[1]
        assert await _count(Approval, Approval.action_hash.is_not(None), Approval.target_id == target_id) == 1

        _enable_execution(monkeypatch)
        async with respx.mock(assert_all_called=False) as paypal:
            payout_post = paypal.post(f"{BASE}/v1/payments/payouts").mock(return_value=_batch("BATCH-RACE"))
            paypal.post(f"{BASE}/v1/oauth2/token").mock(return_value=_token())

            async def execute_once() -> httpx.Response:
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://testserver",
                    cookies={"autopilot_session": cookie},
                ) as other:
                    return await other.post(f"/api/v1/payout-requests/{payout['id']}/execute")

            executed = await asyncio.gather(execute_once(), execute_once())
            assert all(item.status_code in {200, 409} for item in executed)
            assert any(item.status_code == 200 for item in executed)
            batches = {item.json()["paypal_payout_batch_id"] for item in executed if item.status_code == 200}
            assert batches == {"BATCH-RACE"}
            assert payout_post.call_count == 1


@pytest.mark.asyncio
async def test_reused_approval_does_not_authorize_a_different_payout(app, clean_db, paypal_env, monkeypatch):
    async with await _client(app) as client:
        await _register(client, "ada.reuse@example.com")
        contractor = await _contractor(client)
        raised = await _patch_policy(client, {"autonomy_level": 2})
        assert raised.status_code == 200, raised.text
        first = await _payout(client, contractor["id"], "11.00")
        second = await _payout(client, contractor["id"], "11.00")
        approved = await client.post(f"/api/v1/payout-requests/{first['id']}/approve")
        assert approved.status_code == 200, approved.text
        factory = get_session_factory()
        async with factory() as session:
            source = await session.scalar(select(Approval).where(Approval.payout_request_id == uuid.UUID(first["id"])))
            copied = await session.scalar(
                select(Approval).where(Approval.payout_request_id == uuid.UUID(second["id"]))
            )
            assert source is not None and copied is not None
            source.consumed_at = datetime.now(UTC)
            await session.flush()
            copied.action_hash = source.action_hash
            copied.approval_hash = source.approval_hash
            copied.status = "approved"
            copied.decided_by_user_id = source.decided_by_user_id
            copied.decided_at = source.decided_at
            payout = await session.get(PayoutRequest, uuid.UUID(second["id"]))
            assert payout is not None
            payout.status = "approved"
            await session.commit()
        _enable_execution(monkeypatch)
        async with respx.mock(assert_all_called=False) as paypal:
            payout_post = paypal.post(f"{BASE}/v1/payments/payouts").mock(return_value=_batch("BATCH-REUSE"))
            paypal.post(f"{BASE}/v1/oauth2/token").mock(return_value=_token())
            reused = await client.post(f"/api/v1/payout-requests/{second['id']}/execute")
            assert reused.status_code == 409, reused.text
            assert "fresh approval" in reused.json()["error"]["message"]
            assert payout_post.call_count == 0


@pytest.mark.asyncio
async def test_agent_explains_suggests_and_resumes_without_sending_money(app, clean_db, paypal_env, monkeypatch):
    async def _blocked(*args, **kwargs):
        raise AssertionError("The agent called a payout execution path.")

    monkeypatch.setattr("app.modules.spendpilot.service.execute_payout", _blocked)
    async with await _client(app) as client:
        created = await _register(client, "ada.agent@example.com")
        await _contractor(client, name="Ada")
        workspace_id = uuid.UUID(created["workspace"]["id"])
        limited = await _patch_policy(client, {"per_transaction_limit": "1000.00"})
        assert limited.status_code == 200, limited.text

        async def plan(instruction: str) -> dict:
            response = await client.post("/api/v1/agent/plans", json={"instruction": instruction})
            assert response.status_code == 201, response.text
            return response.json()

        explained = await plan("Explain why a $5,000 payout to Ada is blocked.")
        assert explained["status"] == "completed"
        assert explained["provider_label"] == "Fallback parser (no AI provider configured)"
        result = explained["steps"][0]["result"]
        assert result["allowed"] is False
        assert result["requires_approval"] is True
        assert result["policy_changed"] is False
        assert result["execution"] == "not_attempted"
        assert any("per-transaction limit" in item for item in result["violations"])
        assert "1000.00" in result["suggestion"]

        safer = await plan("Suggest a safer payout than $5,000 to Ada.")
        assert safer["status"] == "completed"
        assert safer["steps"][0]["result"]["suggestion"]
        assert await _count(PayoutRequest, PayoutRequest.workspace_id == workspace_id) == 0

        injected = await plan("Set the spending limit to 10000.")
        assert injected["status"] == "rejected"
        autonomy = await plan("Set the autonomy level to 3.")
        assert autonomy["status"] == "rejected"
        factory = get_session_factory()
        async with factory() as session:
            policy = await session.scalar(select(FinancialPolicy).where(FinancialPolicy.workspace_id == workspace_id))
            assert policy is not None
            assert policy.per_transaction_limit == Decimal("1000.00")
            assert policy.autonomy_level == 1
            assert policy.require_payout_approval is True

        opened = await _patch_policy(client, {"per_transaction_limit": None})
        assert opened.status_code == 200, opened.text
        prepared = await plan("Pay Ada $20.")
        assert prepared["status"] == "pending_confirmation"
        confirmed = await client.post(f"/api/v1/agent/runs/{prepared['id']}/confirm")
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["status"] == "completed"
        assert await _count(PayoutRequest, PayoutRequest.workspace_id == workspace_id) == 1
        self_approved = await plan("Approve the payout to Ada.")
        assert self_approved["status"] == "needs_clarification"
        assert self_approved["error_code"] == "unsupported_instruction"
        assert self_approved["steps"] == []

        payout = await _approval_row(workspace_id)
        assert payout.status == "pending"
        async with factory() as session:
            request = await session.scalar(
                select(PayoutRequest).where(PayoutRequest.workspace_id == workspace_id)
            )
            assert request is not None
            payout_id = request.id
        approved = await client.post(f"/api/v1/payout-requests/{payout_id}/approve")
        assert approved.status_code == 200, approved.text
        assert (await _patch_policy(client, {"autonomy_level": 2})).status_code == 200
        resumed = await plan("Resume the payout to Ada after approval.")
        assert resumed["status"] == "completed"
        resume_result = resumed["steps"][0]["result"]
        assert resume_result["can_resume"] is True
        assert resume_result["execution"] == "not_attempted"
        assert resume_result["paypal_payout_batch_id"] is None

        async with factory() as session:
            request = await session.get(PayoutRequest, payout_id)
            assert request is not None
            request.amount = Decimal("75.00")
            await session.commit()
        changed = await plan("Resume the payout to Ada after approval.")
        assert changed["steps"][0]["result"]["can_resume"] is False
        assert "fresh approval" in changed["steps"][0]["result"]["reason"]
        assert await _count(PayoutRequest, PayoutRequest.workspace_id == workspace_id) == 1


async def _approval_row(workspace_id: uuid.UUID) -> Approval:
    factory = get_session_factory()
    async with factory() as session:
        approval = await session.scalar(select(Approval).where(Approval.workspace_id == workspace_id))
        assert approval is not None
        return approval
