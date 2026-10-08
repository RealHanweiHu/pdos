"""All adapters must share the host command transaction. No commits/connections here."""

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pdos_next.schemas.quality_issues.contracts import FailureRef, Issue, Ref, Risk
from pdos_next.schemas.verification.contracts import DTO, Scope, SourceRef, TestRun


class Authority(DTO):
    scope: Scope
    actor_id: UUID
    actor_kind: Literal["human", "ai"]
    roles: tuple[str, ...]
    audience: tuple[str, ...]
    authorized: bool
    qualified: bool
    cancelled: bool
    now: datetime


class Invocation(DTO):
    command_id: UUID
    operation: str
    subject_id: UUID
    expected_revision: int
    semantic_digest: str
    confirmation_token: str | None = None
    decision_id: UUID | None = None


class VerifiedRun(DTO):
    run: TestRun
    nature: Literal["real", "synthetic"]


class Currentness(DTO):
    current: bool
    reasons: tuple[str, ...] = ()
    # Changes to the source revision/configuration require recheck; unrelated Run
    # revisions do not. Host compares the precise FailureRef, not entire run revision.


class QualityPolicy(DTO):
    ref: Ref
    risk: Risk
    independent_verification: bool


class VerificationEvidence(DTO):
    id: UUID
    sources: tuple[SourceRef, ...]
    failure_ids: tuple[str, ...]
    run_ids: tuple[UUID, ...]
    verifier_id: UUID
    executor_ids: tuple[UUID, ...]
    result: Literal["pass", "fail", "indeterminate"]
    requirement_digest: str
    observed_from: datetime
    observed_until: datetime
    applicable: bool
    current: bool
    nature: Literal["real", "synthetic"]
    # From named reviewed fixed new TestRun/observation records, not a caller flag.


class Preview(DTO):
    operation: str
    subject_id: UUID
    expected_revision: int
    payload_digest: str
    digest: str
    allowed: bool = True
    failures: tuple[FailureRef, ...]
    issues: tuple[Ref, ...]
    policy: QualityPolicy | None
    differences: tuple[str, ...]
    effect: str


class Outcome(DTO):
    subject_id: UUID
    revision: int
    status: str
    replayed: bool = False


class Delivery(DTO):
    event_id: UUID
    failure_identity: str
    issue_id: UUID
    observed: FailureRef


class Mutation(DTO):
    changes: tuple[Issue, ...]
    before: tuple[Ref, ...] = ()
    insert_ids: tuple[UUID, ...] = ()
    deliveries: tuple[Delivery, ...] = ()
    event_name: str | None
    preview_digest: str


class CommandPort(Protocol):
    def context(self, operation: str, subject_id: UUID) -> Authority: ...
    def begin(self, invocation: Invocation) -> Authority:
        """Lock intent/key. Replays still enter domain reauthorization/currentness checks.

        Host handles command key collisions; do not early-return an unchecked Outcome.
        For create the business uniqueness is scope+FailureRef.identity, not payload
        digest (which includes delivery id/title). Lock this identity before lookup.
        """
        ...

    def replay(self, invocation: Invocation, authority: Authority) -> Outcome | None:
        """Lookup exact persisted semantic intent across keys (not eternal equal payload).

        Reauthorize original read set/audience, cancellation and current source ACL.
        Compare same key payload before returning. Do not consume proof again. Caller
        additionally checks current Issue accessibility/currentness before returning.
        """
        ...

    def issue(self, scope: Scope, issue_id: UUID) -> Issue: ...
    def by_failure(self, scope: Scope, identity: str) -> Issue | None:
        """Lock stable failure identity, resolve merged aliases to canonical Issue."""
        ...

    def confirm(self, invocation: Invocation, preview: Preview, authority: Authority) -> None:
        """Host common proof, binding full read digest/policy/payload/actor/expiry; T2 named."""
        ...

    def record(self, invocation: Invocation, mutation: Mutation) -> Outcome:
        """CAS all issues; insert-only ids; unique scope+failure identity
        and (event_id,failure_identity) mapping.

        Retain original merge rows/all history; one Run event may map multiple failures.
        Facts, proof consumption, delivery Inbox, one receipt, audit and Outbox persist
        together in caller transaction; exception rolls EVERYTHING back. No commit.
        Validate referenced executors/assignees in current scope (no nomination grants).
        Stable intent replay returns original outcome without duplicate domain history.
        """
        ...


class RunPort(Protocol):
    def delivery(self, scope: Scope, event_id: UUID, failure: FailureRef) -> None:
        """Validate persisted source event/Inbox belongs to this Run and exact failure.

        The event may contain multiple failed measurements. Verify its fixed revision
        has this measurement/criterion; unrelated later Run changes do not invalidate
        delivery. No arbitrary event UUID supplied by a model becomes a source fact.
        """
        ...

    def original(self, scope: Scope, run: Ref) -> VerifiedRun:
        """ACL-checked archived exact Run revision for reading original measurements.
        Never substitute current Run/source/configuration. No new TestRun ownership.
        """
        ...

    def fixed(self, scope: Scope, run_id: UUID) -> VerifiedRun:
        """Actual locked TestRun, ACL/scope; verify exact original measurement values,
        methods, criteria, sample/configuration; synthetic nature is server-bound.
        Reject planned Build and missing resources/verification interfaces explicitly.
        """
        ...

    def currentness(self, scope: Scope, failure: FailureRef) -> Currentness:
        """Assess exact source/criterion/method/sample/configuration and corrections.
        Withdrawal/drift returns reasons; unauthorized reads raise, never leak history.
        """
        ...


class PolicyPort(Protocol):
    def assess(self, authority: Authority, failures: tuple[FailureRef, ...]) -> QualityPolicy: ...
    def verification(
        self, authority: Authority, evidence_id: UUID, issue: Issue
    ) -> VerificationEvidence:
        """Revalidate named evidence, ACL, new Run/config applicability/observation window.
        Include all test/measure executors in executor_ids, server-bound verifier.
        """
        ...


class EvidencePort(Protocol):
    def currentness(self, scope: Scope, source: SourceRef, purpose: str) -> Currentness:
        """Withdrawal/drift returns reasons; unauthorized access raises without leaking."""
        ...

    def check(self, scope: Scope, source: SourceRef, purpose: str) -> None: ...


class Ports:
    def __init__(
        self,
        *,
        commands: CommandPort | None = None,
        runs: RunPort | None = None,
        policies: PolicyPort | None = None,
        evidence: EvidencePort | None = None,
    ):
        self.commands, self.runs, self.policies, self.evidence = commands, runs, policies, evidence
