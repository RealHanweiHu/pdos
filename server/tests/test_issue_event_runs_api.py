"""Real budgeted event-Issue requests, with an isolated synthetic model transport."""

# ruff: noqa: F811
import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.ai import capability_contract as registry
from app.ai.application_gateway import configured_application_gateway
from app.ai.capability_contract import CapabilityKey, CapabilityRollout
from app.api import ai_issue_event_runs as api
from app.db.schema import tables
from tests import test_application_budget_factory as factory
from tests.test_application_budget_factory import factory_setup  # noqa: F401
from tests.test_input_metering import publication
from tests.test_model_budget_controller import response
from tests.test_test_runs_api import (
    Scope,
    bearer_headers,
    client,  # noqa: F401
    isolated_test_run_database,  # noqa: F401
    runs_url,
)


@pytest.fixture(autouse=True)
def fixture_meter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        factory, "publication", lambda path: publication(path, qualified_input_limit=6000)
    )


def live(monkeypatch: pytest.MonkeyPatch) -> None:
    contracts = dict(registry.CAPABILITY_CONTRACTS)
    key = CapabilityKey.QUALITY_EVENT_ISSUE
    contracts[key] = contracts[key].model_copy(update={"rollout": CapabilityRollout.LIVE})
    monkeypatch.setattr(registry, "CAPABILITY_CONTRACTS", contracts)


