"""Bounded traversal of actual change references; adjacency is not an impact decision."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, func, or_, select

from app.auth.project_access import ProjectAccessService, SqlProjectAccessRepository
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.change_impact_scope import current_basis as scope_basis
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.professional_change_routes import impact_basis
from app.domain.test_verification_paths import _authorize

# Explicit domain relationships only: sharing a project is never an impact edge.
KINDS = {
    "ecr": (tables.engineering_change_requests, "工程变更"),
    "ecn": (tables.engineering_change_notices, "变更通知"),
    "bom": (tables.development_boms, "BOM"),
    "bom_item": (tables.development_bom_items, "BOM物料项"),
    "specification": (tables.specifications, "规格"),
    "requirement": (tables.requirements, "需求"),
    "test_case": (tables.test_cases, "测试项"),
    "test_run": (tables.test_runs, "逐次测试"),
    "sample": (tables.samples, "样机"),
    "configuration": (tables.sample_configuration_revisions, "当次配置"),
    "build": (tables.build_batches, "试制批次"),
    "issue": (tables.issues, "问题"),
    "cost_item": (tables.cost_bom_items, "BOM成本项"),
    "cost": (tables.costs, "项目成本"),
    "supplier": (tables.suppliers, "供方"),
    "certification": (tables.certifications, "认证"),
    "document": (tables.documents, "原始文件"),
}
RELATIONS = (
    ("ecn", "ecr_id", "ecr", "通知来源变更"),
    ("ecn", "released_bom_id", "bom", "通知生效BOM"),
    ("bom", "specification_id", "specification", "BOM依据规格"),
    ("bom_item", "bom_id", "bom", "BOM所属物料项"),
    ("bom_item", "parent_item_id", "bom_item", "物料项父子关系"),
    ("specification", "requirement_id", "requirement", "规格依据需求"),
    ("test_case", "specification_id", "specification", "测试验证规格"),
    ("test_case", "related_issue_id", "issue", "测试关联问题"),
    ("test_run", "test_case_id", "test_case", "测试项逐次执行"),
    ("test_run", "sample_id", "sample", "测试实际样机"),
    ("test_run", "sample_configuration_revision_id", "configuration", "测试当次配置"),
    ("test_run", "evidence_document_id", "document", "测试原始证据"),
    ("configuration", "sample_id", "sample", "样机配置版本"),
    ("configuration", "source_document_id", "document", "配置原始出处"),
    ("sample", "prototype_bom_id", "bom", "样机装配BOM"),
    ("sample", "parent_sample_id", "sample", "样机谱系"),
    ("sample", "build_batch_id", "build", "样机实际批次"),
    ("issue", "sample_id", "sample", "问题关联样机"),
    ("cost_item", "bom_item_id", "bom_item", "物料项成本"),
    ("cost_item", "bom_id", "bom", "成本归属BOM"),
    ("cost", "supplier_id", "supplier", "成本对应供方"),
    ("certification", "replaces_certification_id", "certification", "重新认证替代来源"),
)
MAX_NODES = 600


def _key(kind: str, id: Any) -> str:
    return f"{kind}:{id}"


def read(
    engine: Engine, *, context: AuthContext, project_id: UUID, ecr_id: UUID, depth: int = 3
) -> dict[str, Any]:
    _authorize(engine, context, project_id, edit=False)
    ProjectAccessService(SqlProjectAccessRepository(engine)).authorize(
        context=context, project_id=project_id, action=Action.CHANGE_VIEW
    )
    if not 1 <= depth <= 6:
        raise ProductWorkError("请选择1至6层关联范围")
    # One repeatable snapshot for nodes, edge references and approval comparison.
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        return _read(c, context.tenant.id, project_id, ecr_id, depth)


def _read(
    c: Connection, tenant_id: UUID, project_id: UUID, ecr_id: UUID, depth: int
) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    raw: dict[str, dict[UUID, dict[str, Any]]] = defaultdict(dict)
    gaps: list[dict[str, Any]] = []
    limits: set[str] = set()

    def scoped(kind: str) -> Any:
        t = KINDS[kind][0]
        predicates = [t.c.tenant_id == tenant_id]
        if "project_id" in t.c:
            predicates.append(t.c.project_id == project_id)
        return select(t).where(*predicates)

    def add(kind: str, row: dict[str, Any]) -> bool:
        key = _key(kind, row["id"])
        if key in nodes:
            return False
        if len(nodes) >= MAX_NODES:
            limits.add("节点上限")
            return False
        raw[kind][row["id"]] = row
        label = next(
            (
                str(row[k])
                for k in (
                    "title",
                    "name",
                    "serial_number",
                    "part_number",
                    "filename",
                    "code",
                    "certificate_type",
                )
                if row.get(k)
            ),
            KINDS[kind][1],
        )
        nodes[key] = {
            "key": key,
            "kind": kind,
            "kind_label": KINDS[kind][1],
            "id": str(row["id"]),
            "label": label,
            "digest": digest(_plain(row)),
            "test_case_id": str(row["test_case_id"]) if row.get("test_case_id") else None,
            "facts": _plain(
                {
                    k: row[k]
                    for k in (
                        "code",
                        "version",
                        "revision_number",
                        "status",
                        "draft_state",
                        "part_number",
                        "bom_type",
                        "quantity",
                        "unit",
                        "currency",
                        "unit_cost",
                        "amount",
                        "run_number",
                        "execution_time_precision",
                        "executed_at",
                        "valid_until",
                        "updated_at",
                    )
                    if k in row
                }
            ),
        }
        return True

    def edge(source: str, target: str, label: str, evidence: dict[str, Any]) -> None:
        if source not in nodes or target not in nodes:
            return
        value = {"source": source, "target": target, "label": label, "evidence": evidence}
        edges[digest(value)] = value

    ecr = (
        c.execute(scoped("ecr").where(tables.engineering_change_requests.c.id == ecr_id))
        .mappings()
        .one_or_none()
    )
    if ecr is None:
        raise ProductWorkError("工程变更不存在或不属于本项目")
    add("ecr", dict(ecr))
    seeds: dict[str, set[UUID]] = defaultdict(set)
    seeds["ecr"].add(ecr_id)
    pending_edges: list[tuple[str, str, str, dict[str, Any]]] = []
    links = tables.ecr_affected_boms
    for link in c.execute(
        select(links).where(
            links.c.tenant_id == tenant_id,
            links.c.project_id == project_id,
            links.c.ecr_id == ecr_id,
        )
    ).mappings():
        seeds["bom"].add(link["bom_id"])
        pending_edges.append(
            (
                _key("ecr", ecr_id),
                _key("bom", link["bom_id"]),
                "人工标记的受影响BOM",
                {"table": links.fullname, "ecr_id": str(ecr_id), "bom_id": str(link["bom_id"])},
            )
        )
    scope = scope_basis(c, tenant_id, project_id, ecr_id)
    scope_items = {}
    scope_comparisons = []
    approved_scope = ((ecr["impact_analysis"] or {}).get("impact_scope") or {}).get("basis")
    if scope:
        for item in scope["version"]["snapshot"]["items"]:
            kind, id = item["kind"], UUID(item["id"])
            seeds[kind].add(id)
            scope_items[item["key"]] = _key(kind, id)
            pending_edges.append(
                (
                    _key("ecr", ecr_id),
                    _key(kind, id),
                    "人工核对范围："
                    + {"affected": "受影响", "unaffected": "无影响", "unknown": "待查"}[
                        item["conclusion"]
                    ],
                    {
                        "scope_version_id": scope["version"]["id"],
                        "source_revision": scope["version"]["revision_number"],
                        "basis": item["basis"],
                        "expected_digest": item["expected_digest"],
                    },
                )
            )
        for link in scope["version"]["snapshot"]["edges"]:
            pending_edges.append(
                (
                    scope_items[link["source_key"]],
                    scope_items[link["target_key"]],
                    "人工核对关系：" + link["relation"],
                    {
                        "scope_version_id": scope["version"]["id"],
                        "source_revision": scope["version"]["revision_number"],
                        "basis": link["basis"],
                        "evidence_document_id": link["evidence_document_id"],
                        "evidence_locator": link["evidence_locator"],
                        "expected_digest": link["evidence_digest"],
                    },
                )
            )
        old_sources = {(r["kind"], r["id"]): r for r in (approved_scope or {}).get("sources", [])}
        for ref in scope["sources"]:
            old = old_sources.get((ref["kind"], ref["id"]))
            scope_comparisons.append(
                {
                    **ref,
                    "analysis_comparison": "not_analyzed"
                    if old is None
                    else "unchanged"
                    if old["current_digest"] == ref["current_digest"]
                    else "changed",
                }
            )
    professional = impact_basis(c, tenant_id, project_id, ecr_id)
    comparisons = []
    stored = ((ecr["impact_analysis"] or {}).get("professional") or {}).get("basis", {})
    prior = {s["route_id"]: s for s in stored.get("sources", [])}
    for source in (professional or {}).get("sources", []):
        route_id = source["route_id"]
        previous = prior.get(route_id)
        comparisons.append(
            {
                "route_id": route_id,
                "source_id": source["source"]["id"],
                "kind": source["kind"],
                "revision": source["source"]["revision_number"],
                "ready": source["ready"],
                "comparison": "not_analyzed"
                if previous is None
                else "unchanged"
                if digest(previous) == digest(source)
                else "changed",
                "reference_changes": [
                    {"kind": r["kind"], "id": r["id"], "changed": r["changed"]}
                    for r in source["references"]
                ],
            }
        )
        for ref in source["source"]["snapshot"]["sources"]:
            kind, id = ref["kind"], UUID(ref["id"])
            if kind not in KINDS:
                continue
            seeds[kind].add(id)
            pending_edges.append(
                (
                    _key("ecr", ecr_id),
                    _key(kind, id),
                    "转入专业资料引用",
                    {
                        "route_id": route_id,
                        "source_id": source["source"]["id"],
                        "source_revision": source["source"]["revision_number"],
                        "expected_digest": ref["expected_digest"],
                    },
                )
            )
    for kind, ids in seeds.items():
        for row in c.execute(
            scoped(kind)
            .where(KINDS[kind][0].c.id.in_(ids))
            .order_by(KINDS[kind][0].c.id)
            .limit(MAX_NODES + 1)
        ).mappings():
            add(kind, dict(row))
        for id in ids:
            if id not in raw[kind]:
                gaps.append(
                    {"node": _key(kind, id), "message": "引用对象当前不可读，或已达到展示上限"}
                )
    for args in pending_edges:
        edge(*args)
    frontier = {kind: set(records) for kind, records in raw.items()}
    for _ in range(depth):
        next_frontier: dict[str, set[UUID]] = defaultdict(set)
        bridge = tables.test_case_samples
        bridge_filters = []
        if frontier.get("test_case"):
            bridge_filters.append(bridge.c.test_case_id.in_(frontier["test_case"]))
        if frontier.get("sample"):
            bridge_filters.append(bridge.c.sample_id.in_(frontier["sample"]))
        if bridge_filters:
            allocations = (
                c.execute(
                    select(bridge)
                    .where(
                        bridge.c.tenant_id == tenant_id,
                        bridge.c.project_id == project_id,
                        or_(*bridge_filters),
                    )
                    .order_by(bridge.c.test_case_id, bridge.c.sample_id)
                    .limit(MAX_NODES + 1)
                )
                .mappings()
                .all()
            )
            if len(allocations) > MAX_NODES:
                limits.add("样机分配查询上限")
            for kind, column in (("test_case", "test_case_id"), ("sample", "sample_id")):
                ids = {r[column] for r in allocations} - set(raw[kind])
                if ids:
                    for row in c.execute(
                        scoped(kind)
                        .where(KINDS[kind][0].c.id.in_(ids))
                        .order_by(KINDS[kind][0].c.id)
                        .limit(MAX_NODES + 1)
                    ).mappings():
                        if add(kind, dict(row)):
                            next_frontier[kind].add(row["id"])
            for allocation in allocations:
                edge(
                    _key("test_case", allocation["test_case_id"]),
                    _key("sample", allocation["sample_id"]),
                    "计划分配的样机",
                    {
                        "table": bridge.fullname,
                        "test_case_id": str(allocation["test_case_id"]),
                        "sample_id": str(allocation["sample_id"]),
                    },
                )
        for child, field, parent, label in RELATIONS:
            child_table, parent_table = KINDS[child][0], KINDS[parent][0]
            selected_children = set(frontier.get(child, set()))
            if frontier.get(parent):
                matches = (
                    c.execute(
                        scoped(child)
                        .where(child_table.c[field].in_(frontier[parent]))
                        .order_by(child_table.c.id)
                        .limit(MAX_NODES + 1)
                    )
                    .mappings()
                    .all()
                )
                if len(matches) > MAX_NODES:
                    limits.add("关联查询上限")
                for row in matches:
                    if add(child, dict(row)):
                        next_frontier[child].add(row["id"])
                    if row["id"] in raw[child]:
                        selected_children.add(row["id"])
            parent_ids = {
                raw[child][id][field]
                for id in selected_children
                if raw[child][id][field] is not None
            }
            missing = parent_ids - set(raw[parent])
            if missing:
                for row in c.execute(
                    scoped(parent)
                    .where(parent_table.c.id.in_(missing))
                    .order_by(parent_table.c.id)
                    .limit(MAX_NODES + 1)
                ).mappings():
                    if add(parent, dict(row)):
                        next_frontier[parent].add(row["id"])
            for id in selected_children:
                record = raw[child][id]
                if record[field] is not None:
                    edge(
                        _key(child, id),
                        _key(parent, record[field]),
                        label,
                        {
                            "table": child_table.fullname,
                            "record_id": str(id),
                            "field": field,
                            "target_id": str(record[field]),
                            "record_digest": nodes[_key(child, id)]["digest"],
                        },
                    )
        frontier = next_frontier
        if not any(frontier.values()) or len(nodes) >= MAX_NODES:
            break
    if any(frontier.values()):
        limits.add("深度或节点范围之外仍有待展开关系")

    for kind, field, message in (
        ("bom", "specification_id", "BOM尚未关联规格"),
        ("test_case", "specification_id", "测试项尚未关联验证规格"),
        ("sample", "prototype_bom_id", "样机尚未关联装配BOM"),
        ("test_run", "sample_configuration_revision_id", "当次测试配置未知"),
        ("test_run", "evidence_document_id", "逐次测试缺少原始文件证据"),
    ):
        for id, record in raw[kind].items():
            if record[field] is None:
                gaps.append({"node": _key(kind, id), "message": message})
    unresolved = []
    for kind, reason in (
        ("certification", "认证关系仅含明确引用及具名补录，其余认证须核对复认证范围"),
        ("cost", "项目费用不能仅凭所属项目认定受影响，须核对费用与变更范围"),
    ):
        t = KINDS[kind][0]
        total = c.execute(
            select(func.count())
            .select_from(t)
            .where(t.c.tenant_id == tenant_id, t.c.project_id == project_id)
        ).scalar_one()
        unresolved.append({"kind": kind, "count": total, "message": reason})
    unresolved.append(
        {
            "kind": "supplier",
            "count": None,
            "message": "供方关系仅含明确引用及具名补录；其他物料供方文本不能推断为影响关系",
        }
    )
    unresolved.append(
        {
            "kind": "baseline",
            "count": None,
            "message": "未纳入人工核对范围或专业资料的对象，没有分析时完整快照，不能推断版本未变化",
        }
    )
    graph = {
        "nodes": sorted(nodes.values(), key=lambda n: n["key"]),
        "edges": sorted(edges.values(), key=lambda e: (e["source"], e["target"], e["label"])),
    }
    return {
        **graph,
        "digest": digest(graph),
        "as_of": datetime.now(UTC).isoformat(),
        "depth": depth,
        "limits": sorted(limits),
        "gaps": gaps,
        "unresolved": unresolved,
        "professional_comparisons": comparisons,
        "scope_comparisons": scope_comparisons,
        "scope_revision": scope["version"]["revision_number"] if scope else None,
        "analyzed_scope_revision": approved_scope["version"]["revision_number"]
        if approved_scope
        else None,
        "analysis_state": ecr["status"],
        "approved_at": _plain({"value": ecr["approved_at"]})["value"],
        "semantics": (
            "实际引用关系用于核对潜在影响；邻接、历史通过和条目计数均不是复验完成或批准结论。"
        ),
    }
