"""Smoke test: the FastAPI app boots and reports sandbox mode.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_health_ok(client):
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["paypal_env"] == "sandbox"
