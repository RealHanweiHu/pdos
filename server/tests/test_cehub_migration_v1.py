from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Table, create_engine, func, select, text
from sqlalchemy.engine import make_url

from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.domain.gates import GateService
from app.migrations.cehub_v1 import (
    MigrationValidationError,
    cehub_psycopg_database_url,
    map_gate_decision,
    map_project_status,
    map_user_role,
    migrate_cehub_v1,
    normalize_project_code,
)

SERVER_ROOT = Path(__file__).resolve().parents[1]
SOURCE_SCHEMA = "legacy_cehub_s37"
SOURCE_ROLE = "pdos_cehub_source_test"
SOURCE_PASSWORD = "pdos-cehub-source-test"


@pytest.fixture(scope="module")
def migration_database_url() -> Iterator[str]:
    test_url = configured_test_database_url()
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    try:
        yield test_url
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def _create_source_fixture(engine_url: str) -> None:
    engine = create_engine(psycopg_database_url(engine_url))
    try:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{SOURCE_SCHEMA}" CASCADE'))
            connection.execute(text(f'CREATE SCHEMA "{SOURCE_SCHEMA}"'))
            connection.execute(
                text(
                    f'''
                    CREATE TABLE "{SOURCE_SCHEMA}"."users" (
                        id integer PRIMARY KEY,
                        "openId" varchar(64) NOT NULL,
                        username varchar(64),
                        name text,
                        email varchar(320),
                        role varchar(32) NOT NULL,
                        "createdAt" timestamptz NOT NULL,
                        "updatedAt" timestamptz NOT NULL
                    );
                    CREATE TABLE "{SOURCE_SCHEMA}"."projects" (
                        id varchar(32) PRIMARY KEY,
                        name varchar(256) NOT NULL,
                        "projectNumber" varchar(64) NOT NULL,
                        category varchar(32) NOT NULL,
                        "pmUserId" integer,
                        description text,
                        "currentPhase" varchar(32) NOT NULL,
                        "startDate" varchar(32),
                        "targetDate" varchar(32),
                        "createdBy" integer NOT NULL,
                        archived boolean NOT NULL,
                        lifecycle varchar(32) NOT NULL,
                        "createdAt" timestamptz NOT NULL,
                        "updatedAt" timestamptz NOT NULL
                    );
                    CREATE TABLE "{SOURCE_SCHEMA}"."project_tasks" (
                        id integer PRIMARY KEY,
                        "projectId" varchar(32) NOT NULL,
                        "phaseId" varchar(32) NOT NULL,
                        "taskId" varchar(32) NOT NULL,
                        completed boolean NOT NULL,
                        instructions text,
                        completion_note text,
                        "assigneeUserId" integer,
                        "dueDate" date,
                        "startDate" date,
                        "actualStartedAt" timestamptz,
                        status varchar(32) NOT NULL,
                        blocked_reason text,
                        priority varchar(16) NOT NULL,
                        "completedAt" timestamptz,
                        "createdAt" timestamptz NOT NULL,
                        "updatedAt" timestamptz NOT NULL
                    );
                    CREATE TABLE "{SOURCE_SCHEMA}"."project_gate_reviews" (
                        id integer PRIMARY KEY,
                        "projectId" varchar(32) NOT NULL,
                        "phaseId" varchar(32) NOT NULL,
                        "phaseName" varchar(256) NOT NULL,
                        "gateName" varchar(256) NOT NULL,
                        "reviewDate" varchar(32) NOT NULL,
                        participants text,
                        decision varchar(32) NOT NULL,
                        conditions text,
                        notes text,
                        "roundNumber" integer NOT NULL,
                        "createdBy" integer,
                        "createdAt" timestamptz NOT NULL,
                        "updatedAt" timestamptz NOT NULL
                    );
                    CREATE TABLE "{SOURCE_SCHEMA}"."project_files" (
                        id integer PRIMARY KEY,
                        "projectId" varchar(32) NOT NULL,
                        "phaseId" varchar(32),
                        "taskId" varchar(32),
                        visibility varchar(32) NOT NULL,
                        "securityClassification" varchar(24) NOT NULL,
                        name varchar(256) NOT NULL,
                        "mimeType" varchar(128) NOT NULL,
                        size bigint NOT NULL,
                        "storageKey" varchar(512) NOT NULL,
                        "storageUrl" varchar(512) NOT NULL,
                        "uploadedBy" integer NOT NULL,
                        "createdAt" timestamptz NOT NULL
                    );
                    '''
                )
            )
            connection.execute(
                text(
                    f'''
                    INSERT INTO "{SOURCE_SCHEMA}"."users"
                        (id, "openId", username, name, email, role, "createdAt", "updatedAt")
                    VALUES
                        (1, 'pm.han', 'pm.han', '韩项目经理', 'pm.han@example.test', 'admin',
                         '2026-01-01T00:00:00Z', '2026-08-01T00:00:00Z'),
                        (2, 'eng.li', 'eng.li', '李工程师', 'eng.li@example.test', 'member',
                         '2026-01-02T00:00:00Z', '2026-08-02T00:00:00Z');
                    INSERT INTO "{SOURCE_SCHEMA}"."projects"
                        (id, name, "projectNumber", category, "pmUserId", description,
                         "currentPhase", "startDate", "targetDate", "createdBy", archived,
                         lifecycle, "createdAt", "updatedAt")
                    VALUES
                        ('aBnbEdQG', 'S18 试点项目', 'S18-01', 'npd', 1, 'CEHub 真实形态样本',
                         'dvt', '2026-01-10', '2026-12-31', 1, false, 'active',
                         '2026-01-10T00:00:00Z', '2026-08-10T00:00:00Z'),
                        ('zGpNH0Xq', 'C4s 手持充气泵', 'C4s', 'obt', 1, 'OBT 真实形态样本',
                         'intake', '2026-02-01', '2026-10-31', 1, false, 'active',
                         '2026-02-01T00:00:00Z', '2026-08-11T00:00:00Z');
                    INSERT INTO "{SOURCE_SCHEMA}"."project_tasks"
                        (id, "projectId", "phaseId", "taskId", completed, instructions,
                         completion_note, "assigneeUserId", "dueDate", "startDate",
                         "actualStartedAt", status, blocked_reason, priority, "completedAt",
                         "createdAt", "updatedAt")
                    VALUES
                        (101, 'aBnbEdQG', 'evt', 'evt-verify', true, '完成 EVT 验证', '证据已归档',
                         2, '2026-05-30', '2026-05-01', '2026-05-01T08:00:00Z', 'done', null,
                         'high', '2026-05-28T08:00:00Z', '2026-05-01T00:00:00Z',
                         '2026-05-28T08:00:00Z'),
                        (102, 'aBnbEdQG', 'dvt', 'dvt-verify', false, '执行 DVT', null,
                         2, '2026-08-31', '2026-08-01', '2026-08-01T08:00:00Z', 'in_progress',
                         null, 'critical', null, '2026-08-01T00:00:00Z',
                         '2026-08-10T00:00:00Z'),
                        (401, 'zGpNH0Xq', 'intake', 'intake-review', false,
                         '完成 DFM 输入评审', null,
                         1, '2026-08-31', '2026-08-01', null, 'todo', null,
                         'high', null, '2026-08-01T00:00:00Z', '2026-08-11T00:00:00Z'),
                        (402, 'zGpNH0Xq', 'sample', 'sample-fai', false, '完成首件确认', null,
                         2, '2026-09-15', '2026-09-01', null, 'todo', null,
                         'medium', null, '2026-08-01T00:00:00Z', '2026-08-11T00:00:00Z'),
                        (403, 'zGpNH0Xq', 'pvt', 'pvt-trial', false, '完成小批试产', null,
                         2, '2026-10-01', '2026-09-16', null, 'todo', null,
                         'high', null, '2026-08-01T00:00:00Z', '2026-08-11T00:00:00Z'),
                        (404, 'zGpNH0Xq', 'mp', 'mp-handoff', false, '完成量产移交', null,
                         1, '2026-10-31', '2026-10-02', null, 'todo', null,
                         'medium', null, '2026-08-01T00:00:00Z', '2026-08-11T00:00:00Z');
                    INSERT INTO "{SOURCE_SCHEMA}"."project_gate_reviews"
                        (id, "projectId", "phaseId", "phaseName", "gateName", "reviewDate",
                         participants, decision, conditions, notes, "roundNumber", "createdBy",
                         "createdAt", "updatedAt")
                    VALUES
                        (201, 'aBnbEdQG', 'evt', 'EVT', 'EVT Gate', '2026-06-01',
                         '韩项目经理,李工程师', 'conditional', '关闭遗留项', '首轮', 1, 1,
                         '2026-06-01T08:00:00Z', '2026-06-01T08:00:00Z'),
                        (202, 'aBnbEdQG', 'evt', 'EVT', 'EVT Gate', '2026-06-08',
                         '韩项目经理,李工程师', 'approved', null, '复审通过', 2, 1,
                         '2026-06-08T08:00:00Z', '2026-06-08T08:00:00Z');
                    INSERT INTO "{SOURCE_SCHEMA}"."project_files"
                        (id, "projectId", "phaseId", "taskId", visibility,
                         "securityClassification", name, "mimeType", size, "storageKey",
                         "storageUrl", "uploadedBy", "createdAt")
                    VALUES
                        (301, 'aBnbEdQG', 'evt', 'evt-verify', 'internal', 'confidential',
                         'EVT-report.pdf', 'application/pdf', 4096,
                         'projects/S18-01/evt-report.pdf',
                         '/storage/projects/S18-01/evt-report.pdf',
                         2, '2026-05-28T08:00:00Z'),
                        (501, 'zGpNH0Xq', 'intake', 'intake-review', 'internal', 'internal',
                         'C4s-DFM.pdf', 'application/pdf', 2048,
                         'projects/C4s/dfm.pdf', '/storage/projects/C4s/dfm.pdf',
                         1, '2026-08-11T08:00:00Z');
                    '''
                )
            )
            connection.execute(
                text(
                    f'''
                    DO $$
                    BEGIN
                        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{SOURCE_ROLE}') THEN
                            CREATE ROLE {SOURCE_ROLE} LOGIN NOINHERIT
                                PASSWORD '{SOURCE_PASSWORD}';
                        END IF;
                    END
                    $$;
                    ALTER ROLE {SOURCE_ROLE} SET default_transaction_read_only = on;
                    GRANT USAGE ON SCHEMA "{SOURCE_SCHEMA}" TO {SOURCE_ROLE};
                    GRANT SELECT ON ALL TABLES IN SCHEMA "{SOURCE_SCHEMA}" TO {SOURCE_ROLE};
                    REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
                        ON ALL TABLES IN SCHEMA "{SOURCE_SCHEMA}" FROM {SOURCE_ROLE};
                    '''
                )
            )
    finally:
        engine.dispose()


