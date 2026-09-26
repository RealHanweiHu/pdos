"""Current, permission-scoped notice evidence in ECR analysis and approval."""

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext, AuthRepository
from app.contracts.common_objects import Contract, Digest
from app.db.schema import tables
from app.domain.id_change_impact import AXES, ImpactAssessment
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.supplier_notice_applications import authorize, target
from app.domain.supplier_notice_reviews import ReviewDraft, candidate, latest, sources

VERSION = "supplier-notice-impact-v1"


class NoticeImpact(Contract):
    expected_basis_digest: Digest
    source_responses: dict[str, ImpactAssessment]
    assessments: dict[str, ImpactAssessment]


def basis(c: Connection, context: AuthContext, project: UUID, ecr_id: UUID) -> dict[str, Any]:
    from app.auth.roles import Action
    from app.domain.knowledge_corrections import KnowledgeCorrectionService

    KnowledgeCorrectionService._authorize(
        c, context.tenant.id, context.user.id, project, Action.CHANGE_VIEW
    )
    target(c, context.tenant.id, project, "ecr", ecr_id)
    t = tables.supplier_notice_applications
    applications = (
        c.execute(
            select(t)
            .where(
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == project,
                t.c.ecr_id == ecr_id,
                t.c.target_kind == "ecr",
            )
            .order_by(t.c.id)
        )
        .mappings()
        .all()
    )
    entries: list[dict[str, Any]] = []
    for application in applications:
        entry: dict[str, Any] = {
            "application_id": str(application["id"]),
            "candidate_id": str(application["candidate_id"]),
            "application_review_id": str(application["review_id"]),
            "ready": False,
        }
        try:
            authorize(c, context, project, "ecr")
            item = candidate(c, context.tenant.id, project, application["candidate_id"])
            review = latest(c, item["id"])
            source = sources(c, context, project, item, [])
            if not source["content_available"]:
                raise ProductWorkError("原通告来源已停用")
            if review is None:
                raise ProductWorkError("原人审记录不可用")
            evidence = ReviewDraft.model_validate(review["review"]).evidence
            if evidence:
                source = sources(c, context, project, item, evidence)
            ready = bool(
                review["decision"] == "accepted"
                and source["original_valid"]
                and source["scope_current"]
                and digest(source) == review["source_digest"]
            )
            bom_item = source["original"]["watch_source"]["bom_item"]
            entry.update(
                review_id=str(review["id"]),
                review_version=review["version"],
                review_digest=digest(_plain(review)),
                current_source_digest=digest(source),
                bom_id=bom_item["bom_id"],
                bom_item_id=bom_item["id"],
                bom_code=bom_item["bom_code"],
                bom_version=bom_item["bom_version"],
                notice=review["review"],
                ready=ready,
                revised_since_application=review["id"] != application["review_id"],
                source_url=source["original_snapshot"]["url"],
                snapshot_id=source["original_snapshot"]["id"],
                reason=application["command"]["reason"],
                error=None if ready else "最新人审未接受或其来源/在用范围已变化，请先重新核对通告",
            )
        except (LookupError, ValueError, PermissionError):
            entry["error"] = "原来源、人审或核对资料不可读取，请恢复读取范围并重新核对"
        entries.append(entry)
    return {"version": VERSION, "sources": entries}


def compact(value: dict[str, Any]) -> dict[str, Any]:
    """Store identity/version receipts in the general ECR, not restricted source text."""
    return {
        "version": VERSION,
        "sources": [
            {
                key: source.get(key)
                for key in (
                    "application_id",
                    "candidate_id",
                    "application_review_id",
                    "review_id",
                    "review_version",
                    "review_digest",
                    "current_source_digest",
                    "bom_id",
                    "bom_item_id",
                    "ready",
                )
            }
            for source in value["sources"]
        ],
    }


