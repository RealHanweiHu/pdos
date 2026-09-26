"""Conversation → typed Finding → independent human revision, on pdos_test only."""

from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
from importlib import import_module
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.ai.call_identity import ModelCallSlot, model_call_id
from app.ai.context_projection import project_gateway_context
from app.ai.gateway import GatewayResult
from app.api.ai import get_application_gateway
from app.db.engine import get_engine
from app.db.schema import tables
from app.domain.test_plan_changes import TestPlanChangeError as PlanChangeError
from app.domain.test_plan_changes import TestPlanModelAssessment as PlanModelAssessment
from app.main import app
from tests.migration_fixtures import rollback_migration_operations
from tests.test_test_report_import_api import (  # noqa: F401
    Scope,
    bearer_headers,
    isolated_import_database,
)
from tests.test_test_templates import pilot_selection

MESSAGE = "客户追加测试：检查模拟指示功能，按测试夹具 A 执行，预期显示 A，记录照片。"
READY: dict[str, Any] = {
    "summary": "根据客户转述追加一项，工程测试用合成参数。",
    "questions": [],
    "changes": [
        {
            "operation": "add",
            "target_key": None,
            "reason": "客户新增要求；工程测试合成条件",
            "after": {
                "title": "模拟指示功能",
                "category": "whole_unit",
                "method": "按测试夹具 A 执行",
                "acceptance_criteria": "显示 A",
                "applicability": "本项目新增功能",
                "evidence_requirements": "记录照片",
                "required": True,
            },
            "references": [{"reference_id": "message:1", "quote": MESSAGE}],
            "unresolved": [],
        }
    ],
}


class Gateway:
    def __init__(self) -> None:
        self.output = deepcopy(READY)
        self.calls: list[Any] = []
        self.unavailable = False

    def invoke_structured(self, invocation: Any, output_type: Any) -> Any:
        assert invocation.model_call_id == model_call_id(
            invocation.run_id, ModelCallSlot.TEST_PLAN_SUGGESTION
        )
        self.calls.append(invocation)
        if self.unavailable:
            return GatewayResult(
                status="degraded",
                output=None,
                error_code="MODEL_NOT_AVAILABLE",
                structured_attempts=0,
                removed_context_paths=(),
            )
        invocation_id = uuid4()
        with get_engine().begin() as connection:
            connection.execute(
                tables.model_invocations.insert().values(
                    id=invocation_id,
                    tenant_id=invocation.tenant_id,
                    project_id=invocation.project_id,
                    run_id=invocation.run_id,
                    agent_key=invocation.agent_key,
                    agent_tier=invocation.agent_tier.value,
                    prompt_version=invocation.prompt_version,
                    provider="minimax",
                    model="fake-model",
                    protocol="openai-compatible",
                    status="succeeded",
                    structured_attempts=1,
                )
            )
        return GatewayResult(
            status="succeeded",
            output=output_type.model_validate(
                {
                    **self.output,
                    "changes": [
                        {
                            **{k: v for k, v in c.items() if k != "references"},
                            "reference_ids": [r["reference_id"] for r in c["references"]],
                        }
                        for c in self.output["changes"]
                    ],
                }
            ),
            error_code=None,
            structured_attempts=1,
            removed_context_paths=(),
            invocation_id=invocation_id,
        )


@pytest.fixture
def scenario(isolated_import_database: str) -> Iterator[Any]:  # noqa: F811
    gateway = Gateway()
    app.dependency_overrides[get_application_gateway] = lambda: gateway
    with TestClient(app) as client:
        scope = Scope(client, isolated_import_database)
        ids = scope.seed()
        headers = bearer_headers(client)
        path = f"/api/projects/{ids['project_id']}/npi"
        with scope.engine.connect() as connection:
            old_plan = (
                connection.execute(
                    select(tables.test_plans).where(tables.test_plans.c.id == ids["plan_id"])
                )
                .mappings()
                .one()
            )
        response = client.post(
            path + "/test-plans",
            headers=headers,
            json={
                "stage_id": str(old_plan["stage_id"]),
                "phase": "evt",
                "title": "合成项目测试计划",
                "scope": "仅测试",
                "sample_size": 1,
                "status": "draft",
                "template": pilot_selection().model_dump(mode="json"),
            },
        )
        assert response.status_code == 201, response.text
        plan = response.json()
        try:
            yield client, scope, gateway, headers, path, plan
        finally:
            scope.dispose()


def suggest(scenario: Any, **changes: Any) -> Any:
    client, _, _, headers, path, plan = scenario
    return client.post(
        f"{path}/test-plans/{plan['id']}/suggestions",
        headers=headers,
        json={"message": MESSAGE, "request_id": str(uuid4()), **changes},
    )


