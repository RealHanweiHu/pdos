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
from sqlalchemy import Connection, Engine, create_engine, select

from app.ai.call_identity import ModelCallSlot, model_call_id
from app.ai.executor import (
    INSTRUCTIONS,
    PROMPT_VERSIONS,
    SYSTEM_PROMPTS,
    AgentAssessment,
    AgentExecutor,
)
from app.ai.gateway import GatewayInvocation, GatewayResult
from app.ai.runtime_contract import AgentKey
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.domain.findings import RiskSuggestionPayload
from app.worker.dispatcher import AgentDispatcher
from tests.db_cleanup import clear_test_tenants

SERVER_ROOT = Path(__file__).resolve().parents[1]


class FakeModelInvoker:
    def __init__(self, result: GatewayResult[AgentAssessment]) -> None:
        self.result = result
        self.invocations: list[GatewayInvocation] = []

    def invoke(self, invocation: GatewayInvocation) -> GatewayResult[AgentAssessment]:
        assert invocation.run_id is not None
        assert invocation.model_call_id == model_call_id(
            invocation.run_id, ModelCallSlot.EVENT_ASSESSMENT
        )
        self.invocations.append(invocation)
        return self.result


class FailingModelInvoker:
    def __init__(self) -> None:
        self.invocations: list[GatewayInvocation] = []

    def invoke(self, invocation: GatewayInvocation) -> GatewayResult[AgentAssessment]:
        assert invocation.run_id is not None
        assert invocation.model_call_id == model_call_id(
            invocation.run_id, ModelCallSlot.EVENT_ASSESSMENT
        )
        self.invocations.append(invocation)
        raise RuntimeError("simulated executor failure")


@pytest.fixture
def executor_database_url() -> Iterator[str]:
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
        with engine.begin() as connection:
            clear_test_tenants(connection)
        engine.dispose()
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url


def seed_project(connection: Connection) -> tuple[UUID, UUID]:
    tenant_id = uuid4()
    workflow_id = uuid4()
    project_id = uuid4()
    connection.execute(
        tables.tenants.insert(),
        {"id": tenant_id, "slug": "executor", "name": "Executor"},
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
            "code": "PRJ-EXEC",
            "name": "Executor Project",
            "status": "active",
        },
    )
    return tenant_id, project_id


def append_trigger(
    connection: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    occurred_at: datetime,
) -> int:
    return int(
        connection.execute(
            tables.events.insert()
            .values(
                tenant_id=tenant_id,
                project_id=project_id,
                event_id=f"issue:{uuid4()}",
                event_type="ISSUE_CREATED",
                schema_version=1,
                source="executor_test",
                entity="issue",
                entity_id=uuid4(),
                payload={"description": "raw payload must never reach model"},
                timestamp=occurred_at,
            )
            .returning(tables.events.c.id)
        ).scalar_one()
    )


def queued_run(engine: Engine, *, now: datetime) -> tuple[UUID, UUID, int]:
    with engine.begin() as connection:
        tenant_id, project_id = seed_project(connection)
        event_id = append_trigger(
            connection,
            tenant_id=tenant_id,
            project_id=project_id,
            occurred_at=now - timedelta(minutes=16),
        )
    dispatcher = AgentDispatcher(engine)
    dispatcher.dispatch_tenant(tenant_id=tenant_id)
    sealed = dispatcher.seal_due_runs(now=now)
    return sealed.queued_run_ids[0], project_id, event_id


def test_langgraph_executes_frozen_prefix_then_appends_project_context(
    executor_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(executor_database_url))
    now = datetime.now(UTC)
    try:
        run_id, project_id, event_id = queued_run(engine, now=now)
        invoker = FakeModelInvoker(
            GatewayResult(
                status="succeeded",
                output=AgentAssessment(
                    disposition="human_review_candidate",
                    candidate_type="blocker_alert",
                    summary="Review the new issue.",
                    proposed_payload=RiskSuggestionPayload(
                        title="Review the new issue",
                        description="The issue may block delivery.",
                        likelihood=3,
                        impact=4,
                    ),
                    evidence_event_ids=(event_id,),
                    confidence=0.8,
                ),
                error_code=None,
                structured_attempts=1,
                removed_context_paths=(),
            )
        )

        result = AgentExecutor(engine, model_invoker=invoker).execute_next(now=now)

        assert result.run_id == run_id
        assert result.status == "succeeded"
        assert len(invoker.invocations) == 1
        invocation = invoker.invocations[0]
        assert invocation.run_id == run_id
        assert invocation.project_id == project_id
        assert invocation.prompt_version == PROMPT_VERSIONS[AgentKey.PROJECT_INTELLIGENCE]
        assert invocation.system_prompt == SYSTEM_PROMPTS[AgentKey.PROJECT_INTELLIGENCE]
        assert invocation.instruction == INSTRUCTIONS[AgentKey.PROJECT_INTELLIGENCE]
        assert str(project_id) not in invocation.system_prompt
        assert str(run_id) not in invocation.system_prompt
        assert invocation.context["project"]["id"] == str(project_id)  # type: ignore[index]
        assert invocation.context["trigger"]["event_type"] == "ISSUE_CREATED"  # type: ignore[index]
        assert "payload" not in invocation.context["trigger"]  # type: ignore[operator]

        with engine.connect() as connection:
            run = (
                connection.execute(
                    select(tables.agent_runs).where(tables.agent_runs.c.id == run_id)
                )
                .mappings()
                .one()
            )
        assert run["status"] == "succeeded"
        assert run["started_at"] is not None
        assert run["completed_at"] is not None
        assert run["error_code"] is None
    finally:
        engine.dispose()


