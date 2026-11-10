"""Celery application instance.

Run the worker with: `celery -A app.workers.celery_app worker --loglevel=INFO`
Run the beat scheduler with: `celery -A app.workers.celery_app beat --loglevel=INFO`

Redis is the broker and result backend only. Workflow state, reminders,
and provider ids live in PostgreSQL.
"""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "autopilot",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "dispatch-due-scheduled-actions": {
            "task": "app.workers.dispatch_due_scheduled_actions",
            "schedule": 60.0,
        }
    },
)
