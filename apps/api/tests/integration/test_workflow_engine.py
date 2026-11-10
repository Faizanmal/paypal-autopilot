"""Invoice, reminder, and payout orchestration survives restarts and duplicate events."""

from __future__ import annotations

import json
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
from app.modules.ai.models import AgentAction, AgentRun
from app.modules.autopilot.models import Invoice, ScheduledAction, WebhookEvent
from app.modules.autopilot.reminders import INVOICE_REMINDER_JOB, run_due_invoice_checks, run_due_invoice_reminders
from app.modules.spendpilot.models import Approval, PayoutRequest
from app.modules.workflows.engine import reconcile_open_invoices, resume_interrupted_runs
from app.modules.workflows.models import Workflow, WorkflowStep

BASE = "https://api-m.sandbox.paypal.com"
SCOPE = "https://uri.paypal.com/services/invoicing/invoices/readwrite"
INSTRUCTION = (
    "Invoice Acme $100 for October. Remind Acme in seven days. "
    "Pay my designer $40 after the client payment clears."
)


class AcceptWebhook:
    async def verify(self, raw_body: bytes, headers: dict[str, str]) -> None:
        return None


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


def _token() -> httpx.Response:
    return httpx.Response(200, json={"access_token": "token-abc", "expires_in": 3600, "scope": SCOPE})


async def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


async def _register(client: AsyncClient) -> dict:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "ada.workflow@example.com",
            "password": "correct-horse-battery",
            "full_name": "Ada Lovelace",
            "workspace_name": "Analytical Engines",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _count(model) -> int:
    factory = get_session_factory()
    async with factory() as session:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def _start(app, client: AsyncClient) -> dict:
    app.state.paypal_webhook_verifier = AcceptWebhook()
    created = await _register(client)
    customer = await client.post("/api/v1/customers", json={"name": "Acme", "email": "billing@acme.example"})
    assert customer.status_code == 201, customer.text
    contractor = await client.post(
        "/api/v1/contractors",
        json={"name": "Designer", "email": "designer@example.com", "paypal_email": "designer.pay@example.com"},
    )
    assert contractor.status_code == 201, contractor.text
    planned = await client.post("/api/v1/agent/plans", json={"instruction": INSTRUCTION})
    assert planned.status_code == 201, planned.text
    assert planned.json()["status"] == "pending_confirmation"
    async with respx.mock(assert_all_called=False) as paypal:
        paypal.post(f"{BASE}/v1/oauth2/token").mock(return_value=_token())
        paypal.post(f"{BASE}/v2/invoicing/invoices").mock(
            return_value=httpx.Response(201, json={"id": "INV2-FLOW", "status": "DRAFT"})
        )
        confirmed = await client.post(f"/api/v1/agent/runs/{planned.json()['id']}/confirm")
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["status"] == "waiting"
    assert [step["status"] for step in body["steps"]] == ["succeeded", "succeeded", "waiting", "waiting"]
    return {"run_id": body["id"], "user_id": created["user"]["id"], "workspace_id": created["workspace"]["id"]}


async def _post_event(
    client: AsyncClient, event_id: str, event_type: str, status: str, paypal_status: str
) -> httpx.Response:
    async with respx.mock(assert_all_called=False) as paypal:
        paypal.post(f"{BASE}/v1/oauth2/token").mock(return_value=_token())
        paypal.get(f"{BASE}/v2/invoicing/invoices/INV2-FLOW").mock(
            return_value=httpx.Response(200, json={"id": "INV2-FLOW", "status": paypal_status})
        )
        return await client.post(
            "/api/v1/webhooks/paypal",
            content=json.dumps(
                {"id": event_id, "event_type": event_type, "resource": {"id": "INV2-FLOW", "status": status}}
            ),
            headers={"content-type": "application/json"},
        )


