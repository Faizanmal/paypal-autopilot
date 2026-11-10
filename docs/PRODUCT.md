# PRODUCT.md — PayPal Autopilot

## 1. Vision

**PayPal Autopilot** is an AI-operated financial back office for freelancers and
small businesses that get paid through PayPal. A user describes an engagement
in plain language — a project, its milestones, who to invoice, when to chase
late payers, and who to pay out of the proceeds — and the system turns that
into a structured, auditable, policy-checked financial workflow that runs
safely over days and weeks.

The product is really three cooperating subsystems wearing one UI:

| Codename | Responsibility |
|---|---|
| **PayPal Autopilot** (core) | Invoicing, checkout/payment collection, payment monitoring, reminders, contractor payouts via PayPal. |
| **TrustFlow** | Contracts, projects, milestones, and the payment conditions that bind them together. |
| **SpendPilot** | Spending policy, human approval gates, financial intelligence (balances, exposure, risk), and workflow automation/scheduling. |

AI is the **intake and planning layer only**. It never moves money. Every
dollar that moves does so through deterministic, validated, authorized,
idempotent backend code — the AI's job ends at producing a structured plan
for a human to review.

## 2. Primary Persona

- **Independent contractor / small agency owner** who invoices clients
  through PayPal, subcontracts part of the work, and currently tracks
  milestones, due dates, and subcontractor payments in spreadsheets, email,
  and PayPal's own dashboard — manually, and often late.

Secondary persona: a very small team (2-5 people) where one person acts as
the de facto finance lead and needs a lightweight approval step before any
money leaves the business.

## 3. Core Experience (the canonical example)

> "Create a $3,000 project for Acme with three milestones: $1,000 upfront,
> $1,200 after development, and $800 at delivery. Invoice the upfront
> milestone, remind Acme in seven days if unpaid, and prepare a $300 payout
> to my designer after payment arrives."

What the platform must do with this sentence:

1. **Parse** it into a structured, strictly-typed draft plan (project,
   milestones, an invoice action, a reminder rule, a conditional payout
   draft) — via the AI reasoning layer. The draft is inert: nothing exists
   yet except a proposal.
2. **Validate** the draft: milestone amounts must sum to the project total,
   currencies must match, amounts must be positive, the payout recipient
   must resolve to a known or newly-declared payee.
3. **Present** the plan to the user for confirmation/edit — this is the
   human-in-the-loop checkpoint before anything durable is created.
4. **Materialize** the plan on confirmation: create the `Project` and its
   `Milestone`s (TrustFlow), create a real PayPal invoice for the upfront
   milestone and send it (Autopilot), persist a durable scheduled reminder
   job for day 7 (Autopilot + durable jobs), and create a **payout draft**
   plus a **pending approval request** gated on the invoice being paid
   (SpendPilot) — the payout is *never* executed automatically.
5. **Operate**: monitor the invoice via verified PayPal webhooks (with
   reconciliation polling as a fallback), fire the reminder if still unpaid
   at day 7, and once the invoice is paid, surface the payout for a human to
   explicitly approve. Only an explicit, current approval triggers the
   actual PayPal Payouts call.
6. **Record**: every transition (plan created, plan confirmed, invoice sent,
   reminder sent, payment detected, approval requested, approval granted,
   payout sent, payout succeeded/failed) is written to an immutable audit
   log tied to the workspace and the acting user.

## 4. Feature Inventory by Subsystem

### 4.1 PayPal Autopilot (payments core)
- Create & send PayPal invoices (PayPal Invoicing API v2) tied to a milestone.
- Track invoice lifecycle via verified webhooks: sent, viewed, paid, cancelled, refunded.
- Reminder scheduling ("remind in N days if unpaid") as a durable, persisted job — not a fire-and-forget Celery `countdown` call.
- Contractor/subcontractor payouts (PayPal Payouts API) — always draft → approval → execution.
- Payment reconciliation job that periodically re-checks invoice status from PayPal as a safety net against missed/duplicated webhooks.

### 4.2 TrustFlow (contracts & projects)
- Projects with a total contract value, currency, dates, a customer, and a status derived from the milestones (`draft`, `active`, `completed`, `cancelled`).
- Milestones with amount, trigger condition (upfront / on-event / on-delivery), sequence, and a fixed state machine. Acceptance authorizes an invoice draft.
- Payment conditions linking a milestone to an invoicing action and, optionally, to downstream payouts.
- Contract upload for PDF and DOCX. The extraction is review data, not a legal verification, and the file cannot change policy or become an instruction.

### 4.3 SpendPilot (policy, approval, intelligence)
- Workspace spending policy: per-transaction, daily, monthly, and workspace limits, allowed currencies, an approved-recipient list, restricted action types, and an emergency pause. The default autonomy level is Assistant.
- Payouts always require a fresh approval of the exact action. An Autopilot threshold can cover a non-payout action. It cannot waive payout approval.
- Approval queue: request, approve, reject, cancel, and expire. The approval binds the action type, recipient, amount, currency, target, workspace, and approving identity. A changed amount or recipient needs a new approval.
- Approval decision audit (who approved, rejected, cancelled, or expired the request, and when).
- Financial intelligence: per-workspace view of invoiced vs. paid vs. overdue amounts, pending payout exposure. MVP is read-model queries over existing tables, not a separate analytics pipeline.
- Workflow automation: the durable workflow engine that threads AI-planned steps through TrustFlow and Autopilot.

