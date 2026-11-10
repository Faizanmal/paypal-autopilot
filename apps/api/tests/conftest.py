from __future__ import annotations

import os

import httpcore
import pytest
from httpx import ASGITransport, AsyncClient

# Ensure sandbox-safe defaults for the test environment before any app
# module (which reads settings at import time via get_settings()) is
# imported.
# Force the test database. Never point this at the development database:
# integration tests truncate every table.
os.environ["APP_ENV"] = "test"
os.environ["PAYPAL_ENV"] = "sandbox"
os.environ["AI_PROVIDER"] = "fallback_rules"
os.environ["GROQ_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["RENDER_API_KEY"] = ""
os.environ["RENDER_REPORT_TASK"] = ""
os.environ["RENDER_USE_LOCAL_DEV"] = "false"
os.environ["RENDER_LOCAL_DEV_URL"] = ""
for _credential in (
    "PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_WEBHOOK_ID", "PAYPAL_API_BASE_URL",
    "PAYPAL_SANDBOX_BUSINESS_EMAIL", "PAYPAL_SANDBOX_BUYER_EMAIL",
):
    os.environ[_credential] = ""
os.environ["PAYPAL_PAYOUTS_EXECUTION"] = "false"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["DATABASE_URL"] = (
    "postgresql+asyncpg://autopilot:autopilot@localhost:5433/autopilot_test"
)
os.environ["DATABASE_URL_SYNC"] = (
    "postgresql+psycopg://autopilot:autopilot@localhost:5433/autopilot_test"
)

from app.core.config import Settings, get_settings  # noqa: E402

# Test cases that delete environment variables must never fall back to a
# developer's .env credentials. Mocked tests supply their own explicit values.
Settings.model_config["env_file"] = None
get_settings.cache_clear()

from app.main import create_app  # noqa: E402


@pytest.fixture(autouse=True)
def block_unmocked_http(monkeypatch):
    async def deny_async(self, host, port, *args, **kwargs):
        raise AssertionError(f"Unmocked external HTTP is disabled in tests: {host}:{port}")

    def deny_sync(self, host, port, *args, **kwargs):
        raise AssertionError(f"Unmocked external HTTP is disabled in tests: {host}:{port}")

    # Block sockets below HTTP mocking, so respx/MockTransport remain usable.
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", deny_async)
    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", deny_sync)


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c
