"""Human-scoped audit clauses and actual electronic approval evidence."""

from datetime import UTC, date, datetime
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import Connection, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Text
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError, _plain
from app.domain.quality_operations import authorize, evidence_value
from app.exports.definition_documents import value

VERSION = "internal-audit-evidence.v1"
EvidenceKind = Literal["gate", "ecn", "document"]


class AuditEvidence(Contract):
    kind: EvidenceKind
    id: UUID
    position: Text
    relevance: Text
    valid_until: date | None = None


class AuditClause(Contract):
    standard: str = Field(min_length=1, max_length=128)
    edition: str = Field(min_length=1, max_length=128)
    clause: str = Field(min_length=1, max_length=128)
    requirement: Text
    applicability: Literal["applicable", "not_applicable", "unconfirmed"]
    rationale: Text
    missing: str = Field(default="", max_length=2048)
    evidence: tuple[AuditEvidence, ...] = Field(default=(), max_length=10)

    @model_validator(mode="after")
    def explicit(self) -> Self:
        if (
            self.applicability != "not_applicable"
            and not self.evidence
            and not self.missing.strip()
        ):
            raise ValueError("缺少依据时须说明待补项")
        if len({(e.kind, e.id, e.position) for e in self.evidence}) != len(self.evidence):
            raise ValueError("同条款内同一证据位置不能重复")
        return self


class AuditOptions(Contract):
    kind: EvidenceKind
    search: str = Field(default="", max_length=128)
    before_id: UUID | None = None


def source_access(c: Connection, context: AuthContext, project: UUID, kind: EvidenceKind) -> None:
    authorize(c, context, project, Action.QUALITY_VIEW)
    authorize(
        c,
        context,
        project,
        {"gate": Action.GATE_VIEW, "ecn": Action.CHANGE_VIEW, "document": Action.QUALITY_VIEW}[
            kind
        ],
    )


def options(
    c: Connection, context: AuthContext, project: UUID, query: AuditOptions
) -> dict[str, Any]:
    source_access(c, context, project, query.kind)
    t = {
        "gate": tables.gates,
        "ecn": tables.engineering_change_notices,
        "document": tables.documents,
    }[query.kind]
    label = (
        t.c.filename
        if query.kind == "document"
        else t.c.name
        if query.kind == "gate"
        else t.c.title
    )
    columns = [t.c.id, label.label("title")]
    if query.kind != "document":
        columns.extend([t.c.code, t.c.status])
    else:
        columns.extend([t.c.sha256, t.c.classification])
    q = select(*columns).where(t.c.tenant_id == context.tenant.id, t.c.project_id == project)
    if query.search:
        q = q.where(label.icontains(query.search, autoescape=True))
    if query.before_id:
        q = q.where(t.c.id < query.before_id)
    rows = c.execute(q.order_by(t.c.id.desc()).limit(21)).mappings().all()
    return {
        "items": [_plain(v) for v in rows[:20]],
        "next_before_id": str(rows[19]["id"]) if len(rows) > 20 else None,
    }


