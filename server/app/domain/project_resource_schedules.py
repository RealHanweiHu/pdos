"""Saved resource-constrained schedule proposals with fixed source evidence."""

from datetime import datetime
from decimal import localcontext
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import Engine, func, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.forecast_capacity import reservation_differences
from app.domain.product_workspace import ProductWorkError, _plain, _role, digest
from app.domain.project_scenario_capacity import get_scenario
from app.domain.project_schedule_scenarios import calculate_scenario_at, scenario_basis
from app.domain.resource_capacity import CapacityCheckDraft, _compute
from app.domain.resource_reservations import _project
from app.domain.resource_schedule_solver import ResourceSolver
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class ResourceScheduleDraft(CapacityCheckDraft):
    horizon_days: int = Field(default=90, ge=1, le=366)


class ProjectResourceScheduleService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def list(
        self, context: AuthContext, project: UUID, scenario_id: UUID, before: UUID | None = None
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            _project(c, context, project)
            get_scenario(c, context, project, scenario_id)
            t = tables.project_resource_schedules
            query = select(t).where(
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == project,
                t.c.scenario_id == scenario_id,
            )
            if before:
                cursor = c.execute(query.where(t.c.id == before)).mappings().one_or_none()
                if cursor is None:
                    raise ProductWorkError("资源日期历史游标不属于此情景")
                query = query.where(
                    (t.c.created_at < cursor["created_at"])
                    | ((t.c.created_at == cursor["created_at"]) & (t.c.id < before))
                )
            rows = list(
                c.execute(query.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21)).mappings()
            )
            prepared = tables.project_resource_schedule_preparations
            origins = {
                row["schedule_id"]: _plain(dict(row))
                for row in c.execute(
                    select(prepared).where(
                        prepared.c.tenant_id == context.tenant.id,
                        prepared.c.project_id == project,
                        prepared.c.schedule_id.in_([item["id"] for item in rows[:20]]),
                    )
                ).mappings()
            }
            return {
                "items": [
                    {**_plain(row), "preparation": origins.get(row["id"])} for row in rows[:20]
                ],
                "next": str(rows[19]["id"]) if len(rows) > 20 else None,
            }

    def solve(
        self, context: AuthContext, project: UUID, scenario_id: UUID, draft: ResourceScheduleDraft
    ) -> dict[str, Any]:
        _role(context, Action.PROJECT_EDIT)
        with self.engine.begin() as c:
            actual = _project(c, context, project, write=True)
            c.execute(
                select(tables.projects.c.id)
                .where(
                    tables.projects.c.tenant_id == context.tenant.id,
                    tables.projects.c.id == project,
                )
                .with_for_update()
            )
            table = tables.project_resource_schedules
            fingerprint = digest(
                {
                    "project_id": str(project),
                    "scenario_id": str(scenario_id),
                    **draft.model_dump(mode="json"),
                }
            )
            prior = (
                c.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.created_by_user_id == context.user.id,
                        table.c.request_id == draft.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != fingerprint:
                    raise ProductWorkError("请求编号已用于另一份资源日期方案")
                return _plain(prior)
            if actual["status"] in ("completed", "archived"):
                raise ProductWorkError("已结束项目不能新建资源日期方案")
            scenario = get_scenario(c, context, project, scenario_id)
            if scenario_basis(c, context, project)["basis_digest"] != scenario["basis_digest"]:
                raise ProductWorkError("情景来源或实际进展已变化，请先重新计算情景")
            now: datetime = c.execute(select(func.clock_timestamp())).scalar_one()
            solver = ResourceSolver(c, context, project, scenario, draft, now, draft.horizon_days)
            now = solver.as_of
            with localcontext() as arithmetic:
                arithmetic.prec = 48
                result = calculate_scenario_at(scenario, now, solver.place)
                projection = {
                    **result,
                    "nodes": [
                        {
                            **node,
                            "start": node["remaining_work_start"],
                            "work_minutes": node["remaining_work_minutes"],
                        }
                        for node in result["nodes"]
                        if not node.get("actual_finish")
                    ],
                }
                capacity = _compute(
                    {"id": scenario_id, "result": projection, "result_digest": digest(projection)},
                    draft.demands,
                    solver.profiles,
                    draft.no_resource_reasons,
                    [*solver.original, *solver.pending],
                    solver.legacy,
                    match_existing_reservations=True,
                )
            mapping = {UUID(node["node_id"]): node["node_key"] for node in result["nodes"]}
            uncertain = {
                node["node_key"]
                for node in projection["nodes"]
                if node["start"] is None or node["work_minutes"] is None
            }
            capacity["reservation_differences"] = reservation_differences(
                c, context.tenant.id, project, capacity, now, uncertain, node_keys=mapping
            )
            # A proposal can be feasible while existing reservations still need independent action.
            feasible = result["complete"] and capacity["status"] == "capacity_clear"
            evidence = solver.evidence()
            result.update(
                resource_solver=evidence,
                capacity=capacity,
                capacity_status=capacity["status"],
                solution_status="candidate_found" if feasible else "unresolved",
                applied=False,
                ready_for_application=False,
            )
            if scenario_basis(c, context, project)["basis_digest"] != scenario["basis_digest"]:
                raise ProductWorkError("计算期间情景依据变化，请刷新后重算")
            row = (
                c.execute(
                    table.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project,
                        scenario_id=scenario_id,
                        inputs=draft.model_dump(mode="json"),
                        result=result,
                        result_digest=digest(result),
                        scenario_basis_digest=scenario["basis_digest"],
                        source_digest=digest(
                            {
                                k: v
                                for k, v in evidence.items()
                                if k not in ("decisions", "attempts")
                            }
                        ),
                        created_by_user_id=context.user.id,
                        request_id=draft.request_id,
                        request_digest=fingerprint,
                        created_at=now,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            policies = {p["resource_id"]: p["policy_id"] for p in solver.policies}
            for profile in solver.profiles.values():
                c.execute(
                    tables.project_resource_schedule_versions.insert().values(
                        tenant_id=context.tenant.id,
                        schedule_id=row["id"],
                        capacity_version_id=profile["id"],
                        policy_id=UUID(policies[str(profile["resource_id"])])
                        if str(profile["resource_id"]) in policies
                        else None,
                    )
                )
            EventAuditWriter(
                c, tenant_id=context.tenant.id, actor_user_id=context.user.id, project_id=project
            ).record(
                EventDraft(
                    event_id=f"resource-schedule:{row['id']}",
                    event_type="PROJECT_RESOURCE_SCHEDULE_PROPOSED",
                    source="planning_service",
                    entity_id=row["id"],
                    payload={"scenario_id": str(scenario_id), "schedule_id": str(row["id"])},
                ),
                AuditDraft(
                    action="project_resource_schedule.solve",
                    after_snapshot={
                        "id": str(row["id"]),
                        "result_digest": row["result_digest"],
                        "solution_status": result["solution_status"],
                    },
                ),
            )
            return _plain(row)
