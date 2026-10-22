"""Real G0 projects/first plans and owned runs through personal HTTP projections."""

import json
from copy import copy
from dataclasses import replace
from datetime import timedelta
from time import perf_counter
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from g0_fixture import create_g0_project
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.api import ApiPorts
from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.models import AgentRun
from pdos_next.api import create_app
from pdos_next.models import Artifact, Category, Grant, Receipt, now
from tests.preproject.test_evidence_commands_pg import artifact
from tests.preproject.test_g0 import create, decide_request, save, submit
from tests.preproject.test_g0 import work as work  # noqa: F401
from tests.test_project_first_plan import accepted, application, post, proposal_command


def second_category(setup):
    other = copy(setup)
    other.category = uuid4()
    other.ctx = replace(setup.ctx, category_id=other.category)
    with Session(setup.admin) as session, session.begin():
        session.add(
            Category(
                id=other.category,
                tenant_id=setup.tenant,
                owner_id=setup.human,
                name="Synthetic second category",
                purpose="Cross-category fixture",
            )
        )
        session.flush()
        for principal in (setup.human, setup.peer, setup.agent):
            session.add(
                Grant(
                    tenant_id=setup.tenant,
                    category_id=other.category,
                    principal_id=principal,
                    can_write=True,
                )
            )
    return other


def get(setup, suffix="", *, actor=None):
    return setup.client.get(
        "/v1/personal/projects" + suffix,
        headers={"Authorization": f"Bearer {setup.tokens[actor or setup.human]}"},
    )


