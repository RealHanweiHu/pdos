"""Actual observation HTTP chain for a freshly isolated test database only.

Synthetic transport drives the real budget/gateway path. These tests never prove
real-provider quality or automatic qualification. Do not run on retained tenants.
"""

# ruff: noqa: F811
import json
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import DBAPIError

from app.db.schema import tables
from app.db.url import psycopg_database_url
from tests import test_application_budget_factory as factory
from tests.test_ai_issue_proposal_reviews_api import (
    test_generation_binding_review_history_replay_and_application_guards as exercise_chain,
)
from tests.test_application_budget_factory import factory_setup  # noqa: F401
from tests.test_issue_event_runs_api import fixture_meter  # noqa: F401
from tests.test_model_budget_controller import response
from tests.test_test_runs_api import (
    PASSWORD,
    bearer_headers,
    client,  # noqa: F401
    isolated_test_run_database,  # noqa: F401
)


def ok(reply: Any) -> dict[str, Any]:
    assert reply.status_code == 200, reply.text
    assert reply.headers["cache-control"] == "no-store"
    value: dict[str, Any] = reply.json()
    return value


def conflict(reply: Any, code: str) -> None:
    assert reply.status_code == 409, reply.text
    assert reply.json()["detail"]["code"] == code, reply.text


def test_complete_observation_history_replay_and_actual_failed_run(
    client: TestClient,
    isolated_test_run_database: str,
    factory_setup: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # One setup/fixture lifecycle, preserving all original receipts from this chain.
    exercise_chain(client, isolated_test_run_database, factory_setup, monkeypatch)
    engine = create_engine(psycopg_database_url(isolated_test_run_database))
    headers = bearer_headers(client)
    _, calls, _ = factory_setup
    try:
        with engine.connect() as c:
            runs = list(
                c.execute(
                    select(tables.agent_runs).where(
                        tables.agent_runs.c.context_version == "event-issue-request-v1"
                    )
                ).mappings()
            )
            assert len(runs) == 3
            project, tenant, owner = (
                runs[0]["project_id"],
                runs[0]["tenant_id"],
                runs[0]["requested_by_user_id"],
            )
            assert all(r["project_id"] == project and r["tenant_id"] == tenant for r in runs)
            stamp = c.execute(select(func.clock_timestamp())).scalar_one()
        base = f"/api/projects/{project}/ai-issue-observations"
        body = {
            "request_id": str(uuid4()),
            "window_start": (min(r["created_at"] for r in runs) - timedelta(seconds=1)).isoformat(),
            "window_end": stamp.isoformat(),
        }
        empty_history = ok(client.get(base, headers=headers))
        assert empty_history == {"items": [], "next_before_id": None, "can_capture": True}
        first = ok(client.post(base, headers=headers, json=body))
        assert first["total_runs"] == first["counts"]["total_runs"] == len(first["items"]) == 3
        assert first["actor_user_id"] == str(owner)
        assert first["project_id"] == str(project)
        assert (
            first["qualification_granted"] is False and first["ratios"]["descriptive_only"] is True
        )
        assert {item["run_id"] for item in first["items"]} == {str(r["id"]) for r in runs}
        assert all(item["provider_verified"] is False for item in first["items"])
        for name, expected in {
            "succeeded_runs": 3,
            "failed_runs": 0,
            "pending_runs": 0,
            "proposal_runs": 3,
            "created_issues": 1,
            "reused_issues": 0,
            "same_source_applied_runs": 1,
            "insufficient_runs": 1,
            "unhandled_proposals": 1,
            "trial_candidates": 2,
            "evidence_only_runs": 1,
            "unrecorded_bindings": 0,
            "declined_runs": 0,
            "reopened_runs": 2,
        }.items():
            assert first["counts"][name] == expected, first["counts"]
        assert first["ratios"]["handled_proposals"] == first["ratios"]["confirmed_proposals"] == 1
        assert first["ratios"]["confirmation_basis_points"] == 10000
        assert first["ratios"]["withdrawal_basis_points"] == 0
        assert ok(client.get(base + "/" + first["id"], headers=headers)) == first
        assert ok(client.post(base, headers=headers, json=body)) == first
        conflict(
            client.post(
                base,
                headers=headers,
                json={
                    **body,
                    "window_start": (
                        min(r["created_at"] for r in runs) - timedelta(seconds=2)
                    ).isoformat(),
                },
            ),
            "REQUEST_ID_REUSED",
        )

        # The separate insufficient proposal is a genuine unhandled candidate.
        pending = next(v for v in first["items"] if v["disposition"] == "insufficient_evidence")
        review_url = f"/api/projects/{project}/ai-issue-applications/{pending['run_id']}/review"
        review = ok(
            client.post(
                review_url,
                headers=headers,
                json={
                    "request_id": str(uuid4()),
                    "result_id": pending["result_id"],
                    "expected_digest": pending["source_digest"],
                    "expected_version": pending["review_version"],
                    "action": "decline",
                    "reason": "隔离模拟：观察后暂不采纳，等待补充发生条件",
                },
            )
        )
        assert review["review"]["state"] == "declined"
        second = ok(client.post(base, headers=headers, json={**body, "request_id": str(uuid4())}))
        assert second["id"] != first["id"]
        assert (
            second["counts"]["declined_runs"] == 1 and second["counts"]["unhandled_proposals"] == 0
        )
        assert second["counts"]["reopened_runs"] == 1
        assert second["ratios"]["handled_proposals"] == 2
        assert second["ratios"]["confirmed_proposals"] == 1
        assert second["ratios"]["confirmation_basis_points"] == 5000
        assert ok(client.get(base + "/" + first["id"], headers=headers)) == first
        assert ok(client.post(base, headers=headers, json=body)) == first

        # Create an actual degraded runtime via HTTP source change during the
        # synthetic provider call; never insert fake run/model/result grades.
        case = UUID(pending["source_key"].split(":", 1)[1])
        run_base = f"/api/projects/{project}/ai-issue-event-runs"
        prepared = ok(
            client.get(
                run_base + "/preparation",
                headers=headers,
                params={"event_row_id": pending["event_row_id"]},
            )
        )
        before_calls = len(calls)

        def finish_after_pass() -> Any:
            changed = client.post(
                f"/api/projects/{project}/npi/test-cases/{case}/result",
                headers=headers,
                json={"status": "passed", "result_notes": "隔离模拟：建议生成期间复测通过"},
            )
            assert changed.status_code == 200, changed.text
            return response(
                json.dumps(
                    {
                        "disposition": "insufficient_evidence",
                        "open_questions": ["请补充泄漏发生条件。"],
                    },
                    ensure_ascii=False,
                )
            )

        monkeypatch.setattr(factory, "response", finish_after_pass)
        failed = ok(
            client.post(
                run_base,
                headers=headers,
                json={
                    "request_id": str(uuid4()),
                    "event_row_id": pending["event_row_id"],
                    "expected_digest": prepared["source_digest"],
                },
            )
        )
        assert failed["status"] == "degraded" and failed["result_id"] is None
        assert failed["error_code"] in {
            "EVENT_ISSUE_SOURCE_CHANGED",
            "APPLICATION_CONTEXT_SOURCE_CHANGED",
        }
        assert len(calls) == before_calls + 1
        with engine.connect() as c:
            stamp = c.execute(select(func.clock_timestamp())).scalar_one()
        all_body = {**body, "request_id": str(uuid4()), "window_end": stamp.isoformat()}
        with_failed = ok(client.post(base, headers=headers, json=all_body))
        assert with_failed["total_runs"] == with_failed["counts"]["total_runs"] == 4
        assert (
            with_failed["counts"]["failed_runs"] == 1
            and with_failed["counts"]["proposal_runs"] == 3
        )
        failed_item = next(i for i in with_failed["items"] if i["run_id"] == failed["run_id"])
        assert failed_item["status"] == "degraded" and failed_item["result_id"] is None
        assert failed_item["disposition"] is None and failed_item["model_calls"]
        assert (
            with_failed["counts"]["evidence_only_runs"] == 2
        )  # Scope was revoked by the original chain.
        assert ok(client.get(base + "/" + first["id"], headers=headers)) == first

        conflict(
            client.post(
                base,
                headers=headers,
                json={
                    **all_body,
                    "request_id": str(uuid4()),
                    "window_end": (stamp + timedelta(days=1)).isoformat(),
                },
            ),
            "WINDOW_NOT_CLOSED",
        )
        empty = ok(
            client.post(
                base,
                headers=headers,
                json={
                    "request_id": str(uuid4()),
                    "window_start": (stamp - timedelta(days=2)).isoformat(),
                    "window_end": (stamp - timedelta(days=1)).isoformat(),
                },
            )
        )
        assert empty["total_runs"] == 0 and empty["items"] == []
        assert empty["ratios"]["confirmation_basis_points"] is None
        assert empty["ratios"]["withdrawal_basis_points"] is None

        # Every entry is a real POST, enough to cross the stable 20-row boundary.
        observations = [first, second, with_failed, empty]
        for _ in range(17):
            observations.append(
                ok(client.post(base, headers=headers, json={**body, "request_id": str(uuid4())}))
            )
        newest = sorted(observations, key=lambda v: (v["created_at"], v["id"]), reverse=True)
        page = ok(client.get(base, headers=headers))
        assert [v["id"] for v in page["items"]] == [v["id"] for v in newest[:20]]
        assert page["next_before_id"] == newest[19]["id"]
        tail = ok(client.get(base, headers=headers, params={"before_id": page["next_before_id"]}))
        assert [v["id"] for v in tail["items"]] == [newest[20]["id"]]
        assert tail["next_before_id"] is None
        conflict(
            client.get(base, headers=headers, params={"before_id": str(uuid4())}), "CURSOR_INVALID"
        )

        # A separate same-tenant project must not reuse another project's request
        # or dereference its observation/cursor. No model evidence is fabricated.
        other, other_workflow, other_stage = uuid4(), uuid4(), uuid4()
        with engine.begin() as c:
            c.execute(
                tables.workflows.insert().values(
                    id=other_workflow, tenant_id=tenant, code="OBS-OTHER", name="观察独立流程"
                )
            )
            c.execute(
                tables.stages.insert().values(
                    id=other_stage,
                    tenant_id=tenant,
                    workflow_id=other_workflow,
                    code="evt",
                    name="EVT",
                    sequence=1,
                )
            )
            c.execute(
                tables.projects.insert().values(
                    id=other,
                    tenant_id=tenant,
                    workflow_id=other_workflow,
                    current_stage_id=other_stage,
                    owner_user_id=owner,
                    code="OBS-OTHER",
                    name="观察范围隔离模拟",
                    status="active",
                )
            )
        other_base = f"/api/projects/{other}/ai-issue-observations"
        conflict(client.post(other_base, headers=headers, json=body), "REQUEST_ID_REUSED")
        assert client.get(other_base + "/" + first["id"], headers=headers).status_code == 404
        conflict(
            client.get(other_base, headers=headers, params={"before_id": first["id"]}),
            "CURSOR_INVALID",
        )
        assert (
            client.get(
                f"/api/projects/{uuid4()}/ai-issue-observations", headers=headers
            ).status_code
            == 404
        )
        user = client.post(
            "/api/admin/users",
            headers=headers,
            json={
                "username": "observation-supplier",
                "display_name": "隔离模拟供方",
                "role": "supplier",
                "password": PASSWORD,
            },
        )
        assert user.status_code == 201, user.text
        login = client.post(
            "/api/auth/login",
            json={
                "tenant_slug": "beepump",
                "username": "observation-supplier",
                "password": PASSWORD,
            },
        )
        assert login.status_code == 200, login.text
        forbidden_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assert client.get(base, headers=forbidden_headers).status_code == 403
        assert client.get(base + "/" + first["id"], headers=forbidden_headers).status_code == 403
        assert (
            client.post(
                base, headers=forbidden_headers, json={**body, "request_id": str(uuid4())}
            ).status_code
            == 403
        )

        table = tables.ai_issue_observations
        for statement in (table.update().values(created_at=func.clock_timestamp()), table.delete()):
            with pytest.raises(DBAPIError) as caught, engine.begin() as c:
                c.execute(
                    statement.where(table.c.tenant_id == tenant, table.c.id == UUID(first["id"]))
                )
            assert getattr(caught.value.orig, "sqlstate", None) == "42501"
        assert ok(client.get(base + "/" + first["id"], headers=headers)) == first
        assert len(calls) == 4  # Captures, history, retries and denials have no model calls.
    finally:
        engine.dispose()
