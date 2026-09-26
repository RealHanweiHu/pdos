"""Actual, scope-related professional evidence; missing disciplines remain explicit."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, exists, or_, select

from app.db.schema import tables
from app.domain.living_fmea import current_sources
from app.domain.product_workspace import _plain, digest

VERSION = "change-professional-projections-v1"
SEATS = {
    "id_designer": "ID 设计",
    "firmware_engineer": "固件 / 联调",
    "structure_engineer": "结构 / 接口",
    "hardware_engineer": "硬件 / 替代",
    "dqe": "DQE / 设计品质",
    "sqe": "SQE / 供方品质",
    "ie": "IE / 工艺与工装",
    "project_manager": "项目经理 / 正式计划",
}
LIMIT = 30


PUBLIC_FIELDS = frozenset(
    {
        "id",
        "code",
        "ncr_id",
        "issue_id",
        "origin",
        "reason",
        "created_at",
        "updated_at",
        "nonconformity",
        "requirement_reference",
        "severity",
        "status",
        "target_date",
        "containment_action",
        "containment_completed_at",
        "affected_quantity",
        "affected_scope",
        "preventive_not_applicable_reason",
        "preventive_disposition_approved_at",
        "effectiveness_criteria",
        "observation_due_at",
        "closed_at",
        "version",
        "method",
        "analysis",
        "root_cause",
        "evidence_refs",
        "approved_at",
        "superseded_at",
        "action_type",
        "description",
        "due_date",
        "completion_summary",
        "started_at",
        "completed_at",
        "review_number",
        "criteria",
        "actual_result",
        "result",
        "reviewed_at",
        "variant_id",
        "previous_revision_id",
        "brief",
        "envelope",
        "cmf",
        "layout",
        "interfaces",
        "document_id",
        "external_file_reference_id",
        "artifact_snapshot",
        "payload_digest",
        "revision_id",
        "source_kind",
        "source_reference",
        "reported_at",
        "topic",
        "content",
        "approved_root_cause",
        "latest_effectiveness_review",
        "ncr",
    }
)


def public_fields(row: Any) -> dict[str, Any]:
    result = {k: v for k, v in dict(row).items() if k in PUBLIC_FIELDS}
    for key in ("approved_root_cause", "latest_effectiveness_review", "ncr"):
        if result.get(key):
            result[key] = public_fields(result[key])
    return _plain(result)


def collect(
    c: Connection,
    tenant: UUID,
    project: UUID,
    ecr_id: UUID,
    graph: dict[str, Any],
    professional: dict[str, Any] | None,
    schedule: dict[str, Any],
) -> dict[str, Any]:
    refs: list[dict[str, Any]] = []
    assignments: dict[str, set[str]] = {key: set() for key in SEATS}
    gaps: dict[str, list[str]] = {key: [] for key in SEATS}
    coverage: dict[str, Any] = {}
    shared = ["ecr:" + str(ecr_id), "analysis-comparisons:" + str(ecr_id)]

    def add(key: str, label: str, fields: dict[str, Any], seats: tuple[str, ...]) -> None:
        fields = _plain(fields)
        refs.append(
            {
                "reference_id": key,
                "category": "professional_evidence",
                "label": label,
                "fields": fields,
                "source_digest": digest(fields),
            }
        )
        for seat in seats:
            assignments[seat].add(key)

    by_kind: dict[str, set[str]] = {}
    for node in graph["nodes"]:
        by_kind.setdefault(node["kind"], set()).add(node["key"])
    for seat, kinds in {
        "firmware_engineer": ("configuration", "sample", "test_run"),
        "structure_engineer": ("specification", "bom", "bom_item", "configuration"),
        "hardware_engineer": ("specification", "bom", "bom_item", "configuration"),
        "dqe": ("test_case", "test_run", "certification", "issue"),
        "sqe": ("supplier", "bom_item"),
        "ie": ("build", "bom", "configuration"),
    }.items():
        for kind in kinds:
            assignments[seat].update(by_kind.get(kind, set()))
    for entry in professional["sources"] if professional else []:
        source = entry["source"]
        kind = source["snapshot"].get("kind")
        seats = (
            ("structure_engineer", "hardware_engineer", "dqe", "sqe", "ie", "project_manager")
            if entry["kind"] == "cost_alternative"
            else ("firmware_engineer",)
            if entry["kind"] == "firmware_package"
            else (
                ("structure_engineer",)
                if kind == "mechanical_interface"
                else ("hardware_engineer",)
                if kind == "hardware_substitution"
                else ("structure_engineer", "hardware_engineer")
            )
        )
        for seat in seats:
            assignments[seat].add("professional:" + source["id"])
            assignments[seat].update(
                "professional-line:" + source["id"] + ":" + str(i)
                for i in range(len(source["snapshot"].get("lines", [])))
            )
            if not entry["ready"]:
                gaps[seat].append("已关联专业工作包的版本或出处变化，原意见需要重新核对")
    assignments["project_manager"].update(r["reference_id"] for r in schedule["references"])
    gaps["project_manager"].extend(schedule["gaps"])
    coverage["formal_baseline_available"] = bool(
        schedule["references"][0]["fields"].get("baseline_id")
    )

    link = tables.id_design_change_decisions
    id_rows = (
        c.execute(
            select(link)
            .where(
                link.c.tenant_id == tenant,
                link.c.project_id == project,
                link.c.ecr_id == ecr_id,
                link.c.action == "route_ecr",
            )
            .order_by(link.c.id)
            .limit(LIMIT + 1)
        )
        .mappings()
        .all()
    )
    from app.domain.id_design_activation import active_freeze_ids

    active = active_freeze_ids(c, tenant, project) if id_rows else set()
    for row in id_rows[:LIMIT]:
        value = row["snapshot"]
        current = UUID(value["freeze"]["id"]) in active
        for kind in ("frozen_revision", "feedback_revision", "feedback"):
            add(
                f"id-change:{row['id']}:{kind}",
                "ID 冻结方案与反馈 · " + kind,
                {
                    "source_kind": kind,
                    "freeze_id": value["freeze"]["id"],
                    "freeze_is_current": current,
                    "routing_reason": row["reason"],
                    **public_fields(value[kind]),
                },
                ("id_designer",),
            )
        if not current:
            gaps["id_designer"].append("原 ID 冻结已有替代，须按当前冻结核对变更来源")
    if not id_rows:
        gaps["id_designer"].append("本次变更尚未关联具名转入的 ID 冻结方案及反馈")
    if len(id_rows) > LIMIT:
        gaps["id_designer"].append("ID 来源超过本次读取上限，保留未覆盖范围")

    # Only actual Issue→NCR relations qualify; unrelated project NCRs do not enter this change.
    issue_ids = [UUID(n["id"]) for n in graph["nodes"] if n["kind"] == "issue"]
    q, retract = tables.quality_issue_links, tables.quality_issue_link_retractions
    linked = (
        c.execute(
            select(q)
            .where(
                q.c.tenant_id == tenant,
                q.c.project_id == project,
                q.c.issue_id.in_(issue_ids),
                ~exists().where(
                    retract.c.tenant_id == tenant,
                    retract.c.project_id == project,
                    retract.c.link_id == q.c.id,
                ),
            )
            .order_by(q.c.id)
            .limit(LIMIT + 1)
        )
        .mappings()
        .all()
        if issue_ids
        else []
    )
    ncr_ids = {row["ncr_id"] for row in linked[:LIMIT]}
    for row in linked[:LIMIT]:
        add(
            "quality-link:" + str(row["id"]),
            "原问题与 NCR 的具名关联",
            public_fields(row),
            ("dqe",),
        )
    if len(linked) > LIMIT:
        gaps["dqe"].append("问题与 NCR 关联超过本次读取上限，未全量覆盖")
    if not ncr_ids:
        gaps["dqe"].append("本次影响对象尚无有效 Issue→NCR 关联，不能推断无质量风险")
    for table, kind, label, field in (
        (tables.nonconformance_reports, "ncr", "关联 NCR 当前状态", "id"),
        (tables.root_cause_analyses, "root_cause", "关联根因版本与实际审批状态", "ncr_id"),
        (tables.capa_actions, "capa_action", "关联 CAPA 实际措施与状态", "ncr_id"),
        (tables.effectiveness_reviews, "effectiveness_review", "关联质量有效性记录", "ncr_id"),
    ):
        order = (
            table.c.version
            if kind == "root_cause"
            else table.c.review_number
            if kind == "effectiveness_review"
            else table.c.created_at
        )
        records = (
            c.execute(
                select(table)
                .where(
                    table.c.tenant_id == tenant,
                    table.c.project_id == project,
                    table.c[field].in_(ncr_ids),
                )
                .order_by(order.desc(), table.c.id)
                .limit(LIMIT + 1)
            )
            .mappings()
            .all()
            if ncr_ids
            else []
        )
        coverage[kind + "_included_count"] = min(len(records), LIMIT)
        for row in records[:LIMIT]:
            add(kind + ":" + str(row["id"]), label, public_fields(row), ("dqe",))
        if len(records) > LIMIT:
            gaps["dqe"].append(label + "超过本次读取上限，不能用已读记录替代全部历史")
        elif ncr_ids and not records:
            gaps["dqe"].append("关联 NCR 尚无" + label)

    # Latest publication is chosen before relevance filtering; never silently use a superseded FMEA.
    pub, version = tables.fmea_publications, tables.fmea_versions
    latest = (
        select(pub)
        .where(pub.c.tenant_id == tenant, pub.c.project_id == project)
        .distinct(pub.c.entry_id)
        .order_by(pub.c.entry_id, pub.c.published_at.desc(), pub.c.id.desc())
        .subquery()
    )
    targets = {(n["kind"], n["id"]) for n in graph["nodes"]}
    targets.update(("ncr", str(id)) for id in ncr_ids)
    filters = [
        version.c.body["references"].contains([{"kind": kind, "id": id}])
        for kind, id in sorted(targets)
    ]
    fmeas = (
        c.execute(
            select(version, latest.c.id.label("publication_id"), latest.c.published_at)
            .join(latest, latest.c.version_id == version.c.id)
            .where(version.c.tenant_id == tenant, version.c.project_id == project, or_(*filters))
            .order_by(version.c.entry_id)
            .limit(LIMIT + 1)
        )
        .mappings()
        .all()
        if filters
        else []
    )
    for row in fmeas[:LIMIT]:
        evaluated_sources, changed = current_sources(c, row)
        add(
            "fmea:" + str(row["id"]),
            "本次对象关联的已发布 FMEA · " + row["body"]["title"],
            {
                "id": row["id"],
                "entry_id": row["entry_id"],
                "version": row["version"],
                "publication_id": row["publication_id"],
                "published_at": row["published_at"],
                "content": row["body"],
                "source_gaps": changed,
                "sources_current": not changed,
            },
            ("dqe",),
        )
        for i, source in enumerate(evaluated_sources):
            if source["kind"] in {"ncr", "capa_action"} and source["current_value"]:
                source = {**source, "current_value": public_fields(source["current_value"])}
            add(f"fmea-source:{row['id']}:{i}", "FMEA 原引用与当前核对", source, ("dqe",))
        if changed:
            gaps["dqe"].append("已发布 FMEA 的关联来源变化，需核对原评分与控制措施")
    if not fmeas:
        gaps["dqe"].append("尚无与本次对象显式关联的当前已发布 FMEA")
    if len(fmeas) > LIMIT:
        gaps["dqe"].append("关联 FMEA 超过本次读取上限，尚未覆盖全部失效模式")
    coverage["fmea_included_count"] = min(len(fmeas), LIMIT)
    gaps["sqe"].append("供方目录/物料引用不代表供方资格、来料表现或承认结果；尚缺对应品质证据")
    gaps["ie"].append("试制批次/BOM/配置不代表工艺能力；尚缺已关联的受控工艺、工装和节拍约束")
    for seat, label in (
        ("firmware_engineer", "固件工作包"),
        ("structure_engineer", "结构接口评审"),
        ("hardware_engineer", "硬件替代评审"),
    ):
        if not any(key.startswith("professional:") for key in assignments[seat]):
            gaps[seat].append("本次变更尚未关联" + label + "；通用配置不能替代专业结论")
    result = {
        "version": VERSION,
        "references": refs,
        "coverage": coverage,
        "seats": [
            {
                "key": key,
                "label": label,
                "shared_reference_ids": shared,
                "reference_ids": sorted(assignments[key]),
                "missing": sorted(set(gaps[key])),
            }
            for key, label in SEATS.items()
        ],
    }
    return {**result, "digest": digest(result)}


def project(actual: dict[str, Any], references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Freeze only references which actually survived the context's capacity limits."""
    available = {r["reference_id"]: r for r in references}
    result = []
    for seat in actual["seats"]:
        selected = [key for key in seat["reference_ids"] if key in available]
        missing = list(seat["missing"])
        omitted = [key for key in seat["reference_ids"] if key not in available]
        partial = [key for key in selected if available[key]["omitted_fields"]]
        if omitted:
            missing.append(f"本次容量限制未纳入 {len(omitted)} 份专业来源")
        if partial:
            missing.append(f"本次有 {len(partial)} 份专业来源仅含部分字段")
        result.append(
            {
                "key": seat["key"],
                "label": seat["label"],
                "reference_ids": selected,
                "shared_reference_ids": [
                    key for key in seat["shared_reference_ids"] if key in available
                ],
                "omitted_reference_count": len(omitted),
                "partial_reference_count": len(partial),
                "status": "missing_sources"
                if not selected
                else "partial"
                if missing
                else "available",
                "missing": missing,
            }
        )
    return result
