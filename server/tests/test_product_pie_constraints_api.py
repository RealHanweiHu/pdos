"""Queued PIE domain/API cases; synthetic work, not qualification or manual Exit.

Contract section 6.4 maps PIE to existing roles and separately named work. The
coordinator must allocate an exclusive local pdos_test before these cases run.
No model, role-policy, migration, shared fixture, or production behavior is mocked.
"""

from collections.abc import Iterator
from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.contracts.product_records import StrategyCanvas
from app.db.schema import tables
from tests.product_master_reference_fixtures import (
    master_reference_database_guard as master_reference_database_guard,
)
from tests.test_product_discovery_findings_api import seed_discovery
from tests.test_product_manager_loop_api import command
from tests.test_product_work_preparation_api import space
from tests.test_product_work_result_evidence_api import evidence
from tests.test_test_runs_api import PASSWORD, Scope
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database


@dataclass
class PieCandidate:
    client: TestClient
    scope: Scope
    seed: dict[str, Any]
    reference: dict[str, Any]

    @property
    def base(self) -> str:
        return str(self.seed["base"])

    @property
    def headers(self) -> dict[str, str]:
        return dict(self.seed["headers"])

    @property
    def line_id(self) -> str:
        return str(self.seed["line"]["id"])

    def post(
        self,
        path: str,
        body: dict[str, Any],
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        response = self.client.post(self.base + path, headers=headers or self.headers, json=body)
        assert response.status_code == status, (path, response.text)
        return dict(response.json())

    def read(self, path: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
        response = self.client.get(self.base + path, headers=headers or self.headers)
        assert response.status_code == 200, response.text
        return dict(response.json())

    def content(self, manufacturing: str = "pie") -> dict[str, Any]:
        fact = {
            "text": "合成PIE输入：版本、装配方法、工时和制造成本仍待真实验证",
            "fact_kind": "hypothesis",
            "sources": [self.reference],
        }
        budget = {"amount": None, "basis": fact}
        return {
            "title": "合成PIE策略，非业务实测",
            "owner_user_id": str(self.scope.owner_id),
            "canvas": {key: fact for key in StrategyCanvas.model_fields},
            "selected_solution_id": self.seed["opportunity"]["solutions"][0]["id"],
            "route_comparisons": [
                {
                    "solution_id": solution["id"],
                    "currency": "CNY",
                    "price_target": budget,
                    "nre_budget": budget,
                    "id_cycle_days": budget,
                    "modules": [{"key": "assembly", "name": "装配", "target": budget}],
                    **{
                        key: fact
                        for key in (
                            "scope",
                            "quality",
                            "supply",
                            "manufacturing",
                            "resources",
                            "trade_off",
                        )
                    },
                }
                for solution in self.seed["opportunity"]["solutions"]
            ],
            "professional_constraints": [
                {
                    "id": str(uuid4()),
                    "discipline": discipline,
                    "statement": fact,
                    "disposition": {
                        "outcome": "deferred",
                        "reason": "明确保留假设，后续由有效责任人补实际证据",
                        "sources": [self.reference],
                    },
                }
                for discipline in ("dqe", "sqe", manufacturing)
            ],
            "unknowns": ["原件配置版本待核对", "实际工时、节拍、产能和制造成本未知"],
            "decision_reason": "具名策略取舍保留专业未决事项，不宣称制造已验收",
        }

    def create(
        self, content: dict[str, Any], headers: dict[str, str] | None = None, status: int = 201
    ) -> dict[str, Any]:
        return self.post(
            "/strategies",
            {
                "request_id": str(uuid4()),
                "opportunity_id": self.seed["opportunity"]["id"],
                "content": content,
            },
            status,
            headers,
        )

    def act(
        self,
        row: dict[str, Any],
        action: str,
        headers: dict[str, str] | None = None,
        status: int = 200,
    ) -> dict[str, Any]:
        return self.post(
            f"/strategies/{row['id']}/actions",
            {**command(row), "action": action, "reason": "合成具名策略操作"},
            status,
            headers,
        )

    def work(
        self,
        title: str,
        owner: str | None = None,
        receiver: str | None = None,
        *,
        base: str | None = None,
        line_id: str | None = None,
        action_type: str = "constraint_review",
    ) -> dict[str, Any]:
        response = self.client.post(
            (base or self.base) + "/work-items",
            headers=self.headers,
            json={
                "request_id": str(uuid4()),
                "product_line_id": line_id or self.line_id,
                "title": title,
                "action_type": action_type,
                "owner_user_id": owner or str(self.scope.owner_id),
                "receiver_user_id": receiver or str(self.scope.owner_id),
                "expected_output": title + "：保留原配置/版本、来源及未知，不填实测值",
                "completion_criteria": "接收人核对合成输出原文及适用边界",
            },
        )
        assert response.status_code == 201, response.text
        return dict(response.json())

    def work_action(
        self,
        row: dict[str, Any],
        action: str,
        headers: dict[str, str] | None = None,
        status: int = 200,
        sources: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return self.post(
            f"/work-items/{row['id']}/actions",
            {
                **command(row),
                "action": action,
                "note": "合成PIE专业办理，非现场试产或真人验收",
                "evidence": sources or [],
            },
            status,
            headers,
        )

    def line_access(self, user_id: str, access: str) -> None:
        line = next(item for item in self.read("/products")["nodes"] if item["id"] == self.line_id)
        self.post(
            f"/products/{self.line_id}/members",
            {**command(line), "user_id": user_id, "access": access},
        )

    def member(self, role: str) -> tuple[str, dict[str, str]]:
        username = "pie-" + uuid4().hex[:12]
        created = self.client.post(
            "/api/admin/users",
            headers=self.headers,
            json={
                "username": username,
                "display_name": "合成PIE协作人",
                "role": role,
                "password": PASSWORD,
            },
        )
        assert created.status_code == 201, created.text
        user_id = str(created.json()["id"])
        granted = self.client.put(
            self.base + f"/members/{user_id}", headers=self.headers, json={"access": "manager"}
        )
        assert granted.status_code == 204, granted.text
        self.line_access(user_id, "manager")
        login = self.client.post(
            "/api/auth/login",
            json={"tenant_slug": "beepump", "username": username, "password": PASSWORD},
        )
        assert login.status_code == 200, login.text
        return user_id, {"Authorization": "Bearer " + login.json()["access_token"]}

    def state(self) -> dict[str, list[dict[str, Any]]]:
        with self.scope.engine.connect() as connection:
            return {
                table.name: [
                    dict(row)
                    for row in connection.execute(
                        select(table)
                        .where(table.c.tenant_id == self.scope.tenant_id)
                        .order_by(table.c.id)
                    ).mappings()
                ]
                for table in (
                    tables.product_strategies,
                    tables.scoped_work_items,
                    tables.events,
                    tables.audit_log,
                )
            }


@pytest.fixture
def pie_candidate(client: TestClient, isolated_test_run_database: str) -> Iterator[PieCandidate]:
    scope = Scope(client, isolated_test_run_database)
    try:
        yield PieCandidate(client, scope, seed_discovery(client, scope), evidence(scope, "body"))
        with scope.engine.connect() as connection:
            for table in (tables.projects, tables.agent_runs, tables.model_invocations):
                assert (
                    connection.execute(
                        select(func.count())
                        .select_from(table)
                        .where(table.c.tenant_id == scope.tenant_id)
                    ).scalar_one()
                    == 0
                )
    finally:
        scope.dispose()


@pytest.mark.parametrize("manufacturing", ["pie", "PIE", "ie"])
def test_pie_and_legacy_ie_publish_preserve_tag_unknowns_and_fixed_sources(
    pie_candidate: PieCandidate, manufacturing: str
) -> None:
    fixture = pie_candidate
    content = fixture.content(manufacturing)
    row = fixture.create(content)
    assert row["publication_blockers"] == []
    row = fixture.act(row, "submit")
    published = fixture.act(row, "publish")
    assert published["state"] == "published"
    assert published["approval"]["approved_by_user_id"] == str(fixture.scope.owner_id)
    assert published["professional_constraints"][-1]["discipline"] == manufacturing
    assert published["professional_constraints"][-1]["disposition"]["outcome"] == "deferred"
    assert published["professional_constraints"][-1]["statement"]["fact_kind"] == "hypothesis"
    assert (
        published["professional_constraints"][-1]["statement"]["sources"][0]["ref_id"]
        == (fixture.reference["ref_id"])
    )
    assert published["unknowns"] == content["unknowns"]
    assert all(route["target_unit_cost"] is None for route in published["cost_summary"])
    assert (
        published["published_snapshot"]["professional_constraints"]
        == (published["professional_constraints"])
    )
    stored = fixture.state()["product_strategies"][0]
    assert stored["professional_constraints"] == published["professional_constraints"]
    assert stored["approval"] == published["approval"]


@pytest.mark.parametrize("missing", ["dqe", "sqe", "manufacturing", "review_handling"])
def test_pie_does_not_remove_required_profession_or_handling_before_submit(
    pie_candidate: PieCandidate, missing: str
) -> None:
    fixture = pie_candidate
    content = fixture.content()
    if missing == "review_handling":
        content["professional_constraints"][-1]["disposition"] = None
    else:
        removed = "pie" if missing == "manufacturing" else missing
        content["professional_constraints"] = [
            item for item in content["professional_constraints"] if item["discipline"] != removed
        ]
    row = fixture.create(content)
    expected = (
        "尚无评审任务或明确处置"
        if missing == "review_handling"
        else "PIE"
        if missing == "manufacturing"
        else missing.upper()
    )
    assert any(expected in blocker for blocker in row["publication_blockers"])
    before = fixture.state()
    rejected = fixture.act(row, "submit", status=409)
    assert expected in str(rejected)
    assert fixture.state() == before
    assert before["product_strategies"][0]["state"] == "draft"
    assert before["product_strategies"][0]["approval"] is None


def test_pie_review_cancelled_after_submit_blocks_publish_until_explicit_disposition(
    pie_candidate: PieCandidate,
) -> None:
    fixture = pie_candidate
    work = fixture.work("合成PIE制造可行性待验证")
    content = fixture.content()
    content["professional_constraints"][-1].update(work_item_id=work["id"], disposition=None)
    row = fixture.create(content)
    # An active, explicitly assigned future review is permitted by the existing
    # strategy contract. This is not a claim that its actual work is completed.
    row = fixture.act(row, "submit")
    assert work["state"] == "ready"
    cancelled = fixture.work_action(work, "cancel")
    before = fixture.state()
    rejected = fixture.act(row, "publish", status=409)
    assert "关联工作已取消" in str(rejected)
    assert fixture.state() == before
    assert before["product_strategies"][0]["approval"] is None

    returned = fixture.act(row, "return")
    content["professional_constraints"][-1]["disposition"] = {
        "outcome": "deferred",
        "reason": "原评审取消，具名保留未知并重新安排后续证据，不认定工艺已验证",
        "sources": [fixture.reference],
    }
    edited = fixture.post(
        f"/strategies/{row['id']}/changes",
        {**command(returned), "content": content, "reason": "明确处置取消的专业评审"},
    )
    submitted = fixture.act(edited, "submit")
    published = fixture.act(submitted, "publish")
    assert published["professional_constraints"][-1]["work_item_id"] == cancelled["id"]
    assert published["professional_constraints"][-1]["disposition"]["outcome"] == "deferred"
    assert published["unknowns"] == content["unknowns"]
    assert fixture.state()["scoped_work_items"][0]["state"] == "cancelled"


def test_named_pie_responsibilities_require_current_actors_and_human_publication(
    pie_candidate: PieCandidate,
) -> None:
    fixture = pie_candidate
    engineer, engineer_headers = fixture.member("engineer")
    manager, manager_headers = fixture.member("project_manager")
    original_manager_headers = deepcopy(manager_headers)
    responsibilities = (
        "产品导入：输入资料与配置版本核对",
        "工艺工程：装配/治具风险及适用工序",
        "工业工程：工时/节拍/产能与制造成本假设",
    )
    works = [fixture.work(title, engineer, manager) for title in responsibilities]
    assert len({work["id"] for work in works}) == 3
    content = fixture.content("PIE")
    template = content["professional_constraints"].pop()
    content["owner_user_id"] = engineer
    content["professional_constraints"] += [
        {
            **deepcopy(template),
            "id": str(uuid4()),
            "work_item_id": work["id"],
            "disposition": None,
            "statement": {**template["statement"], "text": work["expected_output"]},
        }
        for work in works
    ]
    strategy = fixture.create(content, engineer_headers)
    assert not strategy["can_publish"]
    strategy = fixture.act(strategy, "submit", engineer_headers)
    before = fixture.state()
    fixture.act(strategy, "publish", engineer_headers, 403)
    assert fixture.state() == before

    accepted_ids = []
    for work in works:
        before = fixture.state()
        fixture.work_action(work, "start", manager_headers, 403)
        assert fixture.state() == before
        started = fixture.work_action(work, "start", engineer_headers)
        before = fixture.state()
        fixture.work_action(started, "submit", engineer_headers, 409)
        assert fixture.state() == before
        submitted = fixture.work_action(
            started, "submit", engineer_headers, sources=[fixture.reference]
        )
        assert submitted["state"] == "submitted"
        before = fixture.state()
        fixture.work_action(submitted, "accept", engineer_headers, 403)
        assert fixture.state() == before
        accepted = fixture.work_action(submitted, "accept", manager_headers)
        assert accepted["state"] == "completed"
        assert accepted["owner_user_id"] == engineer and accepted["receiver_user_id"] == manager
        assert accepted["accepted_by_user_id"] == manager and accepted["accepted_at"]
        assert accepted["evidence"][0]["ref_id"] == fixture.reference["ref_id"]
        accepted_ids.append(accepted["id"])

    publish_body = {**command(strategy), "action": "publish", "reason": "合成具名发布"}
    path = f"/strategies/{strategy['id']}/actions"
    fixture.line_access(manager, "contributor")
    before = fixture.state()
    fixture.post(path, publish_body, 403, manager_headers)
    assert fixture.state() == before
    fixture.line_access(manager, "manager")
    changed = fixture.client.patch(
        f"/api/admin/users/{manager}", headers=fixture.headers, json={"role": "engineer"}
    )
    assert changed.status_code == 200, changed.text
    before = fixture.state()
    fixture.post(path, publish_body, 403, manager_headers)
    assert fixture.state() == before
    restored = fixture.client.patch(
        f"/api/admin/users/{manager}",
        headers=fixture.headers,
        json={"role": "project_manager"},
    )
    assert restored.status_code == 200, restored.text
    published = fixture.post(path, publish_body, headers=manager_headers)
    assert manager_headers == original_manager_headers
    assert published["approval"]["approved_by_user_id"] == manager
    assert {
        item["work_item_id"]
        for item in published["professional_constraints"]
        if item["discipline"] == "PIE"
    } == set(accepted_ids)
    assert published["unknowns"] == content["unknowns"]
    before = fixture.state()
    assert fixture.post(path, publish_body, headers=manager_headers) == published
    assert fixture.state() == before
    history = fixture.read(f"/strategies/{strategy['id']}/history", manager_headers)["items"]
    releases = [item for item in history if item["action"] == "product_strategy.publish"]
    assert len(releases) == 1 and releases[0]["actor_user_id"] == manager


@pytest.mark.parametrize("wrong_context", ["space", "line", "action_type"])
def test_pie_review_link_rejects_wrong_scope_or_action_without_partial_strategy(
    pie_candidate: PieCandidate, wrong_context: str
) -> None:
    fixture = pie_candidate
    other_base = fixture.base
    other_line = fixture.line_id
    if wrong_context != "action_type":
        if wrong_context == "space":
            other_base = f"/api/product-work/spaces/{space(fixture.client, fixture.headers)}"
        response = fixture.client.post(
            other_base + "/products",
            headers=fixture.headers,
            json={
                "request_id": str(uuid4()),
                "code": "PIE-OTHER-LINE",
                "name": "合成独立产品线",
                "level": "line",
                "owner_user_id": str(fixture.scope.owner_id),
            },
        )
        assert response.status_code == 201, response.text
        other_line = str(response.json()["id"])
    work = fixture.work(
        "合成不可误用的其他专业工作",
        base=other_base,
        line_id=other_line,
        action_type="evidence_collection"
        if wrong_context == "action_type"
        else "constraint_review",
    )
    content = fixture.content()
    content["professional_constraints"][-1].update(work_item_id=work["id"], disposition=None)
    before = fixture.state()
    rejected = fixture.create(content, status=409)
    assert "同一范围的专业或约束评审工作" in str(rejected)
    assert fixture.state() == before
    assert before["product_strategies"] == []
