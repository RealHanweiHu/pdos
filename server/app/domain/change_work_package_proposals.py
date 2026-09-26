"""Source-bound engineering work-package Findings, separate from business approval."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, select

from app.ai.quality import FindingQualityService
from app.ai.rollout_guard import require_live_finding
from app.contracts.change_work_package import ChangeImpactAssessment
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError, digest
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

if TYPE_CHECKING:
    from app.domain.change_impact_scope import ScopeDraft
    from app.domain.findings import FindingRecord


class ImpactChoice(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    target_reference_id: str
    disposition: Literal["adopt", "exclude"]
    reason: str = Field(min_length=1, max_length=4000)
    conclusion: Literal["affected", "unaffected", "unknown"]
    action: Literal["retest", "rereview", "recertification", "coordination", "none"]
    basis: str = Field(default="", max_length=4000)
    next_action: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def complete_choice(self) -> ImpactChoice:
        if self.disposition == "adopt" and (
            not self.basis
            or not self.next_action
            or self.conclusion != "unaffected"
            and self.action == "none"
        ):
            raise ValueError("采用条目须填写影响依据、后续要求和适用的处理方式")
        return self


class PackageReview(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reason: str = Field(min_length=1, max_length=4000)
    coverage: str = Field(min_length=1, max_length=10000)
    exclusions: str = Field(min_length=1, max_length=10000)
    choices: list[ImpactChoice] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def has_application(self) -> PackageReview:
        if len({c.target_reference_id for c in self.choices}) != len(self.choices):
            raise ValueError("同一建议对象须合并核对")
        if not any(c.disposition == "adopt" for c in self.choices):
            raise ValueError("至少采用一项；全部不采用请填写理由并拒绝候选")
        return self


class ChangeWorkPackagePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    ecr_id: UUID
    source_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    depth: int = Field(ge=1, le=5)
    assessment: ChangeImpactAssessment
    review_context: dict[str, Any] = Field(default_factory=dict)
    review: PackageReview | None = None
    details_confirmed: bool = False


def validate_review(
    c: Connection,
    finding: FindingRecord,
    payload: ChangeWorkPackagePayload,
    actor_user_id: UUID | None = None,
) -> None:
    from app.ai.change_impact_preparation import validate_assessment
    from app.ai.change_notice_preparation import rebuild, require_enabled

    if not payload.details_confirmed or payload.review is None:
        raise ProductWorkError("请逐项核对影响、引用和未覆盖范围")
    proposed = payload.model_dump(mode="json", exclude={"details_confirmed", "review"})
    if any(proposed[k] != finding.proposed_payload.get(k) for k in proposed):
        raise ProductWorkError("不能改写本次来源和模型原建议，请在人工核对栏记录业务调整")
    run = (
        c.execute(
            select(tables.agent_runs).where(
                tables.agent_runs.c.tenant_id == finding.tenant_id,
                tables.agent_runs.c.project_id == finding.project_id,
                tables.agent_runs.c.id == finding.run_id,
                tables.agent_runs.c.context_version == "change-work-package-request-v1",
            )
        )
        .mappings()
        .one_or_none()
    )
    if run is None:
        raise ProductWorkError("候选缺少原生成运行")
    snapshot = run["run_context"]["impact_source"]
    require_enabled(snapshot)
    from app.ai.discussion_followup import require_current

    if snapshot.get("discussion_input"):
        from app.ai.discussion_followup import KEY as FOLLOWUP_KEY
        from app.ai.rollout_guard import require_live_key

        require_live_key(FOLLOWUP_KEY)
    require_current(c, finding.tenant_id, snapshot)
    if (
        rebuild(c, finding.tenant_id, finding.project_id, snapshot, actor_user_id)["digest"]
        != payload.source_digest
    ):
        raise ProductWorkError("变更、范围或原证据已变化，请重新生成")
    validate_assessment(payload.assessment, snapshot)
    if payload.review_context != review_context(
        c, finding.tenant_id, finding.project_id, snapshot, payload.assessment
    ):
        raise ProductWorkError("原核对范围或对象已有变化，请重新生成")
    # Build and validate the exact merged scope during review and again at apply.
    from app.domain.change_impact_scope import _ecr

    if _ecr(c, finding.tenant_id, finding.project_id, payload.ecr_id)["status"] not in {
        "request",
        "impact_analysis",
    }:
        raise ProductWorkError("请先退回重新分析，再核对应用范围建议")
    scope = payload.review_context.get("scope")
    if scope and not scope["ready"]:
        raise ProductWorkError("原范围引用已有变化，请先重新核对范围")
    scope_draft(finding, payload)


def review_context(
    c: Connection,
    tenant_id: UUID,
    project_id: UUID,
    snapshot: dict[str, Any],
    output: ChangeImpactAssessment,
) -> dict[str, Any]:
    from app.domain.change_impact_scope import OBJECTS, current_basis, source

    references = {r["reference_id"]: r for r in snapshot["model_context"]["references"]}
    targets = {}
    for impact in output.impacts:
        ref_id = impact.target_reference_id
        kind, raw_id = ref_id.split(":", 1)
        if kind not in OBJECTS:
            raise ProductWorkError("该对象尚无实际范围办理入口")
        value = source(c, tenant_id, project_id, kind, UUID(raw_id))
        targets[ref_id] = {
            "kind": kind,
            "id": raw_id,
            "label": references[ref_id]["label"],
            "expected_digest": digest(value),
            "snapshot": value,
        }
    scope = current_basis(c, tenant_id, project_id, UUID(snapshot["ecr_id"]))
    from app.ai.discussion_followup import provenance

    return {
        **provenance(snapshot),
        "targets": targets,
        "scope": scope,
        "reference_labels": {k: v["label"] for k, v in references.items()},
    }


def scope_draft(finding: FindingRecord, payload: ChangeWorkPackagePayload) -> ScopeDraft:
    from app.domain.change_impact_scope import ScopeDraft, ScopeEdge, ScopeItem

    review = payload.review
    if review is None:
        raise ProductWorkError("缺少逐项人工核对")
    targets = payload.review_context.get("targets", {})
    if {c.target_reference_id for c in review.choices} != {
        i.target_reference_id for i in payload.assessment.impacts
    }:
        raise ProductWorkError("每个建议对象均须记录采用或不采用及其依据")
    scope = payload.review_context.get("scope")
    version = scope["version"] if scope else None
    snapshot = version["snapshot"] if version else {"items": [], "edges": []}
    items = {
        (i["kind"], i["id"]): ScopeItem.model_validate({k: i[k] for k in ScopeItem.model_fields})
        for i in snapshot["items"]
    }
    for choice in review.choices:
        if choice.disposition == "exclude":
            continue
        target = targets.get(choice.target_reference_id)
        if target is None:
            raise ProductWorkError("采用对象缺少本次实际来源")
        identity = (target["kind"], target["id"])
        old = items.get(identity)
        items[identity] = ScopeItem(
            key=old.key if old else uuid5(finding.id, choice.target_reference_id),
            kind=target["kind"],
            id=target["id"],
            expected_digest=target["expected_digest"],
            conclusion=choice.conclusion,
            basis=choice.basis,
            action=choice.action,
            next_action=choice.next_action,
        )
    try:
        return ScopeDraft(
            request_id=uuid5(finding.id, "change-work-package.apply.v1"),
            expected_version_id=version["id"] if version else None,
            reason=review.reason,
            coverage=review.coverage,
            exclusions=review.exclusions,
            items=list(items.values()),
            edges=[
                ScopeEdge.model_validate({k: edge[k] for k in ScopeEdge.model_fields})
                for edge in snapshot["edges"]
            ],
        )
    except ValueError as error:
        raise ProductWorkError(
            "合并后范围超出容量或资料不完整，请调整人工范围后重新生成"
        ) from error


def apply_package(
    c: Connection,
    *,
    finding: FindingRecord,
    payload: ChangeWorkPackagePayload,
    actor_user_id: UUID,
    applied_at: datetime,
) -> UUID:
    from app.auth.roles import Action
    from app.domain.change_impact_scope import save_connection
    from app.domain.findings import FindingService

    for action in (Action.CHANGE_EDIT, Action.PRODUCT_ENGINEERING_VIEW):
        FindingService._authorize_user(
            c,
            tenant_id=finding.tenant_id,
            project_id=finding.project_id,
            user_id=actor_user_id,
            action=action,
        )
    validate_review(c, finding, payload, actor_user_id)
    duplicate = c.execute(
        select(tables.findings.c.id)
        .where(
            tables.findings.c.tenant_id == finding.tenant_id,
            tables.findings.c.project_id == finding.project_id,
            tables.findings.c.origin_key == finding.origin_key,
            tables.findings.c.finding_type == "change_work_package",
            tables.findings.c.status == "applied",
        )
        .limit(1)
    ).scalar_one_or_none()
    if duplicate is not None:
        raise ProductWorkError("相同来源已应用，请到原变更继续办理")
    saved = save_connection(
        c,
        tenant_id=finding.tenant_id,
        project_id=finding.project_id,
        ecr_id=payload.ecr_id,
        actor_user_id=actor_user_id,
        draft=scope_draft(finding, payload),
        finding_origin={
            "finding_id": str(finding.id),
            "run_id": str(finding.run_id),
            "source_digest": payload.source_digest,
            "reviewed_by_user_id": str(finding.reviewed_by_user_id),
            "reviewed_at": finding.reviewed_at.isoformat() if finding.reviewed_at else None,
            "applied_at": applied_at.isoformat(),
            "review": payload.review.model_dump(mode="json") if payload.review else None,
        },
    )
    return UUID(saved["id"])


def persist(
    c: Connection,
    *,
    row: Any,
    snapshot: dict[str, Any],
    output: ChangeImpactAssessment,
    invocation_id: UUID,
    created_at: datetime,
) -> UUID | None:
    from app.ai.change_impact_preparation import validate_assessment
    from app.ai.change_notice_preparation import rebuild, require_enabled
    from app.ai.discussion_followup import require_current
    from app.domain.findings import FINDING_PREFLIGHT_VERSION

    if snapshot.get("discussion_input"):
        from app.ai.discussion_followup import KEY as FOLLOWUP_KEY
        from app.ai.rollout_guard import require_live_key

        require_live_key(FOLLOWUP_KEY)
    require_current(c, row["tenant_id"], snapshot)
    require_enabled(snapshot)
    require_live_finding("engineering_intelligence", "change_work_package")
    if (
        rebuild(c, row["tenant_id"], row["project_id"], snapshot, row["requested_by_user_id"])[
            "digest"
        ]
        != snapshot["digest"]
    ):
        raise ProductWorkError("生成期间变更或原证据已有变化")
    validate_assessment(output, snapshot)
    if output.disposition == "insufficient_evidence":
        return None
    if not FindingQualityService.is_output_allowed_connection(
        c,
        tenant_id=row["tenant_id"],
        agent_key="engineering_intelligence",
        finding_type="change_work_package",
    ):
        raise ProductWorkError("工程变更候选质量控制已收窄")
    payload = ChangeWorkPackagePayload(
        ecr_id=UUID(snapshot["ecr_id"]),
        source_digest=snapshot["digest"],
        depth=snapshot["model_context"]["coverage"]["depth"],
        assessment=output,
        review_context=review_context(c, row["tenant_id"], row["project_id"], snapshot, output),
    )
    origin = "change-work-package:" + digest(
        {"ecr": snapshot["ecr_id"], "source": snapshot["digest"]}
    )
    existing = c.execute(
        select(tables.findings.c.id).where(
            tables.findings.c.tenant_id == row["tenant_id"],
            tables.findings.c.run_id == row["id"],
            tables.findings.c.origin_key == origin,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return UUID(str(existing))
    finding_id = uuid4()
    c.execute(
        tables.findings.insert().values(
            id=finding_id,
            tenant_id=row["tenant_id"],
            project_id=row["project_id"],
            run_id=row["id"],
            model_invocation_id=invocation_id,
            agent_key="engineering_intelligence",
            finding_type="change_work_package",
            origin_key=origin,
            status="pending_review",
            title="讨论后的工程变更建议"
            if snapshot.get("discussion_input")
            else "工程变更影响与后续验证建议",
            summary="请逐项核对影响判断、实际来源及后续专业工作；" + output.coverage_limits,
            proposed_payload=payload.model_dump(mode="json"),
            evidence_event_ids=[],
            confidence_basis_points=0,
            preflight_version=FINDING_PREFLIGHT_VERSION,
            created_at=created_at,
            updated_at=created_at,
        )
    )
    c.execute(
        tables.finding_actions.insert().values(
            id=uuid4(),
            tenant_id=row["tenant_id"],
            project_id=row["project_id"],
            finding_id=finding_id,
            action="created",
            actor_user_id=None,
            to_status="pending_review",
            detail={"source": "change_impact_sources", "ecr_id": snapshot["ecr_id"]},
            created_at=created_at,
        )
    )
    EventAuditWriter(
        c,
        tenant_id=row["tenant_id"],
        actor_user_id=row["requested_by_user_id"],
        project_id=row["project_id"],
    ).record(
        EventDraft(
            event_id=f"ai-finding:{finding_id}:created",
            event_type="AI_FINDING_CREATED",
            source="ai_runtime",
            entity_id=finding_id,
            occurred_at=created_at,
            payload={"finding_id": str(finding_id), "agent_run_id": str(row["id"])},
        ),
        AuditDraft(
            action="finding.create_change_work_package",
            after_snapshot={"finding_id": str(finding_id)},
            context={"ecr_id": snapshot["ecr_id"], "model_invocation_id": str(invocation_id)},
        ),
    )
    return finding_id
