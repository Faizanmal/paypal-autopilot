"""Check configured sandbox authentication and AI planning without executing a workflow.

Run from apps/api: .venv/Scripts/python ../../scripts/check_integrations.py --ai
The optional AI check makes one planning request (provider charges may apply).
No invoice, payout, database write, or workflow execution is performed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.core.config import PayPalEnv, get_settings  # noqa: E402
from app.integrations.paypal.capability import (  # noqa: E402
    INVOICING_SCOPES,
    ORDERS_SCOPES,
    PAYOUTS_SCOPE,
)
from app.integrations.paypal.client import PayPalClient  # noqa: E402
from app.integrations.paypal.errors import PayPalError  # noqa: E402
from app.modules.ai.providers import get_planner  # noqa: E402
from app.modules.ai.schemas import WorkflowPlanningContext  # noqa: E402
from app.modules.ai.validate import validate_plan  # noqa: E402


async def main(check_ai: bool) -> int:
    settings = get_settings()
    if settings.paypal_env is not PayPalEnv.SANDBOX:
        print("FAIL: This check only supports PayPal sandbox.")
        return 1
    failed = False
    client = PayPalClient(settings)
    try:
        token = await client.access_token(force_refresh=True)
        print("PayPal sandbox authentication: PASS")
        for name, available in (
            ("Invoicing scope", bool(token.scopes & INVOICING_SCOPES)),
            ("Orders scope", bool(token.scopes & ORDERS_SCOPES)),
            ("Payouts scope", PAYOUTS_SCOPE in token.scopes),
        ):
            print(f"{name}: {'PASS' if available else 'UNAVAILABLE'}")
        failed = not bool(token.scopes & INVOICING_SCOPES)
    except PayPalError as exc:
        # Provider exception bodies may contain sensitive request details.
        print(f"PayPal sandbox authentication: FAIL ({type(exc).__name__})")
        failed = True
    finally:
        await client.aclose()

    if check_ai:
        instruction = "Invoice Acme $100 for development."
        context = WorkflowPlanningContext(
            workspace_name="Readiness check",
            customer_names=["Acme"],
            contractor_names=[],
            supported_currencies=["USD"],
        )
        result = await get_planner(settings).plan_workflow(instruction, context)
        if result.provider == "fallback_rules" or result.draft is None:
            print("Live AI planning: FAIL (no live AI plan returned)")
            failed = True
        else:
            validated = validate_plan(result.draft, instruction)
            if not validated.ok:
                print("Live AI planning: FAIL (plan failed validation)")
                failed = True
            else:
                print(f"Live AI planning: PASS ({result.provider})")
    print("No financial actions executed.")
    return int(failed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ai", action="store_true", help="Also request and validate an AI plan.")
    raise SystemExit(asyncio.run(main(parser.parse_args().ai)))
