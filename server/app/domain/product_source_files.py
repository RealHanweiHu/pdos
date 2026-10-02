"""Private pre-project RFQ files; deterministic extraction never calls a model."""

from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import PurePath
from typing import Any, Literal
from uuid import UUID, uuid5

from pydantic import Field
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Digest
from app.db.schema import tables
from app.domain.documents import (
    MAX_DOCUMENT_BYTES,
    SUPPORTED_MEDIA_TYPES,
    DocumentError,
    _safe_filename,
    extract_document_details,
)
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _emit,
    _line,
    _plain,
    _role,
    _space,
    digest,
)
from app.storage.documents import DocumentObjectStore, ReadableDocumentObjectStore

PARSER_VERSION = "product-rfq-pdf-xlsx.v1"


class FileRegistration(Contract):
    request_id: UUID
    product_line_id: UUID | None = None
    filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=1, le=MAX_DOCUMENT_BYTES)
    sha256: Digest
    classification: Literal["internal", "confidential", "restricted"] = "internal"


def summary(row: Any) -> dict[str, Any]:
    return {
        **_plain(
            {
                k: row[k]
                for k in (
                    "id",
                    "market_space_id",
                    "product_line_id",
                    "uploaded_by_user_id",
                    "filename",
                    "media_type",
                    "size_bytes",
                    "sha256",
                    "classification",
                    "parser_version",
                    "status",
                    "error_code",
                    "version",
                    "revoked_at",
                    "created_at",
                    "updated_at",
                )
            }
        ),
        "fragment_count": len(row["fragments"]),
    }


def file_row(
    c: Connection, context: AuthContext, space: UUID, id: UUID, *, write: bool = False
) -> Any:
    _role(context, Action.DOCUMENT_ANALYZE)
    _space(c, context, space, access="contributor" if write else "viewer", lock=write)
    t = tables.product_source_files
    query = select(t).where(
        t.c.tenant_id == context.tenant.id,
        t.c.market_space_id == space,
        t.c.id == id,
        t.c.uploaded_by_user_id == context.user.id,
    )
    row = c.execute(query.with_for_update() if write else query).mappings().one_or_none()
    if row is None:
        raise ProductWorkAccessError("原文件不存在或不属于当前发起人")
    _line(
        c,
        context,
        space,
        row["product_line_id"],
        access="contributor" if write else "viewer",
        writable=write,
    )
    return row


