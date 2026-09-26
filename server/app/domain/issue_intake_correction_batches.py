"""Atomic, named batches of original source-association corrections."""

from typing import Any, Literal
from uuid import UUID, uuid4, uuid5

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Engine, or_, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.conversations import ConversationError
from app.domain.issue_intake_compensations import CompensationSources
from app.domain.issue_intake_corrections import (
    IssueIntakeCorrections,
    SourceCorrection,
    public_source,
    source_states,
)
from app.domain.issue_intake_reuse import target_snapshot
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class CorrectionPreview(CompensationSources):
    before_created_at: AwareDatetime | None = None
    before_id: UUID | None = None

    @model_validator(mode="after")
    def cursor_pair(self) -> "CorrectionPreview":
        if (self.before_created_at is None) != (self.before_id is None):
            raise ValueError("批次分页位置不完整")
        return self


class CorrectionEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source_row_id: UUID
    expected_revision: int = Field(ge=0)
    expected_current_updated_at: AwareDatetime | None = None
    action: Literal["withdraw", "reassign"]
    target_issue_id: UUID | None = None
    expected_target_updated_at: AwareDatetime | None = None
    reason: str = Field(min_length=1, max_length=2000)
    impact_note: str = Field(min_length=1, max_length=4000)

    def correction(self, batch_request: UUID) -> SourceCorrection:
        return SourceCorrection(
            **self.model_dump(exclude={"source_row_id"}),
            request_id=uuid5(batch_request, str(self.source_row_id)),
            acknowledge_history=True,
        )

    @model_validator(mode="after")
    def action_target(self) -> "CorrectionEntry":
        self.correction(self.source_row_id)
        return self


class CorrectionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    reason: str = Field(min_length=1, max_length=4000)
    entries: list[CorrectionEntry] = Field(min_length=1, max_length=50)
    acknowledge_history: Literal[True]

    @model_validator(mode="after")
    def unique_sources(self) -> "CorrectionBatch":
        if len({item.source_row_id for item in self.entries}) != len(self.entries):
            raise ValueError("同一来源在本批只处理一次")
        self.entries.sort(key=lambda item: str(item.source_row_id))
        return self


class IssueIntakeCorrectionBatches:
    def __init__(self, engine: Engine):
        self.engine = engine

    def preview(self, ctx: AuthContext, project: UUID, body: CorrectionPreview) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            KnowledgeCorrectionService._authorize(
                c, ctx.tenant.id, ctx.user.id, project, Action.WORK_ITEM_VIEW
            )
            t = tables.issue_intake_rows
            sources = (
                c.execute(
                    select(t)
                    .where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.project_id == project,
                        t.c.id.in_(body.source_ids),
                    )
                    .order_by(t.c.id)
                )
                .mappings()
                .all()
            )
            if len(sources) != len(body.source_ids):
                raise ConversationError("所选来源不完整或不属于本项目，请重新读取")
            states = source_states(c, ctx.tenant.id, list(sources))
            ids = {
                UUID(value["current_issue_id"])
                for value in states.values()
                if value["current_issue_id"]
            }
            issues = (
                {
                    str(row["id"]): target_snapshot(row)
                    for row in c.execute(
                        select(tables.issues).where(
                            tables.issues.c.tenant_id == ctx.tenant.id,
                            tables.issues.c.project_id == project,
                            tables.issues.c.id.in_(ids),
                        )
                    ).mappings()
                }
                if ids
                else {}
            )
            batches = tables.issue_intake_correction_batches
            history_query = select(batches).where(
                batches.c.tenant_id == ctx.tenant.id,
                batches.c.project_id == project,
                or_(
                    *[
                        batches.c.results.contains([{"source_row_id": str(identity)}])
                        for identity in body.source_ids
                    ]
                ),
            )
            if body.before_created_at is not None:
                history_query = history_query.where(
                    or_(
                        batches.c.created_at < body.before_created_at,
                        (batches.c.created_at == body.before_created_at)
                        & (batches.c.id < body.before_id),
                    )
                )
            history = (
                c.execute(
                    history_query.order_by(batches.c.created_at.desc(), batches.c.id.desc()).limit(
                        21
                    )
                )
                .mappings()
                .all()
            )
            return {
                "batches": [_plain(row) for row in history[:20]],
                "next": {
                    "before_created_at": history[19]["created_at"].isoformat(),
                    "before_id": str(history[19]["id"]),
                }
                if len(history) > 20
                else None,
                "entries": [
                    {
                        "source": public_source(row),
                        "current_source": states[row["id"]],
                        "current_issue": issues.get(states[row["id"]]["current_issue_id"]),
                    }
                    for row in sources
                ],
            }

    def read(self, ctx: AuthContext, project: UUID, identity: UUID) -> dict[str, Any]:
        with self.engine.connect() as c:
            KnowledgeCorrectionService._authorize(
                c, ctx.tenant.id, ctx.user.id, project, Action.WORK_ITEM_VIEW
            )
            t = tables.issue_intake_correction_batches
            row = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.project_id == project,
                        t.c.id == identity,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ConversationError("本项目没有此批来源纠错回执")
            return _plain(row)

    def apply(self, ctx: AuthContext, project: UUID, body: CorrectionBatch) -> dict[str, Any]:
        signature = digest(body.model_dump(mode="json", exclude={"request_id"}))
        with self.engine.begin() as c:
            KnowledgeCorrectionService._authorize(
                c, ctx.tenant.id, ctx.user.id, project, Action.WORK_ITEM_EDIT
            )
            if not lock_project_write_scope(c, tenant_id=ctx.tenant.id, project_id=project):
                raise ConversationError("项目当前不可办理")
            t = tables.issue_intake_correction_batches
            prior = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.project_id == project,
                        t.c.request_id == body.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior is not None:
                if prior["request_digest"] != signature:
                    raise ConversationError("本请求已对应其他纠错内容，请读取原批次")
                return _plain(prior)
            results = []
            service = IssueIntakeCorrections(self.engine)
            for item in body.entries:
                try:
                    receipt = service.correct(
                        ctx,
                        project,
                        item.source_row_id,
                        item.correction(body.request_id),
                        connection=c,
                    )["receipt"]
                except ConversationError as error:
                    raise ConversationError(
                        f"本批未保存；来源 {item.source_row_id}：{error}"
                    ) from error
                results.append(
                    {
                        "source_row_id": str(item.source_row_id),
                        "correction_id": receipt["id"],
                        "revision": receipt["revision"],
                        "action": receipt["action"],
                        "previous_issue_id": receipt["previous_issue_id"],
                        "target_issue_id": receipt["target_issue_id"],
                    }
                )
            identity = uuid4()
            row = (
                c.execute(
                    t.insert()
                    .values(
                        id=identity,
                        tenant_id=ctx.tenant.id,
                        project_id=project,
                        request_id=body.request_id,
                        request_digest=signature,
                        reason=body.reason,
                        results=results,
                        created_by_user_id=ctx.user.id,
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            EventAuditWriter(
                c, tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, project_id=project
            ).record(
                EventDraft(
                    event_id=f"issue-intake-correction-batch:{identity}",
                    event_type="ISSUE_INTAKE_SOURCE_RECORDED",
                    source="issue_intake_service",
                    entity_id=body.entries[0].source_row_id,
                    payload={
                        "source_row_id": str(body.entries[0].source_row_id),
                        "record_id": str(identity),
                        "action": "batch_corrected",
                    },
                ),
                AuditDraft(
                    action="issue_intake.correct_batch",
                    after_snapshot={"batch_id": str(identity), "results": results},
                    context={"reason": body.reason},
                ),
            )
            return _plain(row)
