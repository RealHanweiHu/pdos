"""Native origins, read-only title hints and the exact existing feedback extension."""

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from migrations.candidates import similar_history_change_origin as ddl
from pdos_next.enterprise_search import similar_history as history
from pdos_next.enterprise_search import similar_history_api as api
from pdos_next.enterprise_search.similar_history_models import SimilarHistoryFeedback as FeedbackRow
from pdos_next.enterprise_search.similar_history_schemas import (
    SimilarHistoryFeedback,
    SimilarHistoryTitleInput,
)
from pdos_next.errors import DomainError
from pdos_next.service import Context
from pydantic import ValidationError


@pytest.mark.parametrize("title", ["", " \n ", "x" * 241, 42, True])
def test_title_lookup_requires_a_real_bounded_human_title(title):
    with pytest.raises(ValidationError):
        SimilarHistoryTitleInput(kind="issue", title=title)


def test_title_lookup_rejects_forged_object_or_authority_and_trims_without_truncating():
    value = SimilarHistoryTitleInput(kind="change", title="  D16 接口漏气  ")
    assert value.title == "D16 接口漏气"
    for extra in ({"version_id": uuid4()}, {"viewer_id": uuid4()}, {"kind": "artifact"}):
        with pytest.raises(ValidationError):
            SimilarHistoryTitleInput.model_validate({**value.model_dump(), **extra})


def test_change_read_uses_only_its_real_snapshot_and_own_registered_exclusions(monkeypatch):
    anchor = SimpleNamespace(request_snapshot={"title": "D16 变更", "reason": "记录原因"})
    selected = []
    monkeypatch.setattr(history, "_human", lambda *_args: None)
    monkeypatch.setattr(history, "_change_anchor", lambda *_args: anchor)
    monkeypatch.setattr(history, "_exclusions", lambda _s, row, **kw:
                        selected.append((row, kw)) or [])
    monkeypatch.setattr(history, "_view", lambda _s, _c, row, query, **kw: (row, query, kw))
    value = history.read_change(None, None, uuid4(), uuid4(), uuid4())
    assert value == (anchor, "D16 变更\n记录原因", {"kind": "change", "exclusions": []})
    assert selected == [(anchor, {"kind": "change"})]
    assert not hasattr(anchor, "issue_id")


@pytest.mark.parametrize("kind", ["issue", "change"])
def test_unsaved_title_has_no_invented_object_version_or_feedback_identity(monkeypatch, kind):
    product = SimpleNamespace(id=uuid4(), category_id=uuid4())
    ctx = SimpleNamespace(tenant_id=uuid4())
    monkeypatch.setattr(history, "_human", lambda *_args: None)
    monkeypatch.setattr(history, "require_access", lambda *_args: product)
    monkeypatch.setattr(history, "_view", lambda _s, _c, row, _query, **kw: (
        history._anchor_view(row, kw["kind"]), row,
    ))
    value, anchor = history.read_title(
        None, ctx, product.id, SimilarHistoryTitleInput(kind=kind, title="接口漏气"),
    )
    assert value == {"kind": kind + "_draft", "title": "接口漏气", "project_id": None,
                     "product_id": str(product.id), "category_id": str(product.category_id)}
    assert anchor.id is None and not hasattr(anchor, "issue_id")
    assert not {"version_id", "revision", "object_id", "feedback_id"} & value.keys()


@pytest.mark.parametrize("kind,allowed", [("issue", True), ("change", False),
                                         ("issue_draft", False), ("change_draft", False)])
def test_only_saved_issue_can_offer_merge_even_when_candidate_is_an_open_issue(
    monkeypatch, kind, allowed,
):
    tenant, category, product, project, candidate = [uuid4() for _ in range(5)]
    anchor = SimpleNamespace(
        id=uuid4(), tenant_id=tenant, category_id=category, product_id=product, project_id=project,
        revision=1, issue_id=uuid4(), issue_snapshot={"title": "当前问题"},
        change_id=uuid4(), request_snapshot={"title": "当前变更"}, title="尚未保存的标题",
    )
    snapshot = {"status": "open"}
    source = {"source_type": "issue", "source_id": str(candidate), "product_id": str(product),
              "project_id": str(project), "category_id": str(category), "object_id": str(uuid4()),
              "source_revision": 1, "content_hash": "a" * 64, "title": "候选问题",
              "channel": "keyword", "is_current": True, "read_basis_status": "current"}
    record = {**source, "source_id": candidate, "structured": {"facts": {"status": "open"}}}
    session = SimpleNamespace(
        execute=lambda *_args: SimpleNamespace(mappings=lambda: [record]),
        scalars=lambda *_args: [SimpleNamespace(id=candidate, issue_snapshot=snapshot)],
    )
    monkeypatch.setattr(history, "search", lambda *_a, **_kw: {
        "items": [source], "as_of": "2026-10-29T00:00:00+00:00",
        "coverage": {"status": "current"}, "ranking_version": "actual-server-ranking",
    })
    monkeypatch.setattr(history, "structural_context", lambda *_a: {
        "parts": {}, "builds": {}, "stages": {},
    })
    monkeypatch.setattr(history, "_names", lambda *_a: {})
    monkeypatch.setattr(history, "links", lambda *_a: {})
    value = history._view(session, SimpleNamespace(tenant_id=tenant, category_id=category),
                          anchor, "接口漏气", kind=kind)
    assert value["items"][0]["can_prepare_merge"] is allowed
    assert "待复验" in value["items"][0]["verification"]
    assert "issue_snapshot" not in str(value)


