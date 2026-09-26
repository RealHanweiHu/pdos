"""Private, source-bound human review of intake suggestions; application is separate."""

from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, RowMapping, String, cast, func, select, update

from app.ai.budget_ledger import BudgetLedgerError
from app.ai.intake_ai_context import CAPABILITY, FINDING_TYPE, RUN_VERSION, bound_source
from app.ai.quality import FindingQualityService
from app.ai.rollout_guard import require_live_key
from app.auth.repository import AuthContext
from app.contracts.intake_proposal import Input, IntakeOrganization, Text, materialize
from app.db.schema import tables
from app.domain.conversations import ConversationError
from app.domain.issue_intake_preview import IssueIntakePreviews
from app.domain.product_workspace import _plain, digest
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class Exclusion(Input):
    number: int = Field(ge=1, le=30)
    reason: Text


class DuplicateReview(Input):
    first: int = Field(ge=1, le=30)
    second: int = Field(ge=1, le=30)
    disposition: Literal["keep_separate", "exclude_first", "exclude_second"]
    reason: Text


class IntakeAssessment(Input):
    assessment: IntakeOrganization
    exclusions: tuple[Exclusion, ...] = Field(max_length=30)
    duplicate_reviews: tuple[DuplicateReview, ...] = Field(max_length=60)


class IntakeFindingReview(Input):
    decision: Literal["accepted", "rejected"]
    comment: Text
    edited: IntakeAssessment | None = None
    preview_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def complete(self) -> Self:
        if not self.comment.strip():
            raise ValueError("请填写核对意见")
        if self.decision == "accepted" and (self.edited is None or self.preview_digest is None):
            raise ValueError("接受前须提交人工核对稿及差异预览")
        if self.decision == "rejected" and (self.edited is not None or self.preview_digest):
            raise ValueError("拒绝时不保存接受稿")
        return self


def prepare(finding: Any, source: dict[str, Any], body: IntakeAssessment) -> dict[str, Any]:
    original = IntakeOrganization.model_validate(finding["proposed_payload"]["assessment"])
    old = {item.number: item for item in original.proposals}
    kept = {item.number for item in body.assessment.proposals}
    excluded = {item.number for item in body.exclusions}
    if not kept:
        raise ConversationError("全部排除时请直接拒绝这份建议")
    if (
        len(excluded) != len(body.exclusions)
        or excluded - old.keys()
        or kept & excluded
        or old.keys() - kept != excluded
        or any(not item.reason.strip() for item in body.exclusions)
    ):
        raise ConversationError("每条原建议须保留或明确排除并说明理由")
    expected = {
        tuple(sorted((item.first, item.second)))
        for item in (*original.possible_duplicates, *body.assessment.possible_duplicates)
    }
    actual = {tuple(sorted((item.first, item.second))) for item in body.duplicate_reviews}
    if actual != expected or len(actual) != len(body.duplicate_reviews):
        raise ConversationError("请逐对核对原AI提示和人工稿中的疑似重复项")
    for pair in body.duplicate_reviews:
        if not pair.reason.strip() or pair.first == pair.second:
            raise ConversationError("重复项须有具体核对理由")
        if pair.disposition == "keep_separate":
            valid = {pair.first, pair.second} <= kept
        elif pair.disposition == "exclude_first":
            valid = pair.first in excluded
        else:
            valid = pair.second in excluded
        if not valid:
            raise ConversationError("重复项处理与实际保留、排除结果不一致")
    try:
        materialized = materialize(source, body.assessment)
    except ValueError as error:
        raise ConversationError(str(error)) from error
    payload = {
        "version": "intake-human-review-v1",
        "brief_id": finding["proposed_payload"]["brief_id"],
        "source_digest": digest(source),
        **body.model_dump(mode="json"),
        **materialized,
    }
    changes = []
    current = {item.number: item for item in body.assessment.proposals}
    for number in sorted(old.keys() | current.keys()):
        before = old[number].model_dump(mode="json") if number in old else None
        after = current[number].model_dump(mode="json") if number in current else None
        status = (
            "added"
            if before is None
            else "excluded"
            if after is None
            else ("unchanged" if before == after else "changed")
        )
        fields_before = {
            item["name"]: item["citation"] for item in (before or {}).get("fields", [])
        }
        fields_after = {item["name"]: item["citation"] for item in (after or {}).get("fields", [])}
        changes.append(
            {
                "number": number,
                "status": status,
                "before": before,
                "after": after,
                "fields": [
                    {
                        "name": name,
                        "before": fields_before.get(name),
                        "after": fields_after.get(name),
                    }
                    for name in sorted(fields_before.keys() | fields_after.keys())
                    if fields_before.get(name) != fields_after.get(name)
                ],
            }
        )
    return {
        "accepted_payload": payload,
        "preview_digest": digest({"finding_id": str(finding["id"]), "payload": payload}),
        "changes": changes,
        "questions_before": list(original.open_questions),
        "questions_after": list(body.assessment.open_questions),
    }


