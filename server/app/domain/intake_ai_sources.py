"""Immutable private source selections for subsequent intake organization runs."""

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, func, select

from app.auth.repository import AuthContext
from app.contracts.intake_proposal import SOURCE_VERSION, Kind
from app.db.schema import tables
from app.domain.conversation_attachments import (
    ConversationAttachmentService,
    message_attachment_ids,
)
from app.domain.conversations import ConversationError
from app.domain.issue_intake_preview import IssueIntakePreviews, source_identity
from app.domain.product_workspace import _plain, digest

MAX_FRAGMENTS = 200
MAX_CHARACTERS = 180000


class SourceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attachment_id: UUID
    expected_source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    first_ordinal: int = Field(ge=1)
    last_ordinal: int = Field(ge=1)

    @model_validator(mode="after")
    def ordered(self) -> "SourceSelection":
        if self.last_ordinal < self.first_ordinal:
            raise ValueError("原文片段范围应从小到大")
        return self


class IntakeBriefInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_revision: int = Field(ge=0)
    instruction: str = Field(min_length=1, max_length=4000)
    permission_basis: str = Field(min_length=1, max_length=2000)
    purpose: str = Field(min_length=1, max_length=2000)
    kinds: list[Kind] = Field(min_length=1, max_length=3)
    selections: list[SourceSelection] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def unique(self) -> "IntakeBriefInput":
        if len(set(self.kinds)) != len(self.kinds):
            raise ValueError("整理对象类型重复")
        self.kinds.sort()
        self.selections.sort(key=lambda item: (str(item.attachment_id), item.first_ordinal))
        previous: SourceSelection | None = None
        for item in self.selections:
            if previous and item.attachment_id == previous.attachment_id:
                if item.first_ordinal <= previous.last_ordinal:
                    raise ValueError("同附件的所选范围不能重复或交叠")
                if item.expected_source_digest != previous.expected_source_digest:
                    raise ValueError("同附件的原文版本须一致")
            previous = item
        return self


def check_source(row: Any) -> None:
    if (
        row["revoked_at"] is not None
        or row["classification"] != "internal"
        or row["status"] != "extracted"
        or Path(row["filename"]).suffix.lower() not in {".pdf", ".xlsx", ".eml"}
    ):
        raise ConversationError("请选择本消息内已抽取、未停止引用的内部PDF/XLSX/EML")


def freeze_sources(
    c: Connection, ctx: AuthContext, conversation: UUID, message: UUID, body: IntakeBriefInput
) -> dict[str, Any]:
    allowed = set(message_attachment_ids(c, ctx.tenant.id, message))
    if {item.attachment_id for item in body.selections} - allowed:
        raise ConversationError("所选来源须是本条已保存消息的实际附件")
    sources: dict[str, Any] = {}
    fragments = []
    total = 0
    for selection in body.selections:
        row = ConversationAttachmentService._row(
            c, ctx.tenant.id, conversation, selection.attachment_id
        )
        check_source(row)
        identity = source_identity(row)
        if digest(identity) != selection.expected_source_digest:
            raise ConversationError("附件来源已变化，请重新读取后选择")
        chosen = [
            item
            for item in row["fragments"]
            if selection.first_ordinal <= item["ordinal"] <= selection.last_ordinal
        ]
        if len(chosen) != selection.last_ordinal - selection.first_ordinal + 1:
            raise ConversationError("所选范围包含不存在的原文片段，请按实际片段编号选择")
        source = sources.setdefault(
            str(row["id"]),
            {
                "identity": identity,
                "fragment_count": len(row["fragments"]),
                "selected_count": 0,
            },
        )
        source["selected_count"] += len(chosen)
        for fragment in chosen:
            total += len(fragment["text"])
            fragments.append(
                _plain(fragment)
                | {
                    "attachment_id": str(row["id"]),
                    "reference_id": f"{row['id']}:{fragment['ordinal']}",
                }
            )
        if len(fragments) > MAX_FRAGMENTS or total > MAX_CHARACTERS:
            raise ConversationError("本次最多选200个片段、18万字，请缩小范围分批整理；原文不会截断")
    return {
        "version": SOURCE_VERSION,
        "instruction": body.instruction,
        "kinds": body.kinds,
        "permission_basis": body.permission_basis,
        "purpose": body.purpose,
        "selections": [item.model_dump(mode="json") for item in body.selections],
        "sources": sources,
        "fragments": fragments,
        "characters": total,
    }


