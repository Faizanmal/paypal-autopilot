# API_INTEGRATIONS.md — PayPal Autopilot

All integration details here were verified against official PayPal Developer
documentation on **2026-11-05**. Re-verify before relying on any endpoint
shape at implementation time — PayPal's docs are versioned and do change.

## 1. Environments

| Environment | Base URL | Enabled in this project |
|---|---|---|
| Sandbox | `https://api-m.sandbox.paypal.com` | **Yes — only mode enabled for the hackathon** |
| Live | `https://api-m.paypal.com` | No. Config is structured so switching requires an explicit, separate credential set and an explicit `PAYPAL_ENV=live`; there is no default that could accidentally hit production. |

Config enforces sandbox: `app/core/config.py` will refuse to start with
`PAYPAL_ENV=live` unless a separate `ALLOW_LIVE_PAYPAL=true` flag is also
set — defense against accidental production calls during the hackathon.

## 2. Authentication

- OAuth2 **Client Credentials** grant.
- `POST {base}/v1/oauth2/token`, Basic Auth with `PAYPAL_CLIENT_ID` /
  `PAYPAL_CLIENT_SECRET`, body `grant_type=client_credentials`.
- Access tokens are cached in-process/Redis with a TTL slightly shorter
  than PayPal's reported `expires_in`, and refreshed on 401. Tokens are
  never logged. Redis is a cache for the token here, not a system of
  record — losing it just costs one extra token fetch.

## 3. Invoicing API v2 (primary payment-collection mechanism)

Chosen over building invoicing manually on top of the Orders/Checkout API
because it natively models "invoice," "send," "reminder," and "paid," which
map directly onto the product's domain language and ship built-in reminder
and webhook support.

| Action | Endpoint | Notes |
|---|---|---|
| Create draft invoice | `POST /v2/invoicing/invoices` | Requires `invoicer` + `items[]`. Returns `201` + PayPal-assigned `id` (e.g. `INV2-...`) — stored as `invoices.paypal_invoice_id`. |
| Send invoice | `POST /v2/invoicing/invoices/{id}/send` | Moves `DRAFT` → payable. `send_to_recipient:true` emails the client; the hosted payment link is also returned for in-app display. |
| Send reminder | `POST /v2/invoicing/invoices/{id}/remind` | **Hard limit: max 2 reminder calls per invoice per day**, enforced by PayPal. Our reminder scheduler must respect this (see §6) — a 7-day "remind if unpaid" rule naturally stays well under this cap, but any future higher-frequency reminder feature must check/guard it explicitly. |
| Get invoice | `GET /v2/invoicing/invoices/{id}` | Used by the reconciliation poller as a fallback to webhooks. |

**Required OAuth scope**: `https://uri.paypal.com/services/invoicing/invoices/readwrite`.

## 4. Payouts API v1 (contractor/subcontractor payments)

| Action | Endpoint | Notes |
|---|---|---|
| Create payout batch | `POST /v1/payments/payouts` | One batch per `PayoutExecution`; batch contains exactly one item for MVP (single recipient). Requires a client-generated `sender_batch_id`, which **is** our idempotency key for this call. |
| Get payout batch status | `GET /v1/payments/payouts/{batch_id}` | Used by reconciliation; also returned synchronously as `PENDING` on creation — final status always arrives via webhook or polling, never assumed from the creation response. |
| Get payout item details | `GET /v1/payments/payouts-item/{item_id}` | Per-item status detail. |

Recipient identification for MVP: PayPal email address (`recipient_type:
EMAIL`) — the simplest, most sandbox-testable payout target. Phone/PayPal
ID-based payouts are a trivial post-hackathon extension.

**Required OAuth scope**: `https://uri.paypal.com/payments/payouts`.

Execution stays disabled unless `PAYPAL_PAYOUTS_EXECUTION=true` and a live
token includes that scope. Diagnostics never create a payout. With the
credentials empty, the API can still store and approve a payout intent and
will refuse execution.

