"""Human-reviewed, immutable change scope and evidence for cross-domain relationships."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, exists, select

from app.auth.project_access import ProjectAccessService, SqlProjectAccessRepository
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.npi_execution import NpiExecutionService, _snapshot
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.test_verification_paths import _authorize

ObjectKind = Literal[
    "requirement",
    "ecn",
    "bom",
    "bom_item",
    "specification",
    "test_case",
    "test_run",
    "sample",
    "configuration",
    "build",
    "issue",
    "cost_item",
    "cost",
    "supplier",
    "certification",
    "document",
]
OBJECTS = {
    "requirement": tables.requirements,
    "ecn": tables.engineering_change_notices,
    "bom": tables.development_boms,
    "bom_item": tables.development_bom_items,
    "specification": tables.specifications,
    "test_case": tables.test_cases,
    "test_run": tables.test_runs,
    "sample": tables.samples,
    "configuration": tables.sample_configuration_revisions,
    "build": tables.build_batches,
    "issue": tables.issues,
    "cost_item": tables.cost_bom_items,
    "cost": tables.costs,
    "supplier": tables.suppliers,
    "certification": tables.certifications,
    "document": tables.documents,
}


class ScopeItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    key: UUID
    kind: ObjectKind
    id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    conclusion: Literal["affected", "unaffected", "unknown"]
    basis: str = Field(min_length=1, max_length=4000)
    action: Literal["retest", "rereview", "recertification", "coordination", "none"]
    next_action: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def action_needed(self) -> ScopeItem:
        if self.conclusion != "unaffected" and self.action == "none":
            raise ValueError("受影响或未知对象须明确复验、复审、复认证或协同行动")
        return self


class ScopeEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source_key: UUID
    target_key: UUID
    relation: str = Field(min_length=1, max_length=200)
    basis: str = Field(min_length=1, max_length=4000)
    evidence_document_id: UUID
    evidence_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence_locator: str = Field(min_length=1, max_length=2000)


class ScopeDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_version_id: UUID | None = None
    reason: str = Field(min_length=1, max_length=4000)
    coverage: str = Field(min_length=1, max_length=10000)
    exclusions: str = Field(min_length=1, max_length=10000)
    items: list[ScopeItem] = Field(min_length=1, max_length=100)
    edges: list[ScopeEdge] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def references(self) -> ScopeDraft:
        keys = {item.key for item in self.items}
        if len(keys) != len(self.items) or len({(i.kind, i.id) for i in self.items}) != len(
            self.items
        ):
            raise ValueError("同一对象请合并范围与处理要求后登记一次")
        seen = set()
        for edge in self.edges:
            identity = (edge.source_key, edge.target_key, edge.relation)
            if (
                edge.source_key == edge.target_key
                or not {edge.source_key, edge.target_key} <= keys
                or identity in seen
            ):
                raise ValueError("关系须连接本版不同对象且不可重复")
            seen.add(identity)
        return self


def _query(kind: str, tenant_id: UUID, project_id: UUID) -> Any:
    t = OBJECTS[kind]
    q = select(t).where(t.c.tenant_id == tenant_id)
    if kind == "requirement":
        spec = tables.specifications
        return q.where(
            exists().where(
                spec.c.tenant_id == tenant_id,
                spec.c.project_id == project_id,
                spec.c.requirement_id == t.c.id,
            )
        )
    return q.where(t.c.project_id == project_id) if "project_id" in t.c else q


def source(c: Connection, tenant_id: UUID, project_id: UUID, kind: str, id: UUID) -> dict[str, Any]:
    row = (
        c.execute(_query(kind, tenant_id, project_id).where(OBJECTS[kind].c.id == id))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkError("范围引用对象不存在或已不可读")
    return _value(kind, dict(row))


def _value(kind: str, value: dict[str, Any]) -> dict[str, Any]:
    if kind == "document":
        value = {
            k: value[k]
            for k in ("id", "filename", "media_type", "sha256", "classification", "created_at")
        }
    return _plain(value)


def _latest(
    c: Connection, tenant_id: UUID, project_id: UUID, ecr_id: UUID
) -> dict[str, Any] | None:
    t = tables.change_impact_scope_versions
    row = (
        c.execute(
            select(t)
            .where(t.c.tenant_id == tenant_id, t.c.project_id == project_id, t.c.ecr_id == ecr_id)
            .order_by(t.c.revision_number.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row else None


def current_basis(
    c: Connection, tenant_id: UUID, project_id: UUID, ecr_id: UUID
) -> dict[str, Any] | None:
    version = _latest(c, tenant_id, project_id, ecr_id)
    if version is None:
        return None
    sources = []
    refs = [(i["kind"], i["id"], i["expected_digest"]) for i in version["snapshot"]["items"]]
    refs += [
        ("document", e["evidence_document_id"], e["evidence_digest"])
        for e in version["snapshot"]["edges"]
    ]
    for kind, id, expected in sorted(set(refs)):
        try:
            current = source(c, tenant_id, project_id, kind, UUID(id))
            current_digest = digest(current)
        except ProductWorkError:
            current_digest = None
        sources.append(
            {
                "kind": kind,
                "id": id,
                "expected_digest": expected,
                "current_digest": current_digest,
                "changed": current_digest != expected,
            }
        )
    return {
        "version": _plain(version),
        "sources": sources,
        "ready": not any(s["changed"] for s in sources),
    }


def _access(engine: Engine, context: AuthContext, project_id: UUID, *, edit: bool) -> None:
    _authorize(engine, context, project_id, edit=False)
    ProjectAccessService(SqlProjectAccessRepository(engine)).authorize(
        context=context,
        project_id=project_id,
        action=Action.CHANGE_EDIT if edit else Action.CHANGE_VIEW,
    )


def read(
    engine: Engine,
    *,
    context: AuthContext,
    project_id: UUID,
    ecr_id: UUID,
    before_revision: int | None = None,
) -> dict[str, Any]:
    _access(engine, context, project_id, edit=False)
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        ecr = _ecr(c, context.tenant.id, project_id, ecr_id)
        basis = current_basis(c, context.tenant.id, project_id, ecr_id)
        t = tables.change_impact_scope_versions
        q = select(t).where(
            t.c.tenant_id == context.tenant.id, t.c.project_id == project_id, t.c.ecr_id == ecr_id
        )
        if before_revision is not None:
            q = q.where(t.c.revision_number < before_revision)
        rows = c.execute(q.order_by(t.c.revision_number.desc()).limit(21)).mappings().all()
        return {
            "basis": basis,
            "digest": digest(basis),
            "can_edit": ecr["status"] in {"request", "impact_analysis"},
            "history": [_plain(dict(r)) for r in rows[:20]],
            "next_before_revision": rows[19]["revision_number"] if len(rows) > 20 else None,
        }


def sources(
    engine: Engine,
    *,
    context: AuthContext,
    project_id: UUID,
    ecr_id: UUID,
    kind: ObjectKind,
    after_id: UUID | None = None,
) -> dict[str, Any]:
    _access(engine, context, project_id, edit=False)
    with engine.connect() as c:
        _ecr(c, context.tenant.id, project_id, ecr_id)
        t = OBJECTS[kind]
        q = _query(kind, context.tenant.id, project_id)
        if after_id is not None:
            q = q.where(t.c.id > after_id)
        rows = c.execute(q.order_by(t.c.id).limit(51)).mappings().all()
        values = []
        for row in rows[:50]:
            value = _value(kind, dict(row))
            values.append({"id": str(row["id"]), "snapshot": value, "digest": digest(value)})
        return {"sources": values, "next_after_id": str(rows[49]["id"]) if len(rows) > 50 else None}


def _ecr(c: Connection, tenant_id: UUID, project_id: UUID, ecr_id: UUID) -> dict[str, Any]:
    t = tables.engineering_change_requests
    row = (
        c.execute(
            select(t).where(
                t.c.tenant_id == tenant_id, t.c.project_id == project_id, t.c.id == ecr_id
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkError("工程变更不存在或不属于本项目")
    return dict(row)


def save(
    engine: Engine, *, context: AuthContext, project_id: UUID, ecr_id: UUID, draft: ScopeDraft
) -> dict[str, Any]:
    _access(engine, context, project_id, edit=True)
    with engine.begin() as c:
        if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project_id):
            raise ProductWorkError("项目不可用")
        _access(engine, context, project_id, edit=True)
        return save_connection(
            c,
            tenant_id=context.tenant.id,
            project_id=project_id,
            ecr_id=ecr_id,
            actor_user_id=context.user.id,
            draft=draft,
        )


def save_connection(
    c: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    ecr_id: UUID,
    actor_user_id: UUID,
    draft: ScopeDraft,
    finding_origin: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write under the caller's project lock and authorization, in the same transaction."""
    fingerprint = digest(
        {
            "project_id": str(project_id),
            "ecr_id": str(ecr_id),
            **draft.model_dump(mode="json"),
            **({"finding_origin": finding_origin} if finding_origin else {}),
        }
    )
    t = tables.change_impact_scope_versions
    prior = (
        c.execute(
            select(t).where(
                t.c.tenant_id == tenant_id,
                t.c.created_by_user_id == actor_user_id,
                t.c.request_id == draft.request_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if prior:
        if prior["request_digest"] != fingerprint:
            raise ProductWorkError("同一保存请求不能改写范围内容")
        return _plain(dict(prior))
    ecr = _ecr(c, tenant_id, project_id, ecr_id)
    if ecr["status"] not in {"request", "impact_analysis"}:
        raise ProductWorkError("请先退回重新分析，再修订变更范围；已批准版本不可改写")
    latest = _latest(c, tenant_id, project_id, ecr_id)
    if (latest["id"] if latest else None) != draft.expected_version_id:
        raise ProductWorkError("核对范围已有新版本，请刷新后修订")
    items = []
    for item in draft.items:
        value = source(c, tenant_id, project_id, item.kind, item.id)
        if digest(value) != item.expected_digest:
            raise ProductWorkError("范围对象已变化，请重新选取当前资料并核对")
        items.append({**item.model_dump(mode="json"), "snapshot": value})
    edges = []
    for edge in draft.edges:
        evidence = source(c, tenant_id, project_id, "document", edge.evidence_document_id)
        if digest(evidence) != edge.evidence_digest:
            raise ProductWorkError("关系证据已变化，请核对原文件")
        edges.append({**edge.model_dump(mode="json"), "evidence_snapshot": evidence})
    snapshot: dict[str, Any] = {
        "coverage": draft.coverage,
        "exclusions": draft.exclusions,
        "items": items,
        "edges": edges,
    }
    if finding_origin is not None:
        snapshot["finding_origin"] = finding_origin
    row = (
        c.execute(
            t.insert()
            .values(
                id=uuid4(),
                tenant_id=tenant_id,
                project_id=project_id,
                ecr_id=ecr_id,
                revision_number=latest["revision_number"] + 1 if latest else 1,
                request_id=draft.request_id,
                request_digest=fingerprint,
                created_by_user_id=actor_user_id,
                created_at=datetime.now(UTC),
                reason=draft.reason,
                snapshot=snapshot,
            )
            .returning(t)
        )
        .mappings()
        .one()
    )
    NpiExecutionService._record_change(
        c,
        tenant_id=tenant_id,
        project_id=project_id,
        actor_user_id=actor_user_id,
        record_id=row["id"],
        record_type="change_impact_scope",
        action="recorded",
        before=_snapshot(latest) if latest else None,
        after=_snapshot(dict(row)),
    )
    return _plain(dict(row))


def freeze_analysis(
    c: Connection,
    tenant_id: UUID,
    project_id: UUID,
    ecr_id: UUID,
    analysis: dict[str, Any],
    affected_bom_ids: list[UUID] | None = None,
) -> dict[str, Any]:
    basis = current_basis(c, tenant_id, project_id, ecr_id)
    if basis is None:
        return {k: v for k, v in analysis.items() if k != "impact_scope"}
    if not isinstance(analysis.get("summary"), str) or not analysis["summary"].strip():
        raise ProductWorkError("请填写本次范围的实际影响分析结论")
    if affected_bom_ids is not None:
        scoped = {
            UUID(item["id"])
            for item in basis["version"]["snapshot"]["items"]
            if item["kind"] == "bom" and item["conclusion"] == "affected"
        }
        if set(affected_bom_ids) != scoped:
            raise ProductWorkError("受影响BOM须与核对范围内逐一确认的BOM一致，请补齐范围或修正勾选")
    submitted = analysis.get("impact_scope") or {}
    if not isinstance(submitted, dict):
        raise ProductWorkError("请核对最新范围版本")
    if (
        not basis["ready"]
        or submitted.get("expected_digest") != digest(basis)
        or submitted.get("version_id") != basis["version"]["id"]
    ):
        raise ProductWorkError("请核对最新范围及全部对象/关系证据后重新提交分析")
    return {
        **analysis,
        "impact_scope": {
            "version_id": basis["version"]["id"],
            "expected_digest": digest(basis),
            "basis": basis,
        },
    }


def require_current(
    c: Connection, tenant_id: UUID, project_id: UUID, ecr_id: UUID, analysis: dict[str, Any] | None
) -> None:
    basis = current_basis(c, tenant_id, project_id, ecr_id)
    if basis is None:
        return
    b = tables.ecr_affected_boms
    bom_ids = list(
        c.execute(
            select(b.c.bom_id).where(
                b.c.tenant_id == tenant_id, b.c.project_id == project_id, b.c.ecr_id == ecr_id
            )
        ).scalars()
    )
    frozen = freeze_analysis(c, tenant_id, project_id, ecr_id, analysis or {}, bom_ids)
    if any(
        item["conclusion"] == "unknown"
        for item in frozen["impact_scope"]["basis"]["version"]["snapshot"]["items"]
    ):
        raise ProductWorkError("核对范围仍有未知影响，请退回分析补齐")
