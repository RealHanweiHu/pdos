# PDOS Server

The server workspace contains the FastAPI control plane, LangGraph runtime code, event
worker, and the canonical Alembic migration history. Python 3.12 is required.

## Local commands

Run commands from `server/`:

```bash
uv sync --python 3.12 --group dev
uv run --env-file ../.env --python 3.12 uvicorn app.main:app --reload
uv run --python 3.12 ruff check .
uv run --python 3.12 ruff format --check .
uv run --python 3.12 mypy
uv run --python 3.12 pytest
uv run --python 3.12 alembic heads
```

The API launch explicitly loads the repository-root `.env` into the server process,
as does `make dev`. Model catalog, budget, and input-meter configuration read this
process environment; loading authentication settings alone does not configure the
model gateway. Existing process variables take precedence. The file is parsed as
dotenv data, not executed as shell code; single-quote literal values containing `$`
to avoid dotenv interpolation. These launch options do not alter the
explicit database requirements for tests and migrations below.

Alembic upgrade and downgrade commands require an explicit `DATABASE_URL`. Test database
execution requires an explicitly exported `TEST_DATABASE_URL` targeting a disposable,
independent `pdos_test` database. The test guard never loads this value from `.env`;
`PDOS_TEST_DATABASE_URL` is not an alias. Local `localhost` / `127.0.0.1` / `::1`
port **57432 is protected and always refused**, even when explicitly configured.
Select and verify a separate test container/port before running tests, test migrations,
or smoke scripts. Tests may clear all tenant data on their configured database.
The guard unit tests (`tests/test_database_safety.py`, `tests/test_db_cleanup.py`)
use synthetic URLs and mocked connections and do not need a database.

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

## Development Case conversion

Owner, Admin, and Project Manager can convert one approved Requirement exactly once with
`POST /api/requirements/{requirement_id}/convert-to-case`. The server binds tenant and actor
scope, then creates a draft Development Case and conversion Decision, marks the Requirement
converted, and records correlated events plus immutable audits in one transaction. A failed or
duplicate conversion rolls the entire action back. Engineer and Quality are read-only; Supplier
and Customer have no Case access.

Authenticated internal roles can list and inspect tenant-bound cases with
`GET /api/development-cases` and `GET /api/development-cases/{id}`. Authorized editors use
`PATCH /api/development-cases/{id}` and the explicit
`POST /api/development-cases/{id}/transitions` action. The frozen graph is
`draft → evaluating → approved → converted` with `evaluating → rejected`; terminal cases cannot
be edited, and `approved → converted` requires an existing same-tenant Project reference.

## Project lifecycle

Owner, Admin, and Project Manager can create one Project from one approved Development Case with
`POST /api/projects`. The transaction instantiates a versioned, project-exclusive NPD Workflow,
its seven ordered Stage records, the draft Project and creator membership, marks the Case
converted, and records the correlated events and immutable audits. Any failure rolls the whole
action back.

Owner and Admin list every tenant Project; all other roles only list exact membership scope.
Owner, Admin, and Project Manager can edit Project content, follow the frozen
`draft → proposed → approved → active → completed → archived` graph (including
`active ↔ on_hold`), and advance active Projects only to an adjacent Stage in their own Workflow.
The Project API never accepts tenant scope from the client.

## Task, Issue, and Risk lifecycle

Project-scoped Task endpoints expose explicit create/edit/transition actions and derive readiness
from same-project, acyclic dependencies. An unfinished predecessor keeps a Task in `todo/waiting`;
only a user action with a nonblank reason may write `blocked`. Issue follows the strict
`open → analysis → action → verification → closed` graph. Risk follows
`open → mitigating/watching`, allows `mitigating ↔ watching`, and closes only from either active
state; its score is always `likelihood × impact`.

Owner and Admin may access work items inside their tenant. Project Manager, Engineer, and Quality
require exact Project membership. Supplier and Customer are denied, including assignment as a
work-item owner. Every write records its versioned event and immutable audit in the business
transaction; cross-project dependencies, cross-Workflow Stages, and failed writes leave no
partial rows.

## Events and audit

Issue event processing records an immutable trigger receipt separately from the mutable
run status. The source history endpoint is project-authorized and preserves the original
actor's private run scope. The work-items panel lists that actor's unresolved runs and links
back to the saved suggestion and original source; skipped events remain in source history.

Historical Issue business calls can be verified against an operator-installed publication
using `PDOS_AI_ISSUE_BUSINESS_CALL_PUBLICATION_PATH` and
`PDOS_AI_ISSUE_BUSINESS_CALL_PUBLICATION_SHA256`. The strict document contract is
`app/ai/issue_business_call_publication.py`; the server checks the file pin, tenant, validity,
exact project/run/invocation/model binding, immutable-originals digest and receipt uniqueness.
An operator must compare real provider receipts and local originals before installing it.
Missing or mismatched proof fails closed. There is no HTTP publication or automatic
qualification endpoint. Synthetic fixtures and golden evaluations are not business-call proof.
This reader verifies completed historical calls only: real-time proof for newly generated
calls remains separate work, as do independent evaluation, T1 trial qualification and current
scope authorization. Installing a publication does not grant T0 eligibility.

`cehub_event.events` is an ordered stream with `(source, event_id)` idempotency and tenant-safe
project scope. `app/events/catalog.py` freezes each event version, producer, consumer set, payload
schema, and retry rule. `EventAuditWriter` accepts an existing SQLAlchemy transaction so the
business mutation, event, and audit row commit or roll back together; tenant, project, and actor
scope are supplied by server-side context. Secret-bearing keys are rejected before I/O.

`cehub_audit.audit_log` is append-only: PostgreSQL rejects both `UPDATE` and `DELETE`. Its
`event_id` correlates the audit record with the business event without adding user IDs or other
high-cardinality values to telemetry. JSONB checks require object payloads and snapshots at the
database boundary, including for direct SQL writers.

Owner and Admin can inspect the frozen registry with `GET /api/events/catalog` and read their
tenant event stream with `GET /api/events`. The stream is read-only, ordered by the immutable
database `id`, and supports `after_id`, bounded `limit`, `event_type`, and tenant-validated
`project_id` filters. All other roles are denied. This Sprint 1 debugger does not expose the
future external `POST /events` contract and cannot re-execute consumers or mutate business state.
