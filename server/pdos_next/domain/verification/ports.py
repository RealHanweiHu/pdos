"""Host adapters bind all ports to the caller's one command transaction.

No adapter implementation here opens a connection, commits, or grants authority.
The host must lock target/source/sample rows, recheck ACL/qualification/cancellation,
consume T1/T2 proofs, and save domain+receipt+audit+outbox atomically.
"""

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pdos_next.schemas.verification.contracts import (
    DTO,
    BuildRef,
    Coverage,
    EventTime,
    ExecutionConditions,
    Gap,
    Measurement,
    SampleRef,
    Scope,
    SourceRef,
    TestRun,
    TimeFact,
    VerificationRequest,
)


class Authority(DTO):
    """Server assessment for this operation; never construct from model/payload.

    qualified means the applicable current capability/professional qualification
    checks passed (including real golden-case for AI). No certificate is granted.
    """

    scope: Scope
    actor_id: UUID
    actor_kind: Literal["human", "ai"]
    roles: tuple[str, ...]
    authorized: bool
    qualified: bool
    cancelled: bool
    now: datetime


class BuildContext(DTO):
    ref: BuildRef
    status: str


class SampleAvailability(DTO):
    sample: SampleRef
    available: bool
    applicable: bool
    source: SourceRef
    ready_at: EventTime | None = None
    reason: str | None = None


class Preview(DTO):
    operation: str
    subject_id: UUID
    expected_revision: int
    digest: str
    allowed: bool
    coverage: tuple[Coverage, ...] = ()
    gaps: tuple[Gap, ...] = ()
    effect: str


class Invocation(DTO):
    command_id: UUID
    operation: str
    subject_id: UUID
    expected_revision: int
    semantic_digest: str
    confirmation_token: str | None = None
    decision_id: UUID | None = None


class DomainEvent(DTO):
    name: str
    subject_id: UUID
    revision: int
    scope: Scope
    at: TimeFact
    coverage: tuple[Coverage, ...] = ()


class Mutation(DTO):
    operation: str
    before_revision: int
    request_before_revision: int
    run_before_revision: int | None = None
    request: VerificationRequest | None = None
    run: TestRun | None = None
    events: tuple[DomainEvent, ...]


class Outcome(DTO):
    subject_id: UUID
    revision: int
    status: str
    result: str | None = None
    replayed: bool = False


class BuildContextPort(Protocol):
    def get(self, scope: Scope, build_id: UUID) -> BuildContext: ...


class EvidencePort(Protocol):
    def check(self, scope: Scope, source: SourceRef, purpose: str) -> None:
        """Raise for drift, withdrawal, missing original, ACL/audience or scope mismatch."""
        ...

    def verify_measurement(self, scope: Scope, measurement: Measurement, run: TestRun) -> None:
        """Bind values to actual source content or authorized original observation.

        Checking source existence/hash/ACL alone does not prove that a proposed raw
        value/unit/condition/time came from its claimed position. Use deterministic
        source extraction or the server-bound human/instrument observation record;
        reject invented values/locator substitutions. Missing fields remain missing.
        No LLM or remote wait in the caller's transaction.
        """
        ...


class SampleAvailabilityPort(Protocol):
    def inspect(self, scope: Scope, sample: SampleRef, purpose: str) -> SampleAvailability:
        """Return locked actual SampleUnit/ActualConfiguration; never from planned quantity."""
        ...

    def reserve(
        self,
        scope: Scope,
        run_id: UUID,
        samples: tuple[SampleRef, ...],
        coverage: tuple[Coverage, ...],
        destructive: tuple[Coverage, ...],
        execution: ExecutionConditions,
    ) -> None:
        """Atomic reservation/consumption and calibration/person/fixture/resource recheck.

        Consume destructive units exactly once. Reject competing runs or more than one
        destructive assignment for a unit. Do not commit; rollback with Mutation failure.
        """
        ...

    def recheck_running(
        self,
        scope: Scope,
        run: TestRun,
    ) -> None:
        """Verify fixed actual configuration and this run's reservation/consumption.

        A consumed sample is usable for its owning run's results only, not for new runs.
        """
        ...


class CommandPort(Protocol):
    def context(self, operation: str, subject_id: UUID) -> Authority:
        """Server-bound current identity/scope; read preview does not consume an intent."""
        ...

    def begin(self, invocation: Invocation) -> Authority | Outcome:
        """Lock stable business intent, reject key/payload mismatch; reauthorize replay.

        Stable intent must survive command_id/key changes. A stored Outcome is returned
        only for the same persisted semantic intent and currently authorized audience.
        """
        ...

    def request(self, scope: Scope, request_id: UUID) -> VerificationRequest: ...

    def run(self, scope: Scope, run_id: UUID) -> TestRun: ...

    def runs(self, scope: Scope, request_id: UUID) -> tuple[TestRun, ...]:
        """Read/lock all runs for this request for precise aggregate milestones."""
        ...

    def confirm(self, invocation: Invocation, preview: Preview, authority: Authority) -> None:
        """Consume real T1 proof exactly once, or matching human T2 named decision.

        Proof binds semantic payload, scope, fixed read set, preview digest, actor,
        operation, version and expiry. Reject AI T2 and proof edits/expiry/revocation.
        """
        ...

    def record(self, invocation: Invocation, mutation: Mutation) -> Outcome:
        """Persist in caller transaction including receipt/audit/outbox; never commit.

        before=0 is insert-only, never upsert an existing ID. CAS request and run
        using their explicit before fields; a read-only unchanged request stays at
        its old version. Acquire parent request lock before run/sample locks in a
        common order, including when starting/importing two different sibling runs.
        Resolve every next_owner_id within this tenant/project's permitted assignee
        scope; a nominated ID never grants that principal authority or membership.
        """
        ...


class Ports:
    def __init__(
        self,
        *,
        commands: CommandPort | None = None,
        builds: BuildContextPort | None = None,
        evidence: EvidencePort | None = None,
        samples: SampleAvailabilityPort | None = None,
    ):
        self.commands = commands
        self.builds = builds
        self.evidence = evidence
        self.samples = samples
