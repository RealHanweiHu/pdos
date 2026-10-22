"""Read-only external wait attention contracts; no database or business emulator."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import union_all
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.engine import Engine

from pdos_next import personal_attention
from pdos_next.domain.external_wait.models import ExternalWaitCurrent, ExternalWaitVersion
from pdos_next.domain.work_management.models import BINDING
from pdos_next.personal_attention_common import QUEUES
from pdos_next.personal_attention_external_wait import queries


def sql(value):
    return str(value.compile(dialect=dialect(), compile_kwargs={"literal_binds": True}))


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Attention pure checks must not connect")

    monkeypatch.setattr(Engine, "connect", deny)
    monkeypatch.setattr(Engine, "raw_connection", deny)


@pytest.fixture
def ctx():
    return SimpleNamespace(tenant_id=uuid4(), requester_id=uuid4())


def test_queries_share_common_metadata_columns_and_never_lock_or_write(ctx):
    values = queries(ctx)
    assert len(values) == 2 and isinstance(values, tuple)
    assert tuple(values[0].selected_columns.keys()) == tuple(values[1].selected_columns.keys())
    selected = sql(union_all(*values))
    assert "UNION ALL" in selected
    assert "FOR UPDATE" not in selected
    assert all(word not in selected for word in ("INSERT ", "UPDATE ", "DELETE "))
    assert "command" not in selected and "source_basis" not in selected
    assert "request_content" not in selected and "closure_condition" not in selected
    assert "proposals" not in selected and "originals" not in selected


@pytest.mark.parametrize(
    "queue,count", [("external", 1), ("receive", 1), ("verify", 0), ("decide", 0)]
)
def test_only_the_requested_real_queue_is_selected(ctx, queue, count):
    assert queue in QUEUES
    values = queries(ctx, queue)
    assert len(values) == count
    if values:
        assert f"'{queue}'" in sql(values[0].selected_columns.queue)


@pytest.mark.parametrize("queue", ["external", "receive"])
def test_exact_current_binding_and_stable_wait_identity(ctx, queue):
    query = queries(ctx, queue)[0]
    selected = sql(query)
    current, row = ExternalWaitCurrent.__tablename__, ExternalWaitVersion.__tablename__
    for field in (*BINDING, "wait_id", "revision", "state"):
        assert f"{current}.{field} = {row}.{field}" in selected
    assert f"{current}.version_id = {row}.id" in selected
    assert f"{row}.state = 'open'" in selected
    assert f"{row}.tenant_id = '{ctx.tenant_id}'" in selected
    kind = "external_wait_transfer" if queue == "receive" else "external_wait"
    key = sql(query.selected_columns.key)
    assert f"'{kind}:'" in key and ".wait_id" in key
    assert ".revision" not in key and ".version_id" not in key
    for field, expected in (
        ("source_id", "wait_id"),
        ("version_id", "id"),
        ("recorded_at", "created_at"),
    ):
        assert f"{row}.{expected}" in sql(query.selected_columns[field])
    assert "'project'" in sql(query.selected_columns.target)
    assert "CAST(NULL AS" in sql(query.selected_columns.epoch)
    assert f"{row}.owner_id" in sql(query.selected_columns.owner_id)
    assert f"{row}.visibility" in sql(query.selected_columns.visibility)


def test_current_owner_remains_external_until_pending_transfer_is_accepted(ctx):
    external, receiving = queries(ctx)
    old_owner, next_owner = sql(external.whereclause), sql(receiving.whereclause)
    assert "body ->> 'responsible_id'" in old_owner
    assert "['transfer']" not in old_owner
    assert "body['transfer']) ->> 'to_id'" in next_owner
    assert "body['transfer']) ->> 'request_id'" in next_owner and "IS NOT NULL" in next_owner
    assert str(ctx.requester_id) in old_owner and str(ctx.requester_id) in next_owner
    assert "owner_id = '" not in old_owner and "owner_id = '" not in next_owner


def test_due_is_internal_check_only_and_missing_delivery_never_becomes_success(ctx):
    external, receiving = queries(ctx)
    assert "next_check_at" in sql(external.selected_columns.due_at)
    assert "TIMESTAMP WITH TIME ZONE" in sql(external.selected_columns.due_at)
    assert "CAST(NULL AS" in sql(receiving.selected_columns.due_at)
    for query in (external, receiving):
        assert "内部" in sql(query.selected_columns.reason)
        assert "外部超期" in sql(query.selected_columns.reason) or "对方已超期" in sql(
            query.selected_columns.reason
        )
        details = sql(query.selected_columns.details)
        assert "delivery_state" in details and "delivery_time_basis" in details
        assert "next_check_is_internal" in details and "reply_state" in details
        assert not any(
            inferred in details
            for inferred in ("coalesce", "working_minutes", "overdue", "succeeded")
        )


@pytest.mark.parametrize(
    "queue,kind", [("external", "external_wait"), ("receive", "external_wait_transfer")]
)
def test_common_dto_preserves_null_facts_and_native_source_watermark(ctx, queue, kind):
    stable, version = uuid4(), uuid4()
    at = datetime(2026, 10, 19, 9, tzinfo=UTC)
    row = dict(
        tenant_id=ctx.tenant_id,
        responsible_id=ctx.requester_id,
        queue=queue,
        key=f"{kind}:{stable}",
        kind=kind,
        title="Actual waiting request",
        reason="内部检查安排不代表对方已超期。",
        state="open",
        target="project",
        responsibility="external_wait_responsible"
        if queue == "external"
        else "external_wait_transfer_recipient",
        source_id=stable,
        version_id=version,
        revision=3,
        epoch=None,
        recorded_at=at,
        due_at=None,
        valid_until=None,
        blocked_code=None,
        blocked_message=None,
        responsible_name=None,
        category_id=uuid4(),
        category_name="Actual category",
        product_id=uuid4(),
        product_name="Actual product",
        project_id=uuid4(),
        project_name="Actual project",
        details={
            "delivery_state": None,
            "reply_state": None,
            "next_check_at": None,
            "next_check_is_internal": True,
        },
    )
    result = personal_attention.entry(row, ctx, queue)
    assert result["id"] == f"{kind}:{stable}"
    assert result["source"] == {
        "id": str(stable),
        "version_id": str(version),
        "revision": 3,
        "epoch": None,
    }
    assert result["responsible"] == {"id": str(ctx.requester_id), "name": None}
    assert result["details"] == row["details"] and result["due_at"] is None
    assert result["recorded_at"] == at.isoformat()