@pytest.mark.asyncio
async def test_payment_to_payout_survives_restart_and_duplicate_events(app, clean_db, paypal_env):
    async with await _client(app) as client:
        started = await _start(app, client)
        assert await _count(Invoice) == 1
        assert await _count(PayoutRequest) == 0
        assert await _count(Approval) == 0

        factory = get_session_factory()
        async with factory() as session:
            run = await session.get(AgentRun, uuid.UUID(started["run_id"]))
            assert run is not None
            run.status = "executing"
            await session.commit()
        async with factory() as session:
            await resume_interrupted_runs(session)
        recovered = await client.get(f"/api/v1/agent/runs/{started['run_id']}")
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["status"] == "waiting"
        assert await _count(PayoutRequest) == 0

        async with factory() as session:
            reminder = await session.scalar(
                select(ScheduledAction).where(ScheduledAction.job_type == INVOICE_REMINDER_JOB)
            )
            assert reminder is not None
            assert reminder.status == "pending"
            counts = await run_due_invoice_reminders(session)
        assert counts["attempted"] == 0

        paid = await _post_event(client, "WH-FLOW-PAID", "INVOICING.INVOICE.PAID", "PAID", "PAID")
        assert paid.status_code == 200, paid.text
        assert paid.json()["status"] == "processed"
        duplicate = await _post_event(client, "WH-FLOW-PAID", "INVOICING.INVOICE.PAID", "PAID", "PAID")
        assert duplicate.status_code == 200, duplicate.text
        assert duplicate.json()["status"] == "duplicate"

        async with factory() as session:
            await run_due_invoice_reminders(session)
            await resume_interrupted_runs(session)
        replay = await _post_event(client, "WH-FLOW-PAID", "INVOICING.INVOICE.PAID", "PAID", "PAID")
        assert replay.json()["status"] == "duplicate"

        finished = await client.get(f"/api/v1/agent/runs/{started['run_id']}")
        body = finished.json()
        assert body["status"] == "completed"
        assert body["steps"][2]["result"]["execution"] == "not_attempted"
        assert body["steps"][2]["result"]["paypal_payout_batch_id"] is None
        assert await _count(Invoice) == 1
        assert await _count(PayoutRequest) == 1
        assert await _count(Approval) == 1
        async with factory() as session:
            invoice = await session.scalar(select(Invoice))
            reminder = await session.scalar(
                select(ScheduledAction).where(ScheduledAction.job_type == INVOICE_REMINDER_JOB)
            )
            step = await session.scalar(select(WorkflowStep).where(WorkflowStep.step_type == "draft_invoice"))
            workflow = await session.scalar(select(Workflow))
            assert invoice is not None and invoice.status == "paid"
            assert reminder is not None and reminder.status == "cancelled"
            assert step is not None and step.provider_reference == "INV2-FLOW"
            assert step.attempts >= 1
            assert workflow is not None and workflow.status == "completed"


@pytest.mark.asyncio
async def test_partial_workflow_waits_without_creating_a_payout(app, clean_db, paypal_env):
    async with await _client(app) as client:
        started = await _start(app, client)
        factory = get_session_factory()
        async with factory() as session:
            workflow = await session.scalar(select(Workflow))
            payout = await session.scalar(select(WorkflowStep).where(WorkflowStep.step_type == "prepare_payout"))
            reminder = await session.scalar(select(WorkflowStep).where(WorkflowStep.step_type == "schedule_reminder"))
            assert workflow is not None and workflow.status == "waiting"
            assert payout is not None and payout.waiting_for == "invoice.paid"
            assert payout.condition == "client payment cleared"
            assert reminder is not None and reminder.condition == "invoice remains unpaid"
            assert reminder.run_after is not None
        assert started["run_id"]
        assert await _count(PayoutRequest) == 0


