"""Synthetic Session/transaction/rows only. Root owns real PG atomic validation."""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from quality_followup.test_pure import issue as fixed_issue
from quality_issues.helpers import NOW, source, uid
from sqlalchemy import inspect as actual_inspect
from sqlalchemy.orm import Session as ActualSession
from sqlalchemy.orm import make_transient_to_detached
from sqlalchemy.orm.attributes import set_committed_value

from pdos_next import quality_followup_host as host
from pdos_next.contracts import Command
from pdos_next.domain.quality_execution.evidence import merge_reads, union_sources
from pdos_next.domain.quality_execution.models import QualityIssueCurrent, QualityIssueVersion
from pdos_next.domain.quality_followup import service as followup
from pdos_next.domain.quality_followup.schemas import RootCausePayload
from pdos_next.domain.quality_issues.ports import Mutation
from pdos_next.domain.quality_issues.rules import issue_sources, replace
from pdos_next.errors import DomainError
from pdos_next.models import Confirmation
from pdos_next.schemas.quality_issues.contracts import NamedConclusion
from pdos_next.service import Context, digest, material_digest


class Result:
    def __init__(self, value):
        self.value = value

    def one_or_none(self):
        return self.value


class Session:
    def __init__(self, ctx):
        self.info = {}
        self.transaction = SimpleNamespace(is_active=True)
        self.nested = None
        self.confirmation = None
        self.pointer = None
        self.actor = (ctx.tenant_id, "human", True)
        self.deleted = (False,)
        self.added_history = (True,)
        self.persistent = True
        self.added = []
        self.flushes = 0

    def get_transaction(self):
        return self.transaction

    def get_nested_transaction(self):
        return self.nested

    def execute(self, statement):
        return Result(self.actor)

    def scalar(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        if entity is Confirmation:
            return self.confirmation
        assert entity is QualityIssueCurrent
        return self.pointer

    def add(self, row):
        self.added.append(row)

    def flush(self):
        self.flushes += 1


@pytest.fixture
def work(monkeypatch):
    issue = fixed_issue()
    ctx = Context(
        issue.scope.tenant_id, uid("executor"), uid("executor"), category_id=uid("category")
    )
    session = Session(ctx)
    monkeypatch.setattr(host, "now", lambda: NOW)
    # This pure fake is explicitly not an actual ORM consumption or PG proof.
    monkeypatch.setattr(
        host,
        "inspect",
        lambda row: SimpleNamespace(
            session=session,
            persistent=session.persistent,
            attrs=SimpleNamespace(
                consumed=SimpleNamespace(
                    history=SimpleNamespace(
                        deleted=session.deleted,
                        added=session.added_history,
                    )
                )
            ),
        ),
    )
    ref = source("host-root")
    payload = RootCausePayload(
        issue_id=issue.id,
        expected_issue_revision=issue.revision,
        text="Named synthetic root cause",
        sources=(ref.model_dump(),),
        approval_token="explicit-synthetic-token",
    )
    command = Command(
        command_id=uuid4(),
        idempotency_key="synthetic-host-key",
        operation=followup.ROOT_CAUSE,
        category_id=ctx.category_id,
        product_id=issue.scope.product_id,
        expected_revision=8,
        source_read_set=[{"artifact_id": ref.id, "expected_revision": ref.revision}],
        payload=payload.model_dump(mode="json"),
    )
    confirmation = Confirmation(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        product_id=command.product_id,
        actor_id=ctx.actor_id,
        subject_id=command.product_id,
        operation=command.operation,
        revision=command.expected_revision,
        token_hash=digest(payload.approval_token),
        payload_digest=material_digest(ctx, command, payload, followup),
        snapshot={"fake": "synthetic-only"},
        expires_at=NOW + timedelta(minutes=10),
        consumed=True,
    )
    session.confirmation = confirmation
    return SimpleNamespace(
        s=session,
        ctx=ctx,
        issue=issue,
        ref=ref,
        payload=payload,
        command=command,
        confirmation=confirmation,
    )


def record(work):
    return host.record_consumed_confirmation(
        work.s, work.ctx, work.command, work.payload, followup, work.confirmation
    )


def require(work, tier="T2"):
    return host.require_consumed_proof(work.s, work.ctx, work.command, work.payload, tier=tier)


def code(expected, callback):
    with pytest.raises(DomainError) as error:
        callback()
    assert error.value.reason == expected


def test_historical_consumed_bool_without_real_marker_cannot_be_used(work):
    code("NAMED_APPROVAL_REQUIRED", lambda: require(work))
    assert work.s.added == [] and work.s.flushes == 0


@pytest.mark.parametrize("deleted,added", [((), ()), ((True,), (True,)), ((False,), ())])
def test_record_needs_immediate_unflushed_actual_transition(work, deleted, added):
    work.s.deleted, work.s.added_history = deleted, added
    code("NAMED_APPROVAL_REQUIRED", lambda: record(work))


def test_record_rejects_detached_or_transient_object(work):
    work.s.persistent = False
    code("NAMED_APPROVAL_REQUIRED", lambda: record(work))


def test_repeat_assertion_returns_same_actual_uuid_without_consumption_or_preview(work):
    identity = record(work)
    work.s.deleted, work.s.added_history = (), ()
    assert identity == work.confirmation.id == require(work) == require(work)
    assert work.confirmation.consumed is True
    assert work.s.added == [] and work.s.flushes == 0


def test_named_t2_consumption_without_deadline_retains_the_same_transaction_binding(work):
    work.confirmation.expires_at = None
    identity = record(work)
    assert require(work) == identity
    work.s.transaction = SimpleNamespace(is_active=True)
    code("NAMED_APPROVAL_REQUIRED", lambda: require(work))


@pytest.mark.parametrize("mode", ["transaction", "inactive", "nested", "another_session"])
def test_marker_cannot_cross_commit_rollback_savepoint_or_session(work, mode):
    record(work)
    if mode == "transaction":
        work.s.transaction = SimpleNamespace(is_active=True)
    elif mode == "inactive":
        work.s.transaction.is_active = False
    elif mode == "nested":
        work.s.nested = SimpleNamespace(is_active=True)
    else:
        second = Session(work.ctx)
        second.info = dict(work.s.info)
        work.s = second
    code(
        "INTEGRATION_REQUIRED" if mode == "inactive" else "NAMED_APPROVAL_REQUIRED",
        lambda: require(work),
    )


@pytest.mark.parametrize("field", ["command_id", "idempotency_key", "readset", "payload", "tier"])
def test_actual_provenance_is_bound_to_exact_command_material_and_tier(work, field):
    record(work)
    tier = "T2"
    if field == "command_id":
        work.command = work.command.model_copy(update={"command_id": uuid4()})
    elif field == "idempotency_key":
        work.command = work.command.model_copy(update={"idempotency_key": "different-key"})
    elif field == "readset":
        work.command = work.command.model_copy(update={"source_read_set": []})
    elif field == "payload":
        work.payload = work.payload.model_copy(update={"text": "Changed named conclusion"})
        work.command = work.command.model_copy(
            update={"payload": work.payload.model_dump(mode="json")}
        )
    else:
        tier = "T1"
    code("NAMED_APPROVAL_REQUIRED", lambda: require(work, tier))


@pytest.mark.parametrize("field", ["subject_id", "revision", "actor_id", "consumed", "snapshot"])
def test_changed_confirmation_record_is_not_reusable(work, field):
    record(work)
    if field == "revision":
        value = 9
    elif field == "consumed":
        value = False
    elif field == "snapshot":
        value = {"different": True}
    else:
        value = uuid4()
    setattr(work.confirmation, field, value)
    code("SOURCE_STALE", lambda: require(work))


def test_final_assertion_rechecks_real_expiry_and_current_principal(work, monkeypatch):
    record(work)
    work.s.actor = (work.ctx.tenant_id, "human", False)
    code("NAMED_DECISION_REQUIRED", lambda: require(work))
    work.s.actor = (work.ctx.tenant_id, "human", True)
    monkeypatch.setattr(host, "now", lambda: work.confirmation.expires_at)
    code("NAMED_APPROVAL_REQUIRED", lambda: require(work))


def test_product_confirmation_does_not_accept_issue_id_as_subject(work):
    work.confirmation.subject_id = work.issue.id
    code("NAMED_APPROVAL_REQUIRED", lambda: record(work))


def test_real_orm_transition_is_recorded_without_any_connection_or_sql(work, monkeypatch):
    monkeypatch.setattr(host, "inspect", actual_inspect)
    detached = Confirmation(
        **host._confirmation_material(work.confirmation),
    )
    detached.consumed = False
    make_transient_to_detached(detached)
    # No bind, connection, SQLite or database is used. load=False stamps the
    # complete detached row into a real identity map for ORM transition checks.
    with ActualSession() as session:
        current = session.merge(detached, load=False)
        current.consumed = True
        assert actual_inspect(current).persistent
        assert tuple(actual_inspect(current).attrs.consumed.history.deleted) == (False,)
        identity = host.record_consumed_confirmation(
            session, work.ctx, work.command, work.payload, followup, current
        )
        assert identity == current.id
        set_committed_value(current, "consumed", True)
        code(
            "NAMED_APPROVAL_REQUIRED",
            lambda: host.record_consumed_confirmation(
                session, work.ctx, work.command, work.payload, followup, current
            ),
        )
        session.rollback()
        code(
            "INTEGRATION_REQUIRED",
            lambda: host.require_consumed_proof(
                session, work.ctx, work.command, work.payload, tier="T2"
            ),
        )


def test_cross_actor_or_ai_identity_cannot_assert_human_marker(work):
    record(work)
    work.ctx = Context(work.ctx.tenant_id, uid("other-actor"), work.ctx.requester_id)
    code("NAMED_DECISION_REQUIRED", lambda: require(work))


def prepare_append(work, *, visibility="private", audience=None):
    before = work.issue
    if visibility != "private":
        before = replace(before, audience=audience or (f"category:{work.ctx.category_id}",))
    raw = before.model_dump(mode="json")
    sources = union_sources(issue_sources(before), (work.ref,))
    reads = merge_reads(
        [{"artifact_id": source.id, "expected_revision": source.revision} for source in sources]
    )
    work.command = Command.model_validate(
        {**work.command.model_dump(mode="json"), "source_read_set": reads}
    )
    work.confirmation.payload_digest = material_digest(
        work.ctx, work.command, work.payload, followup
    )
    row = QualityIssueVersion(
        id=uuid4(),
        tenant_id=work.ctx.tenant_id,
        category_id=work.ctx.category_id,
        product_id=work.command.product_id,
        project_id=before.scope.project_id,
        issue_id=before.id,
        revision=before.revision,
        status=before.status,
        owner_id=work.ctx.requester_id,
        writer_id=work.ctx.requester_id,
        visibility=visibility,
        purpose="investigation",
        issue_snapshot=raw,
        snapshot_sha256=digest(raw),
        sources=[source.model_dump(mode="json") for source in sources],
    )
    after = replace(
        before,
        revision=before.revision + 1,
        root_cause=NamedConclusion(
            text=work.payload.text,
            actor_id=work.ctx.requester_id,
            sources=work.payload.sources,
            at=NOW,
        ),
    )
    authority = {"authorized": True, "qualified": True, "explicit_fake": True}
    policy = {"risk": "high", "sources": [work.ref.model_dump(mode="json")]}
    basis = {
        "artifact_sources": [
            {"id": str(source.id), "revision": source.revision} for source in sources
        ],
        "followup_basis": {"sources": row.sources},
        "completion_assessments": [],
    }
    work.confirmation.snapshot = {
        "before": {str(before.id): raw},
        "after": {str(after.id): followup._preview_issue(after, before)},
        "read_basis": {
            "authority": authority,
            "policy": policy,
            "source_basis": deepcopy(basis),
            "read_set": reads,
        },
    }
    identity = record(work)
    basis["shared_proof"] = {"id": str(identity), "tier": "T2"}
    basis["completion_observations"] = []
    work.s.pointer = SimpleNamespace(issue_version_id=row.id, issue_revision=row.revision, epoch=4)
    mutation = Mutation(changes=(after,), event_name="issue.root_cause_decided", preview_digest="p")
    kwargs = {
        "operation": work.command.operation,
        "authority": authority,
        "policy_snapshot": policy,
        "required_source_read_set": reads,
        "source_basis": basis,
        "input_snapshot": followup.semantic(work.payload),
        "intent_digest": followup._intent(work.ctx, work.command, work.payload),
        "expected_issue_revision": row.revision,
    }
    return SimpleNamespace(
        row=row,
        after=after,
        product=SimpleNamespace(id=work.command.product_id, revision=8),
        mutation=mutation,
        kwargs=kwargs,
    )


def append(work, prepared):
    return host.append_issue(
        work.s, work.ctx, prepared.product, prepared.row, prepared.mutation, **prepared.kwargs
    )


def test_append_preserves_fixed_old_issue_and_continuously_updates_current_once(work):
    prepared = prepare_append(work)
    original = deepcopy(prepared.row.issue_snapshot)
    new = append(work, prepared)
    assert new.id != prepared.row.id
    assert (new.issue_id, new.revision, new.previous_issue_version_id, new.previous_revision) == (
        prepared.row.issue_id,
        prepared.row.revision + 1,
        prepared.row.id,
        prepared.row.revision,
    )
    assert (new.owner_id, new.visibility, new.purpose) == (
        prepared.row.owner_id,
        prepared.row.visibility,
        prepared.row.purpose,
    )
    assert new.snapshot_sha256 == digest(prepared.after.model_dump(mode="json"))
    assert new.sources == prepared.row.sources
    assert new.source_basis == prepared.kwargs["source_basis"]
    assert new.authority_snapshot == prepared.kwargs["authority"]
    assert work.s.pointer.issue_version_id == new.id and work.s.pointer.epoch == 5
    assert work.s.added == [new] and work.s.flushes == 2
    assert prepared.row.issue_snapshot == original


def test_shared_append_preserves_actual_category_audience(work):
    prepared = prepare_append(work, visibility="category")
    new = append(work, prepared)
    assert new.visibility == "category"
    assert new.issue_snapshot["audience"] == [f"category:{work.ctx.category_id}"]
    assert prepared.after.audience == (f"category:{work.ctx.category_id}",)
    assert work.s.pointer.issue_version_id == new.id


@pytest.mark.parametrize("audience", ["product", "other_category"])
def test_shared_append_rejects_stale_product_or_wrong_category_audience(work, audience):
    fixed = f"product:{work.command.product_id}" if audience == "product" else f"category:{uuid4()}"
    prepared = prepare_append(work, visibility="category", audience=(fixed,))
    code("FORBIDDEN_SCOPE", lambda: append(work, prepared))
    assert work.s.added == [] and work.s.flushes == 0


@pytest.mark.parametrize("case", ["pointer", "scope", "intent", "preview", "reads", "proof"])
def test_append_rejects_cas_scope_intent_preview_or_incomplete_sources_before_writing(work, case):
    prepared = prepare_append(work)
    expected = "INTEGRITY_MISMATCH"
    if case == "pointer":
        work.s.pointer.issue_revision += 1
        expected = "VERSION_CONFLICT"
    elif case == "scope":
        prepared.row.project_id = uuid4()
    elif case == "intent":
        prepared.kwargs["intent_digest"] = "changed"
    elif case == "preview":
        prepared.kwargs["authority"] = {"changed": True}
        expected = "CONFIRMATION_SCOPE_CHANGED"
    elif case == "reads":
        prepared.kwargs["required_source_read_set"] = []
        expected = "MISSING_REQUIRED_EVIDENCE"
    else:
        prepared.kwargs["source_basis"]["shared_proof"]["id"] = str(uuid4())
        expected = "NAMED_APPROVAL_REQUIRED"
    code(expected, lambda: append(work, prepared))
    assert work.s.added == [] and work.s.flushes == 0


def test_compatible_same_command_cannot_append_after_own_success(work):
    prepared = prepare_append(work)
    append(work, prepared)
    code("VERSION_CONFLICT", lambda: append(work, prepared))
    assert len(work.s.added) == 1


def test_configure_host_has_no_positive_completion_assessment_default():
    engine = SimpleNamespace()
    host.configure_host(engine)
    runtime = engine._pdos_quality_followup
    assert runtime.append_issue is host.append_issue
    assert runtime.consumed_proof is host.require_consumed_proof
    assert runtime.assess_action_completion is None
