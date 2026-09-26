"""Source-bound cost candidates, human review and actual alternative adoption."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, select

from app.ai.quality import FindingQualityService
from app.ai.rollout_guard import require_live_finding
from app.contracts.common_objects import Digest, Text
from app.contracts.cost_reduction import CostAssessment, Selection
from app.db.schema import tables
from app.domain.cost_alternatives import AlternativeDraft, AlternativeSave, CostAlternativeService
from app.domain.cost_alternatives import preview as alternative_preview
from app.domain.product_workspace import ProductWorkError, _plain
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


def persist(
    c: Connection,
    *,
    row: Any,
    snapshot: dict[str, Any],
    output: CostAssessment,
    invocation_id: UUID,
    created_at: datetime,
) -> UUID | None:
    from app.ai.cost_reduction_preparation import rebuild, validate_assessment
    from app.domain.findings import FINDING_PREFLIGHT_VERSION

    require_live_finding("engineering_intelligence", "cost_reduction")
    if (
        row["agent_key"] != "engineering_intelligence"
        or row["context_version"] != "cost-reduction-request-v1"
    ):
        raise ProductWorkError("成本建议候选须来自原版本实际运行")
    if row["run_context"].get("cost_output_mode") != "reviewable.v1":
        raise ProductWorkError("原只读运行保留原用途，请新建成本建议运行")
    if row["run_context"].get("cost_source") != snapshot:
        raise ProductWorkError("本次来源未固定在原运行")
    invocation = c.execute(
        select(tables.model_invocations.c.id).where(
            tables.model_invocations.c.tenant_id == row["tenant_id"],
            tables.model_invocations.c.project_id == row["project_id"],
            tables.model_invocations.c.run_id == row["id"],
            tables.model_invocations.c.id == invocation_id,
            tables.model_invocations.c.agent_key == row["agent_key"],
            tables.model_invocations.c.prompt_version == row["run_context"]["cost_prompt_version"],
            tables.model_invocations.c.status == "succeeded",
        )
    ).first()
    if invocation is None:
        raise ProductWorkError("缺少实际成功的成本建议模型回执")
    current = rebuild(c, row["tenant_id"], row["project_id"], snapshot)
    if current["digest"] != snapshot["digest"]:
        raise ProductWorkError("原成本资料已变化，请重新准备")
    validate_assessment(output, snapshot)
    if output.disposition == "insufficient_evidence":
        return None
    if not FindingQualityService.is_output_allowed_connection(
        c,
        tenant_id=row["tenant_id"],
        agent_key="engineering_intelligence",
        finding_type="cost_reduction",
    ):
        raise ProductWorkError("成本建议候选输出已被质量控制收窄")
    origin = "cost-reduction:" + snapshot["digest"]
    prior = c.execute(
        select(tables.findings.c.id).where(
            tables.findings.c.tenant_id == row["tenant_id"],
            tables.findings.c.run_id == row["id"],
            tables.findings.c.origin_key == origin,
        )
    ).scalar_one_or_none()
    if prior:
        return UUID(str(prior))
    identity = uuid4()
    payload = {
        "source_digest": snapshot["digest"],
        "selection": snapshot["selection"],
        "assessment": output.model_dump(mode="json"),
        "reference_labels": {
            r["reference_id"]: r["label"] for r in snapshot["model_context"]["references"]
        },
    }
    c.execute(
        tables.findings.insert().values(
            id=identity,
            tenant_id=row["tenant_id"],
            project_id=row["project_id"],
            run_id=row["id"],
            model_invocation_id=invocation_id,
            agent_key="engineering_intelligence",
            finding_type="cost_reduction",
            origin_key=origin,
            status="pending_review",
            title="成本建议方案待审稿",
            summary="核对原费用、预期差额及质量／时间／供方／NRE代价；" + output.coverage_limits,
            proposed_payload=payload,
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
            finding_id=identity,
            action="created",
            actor_user_id=None,
            to_status="pending_review",
            detail={"source": "cost_reduction_sources", "source_digest": snapshot["digest"]},
            created_at=created_at,
        )
    )
    EventAuditWriter(
        c,
        tenant_id=row["tenant_id"],
        project_id=row["project_id"],
        actor_user_id=row["requested_by_user_id"],
    ).record(
        EventDraft(
            event_id=f"ai-finding:{identity}:created",
            event_type="AI_FINDING_CREATED",
            source="ai_runtime",
            entity_id=identity,
            occurred_at=created_at,
            payload={"finding_id": str(identity), "agent_run_id": str(row["id"])},
        ),
        AuditDraft(
            action="finding.create_cost_reduction",
            after_snapshot={"finding_id": str(identity)},
            context={
                "source_digest": snapshot["digest"],
                "model_invocation_id": str(invocation_id),
            },
        ),
    )
    return identity


if TYPE_CHECKING:
    from app.domain.findings import FindingRecord


class CostChoice(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    key: str = Field(min_length=1, max_length=80)
    disposition: Literal["adopt", "exclude"]
    reason: Text
    draft: AlternativeDraft | None = None
    expected_digest: Digest | None = None

    @model_validator(mode="after")
    def complete(self) -> CostChoice:
        if self.disposition == "adopt":
            if self.draft is None or self.expected_digest is None:
                raise ValueError("采用项须补齐实际方案并预览费用、原文件及代价")
            if self.draft.previous_id is not None or self.draft.status != "proposed":
                raise ValueError("建议应用只能建立新备选，原方案请沿修订入口办理")
        elif self.draft is not None or self.expected_digest is not None:
            raise ValueError("不采用项只保留理由，不提交待应用方案")
        return self


class CostReview(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reason: Text
    scope_and_limits: Text
    choices: list[CostChoice] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def complete(self) -> CostReview:
        if len({v.key for v in self.choices}) != len(self.choices):
            raise ValueError("原建议须逐项核对，不可重复")
        if not any(v.disposition == "adopt" for v in self.choices):
            raise ValueError("全部不采用时请填写理由并拒绝候选")
        return self


class CostReductionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_digest: Digest
    selection: Selection
    assessment: CostAssessment
    reference_labels: dict[str, str]
    review: CostReview | None = None
    details_confirmed: bool = False


def authorize(c: Connection, finding: FindingRecord, actor_id: UUID, *, write: bool = True) -> Any:
    from app.ai.project_discussion_sources import actor
    from app.domain.cost_definition_feedback import cost_access

    context = actor(c, finding.tenant_id, actor_id)
    cost_access(c, context, finding.project_id, write=write)
    rc = c.execute(
        select(tables.agent_runs.c.run_context).where(
            tables.agent_runs.c.tenant_id == finding.tenant_id,
            tables.agent_runs.c.project_id == finding.project_id,
            tables.agent_runs.c.id == finding.run_id,
        )
    ).scalar_one()
    discussion_id = rc.get("cost_discussion_run_id")
    if discussion_id:
        from app.ai.change_discussion_runs import binding
        from app.ai.discussion_sources import require_disclosure

        if write:
            from app.ai.rollout_guard import require_live_key

            require_live_key("engineering_intelligence.cost_discussion_followup")
        require_disclosure(
            c, finding.tenant_id, actor_id, binding(c, finding.tenant_id, UUID(discussion_id))
        )
    return context


def validate_review(
    c: Connection, finding: FindingRecord, payload: CostReductionPayload, actor_id: UUID
) -> dict[str, Any]:
    from app.ai.cost_reduction_preparation import rebuild, validate_assessment

    context = authorize(c, finding, actor_id)
    if payload.review is None or not payload.details_confirmed:
        raise ProductWorkError("请逐项核对方案、费用范围、各类代价、实际文件及缺项")
    original = payload.model_dump(mode="json", exclude={"review", "details_confirmed"})
    if original != {
        k: v
        for k, v in finding.proposed_payload.items()
        if k not in {"review", "details_confirmed"}
    }:
        raise ProductWorkError("原建议及引用不可改写，请在人工方案栏记录调整")
    run = c.execute(
        select(tables.agent_runs.c.run_context).where(
            tables.agent_runs.c.tenant_id == finding.tenant_id,
            tables.agent_runs.c.project_id == finding.project_id,
            tables.agent_runs.c.id == finding.run_id,
            tables.agent_runs.c.context_version == "cost-reduction-request-v1",
        )
    ).scalar_one_or_none()
    snapshot = run.get("cost_source") if run else None
    if not snapshot or snapshot["digest"] != payload.source_digest:
        raise ProductWorkError("候选缺少原运行固定的成本资料")
    current = rebuild(c, finding.tenant_id, finding.project_id, snapshot)
    if current["digest"] != payload.source_digest:
        raise ProductWorkError("原成本依据已变化，请按当前资料重新准备")
    validate_assessment(payload.assessment, snapshot)
    if payload.assessment.disposition != "proposal":
        raise ProductWorkError("资料不足结果不能应用为实际方案")
    if {v.key for v in payload.review.choices} != {o.key for o in payload.assessment.options}:
        raise ProductWorkError("每项原建议均须记录采用或不采用理由")
    for choice in payload.review.choices:
        if choice.disposition != "adopt":
            continue
        assert choice.draft is not None
        if choice.draft.observation_id != payload.selection.observation_id:
            raise ProductWorkError("采用方案须保留本次固定的Cost Gap观察")
        observed = alternative_preview(c, context, finding.project_id, choice.draft)
        if observed["digest"] != choice.expected_digest:
            raise ProductWorkError("人工方案或费用依据已变化，请重新预览后核对")
    return dict(snapshot)


def apply_package(
    c: Connection,
    *,
    finding: FindingRecord,
    payload: CostReductionPayload,
    actor_user_id: UUID,
    applied_at: datetime,
) -> UUID:
    snapshot = validate_review(c, finding, payload, actor_user_id)
    context = authorize(c, finding, actor_user_id)
    assert payload.review is not None
    a = tables.cost_reduction_applications
    if c.execute(
        select(a.c.id).where(
            a.c.tenant_id == finding.tenant_id,
            a.c.project_id == finding.project_id,
            a.c.source_digest == payload.source_digest,
        )
    ).scalar_one_or_none():
        raise ProductWorkError("相同成本依据已建立方案，请继续比较或修订原备选")
    identity = uuid4()
    c.execute(
        a.insert().values(
            id=identity,
            tenant_id=finding.tenant_id,
            project_id=finding.project_id,
            finding_id=finding.id,
            run_id=finding.run_id,
            source_digest=payload.source_digest,
            source_snapshot=snapshot,
            review=payload.review.model_dump(mode="json"),
            created_by_user_id=actor_user_id,
            created_at=applied_at,
        )
    )
    for choice in payload.review.choices:
        if choice.disposition != "adopt":
            continue
        assert choice.draft is not None and choice.expected_digest is not None
        saved = CostAlternativeService.save_in_connection(
            c,
            context,
            finding.project_id,
            AlternativeSave(
                request_id=uuid4(),
                expected_digest=choice.expected_digest,
                draft=choice.draft,
                checked=True,
            ),
        )
        c.execute(
            tables.cost_reduction_items.insert().values(
                id=uuid4(),
                tenant_id=finding.tenant_id,
                project_id=finding.project_id,
                application_id=identity,
                proposal_key=choice.key,
                alternative_id=UUID(saved["id"]),
            )
        )
    EventAuditWriter(
        c, tenant_id=finding.tenant_id, project_id=finding.project_id, actor_user_id=actor_user_id
    ).record(
        EventDraft(
            event_id=f"cost-reduction:{identity}",
            event_type="COST_REDUCTION_APPLIED",
            source="cost_service",
            entity_id=identity,
            occurred_at=applied_at,
            payload={"finding_id": str(finding.id), "application_id": str(identity)},
        ),
        AuditDraft(
            action="cost.reduction.applied",
            after_snapshot={
                "application_id": str(identity),
                "finding_id": str(finding.id),
                "source_digest": payload.source_digest,
            },
        ),
    )
    return identity


def applications(c: Connection, tenant: UUID, project: UUID, finding_id: UUID) -> dict[str, Any]:
    from app.domain.cost_alternatives import latest

    a, i, t = (
        tables.cost_reduction_applications,
        tables.cost_reduction_items,
        tables.cost_alternatives,
    )
    app = (
        c.execute(
            select(a).where(
                a.c.tenant_id == tenant, a.c.project_id == project, a.c.finding_id == finding_id
            )
        )
        .mappings()
        .one_or_none()
    )
    if app is None:
        return {"application": None, "items": []}
    items = (
        c.execute(
            select(i.c.proposal_key, t)
            .join(
                t,
                (t.c.tenant_id == i.c.tenant_id)
                & (t.c.project_id == i.c.project_id)
                & (t.c.id == i.c.alternative_id),
            )
            .where(
                i.c.application_id == app["id"], i.c.tenant_id == tenant, i.c.project_id == project
            )
            .order_by(i.c.proposal_key)
        )
        .mappings()
        .all()
    )
    return {
        "application": _plain(
            {k: app[k] for k in ("id", "finding_id", "review", "created_by_user_id", "created_at")}
        ),
        "items": [
            {
                "proposal_key": v["proposal_key"],
                "alternative": _plain(dict(v)),
                "current": _plain(dict(latest(c, tenant, project, v["root_id"]))),
            }
            for v in items
        ],
    }
