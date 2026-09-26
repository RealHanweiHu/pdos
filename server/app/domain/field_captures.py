"""Human field notes and private originals; explicit review creates one actual Issue."""

from __future__ import annotations

import hashlib
from contextlib import nullcontext
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, or_, select
from sqlalchemy.dialects.postgresql import insert

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.documents import _safe_filename
from app.domain.issues import IssueDraft, IssueService
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.product_workspace import _plain, digest
from app.storage.documents import DocumentObjectStore, ReadableDocumentObjectStore

MAX_BYTES = 12 * 1024 * 1024
MEDIA = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
        "audio/webm",
        "audio/ogg",
        "audio/wav",
        "audio/mp4",
        "audio/mpeg",
    }
)


class CaptureError(ValueError):
    pass


def valid_media(data: bytes, media: str) -> bool:
    """Check container signatures; never execute, extract or claim content recognition."""
    return {
        "image/jpeg": data.startswith(b"\xff\xd8\xff"),
        "image/png": data.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": data.startswith(b"RIFF") and data[8:12] == b"WEBP",
        "audio/webm": data.startswith(b"\x1aE\xdf\xa3"),
        "audio/ogg": data.startswith(b"OggS"),
        "audio/wav": data.startswith(b"RIFF") and data[8:12] == b"WAVE",
        "audio/mp4": data[4:8] == b"ftyp",
        "audio/mpeg": data.startswith(b"ID3")
        or (len(data) > 1 and data[0] == 255 and data[1] & 224 == 224),
    }.get(media, False)


def summary(row: Any) -> dict[str, Any]:
    return _plain(
        {key: value for key, value in row.items() if key not in {"object_key", "request_digest"}}
    ) | {
        "status": "submitted"
        if row["issue_id"] or row["test_run_id"]
        else "awaiting_upload"
        if row["filename"] and not row["uploaded_at"]
        else "draft",
    }


