"""Celery application and task registration.

Celery is the *execution mechanism* for durable jobs, not their source of
truth. `scheduled_jobs` in PostgreSQL is authoritative; see
docs/ARCHITECTURE.md §6. Task modules (added as modules land) must
re-validate job state against Postgres before acting.
"""
