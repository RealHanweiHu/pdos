"""Human selection of resource dates into the existing baseline proposal workflow."""

from datetime import UTC, datetime
from decimal import localcontext
from typing import Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy import Connection, Engine, or_, select
from sqlalchemy.exc import IntegrityError

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _plain,
    _role,
    digest,
)
from app.domain.project_resource_schedules import ResourceScheduleDraft
from app.domain.project_scenario_capacity import ProjectScenarioCapacityService, get_scenario
from app.domain.project_schedule_scenarios import (
    ProjectScenarioDraft,
    ProjectScheduleScenarioService,
    scenario_basis,
)
from app.domain.resource_capacity import CapacityCheckDraft, _compute
from app.domain.resource_reservations import _project
from app.domain.resource_schedule_solver import ResourceSolver
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class ResourceSchedulePreparation(Contract):
    request_id: UUID
    schedule_id: UUID
    expected_result_digest: Digest
    title: Text
    reason: Text


def get_schedule(c: Connection, context: AuthContext, project: UUID, schedule_id: UUID) -> Any:
    t = tables.project_resource_schedules
    row = (
        c.execute(
            select(t).where(
                t.c.tenant_id == context.tenant.id, t.c.project_id == project, t.c.id == schedule_id
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkAccessError("资源日期方案不存在或不属于此项目")
    return row


def source_digest(evidence: dict[str, Any]) -> str:
    if not evidence.get("ledger_identity_digest"):
        raise ProductWorkError("此历史方案尚未固定原占用记录身份，请重新计算资源日期")
    keys = ("policies", "profiles", "reserved_intervals", "priority_intervals", "legacy_missing")
    return digest(
        {
            "ledger_identity_digest": evidence["ledger_identity_digest"],
            **{key: sorted(evidence[key], key=digest) for key in keys},
        }
    )


def current_solver(
    c: Connection, context: AuthContext, project: UUID, saved: Any
) -> ResourceSolver:
    scenario = get_scenario(c, context, project, saved["scenario_id"])
    if scenario_basis(c, context, project)["basis_digest"] != saved["scenario_basis_digest"]:
        raise ProductWorkError("原计划、业务来源或实际进展已变化，请重新计算资源日期")
    draft = ResourceScheduleDraft.model_validate(saved["inputs"])
    solver = ResourceSolver(
        c, context, project, scenario, draft, datetime.now(UTC), draft.horizon_days
    )
    if solver.policy_errors or source_digest(solver.evidence()) != source_digest(
        saved["result"]["resource_solver"]
    ):
        raise ProductWorkError("容量、优先级政策或原占用/在先申请已变化，请重新计算资源日期")
    return solver


def capacity_for_origin(
    c: Connection,
    context: AuthContext,
    project: UUID,
    scenario: Any,
    draft: CapacityCheckDraft,
    projection: dict[str, Any],
) -> dict[str, Any] | None:
    t = tables.project_resource_schedule_preparations
    origin = (
        c.execute(
            select(t).where(
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == project,
                t.c.scenario_id == scenario["id"],
            )
        )
        .mappings()
        .one_or_none()
    )
    if origin is None:
        return None
    saved = get_schedule(c, context, project, origin["schedule_id"])
    incoming = draft.model_dump(mode="json")
    if any(incoming[key] != saved["inputs"][key] for key in ("demands", "no_resource_reasons")):
        raise ProductWorkError("此情景已固定所选资源及投入；改变需求后请重新计算资源日期方案")
    solver = current_solver(c, context, project, saved)
    with localcontext() as arithmetic:
        arithmetic.prec = 48
        result = _compute(
            {"id": scenario["id"], "result": projection, "result_digest": digest(projection)},
            draft.demands,
            solver.profiles,
            draft.no_resource_reasons,
            [*solver.original, *solver.pending],
            solver.legacy,
            match_existing_reservations=True,
        )
    result["resource_date_origin"] = {
        "preparation_id": str(origin["id"]),
        "schedule_id": str(saved["id"]),
        "result_digest": saved["result_digest"],
        "source_digest": source_digest(saved["result"]["resource_solver"]),
        "policies": saved["result"]["resource_solver"]["policies"],
    }
    return result


class ResourceSchedulePreparationService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def prepare(
        self, context: AuthContext, project: UUID, command: ResourceSchedulePreparation
    ) -> dict[str, Any]:
        _role(context, Action.PROJECT_EDIT)
        try:
            with self.engine.begin() as c:
                return self.prepare_in_connection(c, context, project, command)
        except IntegrityError as error:
            raise ProductWorkError(
                "方案准备未保存；请刷新原方案并核对来源，无预约或基线变更"
            ) from error

    def prepare_in_connection(
        self,
        c: Connection,
        context: AuthContext,
        project: UUID,
        command: ResourceSchedulePreparation,
        *,
        preserve_source_dates: bool = False,
    ) -> dict[str, Any]:
        _role(context, Action.PROJECT_EDIT)
        _project(c, context, project, write=True)
        c.execute(
            select(tables.projects.c.id)
            .where(
                tables.projects.c.tenant_id == context.tenant.id,
                tables.projects.c.id == project,
            )
            .with_for_update()
        )
        t = tables.project_resource_schedule_preparations
        fingerprint = digest(
            {
                "project_id": str(project),
                **command.model_dump(mode="json"),
                **({"preserve_source_dates": True} if preserve_source_dates else {}),
            }
        )
        prior = (
            c.execute(
                select(t).where(
                    t.c.tenant_id == context.tenant.id,
                    or_(
                        (t.c.created_by_user_id == context.user.id)
                        & (t.c.request_id == command.request_id),
                        t.c.schedule_id == command.schedule_id,
                    ),
                )
            )
            .mappings()
            .all()
        )
        if prior:
            if len(prior) != 1 or prior[0]["request_digest"] != fingerprint:
                raise ProductWorkError("此请求或资源方案已生成计划情景，请打开原准备回执")
            return _plain(prior[0])
        saved = get_schedule(c, context, project, command.schedule_id)
        if saved["result_digest"] != command.expected_result_digest:
            raise ProductWorkError("所选资源日期方案与审阅版本不一致")
        if saved["result"]["solution_status"] != "candidate_found":
            raise ProductWorkError("资源日期尚有未解约束，请先补齐并重算")
        current_solver(c, context, project, saved)
        original = get_scenario(c, context, project, saved["scenario_id"])
        source = ProjectScenarioDraft.model_validate(original["inputs"])
        remaining = source.model_dump(mode="json")["remaining_estimates"]
        plan = {node["node_key"]: node for node in original["plan"]["nodes"]}
        for node in saved["result"]["nodes"]:
            if node.get("actual_finish"):
                continue
            estimate = node.get("estimate")
            assumption = plan[node["node_key"]]
            remaining[node["node_id"]] = {
                "remaining_hours": estimate["remaining_hours"]
                if estimate
                else assumption["effort_hours"],
                "remaining_waiting_days": estimate["remaining_waiting_days"]
                if estimate
                else assumption["waiting_days"],
                "not_before": node["remaining_work_start"],
                "basis": (
                    f"沿资源日期方案 {saved['id']} 的原工时和等待估计；"
                    "采用其最早剩余工作时间，原依据见所选方案及原情景。"
                ),
            }
        draft = ProjectScenarioDraft.model_validate(
            {
                **source.model_dump(mode="json"),
                "request_id": str(uuid5(command.request_id, "resource-plan-scenario")),
                "expected_basis_digest": saved["scenario_basis_digest"],
                "title": command.title,
                "reason": command.reason,
                "remaining_estimates": remaining,
            }
        )
        scenario = ProjectScheduleScenarioService(self.engine).evaluate_in_connection(
            c,
            context,
            project,
            draft,
            calculation_as_of=datetime.fromisoformat(saved["result"]["as_of"])
            if preserve_source_dates
            else None,
        )
        proposed = {node["node_id"]: node for node in scenario["result"]["nodes"]}
        dates = [
            {
                "node_id": node["node_id"],
                "node_key": node["node_key"],
                "selected": {
                    key: node.get(key) for key in ("start", "finish", "remaining_work_start")
                },
                "prepared": {
                    key: proposed[node["node_id"]].get(key)
                    for key in ("start", "finish", "remaining_work_start")
                },
            }
            for node in saved["result"]["nodes"]
        ]
        receipt = {
            "source_result_digest": saved["result_digest"],
            "source_digest": source_digest(saved["result"]["resource_solver"]),
            "selected_as_of": saved["result"]["as_of"],
            "prepared_as_of": scenario["result"]["as_of"],
            "dates": dates,
            "dates_changed": any(item["selected"] != item["prepared"] for item in dates),
            "reservations_changed": False,
            "baseline_changed": False,
            "requires_baseline_approval": True,
        }
        row = (
            c.execute(
                t.insert()
                .values(
                    id=uuid4(),
                    tenant_id=context.tenant.id,
                    project_id=project,
                    schedule_id=saved["id"],
                    scenario_id=UUID(scenario["id"]),
                    title=command.title,
                    reason=command.reason,
                    receipt=receipt,
                    created_by_user_id=context.user.id,
                    request_id=command.request_id,
                    request_digest=fingerprint,
                )
                .returning(t)
            )
            .mappings()
            .one()
        )
        capacity = CapacityCheckDraft.model_validate(
            {
                "request_id": str(uuid5(command.request_id, "resource-plan-capacity")),
                "demands": saved["inputs"]["demands"],
                "no_resource_reasons": saved["inputs"]["no_resource_reasons"],
            }
        )
        checked = ProjectScenarioCapacityService(self.engine).check_in_connection(
            c, context, project, UUID(scenario["id"]), capacity
        )
        EventAuditWriter(
            c,
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project,
        ).record(
            EventDraft(
                event_id=f"resource-schedule-prepared:{row['id']}",
                event_type="RESOURCE_SCHEDULE_PREPARED",
                source="planning_service",
                entity_id=row["id"],
                payload={
                    "schedule_id": str(saved["id"]),
                    "scenario_id": scenario["id"],
                    "capacity_check_id": checked["id"],
                },
            ),
            AuditDraft(
                action="resource_schedule.prepare",
                after_snapshot={
                    "id": str(row["id"]),
                    "source_digest": receipt["source_digest"],
                    "dates_changed": receipt["dates_changed"],
                    "capacity_status": checked["result"]["status"],
                },
            ),
        )
        return _plain(row)
