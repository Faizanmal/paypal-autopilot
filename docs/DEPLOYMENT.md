# Deployment readiness

**Do not deploy until the project owner explicitly authorizes it.** This document
prepares a production-*style* sandbox deployment. PayPal remains **sandbox only**.

## Local pre-deployment verification

The web app reads the root `.env` in local development and builds; host-provided
environment variables take precedence. Backend settings also read the root `.env`.
Secrets stay server-side. The browser sends API requests to the web app's
same-origin `/api/*` proxy.

```powershell
cd apps/web
npm ci
npm run lint
npm run build
npm run typecheck
npm run test:unit
# Production web build, using the local API on port 8000:
npm start
```

`npm start` launches the generated standalone server and copies the static/public
assets into its runtime directory. It reads the root `.env` without copying that
file into the artifact. Set `PORT`/`HOSTNAME`, or pass `-- --port 3100 --hostname
127.0.0.1`, to override the local listener. Build again after changing API rewrite
addresses or browser-visible licence keys.

The UI uses system fonts, so builds do not download fonts from Google.
For Docker, `API_INTERNAL_BASE_URL=http://api:8000` is set during both the
web image build and runtime. For Netlify (or any host that proxies
`/api/*` to the API), set `API_INTERNAL_BASE_URL` to the public HTTPS API
URL **before building**, then rebuild whenever it changes.

```powershell
cd apps/api
uv run ruff check .
uv run mypy app
uv run pytest -q
# Uses configured keys; prints no credentials and executes no financial actions.
# --ai sends a planning request to the configured AI provider.
uv run python ../../scripts/check_integrations.py --ai
```

Full integration tests require the isolated `autopilot_test` database, as in the
root README. A passing build or mocked test does not certify real buyer payment
or public webhook delivery. Those require a final sandbox smoke test after HTTPS
and the PayPal webhook callback have been configured.

## Hackathon host: Render Blueprint + Netlify web (ADR-015)

Supersedes ADR-014 (GCP VM). Use the root `render.yaml` Blueprint so the
backend runs on Render (sponsor credits) while the Next.js UI stays on
Netlify. These steps do not publish anything by themselves.

| Surface | Where |
| --- | --- |
| API, worker, scheduler, Postgres, Redis-compatible broker, Workflows | Render Blueprint (`render.yaml`) |
| Web (Next.js) | Netlify HTTPS origin; browser uses same-origin `/api/*` |
| PayPal webhook | `https://<render-api-host>/api/v1/webhooks/paypal` |

### Deploy: Render API stack

