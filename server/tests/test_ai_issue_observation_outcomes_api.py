"""Observe actual edit/withdrawal receipts with isolated synthetic transport only."""

# ruff: noqa: F811
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select

from app.db.schema import tables
from app.db.url import psycopg_database_url
from tests.test_ai_issue_withdrawals_api import test_actual_withdrawal_chain as exercise_chain
from tests.test_application_budget_factory import factory_setup  # noqa: F401
from tests.test_issue_event_runs_api import fixture_meter  # noqa: F401
from tests.test_test_runs_api import (
    bearer_headers,
    client,  # noqa: F401
    isolated_test_run_database,  # noqa: F401
)


@pytest.mark.parametrize("kind", ["edited", "single"])
def test_observation_distinguishes_human_edit_from_actual_withdrawal(
    client: TestClient,
    isolated_test_run_database: str,
    factory_setup: Any,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    # Reuse one fixture lifecycle; disposing its engine does not erase originals.
    exercise_chain(client, isolated_test_run_database, factory_setup, monkeypatch, kind)
    engine = create_engine(psycopg_database_url(isolated_test_run_database))
    try:
        with engine.connect() as c:
            application = c.execute(select(tables.ai_issue_applications)).mappings().one()
            tenant, project = application["tenant_id"], application["project_id"]
            runs = tables.agent_runs
            start = c.execute(
                select(func.min(runs.c.created_at)).where(
                    runs.c.tenant_id == tenant,
                    runs.c.project_id == project,
                    runs.c.agent_key == "quality_intelligence",
                    runs.c.context_version == "event-issue-request-v1",
                )
            ).scalar_one()
            end = c.execute(select(func.clock_timestamp())).scalar_one()
            withdrawal = (
                c.execute(
                    select(tables.ai_issue_withdrawal_receipts).where(
                        tables.ai_issue_withdrawal_receipts.c.tenant_id == tenant,
                        tables.ai_issue_withdrawal_receipts.c.project_id == project,
                        tables.ai_issue_withdrawal_receipts.c.application_id == application["id"],
                    )
                )
                .mappings()
                .one()
            )
            audits = tables.audit_log
            edit_ids = list(
                c.execute(
                    select(audits.c.id).where(
                        audits.c.tenant_id == tenant,
                        audits.c.project_id == project,
                        audits.c.entity == "issue",
                        audits.c.entity_id == application["issue_id"],
                        audits.c.action == "issue.update",
                        audits.c.actor_user_id.is_not(None),
                        audits.c.timestamp > application["created_at"],
                        audits.c.timestamp <= end,
                    )
                ).scalars()
            )
        assert start is not None
        reply = client.post(
            f"/api/projects/{project}/ai-issue-observations",
            headers=bearer_headers(client),
            json={
                "request_id": str(uuid4()),
                "window_start": (start - timedelta(seconds=1)).isoformat(),
                "window_end": end.isoformat(),
            },
        )
        assert reply.status_code == 200, reply.text
        assert reply.headers["cache-control"] == "no-store"
        observed = reply.json()
        counts = observed["counts"]
        assert observed["total_runs"] == counts["total_runs"] == 1
        assert counts["created_issues"] == 1
        assert counts["human_edited_issues"] == (1 if kind == "edited" else 0)
        assert counts["withdrawn_issues"] == (1 if kind == "single" else 0)
        assert observed["qualification_granted"] is False
        assert len(observed["items"]) == 1
        item = observed["items"][0]
        assert item["run_id"] == str(application["run_id"])
        assert item["application_id"] == str(application["id"])
        assert item["issue_id"] == str(application["issue_id"])
        assert item["human_edited"] is (kind == "edited")
        assert item["withdrawn"] is (kind == "single")
        assert item["provider_verified"] is False
        assert len(withdrawal["items"]) == 1
        original = withdrawal["items"][0]
        assert original["application_id"] == item["application_id"]
        assert original["issue_id"] == item["issue_id"]
        if kind == "edited":
            assert edit_ids
            assert set(item["human_edit_audit_ids"]) == set(edit_ids)
            assert item["withdrawal_id"] is None
            assert original["status"] == "skipped"
            assert original["reason_code"] == "human_edited"
        else:
            assert edit_ids == item["human_edit_audit_ids"] == []
            assert item["withdrawal_id"] == str(withdrawal["id"])
            assert original["status"] == original["reason_code"] == "withdrawn"
    finally:
        engine.dispose()
