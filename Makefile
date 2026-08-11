SHELL := /bin/bash

PNPM := ../scripts/pnpm.sh
PYTHON := uv run --python 3.12

.DEFAULT_GOAL := help

.PHONY: help check-env setup dev test lint type typecheck build check

help:
	@printf '%s\n' \
		'PDOS root commands:' \
		'  make setup      Validate tools and install locked dependencies' \
		'  make dev        Run the web and API development processes' \
		'  make test       Run all unit tests' \
		'  make lint       Run all lint and formatting checks' \
		'  make type       Run all static type checks' \
		'  make build      Build/compile all applications' \
		'  make check      Run lint, type, test, and build gates'

check-env:
	@./scripts/check-env.sh

setup: check-env
	@test -f .env || cp .env.example .env
	cd web && $(PNPM) install --frozen-lockfile
	cd server && uv sync --frozen --python 3.12 --group dev

dev: check-env
	@./scripts/dev.sh

test:
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