def test_change_feedback_keeps_exact_native_change_origin_and_original_idempotency(monkeypatch):
    tenant, human, category, product, change, version, candidate = [uuid4() for _ in range(7)]
    ctx = Context(tenant, human, human, category_id=category)
    view = {"anchor": {"project_id": str(uuid4()), "revision": 2},
            "ranking_version": "server-ranking", "items": [{"kind": "change",
                "source_id": str(candidate), "source_revision": 1, "can_prepare_merge": False}]}
    monkeypatch.setattr(history, "_human", lambda *_a: None)
    monkeypatch.setattr(history, "read_change", lambda *_a: view)
    stored = []
    session = SimpleNamespace(execute=lambda *_a: None,
        scalar=lambda *_a: stored[0] if stored else None,
        add=stored.append, flush=lambda: setattr(stored[-1], "id", uuid4()))
    data = SimilarHistoryFeedback(version_id=version, candidate_kind="change",
        candidate_source_id=candidate, candidate_revision=1,
        action="not_relevant", request_key=uuid4())
    saved = history.feedback_change(session, ctx, product, change, data)
    row = stored[0]
    assert (row.change_id, row.change_version_id, row.change_revision) == (change, version, 2)
    assert (row.issue_id, row.issue_version_id, row.issue_revision) == (None, None, None)
    assert history.feedback_change(session, ctx, product, change, data) == saved
    assert len(stored) == 1
    with pytest.raises(DomainError) as denied:
        history.feedback_change(session, ctx, product, change,
                                data.model_copy(update={"action": "merge_prepared"}))
    assert denied.value.code == "FORBIDDEN_SCOPE" and len(stored) == 1
    with pytest.raises(DomainError) as conflict:
        history.feedback_change(session, ctx, product, uuid4(), data)
    assert conflict.value.code == "VERSION_CONFLICT"


def test_title_route_is_readonly_and_has_no_unsaved_feedback_post(monkeypatch):
    calls = []
    @contextmanager
    def transaction(_engine, _tenant, **kwargs):
        assert kwargs["read_snapshot"] is True
        yield None
    monkeypatch.setattr(api, "tenant_session", transaction)
    monkeypatch.setattr(api, "read_title", lambda _s, _c, product, data: calls.append(
        (product, data.model_dump()),
    ) or {"items": []})
    ctx = Context(uuid4(), uuid4(), uuid4(), category_id=uuid4())
    app = FastAPI()
    api.register_routes(app, None, Depends(lambda: ctx))
    path = f"/v1/categories/{ctx.category_id}/products/{uuid4()}/similar-history"
    with TestClient(app) as client:
        result = client.get(path, params={"kind": "issue", "title": "  接口漏气  "})
        assert result.status_code == 200 and calls[-1][1]["title"] == "接口漏气"
        assert client.get(path, params={"kind": "change", "title": " "}).status_code == 422
        assert client.post(path + "/feedback", json={}).status_code == 404
    assert len(calls) == 1


def test_existing_table_extension_is_exact_and_preserves_legacy_policy_and_acl():
    sql, down = "\n".join(ddl.SCHEMA_SQL), "\n".join(ddl.DOWNGRADE_SQL)
    assert "CREATE TABLE" not in sql and "GRANT" not in sql and "DROP POLICY" not in sql
    assert sql.count("ALTER POLICY") == 2 and "kernel_append_only" not in sql
    assert "change_request_versions(tenant_id,product_id,change_id,id,revision)" in sql
    assert "action<>'merge_prepared'" in ddl.ORIGIN_CHECK
    for prefix in ("issue", "change"):
        for suffix in ("_id", "_version_id", "_revision"):
            assert prefix + suffix + " IS NOT NULL" in ddl.ORIGIN_CHECK
            assert prefix + suffix + " IS NULL" in ddl.ORIGIN_CHECK
    assert "WHERE change_id IS NOT NULL" in "\n".join(ddl.EMPTY_HISTORY_SQL)
    assert down.index("RAISE EXCEPTION") < down.index("DROP COLUMN")
    assert ddl.ISSUE_HUMAN in down and "FORCE ROW LEVEL SECURITY" in down
    columns = FeedbackRow.__table__.columns
    assert all(columns[name].nullable for name in (
        "issue_id", "issue_version_id", "issue_revision", "change_id", "change_version_id",
        "change_revision",
    ))
    assert not columns["project_id"].nullable
