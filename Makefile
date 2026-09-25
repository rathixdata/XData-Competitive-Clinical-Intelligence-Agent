# XData CI Agent - developer entrypoints.  `make help` lists targets.
SHELL := /bin/bash
.DEFAULT_GOAL := help

ROOT        := $(abspath .)
VENV_PY     := $(ROOT)/.venv/bin/python
PY          := $(if $(wildcard $(VENV_PY)),$(VENV_PY),python3)
ENV_FILE    := $(ROOT)/.env
# Compose interpolation reads ../.env only when passed explicitly (project dir is deploy/).
COMPOSE     := docker compose -f deploy/docker-compose.yml $(if $(wildcard $(ENV_FILE)),--env-file $(ENV_FILE))
COMPOSE_OBS := $(COMPOSE) -f deploy/docker-compose.observability.yml
# Load ../.env into the shell for host-side commands (the app reads ./.env relative to cwd).
LOAD_ENV    := set -a; [ -f "$(ENV_FILE)" ] && . "$(ENV_FILE)"; set +a;

TEST_DATABASE_URL ?= postgresql+psycopg://xdata:xdata@localhost:5432/xdata_test
TEST_REDIS_URL    ?= redis://localhost:6379/15

.PHONY: help env up up-obs down down-v logs ps migrate seed build test test-db lint fmt eval dev-api dev-worker dev-web

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

env: ## Create .env from .env.example if missing
	@[ -f .env ] && echo ".env exists" || (cp .env.example .env && echo "created .env")

# ---------------------------------------------------------------- stack
up: env ## Build and start the full stack (web on :8080, api on :8000)
	$(COMPOSE) up -d --build
	@echo "UI: http://localhost:8080   API: http://localhost:8000/docs"

up-obs: env ## Stack + Prometheus (:9090) + Grafana (:3000)
	$(COMPOSE_OBS) up -d --build

down: ## Stop the stack (keeps volumes)
	$(COMPOSE_OBS) down --remove-orphans

down-v: ## Stop the stack and DELETE volumes (database, objects)
	$(COMPOSE_OBS) down -v --remove-orphans

logs: ## Follow logs (S=service to filter, e.g. make logs S=api)
	$(COMPOSE) logs -f --tail=200 $(S)

ps: ## Show stack status
	$(COMPOSE) ps

migrate: ## Run alembic upgrade head in the stack
	$(COMPOSE) run --rm migrate

seed: ## Load the demo tenant into the stack
	$(COMPOSE) --profile seed run --rm seed

build: ## Build the backend and web images
	$(COMPOSE) build

# ---------------------------------------------------------------- quality
test-db: ## Create the xdata_test database in the compose postgres (idempotent)
	@$(COMPOSE) exec -T postgres psql -U postgres -v ON_ERROR_STOP=1 -tc \
	  "SELECT 1 FROM pg_database WHERE datname='xdata_test'" | grep -q 1 || \
	  $(COMPOSE) exec -T postgres psql -U postgres -v ON_ERROR_STOP=1 \
	    -c "CREATE DATABASE xdata_test OWNER xdata"
	@$(COMPOSE) exec -T postgres psql -U postgres -d xdata_test -v ON_ERROR_STOP=1 \
	  -c "CREATE EXTENSION IF NOT EXISTS vector" -c "CREATE EXTENSION IF NOT EXISTS pg_trgm" \
	  -c "ALTER SCHEMA public OWNER TO xdata" >/dev/null
	@echo "xdata_test ready"

test: ## Backend tests (needs postgres + redis: `make up` then `make test-db`)
	cd backend && XDATA_ENV=test XDATA_DATABASE_URL="$(TEST_DATABASE_URL)" \
	  XDATA_REDIS_URL="$(TEST_REDIS_URL)" XDATA_LLM_PROVIDER=offline XDATA_EMBEDDING_PROVIDER=hashing \
	  $(PY) -m pytest tests -q --cov=app --cov-report=term-missing $(ARGS)

lint: ## Ruff + frontend lint/typecheck
	$(PY) -m ruff check backend
	@if [ -d frontend/node_modules ]; then cd frontend && npm run lint && npm run typecheck; \
	  else echo "skip frontend lint (run npm ci in frontend/)"; fi

fmt: ## Auto-format backend (ruff) and frontend (if a format script exists)
	$(PY) -m ruff check --fix backend
	$(PY) -m ruff format backend
	@if [ -d frontend/node_modules ]; then cd frontend && npm run --if-present format; fi

eval: ## Offline golden AI evaluation suite (same gate as CI)
	$(LOAD_ENV) XDATA_LLM_PROVIDER=offline XDATA_EMBEDDING_PROVIDER=hashing \
	  $(PY) -m evals.run --suite golden --offline $(ARGS)

# ---------------------------------------------------------------- host dev loop
dev-api: ## API with autoreload on the host (uses ./.venv if present; DB/redis from `make up`)
	cd backend && $(LOAD_ENV) $(PY) -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

dev-worker: ## Celery worker on the host
	cd backend && $(LOAD_ENV) $(PY) -m celery -A app.workers.celery_app:celery_app worker -l INFO \
	  -Q default,ingest,intel,alerts

dev-web: ## Vite dev server (http://localhost:5173)
	cd frontend && npm run dev
