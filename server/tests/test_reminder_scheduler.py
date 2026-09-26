"""Real database and process coverage for automatic reminder reconciliation."""

from __future__ import annotations

import json
import logging
import os
import select as io_select
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from app.automation.reminders import SCHEDULER_LOCK, ReminderScheduler
from app.db.schema import tables
from app.settings import Settings
from tests import test_reminders_api as reminder_fixtures
from tests.test_reminders_api import Scope, bearer_headers

NOW = datetime(2026, 9, 8, 4, tzinfo=UTC)  # Noon in the delivery timezone.
SERVER_ROOT = Path(__file__).resolve().parents[1]
client = reminder_fixtures.client
isolated_reminder_database = reminder_fixtures.isolated_reminder_database


@pytest.fixture
def scope(client: TestClient, isolated_reminder_database: str) -> Iterator[Scope]:
    value = Scope(client, isolated_reminder_database)
    try:
        yield value
    finally:
        value.dispose()


def settings(database_url: str, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "database_url": database_url,
        "jwt_secret": "scheduler-test-secret-at-least-32-bytes",
        "dingtalk_delivery_enabled": False,
        **overrides,
    }
    return Settings(**values)


def project(scope: Scope, code: str, *, tenant_id: UUID | None = None) -> UUID:
    tenant_id = tenant_id or scope.tenant_id
    workflow_id = scope._insert(
        tables.workflows, {"tenant_id": tenant_id, "code": code, "name": code}
    )
    return scope._insert(
        tables.projects,
        {"tenant_id": tenant_id, "workflow_id": workflow_id, "code": code, "name": code},
    )


def scheduler(scope: Scope, **overrides: Any) -> ReminderScheduler:
    return ReminderScheduler(
        scope.engine, settings(scope.engine.url.render_as_string(hide_password=False), **overrides)
    )


def count(scope: Scope, table: Any) -> int:
    with scope.engine.connect() as connection:
        return int(connection.execute(select(func.count()).select_from(table)).scalar_one())


def bind_owner(scope: Scope) -> None:
    scope._insert(
        tables.dingtalk_tenant_bindings,
        {
            "corp_id": "scheduler-corp",
            "client_id": "scheduler-client",
            "robot_code": "scheduler-robot",
            "oauth_redirect_uri": "https://pdos.example.com/api/dingtalk/oauth",
            "callback_route_key": "scheduler-route",
            "status": "active",
            "configured_by_user_id": scope.owner_id,
        },
    )
    scope._insert(
        tables.dingtalk_user_bindings,
        {
            "user_id": scope.owner_id,
            "staff_id": "scheduler-owner",
            "open_id": "scheduler-open",
            "union_id": "scheduler-union",
            "corp_id": "scheduler-corp",
            "status": "active",
        },
    )


