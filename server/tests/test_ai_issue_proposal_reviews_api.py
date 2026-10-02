"""Actual HTTP review history with an isolated DB and synthetic model transport.

Uses the existing applications fixture and its configured isolated test database.
These cases exercise runtime receipts, not real-model qualification. Do not run
against a retained integration tenant/database.
"""

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
from app.domain import ai_issue_generation_bindings as generation_bindings
from tests import test_application_budget_factory as factory
from tests.test_application_budget_factory import factory_setup  # noqa: F401
from tests.test_issue_event_runs_api import fixture_meter, live  # noqa: F401
from tests.test_model_budget_controller import response
from tests.test_test_runs_api import (
    Scope,
    bearer_headers,
    client,  # noqa: F401
    isolated_test_run_database,  # noqa: F401
)


def _ok(reply: Any) -> dict[str, Any]:
    assert reply.status_code == 200, reply.text
    assert reply.headers["cache-control"] == "no-store"
    body: dict[str, Any] = reply.json()
    return body


def _conflict(reply: Any, code: str) -> None:
    assert reply.status_code == 409, reply.text
    assert reply.json()["detail"]["code"] == code, reply.text
    assert reply.headers["cache-control"] == "no-store"


def test_generation_binding_review_history_replay_and_application_guards(
    client: TestClient,
    isolated_test_run_database: str,
    factory_setup: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        live(monkeypatch)
        assert WRITE_OPERATIONS[OPERATION].trial_ready
        project, headers = scope.project(), bearer_headers(client)
        case = scope.test_case(project)
        failed = client.post(
            f"/api/projects/{project}/npi/test-cases/{case}/result",
            headers=headers,
            json={"status": "failed", "result_notes": "模拟：密封测试出现泄漏。"},
        )
        assert failed.status_code == 200, failed.text
        assert failed.json().get("related_issue_id") is None
        run_base = f"/api/projects/{project}/ai-issue-event-runs"
        application_base = f"/api/projects/{project}/ai-issue-applications"
        source = client.get(
            f"/api/projects/{project}/ai-issue-event-sources", headers=headers
        ).json()["items"][0]
        prepared = _ok(
            client.get(
                run_base + "/preparation",
                headers=headers,
                params={"event_row_id": source["event_row_id"]},
            )
        )
        output = {
            "disposition": "create_issue",
            "title": "核对密封测试泄漏",
            "description": "模拟：密封测试出现泄漏。",
            "severity": "medium",
            "citations": [
                {"reference_id": "test.original.result_notes", "exact_quote": "密封测试出现泄漏"}
            ],
        }
        environment, calls, _ = factory_setup
        monkeypatch.setattr(
            factory, "response", lambda: response(json.dumps(output, ensure_ascii=False))
        )
        monkeypatch.setattr(
            run_api,
            "configured_application_gateway",
            lambda engine: configured_application_gateway(engine, environment),
        )

        # Simulate the historical unfinished adapter before BOTH runs. The first
        # original stays evidence-only even after the adapter becomes ready.
        pending = dict(WRITE_OPERATIONS)
        pending[OPERATION] = pending[OPERATION].model_copy(update={"trial_ready": False})
        monkeypatch.setattr(applications, "WRITE_OPERATIONS", pending)
        monkeypatch.setattr(generation_bindings, "WRITE_OPERATIONS", pending)
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
                "reason": "隔离模拟：生成前固定建议试运行政策",
            },
        )
        assert policy.status_code == 200, policy.text
        _ok(
            client.post(
                application_base + "/scope",
                headers=headers,
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": 0,
                    "enabled": True,
                    "reason": "隔离模拟：生成前授权事件建议范围",
                },
            )
        )
        first_request = {
            "request_id": str(uuid4()),
            "event_row_id": source["event_row_id"],
            "expected_digest": prepared["source_digest"],
        }
        first = _ok(client.post(run_base, headers=headers, json=first_request))
        assert first["status"] == "succeeded"
        frozen_first = first["generation_binding"]
        assert frozen_first["capture_kind"] == "evidence_only"
        assert frozen_first["reason_code"] == "trial_not_ready"
        assert frozen_first["trial_ready"] is False
        assert frozen_first["policy_id"] and frozen_first["scope_revision_id"]
        assert frozen_first["policy"]["operation_setting"]["mode"] == "confirm"
        assert frozen_first["scope"]["enabled"] is True

        # This is an explicit process-local simulation, not a deployed capability
        # flag or qualified model. Both consumers must see the same candidate map.
        operations = dict(WRITE_OPERATIONS)
        operations[OPERATION] = operations[OPERATION].model_copy(update={"trial_ready": True})
        monkeypatch.setattr(applications, "WRITE_OPERATIONS", operations)
        monkeypatch.setattr(generation_bindings, "WRITE_OPERATIONS", operations)
        request = {**first_request, "request_id": str(uuid4())}
        run = _ok(client.post(run_base, headers=headers, json=request))
        assert run["status"] == "succeeded"
        candidate = run["generation_binding"]
        assert candidate["capture_kind"] == candidate["reason_code"] == "trial_candidate"
        assert candidate["trial_ready"] is True and candidate["rollout"] == "live"
        assert candidate["policy_id"] == frozen_first["policy_id"]
        assert candidate["principal_id"] == frozen_first["principal_id"]
        assert candidate["scope_revision_id"] == frozen_first["scope_revision_id"]
        assert candidate["binding_id"] != frozen_first["binding_id"]
        assert (
            _ok(client.post(run_base, headers=headers, json=first_request))["generation_binding"]
            == frozen_first
        )
        assert len(calls) == 2  # Original request replay neither calls nor backfills.

        target = application_base + "/" + run["run_id"]
        review_url = target + "/review"
        application = {
            "request_id": str(uuid4()),
            "result_id": run["result_id"],
            "expected_digest": prepared["source_digest"],
        }
        initial = _ok(client.get(target, headers=headers))
        assert initial["can_apply"] and initial["review"]["state"] == "unreviewed"
        assert initial["review"]["version"] == 0 and initial["review"]["items"] == []
        decline = {
            "request_id": str(uuid4()),
            "result_id": run["result_id"],
            "expected_digest": prepared["source_digest"],
            "expected_version": 0,
            "action": "decline",
            "reason": "模拟：暂不采纳，需进一步核对泄漏位置",
        }
        denied = _ok(client.post(review_url, headers=headers, json=decline))
        original_receipt = denied["review_receipt"]
        assert original_receipt["version"] == 1 and original_receipt["action"] == "decline"
        assert original_receipt["actor_user_id"] == str(scope.owner_id)
        assert original_receipt["reason"] == decline["reason"]
        assert denied["review"]["state"] == "declined" and not denied["can_apply"]
        replay = _ok(client.post(review_url, headers=headers, json=decline))
        assert replay["review_receipt"] == original_receipt and replay["review"]["version"] == 1
        _conflict(
            client.post(
                review_url, headers=headers, json={**decline, "reason": "同请求不能替换原原因"}
            ),
            "REQUEST_ID_REUSED",
        )
        _conflict(client.post(target, headers=headers, json=application), "PROPOSAL_DECLINED")
        _conflict(
            client.post(
                review_url,
                headers=headers,
                json={**decline, "request_id": str(uuid4()), "action": "reopen"},
            ),
            "REVIEW_CHANGED",
        )
        _conflict(
            client.post(
                review_url,
                headers=headers,
                json={**decline, "request_id": str(uuid4()), "expected_version": 1},
            ),
            "REVIEW_ACTION_INVALID",
        )
        reopen = {
            **decline,
            "request_id": str(uuid4()),
            "expected_version": 1,
            "action": "reopen",
            "reason": "模拟：补充核对后重新考虑原建议",
        }
        reopened = _ok(client.post(review_url, headers=headers, json=reopen))
        assert reopened["review"]["state"] == "reopened" and reopened["review"]["version"] == 2
        assert reopened["can_apply"]
        old_replay = _ok(client.post(review_url, headers=headers, json=decline))
        assert old_replay["review_receipt"] == original_receipt
        assert old_replay["review"]["state"] == "reopened"  # Current state != old response.

        # Enough real HTTP transitions to cross the 20-row history boundary.
        receipts = [original_receipt, reopened["review_receipt"]]
        for version in range(3, 23):
            change = {
                **decline,
                "request_id": str(uuid4()),
                "expected_version": version - 1,
                "action": "decline" if version % 2 else "reopen",
                "reason": f"隔离模拟：第 {version} 次具名意见",
            }
            changed = _ok(client.post(review_url, headers=headers, json=change))
            assert changed["review_receipt"]["version"] == version
            receipts.append(changed["review_receipt"])
        page = _ok(client.get(review_url, headers=headers))
        assert page["version"] == 22 and page["state"] == "reopened"
        assert [item["version"] for item in page["items"]] == list(range(22, 2, -1))
        assert page["next_before_version"] == 3
        tail = _ok(client.get(review_url, headers=headers, params={"before_version": 3}))
        assert tail["version"] == 22 and tail["state"] == "reopened"
        assert [item["version"] for item in tail["items"]] == [2, 1]
        assert tail["next_before_version"] is None
        assert tail["items"][-1] == original_receipt
        _conflict(
            client.get(review_url, headers=headers, params={"before_version": 999}),
            "REVIEW_CURSOR_INVALID",
        )
        assert (
            client.get(review_url, headers=headers, params={"before_version": 0}).status_code == 422
        )

        with scope.engine.connect() as c:
            stored_bindings = list(
                c.execute(
                    select(tables.ai_issue_generation_bindings).where(
                        tables.ai_issue_generation_bindings.c.tenant_id == scope.tenant_id,
                        tables.ai_issue_generation_bindings.c.project_id == project,
                    )
                ).mappings()
            )
            assert len(stored_bindings) == 2
            assert {str(row["id"]) for row in stored_bindings} == {
                frozen_first["binding_id"],
                candidate["binding_id"],
            }
            assert (
                c.execute(
                    select(func.count())
                    .select_from(tables.ai_issue_applications)
                    .where(tables.ai_issue_applications.c.tenant_id == scope.tenant_id)
                ).scalar_one()
                == 0
            )
            for receipt in receipts:
                event = (
                    c.execute(
                        select(tables.events).where(
                            tables.events.c.tenant_id == scope.tenant_id,
                            tables.events.c.id == receipt["output_event_row_id"],
                        )
                    )
                    .mappings()
                    .one()
                )
                assert event["event_type"] == "AI_ISSUE_PROPOSAL_REVIEW_RECORDED"
                assert event["entity_id"] == UUID(receipt["id"])
                assert event["payload"] == {
                    "review_id": receipt["id"],
                    "result_id": run["result_id"],
                    "action": receipt["action"],
                    "version": receipt["version"],
                }
                audit = (
                    c.execute(
                        select(tables.audit_log).where(
                            tables.audit_log.c.tenant_id == scope.tenant_id,
                            tables.audit_log.c.event_id == event["event_id"],
                        )
                    )
                    .mappings()
                    .one()
                )
                assert audit["actor_user_id"] == scope.owner_id
                assert audit["after_snapshot"]["reason"] == receipt["reason"]
                assert audit["after_snapshot"]["version"] == receipt["version"]

        # Failed writes roll back individually and must fail specifically through
        # immutable-history protection, not accidentally through a foreign key.
        for table, identity in (
            (tables.ai_issue_generation_bindings, UUID(candidate["binding_id"])),
            (tables.ai_issue_proposal_reviews, UUID(original_receipt["id"])),
        ):
            for statement in (
                table.update().values(created_at=func.clock_timestamp()),
                table.delete(),
            ):
                with pytest.raises(DBAPIError) as caught, scope.engine.begin() as c:
                    c.execute(
                        statement.where(
                            table.c.tenant_id == scope.tenant_id, table.c.id == identity
                        )
                    )
                assert getattr(caught.value.orig, "sqlstate", None) == "42501"
        assert (
            _ok(client.get(review_url, headers=headers, params={"before_version": 3}))["items"][-1]
            == original_receipt
        )

        applied = _ok(client.post(target, headers=headers, json=application))
        assert applied["application"]["disposition"] == "created"
        assert applied["review"]["version"] == 22 and not applied["review"]["can_change"]
        _conflict(
            client.post(
                review_url,
                headers=headers,
                json={**decline, "request_id": str(uuid4()), "expected_version": 22},
            ),
            "SOURCE_ALREADY_APPLIED",
        )
        final_replay = _ok(client.post(review_url, headers=headers, json=decline))
        assert final_replay["review_receipt"] == original_receipt
        assert final_replay["application"]["id"] == applied["application"]["id"]
        assert final_replay["review"]["version"] == 22 and not final_replay["review"]["can_change"]
        assert len(calls) == 2

        # Leave a separate source's insufficient-evidence proposal un-applied for
        # browser continuation. It can be declined/reopened without creating Issue.
        pending_case = scope.test_case(project)
        failed = client.post(
            f"/api/projects/{project}/npi/test-cases/{pending_case}/result",
            headers=headers,
            json={"status": "failed", "result_notes": "模拟：密封测试出现泄漏，发生条件待补。"},
        )
        assert failed.status_code == 200, failed.text
        pending_source = next(
            item
            for item in client.get(
                f"/api/projects/{project}/ai-issue-event-sources", headers=headers
            ).json()["items"]
            if item["source"].get("source_key") == f"test_case:{pending_case}"
        )
        pending_preparation = _ok(
            client.get(
                run_base + "/preparation",
                headers=headers,
                params={"event_row_id": pending_source["event_row_id"]},
            )
        )
        monkeypatch.setattr(
            factory,
            "response",
            lambda: response(
                json.dumps(
                    {
                        "disposition": "insufficient_evidence",
                        "open_questions": ["请补充泄漏发生条件。"],
                    },
                    ensure_ascii=False,
                )
            ),
        )
        pending = _ok(
            client.post(
                run_base,
                headers=headers,
                json={
                    "request_id": str(uuid4()),
                    "event_row_id": pending_source["event_row_id"],
                    "expected_digest": pending_preparation["source_digest"],
                },
            )
        )
        assert (
            pending["status"] == "succeeded" and pending["disposition"] == "insufficient_evidence"
        )
        pending_target = application_base + "/" + pending["run_id"]
        pending_change = {
            "request_id": str(uuid4()),
            "result_id": pending["result_id"],
            "expected_digest": pending_preparation["source_digest"],
            "expected_version": 0,
            "action": "decline",
            "reason": "隔离模拟：先补齐发生条件",
        }
        assert (
            _ok(client.post(pending_target + "/review", headers=headers, json=pending_change))[
                "review"
            ]["state"]
            == "declined"
        )
        pending_state = _ok(
            client.post(
                pending_target + "/review",
                headers=headers,
                json={
                    **pending_change,
                    "request_id": str(uuid4()),
                    "expected_version": 1,
                    "action": "reopen",
                    "reason": "隔离模拟：保留补证建议供后续核对",
                },
            )
        )
        assert pending_state["review"]["state"] == "reopened"
        assert pending_state["review"]["can_change"] and not pending_state["can_apply"]
        assert pending_state["application"] is None
        _conflict(
            client.post(
                pending_target,
                headers=headers,
                json={
                    "request_id": str(uuid4()),
                    "result_id": pending["result_id"],
                    "expected_digest": pending_preparation["source_digest"],
                },
            ),
            "EVIDENCE_REQUIRED",
        )
        with scope.engine.connect() as c:
            assert (
                c.execute(
                    select(func.count())
                    .select_from(tables.issues)
                    .where(tables.issues.c.tenant_id == scope.tenant_id)
                ).scalar_one()
                == 1
            )
            assert (
                c.execute(
                    select(tables.test_cases.c.related_issue_id).where(
                        tables.test_cases.c.tenant_id == scope.tenant_id,
                        tables.test_cases.c.id == pending_case,
                    )
                ).scalar_one()
                is None
            )

        # Revocation changes current authorization, never generation-time evidence.
        current_scope = _ok(client.get(application_base + "/scope", headers=headers))
        _ok(
            client.post(
                application_base + "/scope",
                headers=headers,
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": current_scope["scope"]["revision"],
                    "enabled": False,
                    "reason": "隔离模拟：暂停后保留原生成时授权证据",
                },
            )
        )
        for original_run, expected_binding in (
            (first, frozen_first),
            (run, candidate),
            (pending, pending["generation_binding"]),
        ):
            history = _ok(
                client.get(run_base, headers=headers, params={"run_id": original_run["run_id"]})
            )
            assert len(history["items"]) == 1
            assert history["items"][0]["generation_binding"] == expected_binding
        remaining = _ok(client.get(pending_target, headers=headers))
        assert remaining["application"] is None and remaining["review"]["can_change"]
        assert remaining["review"]["state"] == "reopened"
        assert len(calls) == 3
    finally:
        scope.dispose()
