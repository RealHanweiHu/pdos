"""Saved Human exclusions narrow fresh direct, fallback and relation retrieval."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next.enterprise_search import assistant_exclusions as exclusions
from pdos_next.enterprise_search import assistant_inheritance as inheritance
from pdos_next.enterprise_search import assistant_scope as policy
from pdos_next.enterprise_search.assistant_schemas import AssistantSearchInput
from pdos_next.errors import DomainError
from pdos_next.service import digest


def test_artifact_exclusions_are_typed_deduplicated_and_need_no_citation_scan(monkeypatch):
    identity = str(uuid4())
    monkeypatch.setattr(inheritance, "registry", lambda *_args, **_kwargs: pytest.fail("scan"))
    value = {"id": identity, "kind": "artifact", "reason": "用户标记不相关"}
    assert exclusions.excluded_sources(None, None, {"exclusions": [value, value]}) == (
        ("artifact", identity),
    )
    assert exclusions.excluded_sources(None, None, {}) == ()


@pytest.mark.parametrize("selector", ["root", "parent_alias", "current_alias"])
def test_citation_exclusion_resolves_real_reissued_identity_to_fixed_source(monkeypatch, selector):
    root_id, parent_id, current_id, cid, source_id = [uuid4() for _ in range(5)]
    item = {"citation_id": str(cid), "source_type": "issue", "source_id": str(source_id),
            "source_revision": 3, "title": "已核对问题"}
    root = (str(root_id), item)
    source = {"updated": False, "is_current": True, "read_basis_status": "current"}
    old_ref = inheritance.preview(parent_id, root, source)
    new_ref = inheritance.preview(current_id, root, source)
    parent_state = {"citations": [old_ref]}
    state = {"citations": [new_ref], "exclusions": [{
        "kind": "citation", "reason": "用户标记不相关", "id": {
            "root": str(cid), "parent_alias": old_ref["citation_id"],
            "current_alias": new_ref["citation_id"],
        }[selector],
    }]}
    parent = SimpleNamespace(id=parent_id, versions={
        "work_state": parent_state, "work_state_digest": digest(parent_state),
    })
    current = SimpleNamespace(id=current_id, versions={
        "work_state": state, "work_state_digest": digest(state),
    })
    original = SimpleNamespace(id=root_id, versions={})

    def registry(_session, actual, *, include_self=False):
        assert actual is current and include_self
        return {str(cid): root}, [current, parent, original]

    monkeypatch.setattr(inheritance, "registry", registry)
    monkeypatch.setattr(inheritance, "scope_for_run", lambda run: run.id)
    monkeypatch.setattr(inheritance.ledger, "completed", lambda *_args, **_kwargs: [])
    before = deepcopy(state)
    assert exclusions.excluded_sources(None, current, state) == (("issue", str(source_id)),)
    assert state == before


def test_unknown_or_foreign_citation_cannot_be_guessed_as_a_source_id(monkeypatch):
    monkeypatch.setattr(inheritance, "registry", lambda *_args, **_kwargs: ({}, []))
    state = {"exclusions": [{"id": str(uuid4()), "kind": "citation"}]}
    with pytest.raises(DomainError) as failure:
        exclusions.excluded_sources(None, SimpleNamespace(), state)
    assert failure.value.code == "SOURCE_UNAVAILABLE"


@pytest.mark.parametrize("entry", [
    {"id": "invalid", "kind": "artifact"}, {"id": str(uuid4()), "kind": "sql"}, {},
])
def test_malformed_frozen_condition_stops_instead_of_silently_dropping_it(entry):
    with pytest.raises(DomainError):
        exclusions.excluded_sources(None, None, {"exclusions": [entry]})


@pytest.mark.parametrize("project", [False, True])
def test_every_fresh_search_and_fallback_gets_exclusions_before_source_recheck(
    monkeypatch, project,
):
    category, project_id, excluded_id, included_id, next_id = [uuid4() for _ in range(5)]
    state = {"exclusions": [{"kind": "artifact", "id": str(excluded_id)}],
             "search_preferences": {"scope": "same_category", "include_customer_private": False}}
    run = SimpleNamespace(versions={"work_state": state, "work_state_digest": digest(state)})
    session = SimpleNamespace(get=lambda *_args: run)
    scope = SimpleNamespace(run_id=uuid4(), project_id=project_id if project else None,
                            proposal_id=None)
    calls, authorized = [], []

    def search(_session, _ctx, data, **options):
        blocked = set(options["exclude_sources"])
        assert ("artifact", str(excluded_id)) in blocked
        calls.append(blocked)
        all_rows = [
            {"source_type": "artifact", "source_id": str(excluded_id), "channel": "relation"},
            {"source_type": "issue", "source_id": str(included_id), "channel": "keyword"},
            {"source_type": "capa", "source_id": str(next_id), "channel": "relation"},
        ]
        items = [{**row, "private": False, "customer_original": False} for row in all_rows
                 if (row["source_type"], row["source_id"]) not in blocked]
        return {"items": items, "returned": len(items), "direct_returned": 1,
                "related_returned": 1, "truncated": False, "related_truncated": False,
                "scope": {"category_id": str(category)},
                "coverage": {"status": "current", "notice": None, "indexed_as_of": None}}

    def current(_session, rows):
        assert all(row["source_id"] != str(excluded_id) for row in rows.values())
        authorized.extend(rows.values())
        return rows, {}

    monkeypatch.setattr(policy, "search", search)
    monkeypatch.setattr(policy, "current", current)
    data = AssistantSearchInput(query="漏气", project_id=scope.project_id)
    result = policy.retrieve(session, object(), scope, data)
    assert all(row["source_id"] != str(excluded_id) for row in result["items"])
    assert len(calls) == (2 if project else 1)
    if project:
        assert {("issue", str(included_id)), ("capa", str(next_id))} <= calls[1]
    assert authorized


def test_changed_frozen_work_state_rejects_before_any_fresh_search(monkeypatch):
    state = {"exclusions": []}
    run = SimpleNamespace(versions={"work_state": state, "work_state_digest": "0" * 64})
    session = SimpleNamespace(get=lambda *_args: run)
    scope = SimpleNamespace(run_id=uuid4(), project_id=None, proposal_id=None)
    monkeypatch.setattr(policy, "search", lambda *_args, **_kwargs: pytest.fail("fresh query"))
    with pytest.raises(DomainError):
        policy.retrieve(session, object(), scope, AssistantSearchInput(query="漏气"))
