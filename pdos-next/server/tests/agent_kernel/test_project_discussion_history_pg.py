"""Actual owned project discussion GETs; only root runs the isolated PostgreSQL case."""

from copy import copy

from tests.agent_kernel.test_session_presentation_pg import (
    _base,
    _fixture,
    _list,
    _ok,
    _read,
    _real_run,
    _revoke_peer_project_fixture,
)
from tests.agent_kernel.test_session_views_pg import counts
from tests.g0_fixture import create_g0_project


def test_project_discussions_filter_before_search_paging_and_actual_authority_recheck(setup):
    work = _fixture(setup)
    project = work["project"].project_id
    later = _real_run(setup, project=project, goal="Owned selected project second discussion")
    # G0 updates its caller's product binding. Keep the original project's
    # fixture scope intact for its later exact audience/lifecycle reduction.
    other_setup = copy(setup)
    other_project = create_g0_project(
        other_setup, visibility="category", name="Other readable discussion project",
        purpose="Separate same-category project history without model execution",
    )
    unrelated = _real_run(
        other_setup, project=other_project.project_id,
        goal="Other project must not match this view",
    )
    assert str(setup.product) == work["project"].product_id
    before = counts(setup)
    listing = _ok(_list(setup, project_id=project))
    owned = {work["category"]["session_id"], later["session_id"]}
    assert {row["session_id"] for row in listing["items"]} == owned
    assert listing["scope"]["project_id"] == project
    assert all(row["scope"]["project_id"] == project for row in listing["items"])
    assert work["peer"]["session_id"] not in owned
    assert _ok(_list(setup, project_id=project, q=unrelated["run_id"]))["items"] == []

    first = _ok(_list(setup, project_id=project, page_size=1))
    second = _ok(_list(setup, project_id=project, page_size=1, cursor=first["next_cursor"]))
    assert {first["items"][0]["session_id"], second["items"][0]["session_id"]} == owned
    assert second["next_cursor"] is None
    assert _list(setup, project_id=project, cursor=unrelated["session_id"])["status_code"] == 403

    prefix = _base(setup)
    selected_runs = _ok(_read(
        setup, prefix + f"/agent-sessions/{later['session_id']}/runs",
        params={"project_id": project},
    ))
    assert selected_runs["session"]["scope"]["project_id"] == project
    assert [row["run_id"] for row in selected_runs["items"]] == [later["run_id"]]
    assert _read(
        setup, prefix + f"/agent-sessions/{unrelated['session_id']}/runs",
        params={"project_id": project},
    )["status_code"] == 404
    assert _read(
        setup, "/v1/personal/agent-conversations", params={"project_id": project},
    )["status_code"] == 403
    assert counts(setup) == before, "all discussion operations above are read-only"

    peer_page = _ok(_list(setup, actor=setup.peer, project_id=project))
    assert [row["session_id"] for row in peer_page["items"]] == [work["peer"]["session_id"]]
    _revoke_peer_project_fixture(setup, project)
    assert _list(setup, actor=setup.peer, project_id=project)["status_code"] == 403
    hidden = _ok(_list(setup, actor=setup.peer))
    assert work["peer"]["session_id"] not in {row["session_id"] for row in hidden["items"]}
    assert {row["session_id"] for row in _ok(_list(setup, project_id=project))["items"]} == owned
