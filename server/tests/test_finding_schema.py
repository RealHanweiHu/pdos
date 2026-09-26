from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Table,
    UniqueConstraint,
    create_engine,
    inspect,
    select,
)
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.sql.schema import Constraint

from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from tests.db_cleanup import clear_test_tenants
from tests.migration_fixtures import (
    migrate_test_database_in_steps,
    rollback_migration_operations,
)

SERVER_ROOT = Path(__file__).resolve().parents[1]


def constraint_names(table: Table, constraint_type: type[Constraint]) -> set[str]:
    return {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, constraint_type) and isinstance(constraint.name, str)
    }


def index_names(table: Table) -> set[str]:
    return {
        index.name
        for index in table.indexes
        if isinstance(index, Index) and isinstance(index.name, str)
    }


def test_finding_metadata_freezes_review_and_apply_as_separate_actions() -> None:
    assert set(tables.findings.c.keys()) == {
        "id",
        "tenant_id",
        "project_id",
        "scope_kind",
        "run_id",
        "model_invocation_id",
        "agent_key",
        "finding_type",
        "origin_key",
        "status",
        "title",
        "summary",
        "proposed_payload",
        "accepted_payload",
        "evidence_event_ids",
        "confidence_basis_points",
        "preflight_version",
        "reviewed_by_user_id",
        "reviewed_at",
        "review_comment",
        "applied_by_user_id",
        "applied_at",
        "applied_entity_type",
        "applied_entity_id",
        "created_at",
        "updated_at",
    }
    assert {
        "ck_findings_type_allowed",
        "ck_findings_status_allowed",
        "ck_findings_proposed_payload_object",
        "ck_findings_accepted_payload_object",
        "ck_findings_evidence_event_ids_array",
        "ck_findings_confidence_range",
        "ck_findings_review_lifecycle_consistent",
        "ck_findings_apply_lifecycle_consistent",
    } <= constraint_names(tables.findings, CheckConstraint)
    assert {
        "fk_finding_run_scope",
        "fk_findings_tenant_project_run_agent",
        "fk_findings_tenant_model_invocation",
    } <= constraint_names(tables.findings, ForeignKeyConstraint)
    assert "uq_findings_tenant_run_origin" in constraint_names(tables.findings, UniqueConstraint)
    assert {
        "ix_findings_tenant_status_created",
        "ix_findings_tenant_project_status",
    } <= index_names(tables.findings)

    assert set(tables.finding_actions.c.keys()) == {
        "id",
        "tenant_id",
        "project_id",
        "finding_id",
        "action",
        "actor_user_id",
        "from_status",
        "to_status",
        "detail",
        "created_at",
    }
    terminal = next(
        index
        for index in tables.finding_actions.indexes
        if index.name == "uq_finding_actions_terminal"
    )
    assert terminal.unique
    assert list(terminal.columns.keys()) == ["tenant_id", "finding_id", "action"]
    # Review undo and repeated archive/restore remain auditable; creation and
    # actual application are still unique terminal receipts.
    assert str(terminal.dialect_options["postgresql"]["where"]) == "action IN ('created','applied')"


@pytest.fixture
def finding_database_url() -> Iterator[str]:
    test_url = configured_test_database_url()
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    engine = create_engine(psycopg_database_url(test_url))
    # The explicit migration test below owns the historical round trip; each
    # constraint scenario needs only the current schema and clean tenant rows.
    command.upgrade(config, "head")
    try:
        with engine.begin() as connection:
            clear_test_tenants(connection)
        yield test_url
    finally:
        engine.dispose()
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url


