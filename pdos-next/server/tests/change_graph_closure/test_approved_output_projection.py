"""Approved output growth keeps the original registry closure intact, without IO."""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next import change_graph_closure as closure
from pdos_next.change_implementation_owner import CaptureRead
from pdos_next.domain.change_coverage_owner import registry
from pdos_next.domain.change_execution import graph as graph_owner
from pdos_next.errors import DomainError
from pdos_next.schemas.change_control.contracts import (
    ChangeRequest,
    GraphSnapshot,
    ImplementationFact,
    Ref,
)

from . import test_closure as offline

case = offline.case  # Reuse the offline owner/Session fixture without importing its tests.


@pytest.fixture
def approved(case, monkeypatch):
    request = ChangeRequest(
        id=uuid4(),
        revision=1,
        scope=case.scope,
        audience=case.audience,
        requester_id=case.ctx.requester_id,
        title="Offline approved output change",
        reason="Check approved output projection without SQL or external IO.",
        roots=case.graph.roots,
        references=(),
        sources=case.graph.sources,
    )
    # Exercise the registry's actual owner-material digest producer, rather than
    # independently recreating the projection under test's hash formula.
    monkeypatch.setattr(
        registry,
        "OwnerReader",
        lambda s, ctx, pid, scope, audience, issue_loader: closure._reader(s, ctx, scope, audience),
    )
    basis = registry.read_registry(case.s, case.ctx, case.scope.product_id, request)
    assert basis.projection == registry.graph_projection(case.graph)
    case.state.reader_count = case.state.stamp_count = 0
    return SimpleNamespace(
        request=request,
        basis=basis,
        retained=SimpleNamespace(
            source_basis={"closure_sha256": basis.closure_sha256},
            valid_until=case.valid_until,
        ),
        command=case.command.model_copy(update={"operation": "change.implementation.record"}),
    )


def capture(case, outputs=(), *, outcome="succeeded", reconciles_id=None):
    at = datetime.now(UTC)
    fact = ImplementationFact(
        id=uuid4(),
        reconciles_id=reconciles_id,
        item_id=uuid4(),
        intent_id=uuid4(),
        executor_id=case.ctx.requester_id,
        outcome=outcome,
        occurred_at=at,
        received_at=at,
        sources=(case.source,),
        outputs=outputs,
        note="Offline approved-output closure boundary, not an execution attestation.",
        nature="synthetic",
    )
    return CaptureRead(row=None, fact=fact, occurrence=None, output_basis={})


def outputs(case):
    engineering = Ref(id=uuid4(), revision=1, kind="engineering_configuration")
    manufacturing = Ref(id=uuid4(), revision=1, kind="manufacturing_configuration")
    operation = Ref(id=manufacturing.id, revision=1, kind="operation", key="assembly")
    sop = Ref(id=manufacturing.id, revision=1, kind="sop", key="assembly")
    case.state.links[case.child.identity] = [(engineering, "工程版固定BOM物料")]
    case.state.links[engineering.identity] = [(manufacturing, "制造版固定工程版")]
    case.state.links[manufacturing.identity] = [(operation, "制造版固定工序")]
    case.state.links[operation.identity] = [(sop, "工序固定SOP")]
    return engineering, manufacturing, operation, sop


def rebuild(case):
    reader = closure._reader(case.s, case.ctx, case.scope, case.audience)
    graph = graph_owner.capture_graph(
        reader,
        identity=case.graph.id,
        roots=case.graph.roots,
        captured_at=case.graph.captured_at,
        expires_at=case.graph.expires_at,
        nature=case.graph.nature,
        sources=case.graph.sources,
    )
    return graph, reader


def run(case, approved, captures):
    return closure.recheck_implementation_closure(
        case.s,
        case.ctx,
        approved.command,
        request=approved.request,
        graph=case.graph,
        expected_closure=case.expected,
        captures=captures,
        retained_coverage=approved.retained,
    )


def reject(case, approved, captures):
    listeners = tuple(case.s.dispatch.do_orm_execute)
    with pytest.raises(DomainError) as error:
        run(case, approved, captures)
    assert error.value.reason == "RECHECK_REQUIRED"
    assert tuple(case.s.dispatch.do_orm_execute) == listeners
    return error.value


def test_real_registry_hash_accepts_only_declared_new_configurations_and_their_operations(
    case, approved
):
    original = deepcopy(case.graph.model_dump(mode="json"))
    engineering, manufacturing, operation, sop = outputs(case)
    extra_source = uuid4()
    case.state.reads[operation.identity] = [{"artifact_id": extra_source, "expected_revision": 2}]
    case.state.epoch += 1

    current, reader = rebuild(case)
    projected = closure.approved_projection(
        case.graph,
        current,
        reader,
        (engineering, manufacturing),
        approved.basis.closure_sha256,
    )
    assert closure.graph_material(projected) == closure.graph_material(case.graph)
    assert registry.graph_projection(projected) == approved.basis.projection
    assert {n.ref for n in current.nodes} - {n.ref for n in projected.nodes} == {
        engineering,
        manufacturing,
        operation,
        sop,
    }
    assert all(
        value.status == "unknown"
        for value in current.coverage
        if value.node in {engineering, manufacturing, operation, sop}
    )

    result = run(case, approved, (capture(case, (engineering,)), capture(case, (manufacturing,))))
    assert result.graph is case.graph
    assert case.graph.model_dump(mode="json") == original
    assert result.closure == {**case.expected, "dependency_epoch": case.state.epoch}
    assert result.authority_attested is False
    assert {r["artifact_id"] for r in result.required_source_read_set} == {
        str(case.source.id),
        str(extra_source),
    }


