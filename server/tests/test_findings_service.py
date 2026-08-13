from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text, update

from app.auth.roles import Role
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.domain.findings import (
    FindingApplyPermissionError,
    FindingGroundTruthConflictError,
    FindingInvalidTransitionError,
    FindingReview,
    FindingService,
    KnowledgeDraftPayload,
    RiskSuggestionPayload,
)

SERVER_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def findings_database_url() -> Iterator[str]:
    test_url = configured_test_database_url()
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    command.upgrade(Config(str(SERVER_ROOT / "alembic.ini")), "head")
    engine = create_engine(psycopg_database_url(test_url))
    try:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE cehub_core.tenants CASCADE"))
        yield test_url
    finally:
        engine.dispose()
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url


def seed_reviewable_finding(
    database_url: str,
    *,
    agent_key: str = "project_intelligence",
    event_type: str = "ISSUE_CREATED",
    finding_type: str = "risk_suggestion",
    proposed_payload: dict[str, object] | None = None,
) -> dict[str, UUID | int | datetime]:
    tenant_id = uuid4()
    workflow_id = uuid4()
    project_id = uuid4()
    reviewer_id = uuid4()
    outsider_id = uuid4()
    external_id = uuid4()
    subscription_id = uuid4()
    run_id = uuid4()
    invocation_id = uuid4()
    finding_id = uuid4()
    now = datetime.now(UTC)
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                {"id": tenant_id, "slug": f"review-{tenant_id}", "name": "Review Tenant"},
            )
            connection.execute(
                tables.users.insert(),
                [
                    {
                        "id": reviewer_id,
                        "tenant_id": tenant_id,
                        "username": "reviewer",
                        "display_name": "Reviewer",
                        "role": Role.ENGINEER.value,
                    },
                    {
                        "id": outsider_id,
                        "tenant_id": tenant_id,
                        "username": "outsider",
                        "display_name": "Outsider",
                        "role": Role.ENGINEER.value,
                    },
                    {
                        "id": external_id,
                        "tenant_id": tenant_id,
                        "username": "customer",
                        "display_name": "Customer",
                        "role": Role.CUSTOMER.value,
                    },
                ],
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
                    "code": "PRJ-REVIEW",
                    "name": "Review Project",
                    "status": "active",
                },
            )
            connection.execute(
                tables.project_members.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "user_id": reviewer_id,
                    "added_by_user_id": reviewer_id,
                },
            )
            event_id = int(
                connection.execute(
                    tables.events.insert()
                    .values(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        event_id=f"issue:{uuid4()}",
                        event_type=event_type,
                        schema_version=1,
                        source="finding_service_test",
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
            connection.execute(
                tables.findings.insert(),
                {
                    "id": finding_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "run_id": run_id,
                    "model_invocation_id": invocation_id,
                    "agent_key": agent_key,
                    "finding_type": finding_type,
                    "origin_key": "schedule-risk",
                    "title": "Review schedule risk",
                    "summary": "The issue may delay delivery.",
                    "proposed_payload": proposed_payload
                    or {
                        "title": "Schedule risk",
                        "description": "The current issue may delay delivery.",
                        "likelihood": 3,
                        "impact": 4,
                        "mitigation_plan": "Resolve the issue.",
                    },
                    "evidence_event_ids": [event_id],
                    "confidence_basis_points": 8500,
                    "preflight_version": "finding-preflight-v1",
                    "created_at": now,
                    "updated_at": now,
                },
            )
            connection.execute(
                tables.finding_actions.insert(),
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "finding_id": finding_id,
                    "action": "created",
                    "to_status": "pending_review",
                    "detail": {},
                    "created_at": now,
                },
            )
    finally:
        engine.dispose()
    return {
        "tenant_id": tenant_id,
        "project_id": project_id,
        "reviewer_id": reviewer_id,
        "outsider_id": outsider_id,
        "external_id": external_id,
        "run_id": run_id,
        "finding_id": finding_id,
        "event_id": event_id,
        "now": now,
    }


def test_accept_and_apply_are_two_audited_human_actions(
    findings_database_url: str,
) -> None:
    ids = seed_reviewable_finding(findings_database_url)
    service = FindingService(create_engine(psycopg_database_url(findings_database_url)))
    seeded_at = cast(datetime, ids["now"])
    reviewed_at = seeded_at + timedelta(minutes=1)
    applied_at = seeded_at + timedelta(minutes=2)

    accepted = service.review(
        tenant_id=ids["tenant_id"],  # type: ignore[arg-type]
        actor_user_id=ids["reviewer_id"],  # type: ignore[arg-type]
        finding_id=ids["finding_id"],  # type: ignore[arg-type]
        review=FindingReview(
            decision="accepted",
            edited_payload=RiskSuggestionPayload(
                title="Edited schedule risk",
                description="Reviewer-confirmed schedule impact.",
                likelihood=4,
                impact=4,
                mitigation_plan="Escalate the blocking issue.",
            ),
            comment="Evidence confirmed.",
        ),
        now=reviewed_at,
    )
    assert accepted.status == "accepted"
    assert accepted.applied_entity_id is None

    result = service.apply(
        tenant_id=ids["tenant_id"],  # type: ignore[arg-type]
        actor_user_id=ids["reviewer_id"],  # type: ignore[arg-type]
        finding_id=ids["finding_id"],  # type: ignore[arg-type]
        now=applied_at,
    )
    replay = service.apply(
        tenant_id=ids["tenant_id"],  # type: ignore[arg-type]
        actor_user_id=ids["reviewer_id"],  # type: ignore[arg-type]
        finding_id=ids["finding_id"],  # type: ignore[arg-type]
        now=applied_at + timedelta(seconds=1),
    )
    assert result.finding.status == "applied"
    assert not result.idempotent_replay
    assert replay.idempotent_replay
    assert replay.risk_id == result.risk_id

    engine = create_engine(psycopg_database_url(findings_database_url))
    try:
        with engine.connect() as connection:
            risk = (
                connection.execute(select(tables.risks).where(tables.risks.c.id == result.risk_id))
                .mappings()
                .one()
            )
            actions = list(
                connection.execute(
                    select(tables.finding_actions.c.action)
                    .where(tables.finding_actions.c.finding_id == ids["finding_id"])
                    .order_by(tables.finding_actions.c.created_at)
                ).scalars()
            )
            feedback = list(
                connection.execute(
                    select(tables.events.c.payload)
                    .where(
                        tables.events.c.entity_id == ids["finding_id"],
                        tables.events.c.event_type == "AI_FEEDBACK_RECEIVED",
                    )
                    .order_by(tables.events.c.id)
                ).scalars()
            )
        assert risk["title"] == "Edited schedule risk"
        assert risk["likelihood"] == 4
        assert actions == ["created", "accepted", "applied"]
        assert [item["decision"] for item in feedback] == ["accepted", "applied"]
    finally:
        engine.dispose()


def test_knowledge_draft_apply_creates_unverified_memory_not_business_truth(
    findings_database_url: str,
) -> None:
    ids = seed_reviewable_finding(
        findings_database_url,
        agent_key="knowledge_lite",
        event_type="DOCUMENT_UPLOADED",
        finding_type="knowledge_draft",
        proposed_payload={
            "title": "Connector validation lesson",
            "draft_text": "Validate connector pin mapping before the DVT build.",
            "applicability": "Projects using the same connector family.",
        },
    )
    engine = create_engine(psycopg_database_url(findings_database_url))
    service = FindingService(engine)
    try:
        accepted = service.review(
            tenant_id=ids["tenant_id"],  # type: ignore[arg-type]
            actor_user_id=ids["reviewer_id"],  # type: ignore[arg-type]
            finding_id=ids["finding_id"],  # type: ignore[arg-type]
            review=FindingReview(
                decision="accepted",
                edited_payload=KnowledgeDraftPayload(
                    title="Reviewed connector validation lesson",
                    draft_text="Validate connector pin mapping before the DVT build.",
                    applicability="Projects using the same connector family.",
                ),
            ),
            now=cast(datetime, ids["now"]) + timedelta(minutes=1),
        )

        assert accepted.status == "accepted"
        assert accepted.finding_type == "knowledge_draft"
        applied = service.apply(
            tenant_id=ids["tenant_id"],  # type: ignore[arg-type]
            actor_user_id=ids["reviewer_id"],  # type: ignore[arg-type]
            finding_id=ids["finding_id"],  # type: ignore[arg-type]
            now=cast(datetime, ids["now"]) + timedelta(minutes=2),
        )

        with engine.connect() as connection:
            finding_status = connection.execute(
                select(tables.findings.c.status).where(tables.findings.c.id == ids["finding_id"])
            ).scalar_one()
            risk_count = connection.execute(
                select(text("count(*)")).select_from(tables.risks)
            ).scalar_one()
            memory = (
                connection.execute(
                    select(tables.memories).where(tables.memories.c.id == applied.applied_entity_id)
                )
                .mappings()
                .one()
            )
            actions = list(
                connection.execute(
                    select(tables.finding_actions.c.action)
                    .where(tables.finding_actions.c.finding_id == ids["finding_id"])
                    .order_by(tables.finding_actions.c.created_at)
                ).scalars()
            )
        assert finding_status == "applied"
        assert risk_count == 0
        assert applied.applied_entity_type == "memory"
        assert applied.memory_id == memory["id"]
        assert applied.risk_id is None
        assert memory["status"] == "draft"
        assert memory["source_finding_id"] == ids["finding_id"]
        assert actions == ["created", "accepted", "applied"]
    finally:
        engine.dispose()


def test_reject_is_terminal_and_cannot_apply(findings_database_url: str) -> None:
    ids = seed_reviewable_finding(findings_database_url)
    service = FindingService(create_engine(psycopg_database_url(findings_database_url)))
    rejected = service.review(
        tenant_id=ids["tenant_id"],  # type: ignore[arg-type]
        actor_user_id=ids["reviewer_id"],  # type: ignore[arg-type]
        finding_id=ids["finding_id"],  # type: ignore[arg-type]
        review=FindingReview(decision="rejected", comment="Not actionable."),
        now=cast(datetime, ids["now"]) + timedelta(minutes=1),
    )
    assert rejected.status == "rejected"
    with pytest.raises(FindingInvalidTransitionError):
        service.apply(
            tenant_id=ids["tenant_id"],  # type: ignore[arg-type]
            actor_user_id=ids["reviewer_id"],  # type: ignore[arg-type]
            finding_id=ids["finding_id"],  # type: ignore[arg-type]
            now=cast(datetime, ids["now"]) + timedelta(minutes=2),
        )


def test_review_apply_require_internal_project_permission(
    findings_database_url: str,
) -> None:
    ids = seed_reviewable_finding(findings_database_url)
    service = FindingService(create_engine(psycopg_database_url(findings_database_url)))
    for actor_key in ("outsider_id", "external_id"):
        with pytest.raises(FindingApplyPermissionError):
            service.review(
                tenant_id=ids["tenant_id"],  # type: ignore[arg-type]
                actor_user_id=ids[actor_key],  # type: ignore[arg-type]
                finding_id=ids["finding_id"],  # type: ignore[arg-type]
                review=FindingReview(decision="accepted"),
                now=cast(datetime, ids["now"]) + timedelta(minutes=1),
            )


def test_apply_rechecks_database_ground_truth(findings_database_url: str) -> None:
    ids = seed_reviewable_finding(findings_database_url)
    service = FindingService(create_engine(psycopg_database_url(findings_database_url)))
    service.review(
        tenant_id=ids["tenant_id"],  # type: ignore[arg-type]
        actor_user_id=ids["reviewer_id"],  # type: ignore[arg-type]
        finding_id=ids["finding_id"],  # type: ignore[arg-type]
        review=FindingReview(decision="accepted"),
        now=cast(datetime, ids["now"]) + timedelta(minutes=1),
    )
    engine = create_engine(psycopg_database_url(findings_database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                update(tables.projects)
                .where(tables.projects.c.id == ids["project_id"])
                .values(status="completed")
            )
    finally:
        engine.dispose()
    with pytest.raises(FindingGroundTruthConflictError):
        service.apply(
            tenant_id=ids["tenant_id"],  # type: ignore[arg-type]
            actor_user_id=ids["reviewer_id"],  # type: ignore[arg-type]
            finding_id=ids["finding_id"],  # type: ignore[arg-type]
            now=cast(datetime, ids["now"]) + timedelta(minutes=2),
        )
