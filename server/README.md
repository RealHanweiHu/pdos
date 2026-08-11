# PDOS Server

The server workspace contains the FastAPI control plane, LangGraph runtime code, event
worker, and the canonical Alembic migration history. Python 3.12 is required.

## Local commands

Run commands from `server/`:

```bash
uv sync --python 3.12 --group dev
uv run --python 3.12 uvicorn app.main:app --reload
uv run --python 3.12 ruff check .
uv run --python 3.12 ruff format --check .
uv run --python 3.12 mypy
uv run --python 3.12 pytest
uv run --python 3.12 alembic heads
```

Alembic upgrade and downgrade commands require an explicit `DATABASE_URL`. Test database
execution is wired through the fail-close `pdos_test` guard in S0-1d.