def seed_finding_dependencies(
    database_url: str,
    *,
    agent_key: str = "project_intelligence",
) -> dict[str, UUID | int]:
    tenant_id = uuid4()
    workflow_id = uuid4()
    project_id = uuid4()
    subscription_id = uuid4()
    run_id = uuid4()
    invocation_id = uuid4()
    now = datetime.now(UTC)
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                {"id": tenant_id, "slug": f"finding-{tenant_id}", "name": "Finding"},
            )
            connection.execute(
                tables.workflows.insert(),
                {"id": workflow_id, "tenant_id": tenant_id, "code": "npd", "name": "NPD"},
            )
            connection.execute(
                tables.projects.insert(),
                {
                    "id": project_id,
                    "tenant_id": tenant_id,
                    "workflow_id": workflow_id,
                    "code": "PRJ-FINDING",
                    "name": "Finding Project",
                    "status": "active",
                },
            )
            event_id = int(
                connection.execute(
                    tables.events.insert()
                    .values(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        event_id=f"issue:{uuid4()}",
                        event_type="ISSUE_CREATED",
                        schema_version=1,
                        source="finding_schema_test",
                        entity="issue",
                        entity_id=uuid4(),
                        payload={},
                        timestamp=now - timedelta(minutes=20),
                    )
                    .returning(tables.events.c.id)
                ).scalar_one()
            )
            connection.execute(
                tables.agent_subscriptions.insert(),
                {
                    "id": subscription_id,
                    "tenant_id": tenant_id,
                    "agent_key": agent_key,
                },
            )
            connection.execute(
                tables.agent_runs.insert(),
                {
                    "id": run_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "subscription_id": subscription_id,
                    "agent_key": agent_key,
                    "status": "succeeded",
                    "window_started_at": now - timedelta(minutes=30),
                    "window_ended_at": now - timedelta(minutes=15),
                    "first_event_row_id": event_id,
                    "last_event_row_id": event_id,
                    "event_count": 1,
                    "event_row_ids": [event_id],
                    "started_at": now - timedelta(minutes=14),
                    "completed_at": now - timedelta(minutes=13),
                },
            )
            connection.execute(
                tables.model_invocations.insert(),
                {
                    "id": invocation_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "run_id": run_id,
                    "agent_key": agent_key,
                    "prompt_version": "v1",
                    "provider": "minimax",
                    "model": "MiniMax-M2.7",
                    "protocol": "openai-compatible",
                    "status": "succeeded",
                    "structured_attempts": 1,
                },
            )
    finally:
        engine.dispose()
    return {
        "tenant_id": tenant_id,
        "project_id": project_id,
        "subscription_id": subscription_id,
        "run_id": run_id,
        "invocation_id": invocation_id,
        "event_id": event_id,
    }


def pending_finding(ids: dict[str, UUID | int]) -> dict[str, object]:
    return {
        "id": uuid4(),
        "tenant_id": ids["tenant_id"],
        "project_id": ids["project_id"],
        "run_id": ids["run_id"],
        "model_invocation_id": ids["invocation_id"],
        "agent_key": "project_intelligence",
        "finding_type": "risk_suggestion",
        "origin_key": "risk-1",
        "status": "pending_review",
        "title": "Review schedule risk",
        "summary": "A scoped issue may affect schedule.",
        "proposed_payload": {
            "title": "Schedule risk",
            "description": "Issue may delay the next milestone.",
            "likelihood": 3,
            "impact": 4,
            "mitigation_plan": "Resolve the blocking issue.",
        },
        "evidence_event_ids": [ids["event_id"]],
        "confidence_basis_points": 8500,
        "preflight_version": "finding-preflight-v1",
    }


def test_database_rejects_collapsed_review_apply_and_action_mutation(
    finding_database_url: str,
) -> None:
    ids = seed_finding_dependencies(finding_database_url)
    engine = create_engine(psycopg_database_url(finding_database_url))
    try:
        with engine.begin() as connection:
            finding = pending_finding(ids)
            connection.execute(tables.findings.insert(), finding)
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    tables.findings.insert(),
                    {
                        **finding,
                        "id": uuid4(),
                        "origin_key": "collapsed",
                        "status": "applied",
                        "accepted_payload": finding["proposed_payload"],
                    },
                )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    tables.findings.insert(),
                    {**finding, "id": uuid4(), "confidence_basis_points": 10_001},
                )
            action_id = uuid4()
            connection.execute(
                tables.finding_actions.insert(),
                {
                    "id": action_id,
                    "tenant_id": ids["tenant_id"],
                    "project_id": ids["project_id"],
                    "finding_id": finding["id"],
                    "action": "created",
                    "to_status": "pending_review",
                    "detail": {},
                },
            )
            with pytest.raises(DBAPIError), connection.begin_nested():
                connection.execute(
                    tables.finding_actions.update()
                    .where(tables.finding_actions.c.id == action_id)
                    .values(detail={"tampered": True})
                )
    finally:
        engine.dispose()