def get_finding(scenario: Any, response: Any) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "created", response.text
    client, _, _, headers, _, _ = scenario
    result = client.get(f"/api/ai/findings/{response.json()['finding_id']}", headers=headers)
    assert result.status_code == 200, result.text
    payload = result.json()
    assert isinstance(payload, dict)
    return payload


def test_human_revision_preserves_history_and_replays(scenario: Any) -> None:
    client, scope, gateway, headers, path, plan = scenario
    with scope.engine.connect() as connection:
        case_id = (
            connection.execute(
                select(tables.test_cases.c.id).where(
                    tables.test_cases.c.plan_id == UUID(plan["id"])
                )
            )
            .scalars()
            .first()
        )
    recorded = client.post(
        f"{path}/test-cases/{case_id}/runs",
        headers=headers,
        json={"status": "passed", "result_notes": "历史合成结果"},
    )
    assert recorded.status_code == 201, recorded.text
    report = client.post(
        f"{path}/test-plans/{plan['id']}/reports",
        headers=headers,
        json={
            "report_number": "HISTORY-1",
            "title": "原计划报告",
            "result": "pass",
            "summary": "仅测试用历史记录",
        },
    )
    assert report.status_code == 201, report.text
    request_id = str(uuid4())
    finding = get_finding(scenario, suggest(scenario, request_id=request_id))
    assert suggest(scenario, request_id=request_id).json()["finding_id"] == finding["id"]
    assert len(gateway.calls) == 1
    route = f"/api/ai/findings/{finding['id']}"
    assert client.post(route + "/apply", headers=headers).status_code == 409
    assert (
        client.post(route + "/review", headers=headers, json={"decision": "accepted"}).status_code
        == 200
    )
    before = client.get(path, headers=headers).json()
    assert not any(p.get("parent_plan_id") for p in before["test_plans"])
    applied = client.post(route + "/apply", headers=headers)
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied_entity_type"] == "test_plan"
    replay = client.post(route + "/apply", headers=headers)
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["applied_entity_type"] == "test_plan"
    assert replay.json()["applied_entity_id"] == applied.json()["applied_entity_id"]
    after = client.get(path, headers=headers).json()
    original = next(p for p in after["test_plans"] if p["id"] == plan["id"])
    assert original == next(p for p in before["test_plans"] if p["id"] == plan["id"])
    revised = next(p for p in after["test_plans"] if p.get("parent_plan_id") == plan["id"])
    assert revised["source_finding_id"] == finding["id"]
    assert revised["coverage"]["required"] == 30
    assert revised["coverage"]["covered"] == 0
    cases = [c for c in after["test_cases"] if c["plan_id"] == revised["id"]]
    assert len(cases) == 30 and all(c["status"] == "planned" for c in cases)
    assert after["test_reports"] == before["test_reports"]
    history = client.get(f"{path}/test-cases/{case_id}/runs", headers=headers)
    assert history.status_code == 200 and "历史合成结果" in history.text
    assert len({c["id"] for c in cases}) == 30
    with scope.engine.connect() as connection:
        assert (
            connection.execute(
                select(tables.test_runs).where(
                    tables.test_runs.c.test_case_id.in_([UUID(c["id"]) for c in cases])
                )
            ).first()
            is None
        )
    assert suggest(scenario).status_code == 409  # No parallel successor off old baseline.
    with (
        rollback_migration_operations(scope.engine),
        pytest.raises(RuntimeError, match="refusing downgrade"),
    ):
        import_module("migrations.versions.0058_ai_test_plan_changes").downgrade()


def test_unresolved_and_forged_references_cannot_be_accepted(scenario: Any) -> None:
    client, _, gateway, headers, _, _ = scenario
    gateway.output["questions"] = ["请提供判定条件"]
    gateway.output["changes"][0]["after"]["acceptance_criteria"] = ""
    finding = get_finding(scenario, suggest(scenario))
    route = f"/api/ai/findings/{finding['id']}/review"
    assert client.post(route, headers=headers, json={"decision": "accepted"}).status_code == 409
    edited = deepcopy(finding["proposed_payload"])
    edited["questions"] = []
    edited["changes"] = deepcopy(READY["changes"])
    edited["base_plan_id"] = str(uuid4())
    assert (
        client.post(
            route, headers=headers, json={"decision": "accepted", "edited_payload": edited}
        ).status_code
        == 409
    )
    edited["base_plan_id"] = finding["proposed_payload"]["base_plan_id"]
    edited["changes"][0]["references"][0]["quote"] = "不存在的客户承诺"
    assert (
        client.post(
            route, headers=headers, json={"decision": "accepted", "edited_payload": edited}
        ).status_code
        == 409
    )
    edited["changes"][0]["references"][0]["quote"] = MESSAGE
    assert (
        client.post(
            route, headers=headers, json={"decision": "accepted", "edited_payload": edited}
        ).status_code
        == 200
    )
    gateway.output = deepcopy(READY)
    gateway.output["changes"][0]["references"][0]["reference_id"] = "message:999"
    assert suggest(scenario).status_code == 409


