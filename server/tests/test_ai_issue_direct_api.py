"""Isolated synthetic qualification verifies direct writes, never real eligibility.

The provider transport and qualification decision are explicitly substituted.
Original protocol/collection rows, business writers, guards, sampling reviews,
withdrawal counters and the stop latch are actual database/API operations.
"""

# ruff: noqa: F811
import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, func, select

from app.ai.application_domain_context import bundle
from app.ai.application_gateway import configured_application_gateway
from app.ai.issue_event_proposal import OPERATION
from app.ai.write_policy import POLICY_VERSION, WRITE_OPERATIONS
from app.api import ai_issue_event_runs as run_api
from app.db.schema import tables
from app.domain import ai_issue_applications as applications
from app.domain import ai_issue_direct_route as route
from app.domain.ai_issue_write_monitor import quality_monitor
from app.domain.product_workspace import digest
from app.events.writer import EventAuditWriter
from tests import test_application_budget_factory as factory
from tests.issue_direct_fixture import insert_synthetic_qualification
from tests.test_application_budget_factory import factory_setup  # noqa: F401
from tests.test_issue_evaluation_publication import fixture_document
from tests.test_issue_event_runs_api import fixture_meter, live  # noqa: F401
from tests.test_model_budget_controller import response
from tests.test_test_runs_api import (
    Scope,
    bearer_headers,
    client,  # noqa: F401
    isolated_test_run_database,  # noqa: F401
    runs_url,
)


def ok(reply: Any) -> dict[str, Any]:
    assert reply.status_code == 200, reply.text
    return dict(reply.json())


