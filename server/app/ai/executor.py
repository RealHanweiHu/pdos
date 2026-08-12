"""LangGraph execution plane for server-frozen Agent runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Literal, Protocol, TypedDict, cast
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import Engine, select, update

from app.ai.gateway import GatewayInvocation, GatewayResult, StructuredModelGateway
from app.ai.runtime_contract import AgentKey, FrozenRunContext
from app.ai.tools import TOOL_DEFINITIONS, AgentReadTools, ProjectContextResult, ToolPage
from app.db.schema import tables

PROMPT_VERSION = "agent-runtime-v1"
_TOOL_PREFIX = json.dumps(
    [definition.model_dump(mode="json") for definition in TOOL_DEFINITIONS],
    ensure_ascii=False,
    separators=(",", ":"),
    sort_keys=True,
)
SYSTEM_PROMPTS = MappingProxyType(
    {
        AgentKey.PROJECT_INTELLIGENCE: (
            "You are the PDOS Project Intelligence Agent. Analyze only the supplied run-scoped "
            "Project evidence. Never claim to update business records. Any future business change "
            "must be proposed for human review through the controlled finding workflow. "
            f"FROZEN_READ_ONLY_TOOLS\n{_TOOL_PREFIX}"
        ),
        AgentKey.KNOWLEDGE_LITE: (
            "You are the PDOS Knowledge Agent Lite. Analyze only the supplied run-scoped Project "
            "evidence and verified memory. Never claim an unverified document is organizational "
            "knowledge and never claim to update business records. Any future business change must "
            "be proposed for human review through the controlled finding workflow. "
            f"FROZEN_READ_ONLY_TOOLS\n{_TOOL_PREFIX}"
        ),
    }
)
INSTRUCTIONS = MappingProxyType(
    {
        AgentKey.PROJECT_INTELLIGENCE: (
            "Assess the frozen Project state and recent event references. Return one concise, "
            "evidence-linked assessment. Do not perform or imply a business update."
        ),
        AgentKey.KNOWLEDGE_LITE: (
            "Assess whether the frozen references support a knowledge candidate. "
            "Return one concise, evidence-linked assessment. "
            "Do not treat unverified content as memory."
        ),
    }
)


class AgentAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    disposition: Literal["no_action", "human_review_candidate"]
    summary: str = Field(min_length=1, max_length=2_000)
    evidence_event_ids: tuple[int, ...] = Field(max_length=100)
    confidence: float = Field(ge=0, le=1)


class AgentModelInvoker(Protocol):
    def invoke(self, invocation: GatewayInvocation) -> GatewayResult[AgentAssessment]: ...


class GatewayAgentModelInvoker:
    def __init__(self, gateway: StructuredModelGateway) -> None:
        self._gateway = gateway

    def invoke(self, invocation: GatewayInvocation) -> GatewayResult[AgentAssessment]:
        return self._gateway.invoke_structured(invocation, AgentAssessment)


class ExecutorState(TypedDict, total=False):
    run_context: FrozenRunContext
    project_context: ProjectContextResult
    recent_events: ToolPage
    memory: ToolPage
    gateway_result: GatewayResult[AgentAssessment]


class CompiledExecutorGraph(Protocol):
    def invoke(self, state: ExecutorState) -> ExecutorState: ...


@dataclass(frozen=True)
class ExecutionResult:
    run_id: UUID | None
    status: Literal["idle", "succeeded", "degraded", "failed"]
    error_code: str | None


class AgentExecutor:
    def __init__(self, engine: Engine, *, model_invoker: AgentModelInvoker) -> None:
        self._engine = engine
        self._model_invoker = model_invoker
        self._graph = self._build_graph()

    def execute_next(self, *, now: datetime | None = None) -> ExecutionResult:
        current_time = (now or datetime.now(UTC)).astimezone(UTC)
        context = self._claim_next(current_time)
        if context is None:
            return ExecutionResult(run_id=None, status="idle", error_code=None)

        try:
            final_state = self._graph.invoke({"run_context": context})
            result = final_state["gateway_result"]
        except Exception as error:
            error_code = self._error_code(error)
            self._fail(
                run_id=context.run_id,
                error_code=error_code,
                completed_at=current_time,
            )
            return ExecutionResult(
                run_id=context.run_id,
                status="failed",
                error_code=error_code,
            )

        status: Literal["succeeded", "degraded"] = result.status
        self._complete(
            run_id=context.run_id,
            status=status,
            error_code=result.error_code,
            completed_at=current_time,
        )
        return ExecutionResult(
            run_id=context.run_id,
            status=status,
            error_code=result.error_code,
        )

    def _build_graph(self) -> CompiledExecutorGraph:
        graph = StateGraph(ExecutorState)
        graph.add_node("get_project_context", self._get_project_context)
        graph.add_node("get_recent_events", self._get_recent_events)
        graph.add_node("search_memory", self._search_memory)
        graph.add_node("invoke_model", self._invoke_model)
        graph.add_edge(START, "get_project_context")
        graph.add_edge("get_project_context", "get_recent_events")
        graph.add_edge("get_recent_events", "search_memory")
        graph.add_edge("search_memory", "invoke_model")
        graph.add_edge("invoke_model", END)
        return cast(CompiledExecutorGraph, graph.compile())

    def _get_project_context(self, state: ExecutorState) -> dict[str, ProjectContextResult]:
        context = state["run_context"]
        tools = AgentReadTools(self._engine, run_context=context)
        return {
            "project_context": tools.get_project_context(project_id=context.project_id),
        }

    def _get_recent_events(self, state: ExecutorState) -> dict[str, ToolPage]:
        context = state["run_context"]
        tools = AgentReadTools(self._engine, run_context=context)
        return {
            "recent_events": tools.get_recent_events(
                project_id=context.project_id,
                limit=20,
            )
        }

    def _search_memory(self, state: ExecutorState) -> dict[str, ToolPage]:
        context = state["run_context"]
        tools = AgentReadTools(self._engine, run_context=context)
        return {
            "memory": tools.search_memory(
                project_id=context.project_id,
                query="Project evidence relevant to the current trigger events",
                limit=20,
            )
        }

    def _invoke_model(
        self,
        state: ExecutorState,
    ) -> dict[str, GatewayResult[AgentAssessment]]:
        context = state["run_context"]
        project_context = state["project_context"]
        recent_events = state["recent_events"]
        invocation = GatewayInvocation(
            tenant_id=context.tenant_id,
            project_id=context.project_id,
            run_id=context.run_id,
            agent_key=context.agent_key.value,
            prompt_version=PROMPT_VERSION,
            system_prompt=SYSTEM_PROMPTS[context.agent_key],
            instruction=INSTRUCTIONS[context.agent_key],
            context={
                "project": project_context.project,
                "execution": project_context.execution,
                "trigger": self._trigger(context),
                "references": [
                    {
                        "entity": item["entity"],
                        "entity_id": item["entity_id"],
                        "label": item["event_type"],
                    }
                    for item in recent_events.items
                ],
            },
        )
        return {"gateway_result": self._model_invoker.invoke(invocation)}

    def _claim_next(self, started_at: datetime) -> FrozenRunContext | None:
        with self._engine.begin() as connection:
            run = (
                connection.execute(
                    select(tables.agent_runs)
                    .where(tables.agent_runs.c.status == "queued")
                    .order_by(tables.agent_runs.c.created_at, tables.agent_runs.c.id)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                .mappings()
                .one_or_none()
            )
            if run is None:
                return None
            context = FrozenRunContext.model_validate(run["run_context"])
            if (
                context.run_id != run["id"]
                or context.tenant_id != run["tenant_id"]
                or context.project_id != run["project_id"]
                or context.agent_key.value != run["agent_key"]
            ):
                raise RuntimeError("persisted Agent run context does not match its control record")
            connection.execute(
                update(tables.agent_runs)
                .where(
                    tables.agent_runs.c.id == context.run_id,
                    tables.agent_runs.c.status == "queued",
                )
                .values(status="running", started_at=started_at, updated_at=started_at)
            )
            return context

    def _complete(
        self,
        *,
        run_id: UUID,
        status: Literal["succeeded", "degraded"],
        error_code: str | None,
        completed_at: datetime,
    ) -> None:
        if status == "succeeded" and error_code is not None:
            raise ValueError("successful Agent run cannot carry an error")
        if status == "degraded" and not error_code:
            raise ValueError("degraded Agent run must carry an error")
        with self._engine.begin() as connection:
            run = (
                connection.execute(
                    select(tables.agent_runs)
                    .where(tables.agent_runs.c.id == run_id)
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            connection.execute(
                update(tables.agent_runs)
                .where(
                    tables.agent_runs.c.id == run_id,
                    tables.agent_runs.c.status == "running",
                )
                .values(
                    status=status,
                    completed_at=completed_at,
                    error_code=error_code,
                    updated_at=completed_at,
                )
            )
            connection.execute(
                update(tables.agent_subscriptions)
                .where(tables.agent_subscriptions.c.id == run["subscription_id"])
                .values(
                    consecutive_failure_count=0,
                    updated_at=completed_at,
                )
            )

    def _fail(
        self,
        *,
        run_id: UUID,
        error_code: str,
        completed_at: datetime,
    ) -> None:
        with self._engine.begin() as connection:
            run = (
                connection.execute(
                    select(tables.agent_runs)
                    .where(tables.agent_runs.c.id == run_id)
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            subscription = (
                connection.execute(
                    select(tables.agent_subscriptions)
                    .where(tables.agent_subscriptions.c.id == run["subscription_id"])
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            failure_count = int(subscription["consecutive_failure_count"]) + 1
            threshold = int(subscription["failure_threshold"])
            pause = failure_count >= threshold
            connection.execute(
                update(tables.agent_runs)
                .where(
                    tables.agent_runs.c.id == run_id,
                    tables.agent_runs.c.status == "running",
                )
                .values(
                    status="failed",
                    completed_at=completed_at,
                    error_code=error_code,
                    updated_at=completed_at,
                )
            )
            subscription_values: dict[str, object] = {
                "consecutive_failure_count": failure_count,
                "updated_at": completed_at,
            }
            if pause:
                subscription_values.update(
                    status="paused",
                    paused_reason=(
                        "AGENT_RUN_FAILURE_THRESHOLD_REACHED:"
                        f"{error_code}:count={failure_count}:threshold={threshold}"
                    ),
                )
            connection.execute(
                update(tables.agent_subscriptions)
                .where(tables.agent_subscriptions.c.id == subscription["id"])
                .values(**subscription_values)
            )

    @staticmethod
    def _error_code(error: Exception) -> str:
        if isinstance(error, ValidationError):
            return "RUN_CONTEXT_INVALID"
        if isinstance(error, PermissionError):
            return "TOOL_SCOPE_VIOLATION"
        if isinstance(error, ValueError):
            return "TOOL_INPUT_INVALID"
        return "EXECUTOR_INTERNAL_ERROR"

    @staticmethod
    def _trigger(context: FrozenRunContext) -> dict[str, object]:
        event = context.trigger_events[-1]
        return {
            "event_type": event.event_type,
            "entity": event.entity,
            "entity_id": str(event.entity_id),
            "timestamp": event.timestamp.isoformat(),
        }