### 4.4 AI Command Layer
- Single natural-language command box that produces a reviewable structured plan (see §3).
- Conversation-free for MVP: one instruction → one plan → one review → one confirm. Multi-turn clarification is post-hackathon scope.
- Provider-adapter architecture so the underlying LLM vendor is swappable and mockable in tests.

## 5. MVP Scope (hackathon)

**In scope:**
- Single-workspace-per-user minimum viable multi-tenancy (workspace isolation enforced server-side even though onboarding UI for multi-user workspaces is minimal).
- Email/password auth, one role distinction: member vs. workspace owner (owner can approve payouts).
- Natural-language → structured `WorkflowPlanDraft` → human review/edit → confirm → materialized Project/Milestones/Invoice/ReminderJob/PayoutDraft+ApprovalRequest.
- Real PayPal Sandbox integration: OAuth2 client-credentials, Invoicing API v2 (create/send/remind/get), Payouts API v1 (create batch, get status), Webhooks v1 (subscribe + signature verification).
- Durable reminder scheduling (Postgres-backed job table + Celery execution), with at-least-daily reconciliation.
- Payout approval queue UI with explicit approve/reject and mandatory reason.
- Full audit trail viewer for a workspace.
- Idempotent financial endpoints; webhook replay protection.
- pytest coverage of validation, idempotency, and workflow state machine logic; Playwright coverage of the core happy path (plan → confirm → invoice created, approval → payout dispatched against a stubbed PayPal in CI, real sandbox exercised manually/in a tagged test).

**Explicitly out of scope for MVP** (see §6):
- Multi-currency conversion, non-2-decimal currencies (e.g. JPY).
- Multi-user workspace invitation flows, RBAC beyond owner/member.
- Partial payments, invoice line-item editing UI, refunds UI.
- Recurring invoices, retries UI, subscriptions.
- Real production PayPal credentials — **sandbox only**, enforced in config.
- Automatic (non-approved) payouts of any kind, at any amount.
- Multi-turn conversational plan editing by the AI (user edits the structured form directly instead).

## 6. MVP vs. Post-Hackathon Scope

| Capability | MVP | Post-Hackathon |
|---|---|---|
| Invoicing | Single invoice per milestone, USD, PayPal-hosted payment page | Multi-line invoices, partial payments, multi-currency |
| Reminders | Fixed "remind in N days if unpaid" rule, max per PayPal's own 2/day cap | Configurable cadence/backoff, escalation (email + in-app + SMS) |
| Payouts | Single recipient per payout draft, manual payee registration | Payee directory with saved PayPal payout destinations, batch payouts, split payouts |
| Approvals | Owner approve, reject, cancel, and expire. Exact amount, currency, recipient, and target. Payouts cannot skip this | Multi-approver thresholds, delegated approval |
| AI layer | Single-shot instruction → plan → human edit | Multi-turn clarification, plan revision via chat, proactive suggestions ("this invoice is 10 days overdue, send a reminder?") |
| Workflow engine | Linear plan with a handful of step types | General DAG of steps with conditional branches, retries with backoff policies |
| Multi-tenancy | Workspace isolation, single owner role | Full RBAC, SSO, multiple workspaces per user with switcher |
| Financial intelligence | Deterministic cash snapshot, projections with assumptions/uncertainty, figure-backed insights and alerts | Live PayPal balance reads, anomaly detection beyond rule thresholds |
| Deployment | Docker Compose, local/sandbox | Managed cloud deployment, autoscaling workers, production PayPal app review |

## 7. Success Metrics (hackathon demo)

1. The canonical example sentence, typed into the UI, produces a correct structured plan within one AI call.
2. Confirming the plan creates real rows in Postgres (project, milestones, invoice) and a real PayPal Sandbox invoice with a working hosted payment link.
3. Paying that sandbox invoice (as the simulated buyer) triggers a verified webhook that flips the invoice to PAID and surfaces the payout in the approval queue — without duplicate processing even if the webhook is delivered twice.
4. Approving the payout in the UI triggers a real PayPal Sandbox payout call, and the result (success/failure) is reflected truthfully — never fabricated.
5. The audit log shows a complete, legible history of the above for the workspace.
6. Automated tests pass in CI; the implementation status doc accurately reflects what is VERIFIED vs IMPLEMENTED vs NOT STARTED at demo time.

## 8. Non-Goals (explicit)

- Not a general accounting system (no GAAP ledger, no tax forms).
- Not a replacement for PayPal's own dashboard — it is an automation layer on top of it.
- Not a bank; no custody of funds outside PayPal's own systems.
- Not aiming for payment-method diversity (cards, ACH direct) in MVP — PayPal account/PayPal-hosted checkout only.
