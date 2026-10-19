# Common tasks. On Windows without `make`, run the commands after each target directly (Git Bash or PowerShell).
API = uv run --project apps/api

.PHONY: setup db db-stop migrate demo api web test test-unit lint eval eval-offline mcp docker-up docker-down

setup:            ## install backend + frontend dependencies, create .env
	uv sync --project apps/api --extra eval
	cd apps/web && npm install
	test -f .env || cp .env.example .env
	test -f apps/web/.env.local || printf 'API_BASE_URL=http://127.0.0.1:8000\nAPI_TOKEN=dev-demo-token-change-me\n' > apps/web/.env.local

db:               ## start local PostgreSQL + pgvector (no Docker needed)
	$(API) python scripts/dev_db.py start

db-stop:
	$(API) python scripts/dev_db.py stop

migrate:          ## apply Alembic migrations
	cd apps/api && uv run alembic upgrade head

demo:             ## load the synthetic demo tenant (customers, deals, conversations, policies) + risk scores
	$(API) python -m app.cli load-demo

api:              ## FastAPI on :8000 (docs at /docs)
	cd apps/api && uv run uvicorn app.main:app --reload --port 8000

web:              ## Next.js on :3000
	cd apps/web && npm run dev

test:             ## unit + integration + e2e (needs the local DB running)
	cd apps/api && uv run pytest -q

test-unit:
	cd apps/api && uv run pytest -q tests/unit

lint:
	cd apps/api && uv run ruff check app tests ../../evals && uv run ruff format --check app tests ../../evals
	cd apps/web && npx tsc --noEmit && npx eslint .

eval:             ## all evaluation suites (live if GROQ_API_KEY is set, else offline)
	$(API) python -m evals.run

eval-offline:
	$(API) python -m evals.run --mode offline

mcp:              ## MCP server over stdio
	$(API) python -m app.mcp

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down
