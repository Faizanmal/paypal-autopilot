# ARCHITECTURE.md — PayPal Autopilot

## 1. Architectural Style

**Modular monolith.** One FastAPI process (scalable to N replicas) and one
Next.js process, sharing one PostgreSQL database and one Redis instance
(cache + Celery broker only — **never** the source of financial truth).
Modules are separated by Python package boundaries with disciplined
dependency direction, not by network boundaries. This is deliberate per the
project's architectural rules: microservices add operational and consistency
complexity a hackathon-born fintech MVP cannot afford, and a monolith keeps
financial transactions inside single DB transactions wherever possible.

Boundaries are kept clean enough that any module *could* be extracted into
its own service later (clear module API, no reaching into another module's
ORM models directly — go through its service layer).

## 2. The Three-Layer Separation (hard rule)

This is the single most important architectural invariant in the system:

```
┌─────────────────────┐      ┌──────────────────────────┐      ┌───────────────────────┐
│   1. AI REASONING    │      │  2. FINANCIAL VALIDATION  │      │   3. API EXECUTION     │
│                      │      │                           │      │                        │
│ Natural language in  │ ───► │ Pydantic schema checks    │ ───► │ PayPal API calls       │
│ Structured plan out  │      │ Business rule checks      │      │ DB writes              │
│ (WorkflowPlanDraft)  │      │ Policy / approval checks  │      │ Idempotent, audited    │
│                      │      │ Human confirmation gate   │      │                        │
│ NEVER calls PayPal   │      │ NEVER calls PayPal        │      │ Only layer allowed to  │
│ NEVER writes money   │      │ Produces a validated,     │      │ touch PayPal APIs or   │
│ rows                 │      │ durable, but *inert* plan │      │ mutate money state     │
└─────────────────────┘      └──────────────────────────┘      └───────────────────────┘
```

- **Layer 1 (`app/modules/ai`)**: a provider-adapter that turns text into a
  strictly-typed `WorkflowPlanDraft` (Pydantic model). The LLM is given
  *read-only* grounding tools (e.g. "look up this client's past invoices",
  "list this workspace's known payees") — it is never given a tool that
  creates an invoice, sends money, or writes to the database. If no draft
  can be produced that passes schema validation, the layer returns a
  typed error; it never guesses past a validation failure.
