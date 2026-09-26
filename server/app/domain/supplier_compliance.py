"""Versioned market/regulation/evidence matrix; formal certification remains independent."""

from datetime import UTC, date, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.build_materials import BuildMaterialService
from app.domain.document_previews import document_row, metadata
from app.domain.npi_execution import NpiExecutionService
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.supplier_engineering import supplier_row


class ComplianceDraft(Contract):
    supplier_id: UUID | None = None
    market: str = Field(min_length=1, max_length=128)
    regulation: str = Field(min_length=1, max_length=256)
    regulation_version: str = Field(min_length=1, max_length=128)
    clause: Text
    product_conditions: Text
    early_constraints: Text
    assessment: Literal[
        "unknown", "evidence_pending", "reviewed_met", "reviewed_not_met", "not_applicable"
    ]
    regulation_evidence_id: UUID | None = None
    conclusion_evidence_id: UUID | None = None
    evidence_location: Text
    review_valid_until: date | None = None
    certification_ids: list[UUID] = Field(default_factory=list, max_length=20)
    build_ids: list[UUID] = Field(default_factory=list, max_length=20)
    sample_ids: list[UUID] = Field(default_factory=list, max_length=20)
    bom_item_ids: list[UUID] = Field(default_factory=list, max_length=20)
    specification_ids: list[UUID] = Field(default_factory=list, max_length=20)
    status: Literal["active", "withdrawn"] = "active"
    evidence_id: UUID
    reason: Text

    @model_validator(mode="after")
    def evidence_required(self) -> "ComplianceDraft":
        if not all(
            value.strip() for value in (self.market, self.regulation, self.regulation_version)
        ):
            raise ValueError("市场、法规和版本不能为空；尚未确定时请明确填写待核对")
        if self.assessment in {"reviewed_met", "reviewed_not_met", "not_applicable"} and not (
            self.regulation_evidence_id and self.conclusion_evidence_id
        ):
            raise ValueError("人工核对结论须具备法规原文和实际结论证据")
        for name in LINKS:
            ids = getattr(self, name)
            if len(ids) != len(set(ids)):
                raise ValueError("同一关联对象不能重复选择")
        return self


class ComplianceApply(ComplianceDraft):
    expected_version: int = Field(ge=0)
    expected_digest: Digest
    request_id: UUID


LINKS = {
    "certification_ids": tables.certifications,
    "build_ids": tables.build_batches,
    "sample_ids": tables.samples,
    "bom_item_ids": tables.development_bom_items,
    "specification_ids": tables.specifications,
}


def sources(c: Connection, tenant: UUID, project: UUID, command: ComplianceDraft) -> dict[str, Any]:
    result: dict[str, Any] = {
        "supplier": supplier_row(c, tenant, command.supplier_id) if command.supplier_id else None
    }
    for name in ("evidence_id", "regulation_evidence_id", "conclusion_evidence_id"):
        identity = getattr(command, name)
        result[name] = metadata(document_row(c, tenant, project, identity)) if identity else None
    for name, table in LINKS.items():
        result[name] = [
            _plain(
                dict(
                    NpiExecutionService._row(
                        c,
                        table,
                        tenant_id=tenant,
                        project_id=project,
                        record_id=identity,
                    )
                )
            )
            for identity in getattr(command, name)
        ]
    certificate_table = tables.certifications
    for certificate in result["certification_ids"]:
        certificate["valid_replacement_ids"] = [
            str(identity)
            for identity in c.execute(
                select(certificate_table.c.id).where(
                    certificate_table.c.tenant_id == tenant,
                    certificate_table.c.project_id == project,
                    certificate_table.c.replaces_certification_id == UUID(certificate["id"]),
                    certificate_table.c.status == "valid",
                )
            ).scalars()
        ]
    return result