## 5. Checkout / Orders API v2

Invoicing remains the primary "send a bill" path (ADR-003). Orders v2 is a
separate checkout path (ADR-011). The buyer must approve the order. This
code does not approve or capture on the buyer's behalf.

| Action | Endpoint | Notes |
|---|---|---|
| Create order | `POST /v2/checkout/orders` | `intent` is `CAPTURE` or `AUTHORIZE`. Response links with `rel` `payer-action` or `approve` are the buyer approval URL. |
| Show order | `GET /v2/checkout/orders/{id}` | Used before capture and for reconciliation. |
| Capture order | `POST /v2/checkout/orders/{id}/capture` | Called only when PayPal status is `APPROVED` and intent is `CAPTURE`. |
| Authorize order | `POST /v2/checkout/orders/{id}/authorize` | Called only when intent is `AUTHORIZE` and status is `APPROVED`. |
| Capture authorization | `POST /v2/payments/authorizations/{id}/capture` | Called only when that authorization status is `CREATED`. |

Required scope observed in the Orders reference:
`https://uri.paypal.com/services/payments/payment`.

## 6. Webhooks

- Registration: `POST /v1/notifications/webhooks` with our listener URL and
  explicit `event_types` (not `*`) — least-privilege subscription:
  - `INVOICING.INVOICE.CREATED`, `INVOICING.INVOICE.SENT`,
    `INVOICING.INVOICE.PAID`, `INVOICING.INVOICE.CANCELLED`,
    `INVOICING.INVOICE.REFUNDED`, `INVOICING.INVOICE.UPDATED`
  - `PAYMENT.PAYOUTSBATCH.SUCCESS`, `PAYMENT.PAYOUTSBATCH.DENIED`,
    `PAYMENT.PAYOUTS-ITEM.SUCCEEDED`, `PAYMENT.PAYOUTS-ITEM.FAILED`,
    `PAYMENT.PAYOUTS-ITEM.BLOCKED`, `PAYMENT.PAYOUTS-ITEM.CANCELED`,
    `PAYMENT.PAYOUTS-ITEM.RETURNED`, `PAYMENT.PAYOUTS-ITEM.UNCLAIMED`,
    `PAYMENT.PAYOUTS-ITEM.HELD`
- Listener: `POST /api/v1/webhooks/paypal` (FastAPI). Must respond `2xx`
  within PayPal's timeout or PayPal retries up to 25 times over 3 days —
  our handler does the minimal "verify → dedup-insert → enqueue async
  processing" work synchronously and returns fast; the actual domain
  side-effect (mark invoice paid, etc.) can be done inline for MVP given
  it's a single fast DB write, with a Celery task as an escape valve if
  processing ever needs to be heavier.
- **Verification** (PayPal's preferred local check, June 2026 docs):
  1. Read `PAYPAL-TRANSMISSION-ID`, `PAYPAL-TRANSMISSION-TIME`,
     `PAYPAL-TRANSMISSION-SIG`, `PAYPAL-CERT-URL`, and `PAYPAL-AUTH-ALGO`.
  2. Reject any certificate URL that is not `https` on `api.paypal.com`,
     `api.sandbox.paypal.com`, `api-m.paypal.com`, or
     `api-m.sandbox.paypal.com`.
  3. Verify `PAYPAL-TRANSMISSION-SIG` as SHA256withRSA over
     `transmission_id|transmission_time|webhook_id|crc32(raw_body)`.
     The CRC32 is the unsigned decimal of the raw bytes. The body is not
     re-serialized.
  4. If the certificate cannot be downloaded, fall back to
     `POST /v1/notifications/verify-webhook-signature`. PayPal documents
     that this postback does not work for simulator events, whose webhook
     id is the literal `WEBHOOK_ID`.
- **Dedup**: `webhook_events(webhook_id, event_id)` unique constraint. A
  duplicate delivery (same `event_id`) hits a unique-violation on insert and
  is acknowledged with `200` without re-running any side effect.
- **Sandbox testing**: PayPal's Webhooks Simulator (mock events, fixed
  `WEBHOOK_ID` id) is used for local webhook-handler development; real
  sandbox-triggered events (created by actually paying a sandbox invoice)
  are exercised before calling the feature VERIFIED.
