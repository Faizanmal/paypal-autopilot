"""Audit log service.

Owns: `AuditLog` ORM model and the single `record(...)` entry point
used by every other module to write an insert-only audit trail entry.
`financial_details(...)` normalizes initiator / AI / approval / policy /
PayPal / result fields for the cash-flow and audit UIs.
See docs/SECURITY.md §8.
"""