def test_multiturn_supersedes_old_candidate_and_detects_changed_plan(scenario: Any) -> None:
    client, scope, gateway, headers, path, plan = scenario
    first = get_finding(scenario, suggest(scenario))
    second = get_finding(
        scenario, suggest(scenario, previous_finding_id=first["id"], message="其余沿用")
    )
    assert second["proposed_payload"]["messages"] == [MESSAGE, "其余沿用"]
    assert gateway.calls[-1].context["test_plan"]["previous_proposal"]
    assert (
        client.post(
            f"/api/ai/findings/{first['id']}/review", headers=headers, json={"decision": "accepted"}
        ).status_code
        == 409
    )
    with scope.engine.begin() as connection:
        case = connection.execute(
            select(tables.test_cases.c.id).where(tables.test_cases.c.plan_id == UUID(plan["id"]))
        ).first()
        assert case
        connection.execute(
            update(tables.test_cases)
            .where(tables.test_cases.c.id == case[0])
            .values(method="人工更新后的方法")
        )
    response = client.post(
        f"/api/ai/findings/{second['id']}/review", headers=headers, json={"decision": "accepted"}
    )
    assert response.status_code == 409
    assert "原计划" in response.text


def test_scope_request_integrity_and_model_removal(scenario: Any) -> None:
    client, _, gateway, headers, path, plan = scenario
    req = str(uuid4())
    get_finding(scenario, suggest(scenario, request_id=req))
    assert suggest(scenario, request_id=req, message="不同内容").status_code == 409
    assert (
        client.post(
            f"{path}/test-plans/{uuid4()}/suggestions",
            headers=headers,
            json={"message": MESSAGE, "request_id": str(uuid4())},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/projects/{uuid4()}/npi/test-plans/{plan['id']}/suggestions",
            headers=headers,
            json={"message": MESSAGE, "request_id": str(uuid4())},
        ).status_code
        == 403
    )
    assert suggest(scenario, actor_user_id=str(uuid4())).status_code == 422
    gateway.unavailable = True
    response = suggest(scenario)
    assert response.status_code == 200 and response.json()["status"] == "unavailable"
    assert not any(
        p.get("parent_plan_id") for p in client.get(path, headers=headers).json()["test_plans"]
    )


def test_projection_preserves_whitelisted_template_only() -> None:
    result = project_gateway_context(
        {
            "test_plan": {
                "product_type": "合成",
                "password": "secret",
                "items": [{"key": "a", "title": "A", "method": "B", "private_notes": "hidden"}],
            }
        }
    )
    plan = result.payload["test_plan"]
    assert isinstance(plan, dict) and "password" not in plan
    assert result.removed_paths == ("test_plan.items[0].private_notes", "test_plan.password")


def test_model_can_select_sources_but_cannot_supply_quote_text() -> None:
    change = {k: v for k, v in READY["changes"][0].items() if k != "references"}
    assessment = PlanModelAssessment.model_validate(
        {
            "summary": "合成建议",
            "questions": [],
            "changes": [{**change, "reference_ids": ["message:1"]}],
        }
    )
    source = "  用户原话：输入 A，\n显示 A。  "
    bound = assessment.bind_sources({"message:1": source})
    assert bound.changes[0].references[0].quote == source.strip()
    with pytest.raises(PlanChangeError, match="不存在"):
        assessment.bind_sources({"message:2": source})
    assessment.changes[0].reference_ids.append("message:1")
    with pytest.raises(PlanChangeError, match="重复"):
        assessment.bind_sources({"message:1": source})
    with pytest.raises(ValueError, match="Extra inputs"):
        PlanModelAssessment.model_validate(
            {
                "summary": "合成建议",
                "questions": [],
                "changes": [
                    {
                        **change,
                        "reference_ids": ["message:1"],
                        "references": [{"reference_id": "message:1", "quote": "模型伪造"}],
                    }
                ],
            }
        )


def test_exclusion_of_failed_case_and_duplicate_title_are_blocked(scenario: Any) -> None:
    client, scope, gateway, headers, path, plan = scenario
    with scope.engine.connect() as connection:
        case = (
            connection.execute(
                select(tables.test_cases).where(tables.test_cases.c.plan_id == UUID(plan["id"]))
            )
            .mappings()
            .first()
        )
    assert case
    failed = client.post(
        f"{path}/test-cases/{case['id']}/result",
        headers=headers,
        json={"status": "failed", "result_notes": "合成失败"},
    )
    assert failed.status_code == 200, failed.text
    gateway.output["changes"][0].update(
        operation="exclude", target_key=case["template_item_key"], after=None
    )
    finding = get_finding(scenario, suggest(scenario))
    rejected = client.post(
        f"/api/ai/findings/{finding['id']}/review", headers=headers, json={"decision": "accepted"}
    )
    assert rejected.status_code == 409 and "测试决策" in rejected.text
    gateway.output = deepcopy(READY)
    gateway.output["changes"][0]["after"]["title"] = case["title"]
    assert suggest(scenario).status_code == 409


