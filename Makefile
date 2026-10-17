UV ?= uv

.PHONY: setup dev dev-api-fakes test contracts lint

setup:
	$(UV) sync --project backend --locked

dev:
	$(UV) run --project backend --frozen uvicorn app.integration:create_app --factory --host 127.0.0.1 --port 8000

dev-api-fakes:
	$(UV) run --project backend --frozen uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000

test:
	$(UV) run --project backend --frozen pytest -q

contracts:
	$(UV) run --project backend --frozen python -m app.tools.check_contracts

lint:
	$(UV) run --project backend --frozen ruff check backend
	$(UV) run --project backend --frozen ruff format --check backend
