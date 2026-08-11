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

## Authentication configuration

The API loads `DATABASE_URL`, `JWT_SECRET`, `JWT_ISSUER`, `JWT_AUDIENCE`, and
`JWT_ACCESS_TOKEN_MINUTES` lazily. `JWT_SECRET` must contain at least 32 bytes and must be
different in every environment. Access tokens use strict HS256 issuer/audience validation;
the tenant in a signed token is only a claim and is revalidated against the current database
membership and tenant status on every protected request.

On an empty database, `POST /api/setup` atomically creates the first tenant and administrator.
Only one concurrent setup request can succeed. Use `POST /api/auth/login` to issue a Bearer
token and `GET /api/auth/me` to resolve the current tenant-bound identity. All authentication
responses are marked `Cache-Control: no-store`.

## RBAC and project scope

The role catalog is frozen to Owner, Admin, Project Manager, Engineer, Quality, Supplier, and
Customer. Every action is listed in a server-side matrix; unknown roles and actions are denied.
Owner and Admin can resolve projects inside their active tenant without a project-membership row.
All other roles require both an allowed action and an exact tenant-safe `project_members` record.
Supplier and Customer are external roles and receive only project visibility plus the external
response action. `GET /api/projects/{project_id}/access` exposes the resolved role and action set
without accepting tenant scope from the client.

## Requirement pool

Authenticated internal roles can read the tenant-bound Requirement pool with
`GET /api/requirements`, inspect one item with `GET /api/requirements/{id}`, and obtain the
Customer selector from `GET /api/customers`. Owner, Admin, and Project Manager can create and
edit requirements with `POST /api/requirements` and `PATCH /api/requirements/{id}`. External
Supplier/Customer roles have no Intake access. Customer and Requirement identifiers are always
resolved inside the authenticated tenant; missing and cross-tenant requirements share the same
404 response.

Create and edit operations emit `REQUIREMENT_CREATED` / `REQUIREMENT_UPDATED` plus immutable
audit snapshots in the same database transaction. The `converted` status is reserved for the
formal Requirement→Development Case action in S1-2 and cannot be set through the generic edit
endpoint.

## Events and audit

`cehub_event.events` is an ordered stream with `(source, event_id)` idempotency and tenant-safe
project scope. `app/events/catalog.py` freezes each event version, producer, consumer set, payload
schema, and retry rule. `EventAuditWriter` accepts an existing SQLAlchemy transaction so the
business mutation, event, and audit row commit or roll back together; tenant, project, and actor
scope are supplied by server-side context. Secret-bearing keys are rejected before I/O.

`cehub_audit.audit_log` is append-only: PostgreSQL rejects both `UPDATE` and `DELETE`. Its
`event_id` correlates the audit record with the business event without adding user IDs or other
high-cardinality values to telemetry. JSONB checks require object payloads and snapshots at the
database boundary, including for direct SQL writers.
