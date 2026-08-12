"""Deterministic Finding preflight and restricted persistence port."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol
from uuid import UUID, uuid4

from sqlalchemy import Engine, text

from app.ai.run_store import AgentRunStore, ClaimedAgentRun
from app.ai.runtime_contract import FrozenRunContext
from app.domain.findings import FINDING_PREFLIGHT_VERSION, RiskSuggestionPayload

if TYPE_CHECKING:
    from app.ai.executor import AgentAssessment


class FindingPreflightError(ValueError):
    pass


@dataclass(frozen=True)
class FindingCandidate:
    origin_key: str
    title: str
    summary: str
    payload: RiskSuggestionPayload
    evidence_event_ids: tuple[int, ...]
    confidence_basis_points: int


def preflight_assessment(
    assessment: AgentAssessment,
    *,
    context: FrozenRunContext,
) -> FindingCandidate | None:
    if assessment.disposition == "no_action":
        return None
    evidence = tuple(dict.fromkeys(assessment.evidence_event_ids))
    run_evidence = {event.id for event in context.trigger_events}
    if not evidence or not set(evidence).issubset(run_evidence):
        raise FindingPreflightError("Finding evidence is outside the frozen run context")
    summary = assessment.summary.strip()
    if not summary:
        raise FindingPreflightError("Finding summary is blank")
    return FindingCandidate(
        origin_key=f"assessment:{evidence[-1]}",
        title=summary[:512],
        summary=summary,
        payload=RiskSuggestionPayload(
            title=summary[:512],
            description=summary,
            likelihood=3,
            impact=3,
        ),
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
        if claim.lease_token is None:
            raise RuntimeError("restricted Finding creation requires a run lease")
        finding_id = uuid4()
        with self._engine.begin() as connection:
            self._run_store.bind(connection)
            connection.execute(
                text(
                    "SELECT cehub_ai.create_agent_finding("
                    ":finding_id, :run_id, :lease_token, :invocation_id, :origin_key, "
                    "'risk_suggestion', :title, :summary, CAST(:payload AS jsonb), "
                    "CAST(:evidence AS jsonb), :confidence, :preflight_version, :created_at)"
                ),
                {
                    "finding_id": finding_id,
                    "run_id": context.run_id,
                    "lease_token": claim.lease_token,
                    "invocation_id": model_invocation_id,
                    "origin_key": candidate.origin_key,
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
