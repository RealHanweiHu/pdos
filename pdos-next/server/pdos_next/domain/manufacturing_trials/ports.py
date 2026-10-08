"""All ports use the caller Session/UoW. No connections, commits or authority grants.

The host locks semantic intent -> Build -> lot -> Pilot -> resources in a common
order, rechecks cancellation/currentness before persistence, and rolls back T1
consumption + domain + receipt/audit/outbox + verification intent together.
"""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from pydantic import AwareDatetime, Field

from pdos_next.schemas.manufacturing_trials.contracts import (
    DTO,
    Gap,
    LotBasis,
    Observation,
    Parameter,
    PilotCreate,
    PilotRun,
    Ref,
    ResultRecord,
    ToolTrial,
    ToolTrialCreate,
    YieldScope,
)
from pdos_next.schemas.verification.contracts import RequestCreate, Scope, SourceRef


class Authority(DTO):
    scope: Scope
    actor_id: UUID
    actor_kind: Literal["human", "ai"]
    roles: tuple[str, ...]
    authorized: bool
    qualified: bool
    cancelled: bool
    now: AwareDatetime


class Invocation(DTO):
    command_id: UUID
    operation: Literal["npi.tooltrial.create", "npi.pilot.create", "npi.pilot.result.record"]
    subject_id: UUID
    expected_revision: int = Field(strict=True, ge=0)
    semantic_digest: str
    confirmation_token: str | None = None


class Preview(DTO):
    operation: str
    subject_id: UUID
    expected_revision: int = Field(strict=True, ge=0)
    digest: str
    read_set: tuple[Ref, ...]
    gaps: tuple[Gap, ...]
    summary: str
    write_tier: Literal["T1"] = "T1"


class Outcome(DTO):
    subject_id: UUID
    revision: int = Field(strict=True, ge=1)
    receipt_id: UUID
    replayed: bool = False


class Mutation(DTO):
    before_revision: int = Field(strict=True, ge=0)
    trial: ToolTrial | None = None
    pilot: PilotRun | None = None
    observation: Observation | None = None
    verification_intent: RequestCreate | None = None
    event: Literal["tooltrial.created", "pilot.created", "pilot.results_recorded"]


class LotFacts(DTO):
    scope: Scope
    basis: LotBasis
    observed_unit_count: int = Field(strict=True, ge=0)
    nature: Literal["real", "synthetic"]
    source: SourceRef


class PreparationFacts(DTO):
    """Server-owned resource/verification/supply assessment and critical fixed read set."""

    gaps: tuple[Gap, ...]
    read_set: tuple[Ref, ...]
    sources: tuple[SourceRef, ...]


class CommandPort(Protocol):
    def atomic(self) -> AbstractContextManager[object]:
        """Caller Session savepoint/UoW, rollback on error, NEVER commit outer transaction."""
        ...

    def context(self, operation: str, subject_id: UUID) -> Authority: ...
    def begin(self, invocation: Invocation) -> Authority | Outcome:
        """Lock durable semantic intent; conflicts across keys rejected, replay reauthorized."""
        ...

    def pilot(self, scope: Scope, pilot_id: UUID) -> PilotRun: ...
    def observation(self, scope: Scope, observation_id: UUID) -> Observation: ...
    def confirm(self, invocation: Invocation, preview: Preview, authority: Authority) -> None:
        """Common T1 consumes actor/scope/payload/read-set/expiry-bound proof once.

        Reject expiry, withdrawal, version drift or replaced proof. No private T1 engine.
        """
        ...

    def recheck(self, authority: Authority, preview: Preview) -> None:
        """Current permissions/AI qualification/cancellation/source+resource revocation."""
        ...

    def record(self, invocation: Invocation, mutation: Mutation) -> Outcome:
        """Insert immutable snapshots + CAS Pilot pointer + receipt/audit/outbox.

        insert-only new ids; unique active extension per scoped BuildLot; fixed cohort
        input/sample-set reservation; dedup observation source identity across keys.
        verification_intent is sent to its UNIQUE owner in this same transaction.
        Failure at ANY point raises and rolls back, never a partial successful receipt.
        """
        ...


class FactsPort(Protocol):
    def check_ref(self, scope: Scope, ref: Ref, purpose: str) -> None:
        """Server resolves object kind/version/scope/current ACL and applicability.

        baseline refers to actual named released baseline including SOP/control/risk,
        never a draft ProcessRevision; acceptance refs are authenticated human T2.
        """
        ...

    def source(self, scope: Scope, source: SourceRef, purpose: str) -> None: ...
    def verify_parameters(
        self, scope: Scope, parameters: tuple[Parameter, ...], purpose: str
    ) -> tuple[Parameter, ...]:
        """Bind exact parameter values/units to authorized original observations.

        Return server-normalized fixed facts, not existence/hash-only source checks.
        Null values remain unknown. No model-supplied numeric value is authoritative.
        """
        ...

    def lot(self, scope: Scope, basis: LotBasis) -> LotFacts:
        """Locked existing BuildLot + ActualConfiguration + ProcessRevision only."""
        ...

    def preparation(self, scope: Scope, details: PilotCreate | ToolTrialCreate) -> PreparationFacts:
        """Owner ports: resource_readiness qualifications/calibration/reservation,
        supply_cost actual material/occupancy, verification method/doc/sample gaps.
        Bind qualification/reservation and all critical owner revisions into read_set.
        No empty success fallback when a required owner is unconnected.
        """
        ...

    def verify_result(self, scope: Scope, pilot: PilotRun, result: ResultRecord) -> YieldScope:
        """Verify ORIGINAL exact values/units/time/nature and count scope, not only hash.

        Return server-fixed scope incl. criterion/window/minimum sample threshold.
        Bind observed cohort to actual lot, enforce unique SampleUnit membership and
        disposition authority, explicit subset for sampled counts <= lot quantity.
        Same fixed units/denominator across revisions. AI cannot supply observation
        source or synthetic flag as reality. No LLM/remote waits inside transaction.
        """
        ...


@dataclass(frozen=True)
class Ports:
    commands: CommandPort | None = None
    facts: FactsPort | None = None
