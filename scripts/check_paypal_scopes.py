"""Print live sandbox OAuth scopes and whether the demo Features are enabled.

Usage (from repo root or apps/api):

    cd apps/api
    uv run python ../../scripts/check_paypal_scopes.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps" / "api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))

from app.core.config import get_settings  # noqa: E402
from app.integrations.paypal.capability import (  # noqa: E402
    INVOICING_SCOPES,
    ORDERS_SCOPES,
    PAYOUTS_SCOPE,
)
from app.integrations.paypal.client import PayPalClient  # noqa: E402


async def main() -> int:
    settings = get_settings()
    if not settings.paypal_configured:
        print("FAIL: PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET are not set.")
        return 1

    client = PayPalClient(settings)
    try:
        token = await client.access_token(force_refresh=True)
    finally:
        await client.aclose()

    print(f"paypal_env={settings.paypal_env.value}")
    print(f"base_url={settings.paypal_base_url}")
    print(f"scope_count={len(token.scopes)}")
    for scope in sorted(token.scopes):
        print(f"  {scope}")

    invoicing = bool(token.scopes & INVOICING_SCOPES)
    orders = bool(token.scopes & ORDERS_SCOPES)
    payouts = PAYOUTS_SCOPE in token.scopes
    print("---")
    print(f"invoicing={'PASS' if invoicing else 'FAIL'}")
    print(f"orders={'PASS' if orders else 'FAIL'}")
    print(f"payouts={'PASS' if payouts else 'FAIL'}")
    if not invoicing:
        print(
            "Enable Invoicing under PayPal Developer → Apps & Credentials → "
            "Sandbox app → Features, save, then re-run this script."
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
