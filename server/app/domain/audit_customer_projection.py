"""Explicit customer audit disclosure, separate from the internal evidence package."""

from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any, Self
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import Connection, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.audit_report_bundles import MAX_FILE, MAX_INPUT, document_access, report
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.quality_operations import authorize
from app.exports.audit_report_sources import source_access
from app.exports.weekly_report_text import moment

VERSION = "customer-audit-evidence.v1"


class ClauseDisclosure(Contract):
    clause_number: int = Field(ge=1, le=30)
    customer_requirement: Text
    customer_statement: Text
    customer_gap: str = Field(default="", max_length=2048)
    include_signature_summary: bool = False


class DocumentDisclosure(Contract):
    source_document_id: UUID
    document_id: UUID
    public_filename: str = Field(min_length=1, max_length=128, pattern=r"^[^/\\\x00-\x1f]+$")
    review_basis: Text

    @model_validator(mode="after")
    def filename(self) -> Self:
        if (
            self.public_filename in {".", ".."}
            or self.public_filename.endswith((".", " "))
            or any(char in self.public_filename for char in ':*?"<>|')
        ):
            raise ValueError("请填写有效的客户可见文件名")
        return self


class AuditPackageDraft(Contract):
    customer_id: UUID
    title: str = Field(min_length=1, max_length=256)
    audit_report_id: UUID
    clauses: tuple[ClauseDisclosure, ...] = Field(min_length=1, max_length=30)
    documents: tuple[DocumentDisclosure, ...] = Field(default=(), max_length=30)
    internal_reason: Text

    @model_validator(mode="after")
    def unique(self) -> Self:
        if len({c.clause_number for c in self.clauses}) != len(self.clauses):
            raise ValueError("条款不能重复")
        if len({d.document_id for d in self.documents}) != len(self.documents):
            raise ValueError("同一客户文件只需选择一次")
        return self


class AuditPackageSave(AuditPackageDraft):
    request_id: UUID
    expected_digest: Digest


class AuditDisclosureOptions(Contract):
    audit_report_id: UUID


def access(c: Connection, context: AuthContext, project: UUID, draft: AuditPackageDraft) -> None:
    authorize(c, context, project, Action.QUALITY_VIEW)
    t = tables.project_report_exports
    scope = c.execute(
        select(t.c.scope).where(
            t.c.tenant_id == context.tenant.id,
            t.c.project_id == project,
            t.c.id == draft.audit_report_id,
            t.c.kind == "audit",
        )
    ).scalar_one_or_none()
    if scope is None:
        raise ProductWorkError("原审核报告不可读取")
    for kind in {r["kind"] for clause in scope["audit_clauses"] for r in clause["evidence"]}:
        source_access(c, context, project, kind)
    if draft.documents:
        document_access(c, context, project)


def signature_summary(kind: str, record: dict[str, Any]) -> dict[str, Any] | None:
    if kind == "gate":
        data = record["actual"]
        rounds = data["rounds"]
        latest = max(rounds, key=lambda v: v["round_number"]) if rounds else None
        return {
            "type": "Gate",
            "reference": data["gate"]["code"],
            "status": data["gate"]["status"],
            "round": latest["round_number"] if latest else None,
            "signoffs": [
                {"specialty": s["slot"], "status": s["status"], "signed_at": s["signed_at"]}
                for s in data["signoffs"]
                if latest and s["round_id"] == latest["id"]
            ],
        }
    if kind == "ecn":
        return {
            "type": "ECN",
            "reference": record["ecn"]["code"],
            "status": record["ecn"]["status"],
            "ecr_status": record["ecr"]["status"],
            "ecr_approved_at": record["ecr"]["approved_at"],
            "effectivity_decided_at": record["ecn"]["effectivity_decided_at"],
        }
    return None


