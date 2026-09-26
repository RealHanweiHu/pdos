"""Atomic source corrections within an actual historical Decision import batch."""

from typing import Any, Literal, Self
from uuid import UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.conversations import ConversationError
from app.domain.decision_intake_corrections import (
    DecisionIntakeCorrections,
    DecisionSourceCorrection,
    basis,
)
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.knowledge_push import KnowledgeAccessError
from app.domain.product_workspace import _plain, digest
from app.domain.project_intake import authorize
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class DecisionBatchEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source_row_id: UUID
    expected_revision: int = Field(ge=0)
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    action: Literal["withdraw", "reassign"]
    target_decision_id: UUID | None = None
    expected_decision_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    target_issue_id: UUID | None = None
    expected_issue_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=2000)
    impact_note: str = Field(min_length=1, max_length=4000)

    def correction(self, request_id: UUID) -> DecisionSourceCorrection:
        return DecisionSourceCorrection(
            **self.model_dump(exclude={"source_row_id"}),
            request_id=uuid5(request_id, str(self.source_row_id)),
            acknowledge_history=True,
        )

    @model_validator(mode="after")
    def valid_target(self) -> Self:
        self.correction(self.source_row_id)
        return self


class DecisionCorrectionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    reason: str = Field(min_length=1, max_length=4000)
    entries: list[DecisionBatchEntry] = Field(min_length=1, max_length=50)
    acknowledge_history: Literal[True]

    @model_validator(mode="after")
    def unique_sources(self) -> Self:
        if len({item.source_row_id for item in self.entries}) != len(self.entries):
            raise ValueError("同一来源在本批只处理一次")
        self.entries.sort(key=lambda item: str(item.source_row_id))
        return self


def import_scope(c: Connection, ctx: AuthContext, project: UUID, batch: UUID) -> list[UUID]:
    t = tables.decision_intake_batches
    row = (
        c.execute(
            select(t).where(
                t.c.tenant_id == ctx.tenant.id,
                t.c.project_id == project,
                t.c.id == batch,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ConversationError("本项目没有此导入批次")
    return sorted(
        {
            UUID(item["source_row_id"])
            for item in row["results"]
            if item.get("source_row_id") and item["status"] in {"created", "linked", "reused"}
        },
        key=str,
    )


class DecisionIntakeCorrectionBatches:
    def __init__(self, engine: Engine):
        self.engine = engine

    def preview(
        self,
        ctx: AuthContext,
        project: UUID,
        batch: UUID,
        offset: int = 0,
        before_id: UUID | None = None,
    ) -> dict[str, Any]:
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            authorize(c, ctx, project)
            identities = import_scope(c, ctx, project, batch)
            r, h, u = (
                tables.decision_intake_rows,
                tables.decision_intake_correction_batches,
                tables.users,
            )
            sources = list(
                c.execute(
                    select(r)
                    .where(
                        r.c.tenant_id == ctx.tenant.id,
                        r.c.project_id == project,
                        r.c.id.in_(identities[offset : offset + 50]),
                    )
                    .order_by(r.c.id)
                ).mappings()
            )
            history = (
                select(h, u.c.display_name.label("actor_name"))
                .join(
                    u,
                    (u.c.tenant_id == h.c.tenant_id) & (u.c.id == h.c.created_by_user_id),
                )
                .where(
                    h.c.tenant_id == ctx.tenant.id,
                    h.c.project_id == project,
                    h.c.import_batch_id == batch,
                )
            )
            if before_id is not None:
                history = history.where(h.c.id < before_id)
            receipts = list(c.execute(history.order_by(h.c.id.desc()).limit(21)).mappings())
            can_edit = True
            try:
                KnowledgeCorrectionService._authorize(
                    c, ctx.tenant.id, ctx.user.id, project, Action.WORK_ITEM_EDIT
                )
            except KnowledgeAccessError:
                can_edit = False
            return {
                "can_edit": can_edit,
                "total": len(identities),
                "offset": offset,
                "next_offset": offset + 50 if offset + 50 < len(identities) else None,
                "entries": [
                    {
                        "source": {
                            key: value
                            for key, value in _plain(row).items()
                            if key not in {"tenant_id", "preview_id"}
                        },
                        **basis(c, ctx.tenant.id, project, row),
                    }
                    for row in sources
                ],
                "batches": [_plain(row) for row in receipts[:20]],
                "next_id": str(receipts[19]["id"]) if len(receipts) > 20 else None,
            }

    def apply(
        self, ctx: AuthContext, project: UUID, batch: UUID, body: DecisionCorrectionBatch
    ) -> dict[str, Any]:
        signature = digest(
            {"batch": str(batch), "body": body.model_dump(mode="json", exclude={"request_id"})}
        )
        with self.engine.begin() as c:
            authorize(c, ctx, project, write=True)
            if not lock_project_write_scope(c, tenant_id=ctx.tenant.id, project_id=project):
                raise ConversationError("项目当前不可办理")
            allowed = set(import_scope(c, ctx, project, batch))
            if {item.source_row_id for item in body.entries} - allowed:
                raise ConversationError("所选来源不属于本批已登记范围")
            t = tables.decision_intake_correction_batches
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
                    raise ConversationError("本请求已对应其他批量纠错内容，请读取原回执")
                return _plain(prior)
            results = []
            service = DecisionIntakeCorrections(self.engine)
            for item in body.entries:
                try:
                    result = service.correct(
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
                        "correction_id": result["id"],
                        **{
                            key: result[key]
                            for key in (
                                "revision",
                                "action",
                                "previous_decision_id",
                                "previous_issue_id",
                                "target_decision_id",
                                "target_issue_id",
                                "reason",
                                "impact_note",
                                "before_snapshot",
                                "after_snapshot",
                            )
                        },
                    }
                )
            identity = uuid4()
            receipt = (
                c.execute(
                    t.insert()
                    .values(
                        id=identity,
                        tenant_id=ctx.tenant.id,
                        project_id=project,
                        import_batch_id=batch,
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
                    event_id=f"decision-intake-correction-batch:{identity}",
                    event_type="DECISION_INTAKE_SOURCE_RECORDED",
                    source="decision_intake_service",
                    entity_id=body.entries[0].source_row_id,
                    payload={
                        "source_row_id": str(body.entries[0].source_row_id),
                        "record_id": str(identity),
                        "action": "batch_corrected",
                    },
                ),
                AuditDraft(
                    action="decision_intake.correct_batch",
                    after_snapshot={
                        "batch_id": str(identity),
                        "import_batch_id": str(batch),
                        "results": results,
                    },
                    context={"reason": body.reason},
                ),
            )
            return _plain(receipt)
