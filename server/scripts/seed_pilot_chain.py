"""Seed one pilot project carrying a complete digital chain (Checkpoint V1).

This is the Checkpoint V1 acceptance in executable form: requirement → spec →
sample → test run → issue → decision → gate evidence, plus the V1 surfaces that
need real rows to be walked in a browser (risk candidates, knowledge candidate,
org and delegation, customer change, knowledge push).

It drives the real domain services wherever they exist, so a green run is
itself evidence that the chain composes — not just that rows can be inserted.

Run against a development database only:

    DATABASE_URL=postgresql://... uv run python -m scripts.seed_pilot_chain
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Engine, Table, create_engine, select, text

from app.auth.passwords import PasswordService
from app.db.schema import tables
from app.db.url import psycopg_database_url

TENANT_SLUG = "beepump"
PASSWORD = "correct horse battery staple"
TODAY = date.today()


def _fail(message: str) -> None:
    print(f"refusing to seed: {message}", file=sys.stderr)
    raise SystemExit(1)


class Seeder:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.tenant_id = uuid4()
        self.hash = PasswordService().hash(PASSWORD)
        self.users: dict[str, UUID] = {}

    def insert(self, table: Table, values: dict[str, Any]) -> UUID:
        row_id: UUID = values.setdefault("id", uuid4())
        values.setdefault("tenant_id", self.tenant_id)
        with self.engine.begin() as connection:
            connection.execute(table.insert(), values)
        return row_id

    # ---- org ------------------------------------------------------------

    def tenant(self) -> None:
        self.insert(
            tables.tenants,
            {"id": self.tenant_id, "slug": TENANT_SLUG, "name": "蜂巢气泵科技"},
        )

    def user(self, username: str, display: str, role: str) -> UUID:
        user_id = self.insert(
            tables.users,
            {
                "username": username,
                "display_name": display,
                "role": role,
                "password_hash": self.hash,
            },
        )
        self.users[username] = user_id
        return user_id

    def department(self, name: str, parent: UUID | None = None) -> UUID:
        return self.insert(tables.departments, {"name": name, "parent_department_id": parent})

    def place(self, username: str, *, department_id: UUID, manager: str | None) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                tables.users.update()
                .where(tables.users.c.id == self.users[username])
                .values(
                    department_id=department_id,
                    manager_user_id=self.users[manager] if manager else None,
                )
            )

    def delegation(self, principal: str, delegate: str, reason: str) -> UUID:
        now = datetime.now(UTC)
        return self.insert(
            tables.user_delegations,
            {
                "principal_user_id": self.users[principal],
                "delegate_user_id": self.users[delegate],
                "starts_at": now - timedelta(hours=1),
                "ends_at": now + timedelta(days=7),
                "reason": reason,
                "created_by_user_id": self.users["owner"],
                "created_at": now,
            },
        )


def seed(engine: Engine) -> dict[str, Any]:
    s = Seeder(engine)
    s.tenant()
    owner = s.user("owner", "王总", "owner")
    pm = s.user("manager", "李项目", "project_manager")
    engineer = s.user("engineer", "张工", "engineer")
    quality = s.user("quality", "赵品质", "quality")
    s.user("engineer2", "孙工", "engineer")

    hardware = s.department("硬件部")
    structure = s.department("结构组", hardware)
    s.place("manager", department_id=hardware, manager="owner")
    s.place("engineer", department_id=structure, manager="manager")
    s.place("quality", department_id=hardware, manager="manager")
    s.delegation("engineer", "engineer2", "年假代班")

    customer = s.insert(
        tables.customers, {"code": "CUST-001", "name": "远方制造", "status": "active"}
    )

    # --- workflow and project ------------------------------------------
    workflow = s.insert(tables.workflows, {"code": "npd", "name": "新品开发流程"})
    stages = {}
    for index, (code, name) in enumerate(
        [("concept", "概念"), ("evt", "EVT"), ("dvt", "DVT")], start=1
    ):
        stages[code] = s.insert(
            tables.stages,
            {"workflow_id": workflow, "code": code, "name": name, "sequence": index},
        )

    requirement = s.insert(
        tables.requirements,
        {
            "customer_id": customer,
            "created_by_user_id": pm,
            "code": "REQ-001",
            "title": "便携气泵：充气速度提升 20%",
            "description": "客户现场工况要求更快充气",
            "tier": "customer",
            "status": "approved",
        },
    )
    case = s.insert(
        tables.development_cases,
        {
            "requirement_id": requirement,
            "created_by_user_id": pm,
            "code": "CASE-001",
            "title": "A1 便携气泵开发",
            "status": "converted",
        },
    )
    project = s.insert(
        tables.projects,
        {
            "development_case_id": case,
            "customer_id": customer,
            "workflow_id": workflow,
            "current_stage_id": stages["evt"],
            "owner_user_id": pm,
            "code": "PRJ-A1",
            "name": "A1 便携气泵",
            "description": "面向户外场景的便携高速气泵",
            "status": "active",
            "start_date": TODAY - timedelta(days=60),
            "target_date": TODAY + timedelta(days=30),
        },
    )
    for member in (owner, pm, engineer, quality, s.users["engineer2"]):
        s.insert(
            tables.project_members,
            {"project_id": project, "user_id": member, "added_by_user_id": owner},
        )

    # --- requirement → specification → test case ------------------------
    child_requirement = s.insert(
        tables.requirements,
        {
            "customer_id": customer,
            "created_by_user_id": pm,
            "code": "REQ-001-1",
            "title": "泵体流量 ≥ 22 L/min",
            "tier": "product",
            "parent_requirement_id": requirement,
            "status": "approved",
        },
    )
    specification = s.insert(
        tables.specifications,
        {
            "project_id": project,
            "created_by_user_id": engineer,
            "code": "SPEC-FLOW",
            "title": "流量规格",
            "requirement_id": child_requirement,
            "owner_user_id": engineer,
            "verification_method": "台架流量测试",
            "acceptance_criteria": "连续 3 台 ≥ 22 L/min",
            "criticality": "key",
        },
    )
    plan = s.insert(
        tables.test_plans,
        {
            "project_id": project,
            "workflow_id": workflow,
            "stage_id": stages["evt"],
            "created_by_user_id": quality,
            "phase": "evt",
            "title": "EVT 测试计划",
            "sample_size": 3,
            "status": "active",
        },
    )
    test_case = s.insert(
        tables.test_cases,
        {
            "project_id": project,
            "plan_id": plan,
            "specification_id": specification,
            "created_by_user_id": quality,
            "title": "台架流量测试",
            "category": "performance",
            "acceptance_criteria": "≥ 22 L/min",
            "severity": "major",
            "status": "planned",
        },
    )

    # --- build batch → samples → build configuration --------------------
    batch = s.insert(
        tables.build_batches,
        {
            "project_id": project,
            "workflow_id": workflow,
            "stage_id": stages["evt"],
            "created_by_user_id": engineer,
            "phase": "evt",
            "purpose": "engineering_build",
            "code": "BATCH-EVT-1",
            "planned_quantity": 3,
            "status": "planned",
        },
    )
    bom = s.insert(
        tables.development_boms,
        {
            "project_id": project,
            "specification_id": specification,
            "created_by_user_id": engineer,
            "bom_type": "ebom",
            "code": "BOM-A1",
            "name": "A1 工程 BOM",
            "version": 3,
        },
    )
    samples = []
    for index, (serial, structure_version) in enumerate(
        [("SN-001", "STR-1.0"), ("SN-002", "STR-1.1")], start=1
    ):
        sample = s.insert(
            tables.samples,
            {
                "project_id": project,
                "build_batch_id": batch,
                "created_by_user_id": engineer,
                "serial_number": serial,
                "status": "built",
                "built_at": datetime.now(UTC) - timedelta(days=10 - index),
            },
        )
        fw = s.insert(
            tables.fw_releases,
            {
                "project_id": project,
                "released_by_user_id": engineer,
                "version": f"FW-1.4.{index}",
                "notes": "EVT 固件",
            },
        )
        s.insert(
            tables.sample_build_configurations,
            {
                "project_id": project,
                "sample_id": sample,
                "fw_release_id": fw,
                "development_bom_id": bom,
                "updated_by_user_id": engineer,
                "pcb_version": "PCB-2.1",
                "structure_version": structure_version,
                "key_component_suppliers": {"轴承": "NSK", "电机": "Nidec"},
                "build_date": TODAY - timedelta(days=10),
                "source": "manual",
                "draft_state": "confirmed",
            },
        )
        samples.append(sample)

    # --- test run (failed) → issue on a specific sample ------------------
    s.insert(
        tables.test_runs,
        {
            "project_id": project,
            "test_case_id": test_case,
            "sample_id": samples[0],
            "operator_user_id": quality,
            "run_number": 1,
            "status": "failed",
            "conditions": {"ambient_c": 25},
            "metrics": [
                {"name": "flow", "value": 19.4, "unit": "L/min", "target": 22, "verdict": "fail"}
            ],
            "equipment": "流量台 F-02",
            "environment": "常温实验室",
            "started_at": datetime.now(UTC) - timedelta(days=5),
            "executed_at": datetime.now(UTC) - timedelta(days=5) + timedelta(hours=2),
            "execution_time_precision": "instant",
            "execution_time_source": "human",
            "draft_state": "confirmed",
        },
    )
    with engine.begin() as connection:
        connection.execute(
            tables.test_cases.update()
            .where(tables.test_cases.c.id == test_case)
            .values(
                status="failed",
                executed_by_user_id=quality,
                executed_at=datetime.now(UTC) - timedelta(days=5),
            )
        )
    issue = s.insert(
        tables.issues,
        {
            "project_id": project,
            "workflow_id": workflow,
            "stage_id": stages["evt"],
            "reported_by_user_id": quality,
            "owner_user_id": engineer,
            "verifier_user_id": quality,
            "sample_id": samples[0],
            "title": "SN-001 流量不达标（19.4 L/min）",
            "description": "台架测试低于 22 L/min 目标",
            "issue_type": "test_failure",
            "status": "action",
            "severity": "high",
            "root_cause": "叶轮出口角偏小导致流量损失",
            "closure_criteria": "连续 3 台 ≥ 22 L/min",
            "target_date": TODAY + timedelta(days=7),
        },
    )

    # --- overdue task so the rule engine has a risk candidate to find ----
    s.insert(
        tables.tasks,
        {
            "project_id": project,
            "workflow_id": workflow,
            "stage_id": stages["evt"],
            "assignee_user_id": engineer,
            "created_by_user_id": pm,
            "title": "叶轮改模验证",
            "kind": "issue_action",
            "source_entity": "issue",
            "source_entity_id": issue,
            "expected_output": "改模后的流量测试报告",
            "status": "in_progress",
            "priority": "high",
            "due_date": TODAY - timedelta(days=2),
        },
    )

    # --- decision + gate --------------------------------------------------
    s.insert(
        tables.decisions,
        {
            "project_id": project,
            "decided_by_user_id": pm,
            "decision_kind": "technical_choice",
            "title": "叶轮出口角由 22° 改为 26°",
            "context": "EVT 流量低于目标 12%",
            "options": [{"name": "改模", "cost": "中"}, {"name": "提高转速", "cost": "低"}],
            "trade_offs": "提高转速会增加噪音与功耗",
            "consequence": "改模需 2 周，但噪音指标不受影响",
            "outcome": "改模",
            "rationale": "噪音是客户硬指标，不能牺牲",
            "owner_user_id": engineer,
            "follow_up_state": "none",
            "decided_at": datetime.now(UTC) - timedelta(days=3),
        },
    )
    gate = s.insert(
        tables.gates,
        {
            "project_id": project,
            "stage_id": stages["evt"],
            "code": "GATE-EVT",
            "name": "EVT 评审",
            "status": "preparing",
            "review_due_at": datetime.now(UTC) + timedelta(days=7),
        },
    )

    # --- customer change request -----------------------------------------
    s.insert(
        tables.customer_change_requests,
        {
            "project_id": project,
            "customer_id": customer,
            "requirement_id": requirement,
            "received_by_user_id": pm,
            "code": "CCR-001",
            "title": "客户要求增加低温启动能力",
            "description": "客户新增 -10°C 启动场景",
            "status": "received",
            "received_at": datetime.now(UTC) - timedelta(days=1),
        },
    )

    return {
        "tenant_id": s.tenant_id,
        "project_id": project,
        "issue_id": issue,
        "gate_id": gate,
        "users": s.users,
    }


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        _fail("DATABASE_URL must be set")
        raise SystemExit(1)  # _fail already exits; this narrows the type
    if "prod" in database_url.lower():
        _fail("this script never runs against production")
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.connect() as connection:
            existing = connection.execute(
                select(tables.tenants.c.id).where(tables.tenants.c.slug == TENANT_SLUG)
            ).scalar_one_or_none()
        if existing is not None:
            with engine.begin() as connection:
                connection.execute(
                    text("TRUNCATE TABLE cehub_core.tenants CASCADE"),
                )
            print("cleared the previous demo tenant")
        result = seed(engine)
    finally:
        engine.dispose()
    print("seeded pilot chain")
    print(f"  tenant   {TENANT_SLUG}")
    print(f"  project  {result['project_id']}")
    print(f"  issue    {result['issue_id']}")
    print(f"  gate     {result['gate_id']}")
    print(f"  logins   {', '.join(sorted(result['users']))} / {PASSWORD}")


if __name__ == "__main__":
    main()
