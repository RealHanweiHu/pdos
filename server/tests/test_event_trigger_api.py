"""Trigger deadline visibility through the authenticated project run API."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from app.db.engine import get_engine
from app.db.schema import tables
from app.worker.dispatcher import AgentDispatcher
from tests.test_agent_dispatcher import append_event
from tests.test_ai_api import api_context as api_context
from tests.test_ai_api import isolated_ai_api_database as isolated_ai_api_database
from tests.test_ai_api import seed_project_and_users, setup_owner
from tests.test_chat_requests import ApiContext


def test_project_run_api_reports_prestart_timeout_and_frozen_deadline(
    api_context: ApiContext, isolated_ai_api_database: str
) -> None:
    client, _, _ = api_context
    tenant, _, headers = setup_owner(client)
    project, _ = seed_project_and_users(isolated_ai_api_database, tenant_id=tenant)
    engine = get_engine()
    occurred = datetime.now(UTC) - timedelta(seconds=181)
    with engine.begin() as c:
        event_id = append_event(
            c,
            tenant_id=tenant,
            project_id=project,
            event_type="ISSUE_CREATED",
            occurred_at=occurred,
        )
    AgentDispatcher(engine, scheduling="approved").dispatch_tenant(tenant_id=tenant)
    with engine.begin() as c:
        assert c.execute(text("SELECT cehub_ai.expire_queued_dispatch_runs(10)")).scalar_one() == 1
    response = client.get(f"/api/ai/projects/{project}/runs", headers=headers)
    assert response.status_code == 200, response.text
    with engine.connect() as c:
        run_id = c.execute(
            select(tables.agent_runs.c.id).where(
                tables.agent_runs.c.tenant_id == tenant,
                tables.agent_runs.c.first_event_row_id == event_id,
            )
        ).scalar_one()
    row = next(item for item in response.json()["items"] if item["id"] == str(run_id))
    assert row["dispatch_policy"] == "milestone.v1"
    assert datetime.fromisoformat(row["dispatch_deadline"]) == occurred + timedelta(seconds=180)
    assert row["status"] == "failed" and row["started_at"] is None
    assert row["error_code"] == "AGENT_TRIGGER_DEADLINE_EXCEEDED"
