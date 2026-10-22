"""Offline contracts for native development adoption, with no DB/network access."""

import hashlib
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import httpx
import psycopg
import pytest
from sqlalchemy.engine import Engine

from pdos_next import change_build_adoption as adoption
from pdos_next.domain.change_control.rules import digest
from pdos_next.errors import DomainError
from pdos_next.schemas.change_control.contracts import ImplementationFact, Ref
from pdos_next.schemas.verification.contracts import SourceRef

from . import kernel_helpers as helper


@pytest.fixture(autouse=True)
def no_connections(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Native adoption pure checks must not access DB or network")

    for cls, name in ((Engine, "connect"), (Engine, "raw_connection"), (httpx.Client, "request")):
        monkeypatch.setattr(cls, name, deny)
    monkeypatch.setattr(psycopg, "connect", deny)


@pytest.fixture
def case(monkeypatch):
    host = helper.FakeHost()
    host.approve()
    now = helper.NOW
    old_ref = helper.ref("build", "explicit-previous")
    old_config = helper.ref("engineering_configuration")
    output = helper.ref("engineering_configuration", "new-engineering")
    manufacturing = helper.ref("manufacturing_configuration", "new-manufacturing")
    feedback = helper.ref("field_feedback")
    artifact_id = helper.uid("adoption-actual-source")
    line = "native actual observation, limited to this Build"
    source = SourceRef(
        id=artifact_id,
        revision=1,
        kind="artifact",
        position=f"line:1;quote_sha256:{hashlib.sha256(line.encode()).hexdigest()}",
    )
    definition_source = {
        "artifact_id": str(artifact_id),
        "expected_revision": 1,
        "line": 1,
        "quote": "actual observation",
    }
    reads = [{"artifact_id": str(artifact_id), "expected_revision": 1}]
    item = host.order.plan.items[0]
    item = item.model_copy(
        update={
            "selection": item.selection.model_copy(
                update={
                    "objects": (old_config,),
                    "units": (f"object:{old_config.identity}",),
                    "conditions": (adoption.DEVELOPMENT_BUILD_ADOPTION_CONDITION,),
                    "sources": (source,),
                }
            ),
            "intent": item.intent.model_copy(update={"basis": (old_config, old_ref)}),
        }
    )
    implementation = ImplementationFact(
        id=helper.uid("adoption-implementation"),
        item_id=item.id,
        intent_id=item.intent.id,
        executor_id=helper.uid("executor"),
        outcome="succeeded",
        occurred_at=now,
        received_at=now,
        sources=(source,),
        outputs=(output,),
        note="Native new output",
        nature="synthetic",
    )
    order = host.order.model_copy(
        update={
            "plan": host.order.plan.model_copy(
                update={
                    "items": (item,),
                    "dispositions": tuple(
                        disposition
                        if set(disposition.item_ids) <= {item.id}
                        else disposition.model_copy(
                            update={"handling": "reviewed_no_change", "item_ids": ()}
                        )
                        for disposition in host.order.plan.dispositions
                    ),
                }
            ),
            "implementations": (implementation,),
        }
    )
    request = host.request_value.model_copy(
        update={
            "roots": (feedback,),
            "references": (),
            "sources": (source,),
            "orders": (order,),
            "status": "implementing",
        }
    )
    ctx = SimpleNamespace(
        tenant_id=request.scope.tenant_id,
        requester_id=helper.uid("reader"),
        category_id=helper.uid("category"),
    )

    def row(name, **fields):
        return SimpleNamespace(
            id=helper.uid(name),
            revision=1,
            tenant_id=request.scope.tenant_id,
            product_id=request.scope.product_id,
            project_id=request.scope.project_id,
            owner_id=ctx.requester_id,
            visibility="category",
            **fields,
        )

    def view(value, **fields):
        return {
            "id": str(value.id),
            "revision": value.revision,
            "source_status": "current",
            "required_source_read_set": deepcopy(reads),
            "sources": [deepcopy(definition_source)],
            **fields,
        }

    previous = row("explicit-previous", purpose="development", unit="ea")
    successor = row(
        "actual-successor",
        purpose="development",
        unit="ea",
        previous_build_id=previous.id,
        engineering_configuration_id=output.id,
        manufacturing_configuration_id=manufacturing.id,
    )
    actual = row(
        "actual-config",
        build_id=successor.id,
        build_revision=1,
        actual_engineering_configuration_id=output.id,
        actual_engineering_revision=1,
        actual_manufacturing_configuration_id=manufacturing.id,
        actual_manufacturing_revision=1,
        observed_at=now + timedelta(minutes=1),
        differences=[],
    )
    lot = row(
        "actual-lot",
        build_id=successor.id,
        build_revision=1,
        actual_configuration_id=actual.id,
        actual_configuration_revision=1,
        occurred_at=now + timedelta(minutes=3),
        received_at=now + timedelta(minutes=4),
        created_at=now + timedelta(minutes=4),
        observation_nature="synthetic",
        observed_unit_count=2,
        unit="ea",
    )
    sample = row(
        "actual-sample",
        build_id=successor.id,
        build_revision=1,
        lot_id=lot.id,
        actual_configuration_id=actual.id,
    )
    start = row(
        "actual-start",
        build_id=successor.id,
        build_revision=1,
        occurred_at=now + timedelta(minutes=2),
        engineering_configuration_id=output.id,
        manufacturing_configuration_id=manufacturing.id,
    )
    actual_view = view(
        actual,
        build_id=str(successor.id),
        actual_engineering_configuration_id=str(output.id),
        actual_engineering_revision=1,
        actual_manufacturing_configuration_id=str(manufacturing.id),
        actual_manufacturing_revision=1,
        observed_at=actual.observed_at.isoformat(),
        differences=[],
    )
    lot_view = view(
        lot,
        build_id=str(successor.id),
        actual_configuration_id=str(actual.id),
        actual_configuration_revision=1,
        lot_label="fixed-lot",
        observed_unit_count=2,
        unit="ea",
        observation={
            "system": "actual-source",
            "external_id": "event-1",
            "nature": "synthetic",
            "occurred_at": lot.occurred_at.isoformat(),
            "received_at": lot.received_at.isoformat(),
        },
    )
    sample_view = view(
        sample,
        build_id=str(successor.id),
        lot_id=str(lot.id),
        allocation_id=str(helper.uid("allocation")),
        label="fixed-sample",
        actual_configuration_id=str(actual.id),
        actual_configuration_revision=1,
        observation_nature="synthetic",
    )
    start_view = view(start, build_id=str(successor.id), snapshot_sha256="a" * 64)
    projection = {
        "execution_status": "executing",
        "execution_qualification": "limited_current",
        "stop_required": False,
        "required_source_read_set": deepcopy(reads),
        "current_result": {"fixed_execution": True, "nature": "synthetic"},
    }
    artifacts = {artifact_id: row("adoption-actual-source", content=line)}
    calls = []

    def get_build(_s, _ctx, _pid, identity):
        calls.append(("build", identity))
        return {previous.id: previous, successor.id: successor}[identity]

    def linked(_s, _ctx, _pid, value):
        if value.id == previous.id:
            return (
                None,
                {"id": str(old_config.id), "revision": 1, "source_status": "current"},
                {
                    "id": str(helper.uid("old-process")),
                    "revision": 1,
                    "source_status": "current",
                },
                reads,
            )
        return (
            None,
            {"id": str(output.id), "revision": 1, "source_status": "current"},
            {
                "id": str(manufacturing.id),
                "revision": 1,
                "source_status": "current",
            },
            reads,
        )

    field_row = row("field-version")
    monkeypatch.setattr(
        adoption.field_bridge,
        "get",
        lambda *_: (
            field_row,
            {"required_source_read_set": reads, "sources": [source.model_dump(mode="json")]},
            request.scope,
            "development",
        ),
    )
    monkeypatch.setattr(adoption.builds, "_build", get_build)
    monkeypatch.setattr(adoption.builds, "_linked", linked)
    monkeypatch.setattr(adoption.physical, "get_lot", lambda *_: (lot, lot_view))
    monkeypatch.setattr(
        adoption.physical, "get_actual_configuration", lambda *_: (actual, actual_view)
    )
    monkeypatch.setattr(adoption.physical, "get_sample", lambda *_: (sample, sample_view))
    monkeypatch.setattr(adoption.execution, "execution_projection", lambda *_: projection)
    monkeypatch.setattr(adoption.execution, "_start", lambda *_: start)
    monkeypatch.setattr(adoption.execution, "_view", lambda *_: start_view)
    monkeypatch.setattr(
        adoption, "source_for", lambda _s, _ctx, _pid, identity, _rev: artifacts[identity]
    )
    return SimpleNamespace(**locals())


def read(value, **changes):
    args = {
        "fact_id": helper.uid("derived-adoption-fact"),
        "lot_id": value.lot.id,
        "lot_revision": 1,
        "sample_refs": (Ref(kind="sample", id=value.sample.id, revision=1),),
    }
    args.update(changes)
    return adoption.read_adoption(
        object(),
        value.ctx,
        value.request.scope.product_id,
        value.request,
        value.order,
        value.item,
        value.implementation,
        **args,
    )


@contextmanager
def rejected(reason):
    with pytest.raises(DomainError) as error:
        yield error
    assert error.value.reason == reason


def revise_item(value, **changes):
    value.item = value.item.model_copy(update=changes)
    value.order = value.order.model_copy(
        update={"plan": value.order.plan.model_copy(update={"items": (value.item,)})}
    )
    value.request = value.request.model_copy(update={"orders": (value.order,)})


def test_native_adoption_requires_actual_chain_and_retains_exact_replay(case):
    first, second = read(case), read(case)
    assert first == second
    fact = first.fact
    assert fact.stage == "effective" and fact.outcome == "succeeded"
    assert fact.occurred_at == case.lot.occurred_at
    assert fact.received_at == case.lot.created_at
    assert fact.output_refs == case.implementation.outputs
    assert fact.covered_units == case.item.selection.units
    assert fact.conditions_digest == digest(case.item.selection)
    assert first.sources == (case.source,)
    assert first.verified_domain_sources == ()
    assert {r.kind for r in first.actual_refs} == {"build", "engineering_configuration", "sample"}
    assert first.required_source_read_set == case.reads
    assert first.source_basis["lot"]["id"] == str(case.lot.id)
    assert first.source_basis["start"]["id"] == str(case.start.id)


def test_explicit_late_reception_is_fixed_without_changing_actual_occurrence(case):
    reception = case.lot.created_at + timedelta(hours=1)
    assert read(case, received_at=reception).fact.received_at == reception
    assert read(case, received_at=reception).fact.occurred_at == case.lot.occurred_at


def test_one_actual_lot_can_prove_two_distinct_approved_configuration_adoptions(case):
    """Native item occurrences must not collide as a duplicated external receipt."""
    old = helper.ref("manufacturing_configuration", "old-process")
    manufacturing = case.item.model_copy(
        update={
            "id": helper.uid("manufacturing-item"),
            "discipline": "manufacturing",
            "selection": case.item.selection.model_copy(
                update={"objects": (old,), "units": (f"object:{old.identity}",)}
            ),
            "intent": case.item.intent.model_copy(
                update={
                    "id": helper.uid("manufacturing-intent"),
                    "kind": "new_manufacturing_configuration",
                    "basis": (old, case.old_ref),
                }
            ),
        }
    )
    implementation = case.implementation.model_copy(
        update={
            "id": helper.uid("manufacturing-implementation"),
            "item_id": manufacturing.id,
            "intent_id": manufacturing.intent.id,
            "outputs": (case.manufacturing,),
        }
    )
    case.order = case.order.model_copy(
        update={
            "plan": case.order.plan.model_copy(update={"items": (case.item, manufacturing)}),
            "implementations": (case.implementation, implementation),
        }
    )
    case.request = case.request.model_copy(update={"orders": (case.order,)})
    engineering = read(case).fact
    other = adoption.read_adoption(
        object(),
        case.ctx,
        case.request.scope.product_id,
        case.request,
        case.order,
        manufacturing,
        implementation,
        fact_id=helper.uid("manufacturing-adoption-fact"),
        lot_id=case.lot.id,
        lot_revision=1,
        sample_refs=(Ref(kind="sample", id=case.sample.id, revision=1),),
    ).fact
    assert engineering.external_id != other.external_id
    assert engineering.occurred_at == other.occurred_at == case.lot.occurred_at
    host = case.host
    host.requests[host.subject] = case.request
    host.implementations.update({v.id: v for v in case.order.implementations})
    host.effectivities.update({engineering.id: engineering, other.id: other})
    host.authority = host.authority.model_copy(
        update={"now": helper.NOW + timedelta(minutes=4, seconds=30)}
    )
    host.run("change.effectivity.record", {"item_id": case.item.id, "fact_id": engineering.id})
    assert host.request_value.status == "implementing"
    host.run("change.effectivity.record", {"item_id": manufacturing.id, "fact_id": other.id})
    assert host.request_value.status == "verifying"


@pytest.mark.parametrize(
    "conditions",
    [
        ("generic future plan",),
        (),
        (
            adoption.DEVELOPMENT_BUILD_ADOPTION_CONDITION,
            "unproved additional condition",
        ),
    ],
)
def test_generic_or_additional_conditions_are_not_declared_satisfied(case, conditions):
    revise_item(case, selection=case.item.selection.model_copy(update={"conditions": conditions}))
    with rejected("EFFECTIVITY_SCOPE_MISMATCH"):
        read(case)


@pytest.mark.parametrize("kind", ["new_build", "new_test_run", "erp_mes_effectivity"])
def test_other_intents_do_not_gain_native_configuration_effectivity(case, kind):
    revise_item(case, intent=case.item.intent.model_copy(update={"kind": kind}))
    with rejected("EFFECTIVITY_SCOPE_MISMATCH"):
        read(case)


def test_previous_build_must_be_an_explicit_exact_basis(case):
    revise_item(case, intent=case.item.intent.model_copy(update={"basis": (case.old_config,)}))
    with rejected("EFFECTIVITY_SCOPE_MISMATCH"):
        read(case)


@pytest.mark.parametrize("unit", ["batch:unproved", "serial:unproved", "object:guessed-uuid"])
def test_unit_scope_never_expands_or_guesses_batch_serial(case, unit):
    revise_item(case, selection=case.item.selection.model_copy(update={"units": (unit,)}))
    with rejected("EFFECTIVITY_SCOPE_MISMATCH"):
        read(case)


@pytest.mark.parametrize(
    "drift",
    [
        "previous",
        "purpose",
        "lot_version",
        "actual_version",
        "actual_config",
        "actual_difference",
        "sample_lot",
        "sample_config",
        "sample_version",
        "nature",
    ],
)
def test_wrong_native_binding_or_nature_fails_closed(case, drift):
    kwargs = {}
    if drift == "previous":
        case.successor.previous_build_id = helper.uid("unrelated-build")
    elif drift == "purpose":
        case.successor.purpose = "unapproved production purpose"
    elif drift == "lot_version":
        kwargs["lot_revision"] = 2
    elif drift == "actual_version":
        case.actual.revision = 2
    elif drift == "actual_config":
        case.actual.actual_engineering_configuration_id = case.old_config.id
    elif drift == "actual_difference":
        case.actual.differences = [{"path": "unknown", "reason": "deviation"}]
    elif drift == "sample_lot":
        case.sample.lot_id = helper.uid("unrelated-lot")
    elif drift == "sample_config":
        case.sample.actual_configuration_id = helper.uid("unrelated-config")
    elif drift == "sample_version":
        kwargs["sample_refs"] = (Ref(kind="sample", id=case.sample.id, revision=2),)
    else:
        case.lot.observation_nature = "real"
    with pytest.raises(DomainError):
        read(case, **kwargs)


@pytest.mark.parametrize(
    "projection",
    [
        None,
        {},
        {"stop_required": True},
        {
            "execution_qualification": "needs_recheck",
        },
        {"execution_status": "planned"},
    ],
)
def test_planned_or_revoked_execution_does_not_prove_adoption(case, monkeypatch, projection):
    value = {**case.projection, **projection} if projection is not None else None
    if projection == {}:
        value = {}
    monkeypatch.setattr(adoption.execution, "execution_projection", lambda *_: value)
    with rejected("BUILD_OPERATIONAL_NOT_READY"):
        read(case)


@pytest.mark.parametrize("which", ["lot_view", "actual_view", "sample_view", "start_view"])
def test_withdrawn_native_sources_block_new_use(case, which):
    getattr(case, which)["source_status"] = "needs_recheck"
    with rejected("RECHECK_REQUIRED"):
        read(case)


def test_source_owner_acl_failure_propagates_without_hiding_history_requirement(case, monkeypatch):
    def denied(*_args):
        raise DomainError("SOURCE_UNAVAILABLE", "Actual source is not readable", 403)

    monkeypatch.setattr(adoption, "source_for", denied)
    with rejected("SOURCE_UNAVAILABLE") as error:
        read(case)
    assert error.value.status == 403


def test_artifact_row_is_rechecked_against_actual_native_source_quote(case):
    case.artifacts[case.artifact_id].content = "corrected source excludes original quote"
    with rejected("SOURCE_STALE"):
        read(case)


def test_native_execution_nature_cannot_be_inferred_from_lot_declaration(case):
    case.projection["current_result"]["nature"] = "real"
    with rejected("FACT_NATURE_MISMATCH"):
        read(case)


def test_native_source_versions_must_form_one_exact_read_set(case):
    case.actual_view["required_source_read_set"][0]["expected_revision"] = 2
    with rejected("SOURCE_STALE"):
        read(case)


def test_private_artifact_use_cannot_be_widened_to_shared_adoption(case):
    case.artifacts[case.artifact_id].visibility = "private"
    with rejected("AUDIENCE_USE_FORBIDDEN"):
        read(case)


def test_private_native_evidence_cannot_be_widened_to_shared_change(case):
    case.sample.visibility = "private"
    with rejected("AUDIENCE_USE_FORBIDDEN"):
        read(case)


@pytest.mark.parametrize("which", ["start", "actual", "implementation", "reception"])
def test_adoption_time_is_an_actual_post_implementation_occurrence(case, which):
    later = case.lot.occurred_at + timedelta(seconds=1)
    kwargs = {}
    if which == "start":
        case.start.occurred_at = later
    elif which == "actual":
        case.actual.observed_at = later
    elif which == "implementation":
        case.implementation = case.implementation.model_copy(update={"occurred_at": later})
        case.order = case.order.model_copy(update={"implementations": (case.implementation,)})
        case.request = case.request.model_copy(update={"orders": (case.order,)})
    else:
        kwargs["received_at"] = case.lot.occurred_at - timedelta(seconds=1)
    with rejected("INVALID_EVENT_TIME"):
        read(case, **kwargs)


def test_samples_must_be_actual_explicit_same_lot_identities(case):
    with rejected("EFFECTIVITY_SCOPE_MISMATCH"):
        read(case, sample_refs=())
    ref = Ref(kind="sample", id=case.sample.id, revision=1)
    with rejected("EFFECTIVITY_SCOPE_MISMATCH"):
        read(case, sample_refs=(ref, ref))


def test_unimplemented_configuration_creation_cannot_become_adoption(case):
    case.order = case.order.model_copy(update={"implementations": ()})
    case.request = case.request.model_copy(update={"orders": (case.order,)})
    with rejected("IMPLEMENTATION_INCOMPLETE"):
        read(case)