def test_actual_cross_category_projects_page_detail_and_no_read_writes(setup):
    first = create_g0_project(copy(setup), name="Synthetic first project")
    other = second_category(setup)
    second = create_g0_project(other, name="Synthetic second project")
    with Session(setup.admin) as session:
        before = session.scalar(select(func.count()).select_from(Receipt))
    statements = []

    def capture(_c, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(setup.engine, "before_cursor_execute", capture)
    started = perf_counter()
    try:
        page = get(setup, "?page_size=1")
    finally:
        event.remove(setup.engine, "before_cursor_execute", capture)
    elapsed_ms = round((perf_counter() - started) * 1000, 2)
    assert page.status_code == 200, page.text
    value = page.json()
    assert value["items"][0]["project"]["id"] == second.project_id
    assert value["items"][0]["category"]["id"] == str(other.category)
    assert value["next_cursor"] and value["unavailable_count"] == 0
    remaining = get(setup, "?page_size=1&cursor=" + value["next_cursor"])
    assert remaining.status_code == 200, remaining.text
    assert remaining.json()["items"][0]["project"]["id"] == first.project_id
    assert remaining.json()["next_cursor"] is None
    detail = get(setup, "/" + first.project_id)
    assert detail.status_code == 200, detail.text
    project = detail.json()["items"][0]["project"]
    assert project["definition"]["id"] == first.definition_id
    assert project["definition"]["revision"] == 1 and project["source_status"] == "current"
    assert project["plan_state"] == "not_created" and project["task_count"] is None
    assert get(setup, actor=setup.other_human).json()["items"] == []
    assert get(setup, "/" + first.project_id, actor=setup.other_human).status_code == 404
    assert not any(
        "definition_specs" in sql
        or "definition_revisions.requirements" in sql
        or "artifact_versions.content" in sql
        for sql in statements
    )
    with Session(setup.admin) as session:
        assert session.scalar(select(func.count()).select_from(Receipt)) == before
    print(
        json.dumps(
            {
                "first_page_ms": elapsed_ms,
                "first_page_sql": len(statements),
                "real_model_calls": 0,
            }
        )
    )


def test_actual_applied_plan_is_projected_without_copying_schedule_inputs(setup):
    g0 = create_g0_project(setup)
    definition = (None, g0.definition_id)
    proposed = post(setup, proposal_command(setup, definition, g0.project_id))
    assert proposed.status_code == 200, proposed.text
    accepted(setup, application(setup, definition, g0.project_id, proposed.json()["subject_id"]))
    response = get(setup, "/" + g0.project_id)
    assert response.status_code == 200, response.text
    project = response.json()["items"][0]["project"]
    assert project["revision"] == 2 and project["plan_state"] == "available"
    assert project["task_count"] == 2 and len(project["work_packages"]) == 2
    assert project["plan"]["forecast"]["latest_finish"] is None
    assert "input_snapshot" not in response.text and "duration_min_minutes" not in response.text


def test_current_source_and_category_revocation_are_visible_on_refresh(setup):
    source = artifact(setup, body="Synthetic portfolio source", visibility="category")
    g0 = create_g0_project(
        setup,
        source={
            "type": "artifact",
            "id": str(source),
            "version": 1,
            "line": 1,
            "quote": "Synthetic portfolio source",
        },
    )
    statements = []

    def capture(_c, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(setup.engine, "before_cursor_execute", capture)
    try:
        assert get(setup).json()["items"][0]["project"]["source_status"] == "current"
    finally:
        event.remove(setup.engine, "before_cursor_execute", capture)
    assert not any(
        "artifact_versions.content" in statement or "definition_specs" in statement
        for statement in statements
    )
    with Session(setup.admin) as session, session.begin():
        session.get(Artifact, source).status = "withdrawn"
    changed = get(setup, "/" + g0.project_id)
    assert changed.status_code == 200, changed.text
    assert changed.json()["items"][0]["project"]["source_status"] == "needs_recheck"
    with Session(setup.admin) as session, session.begin():
        session.scalar(
            select(Grant).where(
                Grant.category_id == setup.category, Grant.principal_id == setup.human
            )
        ).expires_at = now() - timedelta(seconds=1)
    assert get(setup).json()["items"] == []
    assert get(setup, "/" + g0.project_id).status_code == 404


def test_personal_activity_pages_owned_personal_and_category_runs_without_bodies(setup):
    owner = Bootstrap(setup.engine)

    async def dispatch(_reference):
        pass  # Explicit synthetic dispatch only; no worker or provider runs.

    ports = ApiPorts(
        writer_for=owner.writer_for,
        binding_for=owner.binding_for,
        start_workflow=dispatch,
        signal_workflow=dispatch,
        cancel_workflow=dispatch,
    )
    with TestClient(create_app(setup.engine, setup.auth, agent_api_ports=ports)) as client:
        identities = []
        for path in ("/v1/personal/agent-runs", f"/v1/categories/{setup.category}/agent-runs"):
            response = client.post(
                path,
                headers=setup.headers,
                json={"goal": "Synthetic owned activity", "idempotency_key": str(uuid4())},
            )
            assert response.status_code == 202, response.text
            identities.append(response.json()["run_id"])
        other = client.post(
            f"/v1/categories/{setup.category}/agent-runs",
            headers={"Authorization": f"Bearer {setup.tokens[setup.peer]}"},
            json={"goal": "Synthetic peer activity", "idempotency_key": str(uuid4())},
        )
        assert other.status_code == 202, other.text
        # Only synthetic waiting metadata; no model result or qualification is fabricated.
        with Session(setup.admin) as session, session.begin():
            for identity in identities:
                session.get(AgentRun, UUID(identity)).state = "waiting_input"
        result = client.get(
            "/v1/personal/run-activity?waiting=true&page_size=1", headers=setup.headers
        )
        assert result.status_code == 200, result.text
        value = result.json()
        next_page = client.get(
            "/v1/personal/run-activity?waiting=true&page_size=1&cursor=" + value["next_cursor"],
            headers=setup.headers,
        )
        assert next_page.status_code == 200, next_page.text
        rows = value["items"] + next_page.json()["items"]
        assert {row["run_id"] for row in rows} == set(identities)
        assert {row["scope"] for row in rows} == {"personal", "category"}
        assert {row["categoryId"] for row in rows} == {"", str(setup.category)}
        assert "versions" not in result.text and "result" not in result.text
        assert (
            client.get(
                "/v1/personal/run-activity?category_id=" + str(setup.category),
                headers=setup.headers,
            ).status_code
            == 422
        )


def test_named_project_owner_and_assigned_item_keep_actual_g0_audience(work):
    proposal_id, _ = create(work)
    submit(work, proposal_id)
    command = decide_request(work, proposal_id)
    task = next(item for item in command["payload"]["dispositions"] if item["kind"] == "task")
    task["owner_id"] = str(work.human)
    receipt, _ = save(work, command, actor=work.peer)
    response = get(work, "/" + receipt["result"]["project_id"])
    assert response.status_code == 200, response.text
    entry = response.json()["items"][0]
    assert entry["project"]["owner_id"] == str(work.expert)
    assert entry["project"]["owner_name"] == "合成工程专家"
    assert {item["kind"] for item in entry["openItems"]} == {"task", "risk"}
    assert any(
        item["kind"] == "task" and item["owner_id"] == str(work.human)
        for item in entry["openItems"]
    )
