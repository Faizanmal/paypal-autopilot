"""Offline test execution must not inherit credentials or send real HTTP."""

import httpx
import pytest

from app.core.config import Settings


def test_missing_credentials_do_not_fall_back_to_dotenv(monkeypatch):
    monkeypatch.delenv("PAYPAL_CLIENT_ID", raising=False)
    monkeypatch.delenv("PAYPAL_CLIENT_SECRET", raising=False)
    assert Settings().paypal_configured is False


@pytest.mark.asyncio
async def test_unmocked_http_is_blocked():
    async with httpx.AsyncClient() as client:
        with pytest.raises(AssertionError, match="Unmocked external HTTP is disabled"):
            await client.get("https://api-m.sandbox.paypal.com/")
