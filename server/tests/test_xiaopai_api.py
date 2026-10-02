"""Shared conversation privacy and durable project follow-up integration."""

# ruff: noqa: F811
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.schema import tables
from app.domain.reminders import ReminderService
from app.domain.xiaopai import XiaopaiService
from tests.test_reminders_api import (  # noqa: F401
    Scope,
    bearer_headers,
    client,
    isolated_reminder_database,
)


def shared(
    client: TestClient, headers: dict[str, str], project: UUID, visibility: str = "project"
) -> str:
    r = client.post(
        "/api/conversations",
        headers=headers,
        json={"project_id": str(project), "request_id": str(uuid4()), "visibility": visibility},
    )
    assert r.status_code == 200, r.text
    return str(r.json()["id"])


def test_shared_history_keeps_private_history_private(
    client: TestClient, isolated_reminder_database: str
) -> None:  # noqa: F811
    scope = Scope(client, isolated_reminder_database)
    try:
        engineer = scope.user("engineer", "engineer")
        scope.user("outsider", "engineer")
        project = scope.project(member_ids=(engineer,))
        owner = bearer_headers(client)
        member = bearer_headers(client, username="engineer")
        outsider = bearer_headers(client, username="outsider")
        cid = shared(client, owner, project)
        private = shared(client, owner, project, "private")
        payload = {
            "request_id": str(uuid4()),
            "expected_context_version": 1,
            "body": "项目接口下周复核",
            "action": "note",
        }
        assert (
            client.post(
                f"/api/conversations/{cid}/messages", headers=member, json=payload
            ).status_code
            == 200
        )
        view = client.get(f"/api/conversations/{cid}", headers=owner)
        assert view.status_code == 200, view.text
        assert view.json()["items"][0]["body"] == payload["body"]
        assert client.get(f"/api/conversations/{private}", headers=member).status_code == 403
        assert client.get(f"/api/conversations/{cid}", headers=outsider).status_code == 403
        assert (
            client.post(
                f"/api/conversations/{cid}/messages", headers=owner, json=payload
            ).status_code
            == 409
        )
        assert (
            client.post(
                f"/api/conversations/{cid}/archive", headers=member, json={"archived": True}
            ).status_code
            == 403
        )
        attachment = {
            "request_id": str(uuid4()),
            "filename": "shared.pdf",
            "size_bytes": 20,
            "sha256": "a" * 64,
        }
        assert (
            client.post(
                f"/api/conversations/{cid}/attachments",
                headers=member,
                json={**attachment, "classification": "restricted"},
            ).status_code
            == 409
        )
        added = client.post(
            f"/api/conversations/{cid}/attachments", headers=member, json=attachment
        )
        assert added.status_code == 200, added.text
        assert client.get(f"/api/conversations/{cid}/attachments", headers=owner).status_code == 200
        assert (
            client.get(f"/api/conversations/{cid}/attachments", headers=outsider).status_code == 403
        )
    finally:
        scope.dispose()


def test_followup_reply_is_not_progress_and_pause_stops_notifications(
    client: TestClient, isolated_reminder_database: str
) -> None:  # noqa: F811
    scope = Scope(client, isolated_reminder_database)
    try:
        engineer = scope.user("engineer", "engineer")
        project = scope.project(member_ids=(engineer,))
        task = scope.task(project, assignee=engineer, due=date(2026, 9, 1), title="确认接口")
        owner, member = bearer_headers(client), bearer_headers(client, username="engineer")
        cid = shared(client, owner, project)
        base = f"/api/projects/{project}/xiaopai"
        payload = {
            "request_id": str(uuid4()),
            "conversation_id": cid,
            "goal": "持续跟进项目交付",
            "timezone": "Asia/Shanghai",
        }
        made = client.post(base + "/delegations", headers=owner, json=payload)
        assert made.status_code == 200, made.text
        d = made.json()
        assert (
            client.post(base + "/delegations", headers=owner, json=payload).json()["id"] == d["id"]
        )
        assert (
            client.post(
                base + "/delegations", headers=owner, json={**payload, "goal": "不同目标"}
            ).status_code
            == 409
        )
        service = XiaopaiService(scope.engine)
        now = datetime.now(UTC) + timedelta(minutes=1)
        service.scan_project(scope.tenant_id, project, now)
        ReminderService(scope.engine).scan(
            tenant_id=scope.tenant_id,
            project_id=project,
            actor_user_id=None,
            as_of=now,
            automatic=True,
        )
        service.scan_project(scope.tenant_id, project, now + timedelta(minutes=1))
        view = client.get(base, headers=member).json()
        f = view["followups"][0]
        assert f["status"] == "waiting_reply"
        assert f["delivered_at"] is not None
        assert view["delegations"][0]["result"]["in_progress"]
        notifications = client.get("/api/me/notifications", headers=member)
        assert notifications.status_code == 200, notifications.text
        assert any(item["policy_key"] == "xiaopai_ask" for item in notifications.json()["items"])
        assert not any(
            item["policy_key"].startswith("task_due_") for item in notifications.json()["items"]
        )
        with scope.engine.begin() as c:
            c.execute(
                tables.project_members.delete().where(
                    tables.project_members.c.project_id == project,
                    tables.project_members.c.user_id == engineer,
                )
            )
        assert client.get(base, headers=member).status_code == 403
        assert not any(
            item["policy_key"].startswith("xiaopai_")
            for item in client.get("/api/me/notifications", headers=member).json()["items"]
        )
        with scope.engine.begin() as c:
            c.execute(
                tables.project_members.insert().values(
                    id=uuid4(),
                    tenant_id=scope.tenant_id,
                    project_id=project,
                    user_id=engineer,
                    added_by_user_id=scope.owner_id,
                )
            )
        deadline = datetime.fromisoformat(f["reply_due_at"])
        service.scan_project(scope.tenant_id, project, deadline + timedelta(seconds=1))
        assert client.get(base, headers=member).json()["followups"][0]["status"] == "no_reply"
        response = {
            "request_id": str(uuid4()),
            "body": "收到",
            "checkpoint_at": (deadline + timedelta(days=1)).isoformat(),
        }
        assert (
            client.post(
                base + f"/followups/{f['id']}/reply", headers=owner, json=response
            ).status_code
            == 403
        )
        reply = client.post(base + f"/followups/{f['id']}/reply", headers=member, json=response)
        assert reply.status_code == 200, reply.text
        assert (
            client.post(
                base + f"/followups/{f['id']}/reply", headers=member, json=response
            ).status_code
            == 200
        )
        service.scan_project(scope.tenant_id, project, deadline + timedelta(days=1, seconds=1))
        view = client.get(base, headers=owner).json()
        assert view["followups"][0]["status"] == "no_progress"
        assert view["delegations"][0]["result"]["unfinished"]
        with scope.engine.connect() as c:
            assert c.execute(
                select(tables.tasks.c.due_date).where(tables.tasks.c.id == task)
            ).scalar_one() == date(2026, 9, 1)
        state = {"request_id": str(uuid4()), "expected_version": d["version"], "status": "paused"}
        assert (
            client.post(
                base + f"/delegations/{d['id']}/state", headers=member, json=state
            ).status_code
            == 403
        )
        assert (
            client.post(
                base + f"/delegations/{d['id']}/state", headers=owner, json=state
            ).status_code
            == 200
        )
        assert (
            client.post(
                base + f"/delegations/{d['id']}/state", headers=owner, json=state
            ).status_code
            == 200
        )
        from app.domain.xiaopai_reminders import specs

        with scope.engine.connect() as c:
            assert specs(c, scope.tenant_id, project, now) == []
    finally:
        scope.dispose()