@pytest.mark.parametrize("drift", ["view", "reads", "source_basis"])
def test_same_topology_cannot_mask_original_owner_material_drift(
    case, approved, monkeypatch, drift
):
    engineering, manufacturing, *_ = outputs(case)
    if drift == "view":
        case.state.views[case.child.identity] = {"material_grade": "changed"}
    elif drift == "reads":
        case.state.reads[case.child.identity] = [
            {"artifact_id": case.source.id, "expected_revision": 2}
        ]
    else:
        factory = closure._reader

        def changed_reader(*args):
            reader = factory(*args)
            load = reader._load

            def changed_load(ref):
                row, view, reads, basis = load(ref)
                if ref == case.child:
                    basis = {**basis, "retained_owner": "changed"}
                return row, view, reads, basis

            reader._load = changed_load
            return reader

        monkeypatch.setattr(closure, "_reader", changed_reader)
    current, _ = rebuild(case)
    assert {n.ref for n in current.nodes} >= {n.ref for n in case.graph.nodes}
    reject(case, approved, (capture(case, (engineering, manufacturing)),))


@pytest.mark.parametrize("change", ["remove", "relation", "source"])
def test_original_edge_semantics_must_survive_projection(case, approved, change):
    engineering, manufacturing, *_ = outputs(case)
    current, reader = rebuild(case)
    original = current.edges[0]
    assert original.origin == case.root and original.target == case.child
    edges = tuple(e for e in current.edges if e != original)
    if change != "remove":
        update = (
            {"relation": "different dependency"}
            if change == "relation"
            else {"source": case.source}
        )
        edges = (original.model_copy(update=update), *edges)
    current = GraphSnapshot.model_validate({**current.model_dump(mode="python"), "edges": edges})
    with pytest.raises(DomainError) as error:
        closure.approved_projection(
            case.graph, current, reader, (engineering, manufacturing), approved.basis.closure_sha256
        )
    assert error.value.reason == "RECHECK_REQUIRED"


@pytest.mark.parametrize(
    "kind", ["build", "engineering_configuration", "manufacturing_configuration"]
)
def test_unapproved_reachable_objects_are_not_removed_as_output_growth(case, approved, kind):
    engineering, manufacturing, *_ = outputs(case)
    extra = Ref(id=uuid4(), revision=1, kind=kind)
    case.state.links[manufacturing.identity].append((extra, "new unapproved dependency"))
    reject(case, approved, (capture(case, (engineering, manufacturing)),))


def test_operations_of_another_manufacturing_revision_are_not_approved_children(case, approved):
    engineering, manufacturing, *_ = outputs(case)
    other_operation = Ref(id=manufacturing.id, revision=2, kind="operation", key="assembly")
    case.state.links[manufacturing.identity].append((other_operation, "different process revision"))
    reject(case, approved, (capture(case, (engineering, manufacturing)),))


def test_existing_configuration_cannot_be_reused_as_a_new_output(case, approved):
    reject(case, approved, (capture(case, (case.root,)),))


def test_build_output_cannot_expand_the_configuration_output_allowlist(case, approved):
    build = Ref(id=uuid4(), revision=1, kind="build")
    case.state.links[case.child.identity] = [(build, "new Build")]
    reject(case, approved, (capture(case, (build,)),))


@pytest.mark.parametrize("value", [None, "", "f" * 63])
def test_retained_coverage_requires_the_original_registry_owner_hash(case, approved, value):
    approved.retained.source_basis = {} if value is None else {"closure_sha256": value}
    reject(case, approved, (capture(case, outcome="unknown"),))


def test_hidden_new_dependency_cannot_disappear_during_bfs(case, approved):
    engineering, manufacturing, *_ = outputs(case)
    hidden = Ref(id=uuid4(), revision=1, kind="build")
    case.state.links[manufacturing.identity].append((hidden, "private actual dependency"))
    case.state.hidden.add(hidden.identity)
    error = reject(case, approved, (capture(case, (engineering, manufacturing)),))
    assert str(hidden.id) not in str(error)


@pytest.mark.parametrize("outcome", ["failed", "unknown"])
def test_no_output_may_record_failure_or_uncertainty_when_the_graph_stays_fixed(
    case, approved, outcome
):
    result = run(case, approved, (capture(case, outcome=outcome),))
    assert result.graph is case.graph and result.closure == case.expected


def test_no_output_does_not_authorize_any_graph_growth(case, approved):
    outputs(case)
    reject(case, approved, (capture(case, outcome="unknown"),))


def test_reconciliation_may_reference_the_same_actual_output_without_authorizing_more(
    case, approved
):
    engineering, manufacturing, *_ = outputs(case)
    first = capture(case, (engineering, manufacturing))
    reconciled = capture(case, (engineering, manufacturing), reconciles_id=first.fact.id)
    result = run(case, approved, (first, reconciled))
    assert result.graph is case.graph and result.closure == case.expected


def test_stale_original_owner_cannot_be_projected_away(case, approved, monkeypatch):
    engineering, manufacturing, *_ = outputs(case)
    factory = closure._reader

    def stale_reader(*args):
        reader = factory(*args)
        resolve = reader.resolve

        def stale_resolve(ref):
            obj = resolve(ref)
            if ref == case.child:
                obj = replace(obj, current=False)
                reader.objects[ref.identity] = obj
            return obj

        reader.resolve = stale_resolve
        return reader

    monkeypatch.setattr(closure, "_reader", stale_reader)
    reject(case, approved, (capture(case, (engineering, manufacturing)),))
