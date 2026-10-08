"""Consumption contracts. All writes participate in the caller's command transaction."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from pdos_next.object_storage.types import ObjectRef

from .types import (
    CurrentAuthorization,
    EffectPermit,
    EffectReceipt,
    LifecycleAction,
    LifecycleFence,
    LifecycleIntent,
    LifecycleScope,
    OriginalState,
    OrphanCandidate,
    ReferenceState,
    RequestBinding,
)


class LifecycleAuthorityPort(Protocol):
    def authorize(
        self,
        server_context: object,
        reference: ObjectRef,
        action: LifecycleAction,
        now: datetime,
        *,
        decision: LifecycleIntent | None = None,
    ) -> CurrentAuthorization:
        """Resolve current identity/scope/ACL from server context, not request claims.

        Physical effects need trusted service authority and current permission for
        the stored named decision. Reconciliation needs current observation permission.
        Restore rechecks current source ACL and does not grant audience/scan permission.
        """
        ...


class ReferenceGuardPort(Protocol):
    def read_current(self, reference: ObjectRef) -> ReferenceState:
        """Complete authoritative refs/history; missing/incomplete coverage => None facts."""
        ...

    def read_under_fence(self, fence: LifecycleFence) -> ReferenceState:
        """Use the same object fence as every reference/history/parse/upload writer."""
        ...


class LifecycleStorePort(Protocol):
    def read_current(self, reference: ObjectRef) -> OriginalState:
        """Missing upload journal or scope is unavailable, never an inferred orphan."""
        ...

    def lock_current(self, reference: ObjectRef) -> LifecycleFence:
        """Lock in the enclosing command transaction; never open/commit a transaction.

        New refs, history, hold, retention, source ACL/withdrawal, upload, inventory
        and parse transitions must acquire this same lock and advance the object
        protection/lifecycle revision, even if values are later changed back;
        pending intents and quarantine prohibit new consuming refs/read/parse work.
        """
        ...

    def save_candidate(self, candidate: OrphanCandidate) -> None: ...

    def get_candidate(self, candidate_id: UUID) -> OrphanCandidate: ...

    def find_request(
        self, scope: LifecycleScope, actor_id: UUID, key: str
    ) -> RequestBinding | None: ...

    def find_intent(self, scope: LifecycleScope, intent_digest: str) -> LifecycleIntent | None: ...

    def get_intent(self, intent_id: UUID) -> LifecycleIntent: ...

    def remember_request(self, fence: LifecycleFence, binding: RequestBinding) -> None: ...

    def stage(
        self,
        fence: LifecycleFence,
        intent: LifecycleIntent,
        original: OriginalState,
        request: RequestBinding,
    ) -> LifecycleIntent:
        """CAS lifecycle version+preview consumption+two idempotency keys.

        Persist original pending state, intent, request, preview consumption,
        ActionReceipt/Audit/Outbox atomically. Reject duplicate conflicts. No commit.
        """
        ...

    def change(
        self,
        fence: LifecycleFence,
        before: LifecycleIntent,
        after: LifecycleIntent,
        original: OriginalState,
    ) -> LifecycleIntent:
        """CAS object+intent versions; append receipt/audit/Outbox in same transaction."""
        ...


class ReversibleObjectLifecyclePort(Protocol):
    def apply_once(self, permit: EffectPermit) -> EffectReceipt:
        """Retain exact bytes; durable dedup by operation/token, reject expired permit.

        Called only after permit transaction commits. Reacquire the shared object
        gate and LifecycleService.validate_effect in a new caller-owned transaction;
        atomically compare current lifecycle/inventory/reference/policy/access epochs.
        Keep the gate held through bounded I/O and fence storage markers by token;
        do not release it between protection validation and effect. All protection
        writers must use that gate. No deletion or overwrite.
        A crash/timeout cannot be treated as not applied. No implicit transport retry.
        """
        ...

    def observe(self, permit: EffectPermit) -> EffectReceipt:
        """Read-only reconcile exact original/markers and durable terminal journal.

        NOT_APPLIED requires positive durable proof that this exact operation never
        applied, plus verified retained exact bytes. Absence/current location alone
        is insufficient: an APPLIED operation later restored remains historically
        APPLIED. If current markers/location cannot corroborate that journal, return
        UNKNOWN/conflict rather than retroactively asserting NOT_APPLIED.
        """
        ...


class ClockPort(Protocol):
    def now(self) -> datetime: ...
