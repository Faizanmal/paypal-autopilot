"""PayPal Autopilot module: invoicing, payment monitoring, reminders.

Owns: `Invoice`, `InvoiceEvent`, `ScheduledJob` ORM models; orchestration
of the PayPal Invoicing API via `app.integrations.paypal`; the webhook
handler's domain-level "mark invoice paid" entry point (also used by the
reconciliation poller, so there is exactly one code path for that
transition); durable reminder scheduling.

Status: NOT STARTED.
"""
