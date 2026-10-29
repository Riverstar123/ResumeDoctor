UV ?= uv

.PHONY: setup dev dev-synthetic dev-api-fakes dev-database worker migrate test test-db test-security test-e2e-qa03 test-e2e-qa03-db test-e2e-ai03 cleanup-db contracts lint

setup:
	$(UV) sync --project backend --locked

dev:
	$(UV) run --project backend --frozen --extra database uvicorn app.database:create_app --factory --host 127.0.0.1 --port 8000

dev-synthetic:
	$(UV) run --project backend --frozen uvicorn app.integration:create_app --factory --host 127.0.0.1 --port 8000

dev-api-fakes:
	$(UV) run --project backend --frozen uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000

dev-database:
	$(UV) run --project backend --frozen --extra database uvicorn app.database:create_app --factory --host 127.0.0.1 --port 8000

worker:
	$(UV) run --project backend --frozen --extra database python -m app.platform.jobs

migrate:
	$(UV) run --project backend --frozen --extra database alembic -c backend/alembic.ini upgrade head

test-db:
	@test -n "$$RD_TEST_DATABASE_URL" || { echo "Set RD_TEST_DATABASE_URL to a migrated disposable PostgreSQL test database"; exit 1; }
	$(UV) run --project backend --frozen --extra database pytest -q backend/tests/platform/test_postgres.py backend/tests/platform/test_postgres_concurrency.py backend/tests/platform/test_jobs.py backend/tests/platform/test_int02.py backend/tests/platform/test_profile_sources.py

test-security:
	@test -n "$$RD_TEST_DATABASE_URL" || { echo "Set RD_TEST_DATABASE_URL to a migrated disposable PostgreSQL test database"; exit 1; }
	LLM_MODE=fake $(UV) run --project backend --frozen --extra database pytest -q backend/tests

cleanup-db:
	$(UV) run --project backend --frozen --extra database python -m app.database

# QA-03：真实 FastAPI fake 栈 + 真实 UI；Playwright 自启四个变体后端，无需 PostgreSQL 或凭证。
test-e2e-qa03:
	cd frontend && npm run test:e2e:qa03

# QA-03 正式栈：app.database + 独立 worker + 一次性临时 PostgreSQL（需 RD_QA03_PG_HOME）。
test-e2e-qa03-db:
	cd frontend && npm run test:e2e:qa03:db

# AI-03：默认 fake 开发调试；RD_AI03_MODE=real 才是真实模型验收（另需 backend/.env 与 RD_AI03_NOTICE）。
test-e2e-ai03:
	cd frontend && npm run test:e2e:ai03

test:
	$(UV) run --project backend --frozen pytest -q

contracts:
	$(UV) run --project backend --frozen python -m app.tools.check_contracts

lint:
	$(UV) run --project backend --frozen ruff check backend
	$(UV) run --project backend --frozen ruff format --check backend
