# apps/api — PayPal Autopilot backend

FastAPI + Pydantic v2 + SQLAlchemy 2.x (async) + Alembic + Celery.

See the root-level [`docs/`](../../docs) for product, architecture, API
integration, security, and decision documentation. This README covers
local developer commands only.

## Prerequisites

- Python 3.13
- [`uv`](https://docs.astral.sh/uv/) for dependency management
- PostgreSQL 16 and Redis 7 (via root `docker compose up -d postgres redis`,
  or run natively and point `DATABASE_URL`/`REDIS_URL` at them)

## Setup

```powershell
cd apps/api
uv sync                # installs runtime + dev dependency groups
copy ..\..\.env.example ..\..\.env   # from repo root, once; edit as needed
```

## Common commands

```powershell
# Run the API with reload
uv run uvicorn app.main:app --reload

# Run the Celery worker / beat scheduler
uv run celery -A app.workers.celery_app worker --loglevel=INFO
uv run celery -A app.workers.celery_app beat --loglevel=INFO

# Tests
uv run pytest -v

# Lint / type-check
uv run ruff check .
uv run mypy app

# Alembic migrations (requires a running Postgres; see root docker-compose.yml)
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
```

Tests always use the isolated `localhost:5433/autopilot_test` database.
They ignore developer `.env` credentials and block unmocked outbound HTTP;
PayPal and AI requests must be mocked. The live sandbox test stays skipped.

The focused financial security gate is:

```powershell
uv run pytest tests/unit/test_financial_policy.py tests/integration/test_policy_approvals.py -q
```

Migration `a6d8e2f019bc` adds explicit Autopilot delegation, defaulting to an
empty list. Existing approvals using the previous fingerprint encoding fail
closed after this upgrade: cancel them and prepare fresh payout intents.
Uncertain provider submissions retain their authorization consumption and
budget reservation until the provider result is reconciled; do not clear
consumption or retry an uncertain payout.

## Module layout

Each `app/modules/<name>/` package owns its own `models.py`, `schemas.py`,
`validators.py`, `services.py`, and `router.py`. See
[`docs/ARCHITECTURE.md §10`](../../docs/ARCHITECTURE.md) for the full
convention and the reasoning behind it (no cross-module ORM access).
