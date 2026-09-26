"""Explicit risk-suggestion requests routed into the human-review Finding boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import Engine, RowMapping, func, select, update

from app.ai.application_gateway import ApplicationModelGateway
from app.ai.application_leases import bind_write
from app.ai.application_recovery import is_recovery, original_observation, try_resume
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.call_identity import ModelCallSlot, model_call_id
from app.ai.context_builder import RunContextBuilder
from app.ai.executor import AgentAssessment, PromptFile
from app.ai.finding_writer import (
    FindingCandidate,
    FindingOutputNarrowedError,
    preflight_assessment,
)
from app.ai.gateway import GatewayInvocation
from app.ai.model_catalog import AgentTier
from app.ai.quality import FindingQualityService
from app.ai.rollout_guard import (
    CapabilityUnavailableError,
    require_live_finding,
    require_live_key,
)
from app.ai.run_budget_creation import freeze_created_application_run
from app.ai.runtime_contract import AgentKey, FrozenRunContext
from app.db.schema import tables
from app.domain.findings import FINDING_PREFLIGHT_VERSION
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

PROMPT_PATH = Path(__file__).with_name("prompts") / "risk_suggestion_api_v1.json"
RISK_PROMPT = PromptFile.model_validate_json(PROMPT_PATH.read_text())
if RISK_PROMPT.agent_key is not AgentKey.PROJECT_INTELLIGENCE:
    raise RuntimeError("risk suggestion prompt must use Project Intelligence")


class RiskSuggestionEvidenceError(ValueError):
    pass


class RiskSuggestionRequestConflictError(ValueError):
    pass


@dataclass(frozen=True)
class RiskSuggestionResult:
    status: Literal["created", "no_action", "unavailable", "queued", "running"]
    run_id: UUID
    finding_id: UUID | None
    error_code: str | None


class RiskSuggestionService:
    def __init__(self, engine: Engine, *, gateway: ApplicationModelGateway) -> None:
        self._engine = engine
        self._gateway = gateway

    def create(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        request_id: str,
        concern: str,
        evidence_event_ids: tuple[int, ...],
        now: datetime | None = None,
        auth_version: int | None = None,
        enqueue: bool = False,
    ) -> RiskSuggestionResult:
        require_live_key("project_intelligence.risk_suggestion_api")
        require_live_finding("project_intelligence", "risk_suggestion")
        requested_at = (now or datetime.now(UTC)).astimezone(UTC)
        replay = self._replay(
            tenant_id=tenant_id,
            project_id=project_id,
            actor_user_id=actor_user_id,
            request_id=request_id,
            concern=concern,
            evidence_event_ids=evidence_event_ids,
            auth_version=auth_version,
            enqueue=enqueue,
        )
        if isinstance(replay, RiskSuggestionResult):
            return replay
        run = (
            replay
            if replay is not None
            else self._start_run(
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                request_id=request_id,
                concern=concern,
                evidence_event_ids=evidence_event_ids,
                requested_at=requested_at,
                auth_version=auth_version,
                enqueue=enqueue,
            )
        )
        if enqueue:
            return RiskSuggestionResult(
                status="queued", run_id=run["id"], finding_id=None, error_code=None
            )
        run_id = UUID(str(run["id"]))
        try:
            context = self._build_context(run=run, built_at=requested_at)
        except Exception:
            self._finish_run(
                run_id=run_id,
                status="failed",
                error_code="RISK_SUGGESTION_CONTEXT_FAILED",
                completed_at=requested_at,
            )
            raise
        try:
            require_live_key("project_intelligence.risk_suggestion_api")
            require_live_finding("project_intelligence", "risk_suggestion")
            from app.ai.application_domain_context import record, risk_payload

            model_context = risk_payload(context, concern)
            record(
                self._engine,
                tenant_id=tenant_id,
                project_id=project_id,
                run_id=context.run_id,
                model_call_id=model_call_id(context.run_id, ModelCallSlot.RISK_SUGGESTION),
                purpose="risk_suggestion",
                context=model_context,
                snapshot=context.model_dump(mode="json"),
            )
            result = self._gateway.invoke_structured(
                GatewayInvocation(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    run_id=UUID(str(run["id"])),
                    model_call_id=model_call_id(
                        UUID(str(run["id"])), ModelCallSlot.RISK_SUGGESTION
                    ),
                    agent_key=AgentKey.PROJECT_INTELLIGENCE.value,
                    agent_tier=AgentTier.REASONING,
                    prompt_version=RISK_PROMPT.version,
                    system_prompt=RISK_PROMPT.system_prompt,
                    instruction=RISK_PROMPT.instruction,
                    context=model_context,
                ),
                AgentAssessment,
            )
        except (CapabilityUnavailableError, BudgetLedgerError) as error:
            return self._rollout_unavailable(context.run_id, error.code, requested_at)
        except Exception:
            self._finish_run(
                run_id=context.run_id,
                status="failed",
                error_code="RISK_SUGGESTION_EXECUTION_FAILED",
                completed_at=requested_at,
            )
            raise
        if result.status == "degraded" or result.output is None:
            error_code = result.error_code or "MODEL_UNAVAILABLE"
            self._finish_run(
                run_id=context.run_id,
                status="degraded",
                error_code=error_code,
                completed_at=requested_at,
            )
            return RiskSuggestionResult(
                status="unavailable",
                run_id=context.run_id,
                finding_id=None,
                error_code=error_code,
            )
        try:
            require_live_key("project_intelligence.risk_suggestion_api")
            require_live_finding("project_intelligence", "risk_suggestion")
            candidate = preflight_assessment(result.output, context=context)
        except CapabilityUnavailableError as error:
            return self._rollout_unavailable(context.run_id, error.code, requested_at)
        except ValueError as error:
            self._finish_run(
                run_id=context.run_id,
                status="failed",
                error_code="RISK_SUGGESTION_PREFLIGHT_FAILED",
                completed_at=requested_at,
            )
            raise RiskSuggestionEvidenceError("model evidence failed preflight") from error
        if candidate is not None and candidate.finding_type != "risk_suggestion":
            self._finish_run(
                run_id=context.run_id,
                status="failed",
                error_code="RISK_SUGGESTION_TYPE_INVALID",
                completed_at=requested_at,
            )
            raise RiskSuggestionEvidenceError("model output is outside the API contract")
        finding_id = None
        if candidate is not None:
            if result.invocation_id is None:
                self._finish_run(
                    run_id=context.run_id,
                    status="failed",
                    error_code="RISK_SUGGESTION_TRACE_MISSING",
                    completed_at=requested_at,
                )
                raise RuntimeError("successful risk suggestion has no invocation trace")
            try:
                finding_id = self._persist_finding(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    run_id=context.run_id,
                    model_invocation_id=result.invocation_id,
                    actor_user_id=actor_user_id,
                    request_id=request_id,
                    candidate=candidate,
                    created_at=requested_at,
                )
            except CapabilityUnavailableError as error:
                return self._rollout_unavailable(context.run_id, error.code, requested_at)
            except FindingOutputNarrowedError:
                finding_id = None
            except Exception:
                self._finish_run(
                    run_id=context.run_id,
                    status="failed",
                    error_code="RISK_SUGGESTION_PERSIST_FAILED",
                    completed_at=requested_at,
                )
                raise
        self._finish_run(
            run_id=context.run_id,
            status="succeeded",
            error_code=None,
            completed_at=requested_at,
        )
        return RiskSuggestionResult(
            status="created" if finding_id is not None else "no_action",
            run_id=context.run_id,
            finding_id=finding_id,
            error_code=None,
        )

    def _replay(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        request_id: str,
        concern: str,
        evidence_event_ids: tuple[int, ...],
        auth_version: int | None,
        enqueue: bool = False,
    ) -> RiskSuggestionResult | RowMapping | None:
        with self._engine.begin() as connection:
            connection.execute(
                select(tables.tenants.c.id)
                .where(tables.tenants.c.id == tenant_id)
                .with_for_update()
            ).scalar_one()
            rows = list(
                connection.execute(
                    select(tables.agent_runs).where(
                        tables.agent_runs.c.tenant_id == tenant_id,
                        tables.agent_runs.c.project_id == project_id,
                        tables.agent_runs.c.agent_key == AgentKey.PROJECT_INTELLIGENCE.value,
                        tables.agent_runs.c.run_context["api_request_id"].as_string() == request_id,
                    )
                ).mappings()
            )
            if not rows:
                return None
            if len(rows) != 1:
                raise RiskSuggestionRequestConflictError(request_id)
            run = rows[0]
            run_context = dict(run["run_context"])
            if run_context.get("api_actor_user_id") != str(actor_user_id):
                raise RiskSuggestionRequestConflictError(request_id)
            if run_context.get("api_concern") != concern or tuple(
                int(value) for value in run["event_row_ids"]
            ) != tuple(sorted(evidence_event_ids)):
                raise RiskSuggestionRequestConflictError(request_id)
            if enqueue and run["status"] in {"queued", "running"}:
                return RiskSuggestionResult(
                    status=run["status"], run_id=run["id"], finding_id=None, error_code=None
                )
            if (
                run["status"] == "queued"
                and run["run_context"].get("application_queue_version") == 1
            ):
                from app.ai.application_queue_claim import claim_application_queue

                return claim_application_queue(
                    connection,
                    self._gateway,
                    run,
                    auth_version=auth_version,
                    purpose="risk_suggestion",
                )
            if not enqueue and try_resume(
                connection,
                self._gateway,
                run,
                actor=actor_user_id,
                auth_version=auth_version,
                purpose="risk_suggestion",
            ):
                return run
            if run["status"] in {"running", "debouncing", "queued"}:
                raise RiskSuggestionRequestConflictError(request_id)
            finding_id = connection.execute(
                select(tables.findings.c.id).where(
                    tables.findings.c.tenant_id == tenant_id,
                    tables.findings.c.run_id == run["id"],
                    tables.findings.c.origin_key.like(f"api:{request_id}:%"),
                )
            ).scalar_one_or_none()
            status: Literal["created", "no_action", "unavailable"]
            if run["status"] in {"degraded", "failed"}:
                status = "unavailable"
            elif finding_id is not None:
                status = "created"
            else:
                status = "no_action"
            return RiskSuggestionResult(
                status=status,
                run_id=UUID(str(run["id"])),
                finding_id=(UUID(str(finding_id)) if finding_id is not None else None),
                error_code=(str(run["error_code"]) if run["error_code"] is not None else None),
            )

    def _start_run(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        request_id: str,
        concern: str,
        evidence_event_ids: tuple[int, ...],
        requested_at: datetime,
        auth_version: int | None = None,
        enqueue: bool = False,
    ) -> RowMapping:
        if enqueue and getattr(self._gateway, "creation_budget_profile", None) is None:
            raise BudgetLedgerError("APPLICATION_QUEUE_BUDGET_REQUIRED")
        if not evidence_event_ids or len(set(evidence_event_ids)) != len(evidence_event_ids):
            raise RiskSuggestionEvidenceError("evidence_event_ids must be non-empty and unique")
        with self._engine.begin() as connection:
            connection.execute(
                select(tables.tenants.c.id)
                .where(tables.tenants.c.id == tenant_id)
                .with_for_update()
            ).scalar_one()
            existing_request = connection.execute(
                select(tables.agent_runs.c.id).where(
                    tables.agent_runs.c.tenant_id == tenant_id,
                    tables.agent_runs.c.project_id == project_id,
                    tables.agent_runs.c.agent_key == AgentKey.PROJECT_INTELLIGENCE.value,
                    tables.agent_runs.c.run_context["api_request_id"].as_string() == request_id,
                )
            ).scalar_one_or_none()
            if existing_request is not None:
                raise RiskSuggestionRequestConflictError(request_id)
            events = list(
                connection.execute(
                    select(tables.events)
                    .where(
                        tables.events.c.tenant_id == tenant_id,
                        tables.events.c.project_id == project_id,
                        tables.events.c.id.in_(evidence_event_ids),
                        tables.events.c.event_type.in_(
                            ("PROJECT_STAGE_CHANGED", "ISSUE_CREATED", "TEST_FAILED")
                        ),
                    )
                    .order_by(tables.events.c.id)
                ).mappings()
            )
            if len(events) != len(evidence_event_ids):
                raise RiskSuggestionEvidenceError("evidence is outside the Project Agent scope")
            subscription = (
                connection.execute(
                    select(tables.agent_subscriptions).where(
                        tables.agent_subscriptions.c.tenant_id == tenant_id,
                        tables.agent_subscriptions.c.agent_key
                        == AgentKey.PROJECT_INTELLIGENCE.value,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if subscription is None:
                subscription_id = uuid4()
                connection.execute(
                    tables.agent_subscriptions.insert(),
                    {
                        "id": subscription_id,
                        "tenant_id": tenant_id,
                        "agent_key": AgentKey.PROJECT_INTELLIGENCE.value,
                    },
                )
            else:
                subscription_id = UUID(str(subscription["id"]))
            first_timestamp = min(event["timestamp"] for event in events).astimezone(UTC)
            last_timestamp = max(event["timestamp"] for event in events).astimezone(UTC)
            window_started_at = min(first_timestamp, requested_at) - timedelta(microseconds=1)
            window_ended_at = max(last_timestamp, requested_at) + timedelta(microseconds=1)
            run_id = uuid4()
            connection.execute(
                tables.agent_runs.insert(),
                {
                    "id": run_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "subscription_id": subscription_id,
                    "agent_key": AgentKey.PROJECT_INTELLIGENCE.value,
                    "status": "running",
                    "request_id": request_id,
                    "requested_by_user_id": actor_user_id,
                    "context_version": "risk-suggestion-request-v1",
                    "window_started_at": window_started_at,
                    "window_ended_at": window_ended_at,
                    "first_event_row_id": min(evidence_event_ids),
                    "last_event_row_id": max(evidence_event_ids),
                    "event_count": len(evidence_event_ids),
                    "event_row_ids": sorted(evidence_event_ids),
                    "run_context": {
                        "api_request_id": request_id,
                        "api_actor_user_id": str(actor_user_id),
                        "api_concern": concern,
                        **({"application_queue_version": 1} if enqueue else {}),
                    },
                    "started_at": requested_at,
                    "created_at": requested_at,
                    "updated_at": requested_at,
                },
            )
            freeze_created_application_run(
                connection,
                self._gateway,
                tenant_id=tenant_id,
                run_id=run_id,
                actor_user_id=actor_user_id,
                purpose="risk_suggestion",
                auth_version=auth_version,
                issue_lease=not enqueue,
            )
            if enqueue:
                connection.execute(
                    tables.agent_runs.update()
                    .where(tables.agent_runs.c.id == run_id)
                    .values(status="queued", started_at=None, updated_at=func.clock_timestamp())
                )
            return (
                connection.execute(
                    select(tables.agent_runs).where(tables.agent_runs.c.id == run_id)
                )
                .mappings()
                .one()
            )

    def _build_context(self, *, run: RowMapping, built_at: datetime) -> FrozenRunContext:
        with self._engine.begin() as connection:
            bind_write(connection, self._gateway, run["tenant_id"], run["id"])
            if is_recovery(self._gateway, run["tenant_id"], run["id"]):
                return FrozenRunContext.model_validate(
                    original_observation(connection, run)["output_body"]
                )
            context = RunContextBuilder().build(connection, run=run, built_at=built_at)
            persisted_context = context.model_dump(mode="json")
            persisted_context["api_request_id"] = str(run["run_context"]["api_request_id"])
            persisted_context["api_actor_user_id"] = str(run["run_context"]["api_actor_user_id"])
            persisted_context["api_concern"] = str(run["run_context"]["api_concern"])
            if run["run_context"].get("application_queue_version") == 1:
                persisted_context["application_queue_version"] = 1
            connection.execute(
                update(tables.agent_runs)
                .where(tables.agent_runs.c.id == context.run_id)
                .values(run_context=persisted_context, updated_at=built_at)
            )
        return context

    def _persist_finding(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        run_id: UUID,
        model_invocation_id: UUID,
        actor_user_id: UUID,
        request_id: str,
        candidate: FindingCandidate,
        created_at: datetime,
    ) -> UUID:
        require_live_key("project_intelligence.risk_suggestion_api")
        require_live_finding("project_intelligence", candidate.finding_type)
        finding_id = uuid4()
        origin_key = f"api:{request_id}:{candidate.origin_key}"[:128]
        with self._engine.begin() as connection:
            bind_write(connection, self._gateway, tenant_id, run_id)
            existing = (
                connection.execute(
                    select(tables.findings).where(
                        tables.findings.c.tenant_id == tenant_id,
                        tables.findings.c.run_id == run_id,
                        tables.findings.c.origin_key == origin_key,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                if (
                    existing["model_invocation_id"] != model_invocation_id
                    or existing["finding_type"] != candidate.finding_type
                    or existing["proposed_payload"] != candidate.payload.model_dump(mode="json")
                ):
                    raise RiskSuggestionRequestConflictError(request_id)
                return UUID(str(existing["id"]))
            if not FindingQualityService.is_output_allowed_connection(
                connection,
                tenant_id=tenant_id,
                agent_key=AgentKey.PROJECT_INTELLIGENCE.value,
                finding_type=candidate.finding_type,
            ):
                raise FindingOutputNarrowedError(candidate.finding_type)
            connection.execute(
                tables.findings.insert(),
                {
                    "id": finding_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "run_id": run_id,
                    "model_invocation_id": model_invocation_id,
                    "agent_key": AgentKey.PROJECT_INTELLIGENCE.value,
                    "finding_type": candidate.finding_type,
                    "origin_key": origin_key,
                    "status": "pending_review",
                    "title": candidate.title,
                    "summary": candidate.summary,
                    "proposed_payload": candidate.payload.model_dump(mode="json"),
                    "evidence_event_ids": list(candidate.evidence_event_ids),
                    "confidence_basis_points": candidate.confidence_basis_points,
                    "preflight_version": FINDING_PREFLIGHT_VERSION,
                    "created_at": created_at,
                    "updated_at": created_at,
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
                    "actor_user_id": None,
                    "to_status": "pending_review",
                    "detail": {
                        "preflight_version": FINDING_PREFLIGHT_VERSION,
                        "request_id": request_id,
                    },
                    "created_at": created_at,
                },
            )
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"ai-finding:{finding_id}:created",
                    event_type="AI_FINDING_CREATED",
                    source="ai_runtime",
                    entity_id=finding_id,
                    payload={"finding_id": str(finding_id), "agent_run_id": str(run_id)},
                    occurred_at=created_at,
                ),
                AuditDraft(
                    action="finding.create_from_api",
                    after_snapshot={
                        "finding_id": str(finding_id),
                        "finding_type": candidate.finding_type,
                        "status": "pending_review",
                        "title": candidate.title,
                    },
                    context={
                        "request_id": request_id,
                        "run_id": str(run_id),
                        "model_invocation_id": str(model_invocation_id),
                    },
                ),
            )
        return finding_id

    def _rollout_unavailable(
        self, run_id: UUID, error_code: str, completed_at: datetime
    ) -> RiskSuggestionResult:
        self._finish_run(
            run_id=run_id, status="degraded", error_code=error_code, completed_at=completed_at
        )
        return RiskSuggestionResult(
            status="unavailable", run_id=run_id, finding_id=None, error_code=error_code
        )

    def _finish_run(
        self,
        *,
        run_id: UUID,
        status: Literal["succeeded", "degraded", "failed"],
        error_code: str | None,
        completed_at: datetime,
    ) -> None:
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(tables.agent_runs)
                    .where(
                        tables.agent_runs.c.id == run_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            if row["status"] != "running":
                return
            bind_write(
                connection, self._gateway, row["tenant_id"], run_id, success=status == "succeeded"
            )
            connection.execute(
                update(tables.agent_runs)
                .where(tables.agent_runs.c.id == run_id, tables.agent_runs.c.status == "running")
                .values(
                    status=status,
                    completed_at=completed_at,
                    error_code=error_code,
                    updated_at=completed_at,
                )
            )

    @staticmethod
    def _trigger(event: BaseModel) -> dict[str, object]:
        values = event.model_dump(mode="json")
        return {
            "event_type": values["event_type"],
            "entity": values["entity"],
            "entity_id": values["entity_id"],
            "timestamp": values["timestamp"],
        }
