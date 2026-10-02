"""Private staged conversation files; parsing does not publish project documents."""

from __future__ import annotations

import hashlib
import re
from contextlib import nullcontext
from dataclasses import asdict
from pathlib import PurePath
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import Connection, Engine, func, or_, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.conversations import ConversationError, ConversationService
from app.domain.documents import (
    MAX_DOCUMENT_BYTES,
    SUPPORTED_MEDIA_TYPES,
    DocumentError,
    _safe_filename,
    extract_document_details,
)
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.product_workspace import _plain, _role, digest
from app.storage.documents import DocumentObjectStore, ReadableDocumentObjectStore

PARSER_VERSION = "conversation-pdf-xlsx.v1"
MAX_ATTACHMENTS = 6


def summary(row: Any) -> dict[str, Any]:
    return _plain(
        {
            key: row[key]
            for key in (
                "id",
                "filename",
                "classification",
                "size_bytes",
                "sha256",
                "status",
                "error_code",
                "parser_version",
                "revoked_at",
                "created_at",
            )
        }
        | {"fragment_count": len(row["fragments"])}
    )


def message_attachment_ids(c: Connection, tenant_id: UUID, message_id: UUID) -> tuple[UUID, ...]:
    return tuple(
        c.execute(
            select(tables.conversation_message_attachments.c.attachment_id)
            .where(
                tables.conversation_message_attachments.c.tenant_id == tenant_id,
                tables.conversation_message_attachments.c.message_id == message_id,
            )
            .order_by(tables.conversation_message_attachments.c.ordinal)
        ).scalars()
    )


