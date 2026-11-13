"""Single-project overview and manager cockpit over real G0 projects (D37 ⑦, D76, D41).

Read-only projections: every fact comes from public commands; nothing is inserted
directly. Covers reader-scoped filtering (outsider, removed member, other tenant),
named owners on 需要办理, same-source health between list and cockpit, comparison by
exit conditions instead of tasks, and the honest "阶段节点未建" placeholder.
"""

# ruff: noqa: F811 -- pytest imports fixtures by name
import json
from uuid import UUID, uuid4

from g0_fixture import add_category_human, create_g0_project
from team_fixture import remove_member

from projects.test_project_first_plan import accepted, definition, project  # noqa: F401
from projects.test_project_governance import command
from projects.work_pg.test_workflow import (  # noqa: F401
    ASSIGN,
    CREATE,
    execute,
    original_security_work,
    payload,
    task,
    work,
)

COCKPIT = "/v1/personal/project-cockpit"


def auth(setup, person):
    return {"Authorization": f"Bearer {setup.tokens[person]}"}


def overview_path(setup, product, project_id):
    return f"/v1/categories/{setup.category}/products/{product}/projects/{project_id}/overview"


def read_overview(setup, product, project_id, person, *, expect=200):
    response = setup.client.get(
        overview_path(setup, product, project_id), headers=auth(setup, person)
    )
    assert response.status_code == expect, response.text
    return response.json()


def read_cockpit(setup, person):
    response = setup.client.get(COCKPIT, headers=auth(setup, person))
    assert response.status_code == 200, response.text
    return response.json()


def row_for(cockpit, project_id):
    return next((row for row in cockpit["items"] if row["project"]["id"] == str(project_id)), None)


def test_overview_names_owners_of_open_work_and_admits_missing_stage_nodes(work):
    setup = work.setup
    created = execute(
        work,
        CREATE,
        payload(
            work,
            title="Synthetic drawing delivery",
            goal="Deliver a reviewable drawing",
            outcomes=[{"key": "drawing", "text": "Fixed drawing outcome", "required": True}],
            plan_task=None,
        ),
    )[1]
    work.task_id = UUID(created["result"]["task_id"])
    execute(
        work,
        ASSIGN,
        payload(
            work,
            task=task(work, "proposed"),
            assignee_id=str(setup.peer),
            recipient_id=str(setup.human),
        ),
    )

    view = read_overview(setup, setup.product, work.project_id, setup.human)
    assert view["version"] == "project-overview/v1"
    assert view["project"]["owner"]["id"] == str(setup.human)
    # No stage template: health is the rule's 待核对, never 正常, and it names its rule.
    assert view["stage"]["available"] is False and view["stage"]["reason"] == "尚未采用阶段模板"
    assert (view["health"]["label"], view["health"]["rule"]["id"]) == (
        "待核对",
        "project.health.unknown",
    )
    assert view["health"]["basis"]["stage_adopted"] is False
    # Exit outcomes depend on stage nodes that do not exist yet: said, not invented.
    outcomes = view["next_node"]["exit_outcomes"]
    assert outcomes == {
        "available": False,
        "label": "阶段节点未建",
        "reason": outcomes["reason"],
    }
    assert "D36" in outcomes["reason"]
    # 需要办理: the assigned task waits for its named assignee.
    items = view["actions"]["items"]
    receive = [item for item in items if item["type"] == "task_assigned"]
    assert len(receive) == 1
    assert receive[0]["kind_label"] == "待接收"
    assert receive[0]["responsible"] == {"id": str(setup.peer), "name": "Synthetic peer"}
    assert receive[0]["source"]["id"] == str(work.task_id)
    assert receive[0]["target"]["view"] == "tasks"
    # Team load counts the open task for its assignee; hours are never summed.
    members = {m["principal_id"]: m for m in view["team"]["members"]}
    assert members[str(setup.human)]["is_owner"] is True
    assert "工时未知" in view["team"]["load_note"]
    # Read-only duty summary and an unconnected update cycle, both explicit.
    assert view["agent_duty"]["counts_as_todo"] is False
    assert view["agent_duty"]["revocable"] is False
    assert view["status_update"]["cycle"]["available"] is False
    assert {rule["id"] for rule in view["rules"]} >= {
        "cockpit.actions",
        "cockpit.slip",
        "cockpit.due_soon",
        "project.health.unknown",
    }

    # The assignee reads the same item under their own scope; another tenant reads nothing.
    peer_view = read_overview(setup, setup.product, work.project_id, setup.peer)
    assert [i["source"]["id"] for i in peer_view["actions"]["items"]] == [
        i["source"]["id"] for i in items
    ]
    response = setup.client.get(
        overview_path(setup, setup.product, work.project_id), headers=auth(setup, setup.other_human)
    )
    assert response.status_code in {403, 404}


