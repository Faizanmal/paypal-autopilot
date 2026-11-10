# PayPal Autopilot

AI-planned, policy-validated, approval-gated financial workflows for freelancers and small studios — built for the [PayPal AI Hackathon 2026](https://paypalaihackathon.devpost.com/).

**One sentence in → a structured PayPal sandbox workflow out.** The AI plans; the backend validates; humans approve money movement; PayPal executes only in sandbox.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

## Why this exists

Freelancers are often their own finance ops team: invoices, contractor payouts, and “did we get paid?” threads. Autopilot keeps automation honest — expected invoices are never treated as cash, payouts cannot skip exact-action approval, and every sensitive step is audited.

## What’s in the box

- **TrustFlow** — customers, projects, milestones, contract intake
- **Autopilot** — PayPal Invoicing, webhooks, reminders, checkout adapters
- **SpendPilot** — financial policy, exact-action approvals, gated payouts
- **AI command layer** — natural-language plans (Groq → Gemini → OpenAI cascade; rule-based fallback)
- **Cash flow** — confirmed vs expected vs planned money, insights, uncertainty
- **Audit log** — who initiated, AI proposed?, approver, policy, PayPal op, result

PayPal stays on **sandbox**. Live mode requires an explicit second flag and is not used for the hackathon.

## Quick start (judges & developers)

### Prerequisites

- Docker Desktop (Postgres + Redis)
- Python 3.13 + [uv](https://github.com/astral-sh/uv)
- Node.js 22+

### 1. Environment

```powershell
copy .env.example .env
```

Set at least:

- `SECRET_KEY` (16+ characters)
- Leave `PAYPAL_ENV=sandbox` and `ALLOW_LIVE_PAYPAL=false`
- Optionally fill PayPal sandbox credentials (see `.env.example`)
- For the live invoice demo: in PayPal Developer → Apps & Credentials → your **Sandbox** app → **Features**, enable **Invoicing**, then restart the API. Verify with `cd apps/api; uv run python ../../scripts/check_paypal_scopes.py`

### 2. Data services

```powershell
docker compose up -d postgres redis
```

Host ports default to **5433** (Postgres) and **6380** (Redis).

Create the test database once (for pytest):

```powershell
docker exec paypal-autopilot-postgres-1 psql -U autopilot -d postgres -c "CREATE DATABASE autopilot_test"
```

### 3. API

```powershell
cd apps/api
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

- Health: http://localhost:8000/health  
- Ready: http://localhost:8000/ready  
- OpenAPI (non-production): http://localhost:8000/docs  

### 4. Web

```powershell
cd apps/web
npm install
npm run dev
```

Open http://localhost:3000 and **register a workspace**.

### 5. Optional worker + scheduler

```powershell
cd apps/api
uv run celery -A app.workers.celery_app worker --loglevel=INFO
uv run celery -A app.workers.celery_app beat --loglevel=INFO
```

## Demo

- Executable path: [`docs/DEMO_WALKTHROUGH.md`](docs/DEMO_WALKTHROUGH.md)

Before claiming a live invoice or payout on camera, open **PayPal → diagnostics** in the app. Unavailable scopes are shown as blocked — that is intentional.

## Tests

GitHub Actions runs backend lint, typing and database integration tests, then
frontend checks, a production build and desktop/mobile browser workflows on
every push and pull request. CI uses test credentials and the deterministic
planner; it does not call payment providers.

```powershell
# API
cd apps/api
uv run pytest -q

# Web
cd apps/web
npm run test:unit
npx playwright test
```

Pytest **clears** PayPal credentials and blocks unmocked HTTP. A green suite is not a live sandbox certification.

## Deployment readiness (not auto-deployed)

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

```powershell
# Dev compose
docker compose -f docker-compose.yml config --quiet

# Production-style compose (requires env vars; does not deploy by itself)
# $env:POSTGRES_PASSWORD='…'
# $env:CORS_ORIGINS='https://app.example.com'
# $env:NEXT_PUBLIC_API_BASE_URL='https://api.example.com'
docker compose -f docker-compose.prod.yml config --quiet
```

**Do not** run `up --build` against a public host until the owner authorizes deployment.

## Documentation map

Hackathon host path: **Render Blueprint** (`render.yaml`) + Netlify web — see
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md). Commercial AG Studio / Bryntum /
related terms: [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

| Doc | Purpose |
| --- | --- |
| [`docs/PRODUCT.md`](docs/PRODUCT.md) | Product intent |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Module boundaries & AI/validation/execution split |
| [`docs/API_INTEGRATIONS.md`](docs/API_INTEGRATIONS.md) | PayPal endpoints & AI provider contract |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Security controls |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Render + Netlify, HTTPS, webhooks, workers |
| [`docs/DEMO_WALKTHROUGH.md`](docs/DEMO_WALKTHROUGH.md) | Executable demo path |

## Repository layout

```
apps/web     Next.js App Router, TypeScript, Tailwind
apps/api     FastAPI, SQLAlchemy 2, Alembic, Celery
infra/docker Production-oriented Dockerfiles
docs/        Product, architecture, security, deployment, demo walkthrough
scripts/     Windows task helpers + API docker entrypoint
LICENSE      MIT
```

## Hackathon requirements coverage

| Requirement | Status |
| --- | --- |
| Meaningful PayPal sandbox integration | Yes — Invoicing, Webhooks, Payouts (gated), Orders adapter |
| Meaningful AI use | Yes — planner + validation; Groq/Gemini/OpenAI cascade or rules |
| Public open-source license | MIT (`LICENSE`) |
| Setup so judges can run it | This README + compose |
| Demo video &lt; 3 minutes | Recording preparation maintained privately; video upload pending |
| No fake financial success | Diagnostics + execution flags; audit docs |

## License

MIT — see [`LICENSE`](LICENSE).
