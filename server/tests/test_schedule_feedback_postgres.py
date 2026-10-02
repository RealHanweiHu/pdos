"""Real feedback transactions. Coordinator alone runs this in a verified pdos_test.

The immutable, named baseline boundary is synthetic SQL fixture data (approval
workflow itself is outside this test). Forecast, Task, correction and reservation
actions are real services with constraints enabled. Only deliberate audit failure
is injected. No connection is created at module import or by syntax checks.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text

from app.contracts.common_objects import (
    ApprovalRef,
    NodeTime,
    PlanCandidate,
    PlanNode,
    ScopeRef,
    SourceRef,
    TimeRecord,
    TimeWindow,
)
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError, digest
from app.domain.resource_reallocation_inputs import ReallocationDraft, ReallocationSubmit
from app.domain.resource_reallocations import ResourceReallocationService
from app.domain.resource_reservations import ReservationAction, ResourceReservationService
from app.domain.schedule_actual_corrections import ActualCorrection, ActualCorrectionService
from app.domain.schedule_forecasts import ForecastDraft, RemainingEstimate, ScheduleForecastService
from app.domain.schedule_nodes import NodeDraft, ScheduleNodeService
from app.domain.schedule_source_corrections import (
    SourceActualCorrection,
    SourceActualCorrectionService,
)
from app.domain.tasks import TaskDraft, TaskService
from app.domain.test_runs import TestRunDraft as RunDraft
from app.domain.test_runs import TestRunService as RunService
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft, WrittenEventAudit
from tests.stage_plan_fixtures import seed_formal_task
from tests.test_resource_reallocations_postgres import ProjectSource, Scope
from tests.test_resource_reallocations_postgres import scope as scope

EXTRA_TABLES = (
    tables.schedule_source_forecast_errors,
    tables.schedule_source_corrections,
    tables.schedule_source_observations,
    tables.schedule_forecast_error_corrections,
    tables.schedule_actual_corrections,
    tables.schedule_forecast_errors,
    tables.schedule_forecast_runs,
    tables.scheduled_task_observations,
    tables.schedule_time_nodes,
    tables.baseline_change_applications,
    tables.baseline_change_decisions,
    tables.baseline_change_requests,
    tables.baseline_change_policies,
    tables.project_schedule_scenario_nodes,
    tables.project_scenario_capacity_checks,
    tables.project_schedule_scenarios,
    tables.schedule_time_records,
    tables.task_plan_bindings,
    tables.initial_plan_applications,
    tables.project_execution_requests,
    tables.project_execution_policies,
    tables.initial_plan_reviews,
    tables.plan_capacity_checks,
    tables.initial_plan_scenarios,
    tables.initial_plan_candidates,
    tables.case_project_conversions,
    tables.development_cases,
    tables.requirements,
    tables.test_runs,
    tables.test_cases,
    tables.test_plans,
    tables.stages,
)


def seed_formal(
    scope: Scope,
    source: ProjectSource,
    extra: tuple[UUID, UUID] | None,
    typed_nodes: dict[str, UUID] | None = None,
) -> None:
    """Minimum complete named baseline lineage; no mock or disabled SQL guard."""
    identities = {
        "A": source.node_id,
        **({"B": extra[1]} if extra else {}),
        **(typed_nodes or {}),
    }
    now = datetime.now(UTC) - timedelta(days=1)
    current, scenario, check, policy, change, decision, application = (uuid4() for _ in range(7))
    plan = PlanCandidate(
        id=scenario,
        tenant_id=scope.tenant.id,
        scope=ScopeRef(kind="project", ref_id=source.project_id),
        version=1,
        owner_user_id=source.owner.user.id,
        template_version="pg.feedback.fixture.v1",
        nodes=tuple(
            PlanNode(
                node_key=key,
                title=f"Actual feedback {key}",
                discipline="ME",
                owner_user_id=source.owner.user.id,
                receiver_user_id=scope.admin.user.id,
                expected_output="execution evidence",
                completion_criteria="accepted evidence",
                effort_hours=Decimal(1),
                waiting_days=0,
                estimate_basis="named fixture estimate",
            )
            for key in identities
        ),
        dependencies=(),
    )
    allocations = {
        key: {
            "calendar_key": str(scope.calendar_id),
            "parallel_units": "1",
            "allocation_basis": "named baseline fixture",
            "not_before": now.isoformat(),
        }
        for key in identities
    }
    capacity: dict[str, Any] = {
        "request_id": str(uuid4()),
        "demands": {},
        "no_resource_reasons": {
            key: "Reservations are independent current inputs" for key in identities
        },
    }
    scenario_result: dict[str, Any] = {
        "complete": True,
        "capacity_status": "not_checked",
        "applied": False,
        "nodes": [
            {
                "node_key": key,
                "node_id": str(identities[key]),
                "start": now.isoformat(),
                "finish": (now + timedelta(hours=1)).isoformat(),
                "allocation": value,
            }
            for key, value in allocations.items()
        ],
    }
    capacity_result = {
        "status": "capacity_clear",
        "project_scenario_id": str(scenario),
        "baseline_changed": False,
        "profiles": [],
    }
    snapshot = {
        "plan": plan.model_dump(mode="json"),
        "capacity_inputs": capacity,
        "result": scenario_result,
        "policy": {"id": str(policy)},
        "capacity": capacity_result,
        "blockers": [],
    }
    payload = digest(snapshot)
    approval = ApprovalRef(
        approval_id=decision,
        payload_digest=payload,
        policy_version=f"baseline-policy:{policy}:1",
        approved_by_user_id=scope.admin.user.id,
        approved_at=now,
    )
    with scope.engine.begin() as c:
        assert c.execute(text("SHOW session_replication_role")).scalar_one() == "origin"
        # Reuse the existing historical initial-plan fixture, supplying its
        # actual scoped conversion evidence. These are synthetic preconditions,
        # never an assertion that the approval workflow was exercised here.
        requirement, case = uuid4(), uuid4()
        c.execute(
            tables.requirements.insert().values(
                id=requirement,
                tenant_id=scope.tenant.id,
                created_by_user_id=scope.admin.user.id,
                code=f"FEEDBACK-{requirement.hex[:8]}",
                title="Historical isolated requirement",
                status="approved",
            )
        )
        c.execute(
            tables.development_cases.insert().values(
                id=case,
                tenant_id=scope.tenant.id,
                requirement_id=requirement,
                created_by_user_id=scope.admin.user.id,
                code=f"FEEDBACK-{case.hex[:8]}",
                title="Historical isolated conversion",
                status="converted",
            )
        )
        c.execute(
            tables.projects.update()
            .where(
                tables.projects.c.tenant_id == scope.tenant.id,
                tables.projects.c.id == source.project_id,
            )
            .values(development_case_id=case)
        )
        EventAuditWriter(
            c,
            tenant_id=scope.tenant.id,
            project_id=source.project_id,
            actor_user_id=scope.admin.user.id,
        ).record(
            EventDraft(
                event_id=f"feedback-fixture:{case}:converted",
                event_type="DEVELOPMENT_CASE_STATUS_CHANGED",
                source="development_case_service",
                entity_id=case,
                payload={"from_status": "approved", "to_status": "converted"},
                occurred_at=now,
            ),
            AuditDraft(
                action="development_case.transition",
                before_snapshot={"status": "approved"},
                after_snapshot={"status": "converted"},
            ),
        )
        _, inherited_node_id = seed_formal_task(
            c, scope.tenant.id, source.project_id, scope.admin.user.id, source.owner.user.id
        )
        root = c.execute(
            select(tables.schedule_time_records.c.id).where(
                tables.schedule_time_records.c.tenant_id == scope.tenant.id,
                tables.schedule_time_records.c.project_id == source.project_id,
                tables.schedule_time_records.c.time_kind == "baseline",
            )
        ).scalar_one()
        # A named revision must carry every existing formal node forward. Keep
        # the historical task independent from A/B/T, preserving its approved
        # node definition, calendar, allocation and original time window.
        inherited = (
            c.execute(
                select(
                    tables.task_plan_bindings.c.node_snapshot,
                    tables.initial_plan_applications.c.snapshot,
                )
                .join(
                    tables.initial_plan_applications,
                    (
                        tables.initial_plan_applications.c.tenant_id
                        == tables.task_plan_bindings.c.tenant_id
                    )
                    & (
                        tables.initial_plan_applications.c.id
                        == tables.task_plan_bindings.c.application_id
                    ),
                )
                .where(
                    tables.task_plan_bindings.c.tenant_id == scope.tenant.id,
                    tables.task_plan_bindings.c.project_id == source.project_id,
                    tables.task_plan_bindings.c.schedule_node_id == inherited_node_id,
                    tables.initial_plan_applications.c.baseline_id == root,
                )
            )
            .mappings()
            .one()
        )
        inherited_plan_node = PlanNode.model_validate(inherited["node_snapshot"])
        inherited_key = inherited_plan_node.node_key
        assert inherited_key not in identities
        identities[inherited_key] = inherited_node_id
        plan = plan.model_copy(update={"nodes": (*plan.nodes, inherited_plan_node)})
        inherited_inputs = inherited["snapshot"]["plan_snapshot"]["scenario"]["inputs"]
        original_allocation = inherited_inputs["node_allocations"].get(
            inherited_key, inherited_inputs["default_allocation"]
        )
        allocations[inherited_key] = {
            "calendar_key": original_allocation["calendar_version_id"],
            "parallel_units": original_allocation["parallel_units"],
            "allocation_basis": original_allocation["allocation_basis"],
            "not_before": original_allocation.get("not_before") or inherited_inputs["start"],
        }
        inherited_window = (
            c.execute(
                select(tables.schedule_time_nodes.c.start, tables.schedule_time_nodes.c.end).where(
                    tables.schedule_time_nodes.c.tenant_id == scope.tenant.id,
                    tables.schedule_time_nodes.c.project_id == source.project_id,
                    tables.schedule_time_nodes.c.record_id == root,
                    tables.schedule_time_nodes.c.node_id == inherited_node_id,
                )
            )
            .mappings()
            .one()
        )
        scenario_result["nodes"].append(
            {
                "node_key": inherited_key,
                "node_id": str(inherited_node_id),
                "start": inherited_window["start"].isoformat(),
                "finish": inherited_window["end"].isoformat(),
                "allocation": allocations[inherited_key],
            }
        )
        capacity["no_resource_reasons"][inherited_key] = "Independent historical engineering task"
        snapshot["plan"] = plan.model_dump(mode="json")
        snapshot["baseline"] = {"id": str(root)}
        payload = digest(snapshot)
        approval = approval.model_copy(update={"payload_digest": payload})
        common = {
            "tenant_id": scope.tenant.id,
            "project_id": source.project_id,
            "request_id": uuid4(),
            "request_digest": payload,
        }
        c.execute(
            tables.project_schedule_scenarios.insert().values(
                **common,
                id=scenario,
                baseline_id=root,
                title="Named approved fixture",
                reason="Seed boundary",
                inputs={},
                snapshot=snapshot,
                basis_digest=payload,
                plan=snapshot["plan"],
                result=snapshot["result"],
                result_digest=payload,
                actor_user_id=source.owner.user.id,
            )
        )
        for key, node_id in identities.items():
            c.execute(
                tables.project_schedule_scenario_nodes.insert().values(
                    tenant_id=scope.tenant.id,
                    project_id=source.project_id,
                    scenario_id=scenario,
                    node_id=node_id,
                    node_key=key,
                )
            )
        c.execute(
            tables.project_scenario_capacity_checks.insert().values(
                **{**common, "request_id": uuid4()},
                id=check,
                scenario_id=scenario,
                inputs=capacity,
                result=capacity_result,
                result_digest=payload,
                scenario_basis_digest=payload,
                created_by_user_id=scope.admin.user.id,
            )
        )
        c.execute(
            tables.baseline_change_policies.insert().values(
                **{**common, "request_id": uuid4()},
                id=policy,
                version=1,
                approver_user_id=scope.admin.user.id,
                authority_basis="Isolated named fixture boundary",
                four_eyes=True,
                created_by_user_id=scope.admin.user.id,
            )
        )
        c.execute(
            tables.baseline_change_requests.insert().values(
                **{**common, "request_id": uuid4()},
                id=change,
                scenario_id=scenario,
                capacity_check_id=check,
                policy_id=policy,
                base_baseline_id=root,
                reason="Named approved fixture",
                snapshot=snapshot,
                payload_digest=payload,
                created_by_user_id=source.owner.user.id,
            )
        )
        c.execute(
            tables.baseline_change_decisions.insert().values(
                **{**common, "request_id": uuid4()},
                id=decision,
                change_id=change,
                action="approve",
                reason="Named fixture approval",
                actor_user_id=scope.admin.user.id,
                approved_payload_digest=payload,
                created_at=now,
            )
        )
        record = TimeRecord(
            id=current,
            tenant_id=scope.tenant.id,
            scope=plan.scope,
            version=2,
            owner_user_id=source.owner.user.id,
            time_kind="baseline",
            fact_kind="derived",
            approval=approval,
            algorithm_version="pg.fixture.v1",
            as_of=now,
            sources=(
                SourceRef(
                    tenant_id=scope.tenant.id,
                    project_id=source.project_id,
                    kind="project_schedule_scenario",
                    ref_id=scenario,
                    version=1,
                ),
            ),
            node_times=tuple(
                NodeTime(
                    node_id=node_id,
                    window=TimeWindow(
                        start=inherited_window["start"] if node_id == inherited_node_id else now,
                        end=inherited_window["end"]
                        if node_id == inherited_node_id
                        else now + timedelta(hours=1),
                    ),
                )
                for node_id in identities.values()
            ),
        )
        c.execute(
            tables.schedule_time_records.insert().values(
                id=current,
                tenant_id=scope.tenant.id,
                project_id=source.project_id,
                time_kind="baseline",
                version=2,
                contract=record.model_dump(mode="json"),
            )
        )
        for point in record.node_times:
            c.execute(
                tables.schedule_time_nodes.insert().values(
                    tenant_id=scope.tenant.id,
                    project_id=source.project_id,
                    record_id=current,
                    node_id=point.node_id,
                    start=point.window.start,
                    end=point.window.end,
                )
            )
        c.execute(
            tables.baseline_change_applications.insert().values(
                **{**common, "request_id": uuid4()},
                id=application,
                change_id=change,
                decision_id=decision,
                baseline_id=current,
                previous_baseline_id=root,
                scenario_id=scenario,
                actor_user_id=source.owner.user.id,
                receipt={
                    "id": str(application),
                    "status": "applied",
                    "baseline_id": str(current),
                    "baseline_version": 2,
                    "previous_baseline_id": str(root),
                    "change_id": str(change),
                    "decision_id": str(decision),
                    "actor_user_id": str(source.owner.user.id),
                    "payload_digest": payload,
                    "node_ids": [str(identity) for identity in identities.values()],
                },
            )
        )


@dataclass
class Feedback:
    scope: Scope
    extra_task: UUID

    def snapshot(self) -> dict[str, Any]:
        return {
            **self.scope.snapshot(),
            **{table.fullname: self.scope.rows(table) for table in EXTRA_TABLES},
        }

    def history(self, source: ProjectSource | None = None) -> dict[str, Any]:
        target = source or self.scope.sources[0]
        return ScheduleForecastService(self.scope.engine).get(target.owner, target.project_id)

    def recalculate(
        self,
        estimates: dict[str, RemainingEstimate] | None = None,
        source: ProjectSource | None = None,
    ) -> dict[str, Any]:
        target = source or self.scope.sources[0]
        return ScheduleForecastService(self.scope.engine).recalculate(
            target.owner,
            target.project_id,
            ForecastDraft(
                request_id=uuid4(),
                expected_basis_digest=self.history(target)["basis_digest"],
                estimates=estimates or {},
                reason="Real deterministic feedback calculation",
            ),
        )

    def baseline(self) -> list[dict[str, Any]]:
        return [
            row
            for row in self.scope.rows(tables.schedule_time_records)
            if row["time_kind"] in ("baseline", "commitment")
        ]


@pytest.fixture
def feedback(scope: Scope) -> Iterator[Feedback]:
    # Imported scope first validates explicit URL, pdos_test, protected ports and
    # the coordinator's isolation marker before making any connection.
    try:
        source = scope.sources[0]
        task = TaskService(scope.engine).create(
            tenant_id=scope.tenant.id,
            actor_user_id=source.owner.user.id,
            project_id=source.project_id,
            draft=TaskDraft(
                stage_id=None,
                parent_task_id=None,
                assignee_user_id=source.owner.user.id,
                title="Independent remaining-work source B",
                description=None,
                priority="medium",
                start_date=None,
                due_date=None,
                dependency_task_ids=(),
            ),
        )
        row = next(row for row in scope.rows(tables.tasks) if row["id"] == str(task.id))
        node = ScheduleNodeService(scope.engine).register(
            source.owner,
            source.project_id,
            NodeDraft(
                request_id=uuid4(),
                node_kind="task",
                source_id=task.id,
                expected_source_digest=digest(row),
                calendar_version_id=scope.calendar_id,
            ),
        )
        seed_formal(scope, source, (task.id, UUID(node["id"])))
        seed_formal(scope, scope.sources[1], None)
        yield Feedback(scope, task.id)
    finally:
        with scope.engine.begin() as c:
            assert c.execute(text("SHOW session_replication_role")).scalar_one() == "origin"
            c.execute(text("SET LOCAL session_replication_role=replica"))
            for table in EXTRA_TABLES:
                c.execute(table.delete().where(table.c.tenant_id == scope.tenant.id))


def correction_command(feedback: Feedback) -> ActualCorrection:
    source = feedback.scope.sources[0]
    point = ActualCorrectionService(feedback.scope.engine).get(source.owner, source.project_id)[
        "points"
    ][0]
    return ActualCorrection(
        request_id=uuid4(),
        task_id=source.task_id,
        point="start",
        expected_digest=point["digest"],
        observed_at=datetime.fromisoformat(point["observed_at"]) - timedelta(minutes=5),
        reason="Real actual correction",
        evidence="Synthetic on-site fixture evidence",
    )


def start_task(feedback: Feedback) -> None:
    source = feedback.scope.sources[0]
    TaskService(feedback.scope.engine).transition(
        tenant_id=feedback.scope.tenant.id,
        actor_user_id=source.owner.user.id,
        project_id=source.project_id,
        task_id=source.task_id,
        to_status="in_progress",
        blocked_reason=None,
    )


def approved_adjustment(feedback: Feedback) -> tuple[UUID, str]:
    scope = feedback.scope
    old = scope.proposal(scope.reservations())
    raw = old.model_dump(mode="json", exclude={"expected_preview_digest"})
    for item in raw["items"]:
        for field in ("window_start", "window_end"):
            item["target"][field] = (
                datetime.fromisoformat(item["target"][field]) + timedelta(days=6)
            ).isoformat()
    draft = ReallocationDraft.model_validate(raw)
    preview = ResourceReallocationService(scope.engine).preview(
        scope.admin, scope.sources[0].project_id, draft
    )
    allocation, payload = scope.save(
        ReallocationSubmit.model_validate(
            {**raw, "expected_preview_digest": preview["preview_digest"]}
        )
    )
    scope.approve(allocation, payload)
    return allocation, payload


@pytest.fixture
def long_feedback(scope: Scope) -> Iterator[tuple[Feedback, UUID, UUID, UUID]]:
    try:
        source = scope.sources[0]
        stage_id, plan_id, case_id = (uuid4() for _ in range(3))
        with scope.engine.begin() as c:
            assert c.execute(text("SHOW session_replication_role")).scalar_one() == "origin"
            workflow_id = c.execute(
                select(tables.projects.c.workflow_id).where(
                    tables.projects.c.tenant_id == scope.tenant.id,
                    tables.projects.c.id == source.project_id,
                )
            ).scalar_one()
            c.execute(
                tables.stages.insert().values(
                    id=stage_id,
                    tenant_id=scope.tenant.id,
                    workflow_id=workflow_id,
                    code="DVT",
                    name="Isolated long-test fixture",
                    sequence=1,
                )
            )
            c.execute(
                tables.test_plans.insert().values(
                    id=plan_id,
                    tenant_id=scope.tenant.id,
                    project_id=source.project_id,
                    workflow_id=workflow_id,
                    stage_id=stage_id,
                    created_by_user_id=source.owner.user.id,
                    phase="dvt",
                    title="Isolated ongoing long test",
                    sample_size=1,
                    status="active",
                )
            )
            c.execute(
                tables.test_cases.insert().values(
                    id=case_id,
                    tenant_id=scope.tenant.id,
                    project_id=source.project_id,
                    plan_id=plan_id,
                    created_by_user_id=source.owner.user.id,
                    title="Ongoing aging fixture",
                    category="reliability",
                    acceptance_criteria="Recorded terminal result",
                )
            )
        run = RunService(scope.engine).record_run(
            tenant_id=scope.tenant.id,
            actor_user_id=source.owner.user.id,
            project_id=source.project_id,
            test_case_id=case_id,
            draft=RunDraft(
                status="in_progress",
                expected_completion_at=datetime.now(UTC) + timedelta(days=7),
            ),
        )
        run_row = next(row for row in scope.rows(tables.test_runs) if row["id"] == str(run.id))
        node = ScheduleNodeService(scope.engine).register(
            source.owner,
            source.project_id,
            NodeDraft(
                request_id=uuid4(),
                node_kind="test_run",
                source_id=run.id,
                expected_source_digest=digest(run_row),
                calendar_version_id=scope.calendar_id,
            ),
        )
        node_id = UUID(node["id"])
        seed_formal(scope, source, None, {"T": node_id})
        yield Feedback(scope, source.task_id), case_id, run.id, node_id
    finally:
        with scope.engine.begin() as c:
            assert c.execute(text("SHOW session_replication_role")).scalar_one() == "origin"
            c.execute(text("SET LOCAL session_replication_role=replica"))
            for table in EXTRA_TABLES:
                c.execute(table.delete().where(table.c.tenant_id == scope.tenant.id))


def test_real_long_test_expected_finish_then_actual_and_correction_keep_history(
    long_feedback: tuple[Feedback, UUID, UUID, UUID],
) -> None:
    feedback, case_id, run_id, node_id = long_feedback
    scope, source = feedback.scope, feedback.scope.sources[0]
    baseline = feedback.baseline()
    first = feedback.recalculate()
    node = next(node for node in first["result"]["nodes"] if node["node_key"] == "T")
    assert node["node_id"] == str(node_id)
    assert node["origin"] == "business_expected_completion"
    assert node["actual_start"] is not None and node["actual_finish"] is None
    assert (
        datetime.fromisoformat(node["expected_completion_at"])
        <= datetime.fromisoformat(node["finish"])
        < datetime.fromisoformat(node["expected_completion_at"]) + timedelta(minutes=1)
    )
    assert node["remaining_work_minutes"] is None
    RunService(scope.engine).complete_run(
        tenant_id=scope.tenant.id,
        actor_user_id=source.owner.user.id,
        project_id=source.project_id,
        test_case_id=case_id,
        run_id=run_id,
        status="passed",
    )
    completed = feedback.history()["items"][0]
    node = next(node for node in completed["result"]["nodes"] if node["node_key"] == "T")
    assert completed["previous_record_id"] == first["record_id"]
    assert node["origin"] == "actual"
    assert node["finish"] == node["actual_finish"]
    assert node["finish"] != node["expected_completion_at"]
    service = SourceActualCorrectionService(scope.engine)
    observed = next(
        item
        for item in service.get(source.owner, source.project_id)["items"]
        if item["node_id"] == str(node_id)
    )
    actual = observed["actual"]
    command = SourceActualCorrection(
        request_id=uuid4(),
        observation_id=UUID(actual["id"]),
        expected_digest=observed["expected_digest"],
        started_at=datetime.fromisoformat(actual["started_at"]) - timedelta(minutes=5),
        finished_at=datetime.fromisoformat(actual["finished_at"]),
        reason="Correct synthetic original start evidence",
        evidence="Independent isolated fixture timestamp",
    )
    correction = service.correct(source.owner, source.project_id, node_id, command)
    history = feedback.history()
    corrected = history["items"][0]
    node = next(node for node in corrected["result"]["nodes"] if node["node_key"] == "T")
    assert corrected["previous_record_id"] == completed["record_id"]
    assert command.started_at is not None and command.finished_at is not None
    assert node["actual_start"] == command.started_at.isoformat()
    assert node["actual_finish"] == command.finished_at.isoformat()
    assert any(row["forecast_record_id"] == first["record_id"] for row in history["source_errors"])
    assert any(
        row["correction_id"] == correction["id"] for row in history["source_error_corrections"]
    )
    assert feedback.baseline() == baseline
    saved = feedback.snapshot()
    assert service.correct(source.owner, source.project_id, node_id, command) == correction
    assert feedback.snapshot() == saved


def test_real_actual_correction_keeps_continuous_forecasts_and_revised_errors(
    feedback: Feedback,
) -> None:
    baseline = feedback.baseline()
    first = feedback.recalculate()
    start_task(feedback)
    supplied = {
        key: RemainingEstimate(
            remaining_hours=Decimal(2),
            remaining_waiting_days=0,
            basis="Named remaining-work measurement",
        )
        for key in ("A", "B")
    }
    human = feedback.recalculate(supplied)
    command = correction_command(feedback)
    source = feedback.scope.sources[0]
    service = ActualCorrectionService(feedback.scope.engine)
    correction = service.correct(source.owner, source.project_id, command)
    history = feedback.history()
    latest = history["items"][0]
    assert latest["previous_record_id"] == human["record_id"]
    assert latest["inputs"]["estimates"] == {"B": supplied["B"].model_dump(mode="json")}
    assert latest["inputs"]["estimate_source_record_id"] == human["record_id"]
    nodes = {node["node_key"]: node for node in latest["result"]["nodes"]}
    assert nodes["A"]["actual_start"] == command.observed_at.isoformat()
    assert nodes["A"]["finish"] is None and nodes["B"]["finish"] is not None
    assert any(row["forecast_record_id"] == first["record_id"] for row in history["errors"])
    revised = [
        row for row in history["error_corrections"] if row["correction_id"] == correction["id"]
    ]
    assert revised and all(row["eligible"] is False for row in revised)
    assert feedback.baseline() == baseline
    saved = feedback.snapshot()
    assert service.correct(source.owner, source.project_id, command) == correction
    assert feedback.snapshot() == saved
    with pytest.raises(ProductWorkError, match="实际时间已变化"):
        service.correct(
            source.owner, source.project_id, command.model_copy(update={"request_id": uuid4()})
        )
    with pytest.raises(ProductWorkAccessError):
        ScheduleForecastService(feedback.scope.engine).get(
            feedback.scope.outsider, source.project_id
        )


def test_only_resource_application_invalidates_old_forecast_and_projects_new_window(
    feedback: Feedback,
) -> None:
    allocation, payload = approved_adjustment(feedback)
    baseline = feedback.baseline()
    old = feedback.recalculate()
    scope = feedback.scope
    command = scope.application(allocation, payload)
    service = ResourceReallocationService(scope.engine)
    application = service.apply(scope.admin, scope.sources[0].project_id, command)
    history = feedback.history()
    latest = history["items"][0]
    assert latest["previous_record_id"] == old["record_id"]
    previous = next(row for row in history["items"] if row["record_id"] == old["record_id"])
    assert previous["basis_is_current"] is False and latest["basis_is_current"] is True
    assert (
        latest["inputs"]["basis"]["resource_basis"]["applications"][0]["application_id"]
        == application["id"]
    )
    assert all(
        "body" not in policy and "reason" not in policy
        for policy in latest["inputs"]["basis"]["resource_basis"]["policies"].values()
    )
    assert all(
        item["project_id"] == str(scope.sources[0].project_id)
        for item in latest["inputs"]["basis"]["resource_basis"]["applications"][0]["items"]
    )
    node = next(node for node in latest["result"]["nodes"] if node["node_key"] == "A")
    assert datetime.fromisoformat(node["start"]) == scope.start + timedelta(days=7)
    assert latest["result"]["capacity_status"] == "not_rechecked"
    assert feedback.baseline() == baseline
    snapshot = feedback.snapshot()
    assert service.apply(scope.admin, scope.sources[0].project_id, command) == application
    assert feedback.snapshot() == snapshot
    scope.publish_priority(1)
    assert feedback.history()["items"][0]["basis_is_current"] is False
    current = feedback.recalculate()
    assert (
        next(node for node in current["result"]["nodes"] if node["node_key"] == "A")["finish"]
        is None
    )
    reservation = next(
        row
        for row in scope.rows(tables.resource_reservations)
        if row["state"] == "reserved" and row["project_id"] == str(scope.sources[0].project_id)
    )
    ResourceReservationService(scope.engine).act(
        scope.admin,
        scope.sources[0].project_id,
        UUID(reservation["id"]),
        ReservationAction(
            request_id=uuid4(),
            expected_digest=digest(reservation),
            action="release",
            reason="Real capacity no longer held",
        ),
    )
    current = feedback.recalculate()
    assert (
        next(node for node in current["result"]["nodes"] if node["node_key"] == "A")["finish"]
        is None
    )


@pytest.mark.parametrize("operation", ["correction", "resource_application"])
def test_feedback_audit_failure_rolls_back_source_and_forecast_then_same_request_recovers(
    feedback: Feedback,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    scope, source = feedback.scope, feedback.scope.sources[0]
    execute: Callable[[], dict[str, Any]]
    if operation == "correction":
        feedback.recalculate()
        start_task(feedback)
        correct = correction_command(feedback)

        def correct_run() -> dict[str, Any]:
            return ActualCorrectionService(scope.engine).correct(
                source.owner, source.project_id, correct
            )

        execute = correct_run
    else:
        allocation, payload = approved_adjustment(feedback)
        feedback.recalculate()
        apply = scope.application(allocation, payload)

        def apply_run() -> dict[str, Any]:
            return ResourceReallocationService(scope.engine).apply(
                scope.admin, source.project_id, apply
            )

        execute = apply_run
    before = feedback.snapshot()
    real = EventAuditWriter.record
    writes = 0

    class Failure(RuntimeError):
        pass

    def fail_after_real_forecast(
        writer: EventAuditWriter, event: EventDraft, audit: AuditDraft
    ) -> WrittenEventAudit:
        nonlocal writes
        receipt = real(writer, event, audit)
        if audit.action == "schedule.forecast":
            writes += 1
            raise Failure("real forecast event and audit written, then injected failure")
        return receipt

    with monkeypatch.context() as fault:
        fault.setattr(EventAuditWriter, "record", fail_after_real_forecast)
        with pytest.raises(Failure):
            execute()
    assert writes == 1 and feedback.snapshot() == before
    receipt = execute()
    saved = feedback.snapshot()
    assert execute() == receipt and feedback.snapshot() == saved
