# ruff: noqa: F811 -- pytest imports fixtures by name
from copy import deepcopy

from test_project_first_plan import (  # noqa: F401
    accepted,
    cmd,
    definition,
    post,
    project,
    proposal_command,
)

from pdos_next.domain.projects.resources import conflicts_for


def test_revision_requires_current_base_and_preserves_history(setup, definition, project, engines):
    first = post(setup, proposal_command(setup, definition, project)).json()["subject_id"]
    saved, _ = accepted(
        setup,
        cmd(
            setup,
            "work.plan.apply",
            {"project_id": project, "proposal_id": first, "expected_project_revision": 1},
            definition[0],
        ),
    )
    base = saved["subject_id"]
    revision = proposal_command(setup, definition, project)
    revision["payload"]["expected_project_revision"] = 2
    assert post(setup, revision).status_code == 409
    revision = deepcopy(revision)
    from uuid import uuid4

    revision["command_id"], revision["idempotency_key"] = str(uuid4()), str(uuid4())
    revision["payload"]["base_plan_id"] = base
    revision["payload"]["schedule"]["tasks"][0]["not_before"] = "2026-10-05T01:00:00Z"
    proposal = post(setup, revision)
    assert proposal.status_code == 200, proposal.text
    apply = cmd(
        setup,
        "work.plan.apply",
        {
            "project_id": project,
            "proposal_id": proposal.json()["subject_id"],
            "expected_project_revision": 2,
        },
        definition[0],
    )
    second, confirmed = accepted(setup, apply)
    assert second["result"]["revision"] == 2
    assert post(setup, confirmed).json()["id"] == second["id"]
    view = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/projects/{project}",
        headers=setup.headers,
    ).json()["items"][0]
    assert view["plan"]["id"] == second["subject_id"]
    assert len(view["tasks"][0]["lineage_ids"]) == 2
    # Read old plans through ordinary API candidates, not by rewriting snapshots.
    assert len(view["proposals"]) == 2
    assert view["proposals"][0]["base_plan_id"] == base


def test_capacity_is_peak_not_sum_and_half_open():
    task = {"earliest_start": "2026-10-25T09:00:00Z", "latest_finish": "2026-10-25T12:00:00Z"}
    demand = {"units": 1}
    windows = [{"start": "2026-10-25T08:00:00Z", "finish": "2026-10-25T09:00:00Z", "units": 1}]
    assert conflicts_for(demand, task, windows, 1)["state"] == "unreserved"
    windows = [
        {"start": "2026-10-25T09:00:00Z", "finish": "2026-10-25T10:00:00Z", "units": 1},
        {"start": "2026-10-25T10:00:00Z", "finish": "2026-10-25T11:00:00Z", "units": 1},
    ]
    assert conflicts_for(demand, task, windows, 2)["peak_units"] == "2"
    assert conflicts_for(demand, task, windows, 1)["state"] == "conflict"
    assert conflicts_for(demand, {**task, "latest_finish": None}, windows, 1)["state"] == "unknown"


def test_dependency_proves_tasks_do_not_compete_despite_overlapping_forecast_ranges():
    from pdos_next.domain.projects.resources import sequential

    tasks = {
        "a": {"depends_on": []},
        "b": {"depends_on": ["a"]},
        "c": {"depends_on": ["b"]},
        "parallel": {"depends_on": []},
    }
    assert sequential(tasks, "a", "c")
    assert sequential(tasks, "c", "a")
    assert not sequential(tasks, "a", "parallel")


def test_resource_alternatives_detect_hidden_project_without_leaking_name(
    setup, definition, project
):
    from copy import copy

    from g0_fixture import create_g0_project

    from pdos_next.service import Context

    def proposal(actor, identity, reads, base=None, revision=1, second=False):
        value = proposal_command(actor, definition, identity)
        value["source_read_set"] = reads
        value["payload"]["expected_project_revision"] = revision
        value["payload"]["base_plan_id"] = base
        tasks = value["payload"]["schedule"]["tasks"]
        for task in tasks:
            task["duration_min_minutes"] = 60
            task["duration_max_minutes"] = 60
            task["estimate_source"] = "Synthetic capacity case"
            task["depends_on"] = []
        tasks[1]["not_before"] = "2026-10-05T01:00:00Z" if second else None
        value["payload"]["resource_demands"] = [
            {
                "task_key": task["key"],
                "resource_id": str(setup.human),
                "kind": "person",
                "coordinator_id": str(actor.human),
                "purpose": "Synthetic lab capacity comparison",
                "units": 1,
            }
            for task in tasks
        ]
        result = post(actor, value)
        assert result.status_code == 200, result.text
        return result.json()["subject_id"]

    peer = copy(setup)
    peer.human, peer.peer = setup.peer, setup.human
    peer.headers = {"Authorization": f"Bearer {setup.tokens[peer.human]}"}
    peer.ctx = Context(setup.tenant, peer.human, peer.human, category_id=setup.category)
    hidden = create_g0_project(peer, name="Private secret project never visible")
    hidden_view = peer.client.get(
        f"/v1/categories/{peer.category}/products/{peer.product}/projects/{hidden.project_id}",
        headers=peer.headers,
    ).json()["items"][0]
    hidden_proposal = proposal(peer, hidden.project_id, hidden_view["required_source_read_set"])
    apply = cmd(
        peer,
        "work.plan.apply",
        {
            "project_id": hidden.project_id,
            "proposal_id": hidden_proposal,
            "expected_project_revision": 1,
        },
    )
    apply["source_read_set"] = hidden_view["required_source_read_set"]
    accepted(peer, apply)
    own_view = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/projects/{project}",
        headers=setup.headers,
    ).json()["items"][0]
    candidate = proposal(setup, project, own_view["required_source_read_set"])
    path = (
        f"/v1/categories/{setup.category}/products/{setup.product}"
        f"/projects/{project}/plan-comparison?proposal_id={candidate}"
    )
    result = setup.client.get(path, headers=setup.headers)
    assert result.status_code == 200, result.text
    assert result.json()["resources"]["conflict_count"] == 2
    assert "Private secret project" not in result.text
    assert hidden.project_id not in result.text
    assert "受限项目的计划需求" in result.text
    # A foreign candidate cannot be used to read another project's plan.
    denied = setup.client.get(path.replace(candidate, hidden_proposal), headers=setup.headers)
    assert denied.status_code == 403


def test_mixed_planned_and_reserved_capacity_is_unknown_without_activity_link():
    from pdos_next.domain.projects.resources import compare_capacity

    task = {"earliest_start": "2026-10-25T09:00:00Z", "latest_finish": "2026-10-25T12:00:00Z"}
    window = {"start": task["earliest_start"], "finish": task["latest_finish"], "units": 1}
    windows = [{**window, "source": source} for source in ("plan", "reservation")]
    assert compare_capacity({"units": 1}, task, windows, [], 2)["state"] == "unknown"
    assert compare_capacity({"units": 1}, task, [], [], 2, incomplete=True)["state"] == "unknown"
