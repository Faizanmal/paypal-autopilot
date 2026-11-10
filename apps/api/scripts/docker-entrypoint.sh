#!/bin/sh
set -eu

role="${1:-api}"

case "$role" in
  migrate)
    echo "Running alembic upgrade head"
    alembic upgrade head
    ;;
  api)
    echo "Running alembic upgrade head before API start"
    alembic upgrade head
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
    ;;
  worker)
    exec celery -A app.workers.celery_app worker --loglevel=INFO --concurrency="${CELERY_WORKER_CONCURRENCY:-2}"
    ;;
  scheduler)
    exec celery -A app.workers.celery_app beat --loglevel=INFO
    ;;
  *)
    exec "$@"
    ;;
esac
