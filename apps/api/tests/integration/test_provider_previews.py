import json

import httpx
import pytest
import respx

from app.modules.ai.providers.openai import OPENAI_ENDPOINT, OpenAIPlanner
from tests.integration.test_agent_runs import _client, _customer, _register
from tests.unit.test_planner_normalization import INVOICE, PROJECT, response_plan


@pytest.mark.parametrize("project", [False, True])
async def test_realistic_provider_output_reaches_an_inert_preview(app, clean_db, monkeypatch, project):
    monkeypatch.setattr("app.modules.ai.service.get_planner", lambda _settings: OpenAIPlanner("mock-key"))
    async with await _client(app) as client:
        await _register(client, "provider.preview@example.com", "Provider preview QA")
        await _customer(client)
        async with respx.mock() as router:
            router.post(OPENAI_ENDPOINT).mock(return_value=httpx.Response(200, json={
                "choices": [{"message": {"content": json.dumps(response_plan(project))}}],
            }))
            response = await client.post("/api/v1/agent/plans", json={"instruction": PROJECT if project else INVOICE})
        assert response.status_code == 201, response.text
        assert response.json()["status"] == "pending_confirmation"
        assert response.json()["error_code"] is None
        assert response.json()["provider"] == "openai"
        assert (await client.get("/api/v1/projects")).json()["items"] == []
        assert (await client.get("/api/v1/invoices")).json()["items"] == []
