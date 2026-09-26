"""Original-backed PDF viewing and bounded, page-explicit textual comparison."""

from __future__ import annotations

import hashlib
from difflib import SequenceMatcher
from io import BytesIO
from typing import Any
from uuid import UUID

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy import Connection, Engine, func, literal, select

from app.db.schema import tables
from app.domain.documents import MAX_DOCUMENT_BYTES, MAX_PDF_PAGES
from app.domain.product_workspace import _plain
from app.storage.documents import DocumentObjectStore, ReadableDocumentObjectStore

TEXT_LIMIT = 20000
COMPARE_LINES = 1000


class DocumentPreviewError(ValueError):
    pass


class DocumentPreviewMissing(LookupError):
    pass


def document_row(c: Connection, tenant_id: UUID, project_id: UUID, identity: UUID) -> Any:
    t = tables.documents
    row = (
        c.execute(
            select(t).where(
                t.c.tenant_id == tenant_id, t.c.project_id == project_id, t.c.id == identity
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise DocumentPreviewMissing("资料不存在或不属于此项目")
    return row


def metadata(row: Any) -> dict[str, Any]:
    return _plain(
        {
            k: row[k]
            for k in (
                "id",
                "project_id",
                "filename",
                "media_type",
                "classification",
                "size_bytes",
                "sha256",
                "extraction_status",
                "fragment_count",
                "extraction_metadata",
                "created_at",
            )
        }
    )


class DocumentPreviewService:
    def __init__(self, engine: Engine, store: DocumentObjectStore | None = None):
        self.engine, self.store = engine, store

    def info(self, tenant: UUID, project: UUID, identity: UUID) -> dict[str, Any]:
        with self.engine.connect() as c:
            return metadata(document_row(c, tenant, project, identity))

    def email_text(
        self, tenant: UUID, project: UUID, identity: UUID, after_ordinal: int = 0
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            row = document_row(c, tenant, project, identity)
            if row["media_type"] != "message/rfc822":
                raise DocumentPreviewError("此资料不是邮件原件")
            f = tables.document_fragments
            fragments = (
                c.execute(
                    select(f.c.ordinal, f.c.locator, f.c.text)
                    .where(
                        f.c.tenant_id == tenant,
                        f.c.project_id == project,
                        f.c.document_id == identity,
                        f.c.ordinal > after_ordinal,
                    )
                    .order_by(f.c.ordinal)
                    .limit(11)
                )
                .mappings()
                .all()
            )
            return {
                "document": metadata(row),
                "fragments": [_plain(item) for item in fragments[:10]],
                "next_after": fragments[9]["ordinal"] if len(fragments) > 10 else None,
            }

    def original(
        self, tenant: UUID, project: UUID, identity: UUID
    ) -> tuple[dict[str, Any], bytes, int | None]:
        with self.engine.connect() as c:
            row = document_row(c, tenant, project, identity)
            meta = metadata(row)
            if row["media_type"] not in {
                "application/step",
                "application/x-gerber",
                "application/pdf",
                "message/rfc822",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            }:
                raise DocumentPreviewError("此文件格式尚未接入原件查看")
            if row["size_bytes"] > MAX_DOCUMENT_BYTES:
                raise DocumentPreviewError("此原件超过当前20 MiB查看范围")
            if not isinstance(self.store, ReadableDocumentObjectStore):
                raise DocumentPreviewError("原件存储暂不可读取")
            content = self.store.get(object_key=row["object_key"], max_bytes=MAX_DOCUMENT_BYTES)
            if (
                len(content) != row["size_bytes"]
                or hashlib.sha256(content).hexdigest() != row["sha256"]
            ):
                raise DocumentPreviewError("原件摘要与登记内容不一致，请核对存储文件")
        pages = None
        if meta["media_type"] == "application/pdf":
            try:
                reader = PdfReader(BytesIO(content))
                if reader.is_encrypted:
                    raise DocumentPreviewError("加密PDF暂不能内嵌查看")
                pages = len(reader.pages)
                if not 1 <= pages <= MAX_PDF_PAGES:
                    raise DocumentPreviewError("PDF页数超出当前查看范围")
            except (PdfReadError, ValueError) as error:
                if isinstance(error, DocumentPreviewError):
                    raise
                raise DocumentPreviewError("原始PDF暂不能解析") from error
        return meta, content, pages

    @staticmethod
    def _text(
        c: Connection,
        tenant: UUID,
        project: UUID,
        identity: UUID,
        page: int,
        offset: int,
        limit: int,
    ) -> dict[str, Any]:
        row = document_row(c, tenant, project, identity)
        if row["media_type"] != "application/pdf":
            raise DocumentPreviewError("按页对照当前仅支持PDF")
        f = tables.document_fragments
        # Concatenate only this page, retaining each stored fragment's original order.
        from sqlalchemy.dialects.postgresql import aggregate_order_by

        body = func.coalesce(
            func.string_agg(f.c.text, aggregate_order_by(literal("\n"), f.c.ordinal)), ""
        )
        result = (
            c.execute(
                select(
                    func.length(body).label("total"),
                    func.substr(body, offset + 1, limit).label("body"),
                    func.count(f.c.id).label("fragments"),
                ).where(
                    f.c.tenant_id == tenant,
                    f.c.project_id == project,
                    f.c.document_id == identity,
                    (f.c.locator == f"page:{page}") | f.c.locator.like(f"page:{page}#part:%"),
                )
            )
            .mappings()
            .one()
        )
        total = int(result["total"])
        return {
            "document": metadata(row),
            "page": page,
            "text": str(result["body"]),
            "offset": offset,
            "total_characters": total,
            "fragment_count": int(result["fragments"]),
            "next_offset": offset + limit if offset + limit < total else None,
            "truncated": offset > 0 or offset + limit < total,
            "scope": "stored_page_extraction",
        }

    def page_text(
        self, tenant: UUID, project: UUID, identity: UUID, page: int, offset: int
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            return self._text(c, tenant, project, identity, page, offset, TEXT_LIMIT)

    def compare(
        self, tenant: UUID, project: UUID, left: UUID, right: UUID, left_page: int, right_page: int
    ) -> dict[str, Any]:
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            a = self._text(c, tenant, project, left, left_page, 0, TEXT_LIMIT)
            b = self._text(c, tenant, project, right, right_page, 0, TEXT_LIMIT)
        left_lines = str(a["text"]).splitlines()
        right_lines = str(b["text"]).splitlines()
        limited = len(left_lines) > COMPARE_LINES or len(right_lines) > COMPARE_LINES
        left_lines, right_lines = left_lines[:COMPARE_LINES], right_lines[:COMPARE_LINES]
        changes = []
        for tag, a0, a1, b0, b1 in SequenceMatcher(
            None, left_lines, right_lines, autojunk=False
        ).get_opcodes():
            changes.append(
                {
                    "kind": tag,
                    "left_start": a0 + 1,
                    "left_end": a1,
                    "right_start": b0 + 1,
                    "right_end": b1,
                    "left": left_lines[a0:a1],
                    "right": right_lines[b0:b1],
                }
            )
        return {
            "left": a,
            "right": b,
            "same_original": a["document"]["sha256"] == b["document"]["sha256"],
            "text_equal": left_lines == right_lines,
            "comparable_text": bool(left_lines) and bool(right_lines),
            "limited": limited or a["truncated"] or b["truncated"],
            "changes": changes,
            "scope": "selected_pages_text_only",
        }
