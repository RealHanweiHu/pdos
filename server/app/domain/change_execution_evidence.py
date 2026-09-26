"""Actual execution evidence and comparison with fixed approved source versions."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import Connection

from app.db.schema import tables
from app.domain.change_impact_scope import source
from app.domain.firmware_task_results import _run
from app.domain.firmware_work_packages import FirmwarePackageError
from app.domain.product_workspace import ProductWorkError, digest
from app.domain.professional_change_routes import source_basis

EvidenceKind = Literal["test_run", "engineering_review", "certification", "document"]
EVIDENCE_TABLES = {
    "test_run": tables.test_runs,
    "engineering_review": tables.engineering_review_packages,
    "certification": tables.certifications,
    "document": tables.documents,
}
# Runtime progress can legitimately evolve while executing the approved requirements.
# Design, configuration, scope and document-content changes remain blocking differences.
PROGRESS_FIELDS = {
    "test_case": {"status", "result_notes", "executed_by_user_id", "executed_at"},
    "test_run": {
        "status",
        "draft_state",
        "conditions",
        "metrics",
        "equipment",
        "environment",
        "result_notes",
        "started_at",
        "expected_completion_at",
        "executed_at",
        "operator_user_id",
        "evidence_document_id",
        "execution_time_precision",
        "execution_time_source",
        "test_preparation_id",
    },
    "certification": {
        "status",
        "valid_from",
        "valid_until",
        "evidence_reference",
        "certificate_number",
        "started_at",
        "completed_at",
    },
    "issue": {
        "status",
        "root_cause",
        "resolution",
        "closure_evidence_ref",
        "closed_at",
        "reopen_count",
    },
    "sample": {"status"},
    "build": {"status", "completed_quantity", "started_at", "completed_at"},
}


def scope_changes(
    c: Connection, tenant_id: UUID, project_id: UUID, approved: dict[str, Any]
) -> list[dict[str, Any]]:
    refs = {(i["kind"], i["id"]): i["snapshot"] for i in approved["version"]["snapshot"]["items"]}
    refs.update(
        {
            ("document", e["evidence_document_id"]): e["evidence_snapshot"]
            for e in approved["version"]["snapshot"]["edges"]
        }
    )
    changes = []
    for (kind, id), before in sorted(refs.items()):
        try:
            current = source(c, tenant_id, project_id, kind, UUID(id))
        except ProductWorkError:
            current = None
        fields = sorted(
            k for k in set(before) | set(current or {}) if before.get(k) != (current or {}).get(k)
        )
        ignored = PROGRESS_FIELDS.get(kind, set()) | {"updated_at"}
        if kind == "test_run" and before.get("sample_configuration_revision_id") is None:
            ignored = ignored | {"sample_configuration_revision_id"}
        changed_scope = current is None or any(k not in ignored for k in fields)
        if fields or current is None:
            changes.append(
                {
                    "kind": kind,
                    "id": id,
                    "fields": fields,
                    "blocking": changed_scope,
                    "before": before,
                    "current": current,
                }
            )
    return changes


def read_evidence(
    c: Connection, tenant_id: UUID, project_id: UUID, kind: EvidenceKind, id: UUID
) -> dict[str, Any]:
    if kind == "engineering_review":
        return source_basis(c, tenant_id, project_id, "engineering_review", id)
    if kind == "test_run":
        try:
            value = _run(c, tenant_id, project_id, id)
        except FirmwarePackageError as error:
            raise ProductWorkError("原测试证据不可用") from error
        value["sample_record"] = (
            source(c, tenant_id, project_id, "sample", UUID(value["sample_id"]))
            if value["sample_id"]
            else None
        )
        return value
    return source(c, tenant_id, project_id, kind, id)


def assess(
    kind: EvidenceKind, value: dict[str, Any], item: dict[str, Any], approved_at: str
) -> dict[str, Any]:
    gaps = []
    correspondence = "manual_review"
    scope_kind, scope_id = item["kind"], item["id"]
    approved_day = datetime.fromisoformat(approved_at).date()
    if kind == "test_run":
        if value["draft_state"] != "confirmed" or value["status"] != "passed":
            gaps.append("逐次测试须已确认且实际通过")
        if not value.get("evidence"):
            gaps.append("缺少原报告文件")
        if not value.get("sample_configuration_revision_id") or not value.get("sample_id"):
            gaps.append("缺少实际样机与当次配置")
        if (
            value.get("execution_time_precision") not in {"day", "instant"}
            or value.get("execution_time_source") in {"legacy_unknown", "system_completion"}
            or not value.get("executed_at")
        ):
            gaps.append("真实测试日期未明确")
        elif datetime.fromisoformat(value["executed_at"]).date() < approved_day:
            gaps.append("测试早于本次批准，不能当作本次复验")
        if datetime.fromisoformat(value["created_at"]) < datetime.fromisoformat(approved_at):
            gaps.append("测试记录早于本次批准，请关联本次实际复验记录")
        method = value.get("verification_basis") or {}
        if (
            not (method.get("method") or "").strip()
            or not (method.get("acceptance_criteria") or "").strip()
        ):
            gaps.append("测试方法与判据不完整")
        sample = value.get("sample_record") or {}
        configuration = (value.get("configuration") or {}).get("snapshot") or {}
        match = {
            "test_case": value["test_case_id"],
            "specification": method.get("specification_id"),
            "sample": value.get("sample_id"),
            "configuration": value.get("sample_configuration_revision_id"),
            "bom": configuration.get("development_bom_id"),
            "build": sample.get("build_batch_id"),
        }
        if scope_kind in match:
            correspondence = "matched" if match[scope_kind] == scope_id else "mismatch"
        elif scope_kind == "test_run":
            correspondence = (
                "matched"
                if item["snapshot"]["test_case_id"] == value["test_case_id"]
                else "mismatch"
            )
        elif scope_kind == "bom_item":
            correspondence = (
                "matched"
                if item["snapshot"]["bom_id"] == configuration.get("development_bom_id")
                else "mismatch"
            )
        if scope_kind == "bom" and configuration.get("bom_version") != item["snapshot"].get(
            "version"
        ):
            gaps.append("当次配置BOM版本与获批对象版本不一致")
    elif kind == "engineering_review":
        record = value["source"]
        if not value["ready"]:
            gaps.append("专业复审不是当前有效版本，或原引用已变化")
        if datetime.fromisoformat(record["created_at"]) < datetime.fromisoformat(approved_at):
            gaps.append("复审资料早于本次批准")
        if any(line["verdict"] == "unknown" for line in record["snapshot"]["lines"]):
            gaps.append("专业复审仍有兼容性未知项")
        if scope_kind in {"bom_item", "specification", "document"}:
            correspondence = (
                "matched"
                if any(
                    r["kind"] == scope_kind and r["id"] == scope_id
                    for r in record["snapshot"]["sources"]
                )
                else "mismatch"
            )
    elif kind == "certification":
        today = datetime.now(UTC).date()
        if (
            value["status"] != "valid"
            or not value.get("evidence_reference")
            or not value.get("certificate_number")
        ):
            gaps.append("认证尚未有效或缺少证书编号/证据")
        if value.get("valid_from") and date.fromisoformat(value["valid_from"]) > today:
            gaps.append("证书尚未到生效日期")
        if not value.get("valid_until") or date.fromisoformat(value["valid_until"]) < today:
            gaps.append("证书有效期限未知或已到期")
        if (
            not value.get("completed_at")
            or datetime.fromisoformat(value["completed_at"]).date() < approved_day
        ):
            gaps.append("缺少本次批准后的实际认证完成时间")
        if scope_kind == "certification":
            correspondence = (
                "matched"
                if value.get("replaces_certification_id") == scope_id
                or (value["id"] == scope_id and item["snapshot"]["status"] == "draft")
                else "mismatch"
            )
    if correspondence == "mismatch":
        gaps.append("证据与本条获批对象的明确关联不一致")
    return {
        "eligible": not gaps,
        "gaps": gaps,
        "correspondence": correspondence,
        "digest": digest(value),
    }


def performers(refs: list[dict[str, Any]]) -> set[str]:
    actors = set()
    for ref in refs:
        if ref["role"] != "verification":
            continue
        value = ref["snapshot"]
        actor = (
            value.get("operator_user_id")
            if ref["kind"] == "test_run"
            else value.get("source", {}).get("created_by_user_id")
            if ref["kind"] == "engineering_review"
            else value.get("owner_user_id")
            if ref["kind"] == "certification"
            else None
        )
        if actor:
            actors.add(actor)
    return actors
