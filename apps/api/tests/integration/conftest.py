from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from app.db.session import get_engine


@pytest.fixture(scope="session")
def migrated_database():
    """Apply Alembic migrations to the test database. Fails loudly if Postgres is down."""
    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "alembic upgrade head failed.\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return True


@pytest.fixture
async def clean_db(migrated_database):
    engine = get_engine()
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                TRUNCATE TABLE
                    audit_logs,
                    agent_actions,
                    agent_runs,
                    workflow_steps,
                    workflows,
                    scheduled_actions,
                    webhook_events,
                    approvals,
                    payout_requests,
                    checkout_orders,
                    payment_records,
                    invoices,
                    contract_extractions,
                    contracts,
                    milestones,
                    projects,
                    contractors,
                    customers,
                    financial_policies,
                    cash_assumptions,
                    sessions,
                    workspace_members,
                    workspaces,
                    users
                RESTART IDENTITY CASCADE
                """
            )
        )
    yield
