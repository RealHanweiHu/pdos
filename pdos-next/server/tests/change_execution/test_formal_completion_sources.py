"""Formal completion source projection with actual DTO/proof and transaction.

The completion adapter and implementation attest() execute. Exact saved rows,
original bytes, professional/approval readers and implementation read/refresh
are explicit no-connect IO substitutes, not qualification or PG acceptance.
"""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from pdos_next import change_completion_adapter as adapter
from pdos_next.change_implementation_owner import ApprovedImplementationRead
from pdos_next.domain.change_execution.graph import OwnedObject
from pdos_next.domain.change_execution.models import ChangeCurrent, ChangeRequestVersion
from pdos_next.domain.quality_followup import service as followup
from pdos_next.domain.quality_followup.schemas import Completion, CompletionAssessment
from pdos_next.errors import DomainError
from pdos_next.schemas.change_control.contracts import Ref

from . import kernel_helpers as helper
from .test_change_order import no_connection  # noqa: F401 - denies DB/HTTP, keeps live helper clock
from .test_public_integration import occurrence_work


@pytest.fixture
def formal_sources(monkeypatch):
    ctx, basis, binding, occurrence, _ = occurrence_work()
    kernel = helper.FakeHost()
    kernel.approve()
    request, order = kernel.request_value, kernel.order
    item = order.plan.items[0]
    node = request.assessments[-1].graph.nodes[0]
    domain = OwnedObject(
        node.ref, node.label, node.scope, ctx.requester_id, "category", {}, [], {}, True
    ).source
    # Preserve the actual graph-source location inside the complete request
    # material that ApprovedImplementationOwner.attest() seals.
    raw = request.model_dump(mode="json")
    raw["assessments"][-1]["graph"]["nodes"][0]["source"] = domain.model_dump(mode="json")
    raw["assessments"][-1]["graph"]["sources"].append(domain.model_dump(mode="json"))
    request = type(request).model_validate(raw)
    occurrence = occurrence.model_copy(
        update={
            "change_id": request.id,
            "order_id": order.id,
            "item_id": item.id,
            "intent_id": item.intent.id,
            "outputs": (Ref(id=uuid4(), revision=2, kind="engineering_configuration"),),
        }
    )
    completion = Completion(
        id=binding.action_id,
        executor_id=binding.executor_id,
        text="Actual saved approved configuration implementation",
        evidence=(helper.SOURCE.model_dump(mode="json"),),
        at={
            "occurred_at": helper.NOW,
            "original_timezone": "UTC",
            "source": helper.SOURCE.model_dump(mode="json"),
        },
    )
    basis.issue_revision = 4
    basis.basis_sha256 = "b" * 64
    basis.sources = (helper.SOURCE,)
    basis.required_source_read_set = [
        {"artifact_id": str(helper.SOURCE.id), "expected_revision": helper.SOURCE.revision}
    ]
    basis.owner_id, basis.visibility = ctx.requester_id, "category"
    row = ChangeRequestVersion(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        product_id=basis.scope.product_id,
        project_id=basis.scope.project_id,
        change_id=request.id,
        revision=request.revision,
        status=request.status,
        operation="change.implementation.record",
        request_snapshot=request.model_dump(mode="json"),
        request_sha256=adapter.digest(request.model_dump(mode="json")),
        sources=[v.model_dump(mode="json") for v in (helper.SOURCE, domain)],
        required_source_read_set=deepcopy(basis.required_source_read_set),
        source_basis={
            "artifacts": {str(helper.SOURCE.id): {"revision": helper.SOURCE.revision}},
            "owners": {node.ref.identity: {"source": domain.model_dump(mode="json")}},
        },
    )
    pointer = ChangeCurrent(id=uuid4(), version_id=row.id, revision=row.revision)
    capture = adapter.store.ImplementationCapture(
        id=uuid4(),
        occurrence_snapshot=occurrence.model_dump(mode="json"),
        sources=[helper.SOURCE.model_dump(mode="json")],
    )
    atom = adapter.store.ChangeImplementationRecord(id=uuid4(), change_version_id=row.id)
    until = helper.NOW + timedelta(hours=1)
    executed = ApprovedImplementationRead(
        row,
        atom,
        uuid4(),
        occurrence,
        {
            "version": row.request_snapshot,
            "atom": {"id": str(occurrence.implementation_id)},
            "capture": capture.occurrence_snapshot,
            "outputs": [v.model_dump(mode="json") for v in occurrence.outputs],
            "group": {"receipt": {"id": str(uuid4())}},
            "sources": row.source_basis,
        },
        until,
    )
    selected = SimpleNamespace(
        action_sha256=binding.action_sha256,
        executor_id=binding.executor_id,
        intent_id=occurrence.intent_id,
        selection=SimpleNamespace(
            sources=(helper.SOURCE,),
            required_source_read_set=deepcopy(basis.required_source_read_set),
            valid_until=until,
        ),
    )
    engine = SimpleNamespace()
    s = Session()
    s.begin()  # Real SessionTransaction; no connection, flush or commit.
    monkeypatch.setattr(s, "get_bind", lambda: engine)
    owner = adapter.FormalChangeCompletionOwner(engine)
    state = SimpleNamespace(
        guard_sources=[], owner_calls=[], proofs=[], reject_owner=False, reject_guard=False
    )

    def scalars(statement):
        predicates = {p.left.name: p.right.value for p in statement._where_criteria}
        assert predicates == {
            "tenant_id": ctx.tenant_id,
            "product_id": basis.scope.product_id,
            "project_id": basis.scope.project_id,
            "change_id": request.id,
            "order_id": order.id,
            "item_id": item.id,
            "fact_id": occurrence.implementation_id,
            "executor_id": ctx.requester_id,
        }
        return [capture]

    def implementation_read(session, caller, pid, *, implementation_version_id):
        assert (session, caller, pid, implementation_version_id) == (
            s,
            ctx,
            basis.scope.product_id,
            row.id,
        )
        state.owner_calls.append("read")
        if state.reject_owner:
            raise DomainError("IMPLEMENTATION_OWNER_REQUIRED", "Actual owner rejected", 503)
        return executed

    def implementation_refresh(session, caller, pid, previous):
        assert (session, caller, previous) == (s, ctx, executed)
        state.owner_calls.append("refresh")
        return executed

    attest = owner.implementation.attest

    def implementation_attest(*args):
        proof = attest(*args)  # Actual attest seals the complete implementation material.
        state.proofs.append(proof)
        return proof

    def source_guard(session, caller, pid, visibility, owner_id, reads, sources, **kwargs):
        assert (session, caller, pid) == (s, ctx, basis.scope.product_id)
        state.guard_sources.append(tuple(sources))
        assert domain in sources and helper.SOURCE in sources
        assert reads == basis.required_source_read_set
        if state.reject_guard:
            raise DomainError("SOURCE_STALE", "Actual source closure rejected", 409)
        return {"full_sources": [v.model_dump(mode="json") for v in sources]}

    published = {
        "sources": (helper.SOURCE,),
        "required_source_read_set": basis.required_source_read_set,
    }
    authority = {"required_source_read_set": basis.required_source_read_set}
    monkeypatch.setattr(s, "scalars", scalars)
    monkeypatch.setattr(owner.implementation, "read", implementation_read)
    monkeypatch.setattr(owner.implementation, "refresh", implementation_refresh)
    monkeypatch.setattr(owner.implementation, "attest", implementation_attest)
    monkeypatch.setattr(owner.action_intent, "read", lambda *a, **k: selected)
    monkeypatch.setattr(owner.action_intent, "refresh", lambda *a, **k: selected)
    monkeypatch.setattr(adapter.change, "_runtime_stamp", lambda *_: "fixed-runtime")
    monkeypatch.setattr(adapter, "_is_occurrence", lambda *_: True)
    monkeypatch.setattr(adapter, "original_occurrence", lambda *_: (occurrence, None))
    monkeypatch.setattr(adapter, "_one", lambda *_: atom)
    monkeypatch.setattr(adapter, "current_fixed", lambda *_: (pointer, row))
    monkeypatch.setattr(adapter.controlled, "_caller", lambda *a, **k: ((ctx.actor_id,), until))
    monkeypatch.setattr(adapter.controlled, "_project", lambda *_: (None, (basis.scope,)))
    monkeypatch.setattr(adapter.controlled, "authority", lambda *a, **k: (authority, until))
    monkeypatch.setattr(adapter.controlled, "action_basis", lambda *_: (basis, binding))
    monkeypatch.setattr(adapter.controlled, "approved_order", lambda *_: until)
    monkeypatch.setattr(adapter.controlled, "_source_guard", source_guard)
    monkeypatch.setattr(adapter.policy, "assess", lambda *_: published)
    yield SimpleNamespace(
        s=s,
        ctx=ctx,
        basis=basis,
        binding=binding,
        owner=owner,
        completion=completion,
        published=published,
        executed=executed,
        domain=domain,
        state=state,
    )
    s.close()


