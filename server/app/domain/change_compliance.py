"""Explicit ECR scope to compliance matrix links and immutable human rechecks."""

from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import Connection, Engine, or_, select
from sqlalchemy.dialects.postgresql import JSONB

from app.auth.repository import AuthContext
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.build_materials import BuildMaterialService
from app.domain.change_impact_scope import _access, current_basis
from app.domain.document_previews import document_row, metadata
from app.domain.npi_execution import NpiExecutionService
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.supplier_compliance import ComplianceDraft, latest_query, sources, status

DIRECT = {
    "certification": "certification_ids",
    "build": "build_ids",
    "sample": "sample_ids",
    "bom_item": "bom_item_ids",
    "specification": "specification_ids",
}


class ReviewDraft(Contract):
    request_id: UUID
    expected_version: int = Field(ge=0)
    expected_digest: Digest
    outcome: Literal["needs_recheck", "not_affected", "reviewed"]
    evidence_id: UUID
    reason: Text


def matches(row: dict[str, Any], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payload, original = row["payload"], row["snapshot"]["sources"]
    result = []
    for item in items:
        kind, identity = item["kind"], item["id"]
        found = identity in payload.get(DIRECT[kind], []) if kind in DIRECT else False
        if kind == "supplier":
            found = payload.get("supplier_id") == identity
        if kind == "document":
            found = identity in [
                payload.get(key)
                for key in ("evidence_id", "regulation_evidence_id", "conclusion_evidence_id")
            ]
        if kind in {"bom", "requirement"}:
            key, field = (
                ("bom_item_ids", "bom_id")
                if kind == "bom"
                else ("specification_ids", "requirement_id")
            )
            found = any(value.get(field) == identity for value in original.get(key, []))
        if found:
            result.append(item)
    return result


def matched_query(tenant: UUID, project: UUID, items: list[dict[str, Any]]) -> Any:
    t = tables.supplier_compliance_records
    conditions = []
    for item in items:
        kind, identity = item["kind"], item["id"]
        if kind in DIRECT:
            conditions.append(t.c.payload[DIRECT[kind]].cast(JSONB).contains([identity]))
        elif kind == "supplier":
            conditions.append(t.c.supplier_id == UUID(identity))
        elif kind == "document":
            conditions.extend(
                t.c.payload[key].as_string() == identity
                for key in ("evidence_id", "regulation_evidence_id", "conclusion_evidence_id")
            )
        elif kind in {"bom", "requirement"}:
            key, field = (
                ("bom_item_ids", "bom_id")
                if kind == "bom"
                else ("specification_ids", "requirement_id")
            )
            conditions.append(
                t.c.snapshot["sources"][key].cast(JSONB).contains([{field: identity}])
            )
    return latest_query(tenant, project).where(or_(*conditions) if conditions else False)


def last_review(
    c: Connection, tenant: UUID, project: UUID, ecr: UUID, record: UUID
) -> dict[str, Any] | None:
    t = tables.change_compliance_reviews
    row = (
        c.execute(
            select(t)
            .where(
                t.c.tenant_id == tenant,
                t.c.project_id == project,
                t.c.ecr_id == ecr,
                t.c.record_id == record,
            )
            .order_by(t.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    return _plain(dict(row)) if row else None


def assess(
    c: Connection,
    tenant: UUID,
    project: UUID,
    ecr: UUID,
    scope: dict[str, Any],
    row: dict[str, Any],
) -> dict[str, Any]:
    command = ComplianceDraft.model_validate(row["payload"])
    try:
        actual = sources(c, tenant, project, command)
        current = status(command, actual, digest(actual) != digest(row["snapshot"]["sources"]))
    except (LookupError, ValueError):
        actual = None
        current = {
            "state": "needs_review",
            "reasons": ["部分合规原资料不可读取"],
            "recorded_assessment": command.assessment,
        }
    last = last_review(c, tenant, project, ecr, UUID(row["record_id"]))
    basis = {
        "scope_id": scope["version"]["id"],
        "scope_digest": digest(scope),
        "scope_ready": scope["ready"],
        "matrix": row,
        "current_sources": actual,
        "matrix_status": current,
        "matches": matches(row, scope["version"]["snapshot"]["items"]),
    }
    current_digest = digest(basis)
    return {
        "basis": basis,
        "digest": current_digest,
        "latest": last,
        "review_current": bool(last and last["snapshot"]["digest"] == current_digest),
    }


class ChangeComplianceService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(
        self,
        context: AuthContext,
        project: UUID,
        ecr: UUID,
        after: UUID | None = None,
        record: UUID | None = None,
        before_version: int | None = None,
    ) -> dict[str, Any]:
        _access(self.engine, context, project, edit=False)
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            BuildMaterialService._authorize(c, context, project)
            original = NpiExecutionService._row(
                c,
                tables.engineering_change_requests,
                tenant_id=context.tenant.id,
                project_id=project,
                record_id=ecr,
            )
            scope = current_basis(c, context.tenant.id, project, ecr)
            t, d = tables.supplier_compliance_records, tables.documents
            result: dict[str, Any] = {
                "ecr": _plain(dict(original)),
                "scope": scope,
                "items": [],
                "next_cursor": None,
                "history": [],
                "history_next_before": None,
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
            }
            if scope:
                query = matched_query(
                    context.tenant.id, project, scope["version"]["snapshot"]["items"]
                )
                if record:
                    query = query.where(t.c.record_id == record)
                elif after:
                    query = query.where(t.c.record_id > after)
                rows = list(c.execute(query.order_by(t.c.record_id).limit(21)).mappings())
                result["items"] = [
                    assess(c, context.tenant.id, project, ecr, scope, _plain(dict(row)))
                    for row in rows[:20]
                ]
                result["next_cursor"] = str(rows[19]["record_id"]) if len(rows) > 20 else None
            if record:
                r = tables.change_compliance_reviews
                query = select(r).where(
                    r.c.tenant_id == context.tenant.id,
                    r.c.project_id == project,
                    r.c.ecr_id == ecr,
                    r.c.record_id == record,
                )
                if before_version:
                    query = query.where(r.c.version < before_version)
                history = list(c.execute(query.order_by(r.c.version.desc()).limit(21)).mappings())
                result["history"] = [_plain(dict(row)) for row in history[:20]]
                result["history_next_before"] = (
                    history[19]["version"] if len(history) > 20 else None
                )
            return result

    def apply(
        self, context: AuthContext, project: UUID, ecr: UUID, record: UUID, command: ReviewDraft
    ) -> dict[str, Any]:
        _access(self.engine, context, project, edit=True)
        signature = digest(
            {
                "project": str(project),
                "ecr": str(ecr),
                "record": str(record),
                "command": command.model_dump(mode="json"),
            }
        )
        with self.engine.begin() as c:
            NpiExecutionService._project(
                c, tenant_id=context.tenant.id, project_id=project, lock=True
            )
            BuildMaterialService._authorize(c, context, project, write=True)
            t = tables.change_compliance_reviews
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
                    raise ProductWorkError("原请求已用于另一变更合规核对")
                return _plain(dict(prior))
            scope = current_basis(c, context.tenant.id, project, ecr)
            if scope is None:
                raise ProductWorkError("请先记录 ECR 的实际影响范围")
            matrix = tables.supplier_compliance_records
            row = (
                c.execute(
                    matched_query(
                        context.tenant.id, project, scope["version"]["snapshot"]["items"]
                    ).where(matrix.c.record_id == record)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ProductWorkError("原矩阵条目不在当前显式范围关联中，请先更新范围或矩阵")
            value = assess(c, context.tenant.id, project, ecr, scope, _plain(dict(row)))
            version = value["latest"]["version"] if value["latest"] else 0
            if version != command.expected_version or value["digest"] != command.expected_digest:
                raise ProductWorkError("ECR范围、矩阵或原资料变化，请重新读取核对")
            if command.outcome != "needs_recheck" and not scope["ready"]:
                raise ProductWorkError("原影响范围依据已变化，请先更新范围再记录核对结论")
            if command.outcome == "reviewed" and (
                not scope["ready"]
                or value["basis"]["matrix_status"]["state"]
                not in {"reviewed_met", "reviewed_not_met", "not_applicable"}
            ):
                raise ProductWorkError("范围与矩阵仍有待核项，不能记录已完成重核")
            evidence = metadata(document_row(c, context.tenant.id, project, command.evidence_id))
            saved = (
                c.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project,
                        ecr_id=ecr,
                        record_id=record,
                        matrix_version_id=row["id"],
                        version=version + 1,
                        outcome=command.outcome,
                        evidence_id=command.evidence_id,
                        reason=command.reason,
                        request_id=command.request_id,
                        request_digest=signature,
                        created_by_user_id=context.user.id,
                        snapshot={
                            "basis": value["basis"],
                            "digest": value["digest"],
                            "evidence": evidence,
                        },
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
                record_type="change_compliance_review",
                action=command.outcome,
                before=value["latest"],
                after=_plain(dict(saved)),
            )
            return _plain(dict(saved))
