# Production-oriented API / worker / scheduler image (sandbox PayPal only).
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:${PATH}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
COPY scripts/docker-entrypoint.sh /docker-entrypoint.sh
RUN uv sync --frozen --no-dev \
    && chmod +x /docker-entrypoint.sh

RUN useradd --system --uid 10001 --create-home autopilot \
    && chown autopilot:autopilot /app
USER autopilot

EXPOSE 8000
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["api"]
