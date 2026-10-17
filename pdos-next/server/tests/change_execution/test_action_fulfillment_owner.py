"""Uninstalled action adapter with real DTO/ORM shapes and explicit no-SQL owner ports."""

# ruff: noqa: F811 - imported fixtures register the no-connect source/UOW environment
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from capa_effectiveness.test_actual_applicability_owner import action_work, work  # noqa: F401
from sqlalchemy.engine import Engine

from pdos_next import change_action_fulfillment_owner as owner
from pdos_next.change_controlled_owner import ActionIntentRead
from pdos_next.change_implementation_owner import Occurrence
from pdos_next.domain.capa_effectiveness.fact_commands import ActionReviewInput
from pdos_next.domain.change_control.rules import digest
from pdos_next.domain.change_execution.models import ChangeCurrent, ChangeRequestVersion
from pdos_next.errors import DomainError
from pdos_next.schemas.change_control.contracts import ImplementationFact, Ref

from . import kernel_helpers as helper

CURRENT_ITEMS = owner._current_action_items


@pytest.fixture(autouse=True)
def no_connection(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Draft pure adapter cannot connect to a database")

    monkeypatch.setattr(Engine, "connect", forbidden)
    monkeypatch.setattr(Engine, "raw_connection", forbidden)


@pytest.fixture
def actual(action_work, monkeypatch):
    v = action_work
    s, ctx, pid = v.work.s, v.work.ctx, v.work.pid
    origin, binding = v.anchor.origin, v.binding
    h = helper.FakeHost()
    h.approve()
    item = h.order.plan.items[0]
    source = v.action.completion.evidence[0]
    at = v.action.completion.at.occurred_at - timedelta(seconds=1)
    output = Ref(id=uuid4(), revision=2, kind="engineering_configuration")
    occurrence = Occurrence(
        schema_version="pdos-change-implementation-occurrence-v2",
        scope=origin.scope,
        issue_id=origin.issue_id,
        capa_id=origin.issue.capa.id,
        action_id=binding.action_id,
        action_sha256=binding.action_sha256,
        purpose=origin.purpose,
        change_id=h.request_value.id,
        order_id=h.order.id,
        implementation_id=uuid4(),
        reconciles_id=None,
        item_id=item.id,
        intent_id=item.intent.id,
        executor_id=binding.executor_id,
        operation="change.implementation.record",
        outcome="succeeded",
        occurred_at=at,
        original_timezone="UTC",
        sources=(source,),
        outputs=(output,),
        note="Actual fixed configuration implementation",
        nature=origin.nature,
    )
    fact = ImplementationFact(
        id=occurrence.implementation_id,
        received_at=at + timedelta(microseconds=1),
        **occurrence.model_dump(
            include={
                "reconciles_id",
                "item_id",
                "intent_id",
                "executor_id",
                "outcome",
                "occurred_at",
                "sources",
                "outputs",
                "note",
                "nature",
            }
        ),
    )
    order = h.order.model_copy(update={"implementations": (fact,)})
    request = h.request_value.model_copy(update={"scope": origin.scope, "orders": (order,)})
    row = ChangeRequestVersion(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        product_id=pid,
        project_id=origin.scope.project_id,
        change_id=request.id,
        revision=request.revision,
        status=request.status,
        request_snapshot=request.model_dump(mode="json"),
        request_sha256=digest(request),
        operation="change.implementation.record",
        owner_id=origin.owner_id,
        visibility=origin.visibility,
    )
    pointer = ChangeCurrent(id=uuid4(), version_id=row.id, revision=row.revision)
    capture = owner.store.ImplementationCapture(
        id=uuid4(),
        occurrence_snapshot=occurrence.model_dump(mode="json"),
        sources=[source.model_dump(mode="json")],
    )
    atom = owner.store.ChangeImplementationRecord(
        id=uuid4(),
        capture_id=capture.id,
        change_version_id=row.id,
        fact_snapshot=fact.model_dump(mode="json"),
    )
    current_selection = owner.controlled.models.ChangeSelectionFact(
        id=uuid4(),
        item_id=item.id,
        revision=1,
        status="applicable",
    )
    until = datetime.now(UTC) + timedelta(minutes=20)
    selection_proof = owner.controlled.outputs.SelectionProof(
        scope=origin.scope.model_dump(mode="json"),
        item_sha256=digest(item),
        nature=origin.nature,
        applicable=True,
        valid_until=until,
        sources=(source,),
        required_source_read_set=[
            {"artifact_id": str(source.id), "expected_revision": source.revision}
        ],
        source_basis={},
        owner_proof={"receipt": {"id": str(uuid4())}},
    )
    intended = ActionIntentRead(
        current_selection.id,
        item.id,
        item.intent.id,
        binding.action_id,
        binding.action_sha256,
        binding.executor_id,
        order.id,
        selection_proof,
    )
    executed = SimpleNamespace(
        version=SimpleNamespace(
            id=row.id,
            sources=[source.model_dump(mode="json")],
            required_source_read_set=selection_proof.required_source_read_set,
        ),
        implementation=owner.store.ChangeImplementationRecord(id=atom.id),
        occurrence=occurrence,
        valid_until=until,
        material={
            "capture": occurrence.model_dump(mode="json"),
            "outputs": {
                str(output.id): {
                    "ref": output.model_dump(mode="json"),
                    "group": {
                        "receipt": {"id": str(uuid4()), "actor_id": str(binding.executor_id)}
                    },
                }
            },
        },
    )
    reads = []

    class Implementation:
        def read(self, _s, _ctx, _pid, *, implementation_version_id):
            assert (_s, _ctx, _pid, implementation_version_id) == (s, ctx, pid, row.id)
            reads.append("implementation")
            return executed

        def refresh(self, _s, _ctx, _pid, previous):
            assert previous is executed
            reads.append("implementation_refresh")
            return executed

    class Intent:
        def read(self, _s, _ctx, _pid, **values):
            assert values == {
                "change_id": request.id,
                "order_id": order.id,
                "item_id": item.id,
                "action_id": binding.action_id,
            }
            reads.append("intent")
            return intended

        def refresh(self, _s, _ctx, _pid, previous):
            assert previous is intended
            reads.append("intent_refresh")
            # The real owner returns a new eq=False opaque handle, not the same identity.
            return replace(intended)

    adapter = owner.ApprovedChangeActionFulfillmentOwner(s.get_bind())
    adapter.implementation, adapter.action_intent = Implementation(), Intent()
    basis = SimpleNamespace(
        scope=origin.scope,
        capa_id=origin.issue.capa.id,
        issue_id=origin.issue_id,
        purpose=origin.purpose,
        nature=origin.nature,
        actions=(binding,),
        owner_id=origin.owner_id,
        visibility=origin.visibility,
        sources=origin.sources,
        required_source_read_set=origin.required_source_read_set,
        basis_sha256="b" * 64,
    )
    monkeypatch.setattr(owner, "load_followup_basis", lambda *args, **kwargs: basis)
    monkeypatch.setattr(owner.change, "_runtime_stamp", lambda *_: "fixed-runtime")
    monkeypatch.setattr(owner.orders, "runtime", lambda *_: (("fixed-order-runtime",), ()))
    monkeypatch.setattr(owner.orders, "current_fixed", lambda *args: (pointer, row))
    monkeypatch.setattr(
        owner.controlled, "_caller", lambda *args, **kwargs: ((ctx.actor_id,), until)
    )
    monkeypatch.setattr(
        owner.controlled, "_project", lambda *args: (None, (origin.scope.project_id,))
    )
    monkeypatch.setattr(owner.controlled, "approved_order", lambda *args: until)
    monkeypatch.setattr(owner, "_current_action_items", lambda *args: (current_selection,))
    monkeypatch.setattr(owner, "original_occurrence", lambda *args: (occurrence, None))
    monkeypatch.setattr(
        owner.controlled,
        "_source_guard",
        lambda *args, **kwargs: {"source": "actual IO substitute"},
    )

    def one(_s, model, *where, **kwargs):
        predicates = {clause.left.name: clause.right.value for clause in where}
        assert predicates["tenant_id"] == ctx.tenant_id and predicates["product_id"] == pid
        assert predicates["project_id"] == origin.scope.project_id
        assert predicates["change_id"] == request.id and predicates["order_id"] == order.id
        assert (
            predicates["item_id"] == occurrence.item_id
            and predicates["fact_id"] == occurrence.implementation_id
        )
        if model is owner.store.ImplementationCapture:
            assert predicates["executor_id"] == binding.executor_id
            return capture
        assert (
            model is owner.store.ChangeImplementationRecord
            and predicates["capture_id"] == capture.id
        )
        return atom

    monkeypatch.setattr(owner.orders, "_one", one)
    selection = ActionReviewInput(
        action_id=binding.action_id,
        conclusion="applicable",
        reason="Named selection of actual saved implementation",
        sources=(source.model_dump(mode="json"),),
    )
    return SimpleNamespace(
        v=v,
        adapter=adapter,
        selection=selection,
        occurrence=occurrence,
        capture=capture,
        atom=atom,
        intended=intended,
        executed=executed,
        basis=basis,
        request=request,
        order=order,
        pointer=pointer,
        row=row,
        source=source,
        current_selection=current_selection,
        reads=reads,
    )


def read(actual):
    v = actual.v
    return actual.adapter.read(
        v.work.s,
        v.work.ctx,
        v.work.pid,
        actual.selection,
        anchor=v.anchor,
        candidate=None,
        rule=v.rule,
        observations=(),
        action=v.action,
        completion=v.action.completion,
        classification_material={"classification": "unknown"},
    )


def refresh(actual, previous):
    v = actual.v
    return actual.adapter.refresh(
        v.work.s,
        v.work.ctx,
        v.work.pid,
        actual.selection,
        previous,
        anchor=v.anchor,
        candidate=None,
        rule=v.rule,
        observations=(),
        action=v.action,
        completion=v.action.completion,
        classification_material={"classification": "unknown"},
    )


def test_real_owner_ports_bind_completed_action_and_exact_selected_implementation(actual):
    proof = read(actual)
    assert type(proof) is owner.ActualActionAttestation
    assert proof.action == actual.v.binding and proof.anchor_sha256 == actual.v.anchor.anchor_sha256
    assert proof.classification == "formal_change" and proof.conclusion == "applicable"
    assert proof.owner_refs == (actual.source,)
    assert actual.v.work.actor != actual.v.binding.executor_id
    assert actual.reads == ["implementation", "intent", "implementation_refresh", "intent_refresh"]
    assert refresh(actual, proof).owner_material == proof.owner_material
    assert not actual.v.work.s.new and not actual.v.work.s.dirty and not actual.v.work.s.deleted


@pytest.mark.parametrize("conclusion", ["unknown", "not_applicable"])
def test_no_default_positive_or_negative_fulfillment(actual, conclusion):
    actual.selection = actual.selection.model_copy(update={"conclusion": conclusion})
    with pytest.raises(DomainError) as error:
        read(actual)
    assert error.value.reason == "ACTION_FULFILLMENT_MISMATCH"


@pytest.mark.parametrize(
    "field", ["scope", "action_id", "executor_id", "purpose", "occurred_at", "outcome", "outputs"]
)
def test_other_action_scope_executor_late_or_unimplemented_occurrence_cannot_attest(
    actual, monkeypatch, field
):
    changed = dict(
        scope=actual.occurrence.scope.model_copy(update={"project_id": uuid4()}),
        action_id=uuid4(),
        executor_id=uuid4(),
        purpose="Different actual purpose",
        occurred_at=actual.v.action.completion.at.occurred_at + timedelta(seconds=1),
        outcome="unknown",
        outputs=(),
    )
    wrong = actual.occurrence.model_copy(update={field: changed[field]})
    monkeypatch.setattr(owner, "original_occurrence", lambda *args: (wrong, None))
    with pytest.raises(DomainError):
        read(actual)


def test_named_source_must_already_be_in_real_saved_completion(actual):
    actual.selection = actual.selection.model_copy(
        update={"sources": (actual.source.model_copy(update={"id": uuid4()}),)}
    )
    with pytest.raises(DomainError) as error:
        read(actual)
    assert error.value.reason == "ACTION_IMPLEMENTATION_MISMATCH"


def test_one_selected_occurrence_cannot_hide_sibling_approved_action_item(actual, monkeypatch):
    sibling = owner.controlled.models.ChangeSelectionFact(
        id=uuid4(), item_id=uuid4(), revision=1, status="applicable"
    )
    monkeypatch.setattr(
        owner, "_current_action_items", lambda *args: (actual.current_selection, sibling)
    )
    with pytest.raises(DomainError) as error:
        read(actual)
    assert error.value.reason == "ACTION_IMPLEMENTATION_MISMATCH"


def test_changed_current_completion_cannot_reuse_old_anchor(actual):
    binding = actual.basis.actions[0].model_copy(update={"completion_sha256": "f" * 64})
    actual.basis.actions = (binding,)
    with pytest.raises(DomainError) as error:
        read(actual)
    assert error.value.reason == "ACTION_COMPLETION_MISMATCH"


def test_actual_implementation_and_selection_identity_must_match_not_just_success(actual):
    actual.executed.implementation.id = uuid4()
    with pytest.raises(DomainError) as error:
        read(actual)
    assert error.value.reason == "ACTION_IMPLEMENTATION_MISMATCH"


def test_source_drift_after_actual_owner_io_rejects_attestation(actual, monkeypatch):
    calls = []

    def changed(*args, **kwargs):
        calls.append(True)
        return {"source": "before" if len(calls) == 1 else "after"}

    monkeypatch.setattr(owner.controlled, "_source_guard", changed)
    with pytest.raises(DomainError) as error:
        read(actual)
    assert error.value.reason == "SOURCE_STALE"


def test_modified_unregistered_or_rolled_back_attestation_cannot_refresh(actual):
    proof = read(actual)
    with pytest.raises(DomainError):
        refresh(actual, replace(proof))
    original = deepcopy(proof.owner_material)
    proof.owner_material["items"] = []
    with pytest.raises(DomainError):
        refresh(actual, proof)
    proof.owner_material.clear()
    proof.owner_material.update(original)
    actual.v.work.s.rollback()
    with pytest.raises(DomainError):
        refresh(actual, proof)


def approved_selections(actual, monkeypatch, *, both_target=False):
    """Real immutable material/Fact shapes; original proof IO is explicit substitute."""
    origin, ctx = actual.v.anchor.origin, actual.v.work.ctx
    originals, currents, groups, proofs = {}, {}, {}, []
    for index, item in enumerate(actual.order.plan.items):
        material = owner.controlled.models.SelectionMaterial(
            schema_version="pdos-controlled-change-selection-v1",
            scope=origin.scope,
            purpose=origin.purpose,
            change_id=actual.request.id,
            item=item,
            issue_id=origin.issue_id,
            capa_id=origin.issue.capa.id,
            action_id=actual.v.binding.action_id if index == 0 or both_target else uuid4(),
            action_sha256=actual.v.binding.action_sha256,
            executor_id=actual.v.binding.executor_id,
            decider_id=ctx.actor_id,
            status="applicable",
            valid_until=actual.intended.selection.valid_until,
            reason="Actual original named selection",
            nature=origin.nature,
        )
        data = dict(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            product_id=actual.v.work.pid,
            project_id=origin.scope.project_id,
            change_id=actual.request.id,
            item_id=item.id,
            item_sha256=owner.orders.digest(item),
            intent_id=item.intent.id,
            issue_id=material.issue_id,
            capa_id=material.capa_id,
            action_id=material.action_id,
            action_sha256=material.action_sha256,
            actor_id=material.decider_id,
            material=material.model_dump(mode="json"),
            material_sha256=owner.orders.digest(material),
            confirmation_material_sha256="c" * 64,
            revision=1,
            status="applicable",
        )
        original = owner.controlled.models.ChangeSelectionFact(**data)
        originals[original.id] = original
        currents[item.id] = owner.controlled.models.ChangeSelectionFact(**deepcopy(data))
        group = {
            "receipt": {
                "id": uuid4(),
                "subject_id": original.id,
                "subject_revision": original.revision,
                "subject_type": owner.controlled.models.SELECTION_FAMILY,
                "created_at": datetime.now(UTC),
            }
        }
        groups[original.id] = group
        proofs.append(
            actual.intended.selection.model_copy(
                update={
                    "item_sha256": owner.orders.digest(item),
                    "owner_proof": group,
                }
            ).model_dump(mode="json")
        )
    prepared = owner.store.ChangeOrderRecord(
        id=uuid4(),
        content_sha256=actual.order.content_digest,
        order_snapshot=actual.order.model_dump(mode="json"),
        input_snapshot={"review": {"selection": proofs}},
    )
    reads, checked = [], []

    def one(session, model, *where, **kwargs):
        assert session is actual.v.work.s
        values = {clause.left.name: clause.right.value for clause in where}
        assert values["tenant_id"] == ctx.tenant_id
        assert values["product_id"] == actual.v.work.pid
        assert values["project_id"] == origin.scope.project_id
        assert values["change_id"] == actual.request.id
        if model is owner.store.ChangeOrderRecord:
            assert values["order_id"] == actual.order.id
            return prepared
        assert model is owner.controlled.models.ChangeSelectionFact
        value = originals[values["id"]]
        assert values["item_id"] == value.item_id and values["revision"] == value.revision
        assert "action_id" not in values  # Original facts, never filtered Current visibility.
        reads.append(value.id)
        return value

    def common_group(session, context, pid, row, *, operation, event, actor):
        assert context is ctx and actor == row.actor_id
        assert operation == owner.controlled.models.SELECTION_OPERATION
        assert event == owner.controlled.models.SELECTION_EVENT
        return groups[row.id]

    def proof(session, context, pid, atom, group):
        assert context is ctx and atom.material_sha256 == atom.confirmation_material_sha256
        assert group is groups[atom.id]
        checked.append(atom.id)

    def current(session, context, pid, scope, change_id, item_id):
        assert context is ctx and scope == origin.scope and change_id == actual.request.id
        row = currents.get(item_id)
        return (SimpleNamespace(fact_id=row.id), row) if row is not None else (None, None)

    monkeypatch.setattr(owner.orders, "_one", one)
    monkeypatch.setattr(owner.controlled, "common_group", common_group)
    monkeypatch.setattr(owner.controlled, "_atom_proof", proof)
    monkeypatch.setattr(owner.controlled, "selection_pointer", current)
    return SimpleNamespace(
        originals=originals,
        currents=currents,
        prepared=prepared,
        groups=groups,
        reads=reads,
        checked=checked,
    )


def original_obligations(actual):
    return CURRENT_ITEMS(
        actual.v.work.s,
        actual.v.work.ctx,
        actual.v.work.pid,
        actual.v.anchor.origin,
        actual.request,
        actual.order,
        actual.v.binding.action_id,
    )


def test_all_original_approved_items_define_action_obligations_before_current_filter(
    actual, monkeypatch
):
    saved = approved_selections(actual, monkeypatch)
    # An unrelated action's Current is absent. Its original binding still must be
    # read, so it cannot conceal an obligation that actually belongs to this one.
    saved.currents.pop(actual.order.plan.items[1].id)
    rows = original_obligations(actual)
    assert [row.item_id for row in rows] == [actual.order.plan.items[0].id]
    assert set(saved.reads) == set(saved.checked) == set(saved.originals)


@pytest.mark.parametrize("drift", ["missing", "other_action", "not_applicable"])
def test_lost_or_rebound_current_cannot_shrink_two_original_action_obligations(
    actual, monkeypatch, drift
):
    saved = approved_selections(actual, monkeypatch, both_target=True)
    lost = actual.order.plan.items[1].id
    if drift == "missing":
        saved.currents.pop(lost)
    else:
        current = saved.currents[lost]
        changed = deepcopy(current.material)
        changed["action_id" if drift == "other_action" else "status"] = (
            str(uuid4()) if drift == "other_action" else "not_applicable"
        )
        current.material = changed
        current.material_sha256 = owner.orders.digest(changed)
    with pytest.raises(DomainError) as error:
        original_obligations(actual)
    assert error.value.reason == "ACTION_IMPLEMENTATION_MISMATCH"
    assert set(saved.reads) == set(saved.checked) == set(saved.originals)


@pytest.mark.parametrize("drift", ["missing_item", "wrong_original_receipt"])
def test_original_order_review_must_pin_every_item_and_its_actual_selection_group(
    actual, monkeypatch, drift
):
    saved = approved_selections(actual, monkeypatch)
    selections = saved.prepared.input_snapshot["review"]["selection"]
    if drift == "missing_item":
        selections.pop()
    else:
        selections[0]["owner_proof"]["receipt"]["id"] = str(uuid4())
    with pytest.raises(DomainError) as error:
        original_obligations(actual)
    assert error.value.reason == "ACTION_IMPLEMENTATION_MISMATCH"


def test_expired_actual_rule_never_yields_current_attestation(actual):
    actual.v.rule.valid_until = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(DomainError) as error:
        read(actual)
    assert error.value.reason == "SOURCE_STALE"
