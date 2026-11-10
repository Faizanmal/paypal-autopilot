"""SpendPilot module: spending policy, approvals, payouts, financial intelligence.

Owns: `PayoutDraft`, `ApprovalRequest`, `PayoutExecution` ORM models; the
`PayoutExecutionService` which is the *only* caller of the PayPal Payouts
client and enforces the trigger+approval+idempotency gate described in
docs/SECURITY.md §5; financial intelligence read-models (invoiced vs.
paid vs. overdue, pending payout exposure).

Status: NOT STARTED.
"""