1. Publish the source repository and claim the
   [Render hackathon credits](https://paypalaihackathon.devpost.com/details/render).
   Review current plan costs; credits are not an unlimited hosting plan.
2. In Render: **New → Blueprint**, connect the repository, review `render.yaml`.
   All backend resources share one region and private networking. Auto-deploy
   on commit is off so schema changes can be rolled deliberately.
3. Supply sync-false env vars on the API service:
   - `CORS_ORIGINS` — exact Netlify HTTPS origin
   - `PUBLIC_API_BASE_URL` — final Render API HTTPS origin
   - Sandbox PayPal values (`PAYPAL_CLIENT_ID` / `SECRET`, webhook id, business email)
   - At least one AI key (`GROQ_API_KEY`, `GEMINI_API_KEY`, or `OPENAI_API_KEY`);
     leave unused AI keys empty
   - Keep `PAYPAL_ENV=sandbox`, `ALLOW_LIVE_PAYPAL=false`, and payouts disabled
4. Do **not** paste localhost database URLs. The Blueprint wires
   `DATABASE_URL` / `DATABASE_URL_SYNC` from Render Postgres and `REDIS_URL`
   from the Key Value broker. The API pre-deploy command runs migrations.
   On first deploy, start or restart workers only after the API is healthy.
5. Confirm `GET /health`, `GET /ready`, worker logs, and scheduler logs.
   Keep a single scheduler. Postgres and the broker reject public inbound
   connections. The small worker plan uses one Celery child process.

### Deploy: Netlify web

1. Netlify base directory `apps/web`, Node 22+, build `npm run build`, with the
   Next.js integration.
2. Before building, set `API_INTERNAL_BASE_URL` to the Render API HTTPS URL.
   Optionally set `NEXT_PUBLIC_AG_STUDIO_LICENSE_KEY` for a hosted AG Studio
   trial (browser-visible; never put API secrets there). Rebuild after either
   value changes. API keys and database credentials stay on Render only.
3. Register `{PUBLIC_API_BASE_URL}/api/v1/webhooks/paypal` in PayPal sandbox,
   put the webhook id on the Render API service, restart API/worker/scheduler.
4. Smoke-test hosted registration/login, invoice create/send, sandbox buyer
   payment, webhook verification, reminder cancellation, and audit records.

### Optional: Render Workflows cash-risk report

Deploy the `paypal-autopilot-reports` workflow from the same Blueprint. Copy its
task slug (ending in `/cash-risk-report`) into the API's `RENDER_REPORT_TASK`,
set a server-side `RENDER_API_KEY`, and keep `RENDER_USE_LOCAL_DEV=false` with
`RENDER_LOCAL_DEV_URL` empty on hosted services.

### Alternative: production-style Compose on a VM

`docker-compose.prod.yml` remains valid for a self-hosted sandbox (API bind on
loopback, TLS reverse proxy, Netlify or other HTTPS web). Prefer the Render
path for this hackathon submission.

## Stack

| Service | Role | Health |
| --- | --- | --- |
| `postgres` | System of record (persistent volume) | `pg_isready` |
| `redis` | Celery broker + token cache only | `PING` |
| `api` | FastAPI (runs Alembic on start) | `GET /ready` |
| `worker` | Celery worker (reminders / due jobs) | `inspect ping` |
| `scheduler` | Celery beat | process check |
| `web` | Next.js standalone | `GET /` |

Compose files:

- `docker-compose.yml` — local development (bind mounts, `--reload`, published Postgres/Redis ports)
- `docker-compose.prod.yml` — production-style images (no bind mounts, migrate on API start, sandbox enforced)

## Environment variables

Copy `.env.example` → `.env`. Never commit `.env`.

### Required for any run

| Variable | Notes |
| --- | --- |
| `SECRET_KEY` | ≥16 characters. Used to HMAC session tokens. |
| `DATABASE_URL` | Async SQLAlchemy URL (`postgresql+asyncpg://…`) |
| `DATABASE_URL_SYNC` | Same database, `postgresql+psycopg://…` (Alembic) |
| `REDIS_URL` | Celery broker |

### PayPal sandbox

| Variable | Notes |
| --- | --- |
| `PAYPAL_ENV` | Must stay `sandbox` |
| `ALLOW_LIVE_PAYPAL` | Must stay `false` |
| `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` | Sandbox REST app |
| `PAYPAL_WEBHOOK_ID` | From the PayPal developer webhook subscription |
| `PAYPAL_SANDBOX_BUSINESS_EMAIL` | Invoicer email on draft invoices |
| `PAYPAL_SANDBOX_BUYER_EMAIL` | Optional demo buyer account |
| `PAYPAL_PAYOUTS_EXECUTION` | Keep `false` until Payouts scope is confirmed |

Required OAuth scopes for a full money demo: invoicing read/write, Orders payments (if using checkout), payouts (only if enabling execution).

### Production-style compose extras

| Variable | Notes |
| --- | --- |
| `APP_ENV` | Set to `production` by `docker-compose.prod.yml` |
| `CORS_ORIGINS` | Comma-separated HTTPS origins of the web app (required in production) |
| `NEXT_PUBLIC_API_BASE_URL` | Public HTTPS API URL baked into the web build |
| `PUBLIC_API_BASE_URL` | Optional documented public API origin |
| `POSTGRES_PASSWORD` | Required by prod compose (no weak default) |

## HTTPS and reverse proxy

Place TLS termination in front of `web` and `api` (Caddy, nginx, Traefik, cloud LB).

Requirements:

1. Public `https://` origins for the web app and API.
2. Cookies: with `APP_ENV=production`, the session cookie is `Secure`.
3. Forward `X-Forwarded-Proto` / `X-Forwarded-For`. The API starts with `--proxy-headers`.
4. HSTS is set by the API when `APP_ENV=production`.

Example webhook callback (sandbox developer dashboard):

```text
https://<your-public-api-host>/api/v1/webhooks/paypal
```

PayPal must reach that URL from the internet. Localhost alone cannot receive live webhook deliveries without a tunnel (ngrok, Cloudflare Tunnel, etc.).

## Database migrations

- Local: `cd apps/api && uv run alembic upgrade head`
- Prod compose: API container entrypoint runs `alembic upgrade head` before uvicorn
- One-shot: `docker compose -f docker-compose.prod.yml run --rm api migrate`

Always keep `DATABASE_URL` and `DATABASE_URL_SYNC` pointed at the **same** database name.

## Workers and scheduler

Financial truth lives in Postgres. Redis is only the Celery broker/result backend and OAuth token cache.

- Scale `worker` replicas if reminder volume grows.
- Run **one** `scheduler` (Celery beat) instance to avoid duplicate schedules.
- API, worker, and scheduler images run as the dedicated `autopilot` user
  (UID 10001). Keep `/app` writable for the scheduler's local state file.
- Each scheduled dispatch disposes its database connections before closing its
  event loop. The Compose worker health check targets that container's own worker
  through the broker (`python -m app.workers.health`).
- After a worker crash, due jobs remain in `scheduled_actions` until a healthy worker claims them (`FOR UPDATE SKIP LOCKED` where used).

## Logging and monitoring

- API logs JSON to stdout with secret-key redaction (`app/core/logging.py`).
- Scrape container logs with your platform’s collector (CloudWatch, Datadog, Loki).
- Alert on: `/ready` failures, Celery worker disconnect, repeated `execution_unknown` payouts, webhook `failed` status.

Suggested checks every 60s:

- `GET /health` — process up, reports `paypal_env`
- `GET /ready` — database reachable
- Celery `inspect ping`

## Backup and recovery

1. **Postgres**: volume `postgres_data`. Take logical dumps (`pg_dump`) before demos that mutate money state; schedule daily dumps for any shared environment.
2. **Redis**: disposable. Losing it drops cached OAuth tokens and in-flight Celery messages; durable job rows remain in Postgres.
3. **Secrets**: store `.env` in a secret manager for any shared host. Rotate `SECRET_KEY` only with a planned session invalidation.
4. **Recovery**: restore Postgres volume/dump → `alembic upgrade head` → start api/worker/scheduler/web. Reconcile any `execution_unknown` payouts against PayPal before retrying.

## Validation checklist (pre-authorization)

```powershell
# Secrets not tracked
git check-ignore -v .env
git ls-files .env   # must be empty

# Compose files parse
docker compose -f docker-compose.yml config --quiet
# Prod file requires env vars — set temporary values only in your shell, do not commit them:
# $env:POSTGRES_PASSWORD='…'; $env:CORS_ORIGINS='https://app.example.com'; $env:NEXT_PUBLIC_API_BASE_URL='https://api.example.com'
docker compose -f docker-compose.prod.yml config --quiet

# Local API
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
```

## What is intentionally not automated here

- Creating a cloud account, DNS, or TLS certificate
- Pushing images to a registry
- Opening a public GitHub repository
- Submitting to Devpost
- Enabling live PayPal