def test_formal_forecast_and_daily_digest_replay(
    client: TestClient, isolated_reminder_database: str
) -> None:
    from app.domain.schedule_forecasts import (
        ForecastDraft,
        RemainingEstimate,
        capture_basis,
        persist_forecast,
    )
    from tests.stage_plan_fixtures import seed_formal_task
    from tests.test_projects_api import approved_case, create_project

    scope = Scope(client, isolated_reminder_database)
    try:
        owner = bearer_headers(client)
        case = approved_case(client, owner, suffix="PAI-FORECAST")
        created = create_project(client, owner, case["id"], code="PAI-FORECAST")
        assert created.status_code == 201, created.text
        project = UUID(created.json()["id"])
        engineer = scope.user("schedule-engineer", "engineer")
        with scope.engine.begin() as c:
            c.execute(
                tables.projects.update()
                .where(tables.projects.c.id == project)
                .values(status="active")
            )
            c.execute(
                tables.project_members.insert().values(
                    id=uuid4(),
                    tenant_id=scope.tenant_id,
                    project_id=project,
                    user_id=engineer,
                    added_by_user_id=scope.owner_id,
                )
            )
            task, _ = seed_formal_task(c, scope.tenant_id, project, scope.owner_id, engineer)
            original = (
                c.execute(select(tables.tasks).where(tables.tasks.c.id == task)).mappings().one()
            )
            basis = capture_basis(c, scope.tenant_id, project)
            persist_forecast(
                c,
                scope.tenant_id,
                project,
                scope.owner_id,
                ForecastDraft(
                    request_id=uuid4(),
                    expected_basis_digest=basis["basis_digest"],
                    estimates={
                        "ME-DETAIL": RemainingEstimate(
                            remaining_hours="16",
                            remaining_waiting_days=0,
                            basis="负责人核对剩余工作",
                        )
                    },
                    reason="人工估计",
                ),
                basis,
            )
        cid = shared(client, owner, project)
        base = f"/api/projects/{project}/xiaopai"
        made = client.post(
            base + "/delegations",
            headers=owner,
            json={
                "request_id": str(uuid4()),
                "conversation_id": cid,
                "goal": "持续跟进排程",
                "timezone": "UTC",
            },
        )
        assert made.status_code == 200, made.text
        service = XiaopaiService(scope.engine)
        now = datetime.now(UTC).replace(hour=12) + timedelta(days=1)
        service.scan_project(scope.tenant_id, project, now)
        first = client.get(base, headers=owner).json()
        forecast = first["delegations"][0]["result"]["forecast"]
        assert forecast is not None, first
        assert forecast["record_id"]
        service.scan_project(scope.tenant_id, project, now + timedelta(minutes=1))
        second = client.get(base, headers=owner).json()
        assert second["delegations"][0]["result"]["forecast"]["record_id"] == forecast["record_id"]
        assert len([r for r in second["receipts"] if r["kind"] == "daily_digest"]) == 1
        with scope.engine.connect() as c:
            inputs = c.execute(
                select(tables.schedule_forecast_runs.c.inputs).where(
                    tables.schedule_forecast_runs.c.record_id == UUID(forecast["record_id"]),
                )
            ).scalar_one()
            assert inputs["estimates"]["ME-DETAIL"]["remaining_hours"] == "16"
            current = (
                c.execute(select(tables.tasks).where(tables.tasks.c.id == task)).mappings().one()
            )
            assert current["due_date"] == original["due_date"]
            assert current["status"] == original["status"]
            assert (
                c.execute(select(func.count()).select_from(tables.xiaopai_delegations)).scalar_one()
                == 1
            )
    finally:
        scope.dispose()