@pytest.mark.asyncio
async def test_worker_crash_does_not_send_the_reminder_twice(app, clean_db, paypal_env, monkeypatch):
    async with await _client(app) as client:
        created = await _register(client)
        customer = await client.post("/api/v1/customers", json={"name": "Acme", "email": "billing@acme.example"})
        factory = get_session_factory()
        async with factory() as session:
            invoice = Invoice(
                workspace_id=uuid.UUID(created["workspace"]["id"]),
                customer_id=uuid.UUID(customer.json()["id"]),
                currency_code="USD",
                amount=Decimal("100.00"),
                status="sent",
                paypal_invoice_id="INV-CRASH",
            )
            session.add(invoice)
            await session.flush()
            session.add(
                ScheduledAction(
                    workspace_id=invoice.workspace_id,
                    job_type=INVOICE_REMINDER_JOB,
                    run_after=datetime.now(UTC) - timedelta(minutes=1),
                    status="pending",
                    payload={"actor_user_id": created["user"]["id"], "invoice_id": str(invoice.id)},
                    related_entity_type="invoice",
                    related_entity_id=invoice.id,
                    idempotency_key="crash-reminder",
                )
            )
            await session.commit()

        async def _crash(_session, _row):
            raise RuntimeError("worker crashed")

        monkeypatch.setattr("app.modules.autopilot.reminders._run_one", _crash)
        async with factory() as session:
            with pytest.raises(RuntimeError, match="worker crashed"):
                await run_due_invoice_reminders(session)
        monkeypatch.undo()
        async with factory() as session:
            row = await session.scalar(select(ScheduledAction))
            assert row is not None and row.status == "running"

        async with respx.mock(assert_all_called=False) as paypal:
            paypal.post(f"{BASE}/v1/oauth2/token").mock(return_value=_token())
            remind = paypal.post(f"{BASE}/v2/invoicing/invoices/INV-CRASH/remind").mock(
                return_value=httpx.Response(204)
            )
            async with factory() as session:
                skipped = await run_due_invoice_reminders(session)
            assert skipped["attempted"] == 0
            assert remind.call_count == 0
            async with factory() as session:
                sent = await run_due_invoice_reminders(session, stale_after=timedelta(0))
            assert sent["sent"] == 1
            assert remind.call_count == 1
            async with factory() as session:
                again = await run_due_invoice_reminders(session, stale_after=timedelta(0))
            assert again["attempted"] == 0
            assert remind.call_count == 1


@pytest.mark.asyncio
async def test_reminder_timeout_is_retried(app, clean_db, paypal_env):
    async with await _client(app) as client:
        created = await _register(client)
        customer = await client.post("/api/v1/customers", json={"name": "Acme", "email": "billing@acme.example"})
        factory = get_session_factory()
        async with factory() as session:
            invoice = Invoice(
                workspace_id=uuid.UUID(created["workspace"]["id"]),
                customer_id=uuid.UUID(customer.json()["id"]),
                currency_code="USD",
                amount=Decimal("100.00"),
                status="sent",
                paypal_invoice_id="INV-TIMEOUT",
            )
            session.add(invoice)
            await session.flush()
            session.add(
                ScheduledAction(
                    workspace_id=invoice.workspace_id,
                    job_type=INVOICE_REMINDER_JOB,
                    run_after=datetime.now(UTC) - timedelta(minutes=1),
                    status="pending",
                    payload={"actor_user_id": created["user"]["id"]},
                    related_entity_type="invoice",
                    related_entity_id=invoice.id,
                    idempotency_key="timeout-reminder",
                )
            )
            await session.commit()
        calls = {"n": 0}

        def _flaky(_request):
            calls["n"] += 1
            if calls["n"] <= 3:
                raise httpx.TimeoutException("timed out")
            return httpx.Response(204)

        async with respx.mock(assert_all_called=False) as paypal:
            paypal.post(f"{BASE}/v1/oauth2/token").mock(return_value=_token())
            paypal.post(f"{BASE}/v2/invoicing/invoices/INV-TIMEOUT/remind").mock(side_effect=_flaky)
            async with factory() as session:
                failed = await run_due_invoice_reminders(session)
            assert failed["failed"] == 1
            async with factory() as session:
                retried = await run_due_invoice_reminders(session)
            assert retried["sent"] == 1
        assert calls["n"] == 4
        async with factory() as session:
            row = await session.scalar(select(ScheduledAction))
            assert row is not None and row.status == "succeeded"


