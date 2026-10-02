"""Versioned, project-scoped business evidence checked during handoff acceptance."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Table, select

from app.db.schema import tables
from app.domain.product_workspace import _plain, digest

SOURCE_VERSION = "handoff-business-sources-v2"
# Include current records and immutable execution/revision history. A count alone
# cannot detect a replaced result or a changed source with the same row count.
SOURCE_GROUPS: dict[str, tuple[tuple[str, str, tuple[Table, ...]], ...]] = {
    "configuration": (
        ("规格与样机配置", "engineering", (tables.specifications,)),
        (
            "样机配置及修订",
            "quality",
            (tables.sample_build_configurations, tables.sample_configuration_revisions),
        ),
    ),
    "bom": (
        ("BOM与物料版本", "engineering", (tables.development_boms, tables.development_bom_items)),
    ),
    "manufacturing": (
        (
            "工装轮次与具名修订",
            "materials",
            (tables.tooling_rounds, tables.tooling_round_revisions),
        ),
        ("试制批次", "quality", (tables.build_batches,)),
    ),
    "test_certification": (
        (
            "测试用例、报告与逐次实测",
            "quality",
            (tables.test_cases, tables.test_reports, tables.test_runs),
        ),
        (
            "认证与实际办理",
            "quality",
            (tables.certifications, tables.certification_execution_actions),
        ),
    ),
    "residuals": (("问题与风险处置", "work-items", (tables.issues, tables.risks)),),
    "quality_follow_up": (
        ("投诉与不合格调查", "quality", (tables.complaints, tables.nonconformance_reports)),
        (
            "根因、整改与有效性复核",
            "quality",
            (tables.root_cause_analyses, tables.capa_actions, tables.effectiveness_reviews),
        ),
    ),
}


def source_manifest(
    connection: Connection, tenant: UUID, project: UUID, key: str
) -> dict[str, Any]:
    groups = []
    for index, (label, tab, source_tables) in enumerate(SOURCE_GROUPS.get(key, ())):
        records = {}
        for table in source_tables:
            records[table.name] = [
                _plain(row)
                for row in connection.execute(
                    select(table)
                    .where(table.c.tenant_id == tenant, table.c.project_id == project)
                    .where(*([table.c.withdrawn_at.is_(None)] if table is tables.issues else []))
                    .order_by(table.c.id)
                ).mappings()
            ]
        groups.append(
            {
                "key": f"{key}:{index}",
                "label": label,
                "tab": tab,
                "count": sum(len(rows) for rows in records.values()),
                "digest": digest(records),
            }
        )
    return {"version": SOURCE_VERSION, "groups": groups}


def accepted_source_manifest(
    connection: Connection, tenant: UUID, project: UUID, key: str, item: Any
) -> dict[str, Any] | None:
    if item is None or item["status"] != "accepted":
        return None
    audit = tables.audit_log
    context = connection.execute(
        select(audit.c.context)
        .where(
            audit.c.tenant_id == tenant,
            audit.c.project_id == project,
            audit.c.action == "project.handoff.accept",
            audit.c.after_snapshot["item_key"].as_string() == key,
            audit.c.after_snapshot["accepted_fingerprint"].as_string()
            == item["accepted_fingerprint"],
        )
        .order_by(audit.c.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    details = context.get("handoff_details", {}) if isinstance(context, dict) else {}
    manifest = details.get("business_sources") if isinstance(details, dict) else None
    return (
        manifest
        if isinstance(manifest, dict) and manifest.get("version") == SOURCE_VERSION
        else None
    )


def source_review(current: dict[str, Any], accepted: dict[str, Any] | None) -> list[dict[str, Any]]:
    previous = {row["key"]: row for row in accepted["groups"]} if accepted else {}
    return [
        {
            **row,
            "accepted_count": previous[row["key"]]["count"] if row["key"] in previous else None,
            "changed": row["digest"] != previous[row["key"]]["digest"]
            if row["key"] in previous
            else None,
        }
        for row in current["groups"]
    ]
