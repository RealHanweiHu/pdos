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
from app.domain.gates import GateService
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


@pytest.mark.parametrize(
    "kind", ["edited", "referenced", "cross_project", "source_changed", "reuse", "run", "single"]
)
def test_actual_withdrawal_chain(
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
                title="核对密封测试泄漏",
                description="模拟：密封测试出现泄漏。",
                severity="critical",
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

        issue_url = f"/api/projects/{project}/issues/{app['issue_id']}"
        if kind == "edited":
            edited = client.patch(
                issue_url, headers=headers, json={"description": "负责人已补充调查结论"}
            )
            assert edited.status_code == 200, edited.text
        elif kind == "referenced":
            other_case = scope.test_case(project)
            linked = client.post(
                f"/api/projects/{project}/npi/test-cases/{other_case}/result",
                headers=headers,
                json={
                    "status": "failed",
                    "result_notes": "另一实际试验引用原问题",
                    "related_issue_id": app["issue_id"],
                },
            )
            assert linked.status_code == 200, linked.text
        elif kind == "cross_project":
            consumer_workflow = scope._insert(
                tables.workflows, {"code": "WF-CONSUMER", "name": "另一模拟流程"}
            )
            consumer = scope._insert(
                tables.projects,
                {
                    "workflow_id": consumer_workflow,
                    "owner_user_id": scope.owner_id,
                    "code": "PRJ-CONSUMER",
                    "name": "另一模拟项目",
                    "status": "active",
                },
            )
            scope._insert(
                tables.decisions,
                {
                    "project_id": consumer,
                    "issue_id": UUID(app["issue_id"]),
                    "decision_kind": "technical_choice",
                    "title": "模拟跨项目决策引用",
                    "outcome": "仅验证真实入向引用保护",
                },
            )
        elif kind == "source_changed":
            changed = client.post(
                runs_url(project, case),
                headers=headers,
                json={"status": "passed", "result_notes": "后续试验通过"},
            )
            assert changed.status_code == 201, changed.text
        if kind in {"single", "run"}:
            assert app["can_withdraw"], app["withdrawal_notice"]
            with scope.engine.connect() as c:
                before = GateService._live_non_signoff_blockers(
                    c, tenant_id=scope.tenant_id, project_id=project, stage_id=scope.stage_id
                )
                assert any(b["key"] == f"issue:{app['issue_id']}" for b in before)
                assert (
                    c.execute(
                        select(func.count()).select_from(tables.fmea_revision_candidates)
                    ).scalar_one()
                    == 0
                )
        withdrawal = {"request_id": str(uuid4()), "reason": "隔离模拟：核对为误建，撤回本次AI记录"}
        if kind != "run":
            withdrawal["application_id"] = app["id"]
        action_url = target + ("/withdraw-run" if kind == "run" else "/withdraw")
        done = client.post(action_url, headers=headers, json=withdrawal)
        assert done.status_code == 200, done.text
        result = done.json()
        item = result["items"][0]
        expected = {
            "edited": "human_edited",
            "referenced": "business_reference",
            "cross_project": "business_reference",
            "source_changed": "source_changed",
            "reuse": "reused_issue",
        }.get(kind, "withdrawn")
        assert item["reason_code"] == expected, result
        assert item["status"] == ("withdrawn" if kind in {"single", "run"} else "skipped")
        repeat = client.post(action_url, headers=headers, json=withdrawal)
        assert repeat.status_code == 200 and repeat.json()["id"] == result["id"], repeat.text
        history = client.get(issue_url, headers=headers)
        assert history.status_code == 200, history.text
        listed = client.get(f"/api/projects/{project}/issues", headers=headers)
        assert listed.status_code == 200, listed.text
        if kind in {"single", "run"}:
            assert history.json()["withdrawn_at"] and history.json()["status"] == "open"
            assert history.json()["ai_withdrawal_id"] == result["id"]
            assert all(x["id"] != app["issue_id"] for x in listed.json()["items"])
            assert scope.case_row(case)["related_issue_id"] is None
            with scope.engine.connect() as c:
                after = GateService._live_non_signoff_blockers(
                    c, tenant_id=scope.tenant_id, project_id=project, stage_id=scope.stage_id
                )
                assert not any(b["key"] == f"issue:{app['issue_id']}" for b in after)
            assert (
                client.patch(
                    issue_url, headers=headers, json={"title": "不应改写撤回记录"}
                ).status_code
                == 409
            )
            state = client.get(target, headers=headers).json()["application"]
            assert not state["can_withdraw"] and state["withdrawal_receipt"]["id"] == result["id"]
        else:
            assert history.json()["withdrawn_at"] is None
            assert any(x["id"] == app["issue_id"] for x in listed.json()["items"])
        with scope.engine.connect() as c:
            assert (
                c.execute(
                    select(func.count()).select_from(tables.ai_issue_withdrawal_receipts)
                ).scalar_one()
                == 1
            )
        with pytest.raises(DBAPIError), scope.engine.begin() as c:
            c.execute(tables.ai_issue_withdrawal_receipts.update().values(reason="不可改写"))
    finally:
        scope.dispose()
