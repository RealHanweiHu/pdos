"""Only synthetic bytes and in-memory facts. Not a production storage adapter."""

import hashlib
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import RLock, local
from uuid import uuid4

from pdos_next.object_storage.types import ObjectRef
from pdos_next.original_lifecycle import (
    ActorKind,
    CurrentAuthorization,
    Disposition,
    EffectOutcome,
    EffectReceipt,
    LifecycleFailure,
    LifecycleFence,
    LifecycleScope,
    LifecycleService,
    OriginalState,
    ParseState,
    ReferenceState,
    RetentionPolicy,
    UploadState,
)


class FrozenClock:
    def __init__(self):
        self.value = datetime(2026, 10, 2, 12, tzinfo=UTC)

    def now(self):
        return self.value


class SyntheticStore:
    synthetic_marker = "original-lifecycle-test-only"

    def __init__(self, clock):
        self.clock = clock
        self.content = b"Harmless synthetic failed-upload original."
        identity = uuid4()
        checksum = hashlib.sha256(self.content).hexdigest()
        self.reference = ObjectRef(
            identity,
            1,
            checksum,
            len(self.content),
            "text/plain",
            f"originals/{identity.hex}/v1/{checksum}",
        )
        self.scope = LifecycleScope(uuid4(), uuid4())
        past = clock.now() - timedelta(days=14)
        self.original = OriginalState(
            self.reference,
            self.scope,
            1,
            "inventory:1",
            past,
            clock.now(),
            UploadState.FAILED,
            False,
            past,
            ParseState.NOT_REQUESTED,
            past + timedelta(days=7),
            False,
        )
        self.refs = ReferenceState(
            self.reference, self.scope, "references:1", clock.now(), 0, False
        )
        self.candidates = {}
        self.requests = {}
        self.intents = {}
        self.consumed = {}
        self.events = []
        self._lock = RLock()
        self._local = local()
        self.fail_stage = False
        self.bad_ack = False

    @contextmanager
    def command_transaction(self):
        # The caller owns this synthetic transaction; production port must use the
        # existing command transaction and a DB lock shared with reference writers.
        with self._lock:
            state = (
                self.original,
                self.refs,
                self.candidates.copy(),
                self.requests.copy(),
                self.intents.copy(),
                self.consumed.copy(),
                self.events.copy(),
            )
            self._local.active = True
            self._local.fences = {}
            try:
                yield
            except Exception:
                (
                    self.original,
                    self.refs,
                    self.candidates,
                    self.requests,
                    self.intents,
                    self.consumed,
                    self.events,
                ) = state
                raise
            finally:
                self._local.active = False
                self._local.fences = {}

    def _transaction(self):
        assert getattr(self._local, "active", False), "Caller transaction required"

    def _fenced(self, fence):
        self._transaction()
        assert self._local.fences.get(fence.token) == fence.original.revision
        if self.original.revision != fence.original.revision:
            raise LifecycleFailure("VERSION_CONFLICT", "Synthetic lifecycle fence changed")

    def read_current(self, reference):
        if reference != self.reference:
            raise LifecycleFailure("SOURCE_UNAVAILABLE", "No exact synthetic original")
        return replace(self.original, observed_at=self.clock.now())

    def lock_current(self, reference):
        self._transaction()
        fence = LifecycleFence(self.read_current(reference), uuid4())
        self._local.fences[fence.token] = fence.original.revision
        return fence

    def save_candidate(self, candidate):
        self._transaction()
        self.candidates[candidate.id] = candidate

    def get_candidate(self, candidate_id):
        return self.candidates[candidate_id]

    def find_request(self, scope, actor_id, key):
        return self.requests.get((scope, actor_id, key))

    def find_intent(self, scope, intent_digest):
        return next(
            (
                item
                for item in self.intents.values()
                if item.scope == scope and item.intent_digest == intent_digest
            ),
            None,
        )

    def get_intent(self, intent_id):
        return self.intents[intent_id]

    def remember_request(self, fence, binding):
        self._fenced(fence)
        key = (binding.scope, binding.actor_id, binding.key)
        existing = self.requests.get(key)
        if existing is not None and existing != binding:
            raise LifecycleFailure("IDEMPOTENCY_CONFLICT", "Synthetic alias conflict")
        self.requests[key] = binding

    def stage(self, fence, intent, original, request):
        self._fenced(fence)
        if intent.candidate_id in self.consumed:
            raise LifecycleFailure("PREVIEW_CONSUMED", "Synthetic preview already consumed")
        assert original.revision == fence.original.revision + 1
        assert original.pending_intent_id == intent.id
        self.remember_request(fence, request)
        self.original = original
        self.intents[intent.id] = intent
        self.consumed[intent.candidate_id] = intent.id
        self.events.append(("staged", intent.id))
        if self.fail_stage:
            raise RuntimeError("Synthetic Outbox write failure")
        return replace(intent, authorization_revision="bad-ack") if self.bad_ack else intent

    def change(self, fence, before, after, original):
        self._fenced(fence)
        if self.intents[before.id] != before:
            raise LifecycleFailure("VERSION_CONFLICT", "Synthetic intent changed")
        assert after.revision == before.revision + 1
        assert original.revision == fence.original.revision + 1
        self.original, self.intents[after.id] = original, after
        self.events.append((after.state.value, after.id))
        return after

    def add_reference(self):
        with self._lock:
            if self.original.pending_intent_id is not None or (
                self.original.disposition != Disposition.ACTIVE
            ):
                raise LifecycleFailure(
                    "REFERENCE_BLOCKED", "Pending/quarantined source cannot be consumed"
                )
            self.refs = replace(
                self.refs,
                reference_count=(self.refs.reference_count or 0) + 1,
                read_version=f"references:{uuid4()}",
                observed_at=self.clock.now(),
            )