def test_automatic_notifications_outbox_and_restart_are_idempotent(
    scope: Scope, client: TestClient
) -> None:
    project_id = project(scope, "AUTO")
    bind_owner(scope)
    scope.task(project_id, assignee=scope.owner_id, due=NOW.date() - timedelta(days=1), title="Due")
    first = scheduler(scope).run_once(as_of=NOW)
    assert first.projects == 1 and first.failed_projects == 0
    assert first.candidates_created == 1
    assert first.scheduled == 6 and first.fired == 5 and first.enqueued == 5
    event_count = count(scope, tables.events)
    second = scheduler(scope).run_once(as_of=NOW)
    assert second.candidates_created == second.scheduled == second.fired == second.enqueued == 0
    assert second.already_enqueued == 5
    assert count(scope, tables.events) == event_count
    response = client.get("/api/me/notifications", headers=bearer_headers(client))
    assert response.status_code == 200
    assert response.json()["unread_count"] == 5
    with scope.engine.connect() as connection:
        assert set(connection.execute(select(tables.risks.c.draft_state)).scalars()) == {"draft"}
        outbox = connection.execute(select(tables.integration_outbox)).mappings().all()
        assert len(outbox) == 5
        assert all(row["status"] == "manual" for row in outbox)
        assert all(row["last_error_code"] == "DINGTALK_DELIVERY_DISABLED" for row in outbox)
        assert all(row["attempt_count"] == 0 for row in outbox)
        actors = (
            connection.execute(
                select(tables.audit_log.c.actor_user_id).where(
                    tables.audit_log.c.action.in_(
                        (
                            "reminder.schedule",
                            "reminder.fire",
                            "risk.candidate_create",
                            "dingtalk.outbox.enqueue",
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        assert actors and all(actor is None for actor in actors)


def test_recovery_cancels_future_reminders_and_risk_recurrence_reuses_draft(scope: Scope) -> None:
    project_id = project(scope, "RECOVER")
    task_id = scope.task(
        project_id, assignee=scope.owner_id, due=NOW.date() - timedelta(days=1), title="Recover"
    )
    job = scheduler(scope)
    job.run_once(as_of=NOW)
    scope.complete_task(task_id)
    recovered = job.run_once(as_of=NOW)
    assert recovered.cancelled == 1 and recovered.candidates_cleared == 1
    with scope.engine.begin() as connection:
        risk_id = connection.execute(select(tables.risks.c.id)).scalar_one()
        connection.execute(
            tables.tasks.update()
            .where(tables.tasks.c.id == task_id)
            .values(status="todo", completed_at=None)
        )
    recurred = job.run_once(as_of=NOW)
    assert recurred.candidates_reactivated == 1 and recurred.candidates_created == 0
    assert recurred.scheduled == 1 and recurred.fired == 0
    with scope.engine.connect() as connection:
        row = connection.execute(select(tables.risks.c.id, tables.risks.c.draft_state)).one()
        assert row.id == risk_id and row.draft_state == "draft"


def test_pagination_and_tenant_project_exclusions(
    scope: Scope, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.automation.reminders.PROJECT_BATCH_SIZE", 2)
    included = [project(scope, f"PAGE-{index}") for index in range(5)]
    archived = project(scope, "ARCHIVED")
    suspended_tenant = uuid4()
    other_tenant = uuid4()
    with scope.engine.begin() as connection:
        connection.execute(
            tables.tenants.insert(),
            [
                {
                    "id": suspended_tenant,
                    "slug": "suspended",
                    "name": "Suspended",
                    "status": "suspended",
                },
                {"id": other_tenant, "slug": "other", "name": "Other", "status": "active"},
            ],
        )
        connection.execute(
            tables.projects.update()
            .where(tables.projects.c.id == archived)
            .values(status="archived")
        )
    excluded = project(scope, "SUSPENDED", tenant_id=suspended_tenant)
    other = project(scope, "OTHER", tenant_id=other_tenant)
    for project_id, tenant_id in [
        *((item, scope.tenant_id) for item in included),
        (archived, scope.tenant_id),
        (excluded, suspended_tenant),
        (other, other_tenant),
    ]:
        scope._insert(
            tables.tasks,
            {
                "tenant_id": tenant_id,
                "project_id": project_id,
                "title": "Overdue",
                "due_date": NOW.date() - timedelta(days=1),
            },
        )
    outcome = scheduler(scope).run_once(as_of=NOW)
    assert (
        outcome.projects == 6 and outcome.candidates_created == 6 and outcome.failed_projects == 0
    )
    with scope.engine.connect() as connection:
        scopes = set(
            connection.execute(select(tables.risks.c.tenant_id, tables.risks.c.project_id)).tuples()
        )
        assert scopes == {(scope.tenant_id, item) for item in included} | {(other_tenant, other)}
    # Recheck eligibility inside the domain write, not only at enumeration time.
    for tenant_id, project_id in ((scope.tenant_id, archived), (suspended_tenant, excluded)):
        result = scheduler(scope)._risks.scan(
            tenant_id=tenant_id,
            project_id=project_id,
            actor_user_id=None,
            today=NOW.date(),
            automatic=True,
        )
        assert result.created == 0


@pytest.mark.parametrize("stage", ["risks", "reminders", "delivery"])
def test_failure_isolated_to_project_and_next_cycle_recovers(
    scope: Scope, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, stage: str
) -> None:
    # The in-process Alembic fixture disables existing non-Alembic loggers.
    monkeypatch.setattr(logging.getLogger("app.automation.reminders"), "disabled", False)
    bad, good = sorted((project(scope, "BAD"), project(scope, "GOOD")))
    for project_id in (bad, good):
        scope.task(
            project_id, assignee=scope.owner_id, due=NOW.date() - timedelta(days=1), title="Recover"
        )
    job = scheduler(scope)
    service = getattr(job, f"_{stage}")
    method = "dispatch" if stage == "delivery" else "scan"
    original = getattr(service, method)

    def fail_one(**kwargs: Any) -> Any:
        if kwargs["project_id"] == bad:
            raise RuntimeError("sensitive detail must not appear in logs")
        return original(**kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(service, method, fail_one)
        first = job.run_once(as_of=NOW)
    assert first.projects == 2 and first.failed_projects == 1
    assert f"stage={stage}" in caplog.text
    assert "sensitive detail" not in caplog.text
    with scope.engine.connect() as connection:
        assert (
            connection.execute(
                select(func.count())
                .select_from(tables.reminders)
                .where(tables.reminders.c.project_id == good)
            ).scalar_one()
            == 6
        )
    retry = job.run_once(as_of=NOW)
    assert retry.failed_projects == 0
    assert count(scope, tables.risks) == 2
    assert count(scope, tables.reminders) == 12


def test_second_instance_skips_locked_cycle_and_resumes_after_release(scope: Scope) -> None:
    project_id = project(scope, "LOCK")
    scope.task(project_id, assignee=scope.owner_id, due=None, title="New")
    with scope.engine.begin() as connection:
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
            {"scope": SCHEDULER_LOCK},
        )
        locked = scheduler(scope).run_once(as_of=NOW)
        assert locked.skipped_locked and locked.projects == 0
        assert count(scope, tables.reminders) == 0
    assert scheduler(scope).run_once(as_of=NOW).fired == 1


def test_quiet_hours_defer_only_delivery_and_next_cycle_enqueues(scope: Scope) -> None:
    project_id = project(scope, "QUIET")
    bind_owner(scope)
    scope.task(project_id, assignee=scope.owner_id, due=None, title="New")
    quiet = scheduler(scope).run_once(as_of=NOW.replace(hour=14))
    assert quiet.fired == 1 and quiet.deferred_quiet_hours == 1 and quiet.enqueued == 0
    awake = scheduler(scope).run_once(as_of=NOW + timedelta(days=1))
    assert awake.fired == 0 and awake.enqueued == 1


def test_stop_between_projects_replays_safely(scope: Scope) -> None:
    for code in ("STOP-1", "STOP-2"):
        scope.task(project(scope, code), assignee=scope.owner_id, due=None, title=code)
    interrupted = scheduler(scope).run_once(as_of=NOW, should_stop=lambda: True)
    assert interrupted.interrupted and interrupted.projects == 0
    assert scheduler(scope).run_once(as_of=NOW).fired == 2


def test_real_process_repeats_without_http_trigger_and_stops_on_sigterm(scope: Scope) -> None:
    project_id = project(scope, "PROCESS")
    scope.task(project_id, assignee=scope.owner_id, due=None, title="Automatic")
    environment = {
        **os.environ,
        "DATABASE_URL": scope.engine.url.render_as_string(hide_password=False),
        "JWT_SECRET": "scheduler-process-test-secret-at-least-32-bytes",
        "PDOS_DINGTALK_DELIVERY_ENABLED": "false",
        "PDOS_REMINDER_SCAN_SECONDS": "1",
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "scripts.run_reminder_scheduler"],
        cwd=SERVER_ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        cycles = []
        for _ in range(2):
            ready, _, _ = io_select.select([process.stdout], [], [], 20)
            assert ready, "scheduler did not produce a cycle"
            cycles.append(json.loads(process.stdout.readline()))
        assert cycles[0]["fired"] == 1 and cycles[1]["fired"] == 0
        assert all(cycle["failed_projects"] == 0 for cycle in cycles)
    finally:
        process.terminate()
        try:
            _, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise
    assert process.returncode == 0, stderr
    once = subprocess.run(
        [sys.executable, "-m", "scripts.run_reminder_scheduler", "--once"],
        cwd=SERVER_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert once.returncode == 0, once.stderr
    assert json.loads(once.stdout)["fired"] == 0
    assert count(scope, tables.reminders) == 1


@pytest.mark.parametrize("raw", ["0", "-1", "3601", "nan", "inf", "invalid"])
def test_invalid_interval_fails_before_database_use(raw: str) -> None:
    with pytest.raises(ValueError):
        settings("postgresql://localhost/pdos_test", reminder_scan_seconds=raw)


def test_scan_interval_loads_from_the_local_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / "scheduler.env"
    env_file.write_text("PDOS_REMINDER_SCAN_SECONDS=17\n")
    configured = settings("postgresql://localhost/pdos_test", _env_file=env_file)
    assert configured.reminder_scan_seconds == 17


def test_naive_clock_rejected_before_any_scan(scope: Scope) -> None:
    with pytest.raises(ValueError, match="timezone"):
        scheduler(scope).run_once(as_of=datetime(2026, 9, 8))
