"""LangGraph execution plane for server-frozen Agent runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Protocol, TypedDict, cast
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import Engine

from app.ai.context_builder import RunContextBuilder
from app.ai.embeddings import EmbeddingGateway
from app.ai.finding_writer import (
    AgentFindingWriter,
    FindingOutputNarrowedError,
    preflight_assessment,
)
from app.ai.gateway import GatewayInvocation, GatewayResult, StructuredModelGateway
from app.ai.run_store import AgentRunStore, ClaimedAgentRun, OwnerAgentRunStore
from app.ai.runtime_contract import AgentKey, FrozenRunContext
from app.ai.tools import AgentReadTools, ProjectContextResult, ToolPage, tool_definitions_for_agent
from app.domain.findings import KnowledgeDraftPayload, RiskSuggestionPayload

PROMPT_DIRECTORY = Path(__file__).with_name("prompts")


class PromptFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1, max_length=128)
    agent_key: AgentKey
    system_prompt: str = Field(min_length=1, max_length=100_000)
    instruction: str = Field(min_length=1, max_length=100_000)


def _load_prompt(filename: str, *, expected_agent: AgentKey) -> PromptFile:
    prompt = PromptFile.model_validate_json((PROMPT_DIRECTORY / filename).read_text())
    if prompt.agent_key is not expected_agent:
        raise RuntimeError(f"prompt {filename} has the wrong Agent key")
    return prompt


_PROMPTS = {
    AgentKey.PROJECT_INTELLIGENCE: _load_prompt(
        "project_intelligence_v1.json",
        expected_agent=AgentKey.PROJECT_INTELLIGENCE,
    ),
    AgentKey.KNOWLEDGE_LITE: _load_prompt(
        "knowledge_lite_v1.json",
        expected_agent=AgentKey.KNOWLEDGE_LITE,
    ),
    AgentKey.ENGINEERING_INTELLIGENCE: _load_prompt(
        "engineering_intelligence_v1.json",
        expected_agent=AgentKey.ENGINEERING_INTELLIGENCE,
    ),
    AgentKey.QUALITY_INTELLIGENCE: _load_prompt(
        "quality_intelligence_v1.json",
        expected_agent=AgentKey.QUALITY_INTELLIGENCE,
    ),
    AgentKey.SUPPLIER_INTELLIGENCE: _load_prompt(
        "supplier_intelligence_v1.json",
        expected_agent=AgentKey.SUPPLIER_INTELLIGENCE,
    ),
    AgentKey.EXECUTIVE_INTELLIGENCE: _load_prompt(
        "executive_intelligence_v1.json",
        expected_agent=AgentKey.EXECUTIVE_INTELLIGENCE,
    ),
}
PROMPT_VERSIONS = MappingProxyType({key: prompt.version for key, prompt in _PROMPTS.items()})
SYSTEM_PROMPTS = MappingProxyType(
    {
        key: (
            f"{prompt.system_prompt}\nFROZEN_READ_ONLY_TOOLS\n"
            + json.dumps(
                [
                    definition.model_dump(mode="json")
                    for definition in tool_definitions_for_agent(key)
                ],
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        for key, prompt in _PROMPTS.items()
    }
)
INSTRUCTIONS = MappingProxyType({key: prompt.instruction for key, prompt in _PROMPTS.items()})

FindingCandidateType = Literal[
    "risk_suggestion",
    "blocker_alert",
    "gate_readiness_anomaly",
    "knowledge_draft",
    "bom_impact_suggestion",
    "change_impact_suggestion",
    "quality_cluster_alert",
    "capa_suggestion",
    "supplier_delay_risk",
    "executive_portfolio_brief",
]


class AgentAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    disposition: Literal["no_action", "human_review_candidate"]
    candidate_type: FindingCandidateType | None
    summary: str = Field(min_length=1, max_length=2_000)
    proposed_payload: RiskSuggestionPayload | KnowledgeDraftPayload | None
    evidence_event_ids: tuple[int, ...] = Field(max_length=100)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_candidate_shape(self) -> AgentAssessment:
        if self.disposition == "no_action":
            if (
                self.candidate_type is not None
                or self.proposed_payload is not None
                or self.evidence_event_ids
            ):
                raise ValueError("no_action cannot carry a candidate, payload, or evidence")
            return self
        if self.candidate_type is None or self.proposed_payload is None:
            raise ValueError("human_review_candidate requires a type and payload")
        if self.candidate_type == "knowledge_draft":
            if not isinstance(self.proposed_payload, KnowledgeDraftPayload):
                raise ValueError("knowledge_draft requires a knowledge draft payload")
        elif not isinstance(self.proposed_payload, RiskSuggestionPayload):
            raise ValueError("risk-shaped Agent candidates require a risk payload")
        if not self.evidence_event_ids:
            raise ValueError("human_review_candidate requires evidence")
        return self


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
    domain_evidence: ToolPage
    gateway_result: GatewayResult[AgentAssessment]


class CompiledExecutorGraph(Protocol):
    def invoke(self, state: ExecutorState) -> ExecutorState: ...


@dataclass(frozen=True)
class ExecutionResult:
    run_id: UUID | None
    status: Literal["idle", "succeeded", "degraded", "failed"]
    error_code: str | None
    finding_id: UUID | None = None


class AgentExecutor:
    def __init__(
        self,
        engine: Engine,
        *,
        model_invoker: AgentModelInvoker,
        context_builder: RunContextBuilder | None = None,
        run_store: AgentRunStore | None = None,
        finding_writer: AgentFindingWriter | None = None,
        embedding_gateway: EmbeddingGateway | None = None,
    ) -> None:
        self._engine = engine
        self._model_invoker = model_invoker
        self._context_builder = context_builder or RunContextBuilder()
        self._run_store = run_store or OwnerAgentRunStore(engine)
        self._finding_writer = finding_writer
        self._embedding_gateway = embedding_gateway
        self._graph = self._build_graph()

    def execute_next(self, *, now: datetime | None = None) -> ExecutionResult:
        current_time = (now or datetime.now(UTC)).astimezone(UTC)
        claim = self._run_store.claim(started_at=current_time)
        if claim is None:
            return ExecutionResult(run_id=None, status="idle", error_code=None)

        with self._run_store.scope(claim):
            try:
                context = self._load_context(claim=claim, built_at=current_time)
                final_state = self._graph.invoke({"run_context": context})
                result = final_state["gateway_result"]
                try:
                    finding_id = self._create_finding(
                        claim=claim,
                        context=context,
                        result=result,
                        created_at=current_time,
                    )
                except FindingOutputNarrowedError:
                    finding_id = None
            except Exception as error:
                error_code = self._error_code(error)
                self._run_store.fail(
                    claim=claim,
                    error_code=error_code,
                    completed_at=current_time,
                )
                return ExecutionResult(
                    run_id=claim.id,
                    status="failed",
                    error_code=error_code,
                )
            status: Literal["succeeded", "degraded"] = result.status
            self._run_store.complete(
                claim=claim,
                status=status,
                error_code=result.error_code,
                completed_at=current_time,
            )
            return ExecutionResult(
                run_id=context.run_id,
                status=status,
                error_code=result.error_code,
                finding_id=finding_id,
            )

    def _create_finding(
        self,
        *,
        claim: ClaimedAgentRun,
        context: FrozenRunContext,
        result: GatewayResult[AgentAssessment],
        created_at: datetime,
    ) -> UUID | None:
        if self._finding_writer is None or result.status != "succeeded" or result.output is None:
            return None
        candidate = preflight_assessment(result.output, context=context)
        if candidate is None:
            return None
        if result.invocation_id is None:
            raise RuntimeError("successful Agent result has no model invocation trace")
        return self._finding_writer.create(
            claim=claim,
            context=context,
            model_invocation_id=result.invocation_id,
            candidate=candidate,
            created_at=created_at,
        )

    def _build_graph(self) -> CompiledExecutorGraph:
        graph = StateGraph(ExecutorState)
        graph.add_node("get_project_context", self._get_project_context)
        graph.add_node("get_recent_events", self._get_recent_events)
        graph.add_node("search_memory", self._search_memory)
        graph.add_node("get_domain_evidence", self._get_domain_evidence)
        graph.add_node("invoke_model", self._invoke_model)
        graph.add_edge(START, "get_project_context")
        graph.add_edge("get_project_context", "get_recent_events")
        graph.add_edge("get_recent_events", "search_memory")
        graph.add_edge("search_memory", "get_domain_evidence")
        graph.add_edge("get_domain_evidence", "invoke_model")
        graph.add_edge("invoke_model", END)
        return cast(CompiledExecutorGraph, graph.compile())

    def _get_project_context(self, state: ExecutorState) -> dict[str, ProjectContextResult]:
        context = state["run_context"]
        tools = AgentReadTools(
            self._engine,
            run_context=context,
            run_store=self._run_store,
            embedding_gateway=self._embedding_gateway,
        )
        return {
            "project_context": tools.get_project_context(project_id=context.project_id),
        }

    def _get_recent_events(self, state: ExecutorState) -> dict[str, ToolPage]:
        context = state["run_context"]
        tools = AgentReadTools(
            self._engine,
            run_context=context,
            run_store=self._run_store,
            embedding_gateway=self._embedding_gateway,
        )
        return {
            "recent_events": tools.get_recent_events(
                project_id=context.project_id,
                limit=20,
            )
        }

    def _search_memory(self, state: ExecutorState) -> dict[str, ToolPage]:
        context = state["run_context"]
        tools = AgentReadTools(
            self._engine,
            run_context=context,
            run_store=self._run_store,
            embedding_gateway=self._embedding_gateway,
        )
        return {
            "memory": tools.search_memory(
                project_id=context.project_id,
                query="Project evidence relevant to the current trigger events",
                limit=20,
            )
        }

    def _get_domain_evidence(self, state: ExecutorState) -> dict[str, ToolPage]:
        context = state["run_context"]
        tools = AgentReadTools(
            self._engine,
            run_context=context,
            run_store=self._run_store,
            embedding_gateway=self._embedding_gateway,
        )
        if context.agent_key is AgentKey.ENGINEERING_INTELLIGENCE:
            page = tools.get_engineering_evidence(project_id=context.project_id, limit=20)
        elif context.agent_key is AgentKey.QUALITY_INTELLIGENCE:
            page = tools.get_quality_evidence(project_id=context.project_id, limit=20)
        elif context.agent_key is AgentKey.SUPPLIER_INTELLIGENCE:
            page = tools.get_supplier_delay_evidence(project_id=context.project_id, limit=20)
        elif context.agent_key is AgentKey.EXECUTIVE_INTELLIGENCE:
            page = tools.get_portfolio_brief(project_id=context.project_id, limit=20)
        else:
            page = ToolPage(
                items=(),
                shown_count=0,
                total_count=0,
                truncated=False,
                next_after_id=None,
                continuation="已显示 0 之 0 条；当前 Agent 无附加域证据，无需续读。",
            )
        return {"domain_evidence": page}

    def _invoke_model(
        self,
        state: ExecutorState,
    ) -> dict[str, GatewayResult[AgentAssessment]]:
        context = state["run_context"]
        project_context = state["project_context"]
        recent_events = state["recent_events"]
        references = [
            {
                "reference_id": f"event:{item['id']}",
                "entity": item["entity"],
                "entity_id": item["entity_id"],
                "label": item["event_type"],
            }
            for item in recent_events.items
        ]
        references.extend(
            {
                "reference_id": f"memory:{item['memory_id']}",
                "entity": "memory",
                "entity_id": item["memory_id"],
                "label": item["title"],
                "excerpt": str(item["content"])[:1_000],
            }
            for item in state["memory"].items
        )
        references.extend(state["domain_evidence"].items)
        invocation = GatewayInvocation(
            tenant_id=context.tenant_id,
            project_id=context.project_id,
            run_id=context.run_id,
            agent_key=context.agent_key.value,
            prompt_version=PROMPT_VERSIONS[context.agent_key],
            system_prompt=SYSTEM_PROMPTS[context.agent_key],
            instruction=INSTRUCTIONS[context.agent_key],
            context={
                "project": project_context.project,
                "execution": project_context.execution,
                "trigger": self._trigger(context),
                "references": references,
                "multimodal": context.multimodal.model_dump(mode="json"),
                "user": context.user.model_dump(mode="json"),
            },
        )
        return {"gateway_result": self._model_invoker.invoke(invocation)}

    def _load_context(
        self,
        *,
        claim: ClaimedAgentRun,
        built_at: datetime,
    ) -> FrozenRunContext:
        with self._engine.begin() as connection:
            self._run_store.bind(connection)
            context = self._context_builder.build(
                connection,
                run=claim.values,
                built_at=built_at,
                projection_only=self._run_store.projection_only,
            )
            if (
                context.run_id != claim.id
                or context.tenant_id != claim.values["tenant_id"]
                or context.project_id != claim.values["project_id"]
                or context.agent_key.value != claim.values["agent_key"]
            ):
                raise RuntimeError("persisted Agent run context does not match its control record")
        self._run_store.persist_context(
            claim=claim,
            context=context,
            persisted_at=built_at,
        )
        return context

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