class ProductSourceFiles:
    def __init__(self, engine: Engine, object_store: DocumentObjectStore | None = None):
        self.engine, self.object_store = engine, object_store

    def register(
        self, context: AuthContext, space: UUID, request: FileRegistration
    ) -> dict[str, Any]:
        _role(context, Action.DOCUMENT_ANALYZE)
        try:
            filename = _safe_filename(request.filename)
        except DocumentError as error:
            raise ProductWorkError("原文件名称无效，请保留PDF或XLSX扩展名") from error
        suffix = PurePath(filename).suffix.lower()
        if suffix not in {".pdf", ".xlsx"}:
            raise ProductWorkError("RFQ原件目前支持PDF和XLSX；扫描页会明确提示待OCR")
        with self.engine.begin() as c:
            _space(c, context, space, access="contributor", lock=True)
            _line(c, context, space, request.product_line_id, access="contributor", writable=True)
            id = uuid5(context.user.id, f"product-file:{space}:{request.request_id}")
            t = tables.product_source_files
            existing = (
                c.execute(select(t).where(t.c.tenant_id == context.tenant.id, t.c.id == id))
                .mappings()
                .one_or_none()
            )
            fingerprint = digest(request.model_dump(mode="json"))
            if existing:
                if existing["request_digest"] != fingerprint:
                    raise ProductWorkError("此上传请求已用于不同文件或范围")
                return summary(existing)
            row = (
                c.execute(
                    t.insert()
                    .values(
                        id=id,
                        tenant_id=context.tenant.id,
                        market_space_id=space,
                        product_line_id=request.product_line_id,
                        uploaded_by_user_id=context.user.id,
                        request_id=request.request_id,
                        request_digest=fingerprint,
                        filename=filename,
                        media_type=SUPPORTED_MEDIA_TYPES[suffix],
                        classification=request.classification,
                        size_bytes=request.size_bytes,
                        sha256=request.sha256,
                        object_key=f"tenants/{context.tenant.id}/private-product-files/{space}/{id}",
                        parser_version=PARSER_VERSION,
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            _emit(c, context, space, "product_source_file", "registered", summary(row))
            return summary(row)

    def upload(self, context: AuthContext, space: UUID, id: UUID, content: bytes) -> dict[str, Any]:
        with self.engine.begin() as c:
            row = file_row(c, context, space, id, write=True)
            if row["revoked_at"] is not None:
                raise ProductWorkError("原文件已停止引用")
            if len(content) != row["size_bytes"] or sha256(content).hexdigest() != row["sha256"]:
                raise ProductWorkError("上传原件与登记的大小或摘要不一致")
            if row["status"] != "awaiting_upload":
                return summary(row)
            if self.object_store is None:
                raise ProductWorkError("原件存储暂不可用，请稍后重试")
            try:
                self.object_store.put(
                    object_key=row["object_key"],
                    content=content,
                    media_type=row["media_type"],
                    sha256=row["sha256"],
                )
            except Exception as error:
                raise ProductWorkError("原件上传未确认成功；可用同一请求重试") from error
            return self._update(c, context, space, row, status="uploaded", error_code=None)

    def parse(self, context: AuthContext, space: UUID, id: UUID) -> dict[str, Any]:
        with self.engine.begin() as c:
            row = file_row(c, context, space, id, write=True)
            if row["revoked_at"] is not None or row["status"] == "awaiting_upload":
                raise ProductWorkError("请先上传原件，并核对此文件仍可引用")
            if row["status"] in {"extracted", "ocr_required"}:
                return summary(row)
            if not isinstance(self.object_store, ReadableDocumentObjectStore):
                raise ProductWorkError("原件存储暂不可读取")
            fragments: list[dict[str, Any]] = []
            metadata: dict[str, Any] = {}
            error_code: str | None = None
            try:
                content = self.object_store.get(
                    object_key=row["object_key"], max_bytes=MAX_DOCUMENT_BYTES
                )
                if (
                    len(content) != row["size_bytes"]
                    or sha256(content).hexdigest() != row["sha256"]
                ):
                    raise ProductWorkError("存储原件与登记摘要不一致")
                _, extracted, metadata = extract_document_details(
                    filename=row["filename"], content=content, include_coordinates=True
                )
                fragments = [asdict(item) for item in extracted]
                status = "extracted" if fragments else "ocr_required"
            except DocumentError as error:
                status, error_code = "failed", error.code
            except Exception:
                status, error_code = "failed", "SOURCE_UNAVAILABLE_OR_CHANGED"
            return self._update(
                c,
                context,
                space,
                row,
                status=status,
                error_code=error_code,
                fragments=fragments,
                extraction_metadata=metadata,
            )

    def _update(
        self, c: Connection, context: AuthContext, space: UUID, row: Any, **values: Any
    ) -> dict[str, Any]:
        t = tables.product_source_files
        updated = (
            c.execute(
                t.update()
                .where(t.c.tenant_id == context.tenant.id, t.c.id == row["id"])
                .values(
                    **values,
                    version=row["version"] + 1,
                    updated_at=datetime.now(UTC),
                )
                .returning(t)
            )
            .mappings()
            .one()
        )
        _emit(
            c,
            context,
            space,
            "product_source_file",
            "updated",
            summary(updated),
            before=summary(row),
        )
        return summary(updated)

    def revoke(self, context: AuthContext, space: UUID, id: UUID) -> dict[str, Any]:
        with self.engine.begin() as c:
            row = file_row(c, context, space, id, write=True)
            if row["revoked_at"] is not None:
                return summary(row)
            return self._update(c, context, space, row, revoked_at=datetime.now(UTC))

    def read(self, context: AuthContext, space: UUID, id: UUID, after: int = 0) -> dict[str, Any]:
        with self.engine.connect() as c:
            row = file_row(c, context, space, id)
            # Revoked metadata is visible, but original text cannot feed another run.
            items = (
                [] if row["revoked_at"] else [f for f in row["fragments"] if f["ordinal"] > after]
            )
            return {
                **summary(row),
                "fragments": items[:20],
                "next_after": items[19]["ordinal"] if len(items) > 20 else None,
                "extraction_metadata": row["extraction_metadata"],
            }

    def list(self, context: AuthContext, space: UUID, line: UUID | None) -> dict[str, Any]:
        _role(context, Action.DOCUMENT_ANALYZE)
        with self.engine.connect() as c:
            _space(c, context, space)
            _line(c, context, space, line)
            t = tables.product_source_files
            rows = list(
                c.execute(
                    select(t)
                    .where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.market_space_id == space,
                        t.c.product_line_id == line,
                        t.c.uploaded_by_user_id == context.user.id,
                    )
                    .order_by(t.c.created_at.desc(), t.c.id)
                    .limit(101)
                ).mappings()
            )
            return {"items": [summary(r) for r in rows[:100]], "truncated": len(rows) > 100}
