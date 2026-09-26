"""Reminder DingTalk dispatch adapter tests (vNext V1-A8, S5-1 gated)."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from threading import Event, current_thread
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Connection, RowMapping, Table, create_engine, event, select

from app.auth.passwords import PasswordService
from app.db.engine import get_engine
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.integrations.dingtalk_delivery import OTO_MESSAGE_URL, DingTalkDeliveryClient
from app.integrations.dingtalk_outbox import (
    DingTalkIntentError,
    DingTalkIntentService,
    OutboxRecord,
)
from app.integrations.reminder_delivery import DispatchOutcome, ReminderDeliveryDispatcher
from app.main import app
from app.settings import get_settings
from tests.db_cleanup import clear_test_tenants

SERVER_ROOT = Path(__file__).resolve().parents[1]
TEST_JWT_SECRET = "test-only-jwt-secret-that-is-at-least-32-bytes"
PASSWORD = "correct horse battery staple"
SETUP_PAYLOAD = {
    "tenant_slug": "beepump",
    "tenant_name": "Beehive Technology",
    "username": "owner",
    "password": PASSWORD,
    "display_name": "Initial Owner",
}
AS_OF = "2026-09-07T12:00:00Z"


@pytest.fixture(autouse=True)
def isolated_dispatch_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    test_url = configured_test_database_url()
    monkeypatch.setenv("DATABASE_URL", test_url)
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("JWT_ISSUER", "pdos-test")
    monkeypatch.setenv("JWT_AUDIENCE", "pdos-test-client")
    monkeypatch.setenv("PDOS_DINGTALK_DELIVERY_ENABLED", "false")
    monkeypatch.setenv("PDOS_REMINDER_QUIET_HOURS", "21:00-08:00")
    monkeypatch.setenv("PDOS_REMINDER_DAILY_DM_CAP", "5")
    get_settings.cache_clear()
    get_engine.cache_clear()
    os.environ["DATABASE_URL"] = test_url
    command.upgrade(Config(str(SERVER_ROOT / "alembic.ini")), "head")
    engine = create_engine(psycopg_database_url(test_url))
    try:
        with engine.begin() as connection:
            clear_test_tenants(connection)
        yield test_url
    finally:
        engine.dispose()
        get_engine().dispose()
        get_engine.cache_clear()
        get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def bearer_headers(client: TestClient, *, username: str = "owner") -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"tenant_slug": "beepump", "username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


class Scope:
    def __init__(self, client: TestClient, database_url: str, *, pool_size: int = 5) -> None:
        setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
        self.tenant_id = UUID(setup["tenant"]["id"])
        self.owner_id = UUID(setup["user"]["id"])
        self.engine = create_engine(
            psycopg_database_url(database_url),
            connect_args={"options": "-c statement_timeout=10000"},
            pool_size=pool_size,
            max_overflow=0,
            pool_timeout=2,
        )

    def dispose(self) -> None:
        self.engine.dispose()

    def _insert(self, table: Table, values: dict[str, Any]) -> UUID:
        row_id: UUID = values.setdefault("id", uuid4())
        values.setdefault("tenant_id", self.tenant_id)
        with self.engine.begin() as connection:
            connection.execute(table.insert(), values)
        return row_id

    def user(self, username: str, role: str) -> UUID:
        return self._insert(
            tables.users,
            {
                "username": username,
                "display_name": username.title(),
                "role": role,
                "password_hash": PasswordService().hash(PASSWORD),
                "is_active": True,
            },
        )

    def bind_dingtalk(self, user_id: UUID, *, staff_id: str) -> None:
        if not getattr(self, "_tenant_bound", False):
            self._insert(
                tables.dingtalk_tenant_bindings,
                {
                    "corp_id": "corp-1",
                    "client_id": "client-1",
                    "robot_code": "robot-1",
                    "oauth_redirect_uri": "https://pdos.example.com/api/dingtalk/oauth",
                    "callback_route_key": "route-1",
                    "status": "active",
                    "configured_by_user_id": self.owner_id,
                },
            )
            self._tenant_bound = True
        self._insert(
            tables.dingtalk_user_bindings,
            {
                "user_id": user_id,
                "corp_id": "corp-1",
                "open_id": f"open-{staff_id}",
                "staff_id": staff_id,
            },
        )

    def project(self, *, member_ids: tuple[UUID, ...], code: str = "DM") -> UUID:
        workflow_id = self._insert(tables.workflows, {"code": f"WF-{code}", "name": "Workflow"})
        project_id = self._insert(
            tables.projects,
            {
                "workflow_id": workflow_id,
                "owner_user_id": self.owner_id,
                "code": f"PRJ-{code}",
                "name": "Dispatch project",
                "status": "active",
            },
        )
        for member_id in (self.owner_id, *member_ids):
            self._insert(
                tables.project_members,
                {
                    "project_id": project_id,
                    "user_id": member_id,
                    "added_by_user_id": self.owner_id,
                },
            )
        return project_id

    def task(self, project_id: UUID, *, assignee: UUID, title: str) -> UUID:
        return self._insert(
            tables.tasks,
            {
                "project_id": project_id,
                "assignee_user_id": assignee,
                "title": title,
                "status": "todo",
            },
        )

    def outbox_rows(self) -> list[RowMapping]:
        with self.engine.connect() as connection:
            return list(
                connection.execute(
                    select(tables.integration_outbox).where(
                        tables.integration_outbox.c.operation == "reminder_dm"
                    )
                )
                .mappings()
                .all()
            )


def fire_reminders(client: TestClient, headers: dict[str, str], project_id: UUID) -> None:
    response = client.post(
        f"/api/projects/{project_id}/reminders/scan?as_of={AS_OF}", headers=headers
    )
    assert response.status_code == 200
    assert response.json()["fired"] >= 1


def dispatch(
    client: TestClient, headers: dict[str, str], project_id: UUID, *, as_of: str = AS_OF
) -> httpx2.Response:
    return client.post(
        f"/api/projects/{project_id}/reminders/dispatch?as_of={as_of}", headers=headers
    )


def test_dispatch_stays_in_manual_state_while_delivery_disabled(
    client: TestClient, isolated_dispatch_database: str
) -> None:
    scope = Scope(client, isolated_dispatch_database)
    try:
        engineer = scope.user("engineer", "engineer")
        scope.bind_dingtalk(engineer, staff_id="staff-eng")
        project_id = scope.project(member_ids=(engineer,))
        scope.task(project_id, assignee=engineer, title="Verify motor sample")
        headers = bearer_headers(client)
        fire_reminders(client, headers, project_id)

        first = dispatch(client, headers, project_id).json()
        assert first == {
            "enqueued": 1,
            "already_enqueued": 0,
            "skipped_unbound": 0,
            "deferred_quiet_hours": 0,
            "capped_recipients": 0,
            "delivery_enabled": False,
        }
        rows = scope.outbox_rows()
        assert len(rows) == 1
        assert rows[0]["status"] == "manual"
        assert rows[0]["last_error_code"] == "DINGTALK_DELIVERY_DISABLED"
        assert rows[0]["payload"]["staff_id"] == "staff-eng"
        assert "[打开我的工作](http://localhost:3000/my-work)" in rows[0]["payload"]["text"]
        with scope.engine.connect() as connection:
            assert (
                connection.execute(
                    select(tables.audit_log.c.actor_user_id).where(
                        tables.audit_log.c.entity_id == rows[0]["id"],
                        tables.audit_log.c.action == "dingtalk.outbox.enqueue",
                    )
                ).scalar_one()
                == scope.owner_id
            )

        second = dispatch(client, headers, project_id).json()
        assert second["enqueued"] == 0
        assert second["already_enqueued"] == 1
        assert len(scope.outbox_rows()) == 1
    finally:
        scope.dispose()


def test_dispatch_skips_recipients_without_binding(
    client: TestClient, isolated_dispatch_database: str
) -> None:
    scope = Scope(client, isolated_dispatch_database)
    try:
        engineer = scope.user("engineer", "engineer")
        project_id = scope.project(member_ids=(engineer,))
        scope.task(project_id, assignee=engineer, title="Unbound task")
        headers = bearer_headers(client)
        fire_reminders(client, headers, project_id)

        result = dispatch(client, headers, project_id).json()
        assert result["skipped_unbound"] == 1
        assert result["enqueued"] == 0
        assert scope.outbox_rows() == []
    finally:
        scope.dispose()


def test_dispatch_enqueues_pending_when_delivery_enabled(
    client: TestClient, isolated_dispatch_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PDOS_DINGTALK_DELIVERY_ENABLED", "true")
    get_settings.cache_clear()
    scope = Scope(client, isolated_dispatch_database)
    try:
        engineer = scope.user("engineer", "engineer")
        scope.bind_dingtalk(engineer, staff_id="staff-eng")
        project_id = scope.project(member_ids=(engineer,))
        scope.task(project_id, assignee=engineer, title="Real delivery task")
        headers = bearer_headers(client)
        fire_reminders(client, headers, project_id)

        result = dispatch(client, headers, project_id).json()
        assert result["delivery_enabled"] is True
        rows = scope.outbox_rows()
        assert len(rows) == 1
        assert rows[0]["status"] == "pending"
        assert rows[0]["last_error_code"] is None
    finally:
        scope.dispose()
        get_settings.cache_clear()


def test_oto_markdown_client_sends_expected_payload() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert str(request.url) == OTO_MESSAGE_URL
        captured.update(json.loads(request.content))
        return httpx2.Response(200, json={"processQueryKey": "query-1"})

    with httpx2.Client(transport=httpx2.MockTransport(handler), trust_env=False) as http:
        result = DingTalkDeliveryClient(http).send_oto_markdown(
            token="token-1",
            robot_code="robot-1",
            staff_id="staff-eng",
            title="PDOS 提醒",
            text="任务今天到期：Verify motor sample",
        )
    assert result.remote_reference == "query-1"
    assert captured["robotCode"] == "robot-1"
    assert captured["userIds"] == ["staff-eng"]
    assert "任务今天到期" in captured["msgParam"]


QUIET_AS_OF = "2026-09-07T14:30:00Z"  # 22:30 Asia/Shanghai — inside 21:00-08:00


def test_dispatch_defers_entirely_inside_quiet_hours(
    client: TestClient, isolated_dispatch_database: str
) -> None:
    scope = Scope(client, isolated_dispatch_database)
    try:
        engineer = scope.user("engineer", "engineer")
        scope.bind_dingtalk(engineer, staff_id="staff-eng")
        project_id = scope.project(member_ids=(engineer,))
        scope.task(project_id, assignee=engineer, title="Verify pump housing")
        headers = bearer_headers(client)
        fire_reminders(client, headers, project_id)

        deferred = dispatch(client, headers, project_id, as_of=QUIET_AS_OF).json()
        assert deferred["enqueued"] == 0
        assert deferred["deferred_quiet_hours"] == 1
        assert scope.outbox_rows() == []

        morning = dispatch(client, headers, project_id).json()
        assert morning["enqueued"] == 1
        assert morning["deferred_quiet_hours"] == 0
        assert len(scope.outbox_rows()) == 1
    finally:
        scope.dispose()


def test_dispatch_caps_daily_dms_per_recipient(
    client: TestClient, isolated_dispatch_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PDOS_REMINDER_DAILY_DM_CAP", "1")
    get_settings.cache_clear()
    # 出箱行的 created_at 用真实时钟，因此 as_of 必须与真实日期同日（10:00 本地，
    # 处于活跃时段），否则日界不匹配会绕过每日上限统计。
    local_tz = timezone(timedelta(hours=8))
    cap_as_of = (
        datetime.now(local_tz)
        .replace(hour=10, minute=0, second=0, microsecond=0)
        .astimezone(UTC)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    scope = Scope(client, isolated_dispatch_database)
    try:
        engineer = scope.user("engineer", "engineer")
        scope.bind_dingtalk(engineer, staff_id="staff-eng")
        project_id = scope.project(member_ids=(engineer,))
        scope.task(project_id, assignee=engineer, title="Check impeller fit")
        scope.task(project_id, assignee=engineer, title="Check seal torque")
        headers = bearer_headers(client)
        fire_reminders(client, headers, project_id)

        outcome = dispatch(client, headers, project_id, as_of=cap_as_of).json()
        assert outcome["enqueued"] == 1
        assert outcome["capped_recipients"] == 1
        assert len(scope.outbox_rows()) == 1

        repeat = dispatch(client, headers, project_id, as_of=cap_as_of).json()
        assert repeat["enqueued"] == 0
        assert repeat["already_enqueued"] == 1
        assert repeat["capped_recipients"] == 1
    finally:
        scope.dispose()
        get_settings.cache_clear()


@pytest.mark.parametrize("pool_size", [1, 5])
def test_automatic_dispatch_records_system_actor_and_replays_idempotently(
    client: TestClient, isolated_dispatch_database: str, pool_size: int
) -> None:
    scope = Scope(client, isolated_dispatch_database, pool_size=pool_size)
    try:
        engineer = scope.user("engineer", "engineer")
        scope.bind_dingtalk(engineer, staff_id="staff-eng")
        project_id = scope.project(member_ids=(engineer,))
        scope.task(project_id, assignee=engineer, title="System reminder")
        fire_reminders(client, bearer_headers(client), project_id)
        dispatcher = ReminderDeliveryDispatcher(scope.engine, get_settings())
        now = datetime.fromisoformat(AS_OF)

        first = dispatcher.dispatch(
            tenant_id=scope.tenant_id,
            project_id=project_id,
            actor_user_id=None,
            now=now,
            automatic=True,
        )
        assert first.enqueued == 1
        assert first.delivery_enabled is False
        rows = scope.outbox_rows()
        assert len(rows) == 1
        assert rows[0]["status"] == "manual"
        with scope.engine.connect() as connection:
            audit = connection.execute(
                select(tables.audit_log.c.actor_user_id, tables.audit_log.c.context).where(
                    tables.audit_log.c.entity_id == rows[0]["id"],
                    tables.audit_log.c.action == "dingtalk.outbox.enqueue",
                )
            ).one()
            assert audit.actor_user_id is None
            assert audit.context == {"operation": "reminder_dm"}
        repeat = dispatcher.dispatch(
            tenant_id=scope.tenant_id,
            project_id=project_id,
            actor_user_id=None,
            now=now,
            automatic=True,
        )
        assert repeat.enqueued == 0
        assert repeat.already_enqueued == 1
        assert len(scope.outbox_rows()) == 1
    finally:
        scope.dispose()


@pytest.mark.parametrize("unavailable", ["archived_project", "suspended_tenant", "other_tenant"])
def test_automatic_dispatch_rechecks_active_scope(
    client: TestClient, isolated_dispatch_database: str, unavailable: str
) -> None:
    scope = Scope(client, isolated_dispatch_database)
    try:
        engineer = scope.user("engineer", "engineer")
        scope.bind_dingtalk(engineer, staff_id="staff-eng")
        project_id = scope.project(member_ids=(engineer,))
        scope.task(project_id, assignee=engineer, title="Stale scheduler project")
        fire_reminders(client, bearer_headers(client), project_id)
        with scope.engine.begin() as connection:
            if unavailable == "archived_project":
                connection.execute(
                    tables.projects.update()
                    .where(tables.projects.c.id == project_id)
                    .values(status="archived")
                )
            elif unavailable == "suspended_tenant":
                connection.execute(
                    tables.tenants.update()
                    .where(tables.tenants.c.id == scope.tenant_id)
                    .values(status="suspended")
                )
        result = ReminderDeliveryDispatcher(scope.engine, get_settings()).dispatch(
            tenant_id=uuid4() if unavailable == "other_tenant" else scope.tenant_id,
            project_id=project_id,
            actor_user_id=None,
            now=datetime.fromisoformat(AS_OF),
            automatic=True,
        )
        assert result.enqueued == 0
        assert result.already_enqueued == 0
        assert result.deferred_quiet_hours == 0
        assert result.capped_recipients == 0
        assert scope.outbox_rows() == []
    finally:
        scope.dispose()


@pytest.mark.parametrize("same_project", [True, False])
@pytest.mark.parametrize("pool_size", [1, 2])
def test_periodic_and_manual_dispatch_serialize_idempotency_and_tenant_daily_cap(
    client: TestClient,
    isolated_dispatch_database: str,
    monkeypatch: pytest.MonkeyPatch,
    same_project: bool,
    pool_size: int,
) -> None:
    monkeypatch.setenv("PDOS_REMINDER_DAILY_DM_CAP", "1")
    get_settings.cache_clear()
    scope = Scope(client, isolated_dispatch_database, pool_size=pool_size)
    first_at_enqueue = Event()
    release_first = Event()
    second_at_lock = Event()
    second_started = Event()
    original_enqueue = DingTalkIntentService.enqueue_reminder_dm

    def hold_first_enqueue(service: DingTalkIntentService, **kwargs: Any) -> OutboxRecord:
        if kwargs["actor_user_id"] is None:
            first_at_enqueue.set()
            assert release_first.wait(10), "test did not release first dispatch"
        return original_enqueue(service, **kwargs)

    def observe_lock(
        connection: Connection,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        if "pg_advisory_xact_lock" in statement and current_thread().name.endswith("_1"):
            second_at_lock.set()

    try:
        engineer = scope.user("engineer", "engineer")
        scope.bind_dingtalk(engineer, staff_id="staff-eng")
        first_project = scope.project(member_ids=(engineer,))
        scope.task(first_project, assignee=engineer, title="Periodic task")
        headers = bearer_headers(client)
        fire_reminders(client, headers, first_project)
        second_project = first_project
        if not same_project:
            second_project = scope.project(member_ids=(engineer,), code="DM-2")
            scope.task(second_project, assignee=engineer, title="Manual task")
            fire_reminders(client, headers, second_project)
        now = datetime.now(timezone(timedelta(hours=8))).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        dispatcher = ReminderDeliveryDispatcher(scope.engine, get_settings())

        def run_manual() -> DispatchOutcome:
            second_started.set()
            return dispatcher.dispatch(
                tenant_id=scope.tenant_id,
                project_id=second_project,
                actor_user_id=scope.owner_id,
                now=now,
            )

        monkeypatch.setattr(DingTalkIntentService, "enqueue_reminder_dm", hold_first_enqueue)
        event.listen(scope.engine, "before_cursor_execute", observe_lock)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(
                dispatcher.dispatch,
                tenant_id=scope.tenant_id,
                project_id=first_project,
                actor_user_id=None,
                now=now,
                automatic=True,
            )
            try:
                assert first_at_enqueue.wait(10), "first dispatch did not reach enqueue"
                second = pool.submit(run_manual)
                assert second_started.wait(10), "manual dispatch did not start"
                if pool_size > 1:
                    assert second_at_lock.wait(10), "manual dispatch did not reach the tenant lock"
                assert not second.done()
            finally:
                release_first.set()
            first_result = first.result(timeout=10)
            second_result = second.result(timeout=10)
        assert first_result.enqueued == 1
        assert second_result.enqueued == 0
        assert second_result.already_enqueued == int(same_project)
        assert second_result.capped_recipients == int(not same_project)
        assert len(scope.outbox_rows()) == 1
        assert scope.outbox_rows()[0]["status"] == "manual"
    finally:
        release_first.set()
        if event.contains(scope.engine, "before_cursor_execute", observe_lock):
            event.remove(scope.engine, "before_cursor_execute", observe_lock)
        scope.dispose()
        get_settings.cache_clear()


def test_dispatch_releases_tenant_lock_after_enqueue_failure(
    client: TestClient, isolated_dispatch_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = Scope(client, isolated_dispatch_database)
    try:
        engineer = scope.user("engineer", "engineer")
        scope.bind_dingtalk(engineer, staff_id="staff-eng")
        project_id = scope.project(member_ids=(engineer,))
        scope.task(project_id, assignee=engineer, title="Retry after local failure")
        fire_reminders(client, bearer_headers(client), project_id)
        dispatcher = ReminderDeliveryDispatcher(scope.engine, get_settings())

        def fail_enqueue(service: DingTalkIntentService, **kwargs: Any) -> OutboxRecord:
            raise DingTalkIntentError("DINGTALK_PUBLIC_BASE_URL_INVALID")

        with monkeypatch.context() as failing:
            failing.setattr(DingTalkIntentService, "enqueue_reminder_dm", fail_enqueue)
            with pytest.raises(DingTalkIntentError, match="DINGTALK_PUBLIC_BASE_URL_INVALID"):
                dispatcher.dispatch(
                    tenant_id=scope.tenant_id,
                    project_id=project_id,
                    actor_user_id=None,
                    now=datetime.fromisoformat(AS_OF),
                    automatic=True,
                )
        assert scope.outbox_rows() == []
        # Reserve the pooled connection that held the failed transaction so the
        # retry must acquire the advisory lock through another database session.
        with scope.engine.connect(), ThreadPoolExecutor(max_workers=1) as pool:
            retry = pool.submit(
                dispatcher.dispatch,
                tenant_id=scope.tenant_id,
                project_id=project_id,
                actor_user_id=None,
                now=datetime.fromisoformat(AS_OF),
                automatic=True,
            )
            assert retry.result(timeout=10).enqueued == 1
        assert len(scope.outbox_rows()) == 1
    finally:
        scope.dispose()


def test_enqueue_reminder_without_caller_connection_still_commits_its_own_transaction(
    client: TestClient, isolated_dispatch_database: str
) -> None:
    scope = Scope(client, isolated_dispatch_database, pool_size=1)
    try:
        engineer = scope.user("engineer", "engineer")
        scope.bind_dingtalk(engineer, staff_id="staff-eng")
        project_id = scope.project(member_ids=(engineer,))
        scope.task(project_id, assignee=engineer, title="Standalone reminder")
        fire_reminders(client, bearer_headers(client), project_id)
        with scope.engine.connect() as connection:
            reminder = connection.execute(
                select(tables.reminders.c.id, tables.reminders.c.title).where(
                    tables.reminders.c.tenant_id == scope.tenant_id,
                    tables.reminders.c.project_id == project_id,
                )
            ).one()
        service = DingTalkIntentService(scope.engine, get_settings())
        first = service.enqueue_reminder_dm(
            tenant_id=scope.tenant_id,
            project_id=project_id,
            actor_user_id=scope.owner_id,
            recipient_user_id=engineer,
            reminder_id=reminder.id,
            title=reminder.title,
        )
        repeat = service.enqueue_reminder_dm(
            tenant_id=scope.tenant_id,
            project_id=project_id,
            actor_user_id=scope.owner_id,
            recipient_user_id=engineer,
            reminder_id=reminder.id,
            title=reminder.title,
        )
        assert first.id == repeat.id
        assert first.status == "manual"
        assert len(scope.outbox_rows()) == 1
    finally:
        scope.dispose()


def test_dispatch_rolls_back_all_intents_and_audits_if_a_later_enqueue_fails(
    client: TestClient, isolated_dispatch_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = Scope(client, isolated_dispatch_database, pool_size=1)
    original_enqueue = DingTalkIntentService.enqueue_reminder_dm
    calls = 0

    def fail_second_enqueue(service: DingTalkIntentService, **kwargs: Any) -> OutboxRecord:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise DingTalkIntentError("DINGTALK_PUBLIC_BASE_URL_INVALID")
        return original_enqueue(service, **kwargs)

    try:
        engineer = scope.user("engineer", "engineer")
        scope.bind_dingtalk(engineer, staff_id="staff-eng")
        project_id = scope.project(member_ids=(engineer,))
        scope.task(project_id, assignee=engineer, title="First reminder")
        scope.task(project_id, assignee=engineer, title="Second reminder")
        fire_reminders(client, bearer_headers(client), project_id)
        monkeypatch.setattr(DingTalkIntentService, "enqueue_reminder_dm", fail_second_enqueue)
        with pytest.raises(DingTalkIntentError, match="DINGTALK_PUBLIC_BASE_URL_INVALID"):
            ReminderDeliveryDispatcher(scope.engine, get_settings()).dispatch(
                tenant_id=scope.tenant_id,
                project_id=project_id,
                actor_user_id=None,
                now=datetime.fromisoformat(AS_OF),
                automatic=True,
            )
        assert calls == 2
        assert scope.outbox_rows() == []
        with scope.engine.connect() as connection:
            assert (
                connection.execute(
                    select(tables.audit_log.c.id).where(
                        tables.audit_log.c.tenant_id == scope.tenant_id,
                        tables.audit_log.c.action == "dingtalk.outbox.enqueue",
                    )
                ).all()
                == []
            )
    finally:
        scope.dispose()
