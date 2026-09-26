"""Stage integration: real ID revisions, named approvals, handoff and task execution.

The approved one-task schedule is a database fixture, not an acceptance test of
plan preparation. All ID writes, inbox reads and task transitions use real APIs.
"""

from collections.abc import Mapping
from datetime import datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.roles import Role
from app.db.engine import get_engine
from app.db.schema import tables
from tests.stage_plan_fixtures import seed_formal_task
from tests.test_product_engineering_api import (
    SETUP_PAYLOAD,
    bearer_headers,
    seed_user,
)
from tests.test_product_engineering_api import (
    client as client,
)
from tests.test_product_engineering_api import (
    isolated_product_database as isolated_product_database,
)
from tests.test_projects_api import approved_case, create_project
from tests.test_quality_capa_api import seed_document


def record(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    assert all(isinstance(key, str) for key in value)
    return dict(value)


def test_id_design_delivery_lifecycle(client: TestClient, isolated_product_database: str) -> None:
    setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
    tenant, owner = UUID(setup["tenant"]["id"]), UUID(setup["user"]["id"])
    headers = bearer_headers(client)
    case = approved_case(client, headers, suffix="ID-LIFECYCLE")
    created = create_project(client, headers, case["id"], code="PRJ-ID-LIFECYCLE")
    assert created.status_code == 201, created.text
    project = UUID(created.json()["id"])
    people = {
        slot: seed_user(
            isolated_product_database,
            tenant_id=tenant,
            project_id=project,
            owner_id=owner,
            username=f"id-{slot}",
            role=Role.ENGINEER,
        )
        for slot in ("product", "me", "hw")
    }
    auth = {slot: bearer_headers(client, username=f"id-{slot}") for slot in people}
    document = seed_document(isolated_product_database, tenant, project, owner, filename="id.pdf")
    with get_engine().begin() as connection:
        connection.execute(
            tables.projects.update().where(tables.projects.c.id == project).values(status="active")
        )
        task, node = seed_formal_task(connection, tenant, project, owner, people["me"])
    base = f"/api/projects/{project}/execution/id-design"

    def post(
        path: str, payload: Mapping[str, object], actor: str | None = None
    ) -> dict[str, object]:
        response = client.post(base + path, headers=auth[actor] if actor else headers, json=payload)
        assert response.status_code == 200, response.text
        return record(response.json())

    draft = {
        "request_id": str(uuid4()),
        "expected_version": 0,
        "title": "便携泵外观方案",
        "owner_user_id": str(owner),
        "brief": "握持与便携",
        "envelope": "120×80×50mm",
        "cmf": "哑光橙",
        "layout": "布局v1",
        "interfaces": "USB-C避开握持面",
        "document_id": str(document),
        "reason": "首版方案",
    }
    revision = post("", draft)
    feedback = post(
        f"/revisions/{revision['id']}/feedback",
        {
            "request_id": str(uuid4()),
            "expected_revision_digest": revision["payload_digest"],
            "source_kind": "customer",
            "source_reference": "客户评审纪要2026-ID",
            "topic": "ergonomics",
            "content": "把手加大5mm",
        },
        "product",
    )
    revised = post(
        "",
        {
            **draft,
            "request_id": str(uuid4()),
            "variant_id": revision["variant_id"],
            "expected_version": 1,
            "envelope": "125×80×50mm",
            "reason": "纳入握持反馈",
        },
    )
    post(
        f"/feedback/{feedback['id']}",
        {
            "request_id": str(uuid4()),
            "expected_version": 0,
            "action": "addressed",
            "resolution_revision_id": revised["id"],
            "reason": "按反馈修订包络",
        },
    )
    request = post(
        "/freezes",
        {
            "request_id": str(uuid4()),
            "revision_id": revised["id"],
            "expected_revision_digest": revised["payload_digest"],
            **{f"{slot}_user_id": str(person) for slot, person in people.items()},
            "authority_basis": "项目指定产品、结构及硬件确认人",
            "confirmation_document_id": str(document),
            "reason": "冻结完整交付依据",
        },
    )

    def inbox(actor: str) -> list[dict[str, object]]:
        response = client.get("/api/me/work", headers=auth[actor])
        assert response.status_code == 200, response.text
        actions = record(response.json())["id_design_actions"]
        assert isinstance(actions, list)
        return [record(action) for action in actions]

    def forecast() -> dict[str, object]:
        with get_engine().connect() as connection:
            result = connection.execute(
                select(tables.schedule_forecast_runs.c.result)
                .join(
                    tables.schedule_time_records,
                    tables.schedule_time_records.c.id == tables.schedule_forecast_runs.c.record_id,
                )
                .where(tables.schedule_forecast_runs.c.project_id == project)
                .order_by(tables.schedule_time_records.c.version.desc())
                .limit(1)
            ).scalar_one()
        return record(result)

    for slot in people:
        assert any(row["id"] == request["id"] for row in inbox(slot))
        post(
            f"/freezes/{request['id']}/decisions",
            {
                "request_id": str(uuid4()),
                "expected_digest": request["payload_digest"],
                "slot": slot,
                "action": "approve",
                "reason": "本专业确认可行",
            },
            slot,
        )
    assert all(not inbox(slot) for slot in people)
    apply = {
        "request_id": str(uuid4()),
        "expected_digest": request["payload_digest"],
        "reason": "三方确认后执行冻结",
    }
    freeze = post(f"/freezes/{request['id']}/application", apply)
    assert post(f"/freezes/{request['id']}/application", apply)["id"] == freeze["id"]
    options = client.get(base + "/handoffs", headers=headers)
    assert options.status_code == 200, options.text
    target = next(row for row in options.json()["targets"] if row["node_id"] == str(node))
    handoff = post(
        "/handoffs",
        {
            "request_id": str(uuid4()),
            "freeze_id": freeze["id"],
            "target_node_id": str(node),
            "expected_target_digest": target["target_digest"],
            "receiver_user_id": str(people["me"]),
            "items": [
                {
                    "item_key": "ID-PACKAGE",
                    "title": "冻结设计包",
                    "criteria": "包络、CMF、布局和接口均已核对",
                    "document_id": str(document),
                }
            ],
            "reason": "提交结构详细设计输入",
        },
    )
    assert any(row["id"] == handoff["id"] for row in inbox("me"))
    pending = forecast()
    assert pending["complete"] is False
    pending_nodes = pending["nodes"]
    assert isinstance(pending_nodes, list)
    assert record(pending_nodes[0])["finish"] is None
    task_url = f"/api/projects/{project}/tasks/{task}/transitions"
    started = client.post(task_url, headers=auth["me"], json={"to_status": "in_progress"})
    assert started.status_code == 200, started.text
    premature = client.post(task_url, headers=auth["me"], json={"to_status": "done"})
    assert premature.status_code == 409, premature.text
    data = client.get(base + "/handoffs", headers=auth["me"]).json()
    item = next(row for row in data["items"] if row["handoff_id"] == handoff["id"])
    post(
        f"/handoffs/items/{item['id']}",
        {
            "request_id": str(uuid4()),
            "expected_digest": handoff["payload_digest"],
            "action": "accept",
            "reason": "逐项核对图档与验收条件",
        },
        "me",
    )
    assert not inbox("me")
    completed = client.post(
        task_url,
        headers=auth["me"],
        json={"to_status": "done", "completion_evidence_ref": f"document:{document}"},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "done"
    observed = forecast()
    assert observed["complete"] is True
    observed_nodes = observed["nodes"]
    assert isinstance(observed_nodes, list)
    finish = record(observed_nodes[0])["finish"]
    assert isinstance(finish, str)
    assert datetime.fromisoformat(finish) == datetime.fromisoformat(
        completed.json()["completed_at"]
    )
    final = client.get(base + "/handoffs", headers=headers).json()
    assert final["handoffs"][0]["status"] == "accepted"
    assert final["handoffs"][0]["current"] is True
    with get_engine().connect() as connection:
        revisions = list(
            connection.execute(
                select(tables.id_design_revisions)
                .where(tables.id_design_revisions.c.project_id == project)
                .order_by(tables.id_design_revisions.c.version)
            ).mappings()
        )
        assert [row["envelope"] for row in revisions] == ["120×80×50mm", "125×80×50mm"]
        actuals = list(
            connection.execute(
                select(tables.scheduled_task_observations.c.point).where(
                    tables.scheduled_task_observations.c.task_id == task
                )
            ).scalars()
        )
        assert set(actuals) == {"start", "finish"}
        forecasts = list(
            connection.execute(
                select(tables.schedule_forecast_runs).where(
                    tables.schedule_forecast_runs.c.project_id == project
                )
            ).mappings()
        )
        assert len(forecasts) >= 4
