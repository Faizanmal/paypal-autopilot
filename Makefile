.PHONY: install test lint typecheck format migrate up config config-prod

install:
	cd apps/api && uv sync
	cd apps/web && npm install

test:
	cd apps/api && uv run pytest -q

lint:
	cd apps/api && uv run ruff check .
	cd apps/web && npm run lint

format:
	cd apps/api && uv run ruff format .
	cd apps/api && uv run ruff check --fix .

typecheck:
	cd apps/api && uv run mypy app
	cd apps/web && npm run typecheck

migrate:
	cd apps/api && uv run alembic upgrade head

up:
	docker compose up -d postgres redis

config:
	docker compose -f docker-compose.yml config --quiet

# Validates production-style compose only. Does not build or deploy.
# Requires POSTGRES_PASSWORD, CORS_ORIGINS, NEXT_PUBLIC_API_BASE_URL in the environment.
config-prod:
	docker compose -f docker-compose.prod.yml config --quiet
