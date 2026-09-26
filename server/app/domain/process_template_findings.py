"""Organization-only Finding review and separate atomic candidate application."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID, uuid5

from pydantic import Field
from sqlalchemy import Connection, Engine, RowMapping, func, select

from app.ai.process_template_context import bound_source
from app.ai.quality import FindingQualityService
from app.ai.rollout_guard import require_live_key
from app.auth.repository import AuthContext
from app.contracts.process_template_proposal import Assessment, materialize, output_type
from app.db.schema import tables
from app.domain.process_template_configuration import Input
from app.domain.process_template_gates import baseline
from app.domain.process_template_reminders import policy as reminder_policy
from app.domain.process_templates import (
    ProcessTemplateService,
    TemplateRevisionInput,
    authorize,
    lock,
)
from app.domain.product_workspace import _plain, digest
from app.domain.project_templates import ProjectTemplateError
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

CAPABILITY = "knowledge_lite.process_template_configuration"
FINDING_TYPE = "process_template_configuration"


class TemplateFindingReview(Input):
    decision: Literal["accepted", "rejected"]
    assessment: Assessment | None = None
    comment: str = Field(min_length=1, max_length=5000)
    expected_preview_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class TemplateFindingPreview(Input):
    assessment: Assessment


def preview_digest(finding_id: UUID, proposal: dict[str, Any], original: dict[str, Any]) -> str:
    return digest({"finding_id": str(finding_id), "source": original, "proposal": proposal})


class TemplateFindingApply(Input):
    confirmed: Literal[True]


def payload(source: dict[str, Any], output: Assessment) -> dict[str, Any]:
    return {
        "brief_id": source["id"],
        "assessment": output.model_dump(mode="json"),
        **materialize(source, output),
    }


def row(c: Connection, ctx: AuthContext, identity: UUID, *, update: bool = False) -> RowMapping:
    authorize(c, ctx)
    f = tables.findings
    query = select(f).where(
        f.c.tenant_id == ctx.tenant.id,
        f.c.id == identity,
        f.c.scope_kind == "tenant",
        f.c.finding_type == FINDING_TYPE,
    )
    if update:
        query = query.with_for_update()
    finding = c.execute(query).mappings().one_or_none()
    if finding is None:
        raise ProjectTemplateError("组织配置建议不存在")
    return finding


def source(c: Connection, ctx: AuthContext, finding: RowMapping) -> dict[str, Any]:
    r = tables.agent_runs
    run = (
        c.execute(
            select(r).where(
                r.c.tenant_id == ctx.tenant.id,
                r.c.id == finding["run_id"],
                r.c.scope_kind == "tenant",
            )
        )
        .mappings()
        .one()
    )
    if run["status"] != "succeeded":
        raise ProjectTemplateError("原生成尚未成功完成")
    original = bound_source(c, ctx.tenant.id, run["run_context"])
    return dict(original["source_snapshot"])


def contract_version(c: Connection, ctx: AuthContext, finding: RowMapping) -> str:
    context = c.execute(
        select(tables.agent_runs.c.run_context).where(
            tables.agent_runs.c.tenant_id == ctx.tenant.id,
            tables.agent_runs.c.id == finding["run_id"],
            tables.agent_runs.c.scope_kind == "tenant",
        )
    ).scalar_one()
    version = str(context["process_template_prompt_version"])
    if context["process_template_schema_digest"] != digest(
        output_type(version).model_json_schema()
    ):
        raise ProjectTemplateError("原建议的结构合同已变化，不能用另一版本审阅或应用")
    return version


def pinned_assessment(
    c: Connection,
    ctx: AuthContext,
    finding: RowMapping,
    value: Any,
) -> Assessment:
    if isinstance(value, Input):
        value = value.model_dump(mode="json")
    return output_type(contract_version(c, ctx, finding)).model_validate(value)


def event(c: Connection, ctx: AuthContext, finding: RowMapping, action: str) -> None:
    EventAuditWriter(c, tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id).record(
        EventDraft(
            event_id=f"process-template-finding:{finding['id']}:{action}",
            event_type="PROCESS_TEMPLATE_FINDING_RECORDED",
            source="process_template_service",
            entity_id=finding["id"],
            payload={"finding_id": str(finding["id"]), "action": action},
        ),
        AuditDraft(
            action=f"process_template_finding.{action}",
            after_snapshot={
                "finding_id": str(finding["id"]),
                "status": finding["status"],
                "review_comment": finding["review_comment"],
                "applied_entity_id": str(finding["applied_entity_id"])
                if finding["applied_entity_id"]
                else None,
            },
        ),
    )


class ProcessTemplateFindingService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(self, ctx: AuthContext, identity: UUID) -> dict[str, Any]:
        with self.engine.connect() as c:
            finding = row(c, ctx, identity)
            if finding["status"] != "applied":
                require_live_key(CAPABILITY)
            current, error = True, None
            try:
                source(c, ctx, finding)
            except (ProjectTemplateError, ValueError) as failure:
                current, error = False, str(failure)
            from app.domain.process_template_briefs import brief

            original = brief(c, ctx, UUID(finding["proposed_payload"]["brief_id"]))
            return {
                "finding": _plain(finding),
                "source_current": current,
                "source_error": error,
                "original_source": original["source_snapshot"],
                "assessment_version": contract_version(c, ctx, finding),
                "gate_baseline": baseline(original["source_snapshot"]["base_snapshot"]),
                "reminder_policy": reminder_policy(
                    original["source_snapshot"]["base_snapshot"]
                ).model_dump(mode="json"),
            }

    def preview(
        self, ctx: AuthContext, identity: UUID, body: TemplateFindingPreview
    ) -> dict[str, Any]:
        require_live_key(CAPABILITY)
        with self.engine.connect() as c:
            finding = row(c, ctx, identity)
            if finding["status"] != "pending_review":
                raise ProjectTemplateError("此建议已审阅，不能再编辑接受内容")
            original = source(c, ctx, finding)
            prepared = payload(original, pinned_assessment(c, ctx, finding, body.assessment))
            return {
                "proposal": prepared,
                "preview_digest": preview_digest(identity, prepared, original),
            }

    def review(
        self, ctx: AuthContext, identity: UUID, body: TemplateFindingReview
    ) -> dict[str, Any]:
        require_live_key(CAPABILITY)
        with self.engine.begin() as c:
            finding = row(c, ctx, identity, update=True)
            if body.decision == "rejected" and body.assessment is not None:
                raise ProjectTemplateError("拒绝建议不保存接受内容")
            # Retry identical recorded decisions without mutating historical evidence.
            if finding["status"] in {"accepted", "rejected", "applied"}:
                prior_decision = "accepted" if finding["status"] == "applied" else finding["status"]
                assessment = (
                    pinned_assessment(c, ctx, finding, body.assessment).model_dump(mode="json")
                    if body.assessment
                    else finding["proposed_payload"]["assessment"]
                )
                if (
                    prior_decision == body.decision
                    and finding["reviewed_by_user_id"] == ctx.user.id
                    and finding["review_comment"] == body.comment
                    and (
                        body.decision == "rejected"
                        or finding["accepted_payload"]["assessment"] == assessment
                    )
                ):
                    return _plain(finding)
                raise ProjectTemplateError("此建议已审阅，不能覆盖原决定")
            if finding["status"] != "pending_review":
                raise ProjectTemplateError("此建议当前不可审阅")
            accepted = None
            if body.decision == "accepted":
                original = source(c, ctx, finding)
                output = pinned_assessment(
                    c, ctx, finding, body.assessment or finding["proposed_payload"]["assessment"]
                )
                accepted = payload(original, output)
                edited = accepted != finding["proposed_payload"]
                if (edited or body.expected_preview_digest is not None) and (
                    body.expected_preview_digest != preview_digest(identity, accepted, original)
                ):
                    raise ProjectTemplateError("请先预览本次编辑的实际配置差异，再接受建议")
            stamp = c.execute(select(func.clock_timestamp())).scalar_one()
            updated = (
                c.execute(
                    tables.findings.update()
                    .where(tables.findings.c.id == identity)
                    .values(
                        status=body.decision,
                        accepted_payload=accepted,
                        reviewed_by_user_id=ctx.user.id,
                        reviewed_at=stamp,
                        review_comment=body.comment,
                        updated_at=stamp,
                    )
                    .returning(tables.findings)
                )
                .mappings()
                .one()
            )
            event(c, ctx, updated, body.decision)
            FindingQualityService(self.engine).evaluate_connection(
                c, tenant_id=ctx.tenant.id, evaluated_at=stamp
            )
            return _plain(updated)

    def apply(self, ctx: AuthContext, identity: UUID) -> dict[str, Any]:
        require_live_key(CAPABILITY)
        with self.engine.begin() as c:
            # Acquire the template lock before Finding row locks, as revision creation does.
            before = row(c, ctx, identity)
            original_id = UUID(before["proposed_payload"]["brief_id"])
            from app.domain.process_template_briefs import brief

            original = brief(c, ctx, original_id)
            lock(c, ctx, original["template_id"])
            finding = row(c, ctx, identity, update=True)
            if finding["status"] == "applied":
                return _plain(finding)
            if finding["status"] != "accepted":
                raise ProjectTemplateError("先接受建议，再单独应用为配置候选")
            current = source(c, ctx, finding)
            checked = payload(
                current,
                pinned_assessment(c, ctx, finding, finding["accepted_payload"]["assessment"]),
            )
            if checked != finding["accepted_payload"]:
                raise ProjectTemplateError("接受时的配置合同已变化，请重新准备建议")
            revision = ProcessTemplateService(self.engine).create(
                ctx,
                TemplateRevisionInput(
                    request_id=uuid5(identity, "process-template-finding-apply.v1"),
                    template_id=original["template_id"],
                    base_template_id=original["base_template_id"],
                    base_version=original["base_version"],
                    base_digest=original["base_digest"],
                    expected_release_id=original["base_release_id"],
                    source_brief_id=original["id"],
                    reason=finding["review_comment"],
                    configuration=checked["configuration"],
                ),
                connection=c,
                source_finding_id=identity,
            )
            stamp = c.execute(select(func.clock_timestamp())).scalar_one()
            updated = (
                c.execute(
                    tables.findings.update()
                    .where(tables.findings.c.id == identity)
                    .values(
                        status="applied",
                        applied_entity_type="process_template_revision",
                        applied_entity_id=UUID(revision["id"]),
                        applied_by_user_id=ctx.user.id,
                        applied_at=stamp,
                        updated_at=stamp,
                    )
                    .returning(tables.findings)
                )
                .mappings()
                .one()
            )
            event(c, ctx, updated, "applied")
            FindingQualityService(self.engine).evaluate_connection(
                c, tenant_id=ctx.tenant.id, evaluated_at=stamp
            )
            return _plain(updated)
