"""Field execution uses its exact native selection; these are offline owner checks."""

from types import SimpleNamespace

import httpx
import psycopg
import pytest
from pydantic import ValidationError
from sqlalchemy import UniqueConstraint
from sqlalchemy.engine import Engine

from pdos_next import change_controlled_owner as controlled
from pdos_next import change_implementation_owner as owner
from pdos_next import field_change_selection as field
from pdos_next.change_controlled_schemas import FieldSelectionMaterial
from pdos_next.change_controlled_store import ChangeSelectionFact
from pdos_next.domain.change_control.rules import digest
from pdos_next.errors import DomainError
from pdos_next.schemas.change_control.contracts import Ref

from . import kernel_helpers as helper


@pytest.fixture(autouse=True)
def no_connections(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Field owner unit checks must never use database or HTTP")

    for cls, name in ((Engine, "connect"), (Engine, "raw_connection"), (httpx.Client, "request")):
        monkeypatch.setattr(cls, name, deny)
    monkeypatch.setattr(psycopg, "connect", deny)


def case():
    host = helper.FakeHost()
    host.approve()
    item = host.order.plan.items[0]
    fact = host.implementation_fact(item)
    feedback = Ref(kind="field_feedback", id=helper.uid("actual-field"), revision=2)
    request = host.request_value.model_copy(update={"roots": (feedback,), "references": ()})
    material = FieldSelectionMaterial(
        schema_version="pdos-field-change-selection-v1",
        scope=request.scope,
        purpose="Investigate the actual field configuration",
        change_id=request.id,
        item=item,
        feedback={"id": feedback.id, "revision": feedback.revision},
        feedback_version_id=helper.uid("field-version"),
        feedback_sha256="c" * 64,
        executor_id=fact.executor_id,
        decider_id=helper.uid("field-decider"),
        status="applicable",
        valid_until=None,
        reason="Explicit future engineering change intent",
        nature="synthetic",
    )
    selected = SimpleNamespace(
        id=helper.uid("field-selection"),
        revision=1,
        basis_kind="field_intent",
        material=material.model_dump(mode="json"),
        material_sha256=digest(material),
        feedback_id=feedback.id,
        feedback_version_id=material.feedback_version_id,
        feedback_revision=feedback.revision,
        feedback_sha256=material.feedback_sha256,
        executor_id=fact.executor_id,
    )
    occurrence = owner.FieldOccurrence(
        schema_version="pdos-field-change-implementation-occurrence-v1",
        scope=request.scope,
        purpose=material.purpose,
        feedback=material.feedback,
        feedback_version_id=material.feedback_version_id,
        feedback_sha256=material.feedback_sha256,
        selection_id=selected.id,
        selection_revision=selected.revision,
        selection_sha256=selected.material_sha256,
        change_id=request.id,
        order_id=host.order.id,
        implementation_id=fact.id,
        reconciles_id=None,
        item_id=item.id,
        intent_id=item.intent.id,
        executor_id=fact.executor_id,
        operation="change.implementation.record",
        outcome=fact.outcome,
        occurred_at=fact.occurred_at,
        original_timezone="America/Los_Angeles",
        sources=fact.sources,
        outputs=fact.outputs,
        note=fact.note,
        nature=fact.nature,
    )
    basis = field.FieldBasis(
        request.scope,
        material.purpose,
        helper.uid("category"),
        request.requester_id,
        "category",
        material.nature,
        feedback.id,
        material.feedback_version_id,
        feedback.revision,
        material.feedback_sha256,
        (helper.SOURCE,),
        [],
        {},
    )
    intent = field.FieldIntent(item.intent.id, digest(item.intent), fact.executor_id)
    return SimpleNamespace(
        request=request,
        order=host.order,
        item=item,
        fact=fact,
        occurrence=occurrence,
        selected=selected,
        material=material,
        basis=basis,
        intent=intent,
        ctx=SimpleNamespace(actor_id=fact.executor_id, requester_id=fact.executor_id),
    )


def bind_substitute(monkeypatch, value):
    calls = []

    def selection(*_args, **_kwargs):
        calls.append("native-current-selection")
        return SimpleNamespace(nature=value.material.nature)

    def basis(_s, _ctx, _pid, target, item, request, scope, purpose, nature):
        calls.append("native-field-basis")
        assert target.feedback == value.occurrence.feedback
        assert target.executor_id == value.occurrence.executor_id
        assert (item, request, scope, purpose, nature) == (
            value.item,
            value.request,
            value.request.scope,
            value.material.purpose,
            value.material.nature,
        )
        return value.basis, value.intent

    def no_capa(*_args, **_kwargs):
        raise AssertionError("Native Field implementation must never invent an Issue/CAPA")

    monkeypatch.setattr(controlled, "selection_callback", selection)
    monkeypatch.setattr(
        controlled, "selection_pointer", lambda *_args, **_kwargs: (None, value.selected)
    )
    monkeypatch.setattr(field, "load_basis", basis)
    monkeypatch.setattr(owner, "load_followup_basis", no_capa)
    return calls


def test_native_field_implementation_is_dispatched_without_a_capa_root(monkeypatch):
    value = case()
    calls = bind_substitute(monkeypatch, value)
    basis, item = owner.validate_binding(
        None,
        value.ctx,
        helper.SCOPE.product_id,
        value.request,
        value.order,
        value.occurrence,
        new_write=True,
    )
    assert basis is value.basis and item == value.item
    assert calls == ["native-current-selection", "native-field-basis"]
    owner.fact_matches_occurrence(value.fact, value.occurrence)


@pytest.mark.parametrize(
    "name,replacement",
    (
        ("id", helper.uid("other-selection")),
        ("revision", 2),
        ("material_sha256", "f" * 64),
        ("feedback_id", helper.uid("other-feedback")),
        ("feedback_version_id", helper.uid("other-version")),
        ("feedback_revision", 3),
        ("feedback_sha256", "d" * 64),
        ("executor_id", helper.uid("other-executor")),
    ),
)
def test_field_implementation_rejects_rebound_selection_or_feedback(monkeypatch, name, replacement):
    value = case()
    bind_substitute(monkeypatch, value)
    setattr(value.selected, name, replacement)
    with pytest.raises(DomainError) as error:
        owner.validate_binding(
            None,
            value.ctx,
            helper.SCOPE.product_id,
            value.request,
            value.order,
            value.occurrence,
            new_write=True,
        )
    assert error.value.reason == "IMPLEMENTATION_MATERIAL_MISMATCH"


def test_field_implementation_keeps_actual_named_executor_and_both_approvals(monkeypatch):
    value = case()
    bind_substitute(monkeypatch, value)
    other = SimpleNamespace(actor_id=helper.uid("peer"), requester_id=helper.uid("peer"))
    with pytest.raises(DomainError) as wrong_person:
        owner.validate_binding(
            None,
            other,
            helper.SCOPE.product_id,
            value.request,
            value.order,
            value.occurrence,
            new_write=True,
        )
    assert wrong_person.value.reason == "NAMED_EXECUTOR_REQUIRED"
    incomplete = value.order.model_copy(update={"approvals": value.order.approvals[:1]})
    with pytest.raises(DomainError) as approval:
        owner.validate_binding(
            None,
            value.ctx,
            helper.SCOPE.product_id,
            value.request,
            incomplete,
            value.occurrence,
            new_write=True,
        )
    assert approval.value.reason == "APPROVAL_REQUIRED"


def test_field_and_legacy_occurrence_versions_remain_disjoint():
    value = case()
    field_raw = value.occurrence.model_dump(mode="json")
    assert owner.parse_occurrence(field_raw) == value.occurrence
    with pytest.raises(ValidationError):
        owner.parse_occurrence({**field_raw, "issue_id": str(helper.uid("invented-issue"))})
    legacy = {
        key: item
        for key, item in field_raw.items()
        if key
        not in {
            "feedback",
            "feedback_version_id",
            "feedback_sha256",
            "selection_id",
            "selection_revision",
            "selection_sha256",
        }
    }
    legacy.update(
        schema_version="pdos-change-implementation-occurrence-v2",
        issue_id=str(helper.uid("issue")),
        capa_id=str(helper.uid("capa")),
        action_id=str(helper.uid("action")),
        action_sha256="a" * 64,
    )
    assert type(owner.parse_occurrence(legacy)) is owner.Occurrence
    with pytest.raises(ValidationError):
        owner.parse_occurrence({**legacy, "feedback": field_raw["feedback"]})
    with pytest.raises(ValidationError):
        owner.parse_occurrence({**field_raw, "schema_version": "unregistered-v9"})


@pytest.mark.parametrize("bad", (True, "1", 1.0, 0, -1))
def test_field_occurrence_fixed_selection_revision_is_strict(bad):
    raw = case().occurrence.model_dump(mode="json")
    with pytest.raises(ValidationError):
        owner.parse_occurrence({**raw, "selection_revision": bad})


def test_native_selection_foreign_keys_have_real_unique_targets_and_nullable_alternative():
    table = ChangeSelectionFact.__table__
    for name in (
        "issue_id",
        "issue_version_id",
        "issue_revision",
        "capa_id",
        "action_id",
        "action_sha256",
        "feedback_id",
        "feedback_version_id",
        "feedback_revision",
        "feedback_sha256",
        "executor_id",
    ):
        assert table.c[name].nullable
    assert not table.c.category_id.nullable
    reference = next(
        value
        for value in table.foreign_key_constraints
        if value.name == "controlled_selection_field_feedback_fk"
    )
    target = reference.referred_table
    expected = tuple(element.column.name for element in reference.elements)
    unique_targets = {
        tuple(target.primary_key.columns.keys()),
        *(
            tuple(value.columns.keys())
            for value in target.constraints
            if isinstance(value, UniqueConstraint)
        ),
    }
    assert expected in unique_targets
    assert reference.referred_table.name == "field_feedback_versions"
