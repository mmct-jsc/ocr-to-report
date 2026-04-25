# OCR-to-Report — developer entrypoint
# All targets idempotent; safe to re-run.

SHELL := /bin/bash
.DEFAULT_GOAL := help
.PHONY: help install sync dev down logs ps clean fmt lint typecheck test test-unit \
        test-property test-integration test-contract test-e2e cov security audit \
        ci openapi sdk-ts seed shell-api shell-db migrate

# ─── Colors ──────────────────────────────────────────────────
B := \033[1m
G := \033[32m
Y := \033[33m
R := \033[31m
N := \033[0m

help: ## Show this help
	@printf "$(B)OCR-to-Report — Make targets$(N)\n\n"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  $(G)%-20s$(N) %s\n", $$1, $$2}'
	@printf "\n"

# ─── Bootstrap ───────────────────────────────────────────────
install: ## Install all uv workspace deps + pre-commit hooks
	uv sync --all-packages --group dev
	uv run pre-commit install --install-hooks

sync: ## Re-sync uv workspace (run after dependency changes)
	uv sync --all-packages --group dev

# ─── Dev stack ───────────────────────────────────────────────
dev: ## Bring up full dev stack (postgres + redis + minio + api)
	@if [ ! -f .env ]; then cp .env.example .env && printf "$(Y)Created .env from .env.example — fill in secrets$(N)\n"; fi
	docker compose up -d --build
	@printf "\n$(G)Stack up.$(N) Try: $(B)curl http://localhost:8000/health$(N)\n"

down: ## Stop dev stack
	docker compose down

logs: ## Tail dev stack logs
	docker compose logs -f --tail=200

ps: ## Show stack status
	docker compose ps

clean: down ## Stop stack + remove volumes (DESTRUCTIVE — wipes local DB/blob)
	docker compose down -v
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage .hypothesis

# ─── Quality gates ───────────────────────────────────────────
fmt: ## Auto-format code (ruff format + import sort)
	uv run ruff format .
	uv run ruff check --fix .

lint: ## Lint check (no fixes; CI mode)
	uv run ruff format --check .
	uv run ruff check .

typecheck: ## mypy --strict on all packages
	uv run mypy packages

import-check: ## Verify dependency direction (import-linter)
	PYTHONIOENCODING=utf-8 uv run lint-imports

# ─── Tests ───────────────────────────────────────────────────
test: test-unit test-property ## Fast suite (unit + property only, <10s)

test-unit: ## Unit tests
	uv run pytest -m "unit or not (property or integration or contract or e2e or load)"

test-property: ## Hypothesis property tests
	uv run pytest -m property

test-integration: ## Integration tests (testcontainers required)
	uv run pytest -m integration

test-contract: ## OpenAPI contract tests (schemathesis)
	uv run pytest -m contract

test-e2e: ## E2E tests against live providers (LIVE_TESTS=1 + budget)
	LIVE_TESTS=1 uv run pytest -m e2e

cov: ## Run tests with coverage report
	uv run pytest --cov --cov-report=term-missing --cov-report=html

# ─── Security ────────────────────────────────────────────────
security: ## Static security checks (bandit + ruff S rules)
	uv run bandit -c pyproject.toml -r packages

audit: ## Dependency vulnerability audit
	# CVE-2026-3219 in pip itself has no fixed version; pip is a build-time tool not used
	# at runtime by this app (we use uv). Re-evaluate on every uv sync.
	uv run pip-audit --ignore-vuln CVE-2026-3219

# ─── CI emulation ────────────────────────────────────────────
ci: lint typecheck import-check security audit test cov ## Run every gate the CI runs

# ─── Generated artifacts ─────────────────────────────────────
openapi: ## Export OpenAPI 3.1 spec to docs/api/openapi.json
	@mkdir -p docs/api
	uv run python -m ocr_to_report.api.openapi.export > docs/api/openapi.json
	@printf "$(G)Wrote$(N) docs/api/openapi.json\n"

sdk-ts: openapi ## Re-generate TypeScript SDK from current OpenAPI
	cd sdk-ts && pnpm install && pnpm run generate

# ─── Database ────────────────────────────────────────────────
migrate: ## Apply Alembic migrations
	uv run alembic upgrade head

migration: ## Create new Alembic migration: make migration name="add_xyz"
	uv run alembic revision --autogenerate -m "$(name)"

shell-db: ## psql shell into dev database
	docker compose exec postgres psql -U ocr2r -d ocr2r

# ─── Seed ────────────────────────────────────────────────────
seed: ## Seed dev tenant + API key (prints credentials to stdout)
	uv run python -m ocr_to_report.cli.seed

# ─── Quick checks ────────────────────────────────────────────
shell-api: ## Open shell inside running api container
	docker compose exec api bash
