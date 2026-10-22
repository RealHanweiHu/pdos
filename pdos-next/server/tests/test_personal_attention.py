"""Attention identities, current-source pagination and strictly read-only scope."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from pdos_next import personal_attention as projection
from pdos_next.personal_attention_api import AttentionPage
from pdos_next.personal_attention_common import columns
from pdos_next.personal_attention_work import queries
from pdos_next.service import Context

AT = datetime(2026, 10, 18, 10, tzinfo=UTC)


def sample(ctx, queue="receive"):
    identity = uuid4()
    return {
        "key": "task:" + str(identity),
        "kind": "task",
        "queue": queue,
        "tenant_id": ctx.tenant_id,
        "source_id": identity,
        "version_id": uuid4(),
        "revision": 4,
        "epoch": None,
        "category_id": uuid4(),
        "category_name": "品类",
        "product_id": uuid4(),
        "product_name": "型号",
        "project_id": uuid4(),
        "project_name": "项目",
        "owner_id": uuid4(),
        "visibility": "category",
        "recorded_at": AT,
        "title": "核对实物结果",
        "reason": "你是指定的成果接收人。",
        "state": "submitted",
        "responsible_id": ctx.requester_id,
        "responsible_name": "本人",
        "responsibility": "named_recipient",
        "target": "project",
        "blocked_code": None,
        "blocked_message": None,
        "due_at": None,
        "valid_until": None,
        "details": {},
    }


@pytest.fixture
def world():
    person = uuid4()
    ctx = Context(uuid4(), person, person)
    state = NS(ctx=ctx, queries=[], anchor=None)
    state.rows = [sample(ctx), sample(ctx)]

    class Session:
        info = {"scope": (ctx.tenant_id, person, person, None), "read_snapshot": True}

        def scalar(self, query):
            state.queries.append(query)
            return AT if query.selected_columns[0].name == "transaction_timestamp" else 2

        def execute(self, query):
            state.queries.append(query)
            assert query.is_select and query._for_update_arg is None
            return (
                NS(
                    mappings=lambda: NS(
                        one_or_none=lambda: state.anchor,
                        __iter__=lambda: iter(state.rows),
                    )
                )
                if query._limit_clause is None
                else NS(mappings=lambda: iter(state.rows))
            )

    state.session = Session()
    return state


def test_current_leaf_sql_does_not_project_frozen_documents():
    ctx = Context(uuid4(), uuid4(), uuid4())
    compiled = [str(q.compile(dialect=postgresql.dialect())) for q in queries(ctx)]
    assert len(compiled) == 3
    for sql in compiled:
        assert "work_task_currents" in sql and "version_id" in sql
        assert "transaction_timestamp" in sql and "grants" in sql
        assert " FOR UPDATE" not in sql and "INSERT " not in sql
    assert "attention_newer_submission" in compiled[-1]
    assert "work_commitment_review_currents" in compiled[-1]
    assert "fulfilled" in str(queries(ctx)[-1].compile(compile_kwargs={"literal_binds": True}))
    assert "work_commitment_currents" in compiled[-1]


@pytest.mark.parametrize(
    "queue,present,absent",
    [
        ("decide", "proposal_submissions", "work_task_versions"),
        ("external", "external_handoff_currents", "verification_formal_requests"),
        ("verify", "work_commitment_currents", "external_handoff_currents"),
        ("receive", "verification_current_formal_requests", "work_commitment_currents"),
    ],
)
def test_group_query_only_constructs_its_actual_domain_sources(world, queue, present, absent):
    sql = str(projection.records(world.ctx, queue).compile(dialect=postgresql.dialect()))
    assert present in sql and absent not in sql


def test_typed_source_columns_have_no_implicit_scope_or_version():
    ctx = Context(uuid4(), uuid4(), uuid4())
    value = columns(
        key="test:" + str(uuid4()),
        kind="test",
        queue="receive",
        tenant_id=ctx.tenant_id,
        source_id=uuid4(),
        category_id=uuid4(),
        recorded_at=AT,
        title="实际标题",
        reason="实际原因",
        state="open",
        responsible_id=ctx.requester_id,
        responsibility="named_assignee",
        target="proposal",
    )
    names = {c.name for c in value}
    assert {"version_id", "revision", "epoch", "due_at", "valid_until"} <= names
    assert "body" not in names and "goal" not in names
    assert len(names) == len(value)
    str(select(*value).compile(dialect=postgresql.dialect()))


def test_items_keep_original_version_unknown_dates_and_blocking_reason(world):
    row = sample(world.ctx, "verify")
    row.update(blocked_code="READ_ONLY", blocked_message="当前只有读取权限。")
    item = projection.entry(row, world.ctx, "verify")
    assert item["source"]["version_id"] == str(row["version_id"])
    assert item["source"]["revision"] == 4 and item["source"]["epoch"] is None
    assert item["due_at"] is item["valid_until"] is None
    assert item["blocked"]["message"] == "当前只有读取权限。"
    assert item["responsible"]["id"] == str(world.ctx.requester_id)


@pytest.mark.parametrize(
    "change",
    [
        {"responsible_id": uuid4()},
        {"tenant_id": uuid4()},
        {"queue": "verify"},
        {"revision": 0},
        {"epoch": True},
        {"project_id": None},
        {"reason": ""},
        {"blocked_code": "READ_ONLY"},
        {"recorded_at": AT.replace(tzinfo=None)},
    ],
)
def test_inconsistent_source_never_becomes_attention(world, change):
    row = sample(world.ctx)
    row.update(change)
    with pytest.raises(projection.DomainError) as failure:
        projection.entry(row, world.ctx, "receive")
    assert failure.value.code == "VERSION_CONFLICT" and failure.value.status == 409


def test_page_is_current_source_based_and_preserves_stable_identity(world):
    result = projection.read(world.session, world.ctx, "receive", page_size=1)
    assert result["total_records"] == 2 and len(result["items"]) == 1
    cursor = result["next_cursor"]
    assert projection._decode(cursor, world.ctx, "receive")[0] == world.rows[0]["key"]
    world.anchor = world.rows[0]
    projection.read(world.session, world.ctx, "receive", cursor, page_size=1)
    world.anchor = dict(world.anchor, revision=5)
    with pytest.raises(projection.DomainError, match="分页来源已变化"):
        projection.read(world.session, world.ctx, "receive", cursor)
    world.anchor = None
    with pytest.raises(projection.DomainError, match="分页来源已变化"):
        projection.read(world.session, world.ctx, "receive", cursor)


def test_cursor_cannot_cross_queue_tenant_or_person(world):
    cursor = projection._cursor(world.ctx, "receive", world.rows[0])
    for ctx, queue in (
        (world.ctx, "verify"),
        (replace(world.ctx, tenant_id=uuid4()), "receive"),
        (replace(world.ctx, requester_id=uuid4()), "receive"),
    ):
        with pytest.raises(projection.DomainError):
            projection._decode(cursor, ctx, queue)


@pytest.mark.parametrize("cursor", ["", "!bad", "[]", "W10", "a" * 2049])
def test_invalid_cursor_is_a_validation_error(world, cursor):
    with pytest.raises(projection.DomainError) as failure:
        projection._decode(cursor, world.ctx, "receive")
    assert failure.value.code == "VALIDATION_FAILED"


@pytest.mark.parametrize(
    "params",
    [
        {"queue": "blocked"},
        {"queue": "receive", "principal_id": str(uuid4())},
        {"queue": "verify", "category_id": str(uuid4())},
        {"queue": "verify", "page_size": 101},
    ],
)
def test_http_query_does_not_accept_client_scope_or_new_queue(params):
    with pytest.raises(ValidationError):
        AttentionPage.model_validate(params)


@pytest.mark.parametrize(
    "change",
    [
        {"read_snapshot": False},
        {"scope": (uuid4(), uuid4(), uuid4(), None)},
    ],
)
def test_attention_never_borrows_a_writable_or_other_persons_transaction(world, change):
    world.session.info = {**world.session.info, **change}
    with pytest.raises(projection.DomainError) as failure:
        projection.read(world.session, world.ctx, "receive")
    assert failure.value.status == 403 and not world.queries


@pytest.mark.parametrize("field", ["agent_run_id", "run_id"])
def test_attention_does_not_expose_a_personal_queue_to_agent_execution(world, field):
    with pytest.raises(projection.DomainError) as failure:
        projection.read(world.session, replace(world.ctx, **{field: uuid4()}), "receive")
    assert failure.value.status == 403 and not world.queries


def test_connection_failure_is_retryable_unavailable_and_never_an_empty_page(world, monkeypatch):
    from fastapi import FastAPI
    from sqlalchemy.exc import OperationalError

    from pdos_next import personal_attention_api as api

    def unavailable(*_args, **_kwargs):
        raise OperationalError("", {}, Exception("synthetic connection exhaustion"))

    monkeypatch.setattr(api, "tenant_session", unavailable)
    app = FastAPI()
    api.register_routes(app, object(), lambda: world.ctx)
    endpoint = next(
        route.endpoint for route in app.routes if route.path == "/v1/personal/attention"
    )
    with pytest.raises(projection.DomainError) as failure:
        endpoint(AttentionPage(queue="receive"), world.ctx)
    assert failure.value.status == 503 and failure.value.code == "SOURCE_UNAVAILABLE"
    assert "items" not in failure.value.payload()