def test_quality_executor_appends_only_allowlisted_project_evidence(
    executor_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(executor_database_url))
    now = datetime.now(UTC)
    try:
        with engine.begin() as connection:
            tenant_id, project_id = seed_project(connection)
            quality_user_id = uuid4()
            complaint_id = uuid4()
            connection.execute(
                tables.users.insert(),
                {
                    "id": quality_user_id,
                    "tenant_id": tenant_id,
                    "username": "executor-quality",
                    "display_name": "Executor Quality",
                    "role": "quality",
                },
            )
            connection.execute(
                tables.complaints.insert(),
                {
                    "id": complaint_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "reported_by_user_id": quality_user_id,
                    "owner_user_id": quality_user_id,
                    "code": "CMP-EXEC",
                    "title": "Connector field release",
                    "description": "Connector released during field use",
                    "source": "customer",
                    "severity": "high",
                    "occurred_at": now - timedelta(days=1),
                    "reported_at": now - timedelta(minutes=20),
                    "customer_reference": "PRIVATE-CUSTOMER-REF",
                    "document_refs": ["private/quality/source.pdf"],
                },
            )
            event_id = int(
                connection.execute(
                    tables.events.insert()
                    .values(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        event_id=f"complaint:{complaint_id}:created",
                        event_type="COMPLAINT_CREATED",
                        schema_version=1,
                        source="executor_test",
                        entity="complaint",
                        entity_id=complaint_id,
                        payload={"complaint_id": str(complaint_id), "severity": "high"},
                        timestamp=now - timedelta(minutes=16),
                    )
                    .returning(tables.events.c.id)
                ).scalar_one()
            )
        dispatcher = AgentDispatcher(engine)
        dispatcher.dispatch_tenant(tenant_id=tenant_id)
        sealed = dispatcher.seal_due_runs(now=now)
        assert len(sealed.queued_run_ids) == 1
        invoker = FakeModelInvoker(
            GatewayResult(
                status="succeeded",
                output=AgentAssessment(
                    disposition="no_action",
                    candidate_type=None,
                    summary="No evidence-backed action is warranted.",
                    proposed_payload=None,
                    evidence_event_ids=(),
                    confidence=0.9,
                ),
                error_code=None,
                structured_attempts=1,
                removed_context_paths=(),
            )
        )

        result = AgentExecutor(engine, model_invoker=invoker).execute_next(now=now)

        assert result.run_id == sealed.queued_run_ids[0]
        invocation = invoker.invocations[0]
        assert invocation.agent_key == AgentKey.QUALITY_INTELLIGENCE
        trigger = cast(dict[str, object], invocation.context["trigger"])
        references = cast(list[dict[str, object]], invocation.context["references"])
        assert trigger["event_type"] == "COMPLAINT_CREATED"
        assert any(
            reference["reference_id"] == f"complaint:{complaint_id}" for reference in references
        )
        assert any(reference["reference_id"] == f"event:{event_id}" for reference in references)
        assert "PRIVATE-CUSTOMER-REF" not in str(references)
        assert "private/quality/source.pdf" not in str(references)
        assert "get_quality_evidence" in invocation.system_prompt
        assert "get_quality_evidence" not in SYSTEM_PROMPTS[AgentKey.PROJECT_INTELLIGENCE]
    finally:
        engine.dispose()


