SHELL := /bin/bash

PNPM := ../scripts/pnpm.sh
PYTHON := uv run --python 3.12

.DEFAULT_GOAL := help

.PHONY: help check-env check-test-db setup infra-up infra-down infra-status db-migrate-test dev production-preflight smoke-app smoke-production test lint type typecheck build check sprint2-removal-drill sprint2-redteam verify-s0-1 verify-sprint-0

help:
	@printf '%s\n' \
		'PDOS root commands:' \
		'  make setup      Validate tools and install locked dependencies' \
		'  make infra-up   Start local PostgreSQL and MinIO' \
		'  make db-migrate-test  Upgrade only the isolated pdos_test database' \
		'  make dev        Run the web and API development processes' \
		'  make production-preflight  Validate .env.production before migration/deploy' \
		'  make smoke-app  Run isolated web and API runtime smoke checks' \
		'  make smoke-production  Build and smoke the production containers against pdos_test' \
		'  make test       Run all unit tests' \
		'  make lint       Run all lint and formatting checks' \
		'  make type       Run all static type checks' \
		'  make build      Build/compile all applications' \
		'  make check      Run lint, type, test, and build gates' \
		'  make sprint2-removal-drill  Verify visible model removal degradation' \
		'  make sprint2-redteam  Verify Agent write and tenant boundaries' \
		'  make verify-sprint-0  Run every local Sprint 0 gate, including production containers'

check-env:
	@./scripts/check-env.sh

check-test-db:
	cd server && $(PYTHON) python -m app.db.test_safety

setup: check-env
	@test -f .env || cp .env.example .env
	cd web && $(PNPM) install --frozen-lockfile
	cd server && uv sync --frozen --python 3.12 --group dev

infra-up:
	docker compose up -d --wait postgres minio
	docker compose exec -T minio mc alias set local http://localhost:9000 minioadmin minioadmin >/dev/null
	docker compose exec -T minio mc mb --ignore-existing local/pdos-files

infra-down:
	docker compose down

infra-status:
	docker compose ps

db-migrate-test: check-test-db
	@$(MAKE) infra-up
	cd server && $(PYTHON) python -m scripts.migrate_test

dev: check-env
	@$(MAKE) infra-up
	@./scripts/dev.sh

production-preflight: check-env
	cd server && $(PYTHON) python -m scripts.check_production_env ../.env.production
	docker compose --env-file .env.production -f compose.production.yaml config --quiet

smoke-app: check-env
	@./scripts/smoke-app.sh

smoke-production: check-env
	@$(MAKE) db-migrate-test
	@./scripts/smoke-production.sh

test: check-test-db
	cd web && $(PNPM) test
	cd server && $(PYTHON) pytest

lint:
	cd web && $(PNPM) lint
	cd server && $(PYTHON) ruff check .
	cd server && $(PYTHON) ruff format --check .

type: typecheck

typecheck:
	cd web && $(PNPM) typecheck
	cd server && $(PYTHON) mypy

build:
	cd web && $(PNPM) build
	cd server && $(PYTHON) python -m compileall -q app migrations

check: lint typecheck test build

sprint2-removal-drill: check-test-db
	cd server && $(PYTHON) python -m scripts.sprint2_removal_drill

sprint2-redteam: check-test-db
	cd server && $(PYTHON) pytest tests/test_agent_database_security.py

verify-s0-1:
	@$(MAKE) check-env
	@$(MAKE) db-migrate-test
	@$(MAKE) check
	@$(MAKE) smoke-app

verify-sprint-0: verify-s0-1
	@$(MAKE) smoke-production
