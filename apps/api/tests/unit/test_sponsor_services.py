from dataclasses import asdict
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

from app.core.config import get_settings
from app.core.errors import ValidationFailedError
from app.modules.ai import studio
from app.modules.finance import reports
from app.modules.finance.engine import evaluate
from app.modules.finance.schemas import FinanceSnapshotOut


def cash_snapshot():
    data = asdict(evaluate(invoices=[], payments=[], milestones=[], payouts=[], now=datetime.now(UTC)))
    data.update(outstanding_receivables="300.00", overdue_receivables="100.00", planned_expenses="0.30")
    return FinanceSnapshotOut.model_validate(data)


def turn(**values):
    return studio.StudioTurn(
        input=[
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "text", "text": "Explain report fields"},
                ],
            }
        ],
        **values,
    )


def test_report_exact_amounts_and_unknown_opening_balance():
    result = reports.build_cash_report(cash_snapshot().model_dump())
    assert result["overdue_percent"] == "33.33"
    assert result["planned_expenses"] == "0.30"
    assert result["projected_available"] is None


def test_report_zero_receivables():
    data = cash_snapshot().model_dump()
    data.update(outstanding_receivables="0.00", overdue_receivables="0.00")
    assert reports.build_cash_report(data)["overdue_percent"] == "0.00"


async def test_report_missing_configuration_makes_no_provider_request():
    with pytest.raises(studio.IntegrationUnavailable):
        await reports.run_cash_report(cash_snapshot())


@pytest.mark.parametrize("mode", ["completed", "mismatch", "failed", "timeout"])
async def test_render_result_is_validated_and_client_closed(monkeypatch, mode):
    monkeypatch.setenv("RENDER_API_KEY", "fake-render-key")
    monkeypatch.setenv("RENDER_REPORT_TASK", "test/cash-risk-report")
    get_settings.cache_clear()
    snapshot = cash_snapshot()
    report = reports.build_cash_report(snapshot.model_dump())
    if mode == "mismatch":
        report["currency"] = "EUR"
    run = AsyncMock(return_value=SimpleNamespace(id="run-test"))
    get_run = AsyncMock(
        side_effect=[
            SimpleNamespace(status=SimpleNamespace(value="running")),
            SimpleNamespace(
                id="run-test",
                results=[report],
                status=SimpleNamespace(value="failed" if mode == "failed" else "completed"),
            ),
        ]
    )
    if mode == "timeout":
        run.side_effect = TimeoutError
    monkeypatch.setattr(reports.asyncio, "sleep", AsyncMock())
    context = MagicMock()
    context.__aenter__ = AsyncMock()
    context.__aexit__ = AsyncMock(return_value=False)
    client = SimpleNamespace(
        client=SimpleNamespace(internal=SimpleNamespace(get_async_httpx_client=lambda: context)),
        workflows=SimpleNamespace(start_task=run, get_task_run=get_run),
    )
    monkeypatch.setattr(reports, "RenderAsync", lambda **kwargs: client)
    try:
        if mode != "completed":
            with pytest.raises(studio.IntegrationUnavailable):
                await reports.run_cash_report(snapshot)
        else:
            assert (await reports.run_cash_report(snapshot))["run_id"] == "run-test"
        run.assert_awaited_once_with("test/cash-risk-report", [snapshot.model_dump(mode="json")])
        context.__aexit__.assert_awaited_once()
    finally:
        get_settings.cache_clear()


def test_studio_request_wraps_union_tools_and_keeps_model_server_side():
    request = studio.provider_request(
        turn(
            tools=[
                {
                    "name": "changeReport",
                    "parameters": {
                        "anyOf": [
                            {"type": "object", "properties": {"title": {"type": "string"}}},
                        ]
                    },
                }
            ]
        )
    )
    assert request["store"] is False
    assert request["tools"][0]["parameters"]["type"] == "object"
    assert "payload" in request["tools"][0]["parameters"]["properties"]
    assert "financial records" in request["instructions"]


@pytest.mark.parametrize("tool_kind", ["server", "provided"])
def test_studio_rejects_nonlocal_tools(tool_kind):
    with pytest.raises(ValidationFailedError):
        studio.provider_request(turn(tools=[{"name": "remote", "kind": tool_kind, "parameters": {}}]))


def test_studio_rejects_oversized_context():
    request = turn()
    request.input[0]["content"][0]["text"] = "a" * 256001
    with pytest.raises(ValidationFailedError):
        studio.provider_request(request)


async def test_studio_missing_key_is_explicit():
    with pytest.raises(studio.IntegrationUnavailable, match="OPENAI_API_KEY"):
        await studio.execute_turn(turn())


