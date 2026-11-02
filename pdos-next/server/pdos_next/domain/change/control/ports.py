"""Caller-Session ports. All checks, locks and writes share the host transaction.

Ports never commit/start transactions or wait for ERP/MES/LLM network calls.
Missing adapters are explicit INTEGRATION_REQUIRED, never empty successful facts.
"""

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from pydantic import AwareDatetime, Field

from pdos_next.schemas.change_control.contracts import (
    ChangeOrder,
    ChangeRequest,
    Discipline,
    EffectivityFact,
    GraphSnapshot,
    ImplementationFact,
    PlanItem,
    Ref,
    VerificationFact,
)
from pdos_next.schemas.verification.contracts import DTO, Key, Scope, SourceRef, Text


class Authority(DTO):
    scope: Scope
    actor_id: UUID
    requester_id: UUID
    actor_kind: Literal["human", "ai"]
    audience: tuple[Key, ...] = Field(min_length=1)
    roles: tuple[Key, ...]
    authorized: bool
    qualified: bool
    cancelled: bool
    now: AwareDatetime


class Invocation(DTO):
    command_id: UUID
    operation: Key
    subject_id: UUID
    expected_revision: int = Field(ge=0)
    semantic_digest: Key
    confirmation_token: str | None = None
    decision_id: UUID | None = None


class Currentness(DTO):
    current: bool
    reasons: tuple[Text, ...] = ()


class Policy(DTO):
    source: SourceRef
    required_disciplines: tuple[Discipline, ...] = ("engineering", "manufacturing")


class Preview(DTO):
    operation: Key
    subject_id: UUID
    expected_revision: int
    payload_digest: Key
    read_digest: Key
    digest: Key
    effect: Text
    next_state: str
    unknown: tuple[Text, ...] = ()


class Outcome(DTO):
    subject_id: UUID
    revision: int
    status: str
    replayed: bool = False


class Mutation(DTO):
    change: ChangeRequest
    expected_revision: int
    insert: bool
    event_name: Key | None
    preview_digest: Key
    new_fact_ids: tuple[UUID, ...] = ()


class CommandPort(Protocol):
    def context(self, uow: object, operation: str, subject_id: UUID) -> Authority: ...
    def begin(self, uow: object, invocation: Invocation) -> Authority:
        """Bind authenticated/run scope; lock command key/semantic intent/subject.

        Collision same key/different semantic payload is an error, not replay.
        Same semantic intent across request keys has one persisted effect.
        """
        ...

    def replay(self, uow: object, invocation: Invocation, authority: Authority) -> Outcome | None:
        """Exact historical receipt, reauthorize original read-set/audience/ACL.

        Replays never consume proofs again. Historical outcomes may be returned
        after source drift, with reader reporting current recheck separately.
        """
        ...

    def request(self, uow: object, scope: Scope, request_id: UUID) -> ChangeRequest: ...
    def confirm(
        self, uow: object, invocation: Invocation, preview: Preview, authority: Authority
    ) -> None:
        """COMMON T1 one-use/T2 named proof, matching actor, scope, cancel epoch,
        payload, full read set, policy, target revision, preview digest, expiry.
        Must atomically consume in SAME transaction as record; never mint here.
        """
        ...

    def record(self, uow: object, invocation: Invocation, mutation: Mutation) -> Outcome:
        """CAS/insert-only aggregate, immutable histories/assessments/orders/facts.

        Unique semantic intent + scoped imported fact IDs + output ownership.
        Lock/recheck the complete prepared reference/source/policy read set,
        audience, cancellation/qualification and proof expiry immediately before
        staging; source races must conflict, not consume an obsolete preview.
        Record facts, one ActionReceipt, Audit, Outbox and confirmation consumption
        atomically. Exception rolls them ALL back in caller's transaction.
        """
        ...


class FactPort(Protocol):
    def audience(
        self,
        uow: object,
        authority: Authority,
        audience: tuple[str, ...],
        refs: tuple[Ref, ...],
        sources: tuple[SourceRef, ...],
    ) -> None:
        """Authorize source-to-target audience use, not just actor read access.
        Actor access to two customer sources never grants shared output audience.
        Unknown use authorization rejects; never silently widens target audience.
        """
        ...

    def ref(self, uow: object, authority: Authority, ref: Ref) -> Ref:
        """ACL/current audience/exact scope/version/item checked; immutable archive
        allowed for history. Never replace a fixed reference with latest.
        Issue/CAPA/TestRun are read-only; no new Issue/CAPA or original rewrite.
        """
        ...

    def source(self, uow: object, authority: Authority, source: SourceRef) -> Currentness:
        """Check ACL/audience and exact archived original; expiry/correction/
        withdrawal/configuration drift returns false+reasons, denial raises.
        """
        ...

    def currentness(self, uow: object, authority: Authority, ref: Ref) -> Currentness: ...
    def graph(self, uow: object, authority: Authority, snapshot: Ref) -> GraphSnapshot:
        """Fixed server graph (id/revision), authorized sources/edge provenance,
        coverage manifests, server nature; no model-proposed edges or flags.
        """
        ...

    def selection(self, uow: object, authority: Authority, item: PlanItem) -> None:
        """Resolve each object/batch/serial token to exact scope/selected object,
        conditions and controlled intent applicability. No registration grants.
        """
        ...

    def implementation(
        self, uow: object, authority: Authority, fact_id: UUID, order: ChangeOrder, item: PlanItem
    ) -> ImplementationFact:
        """Read owner-verified persisted execution, exact intent/item/scope/source.
        reconciles_id resolves the SAME unknown attempt with fixed occurrence/
        executor/intent, never a new send; immutable original unknown retained.
        Output new configurations/Build/Run are created only by their owner; no
        planned reference or transport success proves actual execution.
        """
        ...

    def effectivity(
        self, uow: object, authority: Authority, fact_id: UUID, order: ChangeOrder, item: PlanItem
    ) -> EffectivityFact:
        """Actual owner/external receipt; stage/result/units/conditions/versions/
        external ID/source/nature authenticated. Unknown requires reconciliation,
        never a blind resend. reconciles_id authenticated as the same unknown
        external receipt/intent occurrence, complete previously unknown units.
        Sent/accepted must not be mapped to effective.
        """
        ...

    def verification(
        self, uow: object, authority: Authority, fact_id: UUID, order: ChangeOrder
    ) -> VerificationFact:
        """Named new Run/applicability/observation outcome covering approved plan
        and actual outputs, all measurement executors, same source nature.
        """
        ...


class PolicyPort(Protocol):
    def assess(self, uow: object, authority: Authority, request: ChangeRequest) -> Policy:
        """Current professional roles/approval/independence policy version."""
        ...


@dataclass(frozen=True)
class Ports:
    commands: CommandPort | None = None
    facts: FactPort | None = None
    policies: PolicyPort | None = None