class IntakeAiFindings:
    def __init__(self, engine: Engine):
        self.engine = engine
        self.scope = IssueIntakePreviews(engine)

    def rows(
        self,
        c: Connection,
        ctx: AuthContext,
        conversation: UUID,
        identity: UUID,
        *,
        write: bool = False,
    ) -> tuple[RowMapping, RowMapping, RowMapping]:
        conv = self.scope.scope(c, ctx, conversation, write=write)
        f, r, b = tables.findings, tables.agent_runs, tables.intake_ai_briefs
        query = (
            select(f)
            .join(r, (r.c.tenant_id == f.c.tenant_id) & (r.c.id == f.c.run_id))
            .join(
                b,
                (b.c.tenant_id == r.c.tenant_id)
                & (r.c.run_context["intake_brief_id"].astext == cast(b.c.id, String)),
            )
            .where(
                f.c.tenant_id == ctx.tenant.id,
                f.c.id == identity,
                f.c.project_id == conv["project_id"],
                f.c.finding_type == FINDING_TYPE,
                r.c.context_version == RUN_VERSION,
                r.c.requested_by_user_id == ctx.user.id,
                b.c.conversation_id == conversation,
                b.c.created_by_user_id == ctx.user.id,
            )
        )
        if write:
            query = query.with_for_update(of=f)
        finding = c.execute(query).mappings().one_or_none()
        if finding is None:
            raise ConversationError("这份整理建议不属于本人的当前会话")
        run = (
            c.execute(select(r).where(r.c.tenant_id == ctx.tenant.id, r.c.id == finding["run_id"]))
            .mappings()
            .one()
        )
        brief = (
            c.execute(
                select(b).where(
                    b.c.tenant_id == ctx.tenant.id,
                    b.c.id == UUID(run["run_context"]["intake_brief_id"]),
                )
            )
            .mappings()
            .one()
        )
        return finding, run, brief

    @staticmethod
    def current(c: Connection, ctx: AuthContext, run: RowMapping) -> None:
        try:
            bound_source(c, ctx.tenant.id, run["project_id"], ctx.user.id, run["run_context"])
        except BudgetLedgerError as error:
            raise ConversationError("原文、读取权限或运行合同已变化，请重新选择来源整理") from error

    def get(self, ctx: AuthContext, conversation: UUID, identity: UUID) -> dict[str, Any]:
        from app.domain.intake_ai_imports import completed_imports, import_previews
        from app.domain.intake_ai_observations import receipts

        require_live_key(CAPABILITY)
        with self.engine.connect() as c:
            finding, run, brief = self.rows(c, ctx, conversation, identity)
            reason = None
            try:
                self.current(c, ctx, run)
            except ConversationError as error:
                reason = str(error)
            return _plain(
                {
                    "finding": dict(finding),
                    "source": brief["source_snapshot"],
                    "source_current": reason is None,
                    "source_reason": reason,
                    "observation_applications": receipts(c, ctx, identity),
                    "import_previews": import_previews(c, ctx.tenant.id, identity),
                    "completed_imports": completed_imports(c, ctx.tenant.id, identity),
                }
            )

    def preview(
        self, ctx: AuthContext, conversation: UUID, identity: UUID, body: IntakeAssessment
    ) -> dict[str, Any]:
        require_live_key(CAPABILITY)
        with self.engine.begin() as c:
            finding, run, brief = self.rows(c, ctx, conversation, identity, write=True)
            if finding["status"] != "pending_review":
                raise ConversationError("此建议已有核对回执，请读取原结果")
            self.current(c, ctx, run)
            return prepare(finding, brief["source_snapshot"], body)

    def review(
        self, ctx: AuthContext, conversation: UUID, identity: UUID, body: IntakeFindingReview
    ) -> dict[str, Any]:
        require_live_key(CAPABILITY)
        with self.engine.begin() as c:
            finding, run, brief = self.rows(c, ctx, conversation, identity, write=True)
            prepared = (
                prepare(finding, brief["source_snapshot"], body.edited) if body.edited else None
            )
            payload = prepared["accepted_payload"] if prepared else None
            if prepared and prepared["preview_digest"] != body.preview_digest:
                raise ConversationError("人工稿与预览不一致，请重新查看差异后接受")
            if finding["status"] != "pending_review":
                if (
                    finding["status"] == body.decision
                    and finding["reviewed_by_user_id"] == ctx.user.id
                    and finding["review_comment"] == body.comment
                    and finding["accepted_payload"] == payload
                ):
                    return _plain(dict(finding))
                raise ConversationError("此建议已完成核对，原回执不可覆盖")
            if body.decision == "accepted":
                self.current(c, ctx, run)
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            values = {
                "status": body.decision,
                "reviewed_by_user_id": ctx.user.id,
                "reviewed_at": now,
                "review_comment": body.comment,
                "updated_at": now,
                "accepted_payload": payload,
            }
            c.execute(
                update(tables.findings)
                .where(
                    tables.findings.c.tenant_id == ctx.tenant.id, tables.findings.c.id == identity
                )
                .values(**values)
            )
            c.execute(
                tables.finding_actions.insert().values(
                    id=uuid4(),
                    tenant_id=ctx.tenant.id,
                    project_id=finding["project_id"],
                    finding_id=identity,
                    action=body.decision,
                    actor_user_id=ctx.user.id,
                    from_status="pending_review",
                    to_status=body.decision,
                    detail={"comment": body.comment, "preview_digest": body.preview_digest},
                    created_at=now,
                )
            )
            EventAuditWriter(
                c,
                tenant_id=ctx.tenant.id,
                actor_user_id=ctx.user.id,
                project_id=finding["project_id"],
            ).record(
                EventDraft(
                    event_id=f"intake-finding:{identity}:{body.decision}",
                    event_type="INTAKE_AI_FINDING_RECORDED",
                    source="intake_ai_service",
                    entity_id=identity,
                    payload={"finding_id": str(identity), "action": body.decision},
                    occurred_at=now,
                ),
                AuditDraft(
                    action=f"intake_ai_finding.{body.decision}",
                    before_snapshot={"finding_id": str(identity), "status": finding["status"]},
                    after_snapshot={
                        "finding_id": str(identity),
                        "status": body.decision,
                        "preview_digest": body.preview_digest,
                    },
                ),
            )
            FindingQualityService(self.engine).evaluate_connection(
                c, tenant_id=ctx.tenant.id, evaluated_at=now
            )
            return _plain(dict(finding) | values)
