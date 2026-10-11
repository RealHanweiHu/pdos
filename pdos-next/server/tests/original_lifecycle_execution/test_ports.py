"""No-DB SQL adapter contracts. PG atomicity/RLS/fences are mainline checks."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next import models
from pdos_next.domain.original_lifecycle_execution import service as commands
from pdos_next.domain.original_lifecycle_execution.codec import decode_intent, encode_state
from pdos_next.domain.original_lifecycle_execution.runtime import BoundFacts, LifecycleRuntime
from pdos_next.domain.original_lifecycle_execution.schemas import (
    LifecycleCommandPayload,
    LifecycleProtectionPayload,
)
from pdos_next.domain.original_lifecycle_execution.store import (
    SqlLifecycleAuthority,
    SqlLifecycleStore,
)
from pdos_next.error_catalog import REASONS
from pdos_next.errors import DomainError
from pdos_next.original_lifecycle.service import LifecycleService
from pdos_next.original_lifecycle.types import (
    ActorKind,
    DecisionReason,
    IntentState,
    LifecycleAction,
    LifecycleFailure,
)
from pdos_next.service import Context
from tests.original_lifecycle.helpers import fixture

pytestmark = pytest.mark.usefixtures("pure_guard")


class FakeSession:
    """Small query sink; never creates an engine, DB connection or transaction."""

    def __init__(self, runtime, clock):
        self.bind = SimpleNamespace(lifecycle_runtime=runtime)
        self.clock = clock
        self.info = {}
        self.transaction = object()
        self.rows = {}
        self.statements = []
        self.flushes = 0

    def get_transaction(self):
        return self.transaction

    def get_bind(self):
        return self.bind

    def add(self, row):
        if row.id is None:
            row.id = uuid4()
        if row.created_at is None:
            row.created_at = self.clock.now()
        self.rows.setdefault(type(row), []).append(row)

    def flush(self):
        self.flushes += 1

    def scalar(self, query):
        self.statements.append(query)
        entity = query.column_descriptions[0]["entity"]
        params = query.compile().params
        for row in self.rows.get(entity, []):
            matching = True
            for key, value in params.items():
                field = key.rsplit("_", 1)[0]
                if hasattr(row, field) and field != "document" and getattr(row, field) != value:
                    matching = False
            if "candidate_id" in params.values():
                matching = matching and row.document["value"]["candidate_id"] == params["param_1"]
            if matching:
                return row
        return None


class FakeReferenceGuard:
    def __init__(self, facts, clock):
        self.facts, self.clock, self.store = facts, clock, None

    def read_current(self, reference):
        assert reference == self.facts.reference
        return replace(self.facts.refs, observed_at=self.clock.now())

    def read_under_fence(self, fence):
        self.store._fenced(fence)
        return self.read_current(fence.original.reference)


def sql_fixture():
    clock, facts, authority, original_service, _ = fixture()
    facts.category_id = uuid4()
    ctx = Context(
        facts.scope.tenant_id, authority.actor_id, authority.actor_id, category_id=facts.category_id
    )
    holder = {"facts": facts.original, "owner": ctx.actor_id}

    def read_facts(s, context, pid, ref, previous):
        original = replace(holder["facts"], observed_at=clock.now())
        if previous is not None:
            original = replace(
                original,
                revision=previous.revision,
                disposition=previous.disposition,
                quarantined_at=previous.quarantined_at,
                pending_intent_id=previous.pending_intent_id,
            )
        return BoundFacts(holder["owner"], original)

    guard = FakeReferenceGuard(facts, clock)
    runtime = LifecycleRuntime(
        original_service.policy,
        lambda *args: facts.reference,
        read_facts,
        lambda *args: guard,
        clock=clock,
    )
    session = FakeSession(runtime, clock)
    session.add(
        models.Product(
            id=facts.scope.product_id,
            tenant_id=ctx.tenant_id,
            owner_id=ctx.actor_id,
            category_id=ctx.category_id,
            name="synthetic",
            purpose="pure",
            revision=1,
        )
    )
    session.add(
        models.Principal(
            id=ctx.actor_id,
            tenant_id=ctx.tenant_id,
            name="synthetic human",
            kind="human",
            active=True,
            access_epoch=1,
        )
    )
    session.add(
        models.Grant(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            category_id=ctx.category_id,
            principal_id=ctx.actor_id,
            can_write=True,
            expires_at=clock.now() + timedelta(hours=1),
            access_epoch=1,
        )
    )
    store = SqlLifecycleStore(session, ctx, facts.scope.product_id, runtime, emit_transition=False)
    guard.store = store
    service = LifecycleService(
        store=store,
        references=guard,
        authority=SqlLifecycleAuthority(store),
        policy=runtime.policy,
        clock=clock,
    )
    return clock, facts, ctx, holder, session, store, service


def test_missing_runtime_fails_closed():
    s = SimpleNamespace(get_bind=lambda: SimpleNamespace())
    with pytest.raises(DomainError) as error:
        commands.runtime_for(s, Context(uuid4(), uuid4(), uuid4()), uuid4())
    assert error.value.code == REASONS["LIFECYCLE_UNAVAILABLE"]
    assert error.value.reason == "LIFECYCLE_UNAVAILABLE"


def test_only_observation_time_changes_do_not_invalidate_fixed_facts():
    clock, facts, _, _, session, store, _ = sql_fixture()
    first = store.read_current(facts.reference)
    before = session.flushes
    clock.value += timedelta(seconds=1)
    second = store.read_current(facts.reference)
    assert first.revision == second.revision == 1
    assert second.observed_at > first.observed_at
    assert session.flushes == before


def test_authoritative_inventory_epoch_change_advances_persisted_revision_once():
    _, facts, _, holder, session, store, _ = sql_fixture()
    store.read_current(facts.reference)
    holder["facts"] = replace(holder["facts"], inventory_revision="inventory:2")
    current = store.read_current(facts.reference)
    assert current.revision == 2
    assert store.object_row(facts.reference.id).state == encode_state(current)
    assert store.read_current(facts.reference).revision == 2
    assert len(session.rows[models.LifecycleObject]) == 1


def test_authoritative_facts_cannot_fabricate_owner_or_restore_old_location():
    _, facts, _, holder, _, store, _ = sql_fixture()
    store.read_current(facts.reference)
    holder["owner"] = uuid4()
    with pytest.raises(LifecycleFailure) as error:
        store.read_current(facts.reference)
    assert error.value.code == "FORBIDDEN_SCOPE"
    holder["owner"] = store.ctx.actor_id
    holder["facts"] = replace(
        holder["facts"], created_at=holder["facts"].created_at + timedelta(seconds=1)
    )
    with pytest.raises(LifecycleFailure) as error:
        store.read_current(facts.reference)
    assert error.value.code == "FACTS_BINDING_MISMATCH"


def test_sql_staging_and_original_service_two_level_dedup():
    _, facts, ctx, _, session, store, service = sql_fixture()
    candidate = service.preview(ctx, facts.reference)
    store.request_reason = "Synthetic named orphan review"
    intent = service.confirm(ctx, candidate.id, candidate.digest, "stable:1")
    assert intent.state == IntentState.PENDING
    assert store.read_current(facts.reference).pending_intent_id == intent.id
    assert service.confirm(ctx, candidate.id, candidate.digest, "stable:1") == intent
    assert service.confirm(ctx, candidate.id, candidate.digest, "alias:2") == intent
    assert len(session.rows[models.LifecycleIntentRecord]) == 1
    assert len(session.rows[models.LifecycleRequest]) == 2
    assert store.intent_row(intent.id).reason == "Synthetic named orphan review"
    assert all(
        query._for_update_arg is not None
        for query in session.statements
        if query.column_descriptions[0]["entity"] == models.Product
    )


def test_current_acl_checked_before_stored_success_replay_and_aba_changes_revision():
    clock, facts, ctx, _, session, store, service = sql_fixture()
    candidate = service.preview(ctx, facts.reference)
    store.request_reason = "named"
    intent = service.confirm(ctx, candidate.id, candidate.digest, "stable")
    authority = service.authority
    before = authority.authorize(ctx, facts.reference, LifecycleAction.PREVIEW, clock.now())
    grant = session.rows[models.Grant][0]
    grant.can_write = False
    grant.access_epoch += 1
    with pytest.raises(LifecycleFailure) as error:
        service.confirm(ctx, candidate.id, candidate.digest, "stable")
    assert error.value.code == "NAMED_CONFIRMATION_REQUIRED"
    grant.can_write = True
    grant.access_epoch += 1
    after = authority.authorize(ctx, facts.reference, LifecycleAction.PREVIEW, clock.now())
    assert before.access_revision != after.access_revision
    assert service.confirm(ctx, candidate.id, candidate.digest, "stable") == intent


@pytest.mark.parametrize("kind,delegated", [("agent", False), ("human", True)])
def test_agent_and_delegated_human_cannot_obtain_named_authority(kind, delegated):
    clock, facts, ctx, _, session, store, service = sql_fixture()
    store.read_current(facts.reference)
    session.rows[models.Principal][0].kind = kind
    if delegated:
        store.ctx = replace(ctx, actor_id=uuid4())
    with pytest.raises(LifecycleFailure):
        service.authority.authorize(
            store.ctx, facts.reference, LifecycleAction.QUARANTINE, clock.now()
        )


def test_unknown_registration_and_reference_coverage_are_not_zero():
    _, facts, ctx, holder, _, _, service = sql_fixture()
    holder["facts"] = replace(holder["facts"], registered=None)
    facts.refs = replace(facts.refs, reference_count=None, formal_history=None)
    candidate = service.preview(ctx, facts.reference)
    assert not candidate.decision.eligible
    assert DecisionReason.REGISTRATION_UNKNOWN in candidate.decision.reasons
    assert DecisionReason.REFERENCE_UNKNOWN in candidate.decision.reasons


def test_cancel_keeps_reason_and_never_issues_a_physical_permit():
    _, facts, ctx, _, _, store, service = sql_fixture()
    candidate = service.preview(ctx, facts.reference)
    store.request_reason = "Original named reason"
    intent = service.confirm(ctx, candidate.id, candidate.digest, "confirm")
    cancelled = service.cancel_pending(ctx, intent.id)
    assert cancelled.state == IntentState.CANCELLED and cancelled.permit is None
    assert store.read_current(facts.reference).pending_intent_id is None
    assert store.intent_row(intent.id).reason == "Original named reason"
    assert decode_intent(store.intent_row(intent.id).document) == cancelled


def test_worker_audit_hook_is_required_before_mutating_intent():
    _, facts, ctx, _, _, store, service = sql_fixture()
    candidate = service.preview(ctx, facts.reference)
    store.request_reason = "named"
    intent = service.confirm(ctx, candidate.id, candidate.digest, "confirm")
    store.emit_transition = True
    with pytest.raises(LifecycleFailure) as error:
        service.cancel_pending(ctx, intent.id)
    assert error.value.code == "LIFECYCLE_AUDIT_UNAVAILABLE"
    assert store.get_intent(intent.id) == intent


def test_public_intent_projection_omits_storage_key_and_worker_lease():
    _, facts, ctx, _, _, store, service = sql_fixture()
    candidate = service.preview(ctx, facts.reference)
    store.request_reason = "named"
    intent = service.confirm(ctx, candidate.id, candidate.digest, "confirm")
    public = commands.intent_view(store.intent_row(intent.id))
    assert public["state"] == "pending"
    assert "server_storage_key" not in repr(public)
    assert "lease_token" not in repr(public)
    assert "scan_status" not in repr(public)
    assert (
        service.authority.authorize(
            ctx, facts.reference, LifecycleAction.PREVIEW, service.clock.now()
        ).actor_kind
        == ActorKind.HUMAN
    )


def command_for(facts, operation, revision=1):
    return SimpleNamespace(
        operation=operation,
        category_id=facts.category_id,
        product_id=facts.scope.product_id,
        expected_revision=revision,
        source_read_set=(),
        idempotency_key="common-confirmation:1",
    )


def test_t1_review_uses_fixed_candidate_facts_and_is_clock_stable(monkeypatch):
    clock, facts, ctx, _, session, _, service = sql_fixture()
    candidate = service.preview(ctx, facts.reference)
    monkeypatch.setattr(commands, "runtime_for", lambda *args, **kwargs: service)
    payload = LifecycleCommandPayload(
        candidate_id=candidate.id, digest=candidate.digest, reason="Review actual orphan facts"
    )
    command = command_for(facts, "evidence.lifecycle.quarantine")
    product = session.rows[models.Product][0]
    first = commands.preview_view(session, ctx, command, product, payload)
    clock.value += timedelta(seconds=3)
    second = commands.preview_view(session, ctx, command, product, payload)
    assert first == second
    assert first["before"]["registered"] is False
    assert first["before"]["manual_hold"] is False
    assert first["before"]["reference_count"] == 0
    assert first["before"]["formal_history"] is False
    assert first["before"]["retention_until"] == candidate.original.retention_until.isoformat()
    assert first["after"]["physical_effect_applied"] is False
    assert "server_storage_key" not in repr(first)


def test_protection_t1_updates_columns_state_and_epoch_without_weakening_grace(monkeypatch):
    clock, facts, ctx, _, session, store, service = sql_fixture()
    store.read_current(facts.reference)
    monkeypatch.setattr(commands, "runtime_for", lambda *args, **kwargs: service)
    command = command_for(facts, "evidence.lifecycle.protection.record")
    payload = LifecycleProtectionPayload(
        object_id=facts.reference.id,
        expected_revision=1,
        manual_hold=True,
        retention_until=clock.now() + timedelta(days=30),
        reason="Explicit named hold",
    )
    product = session.rows[models.Product][0]
    review = commands.preview_view(session, ctx, command, product, payload)
    row, subject_type, visibility = commands.apply(session, ctx, command, product, payload)
    assert subject_type == "original_lifecycle_object" and visibility == "private"
    assert row.protection_revision == row.revision == 2
    current = store.read_current(facts.reference)
    assert current.manual_hold is True and current.retention_until == payload.retention_until
    assert review["before"]["manual_hold"] is False
    assert review["after"]["manual_hold"] is True
    candidate = service.preview(ctx, facts.reference)
    assert DecisionReason.MANUAL_HOLD in candidate.decision.reasons
    assert DecisionReason.RETENTION_NOT_ELAPSED in candidate.decision.reasons


def test_pending_intent_blocks_protection_edits(monkeypatch):
    clock, facts, ctx, _, session, store, service = sql_fixture()
    candidate = service.preview(ctx, facts.reference)
    store.request_reason = "named"
    service.confirm(ctx, candidate.id, candidate.digest, "confirm")
    monkeypatch.setattr(commands, "runtime_for", lambda *args, **kwargs: service)
    payload = LifecycleProtectionPayload(
        object_id=facts.reference.id,
        expected_revision=2,
        manual_hold=False,
        retention_until=clock.now() - timedelta(days=1),
        reason="Attempted relaxation",
    )
    command = command_for(facts, "evidence.lifecycle.protection.record")
    with pytest.raises(DomainError) as error:
        commands.preview_view(session, ctx, command, session.rows[models.Product][0], payload)
    assert error.value.code == REASONS["EFFECT_PENDING"]
    assert error.value.reason == "EFFECT_PENDING"


def test_common_replay_subject_reuses_same_facts_candidate_before_stale_t1_check(monkeypatch):
    _, facts, ctx, _, session, store, service = sql_fixture()
    first = service.preview(ctx, facts.reference)
    alias = service.preview(ctx, facts.reference)
    assert first.id != alias.id
    store.request_reason = "original reason"
    original = service.confirm(ctx, first.id, first.digest, "original")
    monkeypatch.setattr(commands, "runtime_for", lambda *args, **kwargs: service)
    payload = LifecycleCommandPayload(
        candidate_id=alias.id, digest=alias.digest, reason="new candidate of same unchanged facts"
    )
    command = command_for(facts, "evidence.lifecycle.quarantine")
    product = session.rows[models.Product][0]
    assert commands.replay_subject(session, ctx, command, product, payload).id == original.id
    with pytest.raises(DomainError) as stale:
        commands.preview_view(session, ctx, command, product, payload)
    assert stale.value.code == REASONS["PREVIEW_STALE"]
    assert stale.value.reason == "PREVIEW_STALE"
    session.rows[models.Grant][0].can_write = False
    with pytest.raises(DomainError) as denied:
        commands.replay_subject(session, ctx, command, product, payload)
    assert denied.value.status == 403


def test_common_candidate_review_samples_clock_after_reference_read(monkeypatch):
    clock, facts, ctx, _, session, _, service = sql_fixture()

    def advancing_now():
        clock.value += timedelta(milliseconds=1)
        return clock.value

    monkeypatch.setattr(clock, "now", advancing_now)
    candidate = service.preview(ctx, facts.reference)
    assert candidate.decision.eligible
    monkeypatch.setattr(commands, "runtime_for", lambda *args, **kwargs: service)
    payload = LifecycleCommandPayload(
        candidate_id=candidate.id,
        digest=candidate.digest,
        reason="Review after current facts are read",
    )
    review = commands.preview_view(
        session,
        ctx,
        command_for(facts, "evidence.lifecycle.quarantine"),
        session.rows[models.Product][0],
        payload,
    )
    assert review["before"]["eligible"] is True
    assert review["after"]["status"] == "pending"
