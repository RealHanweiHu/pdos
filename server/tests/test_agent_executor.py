from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, select, text

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

SERVER_ROOT = Path(__file__).resolve().parents[1]


class FakeModelInvoker:
    def __init__(self, result: GatewayResult[AgentAssessment]) -> None:
        self.result = result
        self.invocations: list[GatewayInvocation] = []

    def invoke(self, invocation: GatewayInvocation) -> GatewayResult[AgentAssessment]:
        self.invocations.append(invocation)
        return self.result


class FailingModelInvoker:
    def __init__(self) -> None:
        self.invocations: list[GatewayInvocation] = []

    def invoke(self, invocation: GatewayInvocation) -> GatewayResult[AgentAssessment]:
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
            connection.execute(text("TRUNCATE TABLE cehub_core.tenants CASCADE"))
        yield test_url
    finally:
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
