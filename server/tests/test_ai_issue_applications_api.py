"""Actual confirmed Issue writes, isolated DB and synthetic model transport."""

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
from app.ai.write_policy import WRITE_OPERATIONS
from app.api import ai_issue_event_runs as run_api
from app.db.schema import tables
from app.domain import ai_issue_applications as applications
from tests import test_application_budget_factory as factory
from tests.test_application_budget_factory import factory_setup  # noqa: F401
from tests.test_issue_event_runs_api import fixture_meter, live  # noqa: F401
from tests.test_model_budget_controller import response
from tests.test_test_runs_api import (  # noqa: F401
    Scope,
    bearer_headers,
    client,
    isolated_test_run_database,
    runs_url,
)


@pytest.mark.parametrize("kind", ["reuse", "changed", "create"])
def test_confirmed_application_chain(
    client: TestClient,
    isolated_test_run_database: str,
    factory_setup: Any,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        pending = dict(WRITE_OPERATIONS)
        pending[OPERATION] = pending[OPERATION].model_copy(update={"trial_ready": False})
        monkeypatch.setattr(applications, "WRITE_OPERATIONS", pending)
        live(monkeypatch)
        project, headers = scope.project(), bearer_headers(client)
        case = scope.test_case(project)
        url = (
            runs_url(project, case)
            if kind == "reuse"
            else f"/api/projects/{project}/npi/test-cases/{case}/result"
        )
        failure = client.post(
            url,
            headers=headers,
            json={"status": "failed", "result_notes": "模拟：密封测试出现泄漏。"},
        )
        assert failure.status_code in {200, 201}, failure.text
        existing = failure.json().get("related_issue_id")
        source = client.get(
            f"/api/projects/{project}/ai-issue-event-sources", headers=headers
        ).json()["items"][0]
        run_base = f"/api/projects/{project}/ai-issue-event-runs"
        ready = client.get(
            run_base + "/preparation",
            headers=headers,
            params={"event_row_id": source["event_row_id"]},
        ).json()
        payload: dict[str, Any] = {
            "disposition": "reuse_issue" if existing else "create_issue",
            "citations": [
                {"reference_id": "test.original.result_notes", "exact_quote": "密封测试出现泄漏"}
            ],
        }
        if existing:
            payload["existing_issue_id"] = existing
        else:
            payload.update(
                title="核对密封测试泄漏", description="模拟：密封测试出现泄漏。", severity="medium"
            )
        environment, calls, _ = factory_setup
        monkeypatch.setattr(
            factory, "response", lambda: response(json.dumps(payload, ensure_ascii=False))
        )
        monkeypatch.setattr(
            run_api,
            "configured_application_gateway",
            lambda e: configured_application_gateway(e, environment),
        )
        generated = []
        for _ in range(2 if kind == "create" else 1):
            r = client.post(
                run_base,
                headers=headers,
                json={
                    "request_id": str(uuid4()),
                    "event_row_id": source["event_row_id"],
                    "expected_digest": ready["source_digest"],
                },
            )
            assert r.status_code == 200 and r.json()["status"] == "succeeded", r.text
            generated.append(r.json())
        run = generated[0]
        base = f"/api/projects/{project}/ai-issue-applications"
        target = base + "/" + run["run_id"]
        change = {
            "request_id": str(uuid4()),
            "result_id": run["result_id"],
            "expected_digest": ready["source_digest"],
        }
        assert client.get(target, headers=headers).json()["can_apply"] is False
        blocked = client.post(target, headers=headers, json=change)
        assert (
            blocked.status_code == 409 and blocked.json()["detail"]["code"] == "ADAPTER_NOT_READY"
        )
        operations = dict(WRITE_OPERATIONS)
        operations[OPERATION] = operations[OPERATION].model_copy(update={"trial_ready": True})
        monkeypatch.setattr(applications, "WRITE_OPERATIONS", operations)
        settings = client.get("/api/ai/governance/write-policy", headers=headers).json()
        settings["operation_settings"][OPERATION]["mode"] = "confirm"
        policy = client.post(
            "/api/ai/governance/write-policy",
            headers=headers,
            json={
                "request_id": str(uuid4()),
                "expected_revision": settings["revision"],
                "mode": "tiered",
                "operation_settings": settings["operation_settings"],
                "reason": "隔离模拟：一次确认试运行",
            },
        )
        assert policy.status_code == 200, policy.text
        no_scope = client.post(target, headers=headers, json=change)
        assert no_scope.status_code == 409, no_scope.text
        grant = client.post(
            base + "/scope",
            headers=headers,
            json={
                "request_id": str(uuid4()),
                "expected_revision": 0,
                "enabled": True,
                "reason": "隔离模拟：授权事件建单范围",
            },
        )
        assert grant.status_code == 200, grant.text
        prepared = client.get(target, headers=headers)
        assert prepared.status_code == 200 and prepared.json()["can_apply"], prepared.text
        if kind == "changed":
            assert (
                client.post(
                    runs_url(project, case),
                    headers=headers,
                    json={"status": "passed", "result_notes": "后续测试通过"},
                ).status_code
                == 201
            )
            stale = client.post(target, headers=headers, json=change)
            assert stale.status_code == 409, stale.text
            with scope.engine.connect() as c:
                assert (
                    c.execute(
                        select(func.count()).select_from(tables.ai_issue_applications)
                    ).scalar_one()
                    == 0
                )
                assert c.execute(select(func.count()).select_from(tables.issues)).scalar_one() == 0
            return
        applied = client.post(target, headers=headers, json=change)
        assert applied.status_code == 200, applied.text
        app = applied.json()["application"]
        assert app["disposition"] == ("reused" if existing else "created")
        assert app["capture_mode"] == "trial" and app["writer_name"] == "PDOS Agent"
        assert app["confirmed_by_user_id"] == str(scope.owner_id)
        assert app["requested_by_user_id"] == str(scope.owner_id)
        replay = client.post(target, headers=headers, json=change)
        assert replay.status_code == 200 and replay.json()["application"]["id"] == app["id"], (
            replay.text
        )
        if kind == "create":
            other = client.post(
                base + "/" + generated[1]["run_id"],
                headers=headers,
                json={
                    "request_id": str(uuid4()),
                    "result_id": generated[1]["result_id"],
                    "expected_digest": ready["source_digest"],
                },
            )
            assert other.status_code == 200 and other.json()["application"]["id"] == app["id"], (
                other.text
            )
            assert other.json()["application"]["run_id"] == run["run_id"]
        with scope.engine.connect() as c:
            issue = (
                c.execute(select(tables.issues).where(tables.issues.c.id == UUID(app["issue_id"])))
                .mappings()
                .one()
            )
            assert c.execute(select(func.count()).select_from(tables.issues)).scalar_one() == 1
            assert (
                c.execute(
                    select(func.count()).select_from(tables.ai_issue_applications)
                ).scalar_one()
                == 1
            )
            if existing:
                assert (
                    issue["created_by_ai_principal_id"] is None
                    and issue["reported_by_user_id"] == scope.owner_id
                )
            else:
                assert (
                    issue["created_by_ai_principal_id"] == UUID(app["principal_id"])
                    and issue["reported_by_user_id"] is None
                )
                assert (
                    c.execute(
                        select(tables.test_cases.c.related_issue_id).where(
                            tables.test_cases.c.id == case
                        )
                    ).scalar_one()
                    == issue["id"]
                )
                audit = (
                    c.execute(
                        select(tables.audit_log).where(
                            tables.audit_log.c.event_id == f"issue:{issue['id']}:created"
                        )
                    )
                    .mappings()
                    .one()
                )
                assert audit["actor_user_id"] is None and audit["context"][
                    "confirmed_by_user_id"
                ] == str(scope.owner_id)
                assert audit["context"]["application_id"] == app["id"]
        with pytest.raises(DBAPIError), scope.engine.begin() as c:
            c.execute(tables.ai_issue_applications.update().values(disposition="reused"))
        # Replaying the original confirmed write remains a read after later source changes.
        assert (
            client.post(
                runs_url(project, case),
                headers=headers,
                json={"status": "passed", "result_notes": "办理后复测通过"},
            ).status_code
            == 201
        )
        history = client.get(target, headers=headers).json()
        assert not history["sources_current"] and history["application"]["id"] == app["id"]
        assert (
            client.post(target, headers=headers, json=change).json()["application"]["id"]
            == app["id"]
        )
        assert len(calls) == len(generated)
    finally:
        scope.dispose()
