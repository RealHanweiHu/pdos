"""Persisted historical plan preconditions for stage integration, with DB guards enabled."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection

from app.contracts.common_objects import (
    PlanCandidate,
    PlanNode,
    ScheduleNode,
    ScheduleSource,
    ScopeRef,
)
from app.db.schema import tables
from app.domain.product_workspace import digest
from app.domain.project_execution import ensure_conversion


def seed_formal_task(
    connection: Connection, tenant: UUID, project: UUID, owner: UUID, receiver: UUID
) -> tuple[UUID, UUID]:
    """A historical approved plan as the input boundary for ID delivery integration."""
    conversion = ensure_conversion(connection, tenant, project)
    now = datetime.now(UTC)
    ids = {
        key: uuid4()
        for key in (
            "candidate",
            "scenario",
            "capacity",
            "review",
            "policy",
            "execution",
            "baseline",
            "application",
            "calendar",
            "task",
            "node",
        )
    }

    def insert(table_name: str, **values: Any) -> None:
        table = getattr(tables, table_name)
        base: dict[str, Any] = {"tenant_id": tenant}
        if "created_by_user_id" in table.c:
            base.update(created_by_user_id=owner, request_id=uuid4(), request_digest="a" * 64)
        connection.execute(table.insert().values(**(base | values)))

    node = PlanNode(
        node_key="ME-DETAIL",
        title="结构详细设计",
        discipline="ME",
        owner_user_id=receiver,
        receiver_user_id=receiver,
        expected_output="冻结ID接口的结构详图",
        completion_criteria="尺寸与接口已核对",
        effort_hours=Decimal("8"),
        estimate_basis="工程师人工估算",
    )
    plan = PlanCandidate(
        id=ids["candidate"],
        tenant_id=tenant,
        scope=ScopeRef(kind="tenant", ref_id=tenant),
        version=1,
        owner_user_id=owner,
        template_version="id-integration.v1",
        nodes=(node,),
    ).model_dump(mode="json")
    calendar = {
        "calendar": {
            "id": str(ids["calendar"]),
            "tenant_id": str(tenant),
            "version": 1,
            "timezone": "UTC",
            "working_weekdays": list(range(7)),
            "hours_per_workday": "8",
        },
        "intervals": [{"start_minute": 540, "end_minute": 1020}],
    }
    insert(
        "work_calendar_versions",
        id=ids["calendar"],
        calendar_id=ids["calendar"],
        version=1,
        name="集成日历",
        definition=calendar,
        definition_digest=digest(calendar),
        reason="历史获批日历",
    )
    allocation = {
        "calendar_version_id": str(ids["calendar"]),
        "parallel_units": "1",
        "allocation_basis": "独立工程师",
        "not_before": None,
    }
    inputs = {"start": now.isoformat(), "default_allocation": allocation, "node_allocations": {}}
    candidate = {"plan": plan}
    insert(
        "initial_plan_candidates",
        id=ids["candidate"],
        series_id=ids["candidate"],
        version=1,
        case_id=conversion["case_id"],
        title="ID交接集成计划",
        template_selection={},
        template_snapshot={},
        source_snapshot={},
        source_digest="a" * 64,
        plan=plan,
        stage_assignments={"ME-DETAIL": "design"},
        id_plan={},
        revision_reason="历史计划",
    )
    insert(
        "initial_plan_scenarios",
        id=ids["scenario"],
        candidate_id=ids["candidate"],
        inputs=inputs,
        result={},
        candidate_digest=digest(plan),
        result_digest="a" * 64,
    )
    insert(
        "plan_capacity_checks",
        id=ids["capacity"],
        scenario_id=ids["scenario"],
        inputs={},
        result={},
        result_digest="a" * 64,
    )
    snapshot = {
        "candidate": candidate,
        "scenario": {"inputs": inputs},
        "capacity_inputs": {},
        "blockers": [],
    }
    plan_digest = digest(snapshot)
    approval = {
        "approval_id": str(uuid4()),
        "payload_digest": plan_digest,
        "policy_version": "integration.v1",
        "approved_by_user_id": str(receiver),
        "approved_at": now.isoformat(),
    }
    insert(
        "initial_plan_reviews",
        id=ids["review"],
        candidate_id=ids["candidate"],
        scenario_id=ids["scenario"],
        capacity_check_id=ids["capacity"],
        round_no=1,
        version=1,
        state="pending_review",
        reviewer_user_id=receiver,
        snapshot=snapshot,
        basis_digest=digest(snapshot),
        preparation_reason="集成前提",
    )
    connection.execute(
        tables.initial_plan_reviews.update()
        .where(tables.initial_plan_reviews.c.id == ids["review"])
        .values(version=2, state="accepted", outcome_reason="已批准", approval=approval)
    )
    insert(
        "project_execution_policies",
        id=ids["policy"],
        project_id=project,
        version=1,
        approver_user_id=receiver,
        four_eyes=True,
        authority_basis="具名执行批准",
    )
    insert(
        "project_execution_requests",
        id=ids["execution"],
        project_id=project,
        conversion_id=conversion["id"],
        plan_review_id=ids["review"],
        policy_id=ids["policy"],
        round_no=1,
        version=1,
        state="pending_approval",
        snapshot={"blockers": []},
        basis_digest="a" * 64,
        plan_digest=plan_digest,
        request_reason="历史执行",
    )
    connection.execute(
        tables.project_execution_requests.update()
        .where(tables.project_execution_requests.c.id == ids["execution"])
        .values(version=2, state="approved", outcome_reason="已批准", approval=approval)
    )
    node_time = {
        "node_id": str(ids["node"]),
        "window": {"start": now.isoformat(), "end": (now + timedelta(days=1)).isoformat()},
    }
    insert(
        "schedule_time_records",
        id=ids["baseline"],
        project_id=project,
        time_kind="baseline",
        version=1,
        execution_request_id=ids["execution"],
        contract={
            "id": str(ids["baseline"]),
            "tenant_id": str(tenant),
            "time_kind": "baseline",
            "version": 1,
            "scope": {"kind": "project", "ref_id": str(project)},
            "as_of": now.isoformat(),
            "approval": approval,
            "node_times": [node_time],
        },
    )
    receipt_id = uuid4()
    targets = [{"node_key": node.node_key, "target": {"ref_id": str(ids["task"])}}]
    insert(
        "initial_plan_applications",
        id=ids["application"],
        project_id=project,
        execution_request_id=ids["execution"],
        candidate_id=ids["candidate"],
        baseline_id=ids["baseline"],
        operation_receipt_id=receipt_id,
        contract={
            "id": str(ids["application"]),
            "project_id": str(project),
            "baseline_id": str(ids["baseline"]),
            "operation_receipt_id": str(receipt_id),
            "execution_approval": approval,
            "candidate_digest": plan_digest,
        },
        receipt={
            "id": str(receipt_id),
            "status": "applied",
            "candidate_digest": plan_digest,
            "targets": targets,
        },
        snapshot={"plan_snapshot": snapshot},
        reason="历史计划已应用",
    )
    insert("tasks", id=ids["task"], project_id=project, title=node.title, assignee_user_id=receiver)
    insert(
        "schedule_nodes",
        id=ids["node"],
        project_id=project,
        task_id=ids["task"],
        calendar_version_id=ids["calendar"],
        contract=ScheduleNode(
            id=ids["node"],
            tenant_id=tenant,
            project_id=project,
            node_kind="task",
            calendar_id=ids["calendar"],
            source=ScheduleSource(
                tenant_id=tenant, project_id=project, kind="task", ref_id=ids["task"], version=1
            ),
        ).model_dump(mode="json"),
    )
    insert(
        "task_plan_bindings",
        project_id=project,
        application_id=ids["application"],
        node_key=node.node_key,
        task_id=ids["task"],
        schedule_node_id=ids["node"],
        receiver_user_id=receiver,
        discipline=node.discipline,
        completion_criteria=node.completion_criteria,
        node_snapshot=node.model_dump(mode="json"),
    )
    insert(
        "schedule_time_nodes",
        project_id=project,
        record_id=ids["baseline"],
        node_id=ids["node"],
        start=now,
        end=now + timedelta(days=1),
    )
    return ids["task"], ids["node"]
