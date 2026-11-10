from __future__ import annotations

import asyncio

from tests.integration.test_agent_runs import _client, _plan, _register


async def test_revision_is_inert_supersedes_old_preview_and_requires_confirmation(app, clean_db):
    async with await _client(app) as client, await _client(app) as other:
        await _register(client, "review.owner@example.com", "Review workspace")
        await _register(other, "review.other@example.com", "Other workspace")
        original = await _plan(client, "Create a $3,000 project with three payment milestones.")
        path = f"/api/v1/agent/runs/{original['id']}/revise"
        arguments = {str(step["sequence"]): dict(step["arguments"]) for step in original["steps"]}
        for fields in arguments.values():
            fields["amount"] = "6000.00" if fields["amount"] == "3000.00" else "2000.00"
        body = {"instruction": "Create a $6,000 project with three payment milestones.", "arguments": arguments}

        assert (await other.post(path, json=body)).status_code == 404
        invalid = await client.post(path, json={**body, "instruction": original["instruction"]})
        assert invalid.status_code == 422
        assert (await client.get(f"/api/v1/agent/runs/{original['id']}")).json()["status"] == "pending_confirmation"
        forged = {**arguments, "99": {"workspace_id": "foreign"}}
        assert (await client.post(path, json={**body, "arguments": forged})).status_code == 422
        edited = await client.post(path, json=body)
        assert edited.status_code == 201, edited.text
        revised = edited.json()
        assert revised["id"] != original["id"]
        assert revised["status"] == "pending_confirmation"
        assert revised["provider_label"] == "User-reviewed plan"
        assert "6000.00" in revised["steps"][0]["summary"]
        assert (await client.get("/api/v1/projects")).json()["items"] == []
        assert (await client.post(f"/api/v1/agent/runs/{original['id']}/confirm")).status_code == 409
        assert (await client.post(path, json=body)).status_code == 409

        confirmed = await client.post(f"/api/v1/agent/runs/{revised['id']}/confirm")
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["status"] == "completed"
        projects = (await client.get("/api/v1/projects")).json()["items"]
        assert len(projects) == 1
        assert projects[0]["total_amount"] == "6000.00"
        detail = (await client.get(f"/api/v1/projects/{projects[0]['id']}")).json()
        assert [milestone["amount"] for milestone in detail["milestones"]] == ["2000.00"] * 3
        assert (await client.post(f"/api/v1/agent/runs/{revised['id']}/revise", json=body)).status_code == 409


async def test_concurrent_confirmations_materialize_once(app, clean_db):
    async with await _client(app) as client:
        await _register(client, "concurrent.review@example.com", "Confirmation workspace")
        original = await _plan(client, "Create a $3,000 project with three payment milestones.")
        path = f"/api/v1/agent/runs/{original['id']}/confirm"
        results = await asyncio.gather(client.post(path), client.post(path))
        assert sorted(result.status_code for result in results) == [200, 409]
        assert len((await client.get("/api/v1/projects")).json()["items"]) == 1
