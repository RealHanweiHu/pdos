"""Persist a human-selected mail attachment and its immutable private provenance."""

import hashlib
from typing import Any, Literal
from uuid import UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, or_, select

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.conversation_attachments import ConversationAttachmentService, summary
from app.domain.conversations import ConversationError
from app.domain.documents import MAX_DOCUMENT_BYTES
from app.domain.email_attachment_parts import PARSER_VERSION, attachment_parts
from app.domain.product_workspace import _plain, digest
from app.storage.documents import DocumentObjectStore, ReadableDocumentObjectStore


class EmailPartSave(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    part_path: str = Field(pattern=r"^1(\.[1-9][0-9]*)*$", max_length=128)
    expected_part_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    classification: Literal["internal", "confidential", "restricted"]
    permission_basis: str = Field(min_length=1, max_length=2000)
    purpose: str = Field(min_length=1, max_length=2000)
    reviewed: Literal[True]


def origin_records(
    c: Connection,
    tenant: UUID,
    conversation: UUID,
    attachment: UUID,
    before_id: UUID | None = None,
) -> dict[str, Any]:
    t = tables.conversation_email_parts
    query = select(t).where(
        t.c.tenant_id == tenant,
        t.c.conversation_id == conversation,
        or_(t.c.parent_attachment_id == attachment, t.c.attachment_id == attachment),
    )
    if before_id:
        query = query.where(t.c.id < before_id)
    rows = list(c.execute(query.order_by(t.c.id.desc()).limit(21)).mappings())
    ids = {row[key] for row in rows[:20] for key in ("parent_attachment_id", "attachment_id")}
    a = tables.conversation_attachments
    attachments = (
        {
            row["id"]: summary(row)
            for row in c.execute(
                select(a).where(
                    a.c.tenant_id == tenant,
                    a.c.conversation_id == conversation,
                    a.c.id.in_(ids),
                )
            ).mappings()
        }
        if ids
        else {}
    )
    return {
        "items": [
            _plain(row)
            | {
                "parent": attachments.get(row["parent_attachment_id"]),
                "attachment": attachments.get(row["attachment_id"]),
            }
            for row in rows[:20]
        ],
        "truncated": len(rows) > 20,
        "next_id": str(rows[19]["id"]) if len(rows) > 20 else None,
    }


class ConversationEmailParts:
    def __init__(self, engine: Engine, *, object_store: DocumentObjectStore):
        self.engine, self.object_store = engine, object_store
        self.files = ConversationAttachmentService(engine, object_store=object_store)

    def _source(
        self,
        c: Connection,
        ctx: AuthContext,
        conversation: UUID,
        attachment: UUID,
        *,
        write: bool = False,
    ) -> Any:
        self.files._scope(c, ctx, conversation, write=write)
        row = self.files._row(c, ctx.tenant.id, conversation, attachment, lock=write)
        if row["media_type"] != "message/rfc822" or row["status"] == "awaiting_upload":
            raise ConversationError("请先保存实际EML原件，再选择其中的附件")
        if row["revoked_at"] is not None:
            raise ConversationError("原邮件已停止引用，不能继续拆取附件")
        return row

    def _read(self, row: Any) -> bytes:
        if not isinstance(self.object_store, ReadableDocumentObjectStore):
            raise ConversationError("私有原件存储暂不可读")
        content = self.object_store.get(object_key=row["object_key"], max_bytes=MAX_DOCUMENT_BYTES)
        if (
            len(content) != row["size_bytes"]
            or hashlib.sha256(content).hexdigest() != row["sha256"]
        ):
            raise ConversationError("邮件原件与保存摘要不一致")
        return content

    @staticmethod
    def _identity(row: Any) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "sha256": row["sha256"],
            "size_bytes": row["size_bytes"],
            "classification": row["classification"],
            "parser_version": PARSER_VERSION,
        }

    def preview(self, ctx: AuthContext, conversation: UUID, attachment: UUID) -> dict[str, Any]:
        with self.engine.connect() as c:
            parent = self._source(c, ctx, conversation, attachment)
            parts, _ = attachment_parts(self._read(parent))
            identity = self._identity(parent)
            return {
                "source": identity,
                "source_digest": digest(identity),
                "parts": [part | {"digest": digest(part)} for part in parts],
                "origins": origin_records(c, ctx.tenant.id, conversation, attachment),
            }

    def save(
        self, ctx: AuthContext, conversation: UUID, attachment: UUID, body: EmailPartSave
    ) -> dict[str, Any]:
        signature = digest(body.model_dump(mode="json", exclude={"request_id"}))
        with self.engine.begin() as c:
            self.files._scope(c, ctx, conversation, write=True)
            t = tables.conversation_email_parts
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
                if (
                    prior["request_digest"] != signature
                    or prior["parent_attachment_id"] != attachment
                ):
                    raise ConversationError("此请求已对应其他邮件附件办理")
                child = self.files._row(c, ctx.tenant.id, conversation, prior["attachment_id"])
                if child["status"] != "awaiting_upload" or child["revoked_at"] is not None:
                    return {"origin": _plain(prior), "attachment": summary(child), "reused": True}
            parent = self._source(c, ctx, conversation, attachment, write=True)
            if digest(self._identity(parent)) != body.expected_source_digest:
                raise ConversationError("邮件来源已变化，请重新读取清单")
            levels = {"internal": 0, "confidential": 1, "restricted": 2}
            if levels[body.classification] < levels[parent["classification"]]:
                raise ConversationError("拆取附件不能降低原邮件的资料级别")
            parts, payloads = attachment_parts(self._read(parent))
            part = next((item for item in parts if item["path"] == body.part_path), None)
            if (
                part is None
                or part["status"] != "available"
                or digest(part) != body.expected_part_digest
            ):
                raise ConversationError("所选邮件附件不可拆取或与原核对版本不同")
            child = self.files.register(
                context=ctx,
                conversation_id=conversation,
                request_id=uuid5(body.request_id, "email-part"),
                filename=part["filename"],
                size_bytes=part["size_bytes"],
                sha256=part["sha256"],
                classification=body.classification,
                connection=c,
            )
            if child["revoked_at"] is not None:
                raise ConversationError("相同内容已停止引用，请核对原附件")
            child = self.files.upload(
                context=ctx,
                conversation_id=conversation,
                attachment_id=UUID(child["id"]),
                content=payloads[body.part_path],
                connection=c,
            )
            if prior is None:
                prior = (
                    c.execute(
                        t.insert()
                        .values(
                            id=uuid4(),
                            tenant_id=ctx.tenant.id,
                            project_id=parent["project_id"],
                            conversation_id=conversation,
                            parent_attachment_id=attachment,
                            attachment_id=UUID(child["id"]),
                            created_by_user_id=ctx.user.id,
                            request_id=body.request_id,
                            request_digest=signature,
                            parent_sha256=parent["sha256"],
                            part_path=body.part_path,
                            parser_version=PARSER_VERSION,
                            part_snapshot=part,
                            permission_basis=body.permission_basis,
                            purpose=body.purpose,
                        )
                        .returning(t)
                    )
                    .mappings()
                    .one()
                )
            return {"origin": _plain(prior), "attachment": child, "reused": False}