def prepare(
    c: Connection, context: AuthContext, project: UUID, draft: AuditPackageDraft
) -> dict[str, Any]:
    from app.domain.customer_report_packages import customer

    access(c, context, project, draft)
    actual_customer = customer(c, context, project, draft.customer_id)
    original = report(c, context, project, draft.audit_report_id)
    clauses = original["scope"]["audit_clauses"]
    source_records = {
        (r["kind"], r["id"]): r["record"] for r in original["snapshot"]["actual"]["sources"]
    }
    public_clauses = []
    selected_document_ids = set()
    for item in draft.clauses:
        if item.clause_number > len(clauses):
            raise ProductWorkError("所选条款不在原报告范围")
        clause = clauses[item.clause_number - 1]
        expired = any(
            ref.get("valid_until") and ref["valid_until"] < datetime.now(UTC).date().isoformat()
            for ref in clause["evidence"]
        )
        if (
            clause["missing"] or clause["applicability"] == "unconfirmed" or expired
        ) and not item.customer_gap:
            raise ProductWorkError("原条款有缺项或适用性未知，须明确客户可见的待补说明")
        summaries = []
        for ref in clause["evidence"]:
            if ref["kind"] == "document":
                selected_document_ids.add(UUID(ref["id"]))
            if item.include_signature_summary:
                summary = signature_summary(ref["kind"], source_records[(ref["kind"], ref["id"])])
                if summary is not None and summary not in summaries:
                    summaries.append(summary)
        public_clauses.append(
            {
                "standard": clause["standard"],
                "edition": clause["edition"],
                "clause": clause["clause"],
                "requirement": item.customer_requirement,
                "statement": item.customer_statement,
                "applicability": clause["applicability"],
                "gap": item.customer_gap,
                "signature_summaries": summaries,
            }
        )
    public_documents, refs = [], []
    for index, document in enumerate(draft.documents, 1):
        if document.source_document_id not in selected_document_ids:
            raise ProductWorkError("客户文件须对应所选条款内实际原件；处理版另选本项目已上传文件")
        t = tables.documents
        row = (
            c.execute(
                select(
                    t.c.id,
                    t.c.filename,
                    t.c.sha256,
                    t.c.size_bytes,
                    t.c.media_type,
                    t.c.classification,
                ).where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.project_id == project,
                    t.c.id == document.document_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None or not 1 <= row["size_bytes"] <= MAX_FILE:
            raise ProductWorkError("客户文件不存在或超出20MiB单文件容量")
        if (
            PurePosixPath(document.public_filename).suffix.lower()
            != PurePosixPath(row["filename"]).suffix.lower()
        ):
            raise ProductWorkError("客户文件名须保留所选原件的实际扩展名")
        public_documents.append(
            {
                "filename": document.public_filename,
                "path": f"attachments/{index:02d}-{document.public_filename}",
                "sha256": row["sha256"],
                "size_bytes": row["size_bytes"],
                "media_type": row["media_type"],
            }
        )
        refs.append(
            {
                "document": _plain(row),
                "source_document_id": str(document.source_document_id),
                "review_basis": document.review_basis,
            }
        )
    if sum(d["size_bytes"] for d in public_documents) > MAX_INPUT - 12 * 1024 * 1024:
        raise ProductWorkError("客户附件合计超过38MiB，请缩小范围")
    projection = {
        "template_version": VERSION,
        "title": draft.title,
        "customer_name": actual_customer["name"],
        "audit_clauses": public_clauses,
        "documents": public_documents,
        "interpretation": (
            "本资料按所列条款与批准披露范围提供；未列范围未作覆盖确认。"
            "签核为原业务记录摘要，不代表认证、审核通过或全部整改已有效。"
        ),
    }
    body = {
        "draft": draft.model_dump(mode="json"),
        "customer_id": str(draft.customer_id),
        "projection": projection,
        "source_refs": {
            "audit_report_id": str(draft.audit_report_id),
            "report_digest": original["content_digest"],
            "source_digest": original["source_digest"],
            "documents": refs,
        },
    }
    return {**body, "digest": digest(body)}


def signature_text(summary: dict[str, Any]) -> str:
    states = {
        "hold": "暂缓",
        "approved": "通过",
        "rejected": "退回",
        "conditional": "有条件通过",
        "pending": "待办理",
        "preparing": "准备中",
        "reviewing": "评审中",
        "not_applicable": "不适用",
        "cancelled": "已取消",
        "draft": "草稿",
        "erp_handoff": "已转执行",
    }
    slots = {"product": "产品", "engineering": "工程", "quality": "品质"}
    status = states.get(summary["status"], summary["status"])
    head = f"{summary['type']} · {summary['reference']}\n原状态：{status}"
    if summary["type"] == "Gate":
        head += f"\n原轮次：{summary['round'] if summary['round'] is not None else '未记录'}"
        signs = summary["signoffs"]
        return (
            head
            + "\n"
            + (
                "\n".join(
                    f"{slots.get(s['specialty'], s['specialty'])}席："
                    f"{states.get(s['status'], s['status'])}；"
                    f"签核时间：{moment(s['signed_at'])}"
                    for s in signs
                )
                or "未记录本轮签核，不推定通过。"
            )
        )
    return (
        head
        + f"\n原ECR状态：{states.get(summary['ecr_status'], summary['ecr_status'])}\n"
        + (
            f"ECR批准时间：{moment(summary['ecr_approved_at'])}\n"
            f"ECN生效裁决时间：{moment(summary['effectivity_decided_at'])}"
        )
    )


def sections(projection: dict[str, Any]) -> list[tuple[str, str]]:
    result = [("客户", projection["customer_name"])]
    for item in projection["audit_clauses"]:
        label = f"{item['standard']} · {item['edition']} · {item['clause']}"
        applicability = {"applicable": "适用", "not_applicable": "不适用", "unconfirmed": "待确认"}[
            item["applicability"]
        ]
        result.append(
            (
                label,
                f"核对要求：{item['requirement']}\n适用性：{applicability}\n"
                f"说明：{item['statement']}\n待补说明：{item['gap'] or '未声明其他待补项'}",
            )
        )
        if item["signature_summaries"]:
            result.append(
                (
                    label + " · 原签核摘要",
                    "\n\n".join(signature_text(summary) for summary in item["signature_summaries"]),
                )
            )
    if projection["documents"]:
        result.append(
            (
                "获准附件清单（完整文件见同一批准版ZIP）",
                "\n\n".join(
                    f"{d['filename']} · {d['size_bytes']} 字节\n"
                    f"包内位置：{d['path']}\n校验：{d['sha256']}"
                    for d in projection["documents"]
                ),
            )
        )
    result.append(("适用说明", projection["interpretation"]))
    return result