- **Local delivery**: webhook delivery to `localhost` requires a tunnel
  (e.g. an HTTPS tunnel tool) during local development — tracked as a dev
  environment setup step, documented in the backend README once
  scaffolded, not a production concern (production has a real HTTPS
  endpoint).

## 7. AI Provider Integration

- Abstracted behind `AIProvider` (see `ARCHITECTURE.md §8`). No specific
  LLM vendor is hard-wired into business logic.
- Primary adapters: OpenAI-compatible structured-output clients for
  **Groq**, **Gemini**, and **OpenAI**. Selection is via `AI_PROVIDER`.
- **Cascade**: `AI_PROVIDER=auto` tries **groq → gemini → openai** for any
  keys that are set, then the deterministic rule-based parser.
- **Credentials required**: API keys for whichever providers you enable
  (`GROQ_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`). These are new
  external credentials the user must supply.
- **Fallback when blocked**: `RuleBasedFallbackProvider` — a constrained,
  explicitly-labeled, non-LLM parser that handles the canonical sentence
  pattern (and close variants) using structured text parsing (amounts,
  "milestones", "remind ... days", "payout ... after payment"). It is not a
  mock of financial truth (no fake PayPal responses, no invented success
  states) — it only replaces the *language understanding* step, and its
  output still flows through the full Layer 2/3 validation and execution
  pipeline. It is visibly labeled "Fallback parser (no AI provider
  configured)" everywhere it's used (UI banner + audit log entry).

## 8. Required Environment Variables (to be finalized in `.env.example`)

| Variable | Purpose |
|---|---|
| `PAYPAL_ENV` | `sandbox` (only supported value for the hackathon) |
| `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` | Sandbox REST app credentials |
| `PAYPAL_WEBHOOK_ID` | Registered webhook ID for signature verification |
| `AI_PROVIDER` | `auto` \| `groq` \| `gemini` \| `openai` \| `fallback_rules` |
| `GROQ_API_KEY` | Optional; used by `auto` / `groq` |
| `GEMINI_API_KEY` | Optional; used by `auto` / `gemini` (and cascade after groq) |
| `OPENAI_API_KEY` | Optional; used by `auto` / `openai` (and cascade after gemini) |
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Celery broker/result + token cache |
| `SECRET_KEY` | Session/JWT signing |
| `ALLOW_LIVE_PAYPAL` | Must be explicitly `true`, in addition to `PAYPAL_ENV=live`, to ever call production PayPal — not used in this project's current scope |

No credential above is committed anywhere in the repo; `.env.example` ships
only variable names with placeholder/empty values.

## 9. Known Integration Risks

| Risk | Mitigation |
|---|---|
| PayPal sandbox webhook delivery to a local dev machine requires a public HTTPS tunnel | Document setup step; reconciliation polling as a fallback so core features remain testable even if webhook delivery is temporarily unavailable |
| PayPal sandbox rate limits / flakiness | Backoff + retry with jitter in `integrations/paypal`; circuit breaker not needed at hackathon scale but code structured so a call site can't retry a *mutating* call without an idempotency key |
| Reminder cap (2/day) could be hit if multiple workflow steps target the same invoice same day | `ScheduledJob` dedup on `(invoice_id, job_type, DATE(run_after))` before dispatch |
| No LLM API key available in this environment | Explicit fallback parser (§7); live-LLM wiring is ready behind the adapter interface so adding a key later requires no architecture change |
| PayPal Invoicing API requires the merchant (invoicer) account to be "in good standing" | Use the sandbox business account created for this project; document account setup in README once credentials exist |