def validate(draft: NoticeImpact, value: dict[str, Any], affected_boms: list[UUID]) -> None:
    if draft.expected_basis_digest != digest(compact(value)) or not all(
        source["ready"] for source in value["sources"]
    ):
        raise ProductWorkError("通告人审或原来源已变化，请读取当前资料并重新分析")
    if set(draft.source_responses) != {s["application_id"] for s in value["sources"]}:
        raise ProductWorkError("请逐条核对所有已关联通告，不遗漏或加入其他来源")
    if set(draft.assessments) != set(AXES):
        raise ProductWorkError("请完成通告涉及的九类影响分析")
    for assessment in [*draft.source_responses.values(), *draft.assessments.values()]:
        if assessment.conclusion != "unaffected" and not assessment.next_action:
            raise ProductWorkError("通告受影响或未知项须说明后续行动")
    selected = {str(v) for v in affected_boms}
    for source in value["sources"]:
        if (
            draft.source_responses[source["application_id"]].conclusion == "affected"
            and source["bom_id"] not in selected
        ):
            raise ProductWorkError("已认定受影响的通告须包含其实际在用BOM；无影响应明确说明依据")


def actor(c: Connection, tenant: UUID, user_id: UUID) -> AuthContext:
    context = AuthRepository(c.engine).find_user_context(user_id)
    if (
        context is None
        or context.tenant.id != tenant
        or context.tenant.status != "active"
        or not context.user.is_active
    ):
        raise ProductWorkError("当前分析或批准人不可用")
    return context


def has_sources(c: Connection, tenant: UUID, project: UUID, ecr_id: UUID) -> bool:
    t = tables.supplier_notice_applications
    return (
        c.execute(
            select(t.c.id)
            .where(t.c.tenant_id == tenant, t.c.project_id == project, t.c.ecr_id == ecr_id)
            .limit(1)
        ).scalar_one_or_none()
        is not None
    )


def freeze(
    c: Connection,
    tenant: UUID,
    project: UUID,
    ecr_id: UUID,
    user_id: UUID,
    analysis: dict[str, Any],
    affected_boms: list[UUID],
) -> dict[str, Any]:
    if not has_sources(c, tenant, project, ecr_id):
        return {k: v for k, v in analysis.items() if k != "supplier_notices"}
    value = basis(c, actor(c, tenant, user_id), project, ecr_id)
    if not value["sources"]:
        return {k: v for k, v in analysis.items() if k != "supplier_notices"}
    draft = NoticeImpact.model_validate(analysis.get("supplier_notices", {}))
    validate(draft, value, affected_boms)
    return {
        **analysis,
        "supplier_notices": {**draft.model_dump(mode="json"), "basis": compact(value)},
    }


def require_current(
    c: Connection,
    tenant: UUID,
    project: UUID,
    ecr_id: UUID,
    user_id: UUID,
    analysis: dict[str, Any] | None,
) -> None:
    if not has_sources(c, tenant, project, ecr_id):
        return
    value = basis(c, actor(c, tenant, user_id), project, ecr_id)
    if not value["sources"]:
        return
    stored = (analysis or {}).get("supplier_notices", {})
    draft = NoticeImpact.model_validate(
        {k: stored.get(k) for k in ("expected_basis_digest", "source_responses", "assessments")}
    )
    boms = list(
        c.execute(
            select(tables.ecr_affected_boms.c.bom_id).where(
                tables.ecr_affected_boms.c.tenant_id == tenant,
                tables.ecr_affected_boms.c.project_id == project,
                tables.ecr_affected_boms.c.ecr_id == ecr_id,
            )
        ).scalars()
    )
    validate(draft, value, boms)
    if stored.get("basis") != compact(value):
        raise ProductWorkError("原通告来源版本已变化，请退回重新分析")
    if any(
        v.conclusion == "unknown"
        for v in [*draft.source_responses.values(), *draft.assessments.values()]
    ):
        raise ProductWorkError("通告仍有未知影响，须补齐后再批准")


class SupplierNoticeImpact:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def get(self, context: AuthContext, project: UUID, ecr_id: UUID) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            value = basis(c, context, project, ecr_id)
            ecr = target(c, context.tenant.id, project, "ecr", ecr_id)
            stored = (ecr["impact_analysis"] or {}).get("supplier_notices", {})
            return {
                **value,
                "digest": digest(compact(value)),
                "stored_current": bool(stored and stored.get("basis") == compact(value)),
                "ready": all(s["ready"] for s in value["sources"]),
            }
