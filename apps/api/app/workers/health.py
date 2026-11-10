"""Check that this container's worker responds through its broker."""

from celery.utils.nodenames import default_nodename

from app.workers.celery_app import celery_app


def worker_is_healthy() -> bool:
    node = default_nodename("")
    try:
        replies = celery_app.control.ping(destination=[node], timeout=10)
        return any(reply.get(node, {}).get("ok") == "pong" for reply in replies)
    except Exception:
        return False


if __name__ == "__main__":
    raise SystemExit(0 if worker_is_healthy() else 1)