class SyntheticGuard:
    def __init__(self, store):
        self.store = store

    def read_current(self, reference):
        self.store.read_current(reference)
        return replace(self.store.refs, observed_at=self.store.clock.now())

    def read_under_fence(self, fence):
        self.store._fenced(fence)
        return self.read_current(fence.original.reference)


class SyntheticAuthority:
    def __init__(self, store):
        self.store = store
        self.actor_id = uuid4()
        self.worker_id = uuid4()
        self.denied = False
        self.wrong_scope = False
        self.actor_override = None

    def authorize(self, context, reference, action, now, *, decision=None):
        if self.denied:
            raise LifecycleFailure("FORBIDDEN_SCOPE", "Synthetic current access revoked")
        kind = ActorKind(context)
        if self.actor_override is not None:
            kind = self.actor_override
        return CurrentAuthorization(
            reference,
            LifecycleScope(uuid4(), uuid4()) if self.wrong_scope else self.store.scope,
            self.worker_id if kind == ActorKind.SERVICE else self.actor_id,
            kind,
            action,
            "access:current",
            now + timedelta(minutes=1),
            decision.named_decider_id if decision is not None else self.actor_id,
            decision.id if decision is not None else None,
        )


class SyntheticPhysical:
    """In-memory reversible marker with exact harmless bytes; never writes a file."""

    def __init__(self, store):
        assert store.synthetic_marker == "original-lifecycle-test-only"
        self.store = store
        self.disposition = Disposition.ACTIVE
        self.permits = {}
        self.terminal_outcomes = {}
        self.original_locations = {}
        self.apply_calls = 0
        self.observe_calls = 0
        self.mode = "applied"
        self.service = None
        self.effect_hook = None

    def _receipt(self, permit, outcome):
        content = self.store.content
        assert len(content) == permit.reference.size_bytes
        assert hashlib.sha256(content).hexdigest() == permit.reference.content_sha256
        return EffectReceipt(
            permit.operation_id,
            permit.reference,
            permit.scope,
            permit.lease_token,
            outcome,
            self.disposition if outcome != EffectOutcome.UNKNOWN else None,
            outcome != EffectOutcome.UNKNOWN,
            self.store.clock.now(),
            "synthetic-transport:v1",
        )

    def apply_once(self, permit):
        existing = self.permits.get(permit.operation_id)
        if existing is not None:
            if existing != permit:
                raise LifecycleFailure(
                    "EFFECT_BINDING_MISMATCH", "Synthetic transport permit changed"
                )
            return self.observe(permit)
        with self.store.command_transaction():
            # Holds the same gate through effect. Protection writers cannot run
            # after validate_effect and before the synthetic physical marker.
            self.service.validate_effect("service", permit)
            if self.effect_hook is not None:
                self.effect_hook()
            self.permits[permit.operation_id] = permit
            self.original_locations[permit.operation_id] = self.disposition
            self.apply_calls += 1
            if self.mode != "not_applied":
                self.disposition = (
                    Disposition.QUARANTINED
                    if permit.action.value == "quarantine"
                    else Disposition.ACTIVE
                )
            outcome = (
                EffectOutcome.NOT_APPLIED if self.mode == "not_applied" else EffectOutcome.APPLIED
            )
            # Durable synthetic terminal journal is recorded before replying; an
            # unknown reply does not change the operation's real terminal outcome.
            self.terminal_outcomes[permit.operation_id] = outcome
            if self.mode == "unknown_after_applied":
                return self._receipt(permit, EffectOutcome.UNKNOWN)
            return self._receipt(permit, outcome)

    def observe(self, permit):
        self.observe_calls += 1
        if self.permits.get(permit.operation_id) != permit:
            return self._receipt(permit, EffectOutcome.UNKNOWN)
        outcome = self.terminal_outcomes.get(permit.operation_id)
        if outcome is None:
            return self._receipt(permit, EffectOutcome.UNKNOWN)
        expected = self.original_locations[permit.operation_id]
        if outcome == EffectOutcome.APPLIED:
            expected = (
                Disposition.QUARANTINED
                if permit.action.value == "quarantine"
                else Disposition.ACTIVE
            )
        if self.disposition != expected:
            return self._receipt(permit, EffectOutcome.UNKNOWN)
        return self._receipt(permit, outcome)


def fixture():
    clock = FrozenClock()
    store = SyntheticStore(clock)
    authority = SyntheticAuthority(store)
    policy = RetentionPolicy(
        "synthetic-policy:v1",
        timedelta(days=7),
        timedelta(days=30),
        timedelta(seconds=30),
    )
    service = LifecycleService(
        store=store,
        references=SyntheticGuard(store),
        authority=authority,
        policy=policy,
        clock=clock,
    )
    physical = SyntheticPhysical(store)
    physical.service = service
    return clock, store, authority, service, physical


def preview(store, service, *, action=None):
    with store.command_transaction():
        return service.preview("human", store.reference, **({"action": action} if action else {}))


def confirm(store, service, candidate, *, key="confirm:1", context="human"):
    with store.command_transaction():
        return service.confirm(context, candidate.id, candidate.digest, key)


def start(store, service, intent):
    with store.command_transaction():
        return service.begin_effect("service", intent.id)


def record(store, service, intent, receipt):
    with store.command_transaction():
        return service.record_effect("service", intent.id, receipt)
