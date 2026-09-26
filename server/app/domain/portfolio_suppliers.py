"""Supplier exposure across readable projects, based on original observations and material facts."""

from datetime import datetime
from decimal import Decimal, localcontext
from typing import Any, Literal
from uuid import UUID

from pydantic import Field
from sqlalchemy import Connection, Engine, func, select

from app.auth.repository import AuthContext
from app.contracts.common_objects import Contract, Digest
from app.db.schema import tables
from app.domain.build_materials import BuildMaterialService
from app.domain.document_previews import document_row, metadata
from app.domain.knowledge_push import KnowledgeAccessError
from app.domain.material_exposure import _project_ids, _source
from app.domain.portfolio_materials import PortfolioMaterialService
from app.domain.portfolio_materials import capture as material_capture
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError, _plain, digest
from app.domain.supplier_engineering import EngineeringDraft, sources


class SupplierOverview(Contract):
    project_id: UUID | None = None
    search: str = Field(default="", max_length=200)
    focus: Literal["all", "attention", "multiple_projects"] = "attention"
    order: Literal["attention", "projects", "code"] = "attention"
    offset: int = Field(default=0, ge=0)
    revision: Digest | None = None


class SupplierDetail(Contract):
    supplier_id: UUID
    project_id: UUID | None = None
    expected_digest: Digest
    part: Literal["engineering", "materials"] = "engineering"
    offset: int = Field(default=0, ge=0)
    revision: Digest | None = None


def engineering_query(tenant: UUID, project_ids: list[UUID]) -> Any:
    t = tables.supplier_engineering_records
    newer = t.alias("newer_supplier_exposure")
    return select(t).where(
        t.c.tenant_id == tenant,
        t.c.project_id.in_(project_ids),
        t.c.status == "active",
        ~select(newer.c.id)
        .where(
            newer.c.tenant_id == t.c.tenant_id,
            newer.c.project_id == t.c.project_id,
            newer.c.record_id == t.c.record_id,
            newer.c.version > t.c.version,
        )
        .correlate(t)
        .exists(),
    )


def engineering_record(
    c: Connection, context: AuthContext, row: Any, project: Any, now: datetime
) -> dict[str, Any]:
    missing = []
    actual: dict[str, Any] = {}
    try:
        actual = sources(
            c, context.tenant.id, row["project_id"], EngineeringDraft.model_validate(row["payload"])
        )
        if digest(actual) != digest(row["snapshot"]["sources"]):
            missing.append("原件或所关联业务记录已有变化，待原事项重核")
        promise = row["snapshot"].get("first_promise")
        if (
            promise
            and metadata(
                document_row(c, context.tenant.id, row["project_id"], UUID(promise["evidence_id"]))
            )
            != promise["document"]
        ):
            missing.append("首次承诺原证据已有变化")
    except (ValueError, LookupError, PermissionError) as error:
        missing.append(str(error))
    payload = row["payload"]

    def at(key: str) -> datetime | None:
        fact = payload.get(key)
        return datetime.fromisoformat(fact["at"]) if fact else None

    promise = row["snapshot"].get("first_promise")
    promised = datetime.fromisoformat(promise["at"]) if promise else None
    requested, received, responded = at("requested"), at("received"), at("responded")
    comparable = (
        row["kind"] == "sample_delivery"
        and received is not None
        and promised is not None
        and not missing
    )
    issue = actual.get("issue_id")
    return {
        "id": str(row["id"]),
        "record_id": str(row["record_id"]),
        "version": row["version"],
        "supplier_id": str(row["supplier_id"]),
        "project_id": str(row["project_id"]),
        "project_code": project["code"],
        "project_name": project["name"],
        "kind": row["kind"],
        "title": payload["title"],
        "source_reference": payload["source_reference"],
        "created_at": row["created_at"].isoformat(),
        "requested_at": requested.isoformat() if requested else None,
        "first_promised_at": promised.isoformat() if promised else None,
        "received_at": received.isoformat() if received else None,
        "responded_at": responded.isoformat() if responded else None,
        "detected_at": payload.get("detected", {}).get("at") if payload.get("detected") else None,
        "missing": missing,
        "source_current": not missing,
        "comparable_delivery": comparable,
        "late_delivery": bool(comparable and received and promised and received > promised),
        "overdue_unreceived": bool(
            row["kind"] == "sample_delivery"
            and not received
            and promised
            and promised < now
            and not missing
        ),
        "delivery_elapsed_days": str(Decimal(str((received - requested).total_seconds())) / 86400)
        if requested and received and not missing
        else None,
        "response_elapsed_hours": str(Decimal(str((responded - requested).total_seconds())) / 3600)
        if requested and responded and not missing
        else None,
        "issue": {
            k: issue[k]
            for k in ("id", "title", "status", "severity", "owner_user_id", "target_date")
        }
        if issue
        else None,
        "source_digest": digest({"row": _plain(row), "actual": actual, "missing": missing}),
        "href": (
            f"/projects?project={row['project_id']}&tab=materials"
            f"&supplier_engineering_supplier={row['supplier_id']}"
            f"&supplier_engineering_record={row['record_id']}#supplier-engineering"
        ),
    }


