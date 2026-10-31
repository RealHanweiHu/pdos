# ruff: noqa: F811 -- pytest imports fixtures by name
from test_project_first_plan import accepted, cmd, definition, post, project  # noqa: F401

from pdos_next.domain.project_governance.rules import aggregate, health


def get(setup, project):
    response = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/projects/{project}/governance",
        headers=setup.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def command(setup, definition, project, operation, revision, **fields):
    value = cmd(
        setup,
        operation,
        {
            "project_id": project,
            "expected_project_revision": 1,
            "expected_governance_revision": revision,
            "reason": "核对合成项目实际资料后办理",
            **fields,
        },
        definition[0],
    )
    return value


def test_adopt_review_decide_and_next_stage_not_block_current(setup, definition, project):
    original = get(setup, project)
    assert original["current_stage"] is None and original["health"]["state"] == "unknown"
    adopt = command(setup, definition, project, "work.stage.adopt", 0, template="standard@1")
    adopted, _ = accepted(setup, adopt)
    current = get(setup, project)
    assert current["current_stage"]["key"] == "concept"
    assert current["gate"]["state"] == "READY"
    assert current["next_gate"]["state"] == "READY"
    review = command(
        setup,
        definition,
        project,
        "work.stage.review.submit",
        1,
        stage_id=current["current_stage"]["id"],
    )
    submitted, _ = accepted(setup, review)
    current = get(setup, project)
    assert current["review"]["id"] == submitted["subject_id"]
    assert current["health"]["state"] == "pending_approval"
    decide = command(
        setup,
        definition,
        project,
        "work.stage.decide",
        2,
        review={"id": submitted["subject_id"], "revision": 2},
        outcome="approved",
    )
    approved, confirmed = accepted(setup, decide)
    assert post(setup, confirmed).json()["id"] == approved["id"]
    current = get(setup, project)
    assert current["current_stage"]["key"] == "planning"
    assert current["stages"][0]["status"] == "passed"
    assert current["stages"][0]["actual"] is not None
    assert current["health"]["state"] == "unknown"
    assert len(current["history"]) == 3
    stale = command(setup, definition, project, "work.stage.adopt", 0, template="small-change@1")
    assert post(setup, stale, True).status_code == 409


def test_unknown_gate_cannot_be_approved_and_peer_cannot_adopt(setup, definition, project):
    adopt = command(setup, definition, project, "work.stage.adopt", 0, template="small-change@1")
    accepted(setup, adopt)
    current = get(setup, project)
    submitted, _ = accepted(
        setup,
        command(
            setup,
            definition,
            project,
            "work.stage.review.submit",
            1,
            stage_id=current["current_stage"]["id"],
        ),
    )
    decide = command(
        setup,
        definition,
        project,
        "work.stage.decide",
        2,
        review={"id": submitted["subject_id"], "revision": 2},
        outcome="approved",
    )
    assert post(setup, decide, True).status_code == 409
    decide["payload"]["outcome"] = "returned"
    accepted(setup, decide)
    assert get(setup, project)["current_stage"]["key"] == "planning"


def test_fixed_health_priority():
    assert aggregate(["UNKNOWN", "BLOCKED"]) == "BLOCKED"
    assert aggregate(["READY", "UNKNOWN"]) == "UNKNOWN"
    assert health(gate_state="BLOCKED", overdue=1, pending=True, adopted=True)["state"] == "blocked"
    assert health(gate_state="UNKNOWN", overdue=1, pending=True, adopted=True)["state"] == "unknown"
    assert health(gate_state="READY", overdue=1, pending=True, adopted=True)["state"] == "risk"


def test_baseline_binding_and_directory_share_facts(setup, definition, project):
    from test_project_first_plan import proposal_command

    proposed = proposal_command(setup, definition, project)
    for task in proposed["payload"]["schedule"]["tasks"]:
        task.update(
            duration_min_minutes=60,
            duration_max_minutes=120,
            estimate_source="Synthetic bounded estimate",
        )
    candidate = post(setup, proposed)
    assert candidate.status_code == 200, candidate.text
    plan, _ = accepted(
        setup,
        cmd(
            setup,
            "work.plan.apply",
            {
                "project_id": project,
                "proposal_id": candidate.json()["subject_id"],
                "expected_project_revision": 1,
            },
            definition[0],
        ),
    )

    def change(op, rev, **fields):
        value = command(setup, definition, project, op, rev, **fields)
        value["payload"]["expected_project_revision"] = 2
        return value

    accepted(setup, change("work.stage.adopt", 0, template="small-change@1"))
    current = get(setup, project)
    accepted(
        setup,
        change(
            "work.stage.milestone.bind", 1, stage_id=current["current_stage"]["id"], task_key="eng"
        ),
    )
    accepted(
        setup, change("work.baseline.approve", 2, plan={"id": plan["subject_id"], "revision": 1})
    )
    current = get(setup, project)
    assert current["gate"]["state"] == "READY"
    assert (
        current["timeline"]["baseline"]["latest_finish"]
        == current["timeline"]["forecast"]["latest_finish"]
    )
    personal = setup.client.get(f"/v1/personal/projects/{project}", headers=setup.headers)
    assert personal.status_code == 200, personal.text
    summary = personal.json()["items"][0]["project"]["governance"]
    assert summary["health"] == current["health"]
    assert summary["current_stage"]["id"] == current["current_stage"]["id"]
    assert summary["timeline"] == current["timeline"]
    peer_headers = {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
    denied = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/projects/{project}/governance",
        headers=peer_headers,
    )
    assert denied.status_code == 403

    # Changing a milestone after review invalidates that fixed review, even
    # with the fresh ledger revision. A stage approval is never silently reused.
    submitted, _ = accepted(
        setup, change("work.stage.review.submit", 3, stage_id=current["current_stage"]["id"])
    )
    accepted(
        setup,
        change(
            "work.stage.milestone.bind", 4, stage_id=current["current_stage"]["id"], task_key="npi"
        ),
    )
    stale = change(
        "work.stage.decide",
        5,
        review={"id": submitted["subject_id"], "revision": 4},
        outcome="approved",
    )
    assert post(setup, stale, True).status_code == 409


def test_governance_ledger_is_immutable_and_agent_has_no_write(setup, definition, project):
    import pytest
    from sqlalchemy import func, select, update
    from sqlalchemy.exc import DBAPIError

    from pdos_next.database import tenant_session
    from pdos_next.domain.project_governance.models import GovernanceEvent

    accepted(
        setup, command(setup, definition, project, "work.stage.adopt", 0, template="standard@1")
    )
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        assert (
            s.scalar(
                select(
                    func.has_table_privilege("pdos_agent", GovernanceEvent.__tablename__, "INSERT")
                )
            )
            is False
        )
    with pytest.raises(DBAPIError):
        with tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.human,
            requester_id=setup.human,
            category_id=setup.category,
        ) as s:
            s.execute(update(GovernanceEvent).values(body={"position": 99}))