@pytest.mark.asyncio
async def test_out_of_order_event_and_provider_disagreement(app, clean_db, paypal_env):
    async with await _client(app) as client:
        await _start(app, client)
        sent = await client.post(
            "/api/v1/webhooks/paypal",
            content=json.dumps(
                {
                    "id": "WH-FLOW-SENT",
                    "event_type": "INVOICING.INVOICE.SENT",
                    "resource": {"id": "INV2-FLOW", "status": "SENT"},
                }
            ),
            headers={"content-type": "application/json"},
        )
        assert sent.status_code == 200, sent.text
        disagreed = await _post_event(client, "WH-FLOW-LIE", "INVOICING.INVOICE.PAID", "PAID", "SENT")
        assert disagreed.status_code == 200, disagreed.text
        factory = get_session_factory()
        async with factory() as session:
            invoice = await session.scalar(select(Invoice))
            event = await session.scalar(select(WebhookEvent).where(WebhookEvent.event_id == "WH-FLOW-LIE"))
            assert invoice is not None and invoice.status == "sent"
            assert event is not None and event.last_error == "provider_not_paid"
        assert await _count(PayoutRequest) == 0

        paid = await _post_event(client, "WH-FLOW-PAID", "INVOICING.INVOICE.PAID", "PAID", "PAID")
        assert paid.status_code == 200, paid.text
        late = await client.post(
            "/api/v1/webhooks/paypal",
            content=json.dumps(
                {
                    "id": "WH-FLOW-SENT-LATE",
                    "event_type": "INVOICING.INVOICE.SENT",
                    "resource": {"id": "INV2-FLOW", "status": "SENT"},
                }
            ),
            headers={"content-type": "application/json"},
        )
        assert late.status_code == 200, late.text
        async with factory() as session:
            invoice = await session.scalar(select(Invoice))
            assert invoice is not None and invoice.status == "paid"
        assert await _count(PayoutRequest) == 1
        assert await _count(Approval) == 1


@pytest.mark.asyncio
async def test_missing_webhook_is_recovered_by_reconciliation(app, clean_db, paypal_env):
    async with await _client(app) as client:
        await _start(app, client)
        factory = get_session_factory()
        async with respx.mock(assert_all_called=False) as paypal:
            paypal.post(f"{BASE}/v1/oauth2/token").mock(return_value=_token())
            paypal.get(f"{BASE}/v2/invoicing/invoices/INV2-FLOW").mock(
                return_value=httpx.Response(503, json={"name": "SERVICE_UNAVAILABLE", "message": "down"})
            )
            async with factory() as session:
                first = await reconcile_open_invoices(session)
            assert first["unavailable"] == 1
            assert await _count(PayoutRequest) == 0
            async with factory() as session:
                invoice = await session.scalar(select(Invoice))
                assert invoice is not None and invoice.status == "draft"

        async with respx.mock(assert_all_called=False) as paypal:
            paypal.post(f"{BASE}/v1/oauth2/token").mock(return_value=_token())
            paypal.get(f"{BASE}/v2/invoicing/invoices/INV2-FLOW").mock(
                return_value=httpx.Response(200, json={"id": "INV2-FLOW", "status": "PAID"})
            )
            async with factory() as session:
                second = await reconcile_open_invoices(session)
            assert second["paid"] == 1
            async with factory() as session:
                third = await reconcile_open_invoices(session)
            assert third["checked"] == 0
        assert await _count(PayoutRequest) == 1
        assert await _count(Approval) == 1
        async with factory() as session:
            reminder = await session.scalar(
                select(ScheduledAction).where(ScheduledAction.job_type == INVOICE_REMINDER_JOB)
            )
            invoice = await session.scalar(select(Invoice))
            assert invoice is not None and invoice.status == "paid"
            assert reminder is not None and reminder.status == "cancelled"


@pytest.mark.asyncio
async def test_cancelled_workflow_does_not_prepare_a_payout(app, clean_db, paypal_env):
    async with await _client(app) as client:
        started = await _start(app, client)
        cancelled = await client.post(f"/api/v1/agent/runs/{started['run_id']}/cancel")
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"
        paid = await _post_event(client, "WH-FLOW-CANCELLED", "INVOICING.INVOICE.PAID", "PAID", "PAID")
        assert paid.status_code == 200, paid.text
        assert await _count(PayoutRequest) == 0
        factory = get_session_factory()
        async with factory() as session:
            invoice = await session.scalar(select(Invoice))
            reminder = await session.scalar(
                select(ScheduledAction).where(ScheduledAction.job_type == INVOICE_REMINDER_JOB)
            )
            assert invoice is not None and invoice.status == "paid"
            assert reminder is not None and reminder.status == "cancelled"


