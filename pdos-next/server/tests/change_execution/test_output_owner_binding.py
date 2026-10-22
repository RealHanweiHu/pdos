"""Actual output DTO/ORM lineage guards with explicit save-group read substitutes."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next import change_implementation_owner as owner
from pdos_next import change_order_service
from pdos_next.domain.configurations.models import EngineeringConfiguration, ProcessRevision
from pdos_next.errors import DomainError
from pdos_next.schemas.change_control.contracts import ImplementationFact, PlanItem, Ref
from pdos_next.schemas.verification.contracts import Scope, SourceRef
from pdos_next.service import Context


@pytest.fixture(params=["engineering_configuration", "manufacturing_configuration"])
def output_case(request, monkeypatch):
    kind = request.param
    tenant, product, project, executor = (uuid4() for _ in range(4))
    ctx = Context(tenant, executor, executor, category_id=uuid4())
    scope = Scope(tenant_id=tenant, product_id=product, project_id=project)
    source = SourceRef(id=uuid4(), revision=1, position="fixed-output-original")
    previous = Ref(id=uuid4(), revision=3, kind=kind)
    output = Ref(id=uuid4(), revision=4, kind=kind)
    model = EngineeringConfiguration if kind == "engineering_configuration" else ProcessRevision
    row = model(
        id=output.id,
        revision=output.revision,
        tenant_id=tenant,
        product_id=product,
        series_id=uuid4(),
        previous_id=previous.id,
        expected_previous_revision=previous.revision,
        owner_id=executor,
        visibility="category",
        name="Actual saved configuration output",
    )
    item = PlanItem(
        id=uuid4(),
        discipline="engineering" if kind == "engineering_configuration" else "manufacturing",
        selection={
            "objects": [previous],
            "units": [f"object:{previous.id}"],
            "conditions": ["Retain the exact preceding configuration as the intent basis."],
            "sources": [source],
        },
        intent={
            "id": uuid4(),
            "kind": f"new_{kind}",
            "basis": [previous],
            "description": "Create a new fixed configuration from the named previous version.",
        },
        verification_requirement="Check the saved configuration and professional approval order.",
    )
    at = datetime.now(UTC) - timedelta(minutes=1)
    order = SimpleNamespace(
        plan=SimpleNamespace(items=(item,)),
        approvals=(
            SimpleNamespace(discipline="engineering", at=at),
            SimpleNamespace(discipline="manufacturing", at=at + timedelta(seconds=10)),
        ),
    )
    fact = ImplementationFact(
        id=uuid4(),
        item_id=item.id,
        intent_id=item.intent.id,
        executor_id=executor,
        outcome="succeeded",
        occurred_at=at + timedelta(seconds=30),
        received_at=at + timedelta(seconds=40),
        sources=(source,),
        outputs=(output,),
        note="Offline output binding, not a real common-save-group attestation.",
        nature="synthetic",
    )
    family = (
        "engineering_configuration" if kind == "engineering_configuration" else "process_revision"
    )
    group = {
        "receipt": {
            "id": uuid4(),
            "subject_type": family,
            "created_at": at + timedelta(seconds=20),
        }
    }
    loads, queries, saves = [], [], []

    class Reader(owner.OwnerReader):
        def _load(self, ref):
            loads.append(ref)
            assert ref == output
            return (
                row,
                {"name": row.name, "previous_id": str(row.previous_id)},
                [],
                {"fixed_receipt_id": str(group["receipt"]["id"])},
            )

    def exact_row(s, requested_model, *where):
        queries.append(requested_model)
        assert requested_model is model
        return row

    def common_save(s, caller, pid, actual, **kwargs):
        assert actual is row and caller is ctx and pid == product
        saves.append(kwargs)
        return group

    monkeypatch.setattr(owner, "OwnerReader", Reader)
    monkeypatch.setattr(change_order_service, "_one", exact_row)
    monkeypatch.setattr(owner, "common_group", common_save)
    engine = SimpleNamespace()
    return SimpleNamespace(
        s=SimpleNamespace(get_bind=lambda: engine),
        ctx=ctx,
        product=product,
        request=SimpleNamespace(scope=scope, audience=(f"product:{product}",)),
        order=order,
        item=item,
        fact=fact,
        output=output,
        previous=previous,
        row=row,
        group=group,
        loads=loads,
        queries=queries,
        saves=saves,
    )


def verify(value):
    return owner.verify_outputs(
        value.s, value.ctx, value.product, value.request, value.order, value.fact
    )


def reject(value, reason):
    with pytest.raises(DomainError) as error:
        verify(value)
    assert error.value.reason == reason


def test_actual_configuration_output_matches_kind_previous_version_and_both_approvals(output_case):
    value = output_case
    basis, reader = verify(value)
    assert basis[str(value.output.id)]["ref"] == value.output.model_dump(mode="json")
    assert basis[str(value.output.id)]["object"]["previous_id"] == str(value.previous.id)
    assert value.queries == [type(value.row)]
    assert reader.objects[value.output.identity].current is True
    assert value.saves == [
        {
            "operation": (
                "engineering.configuration.create"
                if value.output.kind == "engineering_configuration"
                else "npi.process.revise"
            ),
            "event": (
                "configuration.created"
                if value.output.kind == "engineering_configuration"
                else "process.revised"
            ),
            "actor": value.fact.executor_id,
        }
    ]


def test_output_cannot_use_the_other_configuration_owner_kind(output_case):
    value = output_case
    other = (
        "manufacturing_configuration"
        if value.output.kind == "engineering_configuration"
        else "engineering_configuration"
    )
    value.fact = value.fact.model_copy(
        update={"outputs": (value.output.model_copy(update={"kind": other}),)}
    )
    reject(value, "IMPLEMENTATION_OWNER_MISMATCH")
    assert value.loads == value.queries == value.saves == []


@pytest.mark.parametrize("mismatch", ["id", "revision", "kind", "key", "first_revision"])
def test_output_requires_the_actual_previous_configuration_in_the_approved_intent(
    output_case, mismatch
):
    value = output_case
    previous = value.previous
    if mismatch == "first_revision":
        value.row.previous_id = value.row.expected_previous_revision = None
    else:
        update = {
            "id": {"id": uuid4()},
            "revision": {"revision": previous.revision + 1},
            "kind": {"kind": "part"},
            "key": {"key": "unapproved-field"},
        }[mismatch]
        item = value.item.model_copy(
            update={
                "intent": value.item.intent.model_copy(
                    update={"basis": (previous.model_copy(update=update),)}
                )
            }
        )
        value.order.plan = SimpleNamespace(items=(item,))
    reject(value, "IMPLEMENTATION_OWNER_MISMATCH")


def test_saved_output_between_professional_approvals_is_not_post_approval_execution(output_case):
    value = output_case
    value.group["receipt"]["created_at"] = value.order.approvals[0].at + timedelta(seconds=5)
    reject(value, "IMPLEMENTATION_WRITER_MISMATCH")


def test_output_cannot_be_saved_after_the_claimed_implementation_occurrence(output_case):
    value = output_case
    value.group["receipt"]["created_at"] = value.fact.occurred_at + timedelta(microseconds=1)
    reject(value, "IMPLEMENTATION_WRITER_MISMATCH")


def test_output_owner_must_be_the_named_executor(output_case):
    value = output_case
    value.row.owner_id = uuid4()
    reject(value, "IMPLEMENTATION_WRITER_MISMATCH")


def test_common_save_receipt_cannot_belong_to_another_owner_family(output_case):
    value = output_case
    value.group["receipt"]["subject_type"] = "build"
    reject(value, "IMPLEMENTATION_WRITER_MISMATCH")
