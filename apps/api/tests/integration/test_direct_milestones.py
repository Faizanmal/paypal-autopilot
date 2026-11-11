import json
from decimal import Decimal

import httpx
import pytest
import respx

from app.modules.ai.providers.openai import OPENAI_ENDPOINT, OpenAIPlanner
from tests.integration.test_agent_runs import _client, _customer, _register
from tests.unit.test_direct_milestones import bulk_plan, milestone_rows
from tests.unit.test_planner_normalization import PROJECT


@pytest.mark.parametrize("explicit", [False, True])
async def test_exact_live_prompt_creates_three_direct_milestones(app, clean_db, monkeypatch, explicit):
    monkeypatch.setattr("app.modules.ai.service.get_planner", lambda _settings: OpenAIPlanner("mock-key"))
    async with await _client(app) as client:
        await _register(client, "milestones.qa@example.com", "Direct milestones QA")
        customer = await _customer(client)
        rows = milestone_rows() if explicit else None
        if rows:
            for row in rows:
                row.pop("currency_code", None)
        with respx.mock() as router:
            router.post(OPENAI_ENDPOINT).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "choices": [{"message": {"content": json.dumps(bulk_plan(rows))}}],
                    },
                )
            )
            preview = await client.post("/api/v1/agent/plans", json={"instruction": PROJECT})
        assert preview.status_code == 201, preview.text
        plan = preview.json()
        assert plan["status"] == "pending_confirmation"
        assert len(plan["steps"]) == 4
        assert [step["arguments"]["amount"] for step in plan["steps"][1:]] == ["1000.00"] * 3
        assert all(step["depends_on"] == [1] for step in plan["steps"][1:])
        assert (await client.get("/api/v1/projects")).json()["items"] == []
        confirmed = await client.post(f"/api/v1/agent/runs/{plan['id']}/confirm")
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["status"] == "completed"
        projects = (await client.get("/api/v1/projects")).json()["items"]
        assert len(projects) == 1
        project = projects[0]
        assert project["name"] == "Website Redesign"
        assert project["customer_id"] == customer["id"]
        detail = (await client.get(f"/api/v1/projects/{project['id']}")).json()
        assert len(detail["milestones"]) == 3
        assert [item["name"] for item in detail["milestones"]] == [f"Milestone {i}" for i in range(1, 4)]
        assert sum(Decimal(item["amount"]) for item in detail["milestones"]) == Decimal("3000.00")
        assert all(item["project_id"] == project["id"] for item in detail["milestones"])
        assert (await client.get("/api/v1/contracts")).json()["items"] == []


async def test_mismatched_sum_cannot_create_a_project(app, clean_db, monkeypatch):
    monkeypatch.setattr("app.modules.ai.service.get_planner", lambda _settings: OpenAIPlanner("mock-key"))
    rows = milestone_rows()
    rows[-1]["amount"] = "900.00"
    async with await _client(app) as client:
        await _register(client, "milestones.mismatch@example.com", "Mismatch QA")
        await _customer(client)
        with respx.mock() as router:
            router.post(OPENAI_ENDPOINT).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "choices": [{"message": {"content": json.dumps(bulk_plan(rows))}}],
                    },
                )
            )
            response = await client.post("/api/v1/agent/plans", json={"instruction": PROJECT})
        assert response.json()["status"] == "rejected", response.text
        assert response.json()["error_code"] == "invalid_plan"
        assert (await client.get("/api/v1/projects")).json()["items"] == []


async def test_groq_scalar_milestones_recover_missing_project_total(app, clean_db, monkeypatch):
    monkeypatch.setattr("app.modules.ai.service.get_planner", lambda _settings: OpenAIPlanner("mock-key"))
    plan = bulk_plan()
    plan["steps"][0]["arguments"].pop("amount")
    plan["steps"] = [plan["steps"][0]] + [
        {
            "sequence": index + 2,
            "action_type": "create_milestone",
            "summary": f"Create Milestone {index + 1}",
            "arguments": {"milestone_name": f"Milestone {index + 1}", "amount": 1000.0, "currency_code": "USD"},
            "depends_on": [1],
            "requires_approval": False,
            "read_only": False,
        }
        for index in range(3)
    ]
    async with await _client(app) as client:
        await _register(client, "milestones.groq@example.com", "Groq scalar milestones")
        customer = await _customer(client)
        with respx.mock() as router:
            router.post(OPENAI_ENDPOINT).mock(
                return_value=httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(plan)}}]})
            )
            preview = await client.post("/api/v1/agent/plans", json={"instruction": PROJECT})
        assert preview.status_code == 201, preview.text
        assert preview.json()["status"] == "pending_confirmation"
        assert preview.json()["steps"][0]["arguments"]["amount"] == "3000.00"
        confirmed = await client.post(f"/api/v1/agent/runs/{preview.json()['id']}/confirm")
        assert confirmed.status_code == 200, confirmed.text
        project = (await client.get("/api/v1/projects")).json()["items"][0]
        assert project["customer_id"] == customer["id"]
        detail = (await client.get(f"/api/v1/projects/{project['id']}")).json()
        assert len(detail["milestones"]) == 3
        assert sum(Decimal(item["amount"]) for item in detail["milestones"]) == Decimal("3000.00")
