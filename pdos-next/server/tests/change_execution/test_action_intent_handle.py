"""Actual action-intent handle sealing/refresh with explicit pure IO substitutes.

The kernel snapshots, SelectionMaterial/SelectionProof, UUIDs, aware clocks and
SQLAlchemy transaction are real. Owner IO substitutes confer no qualification,
source authorization or persisted approval; database/HTTP connections are denied.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from pdos_next import change_controlled_owner as controlled
from pdos_next.change_controlled_schemas import SelectionMaterial
from pdos_next.change_controlled_store import ChangeSelectionFact
from pdos_next.change_order_store import SelectionProof
from pdos_next.domain.change_execution.models import ChangeCurrent, ChangeRequestVersion
from pdos_next.errors import DomainError
from pdos_next.service import Context

from . import kernel_helpers as helper
from .test_change_order import no_connection  # noqa: F401 - pure fixture denies DB/HTTP


@pytest.fixture
def intent_world(monkeypatch):
    kernel = helper.FakeHost()
    kernel.approve()
    request, order = kernel.request_value, kernel.order
    item = order.plan.items[0]
    ctx = Context(helper.SCOPE.tenant_id, helper.uid("intent-reader"), helper.uid("intent-reader"))
    session = Session(bind=SimpleNamespace())
    session.begin()  # Genuine SessionTransaction, with no connection or SQL.
    until = helper.NOW + timedelta(hours=2)
    action_id, executor_id = uuid4(), uuid4()
    material = SelectionMaterial(
        schema_version="pdos-controlled-change-selection-v1",
        scope=request.scope,
        purpose="Synthetic fixed action purpose",
        change_id=request.id,
        item=item,
        issue_id=uuid4(),
        capa_id=uuid4(),
        action_id=action_id,
        action_sha256=controlled.digest("fixed approved action"),
        executor_id=executor_id,
        decider_id=helper.uid("original-selector"),
        status="applicable",
        valid_until=until,
        reason="Explicit synthetic original action selection",
        nature="synthetic",
    )
    selected = ChangeSelectionFact(id=uuid4(), material=material.model_dump(mode="json"))
    row = ChangeRequestVersion(
        id=uuid4(),
        tenant_id=request.scope.tenant_id,
        product_id=request.scope.product_id,
        project_id=request.scope.project_id,
        change_id=request.id,
        revision=request.revision,
        status=request.status,
        operation="change.order.approve",
        request_snapshot=request.model_dump(mode="json"),
        request_sha256=controlled.digest(request),
    )
    pointer = ChangeCurrent(id=uuid4(), version_id=row.id, revision=row.revision)
    proof = SelectionProof(
        scope=request.scope.model_dump(mode="python"),
        item_sha256=controlled.digest(item),
        nature="synthetic",
        applicable=True,
        valid_until=until,
        sources=(helper.SOURCE,),
        required_source_read_set=(
            {"artifact_id": str(helper.SOURCE.id), "expected_revision": helper.SOURCE.revision},
        ),
        source_basis={"observed_at": helper.NOW, "source_id": helper.SOURCE.id},
        owner_proof={
            "receipt": {"id": uuid4(), "created_at": helper.NOW, "actor_id": material.decider_id},
            "audit": {"id": uuid4()},
            "nested": [{"outbox_id": uuid4(), "occurred_at": helper.NOW}],
        },
    )
    calls = {"approved": 0, "selection": 0, "caller": 0, "project": 0}

    def bound(s, caller, pid):
        assert (s, caller, pid) == (session, ctx, request.scope.product_id)

    def current(s, caller, pid, identity):
        bound(s, caller, pid)
        assert identity == request.id
        return pointer, row

    def approved(s, caller, pid, fixed_request, fixed_order):
        bound(s, caller, pid)
        assert fixed_request == request and fixed_order == order
        calls["approved"] += 1
        return until

    def seed(s, caller, pid, refs):
        bound(s, caller, pid)
        assert refs == (*request.roots, *request.references)
        return request.scope, material.purpose

    def selection(s, caller, pid, **values):
        bound(s, caller, pid)
        assert values == {
            "scope": request.scope,
            "purpose": material.purpose,
            "request": request,
            "item": item,
        }
        calls["selection"] += 1
        # Fresh equivalent owner material, retaining native nested UUID/datetime.
        return SelectionProof.model_validate(proof.model_dump(mode="python"))

    def selection_pointer(s, caller, pid, scope, change_id, item_id):
        bound(s, caller, pid)
        assert (scope, change_id, item_id) == (request.scope, request.id, item.id)
        return SimpleNamespace(id=uuid4()), selected

    def caller(s, actual, pid, *, write):
        bound(s, actual, pid)
        assert write is False
        calls["caller"] += 1
        return (ctx.actor_id, "synthetic caller IO"), until

    def project(s, actual, scope):
        bound(s, actual, scope.product_id)
        assert scope == request.scope
        calls["project"] += 1
        return object(), (scope.project_id, "synthetic project IO")

    monkeypatch.setattr(controlled, "current_fixed", current)
    monkeypatch.setattr(controlled, "approved_order", approved)
    monkeypatch.setattr(controlled.old, "_seed", seed)
    monkeypatch.setattr(controlled.old, "_runtime_stamp", lambda s: "fixed synthetic owner runtime")
    monkeypatch.setattr(controlled, "selection_callback", selection)
    monkeypatch.setattr(controlled, "selection_pointer", selection_pointer)
    monkeypatch.setattr(controlled, "_caller", caller)
    monkeypatch.setattr(controlled, "_project", project)
    try:
        yield SimpleNamespace(
            session=session,
            ctx=ctx,
            request=request,
            order=order,
            item=item,
            action_id=action_id,
            executor_id=executor_id,
            proof=proof,
            calls=calls,
            owner=controlled.ApprovedActionIntentOwner(),
        )
    finally:
        session.close()


def read(work):
    return work.owner.read(
        work.session,
        work.ctx,
        work.request.scope.product_id,
        change_id=work.request.id,
        order_id=work.order.id,
        item_id=work.item.id,
        action_id=work.action_id,
    )


def refresh(work, previous):
    return work.owner.refresh(work.session, work.ctx, work.request.scope.product_id, previous)


def test_native_uuid_and_nested_owner_material_seal_and_refresh_as_new_equivalent_handle(
    intent_world,
):
    work = intent_world

    first = read(work)
    second = refresh(work, first)

    assert first is not second
    assert type(first) is type(second) is controlled.ActionIntentRead
    assert vars(first) == vars(second)
    assert first.action_id == work.action_id and first.executor_id == work.executor_id
    assert isinstance(first.selection_id, UUID)
    assert isinstance(first.selection.owner_proof["receipt"]["id"], UUID)
    assert isinstance(first.selection.owner_proof["receipt"]["created_at"], datetime)
    assert first.selection.owner_proof["receipt"]["created_at"].utcoffset() is not None
    assert first.selection.valid_until.utcoffset() is not None
    assert work.calls == {"approved": 4, "selection": 2, "caller": 2, "project": 2}


def test_mutating_sealed_handle_field_still_rejects_before_new_owner_read(intent_world):
    work = intent_world
    first = read(work)
    object.__setattr__(first, "executor_id", uuid4())

    with pytest.raises(DomainError) as error:
        refresh(work, first)
    assert error.value.reason == "SOURCE_STALE"
    assert work.calls["selection"] == 1


def test_changed_later_selection_owner_proof_rejects_after_actual_refresh_read(intent_world):
    work = intent_world
    first = read(work)
    original_receipt = first.selection.owner_proof["receipt"]["id"]
    work.proof.owner_proof["receipt"]["id"] = uuid4()

    with pytest.raises(DomainError) as error:
        refresh(work, first)
    assert error.value.reason == "SOURCE_STALE"
    assert work.calls["selection"] == 2
    assert first.selection.owner_proof["receipt"]["id"] == original_receipt
