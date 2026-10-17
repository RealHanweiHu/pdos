"""Production candidate group checks with explicit no-connect SELECT results.

The real helper executes its boolean SELECT under the original caller. Complete
current ORM/DTO shapes and every saved-group guard remain in the production path;
these substitutes do not prove PostgreSQL RLS, qualification or live evidence.
"""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
from quality_issues.helpers import uid
from sqlalchemy import create_engine, event
from test_fixed_candidate_anchor import origin_fixture
from test_participants_owner import RawSession

from pdos_next.domain.capa_effectiveness import candidate_commands as commands
from pdos_next.domain.capa_effectiveness import candidate_storage as storage
from pdos_next.domain.capa_verification.models import CapaVerificationEvidence
from pdos_next.domain.capa_verification.schemas import CandidateBinding, CandidateInspect
from pdos_next.domain.capa_verification.service import basis_from_issue
from pdos_next.domain.quality_execution.models import QualityIssueVersion
from pdos_next.errors import DomainError
from pdos_next.models import Audit, Confirmation, Outbox, Principal, Receipt, RequestKey
from pdos_next.service import Context, digest


class GroupSession(RawSession):
    """Only SQL results are substituted; ORM columns and UOW are actual."""

    binding_result = True

    def __init__(self, engine):
        super().__init__(engine)
        self.binding_calls = []

    def scalars(self, statement, *args, **kwargs):
        model = statement.column_descriptions[0]["entity"]
        return [model(**row) for row in self.selected(statement)]

    def scalar(self, statement, *args, **kwargs):
        columns = list(statement.selected_columns)
        function = getattr(columns[0], "element", None)
        assert getattr(function, "name", None) == "change_receipt_key_bound"
        assert function.packagenames == ("public",)
        assert tuple(value.value for value in function.clauses) == self.expected_binding
        assert statement.get_execution_options()["autoflush"] is False
        assert statement.get_execution_options()["populate_existing"] is True
        assert self.info["scope"] == self.expected_scope
        assert self.get_transaction() is self.original_transaction
        self.binding_calls.append(statement)
        return self.binding_result


def _seed(session, model, **values):
    session.seed(model, **values)
    return session.rows[model.__tablename__][-1]


