"""Actual owner scope/ref/metadata guards with explicit SQL transport substitutes."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next.domain.work_management import owner
from pdos_next.domain.work_management.constants import CREATE
from pdos_next.domain.work_management.schemas import TaskSnapshot
from pdos_next.errors import DomainError
from pdos_next.service import Context, digest


def task_case():
    tenant, category, actor, pid, stable = (uuid4() for _ in range(5))
    ctx = Context(tenant, actor, actor, category_id=category)
    snapshot = TaskSnapshot(
        task_id=stable,
        revision=1,
        state="proposed",
        title="Fixed task",
        goal="Exact identity",
        outcomes=[{"key": "drawing", "text": "Drawing", "required": True}],
    )
    body = snapshot.model_dump(mode="json")
    row = SimpleNamespace(
        id=uuid4(),
        task_id=stable,
        revision=1,
        state="proposed",
        operation=CREATE,
        tenant_id=tenant,
        category_id=category,
        product_id=pid,
        body=body,
        body_sha256=digest(body),
    )
    return ctx, pid, stable, row


def test_task_uses_stable_identity_and_can_read_an_explicit_historical_revision(monkeypatch):
    ctx, pid, stable, old = task_case()
    pointer = SimpleNamespace(version_id=uuid4(), revision=3)
    statements = []

    class SQL:
        def scalar(self, statement):
            statements.append(statement.compile().params)
            return pointer if len(statements) == 1 else old

        def get(self, *args):
            raise AssertionError("Fixed revision must not substitute the current fact")

    monkeypatch.setattr(owner, "common_group", lambda *args, **kwargs: {})
    row, snapshot, current = owner.task(SQL(), ctx, pid, stable, revision=1, fixed=True)
    assert row is old and snapshot.task_id == stable and current is pointer
    assert all(stable in params.values() for params in statements)
    assert 1 in statements[1].values()


def test_stale_current_reference_fails_before_reading_another_fact_or_common_group(monkeypatch):
    ctx, pid, stable, _ = task_case()

    class SQL:
        def scalar(self, statement):
            assert stable in statement.compile().params.values()
            return SimpleNamespace(version_id=uuid4(), revision=3)

        def get(self, *args):
            raise AssertionError("A stale reference must not read or replace the current row")

    monkeypatch.setattr(
        owner,
        "common_group",
        lambda *args, **kwargs: pytest.fail("No common group read for stale ref"),
    )
    with pytest.raises(DomainError) as error:
        owner.task(SQL(), ctx, pid, stable, revision=2)
    assert error.value.reason == "VERSION_CONFLICT"


def test_foreign_product_row_is_rejected_before_its_receipt_group_is_considered(monkeypatch):
    ctx, pid, _, row = task_case()
    row.product_id = uuid4()
    monkeypatch.setattr(
        owner,
        "common_group",
        lambda *args, **kwargs: pytest.fail("Foreign fixed row cannot use a receipt"),
    )
    with pytest.raises(DomainError) as error:
        owner.retained(object(), ctx, pid, row)
    assert error.value.reason == "FORBIDDEN_SCOPE"


@pytest.mark.parametrize("fault", ["withdrawn", "epoch"])
def test_source_current_rechecks_direct_metadata_without_reading_original_bodies(fault):
    tenant, category, actor, pid, artifact_id, original_id = (uuid4() for _ in range(6))
    ctx = Context(tenant, actor, actor, category_id=category)
    expected = {
        "id": str(artifact_id),
        "revision": 1,
        "hash": "a" * 64,
        "owner_id": str(actor),
        "visibility": "category",
        "original": {"id": str(original_id), "epoch": 2},
    }
    actual = SimpleNamespace(
        id=artifact_id,
        revision=1,
        status="withdrawn" if fault == "withdrawn" else "active",
        content_hash="a" * 64,
        owner_id=actor,
        visibility="category",
        original_id=original_id,
        product_id=pid,
    )

    class SQL:
        def execute(self, statement):
            assert "content" not in statement.selected_columns.keys()
            assert tenant in statement.compile().params.values()
            assert category in statement.compile().params.values()
            assert artifact_id in statement.compile().params.values()
            return SimpleNamespace(first=lambda: actual)

        def scalar(self, statement):
            assert original_id in statement.compile().params.values()
            return SimpleNamespace(epoch=3, source_state="active", disposition="active")

    with pytest.raises(DomainError) as error:
        owner.sources_current(SQL(), ctx, pid, {"artifacts": [expected]})
    assert error.value.reason == "SOURCE_UNAVAILABLE"
