"""Sandbox calls are skipped until real credentials are present.

A passing mocked test is not a verified sandbox capability.
"""

from __future__ import annotations

import os

import pytest

_HAS_SANDBOX_CREDENTIALS = bool(os.environ.get("PAYPAL_CLIENT_ID") and os.environ.get("PAYPAL_CLIENT_SECRET"))

pytestmark = pytest.mark.skipif(
    not _HAS_SANDBOX_CREDENTIALS,
    reason="PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET are not configured; live sandbox checks were not run.",
)


@pytest.mark.asyncio
async def test_live_sandbox_token_and_read_only_diagnostics():
    from app.core.config import get_settings
    from app.integrations.paypal.client import PayPalClient, reset_paypal_client
    from app.integrations.paypal.diagnostics import build_capability_report

    get_settings.cache_clear()
    reset_paypal_client()
    settings = get_settings()
    client = PayPalClient(settings, use_redis=False)
    try:
        report = await build_capability_report(settings, client)
    finally:
        await client.aclose()
    assert report.credentials_configured is True
    auth = next(item for item in report.checks if item.name == "authentication")
    assert auth.status == "available"