def assess(work):
    return work.owner(
        work.s,
        work.ctx,
        work.basis.scope.product_id,
        work.basis,
        SimpleNamespace(id=work.binding.action_id),
        work.completion,
        policy_snapshot=work.published,
        observation=None,
    )


def test_formal_completion_projects_originals_after_full_domain_owner_proof(formal_sources):
    work = formal_sources
    value = assess(work)
    assert type(value) is CompletionAssessment and value.classification == "formal_change"
    assert [v.model_dump(mode="json") for v in value.sources] == [
        helper.SOURCE.model_dump(mode="json")
    ]
    assert len(work.state.guard_sources) == 3
    assert all(work.domain in sources for sources in work.state.guard_sources)
    assert work.state.owner_calls == ["read", "refresh", "refresh"]
    assert value.owner_proofs == tuple(work.state.proofs)
    proof = value.owner_proofs[0]
    assert (proof.id, proof.revision, proof.receipt_id, proof.sha256) == (
        work.executed.version.id,
        work.executed.version.revision,
        work.executed.receipt_id,
        adapter.digest(work.executed.material),
    )
    node_source = work.executed.material["version"]["assessments"][-1]["graph"]["nodes"][0][
        "source"
    ]
    assert node_source == work.domain.model_dump(mode="json")
    changed = deepcopy(work.executed.material)
    changed["version"]["assessments"][-1]["graph"]["nodes"][0]["source"]["revision"] += 1
    assert adapter.digest(changed) != proof.sha256
    assert value.proof_sha256 == adapter.digest(
        value.model_dump(mode="json", exclude={"proof_sha256"})
    )
    assert not work.s.new and not work.s.dirty and not work.s.deleted