def latest_query(tenant: UUID, project: UUID) -> Any:
    t = tables.supplier_compliance_records
    newer = t.alias("newer_compliance_record")
    return select(t).where(
        t.c.tenant_id == tenant,
        t.c.project_id == project,
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


def status(command: ComplianceDraft, actual: dict[str, Any], changed: bool) -> dict[str, Any]:
    reasons = []
    today = datetime.now(UTC).date()
    if changed:
        reasons.append("所关联供方、认证、送样、关键件或规格资料有变化，须重新核对")
    if command.review_valid_until and command.review_valid_until < today:
        reasons.append("本条人工核对有效期已过")
    for certificate in actual["certification_ids"]:
        until = (
            date.fromisoformat(certificate["valid_until"])
            if certificate.get("valid_until")
            else None
        )
        start = (
            date.fromisoformat(certificate["valid_from"]) if certificate.get("valid_from") else None
        )
        if certificate.get("valid_replacement_ids"):
            reasons.append(f"关联认证 {certificate['id']} 已有后续有效认证，请核对替代范围")
        if (
            certificate["status"] != "valid"
            or (until and until < today)
            or (start and start > today)
        ):
            reasons.append(f"关联认证 {certificate['id']} 尚未有效或已过期，需沿原认证流程确认")
        if command.market not in certificate.get("target_markets", []):
            reasons.append(f"关联认证 {certificate['id']} 未明确列出本条市场，适用范围须核对")
    for sample in actual["sample_ids"]:
        if str(sample["build_batch_id"]) not in {str(value) for value in command.build_ids}:
            reasons.append(f"样机 {sample['serial_number']} 的实际批次未纳入本条送样批次")
    return {
        "state": "withdrawn"
        if command.status == "withdrawn"
        else ("needs_review" if reasons else command.assessment),
        "reasons": reasons,
        "recorded_assessment": command.assessment,
    }


def preview(
    c: Connection, context: AuthContext, project: UUID, record: UUID, command: ComplianceDraft
) -> dict[str, Any]:
    BuildMaterialService._authorize(c, context, project, write=True)
    t = tables.supplier_compliance_records
    previous = (
        c.execute(latest_query(context.tenant.id, project).where(t.c.record_id == record))
        .mappings()
        .one_or_none()
    )
    if previous is None and command.status == "withdrawn":
        raise ProductWorkError("尚未登记的条目不能撤回")
    actual = sources(c, context.tenant.id, project, command)
    basis = {
        "sources": actual,
        "previous_version": previous["version"] if previous else 0,
        "command": command.model_dump(
            mode="json", exclude={"expected_version", "expected_digest", "request_id"}
        ),
    }
    return {
        "basis": basis,
        "digest": digest(basis),
        "current_status": status(command, actual, False),
    }


class SupplierComplianceService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(
        self,
        context: AuthContext,
        project: UUID,
        after: UUID | None = None,
        record: UUID | None = None,
        before_version: int | None = None,
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            BuildMaterialService._authorize(c, context, project)
            options: dict[str, Any] = {}
            for name, table in LINKS.items():
                options[name] = [
                    _plain(dict(row))
                    for row in c.execute(
                        select(table)
                        .where(
                            table.c.tenant_id == context.tenant.id,
                            table.c.project_id == project,
                        )
                        .order_by(table.c.created_at.desc())
                        .limit(200)
                    ).mappings()
                ]
            d, s, t = tables.documents, tables.suppliers, tables.supplier_compliance_records
            result: dict[str, Any] = {
                "options": options,
                "documents": [
                    _plain(dict(row))
                    for row in c.execute(
                        select(d.c.id, d.c.filename)
                        .where(
                            d.c.tenant_id == context.tenant.id,
                            d.c.project_id == project,
                        )
                        .order_by(d.c.created_at.desc())
                        .limit(200)
                    ).mappings()
                ],
                "suppliers": [
                    _plain(dict(row))
                    for row in c.execute(
                        select(s).where(s.c.tenant_id == context.tenant.id).order_by(s.c.code)
                    ).mappings()
                ],
                "history": [],
                "history_next_before": None,
            }
            query = latest_query(context.tenant.id, project)
            if record:
                query = query.where(t.c.record_id == record)
                history = select(t).where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.project_id == project,
                    t.c.record_id == record,
                )
                if before_version:
                    history = history.where(t.c.version < before_version)
                older = list(c.execute(history.order_by(t.c.version.desc()).limit(21)).mappings())
                result["history"] = [_plain(dict(row)) for row in older[:20]]
                result["history_next_before"] = older[19]["version"] if len(older) > 20 else None
            elif after:
                query = query.where(t.c.record_id > after)
            rows = list(c.execute(query.order_by(t.c.record_id).limit(21)).mappings())
            items = []
            for row in rows[:20]:
                value = _plain(dict(row))
                command = ComplianceDraft.model_validate(row["payload"])
                try:
                    actual = sources(c, context.tenant.id, project, command)
                    value["current_sources"] = actual
                    value["current_status"] = status(
                        command, actual, digest(actual) != digest(row["snapshot"]["sources"])
                    )
                except (LookupError, ValueError):
                    value["current_sources"] = None
                    value["current_status"] = {
                        "state": "withdrawn" if command.status == "withdrawn" else "needs_review",
                        "recorded_assessment": command.assessment,
                        "reasons": ["部分原资料已不可读取，保留历史来源并重新核对"],
                    }
                items.append(value)
            result["items"] = items
            result["next_cursor"] = str(rows[19]["record_id"]) if len(rows) > 20 else None
            return result

    def preview(
        self, context: AuthContext, project: UUID, record: UUID, command: ComplianceDraft
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            return preview(c, context, project, record, command)

    def apply(
        self, context: AuthContext, project: UUID, record: UUID, command: ComplianceApply
    ) -> dict[str, Any]:
        signature = digest(
            {
                "project": str(project),
                "record": str(record),
                "command": command.model_dump(mode="json"),
            }
        )
        with self.engine.begin() as c:
            NpiExecutionService._project(
                c, tenant_id=context.tenant.id, project_id=project, lock=True
            )
            BuildMaterialService._authorize(c, context, project, write=True)
            t = tables.supplier_compliance_records
            prior = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.created_by_user_id == context.user.id,
                        t.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != signature:
                    raise ProductWorkError("原请求已用于不同合规矩阵记录")
                return _plain(dict(prior))
            observed = preview(c, context, project, record, command)
            if (
                command.expected_version != observed["basis"]["previous_version"]
                or command.expected_digest != observed["digest"]
            ):
                raise ProductWorkError("条目或原资料发生变化，请重新预览核对")
            saved = (
                c.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project,
                        record_id=record,
                        version=command.expected_version + 1,
                        supplier_id=command.supplier_id,
                        status=command.status,
                        payload=observed["basis"]["command"],
                        snapshot=observed["basis"],
                        evidence_id=command.evidence_id,
                        reason=command.reason,
                        request_id=command.request_id,
                        request_digest=signature,
                        created_by_user_id=context.user.id,
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            NpiExecutionService._record_change(
                c,
                tenant_id=context.tenant.id,
                project_id=project,
                actor_user_id=context.user.id,
                record_id=record,
                record_type="supplier_compliance_record",
                action=command.status,
                before=None,
                after=_plain(dict(saved)),
            )
            return _plain(dict(saved))