@respx.mock
async def test_studio_tool_roundtrip_and_provider_error_redaction(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-ai-key")
    get_settings.cache_clear()
    route = respx.post("https://api.openai.com/v1/responses")
    route.mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "resp-test",
                "status": "completed",
                "output": [
                    {
                        "id": "fc-test",
                        "type": "function_call",
                        "call_id": "call-test",
                        "name": "changeReport",
                        "arguments": '{"payload":{"title":"Overdue"}}',
                    },
                ],
            },
        )
    )
    try:
        result = await studio.execute_turn(turn(tools=[{"name": "changeReport", "parameters": {"anyOf": []}}]))
        assert result["output"][0]["arguments"] == '{"title": "Overdue"}'
        assert result["output"][0]["callId"] == "call-test"
        route.mock(return_value=httpx.Response(429, json={"error": "fake-ai-key private debug"}))
        with pytest.raises(studio.IntegrationUnavailable) as error:
            await studio.execute_turn(turn())
        assert "fake-ai-key" not in str(error.value)
    finally:
        get_settings.cache_clear()


async def test_sponsor_endpoints_require_authentication(client):
    assert (await client.post("/api/v1/studio/turn", json=turn().model_dump())).status_code == 401
    assert (await client.post("/api/v1/finance/background-report")).status_code == 401


@pytest.mark.parametrize("count, expected", [(1, None), (121, 429)])
async def test_report_usage_limit_is_shared_and_atomic(monkeypatch, count, expected):
    redis = MagicMock()
    redis.eval = AsyncMock(return_value=count)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=redis)
    context.__aexit__ = AsyncMock()
    monkeypatch.setattr(studio.Redis, "from_url", lambda _: context)
    if expected:
        with pytest.raises(studio.AppError) as error:
            await studio.limit_usage("workspace-a", "studio", 120)
        assert error.value.status_code == expected
    else:
        await studio.limit_usage("workspace-a", "studio", 120)
    args = redis.eval.await_args.args
    assert "EXPIRE" in args[0]
    assert "workspace-a" in args[2]


async def test_report_limiter_fails_closed(monkeypatch):
    monkeypatch.setattr(studio.Redis, "from_url", MagicMock(side_effect=OSError("private details")))
    with pytest.raises(studio.IntegrationUnavailable) as error:
        await studio.limit_usage("workspace-a", "studio", 120)
    assert "private details" not in str(error.value)


@respx.mock
async def test_studio_surfaces_refusals_and_rejects_empty_success(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-ai-key")
    get_settings.cache_clear()
    route = respx.post("https://api.openai.com/v1/responses")
    try:
        route.mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "r",
                    "status": "completed",
                    "output": [
                        {
                            "id": "m",
                            "type": "message",
                            "content": [{"type": "refusal", "refusal": "I cannot do that."}],
                        }
                    ],
                },
            )
        )
        result = await studio.execute_turn(turn())
        assert result["output"][0]["content"][0]["text"] == "I cannot do that."
        route.mock(return_value=httpx.Response(200, json={"id": "r", "status": "completed", "output": []}))
        with pytest.raises(studio.IntegrationUnavailable):
            await studio.execute_turn(turn())
    finally:
        get_settings.cache_clear()


async def test_production_rejects_local_render_task_server(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("RENDER_USE_LOCAL_DEV", "true")
    monkeypatch.setenv("RENDER_REPORT_TASK", "local/cash-risk-report")
    get_settings.cache_clear()
    try:
        with pytest.raises(studio.IntegrationUnavailable):
            await reports.run_cash_report(cash_snapshot())
    finally:
        get_settings.cache_clear()


async def test_background_report_uses_authenticated_workspace(client, app, monkeypatch):
    from app.api.deps import current_principal
    from app.modules.finance import router

    principal = SimpleNamespace(workspace_id="workspace-a")
    app.dependency_overrides[current_principal] = lambda: principal
    snapshot = AsyncMock(return_value=cash_snapshot())
    run = AsyncMock(return_value={"run_id": "qa-run", "report": {}})
    monkeypatch.setattr(router, "snapshot", snapshot)
    monkeypatch.setattr(router, "run_cash_report", run)
    monkeypatch.setattr(router, "limit_usage", AsyncMock())
    try:
        response = await client.post("/api/v1/finance/background-report", json={"workspace_id": "workspace-b"})
        assert response.status_code == 200
        assert snapshot.await_args.args[1] is principal
        run.assert_awaited_once_with(snapshot.return_value)
    finally:
        app.dependency_overrides.clear()
