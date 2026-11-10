# Executable demo walkthrough

Step-by-step path matching the hackathon story. **Do not claim a PayPal
capability works unless `/app/paypal` diagnostics (or the API diagnostics
endpoint) report it available.**

## 0. Preconditions

```powershell
copy .env.example .env   # if needed; fill sandbox values
docker compose up -d postgres redis
cd apps/api; uv sync; uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
# other terminal
cd apps/web; npm install; npm run dev
```

Optional worker (reminders):

```powershell
cd apps/api
uv run celery -A app.workers.celery_app worker --loglevel=INFO
uv run celery -A app.workers.celery_app beat --loglevel=INFO
```

Checks:

- http://localhost:8000/health → `paypal_env: sandbox`
- http://localhost:8000/ready → `database: ok`
- http://localhost:3000 → register workspace (owner)

Owner-only: open **PayPal** page and note Authentication / Invoicing / Orders / Webhooks / Payouts.

## A. Create project from natural language

1. Go to **AI workspace** (`/app/agent`).
2. Preview:

   `Create a $3,000 project called Website Redesign with three payment milestones for Acme.`

3. Confirm the plan.
4. Expect: project + three draft milestones (or clarification if Acme is missing — create the customer first).

## B. Three payment milestones

1. Open the project.
2. Confirm three milestones exist (amounts should sum to the project total).
3. Advance milestone states as needed until the first is **accepted** (required before invoicing).

## C–D. Draft / send sandbox invoice + payment

**Gate:** Invoicing must be **available** on diagnostics.

1. From the accepted milestone, create/draft the PayPal invoice (UI or agent step `prepare_milestone_invoice`).
2. Send the invoice if credentials allow.
3. Pay with the **sandbox buyer** account (or PayPal sandbox payment flow).
4. If invoicing is **unavailable**, stop this branch. Record the diagnostic detail. Do **not** manually invent a `paypal_invoice_id`.

## E–F. Webhook + workflow update

**Gate:** `PAYPAL_WEBHOOK_ID` set and a public HTTPS URL **or** use **Sync** from the invoice detail if your environment cannot receive webhooks.

1. Prefer real webhook delivery to `/api/v1/webhooks/paypal`.
2. Otherwise click sync / refresh status so the app re-fetches PayPal and writes a payment record only when PayPal reports paid.
3. Confirm invoice status and milestone progress; check **Audit log**.

## G–H. Contractor payout + human approval

1. Ensure a contractor exists with a sandbox PayPal email.
2. Create a payout intent (UI or agent) tied to the cleared client payment when required by policy.
3. Open **Approvals**, verify amount/recipient fingerprint, **Approve** as owner.
4. Reject path (optional): reject with a written reason ≥3 characters.

## I. Execute payout

**Gate:** `PAYPAL_PAYOUTS_EXECUTION=true` **and** diagnostics show Payouts available with execution enabled.

1. Execute from the payout detail.
2. If gated off, show the capability reason. Leave the intent `approved` / non-executed. That is a successful honesty demo.

## J. Dashboard + audit

1. **Cash flow**: confirmed paid, receivables, obligations, insights, assumptions.
2. **Audit**: initiator, AI proposed, approval id, policy, PayPal operation, result.
3. **Overview**: top insights and pending approvals count.

## Automated stand-ins for judges

If live scopes are missing, judges can still verify behavior via:

```powershell
cd apps/api
uv run pytest -q
cd ../web
npm run test:unit
npx playwright test
```

Pytest uses mocks for PayPal HTTP and **clears** live credentials — a pass there is not a live sandbox pass.