def test_modify_and_exclude_preserve_keys_then_allow_next_revision(scenario: Any) -> None:
    client, _, gateway, headers, path, plan = scenario
    before = client.get(path, headers=headers).json()
    old_cases = [c for c in before["test_cases"] if c["plan_id"] == plan["id"]]
    modified, excluded = old_cases[:2]
    change = deepcopy(READY["changes"][0])
    change.update(operation="modify", target_key=modified["template_item_key"])
    change["after"]["title"] = modified["title"]
    gateway.output["changes"] = [
        change,
        {
            "operation": "exclude",
            "target_key": excluded["template_item_key"],
            "reason": "合成项目取消此功能，原项尚未执行",
            "after": None,
            "references": [{"reference_id": "message:1", "quote": MESSAGE}],
            "unresolved": [],
        },
    ]
    finding = get_finding(scenario, suggest(scenario))
    route = f"/api/ai/findings/{finding['id']}"
    review = client.post(route + "/review", headers=headers, json={"decision": "accepted"})
    assert review.status_code == 200, review.text
    applied = client.post(route + "/apply", headers=headers)
    assert applied.status_code == 200, applied.text
    state = client.get(path, headers=headers).json()
    child = next(p for p in state["test_plans"] if p.get("parent_plan_id") == plan["id"])
    assert child["coverage"]["required"] == 28 and child["coverage"]["covered"] == 0
    new_cases = [c for c in state["test_cases"] if c["plan_id"] == child["id"]]
    updated = next(c for c in new_cases if c["template_item_key"] == modified["template_item_key"])
    assert updated["method"] == change["after"]["method"]
    assert updated["id"] != modified["id"]
    assert excluded["template_item_key"] not in {c["template_item_key"] for c in new_cases}
    assert [c for c in state["test_cases"] if c["plan_id"] == plan["id"]] == old_cases
    exclusion = next(
        i for i in child["template_snapshot"]["items"] if i["key"] == excluded["template_item_key"]
    )
    assert exclusion["applicable"] is False and exclusion["exclusion_reason"]
    gateway.output = deepcopy(READY)
    response = client.post(
        f"{path}/test-plans/{child['id']}/suggestions",
        headers=headers,
        json={"message": MESSAGE, "request_id": str(uuid4())},
    )
    next_finding = get_finding(scenario, response)
    route = f"/api/ai/findings/{next_finding['id']}"
    assert (
        client.post(route + "/review", headers=headers, json={"decision": "accepted"}).status_code
        == 200
    )
    assert client.post(route + "/apply", headers=headers).status_code == 200
    state = client.get(path, headers=headers).json()
    next_plan = next(p for p in state["test_plans"] if p.get("parent_plan_id") == child["id"])
    assert next_plan["template_snapshot"]["plan_revision"] == 3
    assert next_plan["coverage"]["required"] == 29


@pytest.mark.parametrize("stop_during_model", [False, True])
def test_plan_suggestion_respects_rollout_before_call_and_before_finding(
    scenario: Any,
    monkeypatch: pytest.MonkeyPatch,
    stop_during_model: bool,
) -> None:
    from app.ai.capability_contract import CapabilityRollout
    from app.ai.runtime_contract import AgentKey
    from tests.rollout_support import set_agent_rollout

    _, scope, gateway, _, _, _ = scenario
    original = gateway.invoke_structured

    def invoke_then_disable(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        set_agent_rollout(monkeypatch, AgentKey.QUALITY_INTELLIGENCE, CapabilityRollout.DISABLED)
        return result

    if stop_during_model:
        monkeypatch.setattr(gateway, "invoke_structured", invoke_then_disable)
    else:
        set_agent_rollout(monkeypatch, AgentKey.QUALITY_INTELLIGENCE, CapabilityRollout.DISABLED)
    response = suggest(scenario)
    if stop_during_model:
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "unavailable"
        assert response.json()["error_code"] == "CAPABILITY_DISABLED"
        with scope.engine.connect() as connection:
            assert connection.execute(select(tables.findings.c.id)).first() is None
            assert connection.execute(select(tables.agent_runs.c.status)).scalar_one() == "degraded"
    else:
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "CAPABILITY_DISABLED"
    assert len(gateway.calls) == int(stop_during_model)