@pytest.fixture
def work():
    stable = origin_fixture()
    origin = stable.origin
    ctx = Context(
        origin.scope.tenant_id,
        origin.writer_id,
        origin.writer_id,
        category_id=origin.category_id,
    )
    engine = create_engine("postgresql+psycopg://unused/never_connect")

    @event.listens_for(engine, "do_connect")
    def no_connection(*_args):
        raise AssertionError("candidate group pure checks must never connect")

    session = GroupSession(engine)
    session.begin()
    fixed_issue = QualityIssueVersion(
        id=origin.ref.id,
        tenant_id=ctx.tenant_id,
        product_id=origin.scope.product_id,
        project_id=origin.scope.project_id,
        issue_id=origin.issue_id,
        revision=origin.ref.revision,
        purpose=origin.purpose,
        owner_id=origin.owner_id,
        visibility="category",
        snapshot_sha256=origin.ref.snapshot_sha256,
    )
    source_basis = [value.model_dump(mode="json") for value in origin.source_basis]
    basis = basis_from_issue(
        fixed_issue,
        origin.issue,
        sources=origin.sources,
        reads=origin.required_source_read_set,
        source_basis=source_basis,
    )
    binding = CandidateBinding(basis=basis)
    inspection = CandidateInspect(
        binding=binding,
        current=True,
        required_source_read_set=basis.required_source_read_set,
        source_basis_sha256=digest(source_basis),
        inspection_sha256="0" * 64,
        missing=(),
    )
    inspection = inspection.model_copy(
        update={
            "inspection_sha256": digest(
                inspection.model_dump(mode="json", exclude={"inspection_sha256", "candidate_ref"})
            )
        }
    )
    payload = commands.CandidateRecordPayload(
        issue_id=origin.issue_id,
        expected_issue_revision=origin.ref.revision,
        capa_id=origin.issue.capa.id,
        reason="Synthetic candidate common-group regression",
        visibility="category",
    )
    owner = commands.semantic_owner()
    at = origin.created_at + timedelta(minutes=5)
    body = storage.CandidateInput(
        semantic=owner.semantic(payload),
        shared_proof=storage.SharedProof(id=uid("peer-candidate-proof"), tier="T1"),
        proof_consumed_at=at - timedelta(microseconds=1),
        stable_anchor=stable,
    )
    intent = digest(
        {
            "operation": storage.OPERATION,
            "category": ctx.category_id,
            "product": origin.scope.product_id,
            "payload": owner.semantic(payload),
            "named_actor": origin.writer_id,
            "source_revision": None,
            "private_owner": None,
        }
    )
    candidate = CapaVerificationEvidence(
        id=uid("peer-candidate"),
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        product_id=origin.scope.product_id,
        project_id=origin.scope.project_id,
        issue_id=origin.issue_id,
        issue_version_id=origin.ref.id,
        issue_revision=origin.ref.revision,
        capa_id=origin.issue.capa.id,
        owner_id=origin.owner_id,
        writer_id=origin.writer_id,
        visibility="category",
        purpose=origin.purpose,
        nature="synthetic",
        revision=1,
        created_at=at,
        basis_snapshot=basis.model_dump(mode="json"),
        basis_sha256=basis.basis_sha256,
        sources=[value.model_dump(mode="json") for value in basis.sources],
        required_source_read_set=[
            value.model_dump(mode="json") for value in basis.required_source_read_set
        ],
        source_basis={"artifact_sources": source_basis},
        input_snapshot=body.model_dump(mode="json"),
        intent_digest=intent,
        reason=payload.reason,
        remediation_link_id=None,
        candidate_binding=binding.model_dump(mode="json"),
        binding_sha256=digest(binding.model_dump(mode="json")),
        candidate_snapshot=inspection.model_dump(mode="json"),
        inspection_sha256=inspection.inspection_sha256,
        status="candidate",
        result="indeterminate",
        applicable=None,
        independently_verified=None,
        observation_complete=None,
    )
    shared = dict(tenant_id=ctx.tenant_id, category_id=ctx.category_id)
    _seed(
        session,
        Principal,
        id=origin.writer_id,
        tenant_id=ctx.tenant_id,
        created_at=at - timedelta(days=1),
        name="Synthetic named candidate writer",
        kind="human",
        active=True,
        access_epoch=1,
    )
    receipt = _seed(
        session,
        Receipt,
        **shared,
        id=uid("peer-candidate-receipt"),
        product_id=candidate.product_id,
        command_id=uid("peer-candidate-command"),
        actor_id=origin.writer_id,
        requester_id=origin.writer_id,
        operation=storage.OPERATION,
        subject_type=storage.SUBJECT,
        subject_id=candidate.id,
        subject_revision=1,
        visibility="category",
        request_digest=digest("original complete candidate request"),
        intent_digest=intent,
        run_id=None,
        agent_run_id=None,
        confirmation_id=body.shared_proof.id,
        result={
            "id": str(candidate.id),
            "revision": 1,
            "status": "candidate",
            "candidate_binding_sha256": candidate.binding_sha256,
            "inspection_sha256": candidate.inspection_sha256,
        },
        created_at=at + timedelta(microseconds=1),
    )
    key = _seed(
        session,
        RequestKey,
        **shared,
        id=uid("peer-candidate-key"),
        actor_id=origin.writer_id,
        key="original private candidate key",
        receipt_id=receipt["id"],
        digest=receipt["request_digest"],
        created_at=receipt["created_at"],
    )
    proof = _seed(
        session,
        Confirmation,
        **shared,
        id=body.shared_proof.id,
        product_id=candidate.product_id,
        actor_id=origin.writer_id,
        subject_id=candidate.product_id,
        subject_type="product",
        operation=storage.OPERATION,
        revision=42,
        token_hash=digest("historical confirmation token"),
        expires_at=at + timedelta(minutes=10),
        consumed=True,
        payload_digest=digest(
            {
                "tenant": ctx.tenant_id,
                "actor": origin.writer_id,
                "requester": origin.writer_id,
                "operation": storage.OPERATION,
                "category": ctx.category_id,
                "product": candidate.product_id,
                "expected_revision": 42,
                "read_set": sorted(
                    candidate.required_source_read_set,
                    key=lambda value: (value["artifact_id"], value["expected_revision"]),
                ),
                "payload": owner.semantic(payload),
            }
        ),
        snapshot={"exact_candidate_review": candidate.candidate_snapshot},
        created_at=at - timedelta(minutes=1),
    )
    audit = _seed(
        session,
        Audit,
        **shared,
        id=uid("peer-candidate-audit"),
        receipt_id=receipt["id"],
        actor_id=origin.writer_id,
        operation=storage.OPERATION,
        created_at=receipt["created_at"],
    )
    outbox = _seed(
        session,
        Outbox,
        **shared,
        id=uid("peer-candidate-outbox"),
        receipt_id=receipt["id"],
        type=storage.EVENT,
        subject_id=candidate.id,
        subject_revision=1,
        schema_version=1,
        actor_id=origin.writer_id,
        correlation_id=receipt["command_id"],
        delivered_at=None,
        lease_id=None,
        lease_until=None,
        attempts=0,
        last_error=None,
        created_at=receipt["created_at"],
    )
    value = SimpleNamespace(
        s=session,
        ctx=ctx,
        pid=candidate.product_id,
        candidate=candidate,
        body=body,
        payload=payload,
        owner=owner,
        receipt=receipt,
        key=key,
        proof=proof,
        audit=audit,
        outbox=outbox,
    )
    yield value
    session.close()
    engine.dispose()


