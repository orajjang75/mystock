.PHONY: install db-up db-down migrate scan ingest backfill-universe backtest gen-api dev dev-backend dev-frontend test e2e e2e-screener test-vectorbt lint format

BACKEND := backend
FRONTEND := frontend

install:
	cd $(BACKEND) && uv sync
	cd $(FRONTEND) && npm ci

db-up:
	docker compose up -d --wait

db-down:
	docker compose down

migrate:
	cd $(BACKEND) && uv run alembic upgrade head

# Export the API schema and regenerate the frontend's TypeScript types from it.
gen-api:
	cd $(BACKEND) && uv run python -m app.export_openapi ../$(FRONTEND)/openapi.json
	cd $(FRONTEND) && npm run gen:api

# Collects market data from the ADAPTER source (mock by default) into the database.
scan:
	cd $(BACKEND) && uv run python -m app.jobs.daily_scan --force

ingest:
	cd $(BACKEND) && uv run python -m app.jobs.ingest

# Fills universe_snapshots for past dates (point-in-time universe of the backtest), then rerun ingest.
# Needs an adapter that can answer "who was big on this date" (mock and pykrx can).
backfill-universe:
	cd $(BACKEND) && uv run python -m app.backtest.backfill $(ARGS)

# A backtest from the terminal; the report goes to docs/backtest-reports/. ARGS="--bar 60m --start 2026-07-01"
backtest:
	cd $(BACKEND) && uv run python -m app.backtest $(ARGS)

# Starts PostgreSQL, applies migrations, then runs the API (:8000) and the Vite dev server (:5173).
dev: db-up migrate
	$(MAKE) -j2 dev-backend dev-frontend

dev-backend:
	cd $(BACKEND) && uv run uvicorn app.main:create_app --factory --reload --port 8000

dev-frontend:
	cd $(FRONTEND) && npm run dev

# The backtest tests in a Linux container where vectorbt installs (the vectorbt engine must give the
# same numbers as the pandas one; Intel Macs cannot install it). Needs Docker.
test-vectorbt:
	docker build -q -t mystock-vectorbt -f $(BACKEND)/docker/vectorbt.Dockerfile $(BACKEND)
	docker run --rm -v $(PWD)/$(BACKEND):/app:ro mystock-vectorbt

# Browser (Playwright) tests of the holdings, alerts and sell/rebuy cycle screens. They start their
# own backend on :8010 (mock market, mock clock, database mystock_e2e) and Vite on :5180, so only
# PostgreSQL has to be up (make db-up). Screenshots land in e2e-shots/.
e2e:
	cd $(FRONTEND) && npx playwright test

# The older check of the screener and dashboard against the running `make dev` servers.
e2e-screener:
	cd $(FRONTEND) && node e2e/screener.mjs ../e2e-shots

# The backend migration test needs PostgreSQL (make db-up); it is skipped when the server is unreachable.
test:
	cd $(BACKEND) && uv run pytest
	cd $(FRONTEND) && npm test

lint:
	cd $(BACKEND) && uv run ruff check . && uv run ruff format --check . && uv run mypy
	cd $(FRONTEND) && npm run lint && npx tsc -b

format:
	cd $(BACKEND) && uv run ruff check --fix . && uv run ruff format .
