SHELL := /bin/bash

PNPM := ../scripts/pnpm.sh
PYTHON := uv run --python 3.12

.DEFAULT_GOAL := help

.PHONY: help check-env check-test-db setup infra-up infra-down infra-status db-migrate-test dev test lint type typecheck build check

help:
	@printf '%s\n' \
		'PDOS root commands:' \
		'  make setup      Validate tools and install locked dependencies' \
		'  make infra-up   Start local PostgreSQL and MinIO' \
		'  make db-migrate-test  Upgrade only the isolated pdos_test database' \
		'  make dev        Run the web and API development processes' \
		'  make test       Run all unit tests' \
		'  make lint       Run all lint and formatting checks' \
		'  make type       Run all static type checks' \
		'  make build      Build/compile all applications' \
		'  make check      Run lint, type, test, and build gates'

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