def ecn_source(
    c: Connection, context: AuthContext, project: UUID, identity: UUID
) -> dict[str, Any]:
    from app.exports.project_report_sources import all_rows, scoped

    t = tables.engineering_change_notices
    row = c.execute(scoped(t, context, project).where(t.c.id == identity)).mappings().one_or_none()
    if row is None:
        raise ProductWorkError("ECN不存在或不属于此项目")
    t = tables.engineering_change_requests
    ecr = c.execute(scoped(t, context, project).where(t.c.id == row["ecr_id"])).mappings().one()
    # Only approval fields enter this template; internal impact and cost payloads stay at source.
    current = {
        "ecn": _plain(
            {
                k: row[k]
                for k in (
                    "id",
                    "code",
                    "title",
                    "ecr_id",
                    "status",
                    "created_by_user_id",
                    "created_at",
                    "effectivity_decision_id",
                    "effectivity_decided_by_user_id",
                    "effectivity_decided_at",
                    "released_bom_id",
                    "updated_at",
                )
            }
        ),
        "ecr": _plain(
            {
                k: ecr[k]
                for k in (
                    "id",
                    "code",
                    "title",
                    "status",
                    "requested_by_user_id",
                    "analyzed_by_user_id",
                    "analyzed_at",
                    "approved_by_user_id",
                    "approved_at",
                    "approval_decision_id",
                    "approval_note",
                    "cancelled_at",
                    "updated_at",
                )
            }
        ),
    }
    d = tables.decisions
    ids = [v for v in (ecr["approval_decision_id"], row["effectivity_decision_id"]) if v]
    decisions = all_rows(
        c, scoped(d, context, project).where(d.c.id.in_(ids)).order_by(d.c.created_at, d.c.id)
    )
    audit = tables.audit_log
    logs = all_rows(
        c,
        select(
            audit.c.id,
            audit.c.entity,
            audit.c.entity_id,
            audit.c.action,
            audit.c.timestamp,
            audit.c.actor_user_id,
            audit.c.before_snapshot,
            audit.c.after_snapshot,
        )
        .where(
            audit.c.tenant_id == context.tenant.id,
            audit.c.project_id == project,
            audit.c.entity_id.in_([identity, row["ecr_id"]]),
        )
        .order_by(audit.c.timestamp, audit.c.id),
    )
    allowed = {
        "id",
        "code",
        "title",
        "status",
        "approved_by_user_id",
        "approved_at",
        "approval_decision_id",
        "approval_note",
        "effectivity_decision_id",
        "effectivity_decided_by_user_id",
        "effectivity_decided_at",
        "cancelled_at",
    }
    for log in logs:
        for key in ("before_snapshot", "after_snapshot"):
            snap = log[key]
            log[key] = (
                {k: v for k, v in snap.items() if k in allowed} if isinstance(snap, dict) else None
            )
    warnings = []
    if row["status"] != "erp_handoff":
        warnings.append("ECN尚未处于有效执行状态，取消或未生效记录保留，不能作为已实施证明。")
    if ecr["status"] != "approved":
        warnings.append("原ECR当前不是已批准状态。")
    if len(decisions) != len(set(ids)) or not ids:
        warnings.append("批准/生效裁决存在缺项。")
    if not logs:
        warnings.append("未找到原办理审计；当前批准字段不能替代完整历史记录。")
    return {**current, "decisions": decisions, "approval_history": logs, "warnings": warnings}


def resolve(
    c: Connection, context: AuthContext, project: UUID, kind: EvidenceKind, identity: UUID
) -> dict[str, Any]:
    source_access(c, context, project, kind)
    if kind == "gate":
        from app.exports.project_report_sources import ReportScope, source

        report = source(c, context, project, ReportScope(kind="gate", object_id=identity))
        return {"actual": report["actual"], "warnings": report["warnings"]}
    if kind == "ecn":
        return ecn_source(c, context, project, identity)
    return {
        "document": evidence_value(c, context.tenant.id, project, "document", str(identity)),
        "warnings": [
            "文件仅固定原件编号、内容校验和人工定位；正文附件未打入本文件，须沿原件另行核对。"
        ],
    }


def prepare(
    c: Connection, context: AuthContext, project: UUID, clauses: tuple[AuditClause, ...]
) -> dict[str, Any]:
    refs: dict[tuple[str, UUID], dict[str, Any]] = {}
    matrix = []
    warnings = [
        "标准版本、条款和适用性由整理人明确填写；未自动判定适用体系、审核通过或认证有效。",
        "本包是内部审阅稿；实际业务签核与本次组包是不同记录，未作客户披露批准。",
        "未列条款不在本次核对范围；系统具名办理记录不冒充证书数字签名。",
    ]
    for index, clause in enumerate(clauses, 1):
        evidence = []
        for item in clause.evidence:
            key = (item.kind, item.id)
            if key not in refs:
                refs[key] = resolve(c, context, project, item.kind, item.id)
            expired = bool(item.valid_until and item.valid_until < datetime.now(UTC).date())
            if expired:
                warnings.append(f"条款 {index} 的依据已超过人工登记有效期，需补核。")
            evidence.append(
                {
                    **item.model_dump(mode="json"),
                    "expired": expired,
                    "source_key": f"{item.kind}:{item.id}",
                }
            )
        if clause.missing.strip():
            warnings.append(f"条款 {index} 待补：{clause.missing}")
        if clause.applicability == "unconfirmed":
            warnings.append(f"条款 {index} 适用性尚未确认。")
        matrix.append({**clause.model_dump(mode="json"), "evidence": evidence})
    sections = [("条款适用性、证据对应与缺项", value(matrix))]
    sources = []
    for (kind, identity), body in refs.items():
        sources.append({"kind": kind, "id": str(identity), "record": body})
        sections.append((f"原依据 {kind}:{identity}", value(body)))
        warnings.extend(body.get("warnings", []))
    return {
        "clauses": matrix,
        "sources": sources,
        "warnings": list(dict.fromkeys(warnings)),
        "sections": sections,
    }
