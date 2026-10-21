UV ?= uv

.PHONY: setup dev dev-api-fakes dev-database migrate test test-db cleanup-db contracts lint

setup:
	$(UV) sync --project backend --locked

dev:
	$(UV) run --project backend --frozen uvicorn app.integration:create_app --factory --host 127.0.0.1 --port 8000

dev-api-fakes:
	$(UV) run --project backend --frozen uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000

dev-database:
	$(UV) run --project backend --frozen --extra database uvicorn app.database:create_app --factory --host 127.0.0.1 --port 8000

migrate:
	$(UV) run --project backend --frozen --extra database alembic -c backend/alembic.ini upgrade head

test-db:
	@test -n "$$RD_TEST_DATABASE_URL" || { echo "Set RD_TEST_DATABASE_URL to a migrated disposable PostgreSQL test database"; exit 1; }
	$(UV) run --project backend --frozen --extra database pytest -q backend/tests/platform/test_postgres.py backend/tests/platform/test_postgres_concurrency.py

cleanup-db:
	$(UV) run --project backend --frozen --extra database python -m app.database

test:
	$(UV) run --project backend --frozen pytest -q

contracts:
	$(UV) run --project backend --frozen python -m app.tools.check_contracts

lint:
	$(UV) run --project backend --frozen ruff check backend
	$(UV) run --project backend --frozen ruff format --check backend