def test_executor_persists_gateway_degradation_and_idle_is_model_free(
    executor_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(executor_database_url))
    now = datetime.now(UTC)
    try:
        run_id, _, _ = queued_run(engine, now=now)
        invoker = FakeModelInvoker(
            GatewayResult(
                status="degraded",
                output=None,
                error_code="DAILY_BUDGET_EXCEEDED",
                structured_attempts=0,
                removed_context_paths=(),
            )
        )
        executor = AgentExecutor(engine, model_invoker=invoker)

        result = executor.execute_next(now=now)
        idle = executor.execute_next(now=now)

        assert result.run_id == run_id
        assert result.status == "degraded"
        assert result.error_code == "DAILY_BUDGET_EXCEEDED"
        assert idle.status == "idle"
        assert len(invoker.invocations) == 1
        with engine.connect() as connection:
            run = (
                connection.execute(
                    select(tables.agent_runs).where(tables.agent_runs.c.id == run_id)
                )
                .mappings()
                .one()
            )
        assert run["status"] == "degraded"
        assert run["error_code"] == "DAILY_BUDGET_EXCEEDED"
    finally:
        engine.dispose()


def test_failed_runs_trip_subscription_circuit_without_error_path_model_calls(
    executor_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(executor_database_url))
    now = datetime.now(UTC)
    try:
        with engine.begin() as connection:
            tenant_id, project_id = seed_project(connection)
            for minutes_ago in (61, 31):
                append_trigger(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    occurred_at=now - timedelta(minutes=minutes_ago),
                )
        dispatcher = AgentDispatcher(engine)
        dispatcher.dispatch_tenant(tenant_id=tenant_id)
        sealed = dispatcher.seal_due_runs(now=now)
        assert len(sealed.queued_run_ids) == 2
        with engine.begin() as connection:
            connection.execute(
                tables.agent_subscriptions.update()
                .where(tables.agent_subscriptions.c.tenant_id == tenant_id)
                .values(failure_threshold=2)
            )

        invoker = FailingModelInvoker()
        executor = AgentExecutor(engine, model_invoker=invoker)
        first = executor.execute_next(now=now)
        second = executor.execute_next(now=now)
        idle = executor.execute_next(now=now)

        assert first.status == second.status == "failed"
        assert first.error_code == second.error_code == "EXECUTOR_INTERNAL_ERROR"
        assert idle.status == "idle"
        assert len(invoker.invocations) == 2
        with engine.connect() as connection:
            subscription = (
                connection.execute(
                    select(tables.agent_subscriptions).where(
                        tables.agent_subscriptions.c.tenant_id == tenant_id
                    )
                )
                .mappings()
                .one()
            )
            runs = list(
                connection.execute(
                    select(tables.agent_runs).where(tables.agent_runs.c.tenant_id == tenant_id)
                ).mappings()
            )
        assert subscription["status"] == "paused"
        assert subscription["consecutive_failure_count"] == 2
        assert subscription["paused_reason"] == (
            "AGENT_RUN_FAILURE_THRESHOLD_REACHED:EXECUTOR_INTERNAL_ERROR:count=2:threshold=2"
        )
        assert {run["status"] for run in runs} == {"failed"}

        with engine.begin() as connection:
            new_event_id = append_trigger(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                occurred_at=now + timedelta(minutes=1),
            )
        paused_dispatch = dispatcher.dispatch_tenant(tenant_id=tenant_id)
        assert paused_dispatch.last_event_row_id == new_event_id
        assert paused_dispatch.routed_event_count == 0
        assert paused_dispatch.created_run_count == 0
        assert len(invoker.invocations) == 2
    finally:
        engine.dispose()


@pytest.mark.parametrize("rollout", ["disabled", "shadow"])
def test_queued_run_rechecks_rollout_before_context_tools_or_model(
    executor_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    rollout: str,
) -> None:
    from app.ai.capability_contract import CapabilityRollout
    from tests.rollout_support import set_agent_rollout

    engine = create_engine(psycopg_database_url(executor_database_url))
    try:
        now = datetime.now(UTC)
        run_id, _, _ = queued_run(engine, now=now)
        # The event was queued while live; a later stop still takes effect.
        set_agent_rollout(monkeypatch, AgentKey.PROJECT_INTELLIGENCE, CapabilityRollout(rollout))
        invoker = FailingModelInvoker()
        result = AgentExecutor(engine, model_invoker=invoker).execute_next(now=now)
        assert result.run_id == run_id
        assert result.status == "degraded"
        assert result.error_code == f"CAPABILITY_{rollout.upper()}"
        assert invoker.invocations == []
        with engine.connect() as connection:
            row = (
                connection.execute(
                    select(tables.agent_runs).where(tables.agent_runs.c.id == run_id)
                )
                .mappings()
                .one()
            )
            assert row["status"] == "degraded"
            assert row["error_code"] == result.error_code
            assert row["run_context"] == {}
    finally:
        engine.dispose()