class FieldCaptureService:
    def __init__(self, engine: Engine, store: DocumentObjectStore | None = None):
        self.engine, self.store = engine, store

    @staticmethod
    def authorize(c: Connection, ctx: AuthContext, project: UUID, *, write: bool = False) -> None:
        for action in (
            Action.WORK_ITEM_EDIT if write else Action.WORK_ITEM_VIEW,
            Action.DOCUMENT_ANALYZE,
            Action.QUALITY_VIEW,
        ):
            KnowledgeCorrectionService._authorize(c, ctx.tenant.id, ctx.user.id, project, action)

    def row(
        self, c: Connection, ctx: AuthContext, project: UUID, identity: UUID, *, write: bool = False
    ) -> Any:
        self.authorize(c, ctx, project, write=write)
        t = tables.field_captures
        q = select(t).where(
            t.c.tenant_id == ctx.tenant.id, t.c.project_id == project, t.c.id == identity
        )
        q = (
            q.where(t.c.created_by_user_id == ctx.user.id)
            if write
            else q.where(or_(t.c.created_by_user_id == ctx.user.id, t.c.submitted_at.is_not(None)))
        )
        row = c.execute(q.with_for_update() if write else q).mappings().one_or_none()
        if row is None:
            raise CaptureError("现场记录不存在或当前无权访问")
        return row

    def list_captures(self, ctx: AuthContext, project: UUID) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            self.authorize(c, ctx, project)
            t = tables.field_captures
            return [
                summary(r)
                for r in c.execute(
                    select(t)
                    .where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.project_id == project,
                        t.c.created_by_user_id == ctx.user.id,
                    )
                    .order_by(t.c.created_at.desc(), t.c.id.desc())
                    .limit(100)
                ).mappings()
            ]

    def get(self, ctx: AuthContext, project: UUID, identity: UUID) -> dict[str, Any]:
        with self.engine.connect() as c:
            record = summary(self.row(c, ctx, project, identity))
            if record["created_by_user_id"] != str(ctx.user.id):
                return record | {"draft": None}
            t = tables.field_capture_drafts
            latest = (
                c.execute(
                    select(t)
                    .where(t.c.tenant_id == ctx.tenant.id, t.c.capture_id == identity)
                    .order_by(t.c.version.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            return record | {"draft": _plain(latest) if latest else None}

    def create(
        self,
        ctx: AuthContext,
        project: UUID,
        identity: UUID,
        original_text: str,
        attachment: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not original_text.strip() and attachment is None:
            raise CaptureError("请填写现场说明或选择原始照片/录音")
        file = attachment or {}
        if file and (file["media_type"] not in MEDIA or not 1 <= file["size_bytes"] <= MAX_BYTES):
            raise CaptureError(
                "请选择不超过12 MiB的JPEG、PNG、WebP照片或WebM、Ogg、WAV、MP4、MP3录音"
            )
        filename = _safe_filename(file["filename"]) if file else None
        signature = digest(dict(original_text=original_text, attachment=file))
        with self.engine.begin() as c:
            self.authorize(c, ctx, project, write=True)
            c.execute(
                insert(tables.field_captures)
                .values(
                    id=identity,
                    tenant_id=ctx.tenant.id,
                    project_id=project,
                    created_by_user_id=ctx.user.id,
                    original_text=original_text,
                    filename=filename,
                    media_type=file.get("media_type"),
                    size_bytes=file.get("size_bytes"),
                    sha256=file.get("sha256"),
                    object_key=f"field-captures/{ctx.tenant.id}/{project}/{identity}/{file['sha256']}"
                    if file
                    else None,
                    request_digest=signature,
                )
                .on_conflict_do_nothing(index_elements=["id"])
            )
            row = self.row(c, ctx, project, identity, write=True)
            if row["request_digest"] != signature:
                raise CaptureError("此保存请求已用于其他原始资料，请另建记录")
            return summary(row)

    def upload(
        self, ctx: AuthContext, project: UUID, identity: UUID, content: bytes
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            row = self.row(c, ctx, project, identity, write=True)
            if (
                not row["filename"]
                or len(content) != row["size_bytes"]
                or hashlib.sha256(content).hexdigest() != row["sha256"]
            ):
                raise CaptureError("文件与保存的原件摘要不一致，请重新选择原文件")
            if not valid_media(content, row["media_type"]):
                raise CaptureError("文件内容与所选照片/录音格式不一致")
            if row["uploaded_at"] is not None:
                return summary(row)
            if self.store is None:
                raise CaptureError("原件存储暂不可用，请稍后重试")
            # Deterministic key + identical hash makes a lost response safely retryable.
            self.store.put(
                object_key=row["object_key"],
                content=content,
                media_type=row["media_type"],
                sha256=row["sha256"],
            )
            c.execute(
                tables.field_captures.update()
                .where(tables.field_captures.c.id == identity)
                .values(uploaded_at=datetime.now(UTC))
            )
            return summary(self.row(c, ctx, project, identity, write=True))

    def original(self, ctx: AuthContext, project: UUID, identity: UUID) -> tuple[bytes, str]:
        with self.engine.connect() as c:
            row = self.row(c, ctx, project, identity)
            if not row["uploaded_at"] or not isinstance(self.store, ReadableDocumentObjectStore):
                raise CaptureError("原件尚未上传或暂不可读取")
            content = self.store.get(object_key=row["object_key"], max_bytes=MAX_BYTES)
            if (
                len(content) != row["size_bytes"]
                or hashlib.sha256(content).hexdigest() != row["sha256"]
            ):
                raise CaptureError("原件完整性核对失败")
            return content, str(row["media_type"])

    def samples(self, ctx: AuthContext, project: UUID, query: str) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            self.authorize(c, ctx, project)
            t = tables.samples
            q = select(t.c.id, t.c.serial_number).where(
                t.c.tenant_id == ctx.tenant.id, t.c.project_id == project
            )
            if query.strip():
                q = q.where(
                    t.c.serial_number.ilike(
                        "%"
                        + query.strip()
                        .replace("\\", "\\\\")
                        .replace("%", "\\%")
                        .replace("_", "\\_")
                        + "%",
                        escape="\\",
                    )
                )
            return [
                _plain(r)
                for r in c.execute(q.order_by(t.c.serial_number, t.c.id).limit(50)).mappings()
            ]

    def submit(
        self,
        ctx: AuthContext,
        project: UUID,
        identity: UUID,
        review: dict[str, Any],
        *,
        connection: Connection | None = None,
        from_saved_draft: bool = False,
    ) -> dict[str, Any]:
        with nullcontext(connection) if connection is not None else self.engine.begin() as c:
            row = self.row(c, ctx, project, identity, write=True)
            if row["test_run_id"]:
                raise CaptureError("此记录已经登记测试，请进入原测试办理")
            if (
                not from_saved_draft
                and c.execute(
                    select(tables.field_capture_drafts.c.id)
                    .where(
                        tables.field_capture_drafts.c.tenant_id == ctx.tenant.id,
                        tables.field_capture_drafts.c.capture_id == identity,
                    )
                    .limit(1)
                ).first()
            ):
                raise CaptureError("此记录已有保存的草稿，请核对最新版本后确认提交")
            if row["issue_id"]:
                if row["review"] != review:
                    raise CaptureError("此记录已经转为问题，后续请进入原问题办理")
                return summary(row)
            if row["filename"] and not row["uploaded_at"]:
                raise CaptureError("请先补传原件，再确认问题")
            sample_id = UUID(review["sample_id"]) if review["sample_id"] else None
            if sample_id is None and not review["sample_reason"].strip():
                raise CaptureError("样机不明确时请保留未关联，并说明待核对内容")
            original_link = f"/capture?project={project}&capture={identity}"
            notes = review["description"] + "\n\n现场原始资料：" + original_link
            if sample_id is None:
                notes += "\n样机未关联：" + review["sample_reason"]
            issue = IssueService(self.engine).create(
                tenant_id=ctx.tenant.id,
                actor_user_id=ctx.user.id,
                project_id=project,
                connection=c,
                draft=IssueDraft(
                    stage_id=None,
                    owner_user_id=None,
                    verifier_user_id=None,
                    sample_id=sample_id,
                    title=review["title"],
                    description=notes,
                    issue_type=review["issue_type"],
                    severity=review["severity"],
                    root_cause=None,
                    resolution=None,
                    closure_criteria=None,
                    target_date=None,
                ),
            )
            c.execute(
                tables.field_captures.update()
                .where(tables.field_captures.c.id == identity)
                .values(issue_id=issue.id, review=review, submitted_at=datetime.now(UTC))
            )
            return summary(self.row(c, ctx, project, identity, write=True))
