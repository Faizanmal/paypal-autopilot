# SECURITY.md — PayPal Autopilot

## 1. Threat Model Summary

This system moves real (sandbox) money and plans to move real production
money in the future. The threats that matter most, in priority order:

1. **Unauthorized financial action** — anything that lets a request create
   a real PayPal payout or invoice without proper authorization, approval,
   or idempotency.
2. **Cross-tenant data/financial leakage** — one workspace reading or
   acting on another workspace's data.
3. **AI-originated financial action** — a prompt-injected or hallucinated
   AI output directly causing money movement.
4. **Webhook spoofing / replay** — a forged or duplicated PayPal webhook
   causing a false "paid" state or duplicate side effects.
5. **Credential leakage** — PayPal/AI provider secrets ending up in logs,
   error messages, client-visible responses, or source control.
6. **Non-idempotent retries** — network retries (ours or PayPal's) causing
   double invoices/double payouts.

## 2. Authentication & Session

- Email + password (hashed with Argon2 via `passlib`/`argon2-cffi`) for
  MVP. No plaintext or reversible password storage.
- Session represented as a signed JWT (short-lived access token) or a
  server-side session cookie — exact mechanism finalized in the identity
  module's implementation phase, but in either case: `SECRET_KEY` from env,
  `httpOnly`/`secure`/`SameSite=Lax` cookies if cookie-based, no sensitive
  data embedded in a client-readable token payload beyond user/workspace
  IDs.
- No "remember me forever" tokens for MVP; reasonable expiry with refresh.

## 3. Authorization & Workspace Isolation

- **Every** ORM query for workspace-scoped data includes `workspace_id ==
  current_workspace_id` derived from the authenticated session — never
  from a client-supplied body/query/path parameter used as the sole
  authority. A path parameter like `/projects/{project_id}` is used to look
  up the row, then the row's `workspace_id` is checked against the
  session's workspace; mismatch → `404` (not `403`, to avoid confirming
  existence of another workspace's resource).
- A thin `require_workspace_member(...)` / `require_workspace_owner(...)`
  FastAPI dependency is the single enforcement point reused across all
  module routers — authorization logic is not reimplemented per-endpoint.
- Payout **approval** specifically requires the `owner` role in MVP (the
  simplest safe default: the person who can approve spending money is the
  workspace owner). Broader approver delegation is post-hackathon scope.

## 4. AI Output Is Never Trusted as an Instruction to Act

- The AI layer's only output type is `WorkflowPlanDraft` — pure data,
  validated by Pydantic against a fixed schema. There is no code path where
  a string returned by the model is `eval`'d, used as a SQL fragment, or
  used to pick which service method to call via dynamic dispatch on
  arbitrary names.
- The model is given **read-only** grounding tools; the tool-calling
  contract does not expose any tool capable of mutating data, sending
  money, or sending an invoice. Even if an attacker fully controlled the
  model's output, the worst case is a bad *draft* that a human must still
  explicitly confirm, and which still passes through independent backend
  validation (amount sums, currency checks, payee resolution) regardless of
  what the model asserts.
- Prompt-injection surfaces (e.g. text pasted in from a client email) are
  treated as untrusted content passed to the model, not as instructions the
  backend executes — the backend only ever acts on the structured,
  validated `WorkflowPlanDraft`/`WorkflowRun`, never on free text.

## 5. Payout Execution Safety (defense in depth)

A PayPal Payouts call can only happen when **all** of the following hold,
checked server-side immediately before the call, inside the same
transaction/lock as the state transition:

1. A `PayoutDraft` exists with status `TRIGGER_MET` (e.g. the linked
   invoice is verified paid).
2. An `ApprovalRequest` exists with status `APPROVED`, matching the exact
   `amount`, `currency_code`, and `recipient` of the draft (an edit to any
   of these after approval invalidates the approval and requires a new
   one — "specific, current human approval" per project rules).
3. The `ApprovalRequest` has not already been consumed (`consumed_at IS
   NULL`) — set atomically in the same statement that creates the
   `PayoutExecution`, preventing a race between two workers both acting on
   the same approval.
4. The `ApprovalRequest` has not expired (approvals carry a TTL; a stale
   approval cannot silently authorize a payout days later without a fresh
   look).
5. A valid `Idempotency-Key` (derived from the `payout_draft_id`) is
   present/derivable, preventing double-submission to PayPal on retry.

No payout execution endpoint, task, or script bypasses this check — it
lives in `execute_payout`, which is the only caller of the PayPal Payouts
client.

The running check, before `POST /v1/payments/payouts`, is:

1. The caller is the workspace owner. A member receives 403.
2. The workspace is not paused, the action is not restricted, and the
   amount is inside the per-transaction, daily, monthly, and workspace
   limits. Observer and Assistant cannot execute. Operator and Autopilot
   still need an approval for a payout.
3. `require_payout_approval` is stored true, and a check constraint keeps
   it true. Autonomy level 3 does not waive that rule.
4. The payout row is locked with `SELECT … FOR UPDATE`. A second execution
   sees the stored PayPal batch id and does not create another batch.
5. The approval is approved, unexpired, and unconsumed. Its action hash
   matches the current action type, recipient, amount, currency, target,
   and workspace. Its approval hash matches the approving user. A changed
   amount or a hash copied from another payout is rejected and is not
   consumed.
6. The approving user must still be active and an owner of this workspace.
   Authorization consumption, the `executing` state, and an audit event are
   committed before the PayPal call. The call uses the payout id as
   `PayPal-Request-Id`. A provider error or a missing batch id stores
   `execution_unknown`; the approval remains consumed. An interrupted
   process leaves `executing`. Both states block resubmission and reserve
   the budget until the provider outcome is reconciled. A successful
   response stores the provider batch id and status.

Policy preparation locks the workspace policy row through the reservation
commit, preventing concurrent intents from exceeding the same budget.
Policy updates use that same lock. Execution locks policy before payout;
the durable `execution_started` commit is its authorization point. A later
pause stops new authorizations but cannot retract a committed submission.
Outstanding reservations count in the current day and month even if
prepared in an earlier period. Completed spend is attributed to the
authorization consumption time (UTC), rather than intent creation time.

Autopilot exemptions require an owner-configured `delegated_action_types`
entry and an amount strictly below `approval_threshold_amount`. The default
delegation list is empty. Payout delegation is rejected. Observer mode,
emergency pause, and action restrictions also gate agent mutations and
invoice/project/milestone preparation. Reading and provider status
reconciliation remain available during a pause.

Approval fingerprints use canonical JSON arrays. This changes the encoding
from the earlier delimiter-separated format: pre-upgrade open approvals
fail closed and must be canceled and replaced with fresh payout intents.
Cancel and expiry can revoke an approved action before consumption and
release its reservation. An ambiguous provider outcome requires operational
reconciliation; there is no API that clears consumption to retry an
uncertain payment.

`PAYPAL_PAYOUTS_EXECUTION` remains false in the environment. Tests that
count payout POSTs turn the flag on only inside the test and mock PayPal.
A mocked batch id is not a live payout.

## 6. Idempotency & Replay

- Covered in depth in `ARCHITECTURE.md §5` (API idempotency keys) and
  `§7` (webhook dedup ledger). Security relevance: both mechanisms exist
  specifically to prevent an attacker *or* a buggy retry *or* a malicious
  replay of a captured webhook payload from causing duplicate money
  movement or duplicate invoice emails.
- Webhook signature verification (§7 of `API_INTEGRATIONS.md`) is mandatory
  before any webhook payload is trusted — unverified payloads are logged
  (without sensitive content) and discarded with a non-2xx response.

## 7. Secrets Management

- All credentials (`PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`,
  `PAYPAL_WEBHOOK_ID`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`,
  `SECRET_KEY`, `DATABASE_URL`,
  `REDIS_URL`) are environment variables only. `.env` is git-ignored;
  `.env.example` lists variable names with empty/placeholder values only.
- No secret is ever interpolated into a log line. The logging
  configuration includes a redaction filter for known secret-shaped field
  names (`*secret*`, `*token*`, `*password*`, `authorization`) as a second
  layer of defense beyond "just don't log it."
- PayPal access tokens are cached (Redis/in-memory) but never logged, never
  returned in any API response, and never persisted to Postgres.
- Error responses returned to the frontend never include raw exception
  text from a third-party API call that might embed request
  headers/credentials — they are translated to a safe, typed error first.

## 8. Logging & Audit

- Structured logging (JSON) with a request-scoped correlation ID.
- Audit log (`audit_log_entries`) is separate from application logs: it is
  an application-level, queryable, user-facing record of important state
  transitions (plan confirmed, invoice sent, reminder sent, payment
  detected, approval requested/granted/rejected, payout executed/
  succeeded/failed), each entry carrying `workspace_id`, `actor_user_id`
  (or `system` for automated actions), `action`, `entity_type`,
  `entity_id`, `metadata` (non-sensitive), `created_at`. Audit entries are
  insert-only; no update/delete path exists in the service layer.
- No financial amount, PayPal ID, or workflow metadata is itself
  "sensitive" in the credential sense, but still excluded from raw
  debug-level logs where avoidable in favor of structured, reviewed fields.

## 9. No Silent Failure / No Fabricated Success

- A PayPal API call that errors, times out, or returns an unexpected shape
  results in a typed failure surfaced to the caller/UI and recorded in the
  audit log — never translated into a "success" state to make a demo look
  better. This is an explicit project rule (never fabricate PayPal
  transaction success) and a security property: a false "paid"/"paid out"
  state is itself a financial integrity bug.
- Bare `except:` / broad exception swallowing is disallowed by convention
  (`ARCHITECTURE.md §13`) and will be checked for in review of each
  implementation phase.

## 10. Sandbox-Only Enforcement

- `PAYPAL_ENV` must be `sandbox`; `app/core/config.py` validates this at
  startup and raises a fast, explicit error otherwise. A second explicit
  flag (`ALLOW_LIVE_PAYPAL=true`) is required to even consider `live`, and
  nothing in the current implementation plan sets or reads that flag as
  "go" — it exists purely so a future, deliberate production rollout is an
  explicit, reviewable change rather than a flipped string.

## 11. Dependency & Supply Chain Notes

- Backend dependencies managed via `uv` with a committed lockfile;
  frontend via `npm`/`package-lock.json`. Both are reviewed for known-bad
  packages at implementation time (no automated SCA tool wired up yet in
  MVP — tracked as a post-hackathon hardening item).
- No dependency is vendored/copy-pasted to avoid version tracking.

## 12. Data Retention (MVP stance)

- No automatic deletion/retention policy implemented in MVP; all records
  (including audit log) are retained indefinitely for the duration of the
  hackathon project. A real data-retention/right-to-deletion policy is
  explicitly flagged as **post-hackathon scope**, not silently ignored.
