"""A real Issue in another project/product is read under category authority, not model scope."""
# ruff: noqa: F811,F401 -- actual domain fixture dependencies

import json
from types import SimpleNamespace
from uuid import UUID

from pdos_next.agent_kernel.models import AgentRun
from pdos_next.agent_kernel.search_preferences import SearchPreferences, configure_start
from pdos_next.enterprise_search.assistant_scope import retrieve
from pdos_next.enterprise_search.assistant_sources import human_snapshot
from pdos_next.enterprise_search.schemas import SearchInput
from tests.enterprise_search.test_assistant_pg import execute, fixture
from tests.enterprise_search.test_business_sources_pg import (
    NativeClient,
    accepted_work,
    apply_event,
    change_work,
    known_configuration,
    launch_work,
    native_search,
    operational_work,
    quality_work,
    ready_work,
    results_work,
)
from tests.g0_fixture import create_g0_project


def test_actual_other_project_issue_uses_its_own_source_and_current_object_scope(change_work):
    work = change_work
    assert apply_event(work.quality, work.issue_receipt["id"])["processed"] == 2
    before = native_search(work.quality, str(work.issue_id), ["issue"])
    assert before["returned"] == 1, json.dumps(before)
    another = create_g0_project(work.setup, visibility="category")
    person = SimpleNamespace(**{**vars(work.quality), "product": UUID(another.product_id)})
    after = native_search(person, str(work.issue_id), ["issue"])
    assert after["returned"] == 1, json.dumps(after)
    client = NativeClient(str(work.issue_id), ["issue"])
    owner, scope, host, _adapter = fixture(person, client, project_id=UUID(another.project_id))
    with human_snapshot(person.engine, scope) as session:
        preflight = retrieve(session, person.ctx, scope, SearchInput(
            query=str(work.issue_id), source_types=["issue"],
            product_id=person.product, project_id=scope.project_id,
        ))
    assert before["items"][0]["private"] and before["items"][0]["customer_original"], before
    assert preflight["returned"] == 0
    assert preflight["scope_policy"]["fallback_performed"]
    from pdos_next.database import tenant_session

    with tenant_session(person.engine, person.tenant, actor_id=person.human,
                        requester_id=person.human, category_id=person.ctx.category_id) as session:
        configure_start(session, person.ctx, session.get(AgentRun, scope.run_id),
                        SearchPreferences(include_customer_private=True))
    result = execute(owner, scope, host)
    assert result["status"] == "completed", result
    answer = result["result"]["assistant"]
    source = answer["sources"][0]
    assert source["group"] == "same_category"
    assert source["project_id"] == work.config["project"]
    assert source["product_id"] != str(person.product)
    assert str(scope.project_id) == another.project_id and scope.product_id == person.product
    assert "project=" + work.config["project"] in source["object_url"]
    assert [group["returned"] for group in answer["search_groups"]] == [0, 1]
    assert client.calls == 3