def aggregate(
    c: Connection, context: AuthContext, project_id: UUID | None, now: datetime
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    PortfolioMaterialService.authorize(context)
    try:
        visible = _project_ids(c, context)
    except KnowledgeAccessError as error:
        raise ProductWorkAccessError(str(error)) from error
    p, b, s = tables.projects, tables.build_batches, tables.suppliers
    query = select(p.c.id, p.c.code, p.c.name).where(
        p.c.tenant_id == context.tenant.id, p.c.id.in_(visible)
    )
    if project_id:
        BuildMaterialService._authorize(c, context, project_id)
        query = query.where(p.c.id == project_id)
    projects = {r["id"]: r for r in c.execute(query.order_by(p.c.id)).mappings()}
    for identity in projects:
        BuildMaterialService._authorize(c, context, identity)
    originals = list(
        c.execute(
            engineering_query(context.tenant.id, list(projects))
            .order_by(tables.supplier_engineering_records.c.id)
            .limit(10001)
        ).mappings()
    )
    if len(originals) > 10000:
        raise ProductWorkError("当前范围超过10000项供方事项，请先选择项目；未截断后计算指标")
    engineering = [
        engineering_record(c, context, r, projects[r["project_id"]], now) for r in originals
    ]
    builds = list(
        c.execute(
            select(b.c.id, b.c.project_id)
            .where(
                b.c.tenant_id == context.tenant.id,
                b.c.project_id.in_(projects),
                b.c.status.in_(("planned", "in_progress")),
            )
            .order_by(b.c.project_id, b.c.id)
        ).mappings()
    )
    materials = []
    attribution_cache: dict[str, bool] = {}
    for build in builds:
        items, details = material_capture(
            c, context, projects[build["project_id"]], build["id"], now, "baseline"
        )
        by_key = {v["material_key"]: v for v in details["coverage"]["materials"]}
        for item in items:
            links: dict[str, list[bool]] = {}
            pool_ids = by_key.get(item["material_key"], {}).get("pool_ids", [])
            for pool in details["pools"]:
                attribution = pool["supplier_attribution"]
                if (
                    not pool["source"]
                    or pool["source"]["id"] not in pool_ids
                    or not attribution
                    or not attribution["supplier_id"]
                ):
                    continue
                identity = attribution["id"]
                if identity not in attribution_cache:
                    try:
                        original = _source(
                            c,
                            context.tenant.id,
                            build["project_id"],
                            UUID(attribution["supply_snapshot_id"]),
                        )
                        evidence = metadata(
                            document_row(
                                c,
                                context.tenant.id,
                                build["project_id"],
                                UUID(attribution["evidence_id"]),
                            )
                        )
                        attribution_cache[identity] = bool(
                            original["current"]
                            and original["digest"] == attribution["snapshot"]["original"]["digest"]
                            and evidence == attribution["snapshot"]["evidence"]
                        )
                    except (ValueError, LookupError, PermissionError):
                        attribution_cache[identity] = False
                links.setdefault(attribution["supplier_id"], []).append(attribution_cache[identity])
            materials.append(
                {**item, "supplier_link_states": {k: all(v) for k, v in links.items()}}
            )
    identities = {UUID(v["supplier_id"]) for v in engineering} | {
        UUID(supplier["id"]) for material in materials for supplier in material["suppliers"]
    }
    suppliers = list(
        c.execute(
            select(s.c.id, s.c.code, s.c.name, s.c.status)
            .where(s.c.tenant_id == context.tenant.id, s.c.id.in_(identities))
            .order_by(s.c.code, s.c.id)
        ).mappings()
    )
    items = []
    for supplier in suppliers:
        identity = str(supplier["id"])
        entries = [v for v in engineering if v["supplier_id"] == identity]
        related = [
            {**v, "supplier_link_current": v["supplier_link_states"].get(identity, False)}
            for v in materials
            if any(s["id"] == identity for s in v["suppliers"])
        ]
        samples = [v for v in entries if v["kind"] == "sample_delivery"]
        received = [v for v in samples if v["received_at"]]
        comparable = [v for v in received if v["comparable_delivery"]]
        late = sum(v["late_delivery"] for v in comparable)
        responses = [v for v in entries if v["kind"] == "technical_response"]
        responded = [v for v in responses if v["responded_at"]]
        failure_issues = {
            v["issue"]["id"]: v["issue"]
            for v in entries
            if v["kind"] == "engineering_failure" and v["issue"]
        }
        project_ids = {v["project_id"] for v in entries + related}

        def mean(values: list[dict[str, Any]], field: str) -> str | None:
            if not values or any(v[field] is None for v in values):
                return None
            return str(
                (sum((Decimal(v[field]) for v in values), Decimal(0)) / len(values)).quantize(
                    Decimal("0.000001")
                )
            )

        summary = {
            "supplier_id": identity,
            "code": supplier["code"],
            "name": supplier["name"],
            "supplier_status": supplier["status"],
            "project_count": len(project_ids),
            "projects": [_plain(projects[UUID(v)]) for v in sorted(project_ids)],
            "engineering_count": len(entries),
            "source_unknown_count": sum(not v["source_current"] for v in entries),
            "sample_count": len(samples),
            "received_count": len(received),
            "comparable_delivery_count": len(comparable),
            "late_delivery_count": late,
            "on_time_percent": str(
                (Decimal(len(comparable) - late) * 100 / len(comparable)).quantize(
                    Decimal("0.0001")
                )
            )
            if comparable and len(comparable) == len(received)
            else None,
            "pending_sample_count": len(samples) - len(received),
            "sample_without_promise_count": sum(v["first_promised_at"] is None for v in samples),
            "overdue_unreceived_count": sum(v["overdue_unreceived"] for v in samples),
            "mean_delivery_elapsed_days": mean(received, "delivery_elapsed_days"),
            "response_count": len(responses),
            "responded_count": len(responded),
            "pending_response_count": len(responses) - len(responded),
            "mean_response_elapsed_hours": mean(responded, "response_elapsed_hours"),
            "reported_failure_count": sum(v["kind"] == "engineering_failure" for v in entries),
            "known_open_failure_issues": sum(
                v["status"] != "closed" for v in failure_issues.values()
            ),
            "known_open_severe_issues": sum(
                v["status"] != "closed" and v["severity"] in ("high", "critical")
                for v in failure_issues.values()
            ),
            "material_count": len(related),
            "material_link_recheck_count": sum(not v["supplier_link_current"] for v in related),
            "material_shortage_count": sum(v["status"] == "shortage" for v in related),
            "material_unknown_count": sum(v["status"] == "unknown" for v in related),
            "material_allocation_count": sum(v["status"] == "allocation" for v in related),
            "engineering": sorted(
                entries,
                key=lambda v: (
                    not v["overdue_unreceived"],
                    v["source_current"],
                    v["project_code"],
                    v["record_id"],
                ),
            ),
            "materials": sorted(
                related,
                key=lambda v: (
                    v["status"] == "covered",
                    v["need_date"] or "9999",
                    v["project_id"],
                    v["build_id"],
                    v["material_key"],
                ),
            ),
        }
        summary["attention"] = any(
            summary[k]
            for k in (
                "source_unknown_count",
                "pending_sample_count",
                "pending_response_count",
                "material_link_recheck_count",
                "overdue_unreceived_count",
                "late_delivery_count",
                "known_open_failure_issues",
                "material_shortage_count",
                "material_unknown_count",
                "material_allocation_count",
            )
        ) or any(v["first_promised_at"] is None for v in samples)
        summary["source_digest"] = digest(summary)
        items.append(summary)
    return items, {
        "visible_projects": len(projects),
        "observed_suppliers": len(items),
        "active_engineering_records": len(engineering),
        "unfinished_builds": len(builds),
        "missing_demand_builds": sum(
            v["status"] in ("demand_missing", "empty_demand") for v in materials
        ),
        "unattributed_materials": sum(
            v["material_key"] is not None and (not v["suppliers"] or v["unattributed_pools"] > 0)
            for v in materials
        ),
        "projects_without_recorded_supplier_links": len(projects)
        - len(
            {v["project_id"] for v in engineering}
            | {v["project_id"] for v in materials if v["suppliers"]}
        ),
    }


class PortfolioSupplierService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def read(self, context: AuthContext, command: SupplierOverview) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
            localcontext() as arithmetic,
        ):
            arithmetic.prec = 2048
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            items, scope = aggregate(c, context, command.project_id, now)
            selected = [
                v
                for v in items
                if command.search.casefold() in (v["code"] + " " + v["name"]).casefold()
                and (
                    command.focus == "all"
                    or command.focus == "attention"
                    and v["attention"]
                    or command.focus == "multiple_projects"
                    and v["project_count"] > 1
                )
            ]
            if command.order == "projects":
                selected.sort(key=lambda v: (-v["project_count"], v["code"], v["supplier_id"]))
            elif command.order == "code":
                selected.sort(key=lambda v: (v["code"], v["supplier_id"]))
            else:
                selected.sort(
                    key=lambda v: (
                        -v["overdue_unreceived_count"],
                        -v["known_open_severe_issues"],
                        -v["material_shortage_count"],
                        -v["source_unknown_count"],
                        v["code"],
                        v["supplier_id"],
                    )
                )
            revision = digest(
                {
                    "items": selected,
                    "scope": scope,
                    "filters": command.model_dump(mode="json", exclude={"offset", "revision"}),
                }
            )
            if command.offset and command.revision != revision:
                raise ProductWorkError("供方关联、原记录或读取范围已变化，请刷新第一页")
            return {
                "items": [
                    {k: v for k, v in r.items() if k not in ("engineering", "materials")}
                    for r in selected[command.offset : command.offset + 20]
                ],
                "total": len(selected),
                "scope": scope,
                "as_of": now.isoformat(),
                "revision": revision,
                "next_offset": command.offset + 20 if command.offset + 20 < len(selected) else None,
            }

    def detail(self, context: AuthContext, command: SupplierDetail) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
            localcontext() as arithmetic,
        ):
            arithmetic.prec = 2048
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            items, _ = aggregate(c, context, command.project_id, now)
            row = next((v for v in items if v["supplier_id"] == str(command.supplier_id)), None)
            if row is None:
                raise ProductWorkError("当前有权范围内已无该供方关联，请刷新汇总")
            values = row[command.part]
            revision = digest({"source": row["source_digest"], "part": command.part})
            if command.offset and revision != command.revision:
                raise ProductWorkError("供方明细已有变化，请重新读取第一页")
            return {
                "items": values[command.offset : command.offset + 30],
                "total": len(values),
                "revision": revision,
                "as_of": now.isoformat(),
                "source_current": row["source_digest"] == command.expected_digest,
                "summary": {k: v for k, v in row.items() if k not in ("engineering", "materials")},
                "next_offset": command.offset + 30 if command.offset + 30 < len(values) else None,
            }