def test_finding_migration_round_trip(finding_database_url: str) -> None:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    engine = create_engine(psycopg_database_url(finding_database_url))
    try:
        assert {"findings", "finding_actions"} <= set(
            inspect(engine).get_table_names(schema="cehub_ai")
        )
        migrate_test_database_in_steps(config, engine, "0010_agent_runtime")
        assert {"findings", "finding_actions"}.isdisjoint(
            inspect(engine).get_table_names(schema="cehub_ai")
        )
        migrate_test_database_in_steps(config, engine, "head")
    finally:
        try:
            migrate_test_database_in_steps(config, engine, "head")
        finally:
            engine.dispose()


def test_phase_one_migration_refuses_lossy_downgrade(finding_database_url: str) -> None:
    ids = seed_finding_dependencies(finding_database_url, agent_key="knowledge_lite")
    engine = create_engine(psycopg_database_url(finding_database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.findings.insert(),
                {
                    **pending_finding(ids),
                    "agent_key": "knowledge_lite",
                    "finding_type": "knowledge_draft",
                    "origin_key": "knowledge-draft-1",
                    "proposed_payload": {
                        "title": "Draft lesson",
                        "draft_text": "Retain only for human verification.",
                    },
                },
            )

        with (
            pytest.raises(DBAPIError, match="Cannot downgrade 0012"),
            rollback_migration_operations(engine),
        ):
            import_module("migrations.versions.0012_phase_one_agents").downgrade()

        with engine.connect() as connection:
            assert (
                connection.execute(
                    select(tables.findings.c.id).where(
                        tables.findings.c.origin_key == "knowledge-draft-1"
                    )
                ).scalar_one()
                is not None
            )
    finally:
        command.upgrade(Config(str(SERVER_ROOT / "alembic.ini")), "head")
        engine.dispose()


def test_apply_target_check_follows_object_contract_whitelist(
    finding_database_url: str,
) -> None:
    ids = seed_finding_dependencies(finding_database_url)
    engine = create_engine(psycopg_database_url(finding_database_url))
    now = datetime.now(UTC)
    try:
        with engine.begin() as connection:
            reviewer_id = uuid4()
            connection.execute(
                tables.users.insert(),
                {
                    "id": reviewer_id,
                    "tenant_id": ids["tenant_id"],
                    "username": f"apply-reviewer-{reviewer_id}",
                    "display_name": "Apply Reviewer",
                    "role": "quality",
                },
            )
            base = pending_finding(ids)
            applied = {
                **base,
                "status": "applied",
                "accepted_payload": base["proposed_payload"],
                "reviewed_by_user_id": reviewer_id,
                "reviewed_at": now - timedelta(minutes=5),
                "review_comment": "ok",
                "applied_by_user_id": reviewer_id,
                "applied_at": now,
                "applied_entity_id": uuid4(),
            }
            for allowed in (
                "risk",
                "memory",
                "issue",
                "task",
                "test_run",
                "sample_build_configuration",
                "knowledge_candidate",
                "schedule_change_proposal",
                "material_exception",
            ):
                connection.execute(
                    tables.findings.insert(),
                    {
                        **applied,
                        "id": uuid4(),
                        "origin_key": f"apply-{allowed}",
                        "applied_entity_type": allowed,
                    },
                )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    tables.findings.insert(),
                    {
                        **applied,
                        "id": uuid4(),
                        "origin_key": "apply-outside-whitelist",
                        "applied_entity_type": "supplier",
                    },
                )
    finally:
        engine.dispose()
