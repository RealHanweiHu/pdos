"""Compile the actual authority query and exercise fixed inherited-reference paging."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from pdos_next.enterprise_search import assistant_inheritance as inheritance
from pdos_next.enterprise_search import assistant_scope, query
from pdos_next.enterprise_search.assistant_schemas import AssistantSearchInput, CitationsInput
from pdos_next.service import digest
from tests.agent_kernel.test_context_corrections import case, selection


def test_real_query_applies_fixed_filters_before_all_counts_paging_and_relations(monkeypatch):
    run, ctx, ref = case()
    statements = []
    now = datetime.now(UTC)
    metadata = {
        "incomplete": False,
        "indexed_as_of": now,
        "unsafe_match": False,
        "as_of": now,
        "primary_rows": [],
        "related_rows": [],
    }
    session = SimpleNamespace(
        execute=lambda statement: (
            statements.append(statement)
            or SimpleNamespace(mappings=lambda: SimpleNamespace(one=lambda: metadata))
        )
    )
    scope = {
        "category_id": run.category_id,
        "product_id": uuid4(),
        "project_id": uuid4(),
        "proposal_id": None,
    }
    monkeypatch.setattr(query, "require_context", lambda *_: None)
    monkeypatch.setattr(query, "_narrow", lambda *_: scope)
    monkeypatch.setattr(query, "prepare_read", lambda *_: None)
    family_scopes = []
    monkeypatch.setattr(
        query, "source_families",
        lambda _session, _ctx, _types, selected_scope: (
            family_scopes.append(selected_scope) or (["issue", "capa"], now)
        ),
    )
    monkeypatch.setattr(query, "dependency_originals", lambda *_: set())
    monkeypatch.setattr(query, "safe_originals", lambda *_: set())
    query.search(
        session,
        ctx,
        AssistantSearchInput(query="漏气", include_history=True),
        include_sources=[("issue", ref["source_id"], 2, ref["content_hash"])],
        focus_object=("issue", ref["object_id"]),
        current_only=True,
    )
    assert family_scopes == [{**scope, "product_id": None, "project_id": None}]
    compiled = statements[0].compile(dialect=postgresql.dialect())
    sql = str(compiled)
    authority = sql.split("scoped_authoritative_sources AS MATERIALIZED", 1)[1].split(
        "scoped_enterprise_sources AS",
        1,
    )[0]
    assert ref["source_id"] in str(compiled.params)
    assert ref["content_hash"] in str(compiled.params)
    assert ref["object_id"] in str(compiled.params)
    assert ".object_id =" in authority and ".is_current" in authority
    assert "source_revision" in authority and "content_hash) IN" in authority
    assert sql.index("scoped_authoritative_sources AS MATERIALIZED") < sql.index(
        "enterprise_page AS",
    )
    assert "scoped_authoritative_sources" in sql.split("related_", 1)[-1]


def test_empty_intersection_is_an_empty_sql_allowlist_not_omission(monkeypatch):
    run, ctx, ref = case()
    other = {**ref, "source_id": str(uuid4())}
    condition = selection(ref, focus=None, sources=[ref], version_mode="fixed", versions=[other])
    state = {"context_selection": condition}
    run.versions = {"work_state": state, "work_state_digest": digest(state)}
    captured = []
    session = SimpleNamespace(get=lambda *_: run)
    scope = SimpleNamespace(run_id=run.id, project_id=None, proposal_id=None)
    monkeypatch.setattr("pdos_next.agent_kernel.context_corrections.recheck", lambda *_: condition)
    monkeypatch.setattr(assistant_scope, "_verified", lambda _session, value: value)
    monkeypatch.setattr(
        assistant_scope, "search", lambda *_args, **kwargs: captured.append(kwargs) or {"items": []}
    )
    assistant_scope.retrieve(session, ctx, scope, AssistantSearchInput(query="漏气"))
    assert captured[0]["include_sources"] == set()


@pytest.mark.parametrize("mode", ["current", "fixed"])
def test_inherited_reference_conditions_precede_returned_count_and_cursor(monkeypatch, mode):
    run, _ctx, ref = case()
    old, selected = str(uuid4()), str(uuid4())
    roots = {
        old: (
            str(uuid4()),
            {**ref, "citation_id": old, "source_revision": 1, "content_hash": "b" * 64},
        ),
        selected: (str(uuid4()), {**ref, "citation_id": selected}),
    }
    condition = selection(
        ref, focus=None, version_mode=mode, versions=[ref] if mode == "fixed" else []
    )
    state = {"context_selection": condition}
    run.versions = {"work_state": state, "work_state_digest": digest(state)}
    monkeypatch.setattr(inheritance, "registry", lambda *_: (roots, []))
    monkeypatch.setattr(
        inheritance,
        "current",
        lambda *_args, **_kwargs: (
            {
                old: {"is_current": False, "updated": False, "read_basis_status": "current"},
                selected: {"is_current": True, "updated": False, "read_basis_status": "current"},
            },
            {},
        ),
    )
    page = inheritance.page(None, run, CitationsInput(page_size=1))
    assert page["returned"] == 1 and not page["has_more"] and page["next_cursor"] is None
    assert page["items"][0]["origin_citation_id"] == selected
