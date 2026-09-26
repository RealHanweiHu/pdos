"""Whole-scope material exceptions from the original fixed-demand and supply calculation."""

from datetime import datetime
from decimal import Decimal, localcontext
from typing import Any, Literal
from uuid import UUID

from pydantic import Field
from sqlalchemy import Connection, Engine, func, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Digest
from app.db.schema import tables
from app.domain.build_materials import BuildMaterialService
from app.domain.knowledge_push import KnowledgeAccessError
from app.domain.material_allocations import read_material_state
from app.domain.material_coverage import CoverageSelection, _schedule, calculate
from app.domain.material_exposure import _latest, _project_ids
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _plain,
    _role,
    digest,
)
from app.domain.work_calendars import CalendarCalculationError


class MaterialOverview(Contract):
    project_id: UUID | None = None
    search: str = Field(default="", max_length=200)
    material_reference: str = Field(default="", max_length=256)
    supplier_id: UUID | None = None
    critical_only: bool = True
    include_finished: bool = False
    time_kind: Literal["baseline", "commitment", "forecast"] = "baseline"
    focus: Literal["needs", "all", "shortage", "unknown", "allocation"] = "needs"
    order: Literal["need", "unknown", "project"] = "need"
    offset: int = Field(default=0, ge=0)
    revision: Digest | None = None


class MaterialDetail(Contract):
    project_id: UUID
    build_id: UUID
    material_key: Digest | None = None
    time_kind: Literal["baseline", "commitment", "forecast"] = "baseline"
    expected_digest: Digest