def test_private_project_overview_and_cockpit_follow_the_readers_audience(setup):
    project = create_g0_project(setup, visibility="private", name="Synthetic private cockpit")
    outsider = add_category_human(setup, name="合成品类成员")

    owner_cockpit = read_cockpit(setup, setup.human)
    assert row_for(owner_cockpit, project.project_id) is not None
    # A category member outside the private project sees neither view.
    read_overview(setup, project.product_id, project.project_id, outsider, expect=403)
    assert row_for(read_cockpit(setup, outsider), project.project_id) is None

    # The G0 reviewer is a member; once removed, both views drop the project at once.
    assert row_for(read_cockpit(setup, setup.peer), project.project_id) is not None
    remove_member(setup, project.project_id, setup.peer)
    read_overview(setup, project.product_id, project.project_id, setup.peer, expect=403)
    assert row_for(read_cockpit(setup, setup.peer), project.project_id) is None


def test_cockpit_compares_exit_conditions_from_the_list_source(setup, definition, project):
    adopted, _ = accepted(
        setup, command(setup, definition, project, "work.stage.adopt", 0, template="standard@1")
    )
    governance = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/projects/{project}/governance",
        headers=setup.headers,
    ).json()
    accepted(
        setup,
        command(
            setup,
            definition,
            project,
            "work.stage.review.submit",
            1,
            stage_id=governance["current_stage"]["id"],
        ),
    )
    listed = setup.client.get(f"/v1/personal/projects/{project}", headers=setup.headers).json()
    list_governance = listed["items"][0]["project"]["governance"]

    cockpit = read_cockpit(setup, setup.human)
    row = row_for(cockpit, project)
    # Same source as the project list: identical health, stage and exit conditions.
    assert row["health"] == list_governance["health"]
    assert row["health"]["label"] == "待批准"
    assert row["health"]["rule"] == {"id": "project.health.pending_approval", "version": 1}
    assert row["stage"]["current"] == list_governance["current_stage"]["name"]
    assert [(c["key"], c["state"]) for c in row["exit_conditions"]] == [
        (c["key"], c["state"]) for c in list_governance["exit_conditions"]
    ]
    assert row["exit_conditions"] and all(c["state_label"] for c in row["exit_conditions"])
    assert row["exit_outcomes"] == {"available": False, "label": "阶段节点未建"}
    # Compared by exit outcome, never by tasks or ratios (D76, P61-3).
    text = json.dumps(row, ensure_ascii=False)
    assert "task" not in json.dumps(list(row)) and "%" not in text
    # Only the project owner decides a stage: it is "my decision" for the owner alone.
    assert row["review_pending"] is True and row["my_decision"] is True
    assert cockpit["summary"]["my_stage_decisions"] == 1
    pending = next(h for h in cockpit["summary"]["health"] if h["state"] == "pending_approval")
    assert pending["count"] >= 1
    for metric in ("resource_conflicts", "status_updates_missing", "agent_exceptions"):
        assert cockpit["summary"][metric]["available"] is False
    peer = read_cockpit(setup, setup.peer)
    assert row_for(peer, project)["my_decision"] is False
    assert peer["summary"]["my_stage_decisions"] == 0

    # The overview lists the pending stage decision under its named owner.
    view = read_overview(setup, setup.product, project, setup.human)
    decide = [i for i in view["actions"]["items"] if i["type"] == "stage_review"]
    assert len(decide) == 1
    assert decide[0]["kind_label"] == "待决定" and decide[0]["responsible"]["id"] == str(
        setup.human
    )
    assert view["health"]["basis"]["review_pending"] is True
    assert view["stage"]["available"] is True
    assert [s["status"] for s in view["stage"]["stages"]][0] == "current"

    # Moving the project into a set shows on the cockpit row (filter by set).
    saved = setup.client.post(
        "/v1/project-sets",
        headers=setup.headers,
        json={
            "name": "合成驾驶舱项目集",
            "description": "",
            "expected_revision": 0,
            "request_key": str(uuid4()),
        },
    )
    assert saved.status_code == 200, saved.text
    moved = setup.client.post(
        "/v1/project-sets/move",
        headers=setup.headers,
        json={
            "set_id": saved.json()["id"],
            "projects": [{"project_id": str(project), "expected_revision": 0}],
            "request_key": str(uuid4()),
        },
    )
    assert moved.status_code == 200, moved.text
    assert row_for(read_cockpit(setup, setup.human), project)["project"]["set"] == {
        "id": saved.json()["id"],
        "name": "合成驾驶舱项目集",
    }
