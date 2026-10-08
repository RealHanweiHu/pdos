"""Authorized immutable inputs only; this projection has no second result ledger."""

from pdos_next.errors import DomainError
from pdos_next.schemas.manufacturing_trials.contracts import (
    DTO,
    Observation,
    PilotRun,
    Readiness,
    ToolTrial,
    YieldResult,
    YieldScope,
)


class TrialReading(DTO):
    trial: ToolTrial
    quality_request_pending_owner: bool = True
    # Actual sample-ready/offer/accept/measurement milestones come from verification.
    tooling_acceptance_authority: str = "NAMED_T2_OWNER"


class PilotReading(DTO):
    pilot: PilotRun
    preparation_at_creation: Readiness
    current_preparation: Readiness | None
    latest: Observation | None
    superseded: tuple[Observation, ...]
    yield_scope: YieldScope | None
    yield_result: YieldResult | None
    manufacturing_release_authority: str = "NAMED_T2_OWNER"


def pilot_reading(
    pilot: PilotRun,
    observations: tuple[Observation, ...],
    current_preparation: Readiness | None = None,
) -> PilotReading:
    if any(o.pilot_id != pilot.id for o in observations):
        raise DomainError("FORBIDDEN_SCOPE", "不能混入另一试产的结果历史。", 403)
    if len({o.id for o in observations}) != len(observations):
        raise DomainError("DUPLICATE_HISTORY", "不可变观察历史重复。", 503)
    latest = next((o for o in observations if o.id == pilot.latest_observation_id), None)
    if pilot.latest_observation_id and latest is None:
        raise DomainError("INCOMPLETE_HISTORY", "当前观察未返回，不得用历史结果冒充。", 503)
    return PilotReading(
        pilot=pilot,
        preparation_at_creation=pilot.readiness,
        current_preparation=current_preparation,
        latest=latest,
        superseded=tuple(o for o in observations if not latest or o.id != latest.id),
        yield_scope=latest.details.scope if latest else None,
        yield_result=latest.result if latest else None,
    )