- **Layer 2 (`app/modules/workflows` + each module's `validators.py`)**:
  pure functions and service methods that check the draft against business
  rules (amounts sum correctly, currencies match, payee resolvable) and
  against SpendPilot policy (does this action require approval, and from
  whom). This layer's output is a *persisted but inert* `WorkflowRun` in
  `DRAFT` or `PENDING_CONFIRMATION` state. Nothing external has happened.
- **Layer 3 (module `services.py` + `integrations/paypal`)**: the only code
  in the system allowed to call PayPal's REST APIs or mark a financial
  record as "paid"/"sent"/"succeeded". Every entry point here requires an
  idempotency key and, for payouts specifically, a currently-valid,
  unconsumed `ApprovalRequest` matching the exact amount/currency/recipient.

An LLM response is **data**, never **code** and never a **direct call**. The
tool-calling contract only ever returns JSON matching a server-defined
schema; the server re-validates that JSON independently of whatever the
model claims.

## 3. Domain Model (MVP)

```
Workspace 1──* User (via WorkspaceMembership)
Workspace 1──* Project (TrustFlow)
Project   1──* Milestone
Milestone 1──1 Invoice (optional, created when the milestone is invoiced)
Invoice   1──* InvoiceEvent (append-only status history, sourced from webhooks/reconciliation)
Invoice   1──* ScheduledJob (e.g. "remind in 7 days if unpaid")
Milestone 1──* PayoutDraft (e.g. "pay designer $300 after payment arrives")
PayoutDraft 1──1 ApprovalRequest
ApprovalRequest 1──0..1 PayoutExecution (created only on approval + trigger)
WorkflowRun 1──* WorkflowStep (the AI-planned, human-confirmed execution ledger binding the above together)
Workspace 1──* AuditLogEntry
Workspace 1──* IdempotencyKey
Workspace 1──* WebhookEvent (dedup ledger for PayPal webhook deliveries)
```

Every table below `Workspace` carries a non-nullable `workspace_id` foreign
key. There is no global "admin" query path in application code that spans
workspaces — cross-workspace access is a deployment/ops concern (direct DB
access), never an API capability.

### Core tables (initial Alembic migration target)

| Table | Purpose |
|---|---|
| `workspaces`, `users`, `workspace_memberships` | Identity & tenancy |
| `projects`, `milestones`, `contracts`, `contract_extractions` | TrustFlow |
| `invoices`, `invoice_events` | Autopilot invoicing + payment monitoring |
| `scheduled_jobs` | Durable job metadata (reminders, reconciliation ticks) — source of truth, Celery is just the executor |
| `payout_drafts`, `approval_requests`, `payout_executions` | SpendPilot approval-gated payouts |
| `workflow_runs`, `workflow_steps` | AI-planned workflow durable state |
| `idempotency_keys` | Idempotency ledger for mutating financial endpoints |
| `webhook_events` | PayPal webhook delivery dedup ledger (unique on `(webhook_id, transmission_id)`) |
| `audit_log_entries` | Append-only audit trail |

## 4. Money & Currency Handling

- All monetary columns are `NUMERIC(14, 2)` in PostgreSQL, mapped to Python
  `decimal.Decimal` via SQLAlchemy 2's `Mapped[Decimal]` — **never** `float`.
- Every monetary value is paired with an explicit `currency_code` column
  (ISO 4217). MVP supports `USD` only (validated at the Pydantic layer);
  the schema is not hard-coded to USD so additional 2-decimal currencies can
  be added without a migration.
- All arithmetic (milestone sum vs. project total, etc.) happens via
  `Decimal` with explicit rounding (`ROUND_HALF_UP`) at defined boundaries,
  never via floating point.
- PayPal's REST APIs take amounts as decimal strings (e.g. `"10.00"`); the
  `integrations/paypal` layer is the single place that formats `Decimal` →
  PayPal string and parses PayPal string → `Decimal`.
- Zero-decimal currencies (JPY, etc.) are explicitly unsupported in MVP and
  rejected at validation — flagged as a post-hackathon scope item requiring
  a currency-precision lookup table.

## 5. Idempotency

- Every mutating financial endpoint (`POST` that creates/sends an invoice,
  sends a reminder, creates a payout execution) requires an
  `Idempotency-Key` header.
- `idempotency_keys(workspace_id, key, request_fingerprint, response_body, response_status, created_at)`
  with a unique constraint on `(workspace_id, key)`. On a repeat request with
  the same key and same fingerprint, the stored response is replayed
  verbatim instead of re-executing. A repeat key with a *different*
  fingerprint is rejected (409) — this prevents key reuse from masking a
  different, unintended operation.
- Workflow-engine-triggered actions (e.g. the reminder job, the
  trigger-driven payout execution) derive their idempotency key
  deterministically from the `workflow_step_id` / `scheduled_job_id`, so a
  Celery task retry or a reconciliation sweep can never double-send.

## 6. Durable Scheduling (no Redis-as-truth)

- `scheduled_jobs` is the durable source of truth: `id, workspace_id,
  job_type, run_after, status (PENDING/RUNNING/DONE/FAILED/CANCELLED),
  payload, related_entity_type, related_entity_id, attempts, last_error,
  created_at, updated_at`.
- Celery is used purely as the **execution mechanism**: a lightweight Celery
  beat task runs every minute, selects due `PENDING` jobs from Postgres
  (`run_after <= now()`, row-locked with `FOR UPDATE SKIP LOCKED`), and
  dispatches one Celery task per job. The Celery task re-reads the job row,
  checks it is still `PENDING`, executes the underlying action through the
  same service layer the API uses, and writes the terminal status back to
  Postgres.
- If Redis is flushed or the broker is lost, no financial intent is lost:
  the next beat tick re-discovers any `PENDING` job straight from Postgres.
  Celery result backend is not used for anything financially meaningful.

## 7. PayPal Webhook Verification & Replay Protection

- Webhooks are received on a dedicated FastAPI router
  (`/api/v1/webhooks/paypal`) that:
  1. Reads the raw request body (verification requires the exact bytes).
  2. Looks up the registered `webhook_id` for the current environment from
     config (never trusts a value in the payload).
  3. Verifies authenticity using PayPal's `/v1/notifications/verify-webhook-signature`
     API (server-to-server, using transmission id/time/sig and CRC32 of the
     raw body) — self-verification via PayPal's public cert is the documented
     faster alternative and is tracked as a near-term hardening item (see
     `docs/API_INTEGRATIONS.md`).
  4. On verification failure, returns 4xx and writes an audit entry; the
     event is **not** processed.
  5. On verification success, inserts into `webhook_events` with a unique
     constraint on `(webhook_id, event_id)`; a unique-violation means this
     exact event was already processed, so the handler returns 200
     immediately without re-applying side effects (PayPal retries up to 25
     times over 3 days on non-2xx, so idempotent-but-fast acknowledgement
     matters).
  6. Only after the dedup insert succeeds does the handler translate the
     event into the same domain service calls the API/worker layer uses
     (e.g. "mark invoice paid" → the exact function also called by the
     reconciliation poller), so there is one code path for "an invoice
     became paid," regardless of source.

## 8. AI Provider Adapter

```python
class AIProvider(Protocol):
    async def plan_workflow(
        self, instruction: str, context: WorkflowPlanningContext
    ) -> WorkflowPlanResult: ...
```

- `WorkflowPlanResult` is either `WorkflowPlanDraft` (strict Pydantic model:
  project, milestones, invoice actions, reminder rules, payout drafts) or a
  typed `PlanningFailure` (e.g. `AMBIGUOUS_INPUT`, `UNSUPPORTED_CURRENCY`).
- Concrete adapters live in `app/modules/ai/providers/`: OpenAI-compatible
  LLM adapters for Groq, Gemini, and OpenAI, plus a deterministic
  `RuleBasedFallbackProvider` used when no LLM credentials work (clearly
  labeled in the UI and logs as "fallback parser"). `AI_PROVIDER=auto`
  cascades **groq → gemini → openai → rules** for whichever keys are set.
- Provider selection is via `AI_PROVIDER` env var; adapters are
  unit-testable in isolation with recorded fixtures (not live API calls) in
  `pytest`.

## 9. Workflow Engine State Machine

```
WorkflowRun: DRAFT → PENDING_CONFIRMATION → CONFIRMED → EXECUTING → COMPLETED
                                     │                        │
                                     ▼                        ▼
                                 REJECTED                 FAILED (with per-step error)

WorkflowStep (one row per planned action, e.g. CREATE_PROJECT, CREATE_MILESTONES,
CREATE_AND_SEND_INVOICE, SCHEDULE_REMINDER, CREATE_PAYOUT_DRAFT):
  PENDING → RUNNING → SUCCEEDED
                   └→ FAILED (terminal; does not auto-retry financial steps)

PayoutDraft: AWAITING_TRIGGER → TRIGGER_MET → (needs ApprovalRequest APPROVED) → EXECUTING → SUCCEEDED/FAILED
ApprovalRequest: PENDING → APPROVED | REJECTED | EXPIRED
```

A `WorkflowRun` only moves to `CONFIRMED` via an explicit user action in the
API (never automatically). `EXECUTING` runs each `WorkflowStep` in order;
steps that only touch TrustFlow data (create project/milestones) run inside
one DB transaction. Steps that call an external API (create+send invoice)
commit the DB-visible "intent" first, call PayPal, then commit the result —
so a crash between "intent committed" and "PayPal call made" is observable
and recoverable by a reconciliation job rather than silently lost.

## 10. Repository Structure

```
paypal/
├── apps/
│   ├── web/                         # Next.js 16 App Router frontend
│   │   └── src/
│   │       ├── app/                 # routes
│   │       ├── components/          # shadcn/ui + feature components
│   │       ├── lib/                 # api client, types, utils
│   │       └── hooks/
│   └── api/                         # FastAPI backend
│       ├── pyproject.toml           # uv-managed deps
│       ├── alembic.ini
│       ├── migrations/              # Alembic (async template)
│       ├── app/
│       │   ├── main.py              # app factory, router registration
│       │   ├── core/                # config, security, logging, errors, pagination
│       │   ├── db/                  # engine/session, declarative base, naming convention
│       │   ├── modules/
│       │   │   ├── identity/        # users, workspaces, auth
│       │   │   ├── trustflow/       # projects, milestones, payment conditions
│       │   │   ├── autopilot/       # invoices, reminders, payment monitoring
│       │   │   ├── spendpilot/      # policies, approvals, payouts, financial intelligence
│       │   │   ├── workflows/       # AI plan → durable workflow engine
│       │   │   └── ai/              # provider adapter + schemas
│       │   ├── integrations/
│       │   │   └── paypal/          # OAuth2 client, Invoicing, Payouts, Webhooks clients
│       │   ├── workers/             # Celery app + tasks (thin; delegate to module services)
│       │   └── audit/               # audit log service
│       └── tests/
│           ├── unit/
│           ├── integration/
│           └── fixtures/
├── infra/
│   └── docker/                      # Dockerfiles for api/web/worker
├── docs/                            # this documentation set
├── scripts/                         # one-off dev scripts (seed demo fixtures, etc.)
├── docker-compose.yml
├── .env.example
└── README.md
```

### Module internal convention (each `app/modules/<name>/`)

```
<name>/
├── __init__.py
├── models.py          # SQLAlchemy ORM models owned by this module
├── schemas.py          # Pydantic request/response + domain DTOs
├── validators.py        # Layer-2 business validation (pure, no I/O side effects beyond reads)
├── services.py           # Layer-3 orchestration: DB writes, calls integrations/*, idempotency
├── router.py          # FastAPI APIRouter, thin — delegates to services
└── tasks.py            # Celery task definitions, delegate to services (module-optional)
```

Cross-module access only through another module's `services.py` — never
importing another module's `models.py` to query/write directly. This is the
seam that would let a module be extracted into its own service later.

## 11. Frontend Architecture

- Next.js App Router, `src/app/(dashboard)/...` route groups per
  subsystem: `/projects` (TrustFlow), `/invoices` (Autopilot),
  `/approvals` (SpendPilot), `/command` (AI command bar + plan review),
  `/audit`.
- Server Components for data fetching (calling the FastAPI backend with the
  user's session), Client Components for interactive forms/dialogs
  (shadcn/ui: `Dialog`, `Form`, `Table`, `Command`, `Tabs`, `Badge`,
  `Sheet`, `Toast`).
- The "plan review" screen renders the `WorkflowPlanDraft` as an editable
  structured form (not free text) — the user is confirming/adjusting
  structured fields, not re-prompting the LLM blindly.
- All API calls go through a typed client (`src/lib/api/`) generated/kept in
  sync with the backend's Pydantic schemas; no hand-rolled `fetch` calls
  scattered through components.

## 12. Tech Stack & Verified Versions (as of 2026-11-05)

| Layer | Choice | Verified version |
|---|---|---|
| Frontend framework | Next.js (App Router) | 16.4.5 |
| UI | React + TypeScript + Tailwind CSS + shadcn/ui CLI | shadcn CLI 4.22.0 |
| Backend framework | FastAPI | 0.162.x (requires `pydantic>=2.9.0`) |
| Validation | Pydantic | v2 (>=2.9) |
| ORM | SQLAlchemy | 2.x (async, `Mapped`/`mapped_column`) |
| Migrations | Alembic | async template (`alembic init -t async`) |
| DB | PostgreSQL | 16 (Docker image) |
| Cache/broker | Redis | 7 (Docker image) |
| Jobs | Celery | 5.4/5.5 stable line (pin to latest non-RC at implementation time; 5.7 was RC as of this writing) |
| Python package mgr | `uv` | 0.8.3 (verified locally installed) |
| Payments | PayPal REST (sandbox): Invoicing API v2, Payouts API v1, Webhooks v1 | see `docs/API_INTEGRATIONS.md` |
| Local infra | Docker Compose | v5.6.1 (verified locally installed, Docker 29.9.2) |
| Testing | pytest (backend), Playwright (E2E) | latest stable, pinned at implementation time |

Dependency versions are re-verified against official docs/PyPI/npm at the
time each phase is implemented, not only at project start — package.json /
pyproject.toml lockfiles are the source of truth once scaffolding lands.

## 13. Project Conventions

- **Language/typing**: Python 3.13, full type hints, `mypy`-clean target
  for `app/` (strict mode phased in as modules land). TypeScript `strict:
  true` on the frontend.
- **Naming**: snake_case for Python, camelCase for TS/JS, PascalCase for
  React components and Pydantic/SQLAlchemy classes.
- **Errors**: no bare `except:`; every caught exception either re-raises,
  translates to a typed domain error, or is logged with context and
  re-raised — never swallowed into a false success.
- **Config**: `pydantic-settings` for backend config, loaded from
  environment variables only; `.env` files are for local dev convenience
  and are git-ignored. `.env.example` documents every required variable
  with a placeholder, never a real value.
- **Migrations**: every schema change ships an Alembic migration in the
  same PR/commit as the model change; no "run this manually" schema drift.
- **Commits**: conventional, scoped to one module/concern where practical.
- **Tests**: unit tests for validators/services with no network; integration
  tests against a real Postgres (via `docker compose`) and a PayPal
  Sandbox stub/mocked HTTP layer; a small number of tests explicitly marked
  to hit real PayPal Sandbox, run manually/CI-gated, never in the default
  fast test loop.