@pytest.mark.parametrize("disposition", ["reuse_issue", "create_issue", "insufficient_evidence"])
def test_actual_source_budget_result_and_replay(
    client: TestClient,
    isolated_test_run_database: str,
    factory_setup: Any,
    monkeypatch: pytest.MonkeyPatch,
    disposition: str,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        live(monkeypatch)
        project = scope.project()
        case = scope.test_case(project)
        headers = bearer_headers(client)
        if disposition == "reuse_issue":
            r = client.post(
                runs_url(project, case),
                headers=headers,
                json={
                    "status": "failed",
                    "result_notes": "模拟：密封测试出现泄漏。",
                },
            )
            assert r.status_code == 201, r.text
            existing = r.json()["related_issue_id"]
        else:
            r = client.post(
                f"/api/projects/{project}/npi/test-cases/{case}/result",
                headers=headers,
                json={"status": "failed", "result_notes": "模拟：密封测试出现泄漏。"},
            )
            assert r.status_code == 200, r.text
            existing = None
        sources = client.get(f"/api/projects/{project}/ai-issue-event-sources", headers=headers)
        assert sources.status_code == 200, sources.text
        event = sources.json()["items"][0]
        base = f"/api/projects/{project}/ai-issue-event-runs"
        prepared = client.get(
            base + "/preparation", params={"event_row_id": event["event_row_id"]}, headers=headers
        )
        assert prepared.status_code == 200, prepared.text
        assert prepared.json()["can_request"]
        output: dict[str, Any] = {"disposition": disposition}
        if disposition == "reuse_issue":
            output["existing_issue_id"] = existing
        elif disposition == "create_issue":
            output.update(
                title="核对密封测试泄漏", description="模拟：密封测试出现泄漏。", severity="medium"
            )
        if disposition == "insufficient_evidence":
            output["open_questions"] = ["请补充泄漏发生条件。"]
        else:
            output["citations"] = [
                {"reference_id": "test.original.result_notes", "exact_quote": "密封测试出现泄漏"}
            ]
        environment, calls, _ = factory_setup
        monkeypatch.setattr(
            factory, "response", lambda: response(json.dumps(output, ensure_ascii=False))
        )
        monkeypatch.setattr(
            api,
            "configured_application_gateway",
            lambda e: configured_application_gateway(e, environment),
        )
        request = {
            "request_id": str(uuid4()),
            "event_row_id": event["event_row_id"],
            "expected_digest": prepared.json()["source_digest"],
        }
        result = client.post(base, headers=headers, json=request)
        assert result.status_code == 200, result.text
        body = result.json()
        assert body["status"] == "succeeded", body
        assert body["proposal"]["disposition"] == disposition
        assert len(calls) == 1
        wire = calls[0].content.decode()
        if existing:
            assert existing in wire  # The gateway projection must not drop the existing Issue ID.
        replay = client.post(base, headers=headers, json=request)
        assert replay.status_code == 200 and replay.json()["result_id"] == body["result_id"]
        assert len(calls) == 1
        history = client.get(base, headers=headers, params={"run_id": body["run_id"]})
        assert history.status_code == 200, history.text
        item = history.json()["items"][0]
        assert item["sources_current"] and item["frozen_sources"]
        with scope.engine.connect() as c:
            saved = (
                c.execute(
                    select(tables.ai_issue_event_results).where(
                        tables.ai_issue_event_results.c.run_id == UUID(body["run_id"])
                    )
                )
                .mappings()
                .one()
            )
            cp = (
                c.execute(
                    select(tables.application_result_checkpoints).where(
                        tables.application_result_checkpoints.c.run_id == saved["run_id"]
                    )
                )
                .mappings()
                .one()
            )
            assert saved["proposal"] == cp["body"]["output"]
            assert saved["model_invocation_id"] == cp["invocation_id"]
            assert c.execute(select(func.count()).select_from(tables.issues)).scalar_one() == (
                1 if existing else 0
            )
            assert c.execute(
                select(tables.budget_journal.c.id).where(
                    tables.budget_journal.c.run_id == saved["run_id"],
                    tables.budget_journal.c.reservation_status == "settled",
                )
            ).first()
        passed = client.post(
            runs_url(project, case),
            headers=headers,
            json={"status": "passed", "result_notes": "模拟：复测通过。"},
        )
        assert passed.status_code == 201, passed.text
        later = client.get(base, headers=headers, params={"run_id": body["run_id"]}).json()[
            "items"
        ][0]
        assert later["sources_current"] is False
        assert later["proposal"] == body["proposal"]
        assert len(calls) == 1
    finally:
        scope.dispose()


def test_changed_source_during_generation_keeps_model_receipt_without_issue_proposal(
    client: TestClient,
    isolated_test_run_database: str,
    factory_setup: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        live(monkeypatch)
        project, headers = scope.project(), bearer_headers(client)
        case = scope.test_case(project)
        original = client.post(
            runs_url(project, case),
            headers=headers,
            json={
                "status": "failed",
                "result_notes": "模拟：密封测试出现泄漏。",
            },
        )
        assert original.status_code == 201, original.text
        source = client.get(
            f"/api/projects/{project}/ai-issue-event-sources", headers=headers
        ).json()["items"][0]
        base = f"/api/projects/{project}/ai-issue-event-runs"
        environment, calls, _ = factory_setup

        def finish_after_pass() -> Any:
            updated = client.post(
                runs_url(project, case),
                headers=headers,
                json={
                    "status": "passed",
                    "result_notes": "模拟：模型生成期间复测已通过。",
                },
            )
            assert updated.status_code == 201, updated.text
            return response(
                json.dumps(
                    {
                        "disposition": "reuse_issue",
                        "existing_issue_id": original.json()["related_issue_id"],
                        "citations": [
                            {
                                "reference_id": "test.original.result_notes",
                                "exact_quote": "密封测试出现泄漏",
                            }
                        ],
                    }
                )
            )

        monkeypatch.setattr(factory, "response", finish_after_pass)
        monkeypatch.setattr(
            api,
            "configured_application_gateway",
            lambda e: configured_application_gateway(e, environment),
        )
        result = client.post(
            base,
            headers=headers,
            json={
                "request_id": str(uuid4()),
                "event_row_id": source["event_row_id"],
                "expected_digest": source["source_digest"],
            },
        )
        assert result.status_code == 200, result.text
        assert result.json()["status"] == "degraded"
        assert result.json()["proposal"] is None
        assert result.json()["error_code"] in {
            "EVENT_ISSUE_SOURCE_CHANGED",
            "APPLICATION_CONTEXT_SOURCE_CHANGED",
        }, result.json()
        assert len(calls) == 1
        with scope.engine.connect() as c:
            assert (
                c.execute(
                    select(func.count()).select_from(tables.ai_issue_event_results)
                ).scalar_one()
                == 0
            )
            assert (
                c.execute(select(func.count()).select_from(tables.model_invocations)).scalar_one()
                == 1
            )
            assert c.execute(select(func.count()).select_from(tables.issues)).scalar_one() == 1
    finally:
        scope.dispose()
