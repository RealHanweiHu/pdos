from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, create_engine, inspect, select

from app.ai.quality import FindingQualityService
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from tests.db_cleanup import clear_test_tenants
from tests.migration_fixtures import migrate_test_database_in_steps

SERVER_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def quality_database_url() -> Iterator[str]:
    test_url = configured_test_database_url()
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    command.upgrade(Config(str(SERVER_ROOT / "alembic.ini")), "head")
    engine = create_engine(psycopg_database_url(test_url))
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


def seed_reviewed_findings(connection: Connection, *, decisions: list[str]) -> UUID:
    tenant_id = uuid4()
    workflow_id = uuid4()
    project_id = uuid4()
    subscription_id = uuid4()
    reviewer_id = uuid4()
    now = datetime.now(UTC)
    connection.execute(
        tables.tenants.insert(),
        {"id": tenant_id, "slug": f"quality-{tenant_id}", "name": "Quality"},
    )
    connection.execute(
        tables.users.insert(),
        {
            "id": reviewer_id,
            "tenant_id": tenant_id,
            "username": "reviewer",
            "display_name": "Reviewer",
            "role": "owner",
            "password_hash": "test-only",
        },
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
            "code": "PRJ-Q",
            "name": "Quality Project",
            "status": "active",
        },
    )
    connection.execute(
        tables.agent_subscriptions.insert(),
        {
            "id": subscription_id,
            "tenant_id": tenant_id,
            "agent_key": "project_intelligence",
        },
    )
    for index, status in enumerate(decisions):
        event_id = int(
            connection.execute(
                tables.events.insert()
                .values(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    event_id=f"issue:{uuid4()}",
                    event_type="ISSUE_CREATED",
                    schema_version=1,
                    source="quality_test",
                    entity="issue",
                    entity_id=uuid4(),
                    payload={},
                    timestamp=now - timedelta(minutes=30 + index),
                )
                .returning(tables.events.c.id)
            ).scalar_one()
        )
        run_id = uuid4()
        invocation_id = uuid4()
        finding_id = uuid4()
        connection.execute(
            tables.agent_runs.insert(),
            {
                "id": run_id,
                "tenant_id": tenant_id,
                "project_id": project_id,
                "subscription_id": subscription_id,
                "agent_key": "project_intelligence",
                "status": "succeeded",
                "window_started_at": now - timedelta(minutes=45 + index),
                "window_ended_at": now - timedelta(minutes=30 + index),
                "first_event_row_id": event_id,
                "last_event_row_id": event_id,
                "event_count": 1,
                "event_row_ids": [event_id],
                "started_at": now - timedelta(minutes=29 + index),
                "completed_at": now - timedelta(minutes=28 + index),
            },
        )
        connection.execute(
            tables.model_invocations.insert(),
            {
                "id": invocation_id,
                "tenant_id": tenant_id,
                "project_id": project_id,
                "run_id": run_id,
                "agent_key": "project_intelligence",
                "prompt_version": "v1",
                "provider": "minimax",
                "model": "MiniMax-M2.7",
                "protocol": "openai-compatible",
                "status": "succeeded",
                "structured_attempts": 1,
            },
        )
        reviewed_at = now - timedelta(minutes=20 - index)
        proposed = {"title": "Risk", "likelihood": 3, "impact": 4}
        values: dict[str, object] = {
            "id": finding_id,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "run_id": run_id,
            "model_invocation_id": invocation_id,
            "agent_key": "project_intelligence",
            "finding_type": "blocker_alert",
            "origin_key": f"blocker:{event_id}",
            "status": status,
            "title": "Review blocker",
            "summary": "A blocker needs review.",
            "proposed_payload": proposed,
            "evidence_event_ids": [event_id],
            "confidence_basis_points": 8000,
            "preflight_version": "finding-preflight-v2",
            "reviewed_by_user_id": reviewer_id,
            "reviewed_at": reviewed_at,
            "created_at": now - timedelta(minutes=25 - index),
            "updated_at": reviewed_at,
        }
        if status == "accepted":
            values["accepted_payload"] = proposed
        connection.execute(tables.findings.insert(), values)
    return tenant_id


def test_quality_waits_for_minimum_sample_then_narrows_only_the_low_quality_type(
    quality_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(quality_database_url))
    try:
        with engine.begin() as connection:
            tenant_id = seed_reviewed_findings(
                connection,
                decisions=["accepted", "rejected", "rejected", "rejected"],
            )
        service = FindingQualityService(
            engine,
            minimum_review_count=5,
            acceptance_threshold_basis_points=5_000,
        )

        first = service.evaluate(tenant_id=tenant_id)

        assert first.acceptance_rate_basis_points == 2_500
        assert first.narrowed_output_count == 0
        with engine.begin() as connection:
            seed = (
                connection.execute(
                    select(tables.findings).where(tables.findings.c.tenant_id == tenant_id).limit(1)
                )
                .mappings()
                .one()
            )
            copied = dict(seed)
            copied.pop("accepted_payload", None)
            copied.pop("applied_by_user_id", None)
            copied.pop("applied_at", None)
            copied.pop("applied_entity_type", None)
            copied.pop("applied_entity_id", None)
            copied.update(
                id=uuid4(),
                origin_key=f"blocker:{uuid4()}",
                status="rejected",
            )
            connection.execute(tables.findings.insert(), copied)

        second = service.evaluate(tenant_id=tenant_id)

        assert second.reviewed_count == 5
        assert second.accepted_count == 1
        assert second.acceptance_rate_basis_points == 2_000
        assert second.narrowed_output_count == 1
        assert second.controls[0].status == "narrowed"
        assert (
            service.is_output_allowed(
                tenant_id=tenant_id,
                agent_key="project_intelligence",
                finding_type="blocker_alert",
            )
            is False
        )
        assert (
            service.is_output_allowed(
                tenant_id=tenant_id,
                agent_key="project_intelligence",
                finding_type="risk_suggestion",
            )
            is True
        )
    finally:
        engine.dispose()


def test_quality_control_migration_round_trip(quality_database_url: str) -> None:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    engine = create_engine(psycopg_database_url(quality_database_url))
    try:
        assert "finding_quality_controls" in inspect(engine).get_table_names(schema="cehub_ai")
        migrate_test_database_in_steps(config, engine, "0013_ai_api_documents")
        assert "finding_quality_controls" not in inspect(engine).get_table_names(schema="cehub_ai")
        migrate_test_database_in_steps(config, engine, "head")
    finally:
        try:
            migrate_test_database_in_steps(config, engine, "head")
        finally:
            engine.dispose()