@pytest.mark.parametrize("reject", ["owner", "guard"])
def test_actual_owner_or_source_rejection_cannot_produce_assessment(formal_sources, reject):
    work = formal_sources
    setattr(work.state, f"reject_{reject}", True)
    with pytest.raises(DomainError) as error:
        assess(work)
    assert error.value.reason == (
        "IMPLEMENTATION_OWNER_REQUIRED" if reject == "owner" else "SOURCE_STALE"
    )
    assert not work.state.proofs


def test_late_domain_source_closure_drift_rejects_before_assessment(formal_sources, monkeypatch):
    work = formal_sources
    original = adapter.controlled._source_guard

    def changed(*args, **kwargs):
        material = original(*args, **kwargs)
        if len(work.state.guard_sources) > 1:
            return {**material, "changed_domain_owner": True}
        return material

    monkeypatch.setattr(adapter.controlled, "_source_guard", changed)
    with pytest.raises(DomainError) as error:
        assess(work)
    assert error.value.reason == "SOURCE_STALE"
    assert len(work.state.guard_sources) == 2


def test_quality_guard_still_rejects_unbound_client_domain(formal_sources):
    work = formal_sources
    unknown = work.domain.model_copy(update={"id": uuid4()})
    with pytest.raises(DomainError) as error:
        followup.check_source(work.s, work.ctx, work.basis.scope.product_id, unknown)
    assert error.value.reason == "INTEGRATION_REQUIRED"
