"""Human routing of fixed engineering/firmware packages into the original ECR workflow."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.auth.project_access import ProjectAccessService, SqlProjectAccessRepository
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.change_governance import ChangeGovernanceService
from app.domain.engineering_review_packages import (
    EngineeringReviewError,
)
from app.domain.engineering_review_packages import (
    source as engineering_source,
)
from app.domain.firmware_work_packages import FirmwarePackageError
from app.domain.firmware_work_packages import _source as firmware_source
from app.domain.id_change_impact import AXES, ImpactAssessment
from app.domain.npi_execution import NpiExecutionService, _snapshot
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.test_verification_paths import _authorize

SourceKind = Literal["engineering_review", "firmware_package", "cost_alternative"]


class RouteDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(min_length=1, max_length=4000)
    ecr_id: UUID | None = None
    ecr_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    code: str | None = Field(default=None, min_length=1, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def target(self) -> RouteDraft:
        if self.ecr_id:
            if not self.ecr_digest or self.code or self.title:
                raise ValueError("请核对原ECR，不同时创建新编号")
        elif not self.code or not self.title:
            raise ValueError("新ECR需要编号和标题")
        return self


class ProfessionalImpact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_basis_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_responses: dict[str, str]
    assessments: dict[str, ImpactAssessment]


def source_basis(
    c: Connection, tenant_id: UUID, project_id: UUID, kind: SourceKind, id: UUID
) -> dict[str, Any]:
    if kind == "cost_alternative":
        from app.domain.cost_alternatives import source_for_change

        return source_for_change(c, tenant_id, project_id, id)
    t = (
        tables.engineering_review_packages
        if kind == "engineering_review"
        else tables.firmware_work_packages
    )
    row = (
        c.execute(
            select(t).where(t.c.tenant_id == tenant_id, t.c.project_id == project_id, t.c.id == id)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkError("专业工作包不存在或已不属于本项目")
    root_column = t.c.root_id if kind == "engineering_review" else t.c.fw_release_id
    root_id = row["root_id"] if kind == "engineering_review" else row["fw_release_id"]
    latest_id = c.execute(
        select(t.c.id)
        .where(t.c.tenant_id == tenant_id, t.c.project_id == project_id, root_column == root_id)
        .order_by(t.c.revision_number.desc())
        .limit(1)
    ).scalar_one()
    refs = []
    for ref in row["snapshot"]["sources"]:
        try:
            current = (engineering_source if kind == "engineering_review" else firmware_source)(
                c, tenant_id, project_id, ref["kind"], UUID(ref["id"])
            )
        except (EngineeringReviewError, FirmwarePackageError):
            current = None
        refs.append(
            {
                "kind": ref["kind"],
                "id": ref["id"],
                "current": current,
                "changed": current is None or digest(current) != ref["expected_digest"],
            }
        )
    return _plain(
        {
            "kind": kind,
            "source": dict(row),
            "root_id": root_id,
            "latest_id": latest_id,
            "references": refs,
            "ready": latest_id == id and not any(r["changed"] for r in refs),
        }
    )


def options(
    engine: Engine, *, context: AuthContext, project_id: UUID, kind: SourceKind, source_id: UUID
) -> dict[str, Any]:
    _authorize(engine, context, project_id, edit=False)
    with engine.connect() as c:
        basis = source_basis(c, context.tenant.id, project_id, kind, source_id)
        t = tables.professional_change_routes
        prior = (
            c.execute(
                select(t).where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.project_id == project_id,
                    t.c.source_kind == kind,
                    t.c.source_id == source_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        e = tables.engineering_change_requests
        ecrs = [
            dict(r)
            for r in c.execute(
                select(e)
                .where(
                    e.c.tenant_id == context.tenant.id,
                    e.c.project_id == project_id,
                    e.c.status.in_(["request", "impact_analysis"]),
                )
                .order_by(e.c.created_at, e.c.id)
            ).mappings()
        ]
        routed_ecr = (
            c.execute(
                select(e).where(
                    e.c.tenant_id == context.tenant.id,
                    e.c.project_id == project_id,
                    e.c.id == prior["ecr_id"],
                )
            )
            .mappings()
            .one()
            if prior
            else None
        )
    return {
        "basis": basis,
        "digest": digest(basis),
        "route": _plain(dict(prior)) if prior else None,
        "routed_ecr": _plain(dict(routed_ecr)) if routed_ecr else None,
        "ecrs": [{**_plain(r), "digest": digest(_plain(r))} for r in ecrs],
    }


def route(
    engine: Engine,
    *,
    context: AuthContext,
    project_id: UUID,
    kind: SourceKind,
    source_id: UUID,
    draft: RouteDraft,
) -> dict[str, Any]:
    _authorize(engine, context, project_id, edit=True)
    access = ProjectAccessService(SqlProjectAccessRepository(engine))
    access.authorize(context=context, project_id=project_id, action=Action.CHANGE_EDIT)
    fingerprint = digest(
        {
            "project_id": str(project_id),
            "kind": kind,
            "source_id": str(source_id),
            **draft.model_dump(mode="json"),
        }
    )
    t = tables.professional_change_routes
    with engine.begin() as c:
        if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project_id):
            raise ProductWorkError("项目不可用")
        _authorize(engine, context, project_id, edit=True)
        access.authorize(context=context, project_id=project_id, action=Action.CHANGE_EDIT)
        prior = (
            c.execute(
                select(t).where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.created_by_user_id == context.user.id,
                    t.c.request_id == draft.request_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if prior:
            if prior["request_digest"] != fingerprint:
                raise ProductWorkError("同一转入请求不能改写，请重新核对")
            return _plain(dict(prior))
        if c.execute(
            select(t.c.id).where(
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == project_id,
                t.c.source_kind == kind,
                t.c.source_id == source_id,
            )
        ).first():
            raise ProductWorkError("该资料已转入ECR，请刷新查看原办理回执")
        basis = source_basis(c, context.tenant.id, project_id, kind, source_id)
        if not basis["ready"] or digest(basis) != draft.expected_digest:
            raise ProductWorkError("工作包已有新版或出处已变化，请先修订当前资料")
        if draft.ecr_id:
            e = tables.engineering_change_requests
            ecr = (
                c.execute(
                    select(e)
                    .where(
                        e.c.tenant_id == context.tenant.id,
                        e.c.project_id == project_id,
                        e.c.id == draft.ecr_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if (
                ecr is None
                or ecr["status"] not in {"request", "impact_analysis"}
                or digest(_plain(dict(ecr))) != draft.ecr_digest
            ):
                raise ProductWorkError("原ECR已变化或已进入批准，请重新读取可转入的变更")
            ecr_id = draft.ecr_id
        else:
            created_ecr = ChangeGovernanceService(engine).create_ecr_in_transaction(
                c,
                tenant_id=context.tenant.id,
                project_id=project_id,
                actor_user_id=context.user.id,
                code=str(draft.code),
                title=str(draft.title),
                reason=draft.reason,
            )
            ecr_id = created_ecr["id"]
        row = (
            c.execute(
                t.insert()
                .values(
                    id=uuid4(),
                    tenant_id=context.tenant.id,
                    project_id=project_id,
                    source_kind=kind,
                    source_id=source_id,
                    ecr_id=ecr_id,
                    request_id=draft.request_id,
                    request_digest=fingerprint,
                    created_by_user_id=context.user.id,
                    created_at=datetime.now(UTC),
                    reason=draft.reason,
                    snapshot=basis,
                )
                .returning(t)
            )
            .mappings()
            .one()
        )
        NpiExecutionService._record_change(
            c,
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            record_id=row["id"],
            record_type="professional_change_route",
            action="routed",
            before=None,
            after=_snapshot(dict(row)),
        )
        return _plain(dict(row))


def impact_basis(
    c: Connection, tenant_id: UUID, project_id: UUID, ecr_id: UUID
) -> dict[str, Any] | None:
    t = tables.professional_change_routes
    links = [
        dict(r)
        for r in c.execute(
            select(t)
            .where(t.c.tenant_id == tenant_id, t.c.project_id == project_id, t.c.ecr_id == ecr_id)
            .order_by(t.c.created_at, t.c.id)
        ).mappings()
    ]
    if not links:
        return None
    effective: dict[tuple[str, str], dict[str, Any]] = {}
    for link in links:
        key = (link["source_kind"], link["snapshot"]["root_id"])
        old = effective.get(key)
        if (
            old is None
            or old["snapshot"]["source"]["revision_number"]
            < link["snapshot"]["source"]["revision_number"]
        ):
            effective[key] = link
    return {
        "sources": [
            {
                "route_id": str(link["id"]),
                "routing_reason": link["reason"],
                **source_basis(c, tenant_id, project_id, link["source_kind"], link["source_id"]),
            }
            for link in sorted(effective.values(), key=lambda row: str(row["id"]))
        ]
    }


def source_summaries(basis: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "route_id": s["route_id"],
            "kind": s["kind"],
            "source_id": s["source"]["id"],
            "revision": s["source"]["revision_number"],
            "ready": s["ready"],
            "title": s["source"]["snapshot"].get("title")
            or "固件 " + s["source"]["snapshot"].get("firmware_version", ""),
            "scope": s["source"]["snapshot"].get("scope")
            or s["source"]["snapshot"].get("change_notes"),
            "routing_reason": s["routing_reason"],
        }
        for s in basis["sources"]
    ]


def _validate(draft: ProfessionalImpact, basis: dict[str, Any]) -> None:
    if draft.expected_basis_digest != digest(basis) or not all(
        s["ready"] for s in basis["sources"]
    ):
        raise ProductWorkError("专业工作包或原出处已变化，请修订来源后重新分析")
    if set(draft.source_responses) != {s["route_id"] for s in basis["sources"]} or any(
        not v.strip() or len(v) > 4000 for v in draft.source_responses.values()
    ):
        raise ProductWorkError("请逐一说明专业工作包的影响结论与处理方式")
    if set(draft.assessments) != set(AXES) or any(
        a.conclusion != "unaffected" and not a.next_action for a in draft.assessments.values()
    ):
        raise ProductWorkError("请完成九类影响分析，受影响或未知领域须有后续行动")


def freeze_analysis(
    c: Connection, tenant_id: UUID, project_id: UUID, ecr_id: UUID, analysis: dict[str, Any]
) -> dict[str, Any]:
    basis = impact_basis(c, tenant_id, project_id, ecr_id)
    if basis is None:
        return {key: value for key, value in analysis.items() if key != "professional"}
    if not isinstance(analysis.get("summary"), str) or not analysis["summary"].strip():
        raise ProductWorkError("请填写实际专业变更影响分析")
    draft = ProfessionalImpact.model_validate(analysis.get("professional", {}))
    _validate(draft, basis)
    return {**analysis, "professional": {**draft.model_dump(mode="json"), "basis": basis}}


def require_current_impact(
    c: Connection, tenant_id: UUID, project_id: UUID, ecr_id: UUID, analysis: dict[str, Any] | None
) -> None:
    basis = impact_basis(c, tenant_id, project_id, ecr_id)
    if basis is None:
        return
    stored = (analysis or {}).get("professional", {})
    draft = ProfessionalImpact.model_validate(
        {k: stored.get(k) for k in ("expected_basis_digest", "source_responses", "assessments")}
    )
    _validate(draft, basis)
    if any(a.conclusion == "unknown" for a in draft.assessments.values()):
        raise ProductWorkError("专业变更仍有未明确影响，请退回重新分析")