def source_status(
    c: Connection, ctx: AuthContext, conversation: UUID, snapshot: dict[str, Any]
) -> dict[str, Any]:
    states = []
    for identity, source in snapshot["sources"].items():
        current = False
        try:
            row = ConversationAttachmentService._row(c, ctx.tenant.id, conversation, UUID(identity))
            check_source(row)
            current = source_identity(row) == source["identity"]
        except ConversationError:
            pass
        states.append({"attachment_id": identity, "current": current})
    return {"source_current": all(item["current"] for item in states), "source_states": states}


class IntakeAiSources:
    def __init__(self, engine: Engine):
        self.engine = engine
        self.scope = IssueIntakePreviews(engine)

    def list(
        self,
        ctx: AuthContext,
        conversation: UUID,
        message: UUID,
        before_revision: int | None = None,
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            self.scope.scope(c, ctx, conversation)
            self.scope.message(c, ctx, conversation, message)
            sources = []
            for identity in message_attachment_ids(c, ctx.tenant.id, message):
                row = ConversationAttachmentService._row(c, ctx.tenant.id, conversation, identity)
                try:
                    check_source(row)
                except ConversationError:
                    continue
                source = source_identity(row)
                sources.append(
                    {
                        "id": str(identity),
                        "filename": row["filename"],
                        "digest": digest(source),
                        "fragment_count": len(row["fragments"]),
                        "characters": sum(len(f["text"]) for f in row["fragments"]),
                    }
                )
            t = tables.intake_ai_briefs
            scope = (
                t.c.tenant_id == ctx.tenant.id,
                t.c.conversation_id == conversation,
                t.c.message_id == message,
            )
            latest = c.execute(
                select(func.coalesce(func.max(t.c.revision), 0)).where(*scope)
            ).scalar_one()
            query = select(
                t.c.id, t.c.revision, t.c.purpose, t.c.created_at, t.c.created_by_user_id
            ).where(*scope)
            if before_revision:
                query = query.where(t.c.revision < before_revision)
            versions = list(c.execute(query.order_by(t.c.revision.desc()).limit(21)).mappings())
            from app.ai.intake_ai_runs import generation_state

            return {
                "sources": sources,
                "latest_revision": latest,
                "items": [_plain(item) for item in versions[:20]],
                "next_revision": versions[19]["revision"] if len(versions) > 20 else None,
                **generation_state(),
            }

    def save(
        self, ctx: AuthContext, conversation: UUID, message: UUID, body: IntakeBriefInput
    ) -> dict[str, Any]:
        signature = digest(body.model_dump(mode="json", exclude={"request_id"}))
        with self.engine.begin() as c:
            conv = self.scope.scope(c, ctx, conversation, write=True)
            self.scope.message(c, ctx, conversation, message)
            t = tables.intake_ai_briefs
            prior = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.conversation_id == conversation,
                        t.c.request_id == body.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior is not None:
                if prior["request_digest"] != signature or prior["message_id"] != message:
                    raise ConversationError("此准备请求已对应其他资料或整理要求")
                return _plain(prior) | source_status(c, ctx, conversation, prior["source_snapshot"])
            latest = (
                c.execute(
                    select(t)
                    .where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.conversation_id == conversation,
                        t.c.message_id == message,
                    )
                    .order_by(t.c.revision.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if body.expected_revision != (latest["revision"] if latest else 0):
                raise ConversationError("已有更新的整理要求，请读取后续接")
            source = freeze_sources(c, ctx, conversation, message, body)
            identity = uuid4()
            row = (
                c.execute(
                    t.insert()
                    .values(
                        id=identity,
                        tenant_id=ctx.tenant.id,
                        project_id=conv["project_id"],
                        conversation_id=conversation,
                        message_id=message,
                        created_by_user_id=ctx.user.id,
                        request_id=body.request_id,
                        request_digest=signature,
                        revision=body.expected_revision + 1,
                        previous_brief_id=latest["id"] if latest else None,
                        root_brief_id=latest["root_brief_id"] if latest else identity,
                        purpose=body.purpose,
                        source_snapshot=source,
                        source_digest=digest(source),
                        source_version=SOURCE_VERSION,
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            return _plain(row) | {"source_current": True}

    def get(self, ctx: AuthContext, conversation: UUID, identity: UUID) -> dict[str, Any]:
        with self.engine.connect() as c:
            self.scope.scope(c, ctx, conversation)
            t = tables.intake_ai_briefs
            row = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.conversation_id == conversation,
                        t.c.id == identity,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ConversationError("整理要求不属于本人的当前会话")
            return _plain(row) | source_status(c, ctx, conversation, row["source_snapshot"])
