import asyncio
from unittest.mock import Mock

import pytest

from app.workers import health, tasks


def test_repeated_tasks_release_loop_bound_connections(monkeypatch):
    active_loop = None
    disposals = []

    async def dispatch():
        nonlocal active_loop
        loop = asyncio.get_running_loop()
        assert active_loop is None or active_loop is loop
        active_loop = loop
        return 0

    async def dispose():
        nonlocal active_loop
        assert active_loop is asyncio.get_running_loop()
        disposals.append(active_loop)
        active_loop = None

    monkeypatch.setattr(tasks, "_dispatch", dispatch)
    monkeypatch.setattr(tasks, "get_engine", lambda: Mock(dispose=dispose))
    assert tasks.dispatch_due_scheduled_actions.run() == 0
    assert tasks.dispatch_due_scheduled_actions.run() == 0
    assert len(disposals) == 2
    assert disposals[0] is not disposals[1]
    assert all(loop.is_closed() for loop in disposals)


def test_failed_task_disposes_before_loop_closes(monkeypatch):
    disposed = []

    async def dispatch():
        raise ValueError("dispatch failed")

    async def dispose():
        disposed.append(asyncio.get_running_loop())

    monkeypatch.setattr(tasks, "_dispatch", dispatch)
    monkeypatch.setattr(tasks, "get_engine", lambda: Mock(dispose=dispose))
    with pytest.raises(ValueError, match="dispatch failed"):
        tasks.dispatch_due_scheduled_actions.run()
    assert len(disposed) == 1
    assert disposed[0].is_closed()


@pytest.mark.parametrize("replies, expected", [
    ([{"celery@this-worker": {"ok": "pong"}}], True),
    ([{"celery@another-worker": {"ok": "pong"}}], False),
    ([{"celery@this-worker": {"error": "unavailable"}}], False),
    ([], False),
])
def test_health_requires_own_worker_reply(monkeypatch, replies, expected):
    ping = Mock(return_value=replies)
    monkeypatch.setattr(health, "default_nodename", lambda _: "celery@this-worker")
    monkeypatch.setattr(health.celery_app.control, "ping", ping)
    assert health.worker_is_healthy() is expected
    ping.assert_called_once_with(destination=["celery@this-worker"], timeout=10)


def test_health_fails_when_broker_is_unavailable(monkeypatch):
    monkeypatch.setattr(health.celery_app.control, "ping", Mock(side_effect=OSError))
    assert health.worker_is_healthy() is False