def _read(work, *, peer=False, hidden_key=False, bound=True):
    ctx = (
        replace(work.ctx, actor_id=uid("candidate-peer"), requester_id=uid("candidate-peer"))
        if peer
        else work.ctx
    )
    scope = (ctx.tenant_id, ctx.actor_id, ctx.requester_id, ctx.category_id)
    work.s.info["scope"] = work.s.expected_scope = scope
    work.s.expected_binding = (ctx.tenant_id, work.pid, work.receipt["id"])
    work.s.original_transaction = work.s.get_transaction()
    work.s.binding_result = bound
    if hidden_key:
        work.s.rows[RequestKey.__tablename__].clear()
    before = deepcopy(vars(ctx))
    try:
        return storage._group(
            work.s, ctx, work.pid, work.candidate, work.body, work.payload, work.owner
        )
    finally:
        assert vars(ctx) == before
        assert work.s.info["scope"] == scope and not work.s.new
        assert work.s.get_transaction() is work.s.original_transaction


@pytest.mark.parametrize("peer", [False, True], ids=["own-key", "peer-readable-key"])
def test_readable_original_key_keeps_existing_full_group_path_without_helper(work, peer):
    group = _read(work, peer=peer, bound=False)
    assert work.s.binding_calls == []
    assert group["receipt"]["id"] == str(work.receipt["id"])
    assert group["confirmation"]["consumed"] is True
    assert group["original_request_digest"] == work.key["digest"]
    assert "request_keys" not in group and work.key["key"] not in str(group)


def test_peer_hidden_key_real_helper_true_reaches_the_complete_saved_group(work):
    group = _read(work, peer=True, hidden_key=True)
    assert len(work.s.binding_calls) == 1
    assert group["schema_version"] == "pdos-capa-candidate-common-group-v1"
    assert group["receipt"]["actor_id"] == str(work.candidate.writer_id)
    assert set(group["receipt"]) == set(Receipt.__table__.columns.keys())
    assert set(group["confirmation"]) == set(Confirmation.__table__.columns.keys())
    assert set(group["audit"]) == set(Audit.__table__.columns.keys())
    assert set(group["outbox"]) == set(Outbox.__table__.columns.keys()) - storage.DELIVERY_FIELDS
    assert work.s.rows[RequestKey.__tablename__] == []


@pytest.mark.parametrize("bound", [False, None, 1], ids=["false", "none", "integer-one"])
def test_peer_hidden_key_requires_actual_boolean_true_from_real_helper(work, bound):
    with pytest.raises(DomainError) as error:
        _read(work, peer=True, hidden_key=True, bound=bound)
    assert error.value.reason == "CANDIDATE_ORIGINAL_REQUEST_KEY_MISSING"
    assert len(work.s.binding_calls) == 1


def test_own_missing_key_rejects_without_calling_peer_boolean_helper(work):
    with pytest.raises(DomainError) as error:
        _read(work, hidden_key=True)
    assert error.value.reason == "CANDIDATE_ORIGINAL_REQUEST_KEY_MISSING"
    assert work.s.binding_calls == []


@pytest.mark.parametrize("fault", ["unconsumed", "proof-actor", "proof-digest", "audit", "outbox"])
def test_true_peer_binding_still_requires_the_original_consumed_common_group(work, fault):
    if fault == "unconsumed":
        work.proof["consumed"] = False
    elif fault == "proof-actor":
        work.proof["actor_id"] = uid("another-proof-actor")
    elif fault == "proof-digest":
        work.proof["payload_digest"] = digest("different confirmed candidate")
    elif fault == "audit":
        work.audit["operation"] = "quality.issue.create"
    else:
        work.outbox["correlation_id"] = uid("different-command")
    with pytest.raises(DomainError) as error:
        _read(work, peer=True, hidden_key=True)
    assert error.value.reason == "CANDIDATE_SAVED_COMMON_GROUP_MISMATCH"
    assert len(work.s.binding_calls) == 1


@pytest.mark.parametrize("fault", ["requester", "intent", "result"])
def test_peer_true_binding_cannot_replace_exact_original_receipt(work, fault):
    if fault == "requester":
        work.receipt["requester_id"] = uid("different-requester")
    elif fault == "intent":
        work.receipt["intent_digest"] = digest("different-intent")
    else:
        work.receipt["result"]["revision"] = True
    with pytest.raises(DomainError) as error:
        _read(work, peer=True, hidden_key=True)
    assert error.value.reason == "CANDIDATE_RECEIPT_BINDING_MISMATCH"
    assert work.s.binding_calls == []
