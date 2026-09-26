"""Bounded actual NCR inputs and exact citations for quality.prepare_capa."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, exists, select

from app.ai.executor import PromptFile
from app.contracts.quality_work_package import QualityAssessment
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.quality_operations import Evidence, evidence_value, state

CONTEXT_VERSION = "quality-work-package-context-v1"
RUN_VERSION = "quality-work-package-request-v1"
PROMPT = PromptFile.model_validate_json(
    (Path(__file__).with_name("prompts") / "quality_work_package_v1.json").read_text()
)


def encoded(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def source_state(
    c: Connection, tenant: UUID, project: UUID, ncr_id: UUID, selections: list[Evidence]
) -> dict[str, Any]:
    if len({(s.kind, s.reference) for s in selections}) != len(selections) or len(selections) > 50:
        raise ProductWorkError("原始证据须去重且不超过 50 项")
    actual = state(c, tenant, project, ncr_id)
    if actual["ncr"]["status"] not in {"root_cause", "action"}:
        raise ProductWorkError("请在根因调查或措施执行阶段准备品质工作包")
    phase = "investigation" if actual["ncr"]["status"] == "root_cause" else "actions"
    if phase == "actions" and not any(r["status"] == "approved" for r in actual["root_causes"]):
        raise ProductWorkError("措施方案需要实际获批的根因依据")
    records: list[tuple[str, str, dict[str, Any]]] = [
        ("ncr:" + str(ncr_id), "原 NCR", actual["ncr"])
    ]
    for key, kind, label in [
        ("root_causes", "root_cause", "原根因版本"),
        ("actions", "capa_action", "实际整改措施"),
        ("reviews", "effectiveness_review", "独立有效性记录"),
    ]:
        records.extend((f"{kind}:{r['id']}", label, r) for r in actual[key])
    link, retract = tables.quality_issue_links, tables.quality_issue_link_retractions
    issues = (
        c.execute(
            select(tables.issues)
            .join(link, link.c.issue_id == tables.issues.c.id)
            .where(
                link.c.tenant_id == tenant,
                link.c.project_id == project,
                link.c.ncr_id == ncr_id,
                ~exists().where(retract.c.link_id == link.c.id),
            )
            .order_by(tables.issues.c.id)
        )
        .mappings()
        .all()
    )
    actual["issues"] = [_plain(dict(r)) for r in issues]
    records.extend((f"issue:{r['id']}", "显式关联的原问题", r) for r in actual["issues"])
    app, work = tables.quality_work_package_applications, tables.quality_work_package_items
    tasks = (
        c.execute(
            select(tables.tasks)
            .join(work, work.c.task_id == tables.tasks.c.id)
            .join(app, app.c.id == work.c.application_id)
            .where(app.c.tenant_id == tenant, app.c.project_id == project, app.c.ncr_id == ncr_id)
            .order_by(tables.tasks.c.id)
        )
        .mappings()
        .all()
    )
    actual["investigation_tasks"] = [_plain(dict(r)) for r in tasks]
    records.extend(
        (f"task:{r['id']}", "已登记调查任务及实际进展", r) for r in actual["investigation_tasks"]
    )
    source_values = []
    for selection in selections:
        value = evidence_value(c, tenant, project, selection.kind, selection.reference)
        if digest(value) != selection.expected_digest:
            raise ProductWorkError("原证据已有变化，请重新核对再准备")
        if selection.kind == "document" and value.get("classification") != "internal":
            raise ProductWorkError("当前品质准备仅使用内部项目文件")
        source_values.append({**selection.model_dump(mode="json"), "value": value})
        records.append((f"{selection.kind}:{selection.reference}", "人员选定的原始证据", value))
    basis = {"ncr_id": str(ncr_id), "phase": phase, "state": actual, "source_values": source_values}
    refs: list[dict[str, Any]] = []
    omitted: list[str] = []
    size = 0
    for identity, label, value in records:
        fields: dict[str, Any] = {}
        omitted_fields = []
        for key, item in value.items():
            if len(encoded({**fields, key: item})) <= 12000:
                fields[key] = item
            else:
                omitted_fields.append(key)
        ref = {
            "reference_id": identity,
            "label": label,
            "digest": digest(value),
            "fields": fields,
            "omitted_fields": omitted_fields,
        }
        if size + len(encoded(ref)) > 160000:
            omitted.append(identity)
        else:
            size += len(encoded(ref))
            refs.append(ref)
    return {
        **basis,
        "digest": digest(basis),
        "context_version": CONTEXT_VERSION,
        "model_context": {
            "phase": phase,
            "references": refs,
            "omitted_references": omitted,
            "question": (
                "按当前 NCR 阶段提出有原字段引用的调查或纠正预防工作，并明确未知与覆盖限制。"
            ),
        },
    }


def validate_assessment(output: QualityAssessment, snapshot: dict[str, Any]) -> None:
    if output.phase != snapshot["phase"]:
        raise ProductWorkError("专业候选与实际 NCR 阶段不一致")
    references = {r["reference_id"]: r for r in snapshot["model_context"]["references"]}
    approved_roots = {
        f"root_cause:{r['id']}"
        for r in snapshot["state"]["root_causes"]
        if r["status"] == "approved"
    }
    if output.phase == "actions" and any(
        not any(c.reference_id in approved_roots for c in work.basis.citations)
        for work in output.work
    ):
        raise ProductWorkError("纠正预防措施须引用本次实际获批根因，不能以问题描述代替")
    statements = [*output.observations, *output.hypotheses, *(w.basis for w in output.work)]
    if output.verification:
        statements.append(output.verification.basis)
    for statement in statements:
        for citation in statement.citations:
            ref = references.get(citation.reference_id)
            if ref is None or ref["digest"] != citation.digest:
                raise ProductWorkError("引用不属于本次读取的原资料版本")
            current: Any = ref["fields"]
            for part in citation.field_path:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                elif isinstance(current, list) and part.isdecimal() and int(part) < len(current):
                    current = current[int(part)]
                else:
                    raise ProductWorkError("引用字段未包含在本次原资料中")
            if citation.quoted_value != (current if isinstance(current, str) else encoded(current)):
                raise ProductWorkError("引用摘录与实际字段不一致")