@pytest.mark.parametrize("kind", ["sample", "withdraw", "rollback", "reuse"])
def test_direct_issue_chain(
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
        base = f"/api/projects/{project}/ai-issue-applications"
        run_base = f"/api/projects/{project}/ai-issue-event-runs"
        settings = ok(client.get("/api/ai/governance/write-policy", headers=headers))
        settings["operation_settings"][OPERATION]["mode"] = "automatic"
        saved_policy = ok(
            client.post(
                "/api/ai/governance/write-policy",
                headers=headers,
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": settings["revision"],
                    "mode": "tiered",
                    "operation_settings": settings["operation_settings"],
                    "reason": "仅隔离模拟自动路径，不发布真实资格",
                },
            )
        )["policy"]
        ok(
            client.post(
                base + "/scope",
                headers=headers,
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": 0,
                    "enabled": True,
                    "reason": "隔离模拟项目授权",
                },
            )
        )
        operations = dict(WRITE_OPERATIONS)
        operations[OPERATION] = operations[OPERATION].model_copy(
            update={"trial_ready": True, "adapter_ready": True}
        )
        monkeypatch.setattr(applications, "WRITE_OPERATIONS", operations)
        binding = fixture_document()["evaluations"][0]["evaluation"]["binding"]
        runtime = bundle("event_issue")
        binding.update(
            policy_version=POLICY_VERSION,
            policy_revision=saved_policy["revision"],
            release_bundle_version="sha256:" + digest(runtime),
            adapter_version=runtime["compiled"]["reader"],
        )
        with scope.engine.begin() as c:
            policy = (
                c.execute(
                    select(tables.ai_write_policies).where(
                        tables.ai_write_policies.c.tenant_id == scope.tenant_id,
                        tables.ai_write_policies.c.revision == saved_policy["revision"],
                    )
                )
                .mappings()
                .one()
            )
            grant = (
                c.execute(
                    select(tables.ai_write_scope_revisions).where(
                        tables.ai_write_scope_revisions.c.project_id == project
                    )
                )
                .mappings()
                .one()
            )
            protocol, collection = insert_synthetic_qualification(
                c,
                tenant_id=scope.tenant_id,
                project_id=project,
                policy=dict(policy),
                scope=dict(grant),
                actor_id=scope.owner_id,
                binding=binding,
            )

        def synthetic_route(
            c: Connection,
            *,
            tenant_id: UUID,
            project_id: UUID,
            run_id: UUID,
            as_of: datetime,
        ) -> dict[str, Any]:
            result_row = (
                c.execute(
                    select(tables.ai_issue_event_results).where(
                        tables.ai_issue_event_results.c.tenant_id == tenant_id,
                        tables.ai_issue_event_results.c.run_id == run_id,
                    )
                )
                .mappings()
                .one()
            )
            monitor = quality_monitor(
                c,
                tenant_id=tenant_id,
                project_id=project_id,
                policy_id=UUID(protocol["policy_id"]),
                binding_digest=digest(binding),
                protocol_id=UUID(protocol["id"]),
                configuration=protocol["configuration"],
                as_of=as_of,
            )
            direct = not monitor["stopped"]
            return {
                "version": "event-issue-write-execution-v1",
                "run_id": str(run_id),
                "route": "direct" if direct else "confirm",
                "reason": "qualified_direct_write" if direct else "quality_stop",
                "reason_label": "隔离模拟：AI已办理" if direct else "撤回超限，自动办理暂停",
                "checked_at": as_of.isoformat(),
                "sampled": direct,
                "policy_id": protocol["policy_id"],
                "scope_revision_id": protocol["scope_revision_id"],
                "principal_id": protocol["principal_id"],
                "binding_digest": digest(binding),
                "protocol_id": protocol["id"],
                "collection_id": collection["id"],
                "configuration": protocol["configuration"],
                "monitor": monitor,
                "readiness": {
                    "state": "current",
                    "binding": binding,
                    "provenance": {
                        "provider_verified": True,
                        "provenance_verified": True,
                        "binding": binding,
                        "references": {
                            "result_id": str(result_row["id"]),
                            "invocation_id": str(result_row["model_invocation_id"]),
                        },
                    },
                    "qualification_state": {
                        "state": "current",
                        "protocol_id": protocol["id"],
                        "latest_collection_id": collection["id"],
                        "original_result": {"status": "meets_candidate_criteria"},
                        "fresh_result": {"status": "meets_candidate_criteria"},
                    },
                },
            }

        monkeypatch.setattr(route, "resolve_direct_route", synthetic_route)
        environment, calls, _ = factory_setup
        payload = {
            "disposition": "create_issue",
            "title": "模拟自动密封问题",
            "description": "模拟：密封测试出现泄漏。",
            "severity": "medium",
            "citations": [
                {"reference_id": "test.original.result_notes", "exact_quote": "密封测试出现泄漏"}
            ],
        }
        monkeypatch.setattr(
            factory, "response", lambda: response(json.dumps(payload, ensure_ascii=False))
        )
        monkeypatch.setattr(
            run_api,
            "configured_application_gateway",
            lambda engine: configured_application_gateway(engine, environment),
        )

        def generate() -> tuple[dict[str, Any], dict[str, Any]]:
            case = scope.test_case(project)
            failure = client.post(
                runs_url(project, case)
                if kind == "reuse"
                else f"/api/projects/{project}/npi/test-cases/{case}/result",
                headers=headers,
                json={"status": "failed", "result_notes": "模拟：密封测试出现泄漏。"},
            )
            assert failure.status_code in {200, 201}, failure.text
            if kind == "reuse":
                payload.clear()
                payload.update(
                    disposition="reuse_issue",
                    existing_issue_id=failure.json()["related_issue_id"],
                    citations=[
                        {
                            "reference_id": "test.original.result_notes",
                            "exact_quote": "密封测试出现泄漏",
                        }
                    ],
                )
            source = next(
                v
                for v in ok(
                    client.get(f"/api/projects/{project}/ai-issue-event-sources", headers=headers)
                )["items"]
                if v["source"]["source_key"] == f"test_case:{case}"
            )
            ready = ok(
                client.get(
                    run_base + "/preparation",
                    headers=headers,
                    params={"event_row_id": source["event_row_id"]},
                )
            )
            request = {
                "request_id": str(uuid4()),
                "event_row_id": source["event_row_id"],
                "expected_digest": ready["source_digest"],
            }
            result = ok(client.post(run_base, headers=headers, json=request))
            assert result["status"] == "succeeded", result
            return result, request

        original_writer = EventAuditWriter.record
        if kind == "rollback":

            def fail_application(self: Any, event: Any, audit: Any) -> Any:
                if event.event_type == "AI_ISSUE_APPLICATION_RECORDED":
                    raise ValueError("simulated application receipt failure")
                return original_writer(self, event, audit)

            monkeypatch.setattr(EventAuditWriter, "record", fail_application)
        run, request = generate()
        target = base + "/" + run["run_id"]
        if kind == "rollback":
            assert run["write_execution"]["reason"] == "automatic_apply_failed", run
            assert ok(client.get(target, headers=headers))["application"] is None
            with scope.engine.connect() as c:
                assert c.execute(select(func.count()).select_from(tables.issues)).scalar_one() == 0
                assert (
                    c.execute(
                        select(func.count()).select_from(tables.ai_issue_event_results)
                    ).scalar_one()
                    == 1
                )
            monkeypatch.setattr(EventAuditWriter, "record", original_writer)
            assert ok(client.post(run_base, headers=headers, json=request)) == run
            return
        assert run["write_execution"]["route"] == "direct", run["write_execution"]
        application = ok(client.get(target, headers=headers))["application"]
        assert (
            application["capture_mode"] == "direct" and application["confirmed_by_user_id"] is None
        )
        assert application["confirmed_by_name"] is None and application["requested_by_name"]
        assert application["writer_name"] == "PDOS Agent"
        assert ok(client.post(run_base, headers=headers, json=request)) == run
        with scope.engine.connect() as c:
            audit = (
                c.execute(
                    select(tables.audit_log).where(
                        tables.audit_log.c.action == "ai_issue.automatic_apply"
                    )
                )
                .mappings()
                .one()
            )
            assert (
                audit["actor_user_id"] is None and audit["context"]["confirmed_by_user_id"] is None
            )
            assert c.execute(select(func.count()).select_from(tables.issues)).scalar_one() == 1
        if kind == "reuse":
            assert application["disposition"] == "reused" and application["can_withdraw"] is False
            with scope.engine.connect() as c:
                issue = (
                    c.execute(
                        select(tables.issues).where(
                            tables.issues.c.id == UUID(application["issue_id"])
                        )
                    )
                    .mappings()
                    .one()
                )
                assert issue["created_by_ai_principal_id"] is None
                assert issue["reported_by_user_id"] == scope.owner_id
                assert (
                    c.execute(
                        select(func.count()).select_from(tables.ai_issue_applications)
                    ).scalar_one()
                    == 1
                )
            assert application["receipt"]["write_receipt"]["monitor"]["receipt"]["generated"] == 0
            assert len(calls) == 1
            return
        if kind == "sample":
            sample_url = target + "/sample-review"
            before = ok(
                client.get(
                    f"/api/projects/{project}/issues/{application['issue_id']}", headers=headers
                )
            )
            sample = ok(client.get(sample_url, headers=headers))
            assert sample["can_review"] is True and sample["history"] == []
            body = {
                "request_id": str(uuid4()),
                "expected_digest": sample["expected_digest"],
                "verdict": "accepted",
                "reason": "模拟抽检：逐项对照原建议认可",
            }
            reviewed = ok(client.post(sample_url, headers=headers, json=body))
            assert (
                reviewed["replayed"] is False
                and reviewed["review_receipt"]["verdict"] == "accepted"
            )
            repeated = ok(client.post(sample_url, headers=headers, json=body))
            assert (
                repeated["replayed"] is True
                and repeated["review_receipt"] == reviewed["review_receipt"]
            )
            corrected = ok(
                client.post(
                    sample_url,
                    headers=headers,
                    json={
                        **body,
                        "request_id": str(uuid4()),
                        "verdict": "needs_correction",
                        "reason": "模拟补充复核：需修改措辞",
                    },
                )
            )
            assert len(corrected["history"]) == 2
            assert (
                ok(
                    client.get(
                        f"/api/projects/{project}/issues/{application['issue_id']}", headers=headers
                    )
                )
                == before
            )
            edited = client.patch(
                f"/api/projects/{project}/issues/{application['issue_id']}",
                headers=headers,
                json={"description": "模拟人工补充"},
            )
            assert edited.status_code == 200, edited.text
            stale = client.post(
                sample_url, headers=headers, json={**body, "request_id": str(uuid4())}
            )
            assert stale.status_code == 409, stale.text
            assert len(ok(client.get(sample_url, headers=headers))["history"]) == 2
            # A different automatic Issue may be withdrawn; that stop must also
            # appear on this still-visible, reviewed application in the same policy.
            second, _ = generate()
            second_target = base + "/" + second["run_id"]
            second_app = ok(client.get(second_target, headers=headers))["application"]
            withdrawn = ok(
                client.post(
                    second_target + "/withdraw",
                    headers=headers,
                    json={
                        "request_id": str(uuid4()),
                        "application_id": second_app["id"],
                        "reason": "模拟另一自动问题撤回，共同政策暂停仍显示在原抽检卡",
                    },
                )
            )
            assert withdrawn["items"][0]["status"] == "withdrawn", withdrawn
            retained_app = ok(client.get(target, headers=headers))["application"]
            assert retained_app["withdrawn_at"] is None
            assert retained_app["automatic_stop"]["receipt"]["generated"] == 2
            assert retained_app["automatic_stop"]["receipt"]["withdrawn"] == 1
        else:
            withdrawal = ok(
                client.post(
                    target + "/withdraw",
                    headers=headers,
                    json={
                        "request_id": str(uuid4()),
                        "application_id": application["id"],
                        "reason": "模拟撤回并核对自动暂停",
                    },
                )
            )
            assert withdrawal["items"][0]["status"] == "withdrawn", withdrawal
            after = ok(client.get(target, headers=headers))["application"]
            assert after["automatic_stop"]["receipt"]["generated"] == 1
            assert after["automatic_stop"]["receipt"]["withdrawn"] == 1
            second, _ = generate()
            assert second["write_execution"]["route"] == "confirm"
            assert second["write_execution"]["reason"] == "quality_stop"
            assert (
                ok(client.get(base + "/" + second["run_id"], headers=headers))["application"]
                is None
            )
            with scope.engine.connect() as c:
                assert (
                    c.execute(
                        select(func.count()).select_from(tables.ai_write_runtime_stops)
                    ).scalar_one()
                    == 1
                )
                assert (
                    c.execute(
                        select(func.count()).select_from(tables.ai_issue_applications)
                    ).scalar_one()
                    == 1
                )
        assert len(calls) == (2 if kind in {"sample", "withdraw"} else 1)
    finally:
        scope.dispose()
