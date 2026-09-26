"""Deterministic Finding preflight and restricted persistence port."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol
from uuid import UUID, uuid4

from sqlalchemy import Engine, text

from app.ai.capability_contract import UnknownCapabilityError, capability_for_finding
from app.ai.rollout_guard import require_live_finding
from app.ai.run_store import AgentRunStore, ClaimedAgentRun
from app.ai.runtime_contract import FrozenRunContext, agents_for_event
from app.domain.findings import FINDING_PREFLIGHT_VERSION, FindingPayload

if TYPE_CHECKING:
    from app.ai.executor import AgentAssessment


class FindingPreflightError(ValueError):
    pass


class FindingOutputNarrowedError(ValueError):
    pass


@dataclass(frozen=True)
class FindingCandidate:
    finding_type: str
    origin_key: str
    title: str
    summary: str
    payload: FindingPayload
    evidence_event_ids: tuple[int, ...]
    confidence_basis_points: int


def preflight_assessment(
    assessment: AgentAssessment,
    *,
    context: FrozenRunContext,
) -> FindingCandidate | None:
    if assessment.disposition == "no_action":
        return None
    if assessment.candidate_type is None or assessment.proposed_payload is None:
        raise FindingPreflightError("Finding candidate is incomplete")
    try:
        capability_for_finding(context.agent_key, assessment.candidate_type)
    except UnknownCapabilityError as error:
        raise FindingPreflightError(
            "Finding type is outside the Agent capability contract"
        ) from error
    if any(
        context.agent_key not in agents_for_event(event.event_type)
        for event in context.trigger_events
    ):
        raise FindingPreflightError("Finding evidence is outside the Agent event subscription")
    evidence = tuple(dict.fromkeys(assessment.evidence_event_ids))
    require_live_finding(context.agent_key.value, assessment.candidate_type)
    run_evidence = {event.id for event in context.trigger_events}
    if not evidence or not set(evidence).issubset(run_evidence):
        raise FindingPreflightError("Finding evidence is outside the frozen run context")
    summary = assessment.summary.strip()
    if not summary:
        raise FindingPreflightError("Finding summary is blank")
    return FindingCandidate(
        finding_type=assessment.candidate_type,
        origin_key=f"{assessment.candidate_type}:{evidence[-1]}",
        title=assessment.proposed_payload.title,
        summary=summary,
        payload=assessment.proposed_payload,
        evidence_event_ids=evidence,
        confidence_basis_points=round(assessment.confidence * 10_000),
    )


class AgentFindingWriter(Protocol):
    def create(
        self,
        *,
        claim: ClaimedAgentRun,
        context: FrozenRunContext,
        model_invocation_id: UUID,
        candidate: FindingCandidate,
        created_at: datetime,
    ) -> UUID: ...


class RestrictedAgentFindingWriter:
    def __init__(self, engine: Engine, *, run_store: AgentRunStore) -> None:
        self._engine = engine
        self._run_store = run_store

    def create(
        self,
        *,
        claim: ClaimedAgentRun,
        context: FrozenRunContext,
        model_invocation_id: UUID,
        candidate: FindingCandidate,
        created_at: datetime,
    ) -> UUID:
        require_live_finding(context.agent_key.value, candidate.finding_type)
        if claim.lease_token is None:
            raise RuntimeError("restricted Finding creation requires a run lease")
        finding_id = uuid4()
        with self._engine.begin() as connection:
            self._run_store.bind(connection)
            control_status = connection.execute(
                text(
                    "SELECT status FROM cehub_ai.agent_finding_quality_projection "
                    "WHERE agent_key = :agent_key AND finding_type = :finding_type"
                ),
                {
                    "agent_key": context.agent_key.value,
                    "finding_type": candidate.finding_type,
                },
            ).scalar_one_or_none()
            if control_status == "narrowed":
                raise FindingOutputNarrowedError(candidate.finding_type)
            connection.execute(
                text(
                    "SELECT cehub_ai.create_agent_finding("
                    ":finding_id, :run_id, :lease_token, :invocation_id, :origin_key, "
                    ":finding_type, :title, :summary, CAST(:payload AS jsonb), "
                    "CAST(:evidence AS jsonb), :confidence, :preflight_version, :created_at)"
                ),
                {
                    "finding_id": finding_id,
                    "run_id": context.run_id,
                    "lease_token": claim.lease_token,
                    "invocation_id": model_invocation_id,
                    "origin_key": candidate.origin_key,
                    "finding_type": candidate.finding_type,
                    "title": candidate.title,
                    "summary": candidate.summary,
                    "payload": candidate.payload.model_dump_json(),
                    "evidence": "["
                    + ",".join(str(value) for value in candidate.evidence_event_ids)
                    + "]",
                    "confidence": candidate.confidence_basis_points,
                    "preflight_version": FINDING_PREFLIGHT_VERSION,
                    "created_at": created_at.astimezone(UTC),
                },
            )
        return finding_id
