"""LangGraph execution plane for server-frozen Agent runs."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Protocol, TypedDict, cast, get_args
from uuid import UUID

from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import Engine, text

from app.ai.call_identity import ModelCallSlot, loop_model_call_id, model_call_id
from app.ai.checkpoints import AgentCheckpointError, AgentResultCheckpoints
from app.ai.context_builder import RunContextBuilder
from app.ai.embeddings import EmbeddingGateway
from app.ai.finding_writer import (
    AgentFindingWriter,
    FindingOutputNarrowedError,
    FindingPreflightError,
    preflight_assessment,
)
from app.ai.gateway import GatewayInvocation, GatewayResult, StructuredModelGateway
from app.ai.lease_heartbeat import AgentLeaseLostError
from app.ai.loop_policy import LoopBinding, loop_contract_digest
from app.ai.observations import AgentObservationError, AgentObservations, context_receipt_body
from app.ai.run_store import AgentRunStore, ClaimedAgentRun, OwnerAgentRunStore
from app.ai.runtime_contract import AgentKey, FrozenRunContext
from app.ai.tools import AgentReadTools, ProjectContextResult, ToolPage, tool_definitions_for_agent
from app.contracts.runtime_records import Observation
from app.domain.findings import (
    FINDING_PREFLIGHT_VERSION,
    KnowledgeDraftPayload,
    RiskSuggestionPayload,
)

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


# Explicit API-only capabilities do not expand the event worker output schema.
FindingType = Literal[FindingCandidateType, "test_plan_change"]


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


class AgentResultCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["agent-result.v1"] = "agent-result.v1"
    runtime_digest: str = Field(pattern="^[a-f0-9]{64}$")
    context: FrozenRunContext
    result: GatewayResult[AgentAssessment]
    recent_events: ToolPage
    memory: ToolPage
    domain_evidence: ToolPage
    additional_reads: tuple[LoopToolRead, ...] = ()

    @model_validator(mode="after")
    def complete_result_shape(self) -> AgentResultCheckpoint:
        result = self.result
        if result.invocation_id is None or result.structured_attempts < 0:
            raise ValueError("checkpoint_requires_persisted_model_result")
        if result.status == "succeeded":
            if result.output is None or result.error_code is not None:
                raise ValueError("checkpoint_success_requires_output")
        elif result.output is not None or not result.error_code:
            raise ValueError("checkpoint_degraded_requires_error")
        return self


def checkpoint_runtime_digest(agent_key: AgentKey) -> str:
    return sha256(
        json.dumps(
            {
                "format": "agent-result.v1",
                "observation_schema": Observation.model_json_schema(),
                "context_receipt_version": "projected-context-receipt.v1",
                "prompt_version": PROMPT_VERSIONS[agent_key],
                "system_prompt": SYSTEM_PROMPTS[agent_key],
                "instruction": INSTRUCTIONS[agent_key],
                "output_schema": AgentAssessment.model_json_schema(),
                "context_schema": FrozenRunContext.model_json_schema(),
                "tool_page_schema": ToolPage.model_json_schema(),
                "tool_dispatch_policy": "durable-single-dispatch.v1",
                "checkpoint_schema": AgentResultCheckpoint.model_json_schema(),
                "loop_checkpoint_schema": AgentLoopCheckpoint.model_json_schema(),
                "preflight_version": FINDING_PREFLIGHT_VERSION,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


class AgentModelInvoker(Protocol):
    def invoke(self, invocation: GatewayInvocation) -> GatewayResult[AgentAssessment]: ...


class GatewayAgentModelInvoker:
    def __init__(self, gateway: StructuredModelGateway) -> None:
        self._gateway = gateway

    def invoke(self, invocation: GatewayInvocation) -> GatewayResult[AgentAssessment]:
        return self._gateway.invoke_structured(invocation, AgentAssessment)

    def decide(self, invocation: GatewayInvocation) -> GatewayResult[AgentLoopStep]:
        return self._gateway.invoke_structured(invocation, AgentLoopStep)


class LoopToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Literal[
        "get_project_context",
        "get_recent_events",
        "search_memory",
        "get_engineering_evidence",
        "get_quality_evidence",
        "get_supplier_delay_evidence",
        "get_portfolio_brief",
    ]
    query: str | None = Field(default=None, min_length=1, max_length=500)
    after_id: int = Field(default=0, ge=0, strict=True)
    offset: int = Field(default=0, ge=0, le=10000, strict=True)
    limit: int = Field(default=20, ge=1, le=20, strict=True)

    @model_validator(mode="after")
    def appropriate_parameters(self) -> LoopToolRequest:
        if self.name == "search_memory":
            if self.query is None or not self.query.strip() or self.after_id:
                raise ValueError("memory query required; after_id is not a memory cursor")
        elif self.query is not None or (self.after_id and self.name != "get_recent_events"):
            raise ValueError("parameters do not belong to this tool")
        if self.offset and self.name in {"get_project_context", "get_recent_events"}:
            raise ValueError("offset is not a cursor for this tool")
        return self

    def arguments(self, project_id: UUID) -> dict[str, object]:
        args: dict[str, object] = {"project_id": str(project_id)}
        if self.name != "get_project_context":
            args["limit"] = self.limit
            args["after_id" if self.name == "get_recent_events" else "offset"] = (
                self.after_id if self.name == "get_recent_events" else self.offset
            )
        if self.name == "search_memory":
            args["query"] = self.query
        return args


class LoopToolRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request: LoopToolRequest
    output: ProjectContextResult | ToolPage


class AgentLoopStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: Literal["tool", "final"]
    tool: LoopToolRequest | None
    assessment: AgentAssessment | None

    @model_validator(mode="after")
    def one_action(self) -> AgentLoopStep:
        if self.action == "tool" and (self.tool is None or self.assessment is not None):
            raise ValueError("tool action requires only a tool request")
        if self.action == "final" and (self.assessment is None or self.tool is not None):
            raise ValueError("final action requires only an assessment")
        return self


class AgentLoopCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal["agent-loop-checkpoint.v1"] = "agent-loop-checkpoint.v1"
    runtime_digest: str = Field(pattern="^[a-f0-9]{64}$")
    context: FrozenRunContext
    next_step: int = Field(ge=1, le=99)
    model_invocation_id: UUID
    project_context: ProjectContextResult
    recent_events: ToolPage
    memory: ToolPage
    domain_evidence: ToolPage
    observation_ids: tuple[UUID, ...]
    tool_observations: tuple[dict[str, object], ...]
    additional_reads: tuple[LoopToolRead, ...]
    references: list[dict[str, object]]


LOOP_INSTRUCTION = (
    "Choose exactly one action per response: request a listed read-only tool or return a final "
    "assessment. Do not supply tenant_id or project_id; the server injects the run scope. "
    "Inspect observed evidence "
    "and completeness before deciding; unavailable sources are not empty or verified facts. "
    "No business writes or external tools exist in this loop. Every call uses the original run "
    "budget. On the final permitted step, finish honestly with available evidence; never invent "
    "missing facts. Do not include private reasoning. "
)


def loop_system_prompt(agent_key: AgentKey) -> str:
    names = set(get_args(LoopToolRequest.model_fields["name"].annotation))
    definitions = [
        d.model_dump(mode="json") for d in tool_definitions_for_agent(agent_key) if d.name in names
    ]
    for definition in definitions:
        definition["input_example"].pop("project_id", None)
    return (
        _PROMPTS[agent_key].system_prompt
        + "\nFROZEN_READ_ONLY_TOOLS\n"
        + json.dumps(definitions, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


AgentResultCheckpoint.model_rebuild()


class ExecutorState(TypedDict, total=False):
    run_context: FrozenRunContext
    project_context: ProjectContextResult
    recent_events: ToolPage
    memory: ToolPage
    domain_evidence: ToolPage
    gateway_result: GatewayResult[AgentAssessment]
    observation_ids: tuple[UUID, ...]
    tool_observations: tuple[dict[str, object], ...]
    loop_enabled: bool
    loop_checkpoint: AgentLoopCheckpoint
    additional_reads: tuple[LoopToolRead, ...]


class CompiledExecutorGraph(Protocol):
    def invoke(self, state: ExecutorState) -> ExecutorState: ...


@dataclass(frozen=True)
class ExecutionResult:
    run_id: UUID | None
    status: Literal["idle", "succeeded", "degraded", "failed", "paused"]
    error_code: str | None
    finding_id: UUID | None = None


class AgentRunPaused(Exception):
    pass


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
        loop_binding: LoopBinding | None = None,
        loop_step_limit: int = 0,
    ) -> None:
        self._engine = engine
        self._model_invoker = model_invoker
        self._context_builder = context_builder or RunContextBuilder()
        self._run_store = run_store or OwnerAgentRunStore(engine)
        self._finding_writer = finding_writer
        self._embedding_gateway = embedding_gateway
        if loop_binding is not None and (not 1 <= loop_step_limit < 100):
            raise ValueError("loop requires a bounded model-call profile")
        self._loop_binding, self._loop_step_limit = loop_binding, loop_step_limit
        self._checkpoints = (
            AgentResultCheckpoints(engine, self._run_store)
            if self._run_store.projection_only
            else None
        )
        self._observations = (
            AgentObservations(engine, self._run_store) if self._run_store.projection_only else None
        )
        self._graph = self._build_graph()

    def execute_next(self, *, now: datetime | None = None) -> ExecutionResult:
        current_time = (now or datetime.now(UTC)).astimezone(UTC)
        claim = self._run_store.claim(started_at=current_time)
        if claim is None:
            return ExecutionResult(run_id=None, status="idle", error_code=None)

        try:
            return self._execute_claim(claim, current_time)
        except AgentRunPaused:
            return ExecutionResult(run_id=claim.id, status="paused", error_code=None)
        except AgentLeaseLostError:
            # The old executor no longer has authority to publish/finalize. Keep
            # the persistent run and unknown receipts for service recovery.
            return ExecutionResult(
                run_id=claim.id, status="failed", error_code="AGENT_RUN_LEASE_LOST"
            )

    def _pause_at_checkpoint(self) -> None:
        if self._observations is not None and self._observations._call(
            "SELECT cehub_ai.honor_event_pause()"
        ):
            raise AgentRunPaused

    def _execute_claim(self, claim: ClaimedAgentRun, current_time: datetime) -> ExecutionResult:
        with self._run_store.scope(claim):
            try:
                self._pause_at_checkpoint()
                from app.ai.rollout_guard import require_employee_agent

                require_employee_agent(AgentKey(str(claim.values["agent_key"])))
                if self._observations is not None:
                    self._observations.authorization()
                loop_enabled = self._check_loop_binding(claim)
                if self._observations is not None:
                    from app.ai.context_manifests import bind_bundle

                    bind_bundle(
                        self._observations, str(claim.values["agent_key"]), loop=loop_enabled
                    )
                saved = self._checkpoints.load(claim) if self._checkpoints else None
                if saved is not None:
                    checkpoint = AgentResultCheckpoint.model_validate(saved)
                    context, result = checkpoint.context, checkpoint.result
                    if (
                        context.run_id != claim.id
                        or context.tenant_id != claim.values["tenant_id"]
                        or context.project_id != claim.values["project_id"]
                        or context.agent_key.value != claim.values["agent_key"]
                    ):
                        raise AgentCheckpointError("AGENT_CHECKPOINT_SCOPE_INVALID")
                    if checkpoint.runtime_digest != checkpoint_runtime_digest(context.agent_key):
                        raise AgentCheckpointError("AGENT_CHECKPOINT_VERSION_MISMATCH")
                    self._recheck_checkpoint_sources(claim, checkpoint, current_time)
                else:
                    loop_saved = (
                        self._observations._call("SELECT cehub_ai.load_agent_loop_checkpoint()")
                        if loop_enabled and self._observations is not None
                        else None
                    )
                    if loop_saved is not None:
                        step_checkpoint = AgentLoopCheckpoint.model_validate(loop_saved)
                        context = step_checkpoint.context
                        if (
                            context.run_id != claim.id
                            or context.tenant_id != claim.values["tenant_id"]
                            or context.project_id != claim.values["project_id"]
                            or context.agent_key.value != claim.values["agent_key"]
                        ):
                            raise AgentCheckpointError("AGENT_CHECKPOINT_SCOPE_INVALID")
                        if step_checkpoint.runtime_digest != checkpoint_runtime_digest(
                            context.agent_key
                        ):
                            raise AgentCheckpointError("AGENT_CHECKPOINT_VERSION_MISMATCH")
                        self._recheck_checkpoint_sources(claim, step_checkpoint, current_time)
                        final_state: ExecutorState = {
                            "run_context": context,
                            "project_context": step_checkpoint.project_context,
                            "recent_events": step_checkpoint.recent_events,
                            "memory": step_checkpoint.memory,
                            "domain_evidence": step_checkpoint.domain_evidence,
                            "observation_ids": step_checkpoint.observation_ids,
                            "tool_observations": step_checkpoint.tool_observations,
                            "loop_enabled": True,
                            "loop_checkpoint": step_checkpoint,
                        }
                        final_state.update(cast(ExecutorState, self._invoke_model(final_state)))
                    else:
                        context = self._load_context(claim=claim, built_at=current_time)
                        final_state = self._graph.invoke(
                            {"run_context": context, "loop_enabled": loop_enabled}
                        )
                    result = final_state["gateway_result"]
                    if self._checkpoints is not None and result.invocation_id is not None:
                        self._checkpoints.save(
                            claim,
                            AgentResultCheckpoint(
                                runtime_digest=checkpoint_runtime_digest(context.agent_key),
                                context=context,
                                result=result,
                                recent_events=final_state["recent_events"],
                                memory=final_state["memory"],
                                domain_evidence=final_state["domain_evidence"],
                                additional_reads=final_state.get("additional_reads", ()),
                            ).model_dump_json(),
                        )
                self._pause_at_checkpoint()
                require_employee_agent(context.agent_key)
                if result.status == "succeeded" and self._observations is not None:
                    self._observations._call("SELECT cehub_ai.verify_agent_manifest_sources()")
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
                if isinstance(error, (AgentLeaseLostError, AgentRunPaused)):
                    raise
                from app.ai.rollout_guard import CapabilityUnavailableError

                if isinstance(error, CapabilityUnavailableError):
                    self._run_store.complete(
                        claim=claim,
                        status="degraded",
                        error_code=error.code,
                        completed_at=current_time,
                    )
                    return ExecutionResult(
                        run_id=claim.id, status="degraded", error_code=error.code
                    )
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

    def _recheck_checkpoint_sources(
        self,
        claim: ClaimedAgentRun,
        checkpoint: AgentResultCheckpoint | AgentLoopCheckpoint,
        now: datetime,
    ) -> None:
        original = checkpoint.context
        with self._engine.begin() as connection:
            self._run_store.bind(connection)
            current = self._context_builder.build(
                connection, run=claim.values, built_at=now, projection_only=True
            )
            before = original.model_dump(mode="json")
            after = current.model_dump(mode="json")
            for body in (before, after):
                body.pop("built_at")
                # These two counters reflect the already-accounted model call,
                # not mutable business evidence. Actual budgets are checked in SQL.
                for key in ("remaining_tokens_today", "agent_runs_today"):
                    body["execution"].pop(key, None)
            if before != after:
                raise AgentCheckpointError("AGENT_CHECKPOINT_SOURCES_CHANGED")
            memories = (
                *checkpoint.memory.items,
                *(
                    item
                    for read in checkpoint.additional_reads
                    if read.request.name == "search_memory" and isinstance(read.output, ToolPage)
                    for item in read.output.items
                ),
            )
            if memories:
                ids = [UUID(str(item["memory_id"])) for item in memories]
                visible = connection.execute(
                    text("""SELECT DISTINCT memory_id,title,
                    left(content,4000) AS content,applicability,tags,source_refs,content_sha256
                    FROM cehub_ai.agent_memory_projection
                    WHERE memory_id=ANY(CAST(:ids AS uuid[]))"""),
                    {"ids": ids},
                ).mappings()
                actual = {
                    str(row["memory_id"]): {**dict(row), "memory_id": str(row["memory_id"])}
                    for row in visible
                }
                expected = {
                    str(item["memory_id"]): {
                        key: value for key, value in item.items() if key != "similarity"
                    }
                    for item in memories
                }
                if actual != expected:
                    raise AgentCheckpointError("AGENT_CHECKPOINT_SOURCES_CHANGED")
        state: ExecutorState = {"run_context": original}
        if (
            self._get_recent_events(state)["recent_events"] != checkpoint.recent_events
            or self._get_domain_evidence(state)["domain_evidence"] != checkpoint.domain_evidence
        ):
            raise AgentCheckpointError("AGENT_CHECKPOINT_SOURCES_CHANGED")
        for read in checkpoint.additional_reads:
            if (
                read.request.name != "search_memory"
                and self._read_loop_tool(original, read.request) != read.output
            ):
                raise AgentCheckpointError("AGENT_CHECKPOINT_SOURCES_CHANGED")

    def _check_loop_binding(self, claim: ClaimedAgentRun) -> bool:
        body = (
            self._observations._call("SELECT cehub_ai.read_agent_loop_binding()")
            if self._observations
            else claim.values.get("loop_binding")
        )
        if body is None:
            return False
        binding = LoopBinding.model_validate(body)
        if (
            binding != self._loop_binding
            or binding.qualification.runtime_digest != loop_contract_digest()
        ):
            raise AgentObservationError("AGENT_LOOP_BINDING_MISMATCH")
        return True

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
        for key, function in (
            ("get_project_context", self._get_project_context),
            ("get_recent_events", self._get_recent_events),
            ("search_memory", self._search_memory),
            ("get_domain_evidence", self._get_domain_evidence),
        ):
            graph.add_node(key, RunnableLambda(self._observed_node(key, function)))
        graph.add_node("invoke_model", self._invoke_model)
        graph.add_edge(START, "get_project_context")
        graph.add_edge("get_project_context", "get_recent_events")
        graph.add_edge("get_recent_events", "search_memory")
        graph.add_edge("search_memory", "get_domain_evidence")
        graph.add_edge("get_domain_evidence", "invoke_model")
        graph.add_edge("invoke_model", END)
        return cast(CompiledExecutorGraph, graph.compile())

    def _observed_node(
        self,
        key: str,
        function: Callable[[ExecutorState], Mapping[str, BaseModel]],
    ) -> Callable[[ExecutorState], dict[str, object]]:
        def run(state: ExecutorState) -> dict[str, object]:
            if self._observations is None:
                return dict(function(state))
            context = state["run_context"]
            tool_key = key
            if key == "get_domain_evidence":
                tool_key = {
                    AgentKey.ENGINEERING_INTELLIGENCE: "get_engineering_evidence",
                    AgentKey.QUALITY_INTELLIGENCE: "get_quality_evidence",
                    AgentKey.SUPPLIER_INTELLIGENCE: "get_supplier_delay_evidence",
                    AgentKey.EXECUTIVE_INTELLIGENCE: "get_portfolio_brief",
                }.get(context.agent_key, "")
                if not tool_key:
                    return dict(function(state))
            arguments: dict[str, object] = {"project_id": str(context.project_id)}
            if key != "get_project_context":
                arguments["limit"] = 20
            if key == "search_memory":
                arguments["query"] = "Project evidence relevant to the current trigger events"
            call_id = self._observations.prepare(
                context=context,
                call_key=f"initial.{key}",
                tool_key=tool_key,
                arguments=arguments,
            )
            self._observations.dispatch(call_id)
            try:
                updates = function(state)
            except Exception as error:
                if isinstance(error, AgentLeaseLostError):
                    raise
                code = self._error_code(error)
                self._observations.append(
                    context=context,
                    call_key=f"initial.{key}",
                    tool_key=tool_key,
                    arguments=arguments,
                    output={"error_code": code},
                    error_code=code,
                )
                raise
            output = next(iter(updates.values()))
            if not isinstance(output, BaseModel):
                raise AgentObservationError("AGENT_TOOL_OUTPUT_INVALID")
            observation = self._observations.append(
                context=context,
                call_key=f"initial.{key}",
                tool_key=tool_key,
                arguments=arguments,
                output=output.model_dump(mode="json"),
            )
            return {
                **updates,
                "observation_ids": (*state.get("observation_ids", ()), observation.id),
                "tool_observations": (
                    *state.get("tool_observations", ()),
                    {
                        "tool": tool_key,
                        "status": observation.status,
                        "shown_count": observation.shown_count,
                        "total_count": observation.total_count,
                        "truncated": observation.truncated,
                        "continuation": observation.continuation,
                        "error_code": observation.error_code,
                    },
                ),
            }

        return run

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
    ) -> dict[str, object]:
        from app.ai.rollout_guard import require_employee_agent

        context = state["run_context"]
        require_employee_agent(context.agent_key)
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
            model_call_id=model_call_id(context.run_id, ModelCallSlot.EVENT_ASSESSMENT),
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
                "tool_observations": list(state.get("tool_observations", ())),
            },
        )
        if state.get("loop_enabled", False):
            return self._run_tool_loop(state, invocation)
        if self._observations is not None:
            assert invocation.model_call_id is not None
            receipt = self._observations.freeze(
                invocation.model_call_id,
                context_receipt_body(
                    context=invocation.context,
                    prompt_version=invocation.prompt_version,
                    system_prompt=invocation.system_prompt,
                    instruction=invocation.instruction,
                    output_type=AgentAssessment,
                ),
                state["observation_ids"],
            )
            invocation = invocation.model_copy(update={"context_receipt_id": receipt})
        return {"gateway_result": self._model_invoker.invoke(invocation)}

    def _read_loop_tool(
        self, context: FrozenRunContext, request: LoopToolRequest
    ) -> ProjectContextResult | ToolPage:
        if request.name not in {d.name for d in tool_definitions_for_agent(context.agent_key)}:
            raise AgentObservationError("AGENT_LOOP_TOOL_NOT_ALLOWED")
        tools = AgentReadTools(
            self._engine,
            run_context=context,
            run_store=self._run_store,
            embedding_gateway=self._embedding_gateway,
        )
        # The selected method is restricted to the closed, validated schema above.
        args = request.arguments(context.project_id)
        args["project_id"] = context.project_id
        handler = cast(Callable[..., ProjectContextResult | ToolPage], getattr(tools, request.name))
        return handler(**args)

    def _run_tool_loop(
        self, state: ExecutorState, original: GatewayInvocation
    ) -> dict[str, object]:
        from app.ai.rollout_guard import require_employee_agent

        assert self._loop_binding is not None and self._observations is not None
        if not isinstance(self._model_invoker, GatewayAgentModelInvoker):
            raise AgentObservationError("AGENT_LOOP_INVOKER_REQUIRED")
        context = state["run_context"]
        ids = state["observation_ids"]
        summaries = list(state.get("tool_observations", ()))
        saved = state.get("loop_checkpoint")
        reads = list(saved.additional_reads) if saved else []
        references = (
            list(saved.references)
            if saved
            else list(cast(list[dict[str, object]], original.context["references"]))
        )
        for step in range(saved.next_step if saved else 0, self._loop_step_limit):
            require_employee_agent(context.agent_key)
            binding = self._loop_binding
            if binding.qualification.runtime_digest != loop_contract_digest():
                raise AgentObservationError("AGENT_LOOP_BINDING_MISMATCH")
            invocation = original.model_copy(
                update={
                    "model_call_id": loop_model_call_id(context.run_id, step),
                    "prompt_version": f"{PROMPT_VERSIONS[context.agent_key]}.loop.v1",
                    "system_prompt": loop_system_prompt(context.agent_key),
                    "instruction": LOOP_INSTRUCTION + INSTRUCTIONS[context.agent_key],
                    "expected_provider": binding.qualification.provider,
                    "expected_model": binding.qualification.model,
                    "context": {
                        **original.context,
                        "references": references,
                        "tool_observations": summaries,
                        "loop": {"step": step, "step_limit": self._loop_step_limit},
                    },
                }
            )
            assert invocation.model_call_id is not None
            receipt = self._observations.freeze(
                invocation.model_call_id,
                context_receipt_body(
                    context=invocation.context,
                    prompt_version=invocation.prompt_version,
                    system_prompt=invocation.system_prompt,
                    instruction=invocation.instruction,
                    output_type=AgentLoopStep,
                ),
                ids,
            )
            result = self._model_invoker.decide(
                invocation.model_copy(update={"context_receipt_id": receipt})
            )
            if result.status != "succeeded" or result.output is None:
                return {
                    "gateway_result": replace(result, output=None),
                    "additional_reads": tuple(reads),
                }
            decision = result.output
            if decision.action == "final":
                return {
                    "gateway_result": GatewayResult[AgentAssessment](
                        status=result.status,
                        output=decision.assessment,
                        error_code=result.error_code,
                        structured_attempts=result.structured_attempts,
                        removed_context_paths=result.removed_context_paths,
                        invocation_id=result.invocation_id,
                    ),
                    "additional_reads": tuple(reads),
                }
            if step + 1 == self._loop_step_limit:
                return {
                    "gateway_result": replace(
                        result, status="degraded", output=None, error_code="AGENT_LOOP_MODEL_LIMIT"
                    ),
                    "additional_reads": tuple(reads),
                }
            request = decision.tool
            assert request is not None
            if request.name not in {d.name for d in tool_definitions_for_agent(context.agent_key)}:
                raise AgentObservationError("AGENT_LOOP_TOOL_NOT_ALLOWED")
            key = f"loop.{step}.{request.name}"
            arguments = request.arguments(context.project_id)
            call_id = self._observations.prepare(
                context=context, call_key=key, tool_key=request.name, arguments=arguments
            )
            self._observations.dispatch(call_id)
            try:
                output = self._read_loop_tool(context, request)
            except AgentLeaseLostError:
                raise
            except Exception as error:
                code = self._error_code(error)
                self._observations.append(
                    context=context,
                    call_key=key,
                    tool_key=request.name,
                    arguments=arguments,
                    output={"error_code": code},
                    error_code=code,
                )
                raise
            observation = self._observations.append(
                context=context,
                call_key=key,
                tool_key=request.name,
                arguments=arguments,
                output=output.model_dump(mode="json"),
            )
            reads.append(LoopToolRead(request=request, output=output))
            ids = (*ids, observation.id)
            summaries.append(
                {
                    "tool": request.name,
                    "status": observation.status,
                    "shown_count": observation.shown_count,
                    "total_count": observation.total_count,
                    "truncated": observation.truncated,
                    "continuation": observation.continuation,
                    "error_code": observation.error_code,
                    "request": request.model_dump(mode="json"),
                }
            )
            if isinstance(output, ToolPage):
                for item in output.items:
                    if request.name == "search_memory":
                        reference = {
                            "reference_id": f"memory:{item['memory_id']}",
                            "entity": "memory",
                            "entity_id": item["memory_id"],
                            "label": item["title"],
                            "excerpt": str(item["content"])[:1000],
                        }
                    elif request.name == "get_recent_events":
                        reference = {
                            "reference_id": f"event:{item['id']}",
                            "entity": item["entity"],
                            "entity_id": item["entity_id"],
                            "label": item["event_type"],
                        }
                    else:
                        reference = item
                    if reference not in references:
                        references.append(reference)
            if result.invocation_id is None:
                raise AgentCheckpointError("AGENT_LOOP_CHECKPOINT_TRACE_REQUIRED")
            self._observations._call(
                "SELECT cehub_ai.save_agent_loop_checkpoint(:body)",
                body=AgentLoopCheckpoint(
                    runtime_digest=checkpoint_runtime_digest(context.agent_key),
                    context=context,
                    next_step=step + 1,
                    model_invocation_id=result.invocation_id,
                    project_context=state["project_context"],
                    recent_events=state["recent_events"],
                    memory=state["memory"],
                    domain_evidence=state["domain_evidence"],
                    observation_ids=ids,
                    tool_observations=tuple(summaries),
                    additional_reads=tuple(reads),
                    references=references,
                ).model_dump_json(),
            )
            self._pause_at_checkpoint()
        raise AgentObservationError("AGENT_LOOP_MODEL_LIMIT")

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
        if isinstance(error, (AgentCheckpointError, AgentObservationError)):
            return error.code
        if isinstance(error, FindingPreflightError):
            # A model output rejected by the Finding contract is not a tool-input fault.
            return "FINDING_PREFLIGHT_REJECTED"
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
