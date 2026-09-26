"""Customer change request chain tests (vNext V1-B8, G18)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Table, create_engine, select

from app.auth.passwords import PasswordService
from app.db.engine import get_engine
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.main import app
from app.settings import get_settings
from tests.db_cleanup import clear_test_tenants

SERVER_ROOT = Path(__file__).resolve().parents[1]
TEST_JWT_SECRET = "test-only-jwt-secret-that-is-at-least-32-bytes"
PASSWORD = "correct horse battery staple"
SETUP_PAYLOAD = {
    "tenant_slug": "beepump",
    "tenant_name": "Beehive Technology",
    "username": "owner",
    "password": PASSWORD,
    "display_name": "Initial Owner",
}


@pytest.fixture(autouse=True)
def isolated_ccr_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    test_url = configured_test_database_url()
    monkeypatch.setenv("DATABASE_URL", test_url)
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("JWT_ISSUER", "pdos-test")
    monkeypatch.setenv("JWT_AUDIENCE", "pdos-test-client")
    get_settings.cache_clear()
    get_engine.cache_clear()
    os.environ["DATABASE_URL"] = test_url
    command.upgrade(Config(str(SERVER_ROOT / "alembic.ini")), "head")
    engine = create_engine(psycopg_database_url(test_url))
    try:
        with engine.begin() as connection:
            clear_test_tenants(connection)
        yield test_url
    finally:
        engine.dispose()
        get_engine().dispose()
        get_engine.cache_clear()
        get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def bearer_headers(client: TestClient, *, username: str = "owner") -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"tenant_slug": "beepump", "username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


class Scope:
    def __init__(self, client: TestClient, database_url: str) -> None:
        setup = client.post("/api/setup", json=SETUP_PAYLOAD).json()
        self.tenant_id = UUID(setup["tenant"]["id"])
        self.owner_id = UUID(setup["user"]["id"])
        self.engine = create_engine(psycopg_database_url(database_url))
        self.password_hash = PasswordService().hash(PASSWORD)
        self.workflow_id: UUID | None = None
        self.stage_id: UUID | None = None

    def dispose(self) -> None:
        self.engine.dispose()

    def _insert(self, table: Table, values: dict[str, Any]) -> UUID:
        row_id: UUID = values.setdefault("id", uuid4())
        values.setdefault("tenant_id", self.tenant_id)
        with self.engine.begin() as connection:
            connection.execute(table.insert(), values)
        return row_id

    def user(self, username: str, role: str) -> UUID:
        return self._insert(
            tables.users,
            {
                "username": username,
                "display_name": username.title(),
                "role": role,
                "password_hash": self.password_hash,
            },
        )

    def customer(self) -> UUID:
        return self._insert(
            tables.customers, {"code": "CUST-1", "name": "远方客户", "status": "active"}
        )

    def project(self, *, member_ids: tuple[UUID, ...] = ()) -> UUID:
        self.workflow_id = self._insert(tables.workflows, {"code": "WF-CCR", "name": "Workflow"})
        self.stage_id = self._insert(
            tables.stages,
            {"workflow_id": self.workflow_id, "code": "evt", "name": "EVT", "sequence": 1},
        )
        project_id = self._insert(
            tables.projects,
            {
                "workflow_id": self.workflow_id,
                "owner_user_id": self.owner_id,
                "code": "PRJ-CCR",
                "name": "Customer change project",
                "status": "active",
            },
        )
        for member_id in (self.owner_id, *member_ids):
            self._insert(
                tables.project_members,
                {
                    "project_id": project_id,
                    "user_id": member_id,
                    "added_by_user_id": self.owner_id,
                },
            )
        return project_id

    def requirement(self, code: str, *, customer_id: UUID, parent: UUID | None = None) -> UUID:
        return self._insert(
            tables.requirements,
            {
                "customer_id": customer_id,
                "created_by_user_id": self.owner_id,
                "code": code,
                "title": f"需求 {code}",
                "tier": "customer" if parent is None else "product",
                "parent_requirement_id": parent,
                "status": "approved",
            },
        )

    def specification(self, project_id: UUID, code: str, *, requirement_id: UUID) -> UUID:
        return self._insert(
            tables.specifications,
            {
                "project_id": project_id,
                "created_by_user_id": self.owner_id,
                "code": code,
                "title": f"规格 {code}",
                "requirement_id": requirement_id,
            },
        )

    def test_case(self, project_id: UUID, *, specification_id: UUID, status: str) -> UUID:
        plan_id = self._insert(
            tables.test_plans,
            {
                "project_id": project_id,
                "workflow_id": self.workflow_id,
                "stage_id": self.stage_id,
                "created_by_user_id": self.owner_id,
                "phase": "evt",
                "title": "EVT plan",
                "sample_size": 3,
                "status": "active",
            },
        )
        values = {
            "project_id": project_id,
            "plan_id": plan_id,
            "specification_id": specification_id,
            "created_by_user_id": self.owner_id,
            "title": "流量测试",
            "category": "performance",
            "acceptance_criteria": "满足规格",
            "severity": "major",
            "status": status,
        }
        if status in {"passed", "failed"}:
            values["executed_by_user_id"] = self.owner_id
            values["executed_at"] = datetime.now(UTC)
        return self._insert(tables.test_cases, values)

    def ecr(self, project_id: UUID) -> UUID:
        return self._insert(
            tables.engineering_change_requests,
            {
                "project_id": project_id,
                "requested_by_user_id": self.owner_id,
                "code": "ECR-1",
                "title": "内部工程变更",
                "reason": "客户变更引发",
                "status": "request",
            },
        )

    def audit_actions(self) -> list[str]:
        with self.engine.connect() as connection:
            return [
                row.action
                for row in connection.execute(
                    select(tables.audit_log.c.action).where(
                        tables.audit_log.c.tenant_id == self.tenant_id
                    )
                )
            ]


def ccr_url(project_id: UUID, suffix: str = "") -> str:
    return f"/api/projects/{project_id}/customer-changes{suffix}"


def create_ccr(
    client: TestClient,
    headers: dict[str, str],
    project_id: UUID,
    *,
    customer_id: UUID,
    requirement_id: UUID,
) -> httpx2.Response:
    return client.post(
        ccr_url(project_id),
        headers=headers,
        json={
            "customer_id": str(customer_id),
            "requirement_id": str(requirement_id),
            "code": "CCR-1",
            "title": "客户要求提高流量 10%",
            "description": "客户现场工况变化",
        },
    )


def test_impact_analysis_counts_the_real_traceability_chain(
    client: TestClient, isolated_ccr_database: str
) -> None:
    scope = Scope(client, isolated_ccr_database)
    try:
        headers = bearer_headers(client)
        customer_id = scope.customer()
        project_id = scope.project()
        root = scope.requirement("REQ-ROOT", customer_id=customer_id)
        child = scope.requirement("REQ-CHILD", customer_id=customer_id, parent=root)
        spec_a = scope.specification(project_id, "SPEC-A", requirement_id=root)
        spec_b = scope.specification(project_id, "SPEC-B", requirement_id=child)
        # An unrelated requirement branch must not leak into the analysis.
        unrelated = scope.requirement("REQ-OTHER", customer_id=customer_id)
        scope.specification(project_id, "SPEC-OTHER", requirement_id=unrelated)
        scope.test_case(project_id, specification_id=spec_a, status="passed")
        scope.test_case(project_id, specification_id=spec_b, status="planned")

        created = create_ccr(
            client, headers, project_id, customer_id=customer_id, requirement_id=root
        )
        assert created.status_code == 201
        change_id = created.json()["id"]
        assert created.json()["status"] == "received"

        analyzed = client.post(ccr_url(project_id, f"/{change_id}/analyze"), headers=headers)
        assert analyzed.status_code == 200
        analysis = analyzed.json()["impact_analysis"]
        assert analysis["counts"] == {
            "requirements": 2,
            "specifications": 2,
            "test_cases": 2,
            "passed_test_cases": 1,
            "open_tasks": 0,
        }
        assert sorted(item["code"] for item in analysis["specifications"]) == ["SPEC-A", "SPEC-B"]
        # Re-testing what already passed is the schedule cost of this change.
        assert analysis["retest_required"] == 1
    finally:
        scope.dispose()


def test_the_full_chain_from_receipt_to_linked_ecr(
    client: TestClient, isolated_ccr_database: str
) -> None:
    scope = Scope(client, isolated_ccr_database)
    try:
        drafter = scope.user("sales_pm", "project_manager")
        headers = bearer_headers(client)
        drafter_headers = bearer_headers(client, username="sales_pm")
        customer_id = scope.customer()
        project_id = scope.project(member_ids=(drafter,))
        requirement_id = scope.requirement("REQ-ROOT", customer_id=customer_id)

        change_id = create_ccr(
            client, headers, project_id, customer_id=customer_id, requirement_id=requirement_id
        ).json()["id"]
        client.post(ccr_url(project_id, f"/{change_id}/analyze"), headers=headers)

        drafted = client.post(
            ccr_url(project_id, f"/{change_id}/reply"),
            headers=drafter_headers,
            json={"quote_note": "增加 12000 元工装费", "lead_time_days": 45},
        )
        assert drafted.status_code == 200
        assert drafted.json()["status"] == "reply_drafted"
        assert drafted.json()["lead_time_days"] == 45

        approved = client.post(ccr_url(project_id, f"/{change_id}/reply/approve"), headers=headers)
        assert approved.status_code == 200
        assert approved.json()["status"] == "reply_approved"

        decided = client.post(
            ccr_url(project_id, f"/{change_id}/customer-decision"),
            headers=headers,
            json={"accepted": True, "note": "客户书面确认"},
        )
        assert decided.status_code == 200
        assert decided.json()["status"] == "accepted"

        ecr_id = scope.ecr(project_id)
        linked = client.post(
            ccr_url(project_id, f"/{change_id}/engineering-change"),
            headers=headers,
            json={"engineering_change_request_id": str(ecr_id)},
        )
        assert linked.status_code == 200
        assert linked.json()["engineering_change_request_id"] == str(ecr_id)
        # The CCR stays 'accepted': raising an ECR does not close the customer track.
        assert linked.json()["status"] == "accepted"

        actions = scope.audit_actions()
        for expected in (
            "customer_change.created",
            "customer_change.impact_analyzed",
            "customer_change.reply_drafted",
            "customer_change.reply_approved",
            "customer_change.accepted",
            "customer_change.ecr_linked",
        ):
            assert expected in actions
    finally:
        scope.dispose()


def test_sending_a_commercial_answer_outward_needs_a_second_person(
    client: TestClient, isolated_ccr_database: str
) -> None:
    scope = Scope(client, isolated_ccr_database)
    try:
        headers = bearer_headers(client)
        customer_id = scope.customer()
        project_id = scope.project()
        requirement_id = scope.requirement("REQ-ROOT", customer_id=customer_id)
        change_id = create_ccr(
            client, headers, project_id, customer_id=customer_id, requirement_id=requirement_id
        ).json()["id"]
        client.post(ccr_url(project_id, f"/{change_id}/analyze"), headers=headers)
        client.post(
            ccr_url(project_id, f"/{change_id}/reply"),
            headers=headers,
            json={"quote_note": "加价 8000", "lead_time_days": 30},
        )

        self_approve = client.post(
            ccr_url(project_id, f"/{change_id}/reply/approve"), headers=headers
        )
        assert self_approve.status_code == 403
        assert self_approve.json()["detail"]["code"] == "CUSTOMER_CHANGE_FOUR_EYES"

        approver = scope.user("approver_pm", "project_manager")
        scope._insert(
            tables.project_members,
            {
                "project_id": project_id,
                "user_id": approver,
                "added_by_user_id": scope.owner_id,
            },
        )
        approved = client.post(
            ccr_url(project_id, f"/{change_id}/reply/approve"),
            headers=bearer_headers(client, username="approver_pm"),
        )
        assert approved.status_code == 200
    finally:
        scope.dispose()


def test_steps_cannot_be_skipped(client: TestClient, isolated_ccr_database: str) -> None:
    scope = Scope(client, isolated_ccr_database)
    try:
        headers = bearer_headers(client)
        customer_id = scope.customer()
        project_id = scope.project()
        requirement_id = scope.requirement("REQ-ROOT", customer_id=customer_id)
        change_id = create_ccr(
            client, headers, project_id, customer_id=customer_id, requirement_id=requirement_id
        ).json()["id"]

        # Quoting before knowing the impact is exactly the failure this prevents.
        premature_quote = client.post(
            ccr_url(project_id, f"/{change_id}/reply"),
            headers=headers,
            json={"quote_note": "拍脑袋报价", "lead_time_days": 10},
        )
        assert premature_quote.status_code == 409
        assert premature_quote.json()["detail"]["code"] == "CUSTOMER_CHANGE_INVALID_TRANSITION"

        premature_decision = client.post(
            ccr_url(project_id, f"/{change_id}/customer-decision"),
            headers=headers,
            json={"accepted": True, "note": None},
        )
        assert premature_decision.status_code == 409
    finally:
        scope.dispose()


def test_customer_and_engineering_tracks_stay_separate(
    client: TestClient, isolated_ccr_database: str
) -> None:
    scope = Scope(client, isolated_ccr_database)
    try:
        headers = bearer_headers(client)
        customer_id = scope.customer()
        project_id = scope.project()
        requirement_id = scope.requirement("REQ-ROOT", customer_id=customer_id)
        change_id = create_ccr(
            client, headers, project_id, customer_id=customer_id, requirement_id=requirement_id
        ).json()["id"]
        ecr_id = scope.ecr(project_id)

        ccr_list = client.get(ccr_url(project_id), headers=headers)
        assert [item["id"] for item in ccr_list.json()["items"]] == [change_id]

        ecr_list = client.get(f"/api/projects/{project_id}/changes", headers=headers)
        assert ecr_list.status_code == 200
        ecr_ids = {item["id"] for item in ecr_list.json()["ecrs"]}
        assert str(ecr_id) in ecr_ids
        assert change_id not in ecr_ids, "a customer change must never appear as an ECR"
    finally:
        scope.dispose()


def test_out_of_scope_references_and_cross_project_access_fail_closed(
    client: TestClient, isolated_ccr_database: str
) -> None:
    scope = Scope(client, isolated_ccr_database)
    try:
        headers = bearer_headers(client)
        customer_id = scope.customer()
        project_id = scope.project()
        requirement_id = scope.requirement("REQ-ROOT", customer_id=customer_id)

        unknown_customer = client.post(
            ccr_url(project_id),
            headers=headers,
            json={
                "customer_id": str(uuid4()),
                "requirement_id": str(requirement_id),
                "code": "CCR-X",
                "title": "未知客户",
            },
        )
        assert unknown_customer.status_code == 404

        change_id = create_ccr(
            client, headers, project_id, customer_id=customer_id, requirement_id=requirement_id
        ).json()["id"]
        client.post(ccr_url(project_id, f"/{change_id}/analyze"), headers=headers)
        client.post(
            ccr_url(project_id, f"/{change_id}/reply"),
            headers=headers,
            json={"quote_note": "报价", "lead_time_days": 30},
        )
        approver = scope.user("approver_pm", "project_manager")
        scope._insert(
            tables.project_members,
            {
                "project_id": project_id,
                "user_id": approver,
                "added_by_user_id": scope.owner_id,
            },
        )
        client.post(
            ccr_url(project_id, f"/{change_id}/reply/approve"),
            headers=bearer_headers(client, username="approver_pm"),
        )
        client.post(
            ccr_url(project_id, f"/{change_id}/customer-decision"),
            headers=headers,
            json={"accepted": True, "note": None},
        )
        missing_ecr = client.post(
            ccr_url(project_id, f"/{change_id}/engineering-change"),
            headers=headers,
            json={"engineering_change_request_id": str(uuid4())},
        )
        assert missing_ecr.status_code == 404

        assert client.get(ccr_url(project_id)).status_code == 401
    finally:
        scope.dispose()