@pytest.mark.asyncio
async def test_expired_approval_is_not_reused(app, clean_db, paypal_env):
    async with await _client(app) as client:
        started = await _start(app, client)
        paid = await _post_event(client, "WH-FLOW-EXPIRE", "INVOICING.INVOICE.PAID", "PAID", "PAID")
        assert paid.status_code == 200, paid.text
        factory = get_session_factory()
        async with factory() as session:
            approval = await session.scalar(select(Approval))
            payout = await session.scalar(select(PayoutRequest))
            assert approval is not None and payout is not None
            approval.expires_at = datetime.now(UTC) - timedelta(minutes=1)
            payout_id = payout.id
            await session.commit()
        expired = await client.post(f"/api/v1/payout-requests/{payout_id}/expire")
        assert expired.status_code == 200, expired.text
        assert expired.json()["status"] == "canceled"
        assert expired.json()["paypal_payout_batch_id"] is None
        execute = await client.post(f"/api/v1/payout-requests/{payout_id}/execute")
        assert execute.status_code >= 400
        retry = await client.post(f"/api/v1/agent/runs/{started['run_id']}/retry")
        assert retry.status_code == 409
        assert await _count(PayoutRequest) == 1
        async with factory() as session:
            approval = await session.scalar(select(Approval))
            assert approval is not None and approval.status == "expired"


@pytest.mark.asyncio
async def test_due_and_overdue_notices_are_recorded_once(app, clean_db, paypal_env):
    async with await _client(app) as client:
        created = await _register(client)
        customer = await client.post("/api/v1/customers", json={"name": "Acme", "email": "billing@acme.example"})
        factory = get_session_factory()
        async with factory() as session:
            session.add(
                Invoice(
                    workspace_id=uuid.UUID(created["workspace"]["id"]),
                    customer_id=uuid.UUID(customer.json()["id"]),
                    currency_code="USD",
                    amount=Decimal("80.00"),
                    status="sent",
                    due_at=datetime.now(UTC) - timedelta(days=3),
                    paypal_invoice_id="INV-DUE",
                )
            )
            await session.commit()
            first = await run_due_invoice_checks(session)
            second = await run_due_invoice_checks(session)
        assert first["recorded"] == 2
        assert second["recorded"] == 0
        async with factory() as session:
            notices = list(
                await session.scalars(
                    select(AuditLog).where(AuditLog.action.in_(("invoice.due_reached", "invoice.overdue_notice")))
                )
            )
            jobs = list(await session.scalars(select(ScheduledAction)))
        assert {row.action for row in notices} == {"invoice.due_reached", "invoice.overdue_notice"}
        assert {row.status for row in jobs} == {"succeeded"}
        assert len(jobs) == 2


@pytest.mark.asyncio
async def test_running_payout_step_retries_without_a_second_intent(app, clean_db, paypal_env):
    async with await _client(app) as client:
        started = await _start(app, client)
        paid = await _post_event(client, "WH-FLOW-RETRY", "INVOICING.INVOICE.PAID", "PAID", "PAID")
        assert paid.status_code == 200, paid.text
        assert await _count(PayoutRequest) == 1
        factory = get_session_factory()
        async with factory() as session:
            run = await session.get(AgentRun, uuid.UUID(started["run_id"]))
            action = await session.scalar(select(AgentAction).where(AgentAction.action_type == "prepare_payout"))
            assert run is not None and action is not None
            run.status = "executing"
            action.status = "running"
            await session.commit()
        async with factory() as session:
            await resume_interrupted_runs(session)
        async with factory() as session:
            await resume_interrupted_runs(session)
        assert await _count(PayoutRequest) == 1
        assert await _count(Approval) == 1