class ConversationAttachmentService:
    def __init__(self, engine: Engine, *, object_store: DocumentObjectStore | None = None):
        self.engine, self.object_store = engine, object_store

    def _scope(
        self, c: Connection, context: AuthContext, conversation_id: UUID, *, write: bool = False
    ) -> Any:
        conversation = ConversationService(self.engine)._conversation(
            c, context, conversation_id, lock=write
        )
        if write:
            if conversation["archived_at"] is not None:
                raise ConversationError("会话已归档，请先恢复后再上传或解析")
            if conversation.get("scope_kind", "project") == "project":
                KnowledgeCorrectionService._authorize(
                    c,
                    context.tenant.id,
                    context.user.id,
                    conversation["project_id"],
                    Action.DOCUMENT_ANALYZE,
                )
            else:
                _role(context, Action.DOCUMENT_ANALYZE)

        return conversation

    @staticmethod
    def _row(
        c: Connection,
        tenant_id: UUID,
        conversation_id: UUID,
        attachment_id: UUID,
        *,
        lock: bool = False,
    ) -> Any:
        q = select(tables.conversation_attachments).where(
            tables.conversation_attachments.c.tenant_id == tenant_id,
            tables.conversation_attachments.c.conversation_id == conversation_id,
            tables.conversation_attachments.c.id == attachment_id,
        )
        row = c.execute(q.with_for_update() if lock else q).mappings().one_or_none()
        if row is None:
            raise ConversationError("此附件不属于当前私人会话")
        return row

    def register(
        self,
        *,
        context: AuthContext,
        conversation_id: UUID,
        request_id: UUID,
        filename: str,
        size_bytes: int,
        sha256: str,
        classification: str = "internal",
        connection: Connection | None = None,
    ) -> dict[str, Any]:
        filename = _safe_filename(filename)
        media_type = SUPPORTED_MEDIA_TYPES.get(PurePath(filename).suffix.lower())
        parser_version = "conversation-eml.v1" if media_type == "message/rfc822" else PARSER_VERSION
        if media_type is None or not 1 <= size_bytes <= MAX_DOCUMENT_BYTES:
            raise ConversationError("当前支持不超过20 MiB的PDF、XLSX和授权EML原件")
        if not re.fullmatch(r"[0-9a-f]{64}", sha256) or classification not in {
            "internal",
            "confidential",
            "restricted",
        }:
            raise ConversationError("附件摘要或资料级别无效")
        with self.engine.begin() if connection is None else nullcontext(connection) as c:
            conv = self._scope(c, context, conversation_id, write=True)
            if conv.get("scope_kind", "project") != "project" and media_type not in {
                "application/pdf",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            }:
                raise ConversationError("非项目私人附件当前仅支持PDF/XLSX，不支持邮件子件")
            if conv["visibility"] == "project" and classification != "internal":
                raise ConversationError("受限资料请保留在私人会话，不自动向全部项目成员共享")
            signature = digest(
                dict(sha256=sha256, size_bytes=size_bytes, classification=classification)
            )
            alias = (
                c.execute(
                    select(tables.conversation_attachment_requests).where(
                        tables.conversation_attachment_requests.c.tenant_id == context.tenant.id,
                        tables.conversation_attachment_requests.c.conversation_id
                        == conversation_id,
                        tables.conversation_attachment_requests.c.request_id == request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if alias is not None:
                if alias["request_digest"] != signature:
                    raise ConversationError("此上传请求已用于不同内容")
                return summary(
                    self._row(c, context.tenant.id, conversation_id, alias["attachment_id"])
                ) | {"reused": True}

            def remember(row: Any, reused: bool) -> dict[str, Any]:
                c.execute(
                    tables.conversation_attachment_requests.insert().values(
                        tenant_id=context.tenant.id,
                        project_id=conv["project_id"],
                        conversation_id=conversation_id,
                        request_id=request_id,
                        attachment_id=row["id"],
                        request_digest=signature,
                    )
                )
                return summary(row) | {"reused": reused}

            old = (
                c.execute(
                    select(tables.conversation_attachments).where(
                        tables.conversation_attachments.c.tenant_id == context.tenant.id,
                        tables.conversation_attachments.c.conversation_id == conversation_id,
                        tables.conversation_attachments.c.sha256 == sha256,
                        tables.conversation_attachments.c.classification == classification,
                        tables.conversation_attachments.c.parser_version == parser_version,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if old is not None:
                if old["size_bytes"] != size_bytes:
                    raise ConversationError("文件长度与原内容摘要不一致")
                return remember(old, True)
            aid = uuid5(conversation_id, "attachment:" + str(request_id))
            row = (
                c.execute(
                    tables.conversation_attachments.insert()
                    .values(
                        id=aid,
                        tenant_id=context.tenant.id,
                        project_id=conv["project_id"],
                        conversation_id=conversation_id,
                        request_id=request_id,
                        uploaded_by_user_id=context.user.id,
                        filename=filename,
                        media_type=media_type,
                        classification=classification,
                        size_bytes=size_bytes,
                        sha256=sha256,
                        object_key=f"tenants/{context.tenant.id}/private-conversations/{conversation_id}/{aid}",
                        parser_version=parser_version,
                        status="awaiting_upload",
                    )
                    .returning(tables.conversation_attachments)
                )
                .mappings()
                .one()
            )
            return remember(row, False)

    def upload(
        self,
        *,
        context: AuthContext,
        conversation_id: UUID,
        attachment_id: UUID,
        content: bytes,
        connection: Connection | None = None,
    ) -> dict[str, Any]:
        with self.engine.begin() if connection is None else nullcontext(connection) as c:
            self._scope(c, context, conversation_id, write=True)
            row = self._row(c, context.tenant.id, conversation_id, attachment_id, lock=True)
            if (
                len(content) != row["size_bytes"]
                or hashlib.sha256(content).hexdigest() != row["sha256"]
            ):
                raise ConversationError("请选择与登记摘要一致的原文件，内容已变化请重新添加")
            if row["revoked_at"] is not None:
                raise ConversationError("此附件已停止引用")
            if row["status"] != "awaiting_upload":
                return summary(row)
            if self.object_store is None:
                raise ConversationError("私有文件存储暂不可用，登记已保留")
            # The same key and verified bytes make an uncertain storage receipt safe to reconcile.
            error_code = None
            next_status = "uploaded"
            try:
                self.object_store.put(
                    object_key=row["object_key"],
                    content=content,
                    media_type=row["media_type"],
                    sha256=row["sha256"],
                )
            except Exception:
                next_status, error_code = "awaiting_upload", "ATTACHMENT_UPLOAD_UNAVAILABLE"
            updated = (
                c.execute(
                    tables.conversation_attachments.update()
                    .where(tables.conversation_attachments.c.id == attachment_id)
                    .values(
                        status=next_status,
                        updated_at=func.clock_timestamp(),
                        error_code=error_code,
                    )
                    .returning(tables.conversation_attachments)
                )
                .mappings()
                .one()
            )
            return summary(updated)

    def parse(
        self, *, context: AuthContext, conversation_id: UUID, attachment_id: UUID
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            self._scope(c, context, conversation_id, write=True)
            row = self._row(c, context.tenant.id, conversation_id, attachment_id, lock=True)
            if row["revoked_at"] is not None or row["status"] == "awaiting_upload":
                raise ConversationError("请先传完原文件，并核对此附件仍可引用")
            if row["status"] in {"extracted", "ocr_required"}:
                return summary(row)
            fragments: list[dict[str, Any]] = []
            error_code = None
            extraction_metadata: dict[str, Any] = {}
            try:
                if not isinstance(self.object_store, ReadableDocumentObjectStore):
                    raise ConversationError("私有文件存储暂不可读取")
                content = self.object_store.get(
                    object_key=row["object_key"], max_bytes=MAX_DOCUMENT_BYTES
                )
                if (
                    len(content) != row["size_bytes"]
                    or hashlib.sha256(content).hexdigest() != row["sha256"]
                ):
                    raise ConversationError("存储原件与登记摘要不一致")
                _, extracted, extraction_metadata = extract_document_details(
                    filename=row["filename"], content=content, include_coordinates=True
                )
                fragments = [asdict(item) for item in extracted]
                status = "extracted" if fragments else "ocr_required"
            except DocumentError as error:
                status, error_code = "failed", error.code
            except Exception:
                status, error_code = "failed", "ATTACHMENT_SOURCE_UNAVAILABLE"
            updated = (
                c.execute(
                    tables.conversation_attachments.update()
                    .where(tables.conversation_attachments.c.id == attachment_id)
                    .values(
                        status=status,
                        error_code=error_code,
                        fragments=fragments,
                        extraction_metadata=extraction_metadata,
                        updated_at=func.clock_timestamp(),
                    )
                    .returning(tables.conversation_attachments)
                )
                .mappings()
                .one()
            )
            return summary(updated)

    def list(self, *, context: AuthContext, conversation_id: UUID) -> dict[str, Any]:
        with self.engine.connect() as c:
            self._scope(c, context, conversation_id)
            rows = (
                c.execute(
                    select(tables.conversation_attachments)
                    .where(
                        tables.conversation_attachments.c.tenant_id == context.tenant.id,
                        tables.conversation_attachments.c.conversation_id == conversation_id,
                    )
                    .order_by(tables.conversation_attachments.c.created_at.desc())
                    .limit(101)
                )
                .mappings()
                .all()
            )
            return {"items": [summary(row) for row in rows[:100]], "truncated": len(rows) > 100}

    def get(
        self,
        *,
        context: AuthContext,
        conversation_id: UUID,
        attachment_id: UUID,
        after_ordinal: int = 0,
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            self._scope(c, context, conversation_id)
            row = self._row(c, context.tenant.id, conversation_id, attachment_id)
            fragments = (
                []
                if row["revoked_at"] is not None
                else [f for f in row["fragments"] if f["ordinal"] > after_ordinal]
            )
            from app.domain.conversation_email_parts import origin_records

            return summary(row) | {
                "email_origins": origin_records(
                    c, context.tenant.id, conversation_id, attachment_id
                ),
                "extraction_metadata": row["extraction_metadata"]
                if row["revoked_at"] is None
                else {},
                "fragments": fragments[:10],
                "next_after": fragments[9]["ordinal"] if len(fragments) > 10 else None,
            }

    def revoke(
        self, *, context: AuthContext, conversation_id: UUID, attachment_id: UUID
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            ConversationService(self.engine)._conversation(c, context, conversation_id, lock=True)
            row = self._row(c, context.tenant.id, conversation_id, attachment_id, lock=True)
            if row["revoked_at"] is None:
                row = (
                    c.execute(
                        tables.conversation_attachments.update()
                        .where(tables.conversation_attachments.c.id == attachment_id)
                        .values(
                            revoked_at=func.clock_timestamp(),
                            updated_at=func.clock_timestamp(),
                        )
                        .returning(tables.conversation_attachments)
                    )
                    .mappings()
                    .one()
                )
            return summary(row)


def bind_attachments(
    c: Connection,
    context: AuthContext,
    conversation: Any,
    message_id: UUID,
    attachment_ids: tuple[UUID, ...],
    action: str,
) -> None:
    if len(attachment_ids) > MAX_ATTACHMENTS or len(set(attachment_ids)) != len(attachment_ids):
        raise ConversationError("每条消息最多选择6个不同附件")
    allowed = (
        {"note", "project_query"}
        if conversation.get("scope_kind", "project") == "project"
        else {"note", "product_work"}
    )
    if attachment_ids and action not in allowed:
        raise ConversationError("文件附件请先用项目事实问答阅读；专业候选使用已核对的原业务资料")
    for ordinal, aid in enumerate(attachment_ids, 1):
        row = ConversationAttachmentService._row(c, context.tenant.id, conversation["id"], aid)
        if row["revoked_at"] is not None:
            raise ConversationError("所选附件已停止引用，请重新选择")
        if action in {"project_query", "product_work"} and (
            row["status"] != "extracted" or row["classification"] != "internal"
        ):
            raise ConversationError(
                "文件问答仅使用已抽取的内部资料；失败、需OCR或限制资料可先保存说明"
            )
        c.execute(
            tables.conversation_message_attachments.insert().values(
                tenant_id=context.tenant.id,
                project_id=conversation["project_id"],
                conversation_id=conversation["id"],
                message_id=message_id,
                attachment_id=aid,
                ordinal=ordinal,
            )
        )


def attachment_evidence(
    engine: Engine,
    *,
    tenant_id: UUID,
    project_id: UUID,
    actor_user_id: UUID | None,
    attachment_ids: tuple[UUID, ...],
    question: str,
) -> tuple[Any, ...]:
    from app.ai.chat import ChatEvidence

    if not attachment_ids:
        return ()
    if actor_user_id is None or len(attachment_ids) > MAX_ATTACHMENTS:
        raise ConversationError("附件读取缺少本人范围")
    output = []
    terms = {t.lower() for t in re.findall(r"[\w\u4e00-\u9fff]{2,}", question)}
    with engine.connect() as c:
        for aid in attachment_ids:
            row = (
                c.execute(
                    select(
                        tables.conversation_attachments,
                        tables.conversations.c.meeting_id.label("scope_meeting_id"),
                    )
                    .join(
                        tables.conversations,
                        (
                            tables.conversations.c.tenant_id
                            == tables.conversation_attachments.c.tenant_id
                        )
                        & (
                            tables.conversations.c.id
                            == tables.conversation_attachments.c.conversation_id
                        ),
                    )
                    .where(
                        tables.conversation_attachments.c.tenant_id == tenant_id,
                        tables.conversation_attachments.c.project_id == project_id,
                        tables.conversation_attachments.c.id == aid,
                        or_(
                            tables.conversations.c.created_by_user_id == actor_user_id,
                            tables.conversations.c.visibility == "project",
                        ),
                    )
                )
                .mappings()
                .one_or_none()
            )
            if (
                row is None
                or row["revoked_at"] is not None
                or row["status"] != "extracted"
                or row["classification"] != "internal"
            ):
                raise ConversationError("所选附件当前不可用于模型阅读")
            KnowledgeCorrectionService._authorize(
                c, tenant_id, actor_user_id, project_id, Action.PROJECT_VIEW
            )
            if row["scope_meeting_id"] is not None:
                KnowledgeCorrectionService._authorize(
                    c, tenant_id, actor_user_id, project_id, Action.MEETING_VIEW
                )
            fragments = sorted(
                row["fragments"],
                key=lambda f: (-sum(t in f["text"].lower() for t in terms), f["ordinal"]),
            )[:3]
            href = (
                f"/ask?project={project_id}&conversation={row['conversation_id']}&attachment={aid}"
            )
            conv = row["scope_meeting_id"]
            if conv is not None:
                href += f"&meeting={conv}"
            for f in fragments:
                raw = f["text"]
                match = next((raw.lower().find(t) for t in sorted(terms) if t in raw.lower()), 0)
                start = max(0, match - 300)
                excerpt = raw[start : start + 2000]
                coverage = (
                    f"[局部阅读：本文件{len(row['fragments'])}片段中选取{len(fragments)}段；"
                    f"本段字符{start + 1}–{start + len(excerpt)}/{len(raw)}；未读范围不得推断] "
                )
                if row["media_type"] == "message/rfc822":
                    coverage += (
                        "[邮件仅抽取邮件头及所选内嵌正文；附带文件、图片、链接目标和嵌入邮件未读，"
                        "发件人/日期为原文声明，非身份验证或当前批准] "
                    )
                output.append(
                    ChatEvidence(
                        reference_id=f"attachment:{aid}:fragment:{f['ordinal']}",
                        entity="conversation_attachment",
                        entity_id=str(aid),
                        label=f"{row['filename']} · {f['locator']}",
                        href=href + f"&fragment={f['ordinal']}",
                        excerpt=coverage + excerpt,
                    )
                )
    return tuple(output)
