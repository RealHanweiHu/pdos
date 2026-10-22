"""Offline metadata/guard/route contracts; no DB, scanner, model or object bytes."""

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from pdos_next.agent_kernel import source_views as views
from pdos_next.errors import DomainError
from pdos_next.service import Context


def context():
    actor = uuid4()
    return Context(uuid4(), actor, actor, category_id=uuid4())


def artifact(**changes):
    return SimpleNamespace(
        **{
            "id": uuid4(),
            "revision": 1,
            "title": "Actual registered metadata",
            "product_id": None,
            "status": "active",
            "original_id": None,
            **changes,
        }
    )


def test_page_contract_rejects_unknown_scope_and_malformed_or_unbounded_queries():
    assert views.SourcePage().page_size == 20
    for raw in (
        {"page_size": 0},
        {"page_size": 51},
        {"cursor": "not-a-uuid"},
        {"owner_id": str(uuid4())},
        {"q": "not an enabled source query"},
    ):
        with pytest.raises(ValidationError):
            views.SourcePage.model_validate(raw)


def test_source_query_uses_exact_category_and_optional_product_without_text_columns():
    ctx, product_id = context(), uuid4()
    root = views._query(ctx, None).compile(dialect=postgresql.dialect())
    product = views._query(ctx, product_id).compile(dialect=postgresql.dialect())
    assert "artifact_versions.product_id IS NULL" in str(root)
    assert product_id in product.params.values()
    assert " OR artifact_versions.product_id = " in str(product)
    for query in (root, product):
        assert ctx.tenant_id in query.params.values() and ctx.category_id in query.params.values()
        for column in ("content", "content_hash", "source_label"):
            assert f"artifact_versions.{column}" not in str(query)


def test_head_calls_real_source_guard_with_fixed_expected_artifact_not_original_revision(
    monkeypatch,
):
    row = artifact(original_id=uuid4())
    original = SimpleNamespace(
        id=row.original_id,
        revision=2,
        product_id=None,
        filename="synthetic.txt",
        status="parsed",
        parse_code=None,
        scan_status="clean",
    )
    seen = []

    def guard(_s, ctx, product_id, identity, revision):
        seen.append((ctx, product_id, identity, revision))
        return row

    monkeypatch.setattr(views, "source_for", guard)
    ctx = context()
    value = views._head(object(), ctx, None, row, {original.id: original}, expected_revision=1)
    assert seen == [(ctx, None, row.id, 1)]
    assert value["artifact_revision"] == 1 and value["original"]["revision"] == 2
    assert value["availability"] == {"available": True, "code": None}
    assert set(value) == {
        "artifact_id",
        "artifact_revision",
        "title",
        "product_id",
        "status",
        "original",
        "availability",
    }


def test_expected_version_failure_keeps_readable_head_but_never_claims_current_is_bound(
    monkeypatch,
):
    row = artifact(revision=2)

    def stale(*args):
        assert args[-1] == 1
        raise DomainError("SOURCE_STALE", "Current revision differs")

    monkeypatch.setattr(views, "source_for", stale)
    value = views._head(object(), context(), None, row, {}, expected_revision=1)
    assert value["artifact_revision"] == 2
    assert value["availability"] == {"available": False, "code": "SOURCE_STALE"}


def test_missing_original_fails_closed_without_falling_through_to_full_original_query(monkeypatch):
    monkeypatch.setattr(views, "source_for", lambda *args: pytest.fail("No full Original query"))
    row = artifact(original_id=uuid4())
    value = views._head(object(), context(), None, row, {})
    assert value["original"] is None
    assert value["availability"] == {"available": False, "code": "SOURCE_UNAVAILABLE"}


def test_integrity_faults_are_not_relabelled_as_ordinary_source_unavailability(monkeypatch):
    def corrupt(*_args):
        raise DomainError("INTEGRITY_MISMATCH", "Broken saved source")

    monkeypatch.setattr(views, "source_for", corrupt)
    with pytest.raises(DomainError) as error:
        views._head(object(), context(), None, artifact(), {})
    assert error.value.reason == "INTEGRITY_MISMATCH"


def test_binding_parser_preserves_actual_product_and_rejects_partial_or_duplicate_records():
    identity, product_id = uuid4(), uuid4()
    raw = {"artifact_id": str(identity), "expected_revision": 3, "product_id": str(product_id)}
    assert views._bindings(SimpleNamespace(read_sources=[raw])) == {identity: (3, product_id)}
    for values in (None, [raw, raw], [{"artifact_id": str(identity)}], [{**raw, "extra": True}]):
        with pytest.raises(DomainError) as error:
            views._bindings(SimpleNamespace(read_sources=values))
        assert error.value.reason == "INTEGRITY_MISMATCH"


def test_get_only_router_uses_current_context_and_read_snapshot(monkeypatch):
    seen = []

    @contextmanager
    def transaction(ctx, *, read_snapshot=False):
        assert read_snapshot is True
        yield object()

    def listing(_s, ctx, page):
        seen.append((ctx, page))
        return {"version": "agent-input-sources/v1"}

    def bindings(_s, ctx, identity):
        seen.append((ctx, identity))
        return {"version": "agent-run-source-bindings/v1"}

    monkeypatch.setattr(views, "read_list", listing)
    monkeypatch.setattr(views, "read_bindings", bindings)
    ctx = context()
    app = FastAPI()
    app.include_router(
        views.router(transaction=transaction, context_dependency=Depends(lambda: ctx))
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        path = f"/v1/categories/{ctx.category_id}"
        assert client.get(path + "/agent-input-sources").status_code == 200
        assert seen[-1][0] == ctx
        for params in ({"page_size": 51}, {"unexpected": "x"}):
            assert client.get(path + "/agent-input-sources", params=params).status_code == 422
        assert client.get(path + f"/agent-runs/{uuid4()}/source-bindings").status_code == 200
        assert client.post(path + "/agent-input-sources").status_code == 405
        assert client.get("/v1/personal/agent-input-sources").status_code == 404