def test_model_sees_trigger_ids_and_the_newest_events_up_to_the_trigger(
    executor_database_url: str,
) -> None:
    """A busy Project must not hide the trigger behind its oldest history (N7-02)."""
    engine = create_engine(psycopg_database_url(executor_database_url))
    now = datetime.now(UTC)
    try:
        with engine.begin() as connection:
            tenant_id, project_id = seed_project(connection)
            history = [
                int(
                    connection.execute(
                        tables.events.insert()
                        .values(
                            tenant_id=tenant_id,
                            project_id=project_id,
                            event_id=f"task:{uuid4()}",
                            event_type="TASK_CREATED",
                            schema_version=1,
                            source="executor_test",
                            entity="task",
                            entity_id=uuid4(),
                            payload={},
                            timestamp=now - timedelta(minutes=60 - index),
                        )
                        .returning(tables.events.c.id)
                    ).scalar_one()
                )
                for index in range(25)
            ]
            event_id = append_trigger(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                occurred_at=now - timedelta(minutes=16),
            )
        dispatcher = AgentDispatcher(engine)
        dispatcher.dispatch_tenant(tenant_id=tenant_id)
        dispatcher.seal_due_runs(now=now)
        invoker = FakeModelInvoker(
            GatewayResult(
                status="succeeded",
                output=AgentAssessment(
                    disposition="human_review_candidate",
                    candidate_type="blocker_alert",
                    summary="Review the new issue.",
                    proposed_payload=RiskSuggestionPayload(
                        title="Review the new issue",
                        description="The issue may block delivery.",
                        likelihood=3,
                        impact=4,
                    ),
                    evidence_event_ids=(event_id,),
                    confidence=0.8,
                ),
                error_code=None,
                structured_attempts=1,
                removed_context_paths=(),
            )
        )

        result = AgentExecutor(engine, model_invoker=invoker).execute_next(now=now)

        assert result.status == "succeeded"
        invocation = invoker.invocations[0]
        trigger = cast(dict[str, object], invocation.context["trigger"])
        assert trigger["events"] == [{"event_id": event_id}]
        references = cast(list[dict[str, object]], invocation.context["references"])
        cited = [
            int(str(reference["reference_id"]).removeprefix("event:"))
            for reference in references
            if str(reference["reference_id"]).startswith("event:")
        ]
        assert cited == [*history[-19:], event_id]
        assert history[0] not in cited
    finally:
        engine.dispose()


def test_project_agent_reads_the_triggering_issue_through_issue_evidence(
    executor_database_url: str,
) -> None:
    engine = create_engine(psycopg_database_url(executor_database_url))
    now = datetime.now(UTC)
    try:
        with engine.begin() as connection:
            tenant_id, project_id = seed_project(connection)
            issue_id = uuid4()
            connection.execute(
                tables.issues.insert(),
                {
                    "id": issue_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "title": "Low temperature start failure",
                    "description": "Two of three units fail to start after 2h at -10C.",
                    "issue_type": "test_failure",
                    "severity": "high",
                },
            )
            event_id = int(
                connection.execute(
                    tables.events.insert()
                    .values(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        event_id=f"issue:{issue_id}",
                        event_type="ISSUE_CREATED",
                        schema_version=1,
                        source="executor_test",
                        entity="issue",
                        entity_id=issue_id,
                        payload={"description": "raw payload must never reach model"},
                        timestamp=now - timedelta(minutes=16),
                    )
                    .returning(tables.events.c.id)
                ).scalar_one()
            )
        dispatcher = AgentDispatcher(engine)
        dispatcher.dispatch_tenant(tenant_id=tenant_id)
        dispatcher.seal_due_runs(now=now)
        invoker = FakeModelInvoker(
            GatewayResult(
                status="succeeded",
                output=AgentAssessment(
                    disposition="human_review_candidate",
                    candidate_type="blocker_alert",
                    summary="Review the start failure.",
                    proposed_payload=RiskSuggestionPayload(
                        title="Review the start failure",
                        description="Cold start failures may block EVT exit.",
                        likelihood=3,
                        impact=4,
                    ),
                    evidence_event_ids=(event_id,),
                    confidence=0.8,
                ),
                error_code=None,
                structured_attempts=1,
                removed_context_paths=(),
            )
        )

        result = AgentExecutor(engine, model_invoker=invoker).execute_next(now=now)

        assert result.status == "succeeded"
        invocation = invoker.invocations[0]
        references = cast(list[dict[str, object]], invocation.context["references"])
        issue = next(ref for ref in references if ref["reference_id"] == f"issue:{issue_id}")
        assert issue["label"] == "Low temperature start failure"
        assert "Two of three units fail to start" in str(issue["excerpt"])
        assert "raw payload must never reach model" not in str(references)
        assert "get_issue_evidence" in invocation.system_prompt
    finally:
        engine.dispose()
