"""Durable workflow runs.

Confirmed agent plans materialize `Workflow` and `WorkflowStep` rows.
`engine` resumes steps that wait on a verified PayPal payment.
"""
