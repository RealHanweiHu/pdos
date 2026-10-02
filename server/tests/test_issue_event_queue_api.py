"""Actual queue, budget and scoped history; synthetic transport, never T0 eligibility."""

# ruff: noqa: F811
import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from app.ai.application_gateway import configured_application_gateway
from app.ai.issue_event_proposal import OPERATION
from app.ai.issue_event_queue import IssueEventQueue
from app.db.schema import tables
from tests import test_application_budget_factory as factory
from tests.test_application_budget_factory import factory_setup  # noqa: F401
from tests.test_issue_event_runs_api import fixture_meter, live  # noqa: F401
from tests.test_model_budget_controller import response
from tests.test_test_runs_api import (
    Scope,  # noqa: F401
    bearer_headers,
    client,  # noqa: F401
    isolated_test_run_database,  # noqa: F401
)


def controls(
    client: TestClient, project: UUID, headers: dict[str, str], enabled: bool = True
) -> None:
    settings = client.get("/api/ai/governance/write-policy", headers=headers).json()
    settings["operation_settings"][OPERATION]["mode"] = "automatic"
    saved = client.post(
        "/api/ai/governance/write-policy",
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "expected_revision": settings["revision"],
            "mode": "tiered",
            "operation_settings": settings["operation_settings"],
            "reason": "隔离队列验证，不授真实资格",
        },
    )
    assert saved.status_code == 200, saved.text
    saved = client.post(
        f"/api/projects/{project}/ai-issue-applications/scope",
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "expected_revision": 0,
            "enabled": enabled,
            "reason": "隔离项目来源触发验证",
        },
    )
    assert saved.status_code == 200, saved.text


def failure(
    client: TestClient, scope: Scope, project: UUID, headers: dict[str, str]
) -> dict[str, Any]:
    case = scope.test_case(project)
    saved = client.post(
        f"/api/projects/{project}/npi/test-cases/{case}/result",
        headers=headers,
        json={"status": "failed", "result_notes": "模拟：密封测试出现泄漏。"},
    )
    assert saved.status_code == 200, saved.text
    return dict(
        client.get(f"/api/projects/{project}/ai-issue-event-sources", headers=headers).json()[
            "items"
        ][0]
    )


@pytest.mark.parametrize(
    "kind", ["success", "insufficient", "revoke", "archived", "disabled", "historical"]
)
def test_dispatch_execution_history_and_attention(
    client: TestClient,
    isolated_test_run_database: str,
    factory_setup: Any,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        live(monkeypatch)
        project, headers = scope.project(), bearer_headers(client)
        if kind == "historical":
            source = failure(client, scope, project, headers)
        controls(client, project, headers, enabled=kind != "disabled")
        if kind != "historical":
            source = failure(client, scope, project, headers)
        environment, calls, _ = factory_setup
        output = (
            {"disposition": "insufficient_evidence", "open_questions": ["请补充条件。"]}
            if kind == "insufficient"
            else {
                "disposition": "create_issue",
                "title": "核对泄漏",
                "description": "模拟：密封测试出现泄漏。",
                "severity": "medium",
                "citations": [
                    {
                        "reference_id": "test.original.result_notes",
                        "exact_quote": "密封测试出现泄漏",
                    }
                ],
            }
        )
        monkeypatch.setattr(
            factory, "response", lambda: response(json.dumps(output, ensure_ascii=False))
        )
        with configured_application_gateway(scope.engine, environment) as gateway:
            queue = IssueEventQueue(scope.engine, gateway)
            dispatched = queue.dispatch_once()
            assert calls == []
            skipped = kind in {"disabled", "historical"}
            assert dispatched.queued_count == (0 if skipped else 1), dispatched
            assert dispatched.skipped_count == (1 if skipped else 0), dispatched
            assert queue.dispatch_once().scanned_event_count == 0
            if kind == "revoke":
                r = client.post(
                    f"/api/projects/{project}/ai-issue-applications/scope",
                    headers=headers,
                    json={
                        "request_id": str(uuid4()),
                        "expected_revision": 1,
                        "enabled": False,
                        "reason": "隔离撤权",
                    },
                )
                assert r.status_code == 200, r.text
            if kind == "archived":
                with scope.engine.begin() as c:
                    c.execute(
                        tables.projects.update()
                        .where(tables.projects.c.id == project)
                        .values(status="archived")
                    )
            assert queue.execute_next() is not skipped
            assert queue.execute_next() is False
        assert len(calls) == (1 if kind in {"success", "insufficient"} else 0)
        base = f"/api/projects/{project}"
        history = client.get(
            base + "/ai-issue-event-history",
            params={"event_row_id": source["event_row_id"]},
            headers=headers,
        )
        assert history.status_code == 200, history.text
        assert history.headers["cache-control"] == "no-store"
        item = history.json()["items"][0]
        assert item["status"] == ("skipped" if skipped else "queued")
        if not skipped:
            assert item["run"]["status"] == (
                "failed" if kind in {"revoke", "archived"} else "succeeded"
            ), item
        attention = client.get(base + "/ai-issue-event-runs?attention=true", headers=headers)
        assert attention.status_code == 200, attention.text
        assert len(attention.json()["items"]) == (0 if skipped else 1)
        bad = client.get(
            base + "/ai-issue-event-history",
            params={"event_row_id": source["event_row_id"], "before_id": str(uuid4())},
            headers=headers,
        )
        assert bad.status_code == 409
        with scope.engine.connect() as c:
            assert c.execute(select(func.count()).select_from(tables.issues)).scalar_one() == 0
            assert (
                c.execute(
                    select(func.count()).select_from(tables.ai_issue_event_receipts)
                ).scalar_one()
                == 1
            )
        with scope.engine.begin() as c:
            for statement in (
                tables.ai_issue_event_receipts.update().values(reason="forged"),
                tables.ai_issue_event_receipts.delete(),
            ):
                with pytest.raises(DBAPIError), c.begin_nested():
                    c.execute(statement)
        if kind == "success":
            run = attention.json()["items"][0]
            target = base + "/ai-issue-applications/" + run["run_id"]
            request = {
                "request_id": str(uuid4()),
                "result_id": run["result_id"],
                "expected_digest": run["source_digest"],
            }
            declined = client.post(
                target + "/review",
                headers=headers,
                json={
                    **request,
                    "expected_version": 0,
                    "action": "decline",
                    "reason": "模拟核对后暂不采纳",
                },
            )
            assert declined.status_code == 200, declined.text
            assert (
                client.get(base + "/ai-issue-event-runs?attention=true", headers=headers).json()[
                    "items"
                ]
                == []
            )
            reopened = client.post(
                target + "/review",
                headers=headers,
                json={
                    **request,
                    "request_id": str(uuid4()),
                    "expected_version": 1,
                    "action": "reopen",
                    "reason": "模拟重新核对原建议",
                },
            )
            assert reopened.status_code == 200, reopened.text
            assert (
                len(
                    client.get(
                        base + "/ai-issue-event-runs?attention=true", headers=headers
                    ).json()["items"]
                )
                == 1
            )
            applied = client.post(
                target, headers=headers, json={**request, "request_id": str(uuid4())}
            )
            assert applied.status_code == 200, applied.text
            assert (
                client.get(base + "/ai-issue-event-runs?attention=true", headers=headers).json()[
                    "items"
                ]
                == []
            )
            assert len(calls) == 1  # Human handling never regenerates the original.
    finally:
        scope.dispose()