def capture(
    c: Connection,
    context: AuthContext,
    project: Any,
    build_id: UUID,
    now: datetime,
    time_kind: Literal["baseline", "commitment", "forecast"],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    state = read_material_state(c, context.tenant.id, project["id"], build_id, as_of=now)
    try:
        schedule = _schedule(c, context.tenant.id, project["id"], state["revision"], now)
    except CalendarCalculationError as error:
        schedule = {"node": None, "calendar": None, "times": {}, "issues": [str(error)]}
    coverage = calculate(state, schedule, CoverageSelection(time_kind=time_kind))
    pools = []
    for pool in coverage["pools"]:
        source = pool["source"]
        attribution = (
            _latest(c, context.tenant.id, UUID(source["id"]))
            if source and not source.get("source_grant_id")
            else None
        )
        pools.append({**pool, "supplier_attribution": attribution})
    e, i, u = tables.material_exceptions, tables.issues, tables.users
    issues = [
        _plain(v)
        for v in c.execute(
            select(
                e.c.id.label("exception_id"),
                e.c.material_key,
                i.c.id,
                i.c.title,
                i.c.status,
                i.c.owner_user_id,
                i.c.target_date,
                u.c.display_name.label("owner_name"),
            )
            .select_from(
                e.join(
                    i,
                    (i.c.tenant_id == e.c.tenant_id)
                    & (i.c.project_id == e.c.project_id)
                    & (i.c.id == e.c.issue_id),
                ).outerjoin(u, (u.c.tenant_id == i.c.tenant_id) & (u.c.id == i.c.owner_user_id))
            )
            .where(
                e.c.tenant_id == context.tenant.id,
                e.c.project_id == project["id"],
                e.c.build_id == build_id,
            )
            .order_by(e.c.id)
        ).mappings()
    ]
    revision = state["revision"]
    base = {
        "project_id": str(project["id"]),
        "project_code": project["code"],
        "project_name": project["name"],
        "build_id": str(build_id),
        "build_code": state["build"]["code"],
        "build_status": state["build"]["status"],
        "revision_id": revision["id"] if revision else None,
        "revision_version": revision["version"] if revision else None,
        "need_date": coverage["need_date"],
        "need_date_passed": coverage["need_date_passed"],
        "time_kind": time_kind,
        "time_record": schedule["times"].get(time_kind),
        "schedule_issues": schedule["issues"],
        "pool_limit_reached": coverage["pool_limit_reached"],
        "href": (
            f"/projects?project={project['id']}&tab=quality&build_id={build_id}#build-{build_id}"
        ),
    }
    items = []
    for material in coverage["materials"]:
        matching = [p for p in pools if p["source"] and p["source"]["id"] in material["pool_ids"]]
        suppliers: dict[str, Any] = {}
        for pool in matching:
            attribution = pool["supplier_attribution"]
            if attribution and attribution["supplier_id"]:
                supplier = attribution["snapshot"]["supplier"]
                suppliers[attribution["supplier_id"]] = {
                    "id": attribution["supplier_id"],
                    "code": supplier["code"],
                    "name": supplier["name"],
                }
        allocated_gap = max(
            Decimal(material["required"])
            - Decimal(material["allocated_on_hand"])
            - Decimal(material["qualified_issued"]),
            Decimal(0),
        )
        observed = material["observed_on_hand_gap"]
        status = (
            "unknown"
            if observed is None
            else "shortage"
            if Decimal(observed) > 0
            else "allocation"
            if allocated_gap > 0
            else "covered"
        )
        related = [v for v in issues if v["material_key"] == material["material_key"]]
        item = {
            **base,
            "material_key": material["material_key"],
            "status": status,
            "material_reference": material["material_reference"],
            "unit": material["unit"],
            "critical": any(v["critical"] for v in material["lines"]),
            "bom_line_count": len(material["lines"]),
            "required": material["required"],
            "allocated_on_hand": material["allocated_on_hand"],
            "qualified_issued": material["qualified_issued"],
            "allocation_gap": str(allocated_gap),
            "unallocated_on_hand": material["unallocated_on_hand"],
            "observed_on_hand_gap": observed,
            "source_state": material["source_state"],
            "issues": material["issues"],
            "related_issues": related,
            "suppliers": sorted(suppliers.values(), key=lambda v: v["id"]),
            "unattributed_pools": sum(
                not p["supplier_attribution"] or not p["supplier_attribution"]["supplier_id"]
                for p in matching
            ),
            "shared_pools": sum(bool(p["source"].get("source_grant_id")) for p in matching),
            "source_digest": digest(
                {
                    "coverage": coverage["digest"],
                    "material": material,
                    "pools": matching,
                    "related_issues": related,
                    "base": base,
                }
            ),
        }
        items.append(item)
    if not items:
        items.append(
            {
                **base,
                "material_key": None,
                "status": "demand_missing" if revision is None else "empty_demand",
                "critical": None,
                "material_reference": None,
                "suppliers": [],
                "related_issues": [],
                "unattributed_pools": 0,
                "source_digest": digest({"base": base, "revision": revision}),
            }
        )
    return items, {
        "coverage": coverage,
        "revision": revision,
        "pools": pools,
        "related_issues": issues,
    }


class PortfolioMaterialService:
    def __init__(self, engine: Engine):
        self.engine = engine

    @staticmethod
    def authorize(context: AuthContext) -> None:
        _role(context, Action.PRODUCT_ENGINEERING_VIEW)
        _role(context, Action.WORK_ITEM_VIEW)

    def read(self, context: AuthContext, command: MaterialOverview) -> dict[str, Any]:
        self.authorize(context)
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
            localcontext() as arithmetic,
        ):
            arithmetic.prec = 2048
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            p, b = tables.projects, tables.build_batches
            try:
                visible_projects = _project_ids(c, context)
            except KnowledgeAccessError as error:
                raise ProductWorkAccessError(str(error)) from error
            project_query = select(p.c.id, p.c.code, p.c.name).where(
                p.c.tenant_id == context.tenant.id, p.c.id.in_(visible_projects)
            )
            if command.project_id:
                project_query = project_query.where(p.c.id == command.project_id)
            if command.search:
                project_query = project_query.where(
                    p.c.code.icontains(command.search, autoescape=True)
                    | p.c.name.icontains(command.search, autoescape=True)
                )
            projects = list(c.execute(project_query.order_by(p.c.code, p.c.id)).mappings())
            by_project = {v["id"]: v for v in projects}
            build_query = select(b.c.id, b.c.project_id).where(
                b.c.tenant_id == context.tenant.id, b.c.project_id.in_(by_project)
            )
            if not command.include_finished:
                build_query = build_query.where(b.c.status.in_(("planned", "in_progress")))
            builds = list(c.execute(build_query.order_by(b.c.project_id, b.c.id)).mappings())
            all_items = [
                item
                for build in builds
                for item in capture(
                    c, context, by_project[build["project_id"]], build["id"], now, command.time_kind
                )[0]
            ]
            supplier_options = {v["id"]: v for item in all_items for v in item["suppliers"]}
            items = [
                v
                for v in all_items
                if (not command.critical_only or v["critical"] is not False)
                and (
                    not command.material_reference
                    or v["material_reference"] == command.material_reference
                )
                and (
                    not command.supplier_id
                    or any(s["id"] == str(command.supplier_id) for s in v["suppliers"])
                )
            ]
            totals = {
                "projects": len(projects),
                "builds": len(builds),
                "projects_without_builds": len(set(by_project) - {v["project_id"] for v in builds}),
                "missing_demand_builds": sum(
                    v["status"] in ("demand_missing", "empty_demand") for v in all_items
                ),
                "unattributed_materials": sum(
                    v["material_key"] is not None
                    and (not v["suppliers"] or v["unattributed_pools"] > 0)
                    for v in all_items
                ),
                "filtered_materials": sum(v["material_key"] is not None for v in items),
            }
            for state in (
                "shortage",
                "unknown",
                "allocation",
                "covered",
                "demand_missing",
                "empty_demand",
            ):
                totals[state] = sum(v["status"] == state for v in items)
            if command.focus == "needs":
                items = [v for v in items if v["status"] != "covered"]
            elif command.focus == "unknown":
                items = [
                    v for v in items if v["status"] in ("unknown", "demand_missing", "empty_demand")
                ]
            elif command.focus != "all":
                items = [v for v in items if v["status"] == command.focus]

            def ordering(v: dict[str, Any]) -> tuple[Any, ...]:
                tie = (
                    v["project_code"],
                    v["project_id"],
                    v["build_code"],
                    v["build_id"],
                    v["material_key"] or "",
                )
                unknown = v["status"] in ("unknown", "demand_missing", "empty_demand")
                if command.order == "project":
                    return tie
                if command.order == "unknown":
                    return (not unknown, *tie)
                return (
                    not v["need_date_passed"],
                    v["need_date"] is None,
                    v["need_date"] or "",
                    {
                        "shortage": 0,
                        "unknown": 1,
                        "demand_missing": 1,
                        "empty_demand": 1,
                        "allocation": 2,
                        "covered": 3,
                    }[v["status"]],
                    *tie,
                )

            items.sort(key=ordering)
            revision = digest(
                {
                    "items": items,
                    "totals": totals,
                    "projects": [_plain(v) for v in projects],
                    "suppliers": supplier_options,
                    "filters": command.model_dump(mode="json", exclude={"offset", "revision"}),
                }
            )
            if command.offset and command.revision != revision:
                raise ProductWorkError("物料需求、供给、原问题或读取范围已变化，请刷新第一页")
            return {
                "items": items[command.offset : command.offset + 20],
                "total": len(items),
                "next_offset": command.offset + 20 if command.offset + 20 < len(items) else None,
                "revision": revision,
                "totals": totals,
                "as_of": now.isoformat(),
                "projects": [_plain(v) for v in projects],
                "suppliers": sorted(supplier_options.values(), key=lambda v: (v["code"], v["id"])),
            }

    def detail(self, context: AuthContext, command: MaterialDetail) -> dict[str, Any]:
        self.authorize(context)
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
            localcontext() as arithmetic,
        ):
            arithmetic.prec = 2048
            try:
                BuildMaterialService._authorize(c, context, command.project_id)
            except KnowledgeAccessError as error:
                raise ProductWorkAccessError(str(error)) from error
            p = tables.projects
            project = (
                c.execute(
                    select(p.c.id, p.c.code, p.c.name).where(
                        p.c.tenant_id == context.tenant.id, p.c.id == command.project_id
                    )
                )
                .mappings()
                .one()
            )
            b = tables.build_batches
            if (
                c.execute(
                    select(b.c.id).where(
                        b.c.tenant_id == context.tenant.id,
                        b.c.project_id == command.project_id,
                        b.c.id == command.build_id,
                    )
                ).first()
                is None
            ):
                raise ProductWorkError("当前项目中没有所选批次，请刷新后读取")
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            items, detail = capture(c, context, project, command.build_id, now, command.time_kind)
            selected = next((v for v in items if v["material_key"] == command.material_key), None)
            if selected is None:
                return {
                    "source_current": False,
                    "item": None,
                    "as_of": now.isoformat(),
                    "message": "原物料范围已不在最新固定需求中，请刷新全局结果",
                }
            coverage = detail["coverage"]
            material = next(
                (v for v in coverage["materials"] if v["material_key"] == command.material_key),
                None,
            )
            source_ids = set(material["pool_ids"]) if material else set()
            line_ids = {v["bom_item_id"] for v in material["lines"]} if material else set()
            return {
                "source_current": selected["source_digest"] == command.expected_digest,
                "item": selected,
                "as_of": now.isoformat(),
                "material": material,
                "schedule": coverage["schedule"],
                "revision": {k: v for k, v in (detail["revision"] or {}).items() if k != "lines"},
                "pools": [
                    v
                    for v in detail["pools"]
                    if (v["source"] and v["source"]["id"] in source_ids)
                    or (
                        not v["source"]
                        and material
                        and v["pool_key"][2] == material["material_reference"]
                    )
                ],
                "allocations": [
                    v
                    for v in coverage["allocations"]
                    if v["bom_item_id"] in line_ids and v["revision_id"] == coverage["revision_id"]
                ],
            }
