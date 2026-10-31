"""Fallback eligibility uses actual valid candidates and a frozen human choice."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.agent_kernel.search_preferences import SearchPreferences
from pdos_next.agent_kernel.work_state import ChangeInput
from pdos_next.enterprise_search import assistant_scope as policy
from pdos_next.enterprise_search.assistant_schemas import AssistantSearchInput
from pdos_next.service import digest


@pytest.mark.parametrize("count,invalid,mode,calls", [
    (3, False, "same_category", 1), (3, True, "same_category", 2),
    (2, False, "current", 1), (0, False, "same_category", 2),
])
def test_threshold_follows_source_recheck_and_never_changes_model_selectors(
    monkeypatch, count, invalid, mode, calls
):
    category, project, product = uuid4(), uuid4(), uuid4()
    state = {"search_preferences": {"scope": mode, "include_customer_private": False}}
    run = SimpleNamespace(versions={"work_state": state, "work_state_digest": digest(state)})
    session = SimpleNamespace(get=lambda *_args: run)
    scope = SimpleNamespace(project_id=project, proposal_id=None, run_id=uuid4())
    data = AssistantSearchInput(query="漏气", product_id=product, project_id=project)
    invoked = []

    def search(_session, _ctx, query, **options):
        invoked.append((query, options))
        amount = count if len(invoked) == 1 else 1
        items = [{"source_type": "issue", "source_id": str(uuid4()), "channel": "keyword",
                  "private": False, "customer_original": False, "bad": invalid and i == 0}
                 for i in range(amount)]
        return {"items": items, "returned": amount, "direct_returned": amount,
                "related_returned": 0, "truncated": False, "related_truncated": False,
                "scope": {"category_id": str(category)},
                "coverage": {"status": "current", "notice": None, "indexed_as_of": None}}

    monkeypatch.setattr(policy, "search", search)
    monkeypatch.setattr(policy, "current", lambda _s, rows: (
        {key: item for key, item in rows.items() if not item["bad"]},
        {key: "unavailable" for key, item in rows.items() if item["bad"]},
    ))
    result = policy.retrieve(session, object(), scope, data)
    assert len(invoked) == calls
    assert data.project_id == project and data.product_id == product
    if calls == 2:
        query, options = invoked[-1]
        assert query.category_id == category and query.project_id is query.product_id is None
        assert options["exclude_project"] == project
        assert options["allow_customer_private"] is False
        assert len(options["exclude_sources"]) == count - int(invalid)
        assert [group["id"] for group in result["groups"]] == ["current", "same_category"]
    if invalid:
        assert result["coverage"]["status"] == "partial"


def test_lookup_choices_are_strict_human_fields_and_not_model_tool_arguments():
    with pytest.raises(ValidationError):
        SearchPreferences(include_customer_private="true")
    with pytest.raises(ValidationError):
        AssistantSearchInput(query="漏气", search_preferences={"scope": "same_category"})
    base = {"expected_revision": 1, "request_key": str(uuid4())}
    for fields in (
        {"action": "set_search_scope", "item_id": str(uuid4())},
        {"action": "remove_constraint", "item_id": str(uuid4()),
         "search_preferences": {"scope": "current"}},
    ):
        with pytest.raises(ValidationError):
            ChangeInput(**base, **fields)