def _source_engine(engine_url: str):  # type: ignore[no-untyped-def]
    url = make_url(psycopg_database_url(engine_url)).set(
        username=SOURCE_ROLE,
        password=SOURCE_PASSWORD,
    )
    return create_engine(url)


def _create_target_context(engine_url: str) -> tuple[UUID, UUID]:
    tenant_id = uuid4()
    actor_id = uuid4()
    engine = create_engine(psycopg_database_url(engine_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                {"id": tenant_id, "slug": f"migration-{tenant_id.hex[:12]}", "name": "Migration"},
            )
            connection.execute(
                tables.users.insert(),
                {
                    "id": actor_id,
                    "tenant_id": tenant_id,
                    "username": "migration-operator",
                    "display_name": "Migration Operator",
                    "role": "owner",
                    "is_active": True,
                },
            )
    finally:
        engine.dispose()
    return tenant_id, actor_id


def _tenant_count(engine_url: str, table: Table, tenant_id: UUID) -> int:
    engine = create_engine(psycopg_database_url(engine_url))
    try:
        with engine.connect() as connection:
            return connection.execute(
                select(func.count()).select_from(table).where(table.c.tenant_id == tenant_id)
            ).scalar_one()
    finally:
        engine.dispose()


def test_frozen_cehub_v1_value_mapping_is_fail_closed() -> None:
    assert map_user_role("owner") == "admin"
    assert map_user_role("member") == "engineer"
    assert map_user_role("external") == "supplier"
    assert map_project_status(archived=False, lifecycle="active") == "active"
    assert map_project_status(archived=False, lifecycle="paused") == "on_hold"
    assert map_project_status(archived=True, lifecycle="active") == "archived"
    assert map_gate_decision("conditional") == "reviewing"
    assert normalize_project_code(project_number="", source_id="S18-01") == "S18-01"


def test_unknown_source_values_are_rejected() -> None:
    for function, value in (
        (map_user_role, "superuser"),
        (map_gate_decision, "waived"),
    ):
        try:
            function(value)
        except ValueError as exc:
            assert value in str(exc)
        else:
            raise AssertionError(f"{function.__name__} accepted {value}")


def test_cehub_source_url_drops_only_prisma_libpq_compatibility_parameter() -> None:
    normalized = make_url(
        cehub_psycopg_database_url(
            "postgresql://readonly:secret@rds.example/cehub?sslmode=require&uselibpqcompat=true"
        )
    )

    assert normalized.drivername == "postgresql+psycopg"
    assert normalized.query == {"sslmode": "require"}


def test_write_capable_source_role_is_rejected_before_snapshot(
    migration_database_url: str,
) -> None:
    _create_source_fixture(migration_database_url)
    tenant_id, actor_id = _create_target_context(migration_database_url)
    write_capable_source = create_engine(psycopg_database_url(migration_database_url))
    target_engine = create_engine(psycopg_database_url(migration_database_url))
    try:
        with pytest.raises(ValueError, match="independent read-only role"):
            migrate_cehub_v1(
                source_engine=write_capable_source,
                target_engine=target_engine,
                tenant_id=tenant_id,
                actor_user_id=actor_id,
                project_ids=("S18-01",),
                source_schema=SOURCE_SCHEMA,
                dry_run=True,
            )
    finally:
        write_capable_source.dispose()
        target_engine.dispose()


def test_snapshot_dry_run_apply_replay_and_source_drift(
    migration_database_url: str,
) -> None:
    _create_source_fixture(migration_database_url)
    tenant_id, actor_id = _create_target_context(migration_database_url)
    source_engine = _source_engine(migration_database_url)
    target_engine = create_engine(psycopg_database_url(migration_database_url))
    try:
        before = {
            "projects": _tenant_count(migration_database_url, tables.projects, tenant_id),
            "mappings": _tenant_count(migration_database_url, tables.migration_mappings, tenant_id),
            "runs": _tenant_count(migration_database_url, tables.migration_runs, tenant_id),
        }
        dry_run = migrate_cehub_v1(
            source_engine=source_engine,
            target_engine=target_engine,
            tenant_id=tenant_id,
            actor_user_id=actor_id,
            project_ids=("S18-01",),
            source_schema=SOURCE_SCHEMA,
            dry_run=True,
        )
        assert dry_run.status == "ready"
        assert dry_run.target_writes == 0
        assert dry_run.errors == ()
        assert dry_run.source_counts == {
            "users": 2,
            "projects": 1,
            "tasks": 2,
            "gate_reviews": 2,
            "file_references": 1,
        }
        assert before == {
            "projects": _tenant_count(migration_database_url, tables.projects, tenant_id),
            "mappings": _tenant_count(migration_database_url, tables.migration_mappings, tenant_id),
            "runs": _tenant_count(migration_database_url, tables.migration_runs, tenant_id),
        }

        with pytest.raises(ValueError, match="approved dry-run source fingerprint"):
            migrate_cehub_v1(
                source_engine=source_engine,
                target_engine=target_engine,
                tenant_id=tenant_id,
                actor_user_id=actor_id,
                project_ids=("S18-01",),
                source_schema=SOURCE_SCHEMA,
                dry_run=False,
            )

        with pytest.raises(MigrationValidationError) as unapproved_snapshot:
            migrate_cehub_v1(
                source_engine=source_engine,
                target_engine=target_engine,
                tenant_id=tenant_id,
                actor_user_id=actor_id,
                project_ids=("S18-01",),
                source_schema=SOURCE_SCHEMA,
                dry_run=False,
                expected_source_fingerprint="0" * 64,
            )
        assert {error.code for error in unapproved_snapshot.value.report.errors} == {
            "SOURCE_SNAPSHOT_NOT_APPROVED"
        }
        assert before == {
            "projects": _tenant_count(migration_database_url, tables.projects, tenant_id),
            "mappings": _tenant_count(migration_database_url, tables.migration_mappings, tenant_id),
            "runs": _tenant_count(migration_database_url, tables.migration_runs, tenant_id),
        }

        applied = migrate_cehub_v1(
            source_engine=source_engine,
            target_engine=target_engine,
            tenant_id=tenant_id,
            actor_user_id=actor_id,
            project_ids=("S18-01",),
            source_schema=SOURCE_SCHEMA,
            dry_run=False,
            expected_source_fingerprint=dry_run.source_fingerprint,
        )
        assert applied.status == "completed"
        assert applied.created_counts == {
            "users": 2,
            "projects": 1,
            "tasks": 2,
            "gate_reviews": 2,
            "file_references": 1,
        }
        assert _tenant_count(migration_database_url, tables.migration_mappings, tenant_id) == 8
        assert _tenant_count(migration_database_url, tables.workflows, tenant_id) == 1
        assert _tenant_count(migration_database_url, tables.stages, tenant_id) == 7
        assert _tenant_count(migration_database_url, tables.gates, tenant_id) == 7
        assert _tenant_count(migration_database_url, tables.gate_history_records, tenant_id) == 2
        assert (
            _tenant_count(migration_database_url, tables.external_file_references, tenant_id) == 1
        )
        assert applied.selected_project_ids == ("aBnbEdQG",)
        assert applied.samples[0]["source_project_id"] == "aBnbEdQG"
        assert applied.samples[0]["project_name"] == "S18 试点项目"
        assert applied.samples[0]["current_stage"] == "dvt"
        assert applied.samples[0]["task_count"] == 2
        assert applied.samples[0]["gate_review_count"] == 2
        assert applied.samples[0]["file_reference_count"] == 1

        replay = migrate_cehub_v1(
            source_engine=source_engine,
            target_engine=target_engine,
            tenant_id=tenant_id,
            actor_user_id=actor_id,
            project_ids=("S18-01",),
            source_schema=SOURCE_SCHEMA,
            dry_run=False,
            expected_source_fingerprint=dry_run.source_fingerprint,
        )
        assert replay.created_counts == {key: 0 for key in applied.created_counts}
        assert replay.skipped_counts == applied.created_counts
        assert _tenant_count(migration_database_url, tables.migration_mappings, tenant_id) == 8
        assert _tenant_count(migration_database_url, tables.migration_runs, tenant_id) == 2

        with target_engine.begin() as connection:
            connection.execute(
                text(
                    f'''UPDATE "{SOURCE_SCHEMA}"."projects"
                        SET name = 'source changed' WHERE id = 'aBnbEdQG' '''
                )
            )
        drift = migrate_cehub_v1(
            source_engine=source_engine,
            target_engine=target_engine,
            tenant_id=tenant_id,
            actor_user_id=actor_id,
            project_ids=("S18-01",),
            source_schema=SOURCE_SCHEMA,
            dry_run=True,
        )
        assert drift.status == "invalid"
        assert drift.target_writes == 0
        assert {error.code for error in drift.errors} == {"SOURCE_CHANGED"}
        with pytest.raises(MigrationValidationError):
            migrate_cehub_v1(
                source_engine=source_engine,
                target_engine=target_engine,
                tenant_id=tenant_id,
                actor_user_id=actor_id,
                project_ids=("S18-01",),
                source_schema=SOURCE_SCHEMA,
                dry_run=False,
                expected_source_fingerprint=dry_run.source_fingerprint,
            )
    finally:
        source_engine.dispose()
        target_engine.dispose()


def test_project_number_selection_imports_npd_and_obt_workflow_shapes(
    migration_database_url: str,
) -> None:
    _create_source_fixture(migration_database_url)
    tenant_id, actor_id = _create_target_context(migration_database_url)
    source_engine = _source_engine(migration_database_url)
    target_engine = create_engine(psycopg_database_url(migration_database_url))
    try:
        dry_run = migrate_cehub_v1(
            source_engine=source_engine,
            target_engine=target_engine,
            tenant_id=tenant_id,
            actor_user_id=actor_id,
            project_ids=("C4s", "S18-01"),
            source_schema=SOURCE_SCHEMA,
            dry_run=True,
        )
        report = migrate_cehub_v1(
            source_engine=source_engine,
            target_engine=target_engine,
            tenant_id=tenant_id,
            actor_user_id=actor_id,
            project_ids=("C4s", "S18-01"),
            source_schema=SOURCE_SCHEMA,
            dry_run=False,
            expected_source_fingerprint=dry_run.source_fingerprint,
        )
        assert report.status == "completed"
        assert report.selected_project_ids == ("zGpNH0Xq", "aBnbEdQG")
        assert report.source_counts == {
            "users": 2,
            "projects": 2,
            "tasks": 6,
            "gate_reviews": 2,
            "file_references": 2,
        }
        assert _tenant_count(migration_database_url, tables.workflows, tenant_id) == 2
        assert _tenant_count(migration_database_url, tables.stages, tenant_id) == 11
        assert _tenant_count(migration_database_url, tables.gates, tenant_id) == 11
        assert _tenant_count(migration_database_url, tables.migration_mappings, tenant_id) == 14

        with target_engine.connect() as connection:
            c4s_project_id = connection.execute(
                select(tables.projects.c.id).where(
                    tables.projects.c.tenant_id == tenant_id,
                    tables.projects.c.code == "C4s",
                )
            ).scalar_one()
            c4s_workflow = connection.execute(
                select(tables.workflows.c.code)
                .join(tables.projects, tables.projects.c.workflow_id == tables.workflows.c.id)
                .where(
                    tables.projects.c.tenant_id == tenant_id,
                    tables.projects.c.code == "C4s",
                )
            ).scalar_one()
            c4s_stages = tuple(
                connection.execute(
                    select(tables.stages.c.code)
                    .join(tables.workflows, tables.workflows.c.id == tables.stages.c.workflow_id)
                    .join(tables.projects, tables.projects.c.workflow_id == tables.workflows.c.id)
                    .where(
                        tables.projects.c.tenant_id == tenant_id,
                        tables.projects.c.code == "C4s",
                    )
                    .order_by(tables.stages.c.sequence)
                ).scalars()
            )
            c4s_current_gate_id = connection.execute(
                select(tables.gates.c.id)
                .join(tables.projects, tables.projects.c.id == tables.gates.c.project_id)
                .join(tables.stages, tables.stages.c.id == tables.gates.c.stage_id)
                .where(
                    tables.projects.c.tenant_id == tenant_id,
                    tables.projects.c.code == "C4s",
                    tables.stages.c.code == "intake",
                )
            ).scalar_one()
        assert c4s_workflow.startswith("obt-cehub-")
        assert c4s_stages == ("intake", "sample", "pvt", "mp")
        opened_gate = GateService(target_engine).open_round(
            tenant_id=tenant_id,
            project_id=c4s_project_id,
            gate_id=c4s_current_gate_id,
            actor_user_id=actor_id,
        )
        assert opened_gate.round is not None
        assert opened_gate.round.policy_version == "obt-gate-v1"
    finally:
        source_engine.dispose()
        target_engine.dispose()
