"""Native completion extends a frozen graph only with exact owner-read objects."""

import socket
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from change_graph_closure.test_approved_output_projection import (
    approved as approved_fixture,
)
from change_graph_closure.test_approved_output_projection import capture, outputs, rebuild
from change_graph_closure.test_closure import case as closure_case
from pydantic import ValidationError
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from pdos_next import change_completion_closure as completion
from pdos_next import change_completion_owner as native
from pdos_next import change_graph_closure as closure
from pdos_next.change_completion_schemas import (
    ClosePayload,
    CompletionMaterial,
    EffectivityPayload,
    VerificationPayload,
)
from pdos_next.errors import DomainError
from pdos_next.schemas.change_control.contracts import EffectivityFact, Ref

case = closure_case
approved = approved_fixture


@pytest.fixture(autouse=True)
def no_io(monkeypatch):
    def deny(*_args, **_kwargs):
        pytest.fail("Native completion pure checks must never access SQL or network")

    for cls, name in ((Engine, "connect"), (Engine, "raw_connection"), (Session, "execute")):
        monkeypatch.setattr(cls, name, deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(psycopg, "connect", deny)


@pytest.fixture
def chain(case, approved, monkeypatch):
    engineering, manufacturing, *_ = outputs(case)
    build = Ref(kind="build", id=uuid4(), revision=1)
    sample = Ref(kind="sample", id=uuid4(), revision=1)
    run = Ref(kind="test_run", id=uuid4(), revision=3)
    case.state.links[manufacturing.identity].append((build, "actual successor Build"))
    case.state.links[build.identity] = [(sample, "actual identified sample")]
    case.state.links[sample.identity] = [(run, "actual measured Run")]
    captured = capture(case, (engineering, manufacturing))
    fact = EffectivityFact(
        id=uuid4(),
        item_id=captured.fact.item_id,
        intent_id=captured.fact.intent_id,
        stage="effective",
        outcome="succeeded",
        covered_units=(f"object:{case.root.identity}",),
        conditions_digest="a" * 64,
        occurred_at=captured.fact.occurred_at,
        received_at=captured.fact.received_at,
        sources=(case.source,),
        output_refs=captured.fact.outputs,
        system="offline-native-reader",
        external_id="event-1",
        nature="synthetic",
    )
    owned = SimpleNamespace(actual_refs=(build, sample, run))
    read = native.CompletionRead(fact, object(), owned)
    # The imported alias must use the same offline actual-owner fixture. All
    # production projection, topology, source, material and Session guards run.
    monkeypatch.setattr(completion, "_reader", closure._reader)
    return SimpleNamespace(
        engineering=engineering,
        manufacturing=manufacturing,
        build=build,
        sample=sample,
        run=run,
        captured=captured,
        read=read,
        owner=owned,
        command=case.command.model_copy(update={"operation": "change.effectivity.record"}),
    )


def recheck(case, approved, chain, **changes):
    values = {
        "request": approved.request,
        "graph": case.graph,
        "expected_closure": case.expected,
        "captures": (chain.captured,),
        "completion": (chain.read,),
        "retained_coverage": approved.retained,
    }
    values.update(changes)
    return completion.recheck_completion_closure(case.s, case.ctx, chain.command, **values)


def rejected(call):
    with pytest.raises(DomainError) as error:
        call()
    assert error.value.reason == "RECHECK_REQUIRED"
    return error.value


def test_exact_native_objects_extend_current_reads_without_inheriting_approval(
    case, approved, chain
):
    extra_source = uuid4()
    case.state.reads[chain.run.identity] = [{"artifact_id": extra_source, "expected_revision": 2}]
    case.state.epoch += 1
    original = deepcopy(case.graph.model_dump(mode="json"))
    current, reader = rebuild(case)
    projected = closure.approved_projection(
        case.graph,
        current,
        reader,
        chain.captured.fact.outputs,
        approved.basis.closure_sha256,
        native_refs=chain.owner.actual_refs,
    )
    assert closure.graph_material(projected) == closure.graph_material(case.graph)
    assert all(c.status == "unknown" for c in current.coverage if c.node in chain.owner.actual_refs)
    result = recheck(case, approved, chain)
    assert result.graph is case.graph
    assert result.authority_attested is False
    assert result.closure["dependency_epoch"] == case.state.epoch
    assert {read["artifact_id"] for read in result.required_source_read_set} == {
        str(case.source.id),
        str(extra_source),
    }
    assert case.graph.model_dump(mode="json") == original


@pytest.mark.parametrize("kind", ["build", "sample", "test_run"])
def test_unlisted_new_dependency_is_not_approved_by_another_actual_native_object(
    case, approved, chain, kind
):
    extra = Ref(kind=kind, id=uuid4(), revision=1)
    case.state.links[chain.build.identity].append((extra, "unrelated newly reachable dependency"))
    error = rejected(lambda: recheck(case, approved, chain))
    assert str(extra.id) not in str(error)


def bound_descendants(case, chain):
    sample = Ref(kind="sample", id=uuid4(), revision=1)
    run = Ref(kind="test_run", id=uuid4(), revision=4)
    case.state.links[chain.build.identity].append((sample, "additional actual identified sample"))
    case.state.links[sample.identity] = [(run, "current actual Run uses the sample")]
    case.state.views[sample.identity] = {"build_id": str(chain.build.id)}
    case.state.views[run.identity] = {"build": {"id": str(chain.build.id)}}
    return sample, run


def test_bound_actual_descendants_may_precede_adoption_registration_without_proving_verification(
    case, approved, chain
):
    sample, run = bound_descendants(case, chain)
    extra_source = uuid4()
    case.state.reads[run.identity] = [{"artifact_id": extra_source, "expected_revision": 1}]
    original = deepcopy(approved.request.model_dump(mode="json"))
    current, reader = rebuild(case)
    included = completion.native_dependency_refs(
        case.graph, current, reader, chain.owner.actual_refs
    )
    assert {sample, run} <= set(included)
    assert sample not in chain.owner.actual_refs and run not in chain.owner.actual_refs
    result = recheck(case, approved, chain)
    assert str(extra_source) in {read["artifact_id"] for read in result.required_source_read_set}
    assert type(chain.read.fact) is EffectivityFact
    assert result.authority_attested is False
    assert approved.request.model_dump(mode="json") == original
    assert not approved.request.orders


@pytest.mark.parametrize("kind", ["sample", "test_run"])
@pytest.mark.parametrize("binding", ["other_build", "missing_build", "wrong_shape"])
def test_native_descendants_require_the_actual_owner_build_binding(
    case, approved, chain, kind, binding
):
    sample, run = bound_descendants(case, chain)
    target = sample if kind == "sample" else run
    wrong = str(uuid4())
    if binding == "other_build":
        view = {"build_id": wrong} if kind == "sample" else {"build": {"id": wrong}}
    elif binding == "missing_build":
        view = {}
    else:
        # A guessed identifier in a different field is not the native owner's contract.
        view = (
            {"build": {"id": str(chain.build.id)}}
            if kind == "sample"
            else {"build_id": str(chain.build.id)}
        )
    case.state.views[target.identity] = view
    current, reader = rebuild(case)
    included = completion.native_dependency_refs(
        case.graph, current, reader, chain.owner.actual_refs
    )
    assert target not in included
    rejected(lambda: recheck(case, approved, chain))


def test_another_actual_build_is_not_admitted_with_its_own_bound_descendants(case, approved, chain):
    other_build = Ref(kind="build", id=uuid4(), revision=1)
    other_sample = Ref(kind="sample", id=uuid4(), revision=1)
    case.state.links[chain.build.identity].append((other_build, "unapproved other Build"))
    case.state.links[other_build.identity] = [(other_sample, "sample of another Build")]
    case.state.views[other_sample.identity] = {"build_id": str(other_build.id)}
    current, reader = rebuild(case)
    included = completion.native_dependency_refs(
        case.graph, current, reader, chain.owner.actual_refs
    )
    assert other_build not in included and other_sample not in included
    rejected(lambda: recheck(case, approved, chain))


@pytest.mark.parametrize("kind", ["sample", "test_run"])
@pytest.mark.parametrize("failure", ["owner_missing", "not_current"])
def test_bound_descendant_requires_a_real_current_owner_read(case, approved, chain, kind, failure):
    sample, run = bound_descendants(case, chain)
    target = sample if kind == "sample" else run
    current, reader = rebuild(case)
    if failure == "owner_missing":
        del reader.objects[target.identity]
    else:
        reader.objects[target.identity] = replace(reader.objects[target.identity], current=False)
    rejected(
        lambda: completion.native_dependency_refs(
            case.graph, current, reader, chain.owner.actual_refs
        )
    )


def test_original_build_reference_does_not_grant_scope_to_later_descendants(case):
    old_build = Ref(kind="build", id=uuid4(), revision=1)
    case.state.links[case.child.identity] = [(old_build, "original fixed Build")]
    baseline, _ = rebuild(case)
    sample = Ref(kind="sample", id=uuid4(), revision=1)
    case.state.links[old_build.identity] = [(sample, "new sample of the original Build")]
    case.state.views[sample.identity] = {"build_id": str(old_build.id)}
    current, reader = rebuild(case)
    included = completion.native_dependency_refs(baseline, current, reader, (old_build,))
    assert included == (old_build,)
    assert sample not in included


def test_native_reference_is_exact_version_not_an_identity_allowlist(case, approved, chain):
    chain.owner.actual_refs = (
        chain.build,
        chain.sample,
        chain.run.model_copy(update={"revision": chain.run.revision + 1}),
    )
    rejected(lambda: recheck(case, approved, chain))


def test_listed_but_unread_native_object_is_not_a_permitted_graph_growth(case, approved, chain):
    chain.owner.actual_refs = (*chain.owner.actual_refs, Ref(kind="build", id=uuid4(), revision=1))
    rejected(lambda: recheck(case, approved, chain))


def test_even_listed_native_hidden_node_is_not_silently_projected_away(case, approved, chain):
    case.state.hidden.add(chain.run.identity)
    listeners = tuple(case.s.dispatch.do_orm_execute)
    error = rejected(lambda: recheck(case, approved, chain))
    assert str(chain.run.id) not in str(error)
    assert tuple(case.s.dispatch.do_orm_execute) == listeners


@pytest.mark.parametrize("drift", ["view", "reads", "source_basis"])
def test_native_growth_keeps_original_owner_material_binding(
    case, approved, chain, monkeypatch, drift
):
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
                return (
                    row,
                    view,
                    reads,
                    ({**basis, "retained_owner": "changed"} if ref == case.child else basis),
                )

            reader._load = changed_load
            return reader

        monkeypatch.setattr(completion, "_reader", changed_reader)
    rejected(lambda: recheck(case, approved, chain))


@pytest.mark.parametrize("change", ["remove", "relation"])
def test_approved_native_chain_does_not_authorize_old_topology_changes(
    case, approved, chain, change
):
    if change == "remove":
        case.state.links[case.root.identity] = []
    else:
        case.state.links[case.root.identity] = [(case.child, "changed original relationship")]
    rejected(lambda: recheck(case, approved, chain))


def test_implementation_default_remains_exact_without_native_completion_refs(case, approved, chain):
    current, reader = rebuild(case)
    rejected(
        lambda: closure.approved_projection(
            case.graph,
            current,
            reader,
            chain.captured.fact.outputs,
            approved.basis.closure_sha256,
        )
    )
    rejected(
        lambda: closure.recheck_implementation_closure(
            case.s,
            case.ctx,
            approved.command,
            request=approved.request,
            graph=case.graph,
            expected_closure=case.expected,
            captures=(chain.captured,),
            retained_coverage=approved.retained,
        )
    )
    # Removing actual native growth restores the existing implementation route.
    case.state.links[chain.manufacturing.identity] = [
        (ref, relation)
        for ref, relation in case.state.links[chain.manufacturing.identity]
        if ref != chain.build
    ]
    result = closure.recheck_implementation_closure(
        case.s,
        case.ctx,
        approved.command,
        request=approved.request,
        graph=case.graph,
        expected_closure=case.expected,
        captures=(chain.captured,),
        retained_coverage=approved.retained,
    )
    assert result.graph is case.graph and result.closure == case.expected


def test_plain_client_claim_cannot_replace_completion_owner_read(case, approved, chain):
    claimed = SimpleNamespace(fact=chain.read.fact, owner=chain.owner)
    rejected(lambda: recheck(case, approved, chain, completion=(claimed,)))


def effectivity_input():
    return {
        "change_id": uuid4(),
        "expected_change_revision": 4,
        "visibility": "category",
        "item_id": uuid4(),
        "lot": {"id": uuid4(), "revision": 1},
        "sample_refs": [Ref(kind="sample", id=uuid4(), revision=1).model_dump()],
    }


@pytest.mark.parametrize(
    "claimed",
    [
        {"outcome": "succeeded"},
        {"stage": "effective"},
        {"current": True},
        {"applicable": True},
        {"nature": "real"},
        {"fact_id": uuid4()},
        {"occurred_at": datetime.now(UTC).isoformat()},
        {"output_refs": []},
    ],
)
def test_effectivity_payload_cannot_supply_business_fact_flags(claimed):
    with pytest.raises(ValidationError):
        EffectivityPayload.model_validate({**effectivity_input(), **claimed})


def verification_input():
    value = effectivity_input()
    return {key: value[key] for key in ("change_id", "expected_change_revision", "visibility")} | {
        "text": "Review actual new Run raw values",
        "mappings": [
            {
                "item_id": value["item_id"],
                "run": Ref(kind="test_run", id=uuid4(), revision=3),
                "sample_id": value["sample_refs"][0]["id"],
                "test_item_id": "dimension",
                "method": {"id": uuid4(), "revision": 1, "kind": "artifact", "position": "line:1"},
                "requirement_sha256": "a" * 64,
                "rationale": "Maps the approved verification requirement",
            }
        ],
    }


@pytest.mark.parametrize(
    "claimed",
    [
        {"result": "pass"},
        {"verifier_id": uuid4()},
        {"executor_ids": []},
        {"current": True},
        {"applicable": True},
        {"nature": "real"},
        {"observed_from": datetime.now(UTC).isoformat()},
    ],
)
def test_verification_payload_cannot_attest_result_participants_or_currentness(claimed):
    with pytest.raises(ValidationError):
        VerificationPayload.model_validate({**verification_input(), **claimed})


def test_adoption_fact_identity_stays_fixed_for_same_native_occurrence():
    value = effectivity_input()
    value["sample_refs"].append(Ref(kind="sample", id=uuid4(), revision=1).model_dump())
    payload = EffectivityPayload.model_validate(value)
    order, actor = SimpleNamespace(id=uuid4()), uuid4()
    identity = native.fact_id(payload, order, actor)
    changed = payload.model_copy(
        update={
            "sample_refs": tuple(reversed(payload.sample_refs)),
            "expected_change_revision": 99,
            "confirmation_token": "x" * 20,
        }
    )
    assert native.fact_id(changed, order, uuid4()) == identity
    assert native.fact_id(payload.model_copy(update={"item_id": uuid4()}), order, actor) != identity
    assert native.fact_id(payload, SimpleNamespace(id=uuid4()), actor) != identity


def test_material_kind_and_operation_are_exact_and_do_not_accept_existing_proof():
    payload = EffectivityPayload.model_validate(effectivity_input())
    value = CompletionMaterial(operation="change.effectivity.record", payload=payload)
    assert type(value.payload) is EffectivityPayload
    with pytest.raises(ValidationError):
        CompletionMaterial(operation="change.close", payload=payload)
    with pytest.raises(ValidationError):
        CompletionMaterial(
            operation="change.effectivity.record",
            payload=payload.model_copy(update={"confirmation_token": "x" * 20}),
        )
    close = ClosePayload.model_validate(
        {
            "change_id": payload.change_id,
            "expected_change_revision": 4,
            "text": "Close after pass",
        }
    )
    with pytest.raises(ValidationError):
        ClosePayload.model_validate({**close.model_dump(), "passed": True})
