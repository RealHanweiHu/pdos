"""Authorized original bytes and located derivations; no model calls in parse/error paths."""

import base64
import binascii
import hashlib
import re
from bisect import bisect_left, bisect_right
from dataclasses import asdict
from pathlib import PurePath
from uuid import UUID, uuid4

from sqlalchemy import select

from pdos_next.contracts import ArtifactPayload, Command
from pdos_next.database import tenant_session
from pdos_next.dispatch.context import event_context
from pdos_next.errors import DomainError
from pdos_next.evidence_processing import ParseFailure, ParseLimits
from pdos_next.models import (
    Artifact,
    OriginalSecurity,
    Principal,
    Product,
    Receipt,
    RequestKey,
    UploadedOriginal,
)
from pdos_next.object_storage import ObjectRef, StorageFailure
from pdos_next.service import append_receipt, digest, receipt_view, require_access

MEDIA = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def object_reference(row):
    return ObjectRef(row.id, 1, row.content_hash, row.byte_count, row.media_type, row.storage_key)


def read_registered_bytes(store, reference, tenant_id, product_id, category_id=None):
    if hasattr(store, "read_registered"):
        from pdos_next.object_journal import JournalScope

        return store.read_registered(
            reference,
            JournalScope(tenant_id, product_id, category_id if product_id is None else None),
        )
    return store.read_original(reference)


def require_original(s, ctx, product_id, original_id, *, lock=False):
    from pdos_next.request_proof import scoped_rows

    scope = require_access(s, ctx, product_id)
    query = select(UploadedOriginal).where(
        UploadedOriginal.id == original_id,
        UploadedOriginal.category_id == scope.category_id,
        UploadedOriginal.product_id.is_(None) | (UploadedOriginal.product_id == product_id),
    )
    rows = scoped_rows(
        s, (UploadedOriginal, scope.category_id, product_id, original_id), query, lock=lock
    )
    row = rows[0] if rows else None
    if not row:
        raise DomainError("SOURCE_UNAVAILABLE", "原件不在当前授权范围。", 403)
    return row


def upload_contents(data):
    if (
        data.filename != PurePath(data.filename).name
        or any(ord(c) < 32 or c in "/\\" for c in data.filename)
        or len(data.filename.encode()) > 600
    ):
        raise DomainError("INVALID_PAYLOAD", "文件名称无效。", 422)
    media = MEDIA.get(PurePath(data.filename.lower()).suffix)
    if not media:
        raise DomainError("UNSUPPORTED_MEDIA_TYPE", "当前可处理UTF-8文本、PDF和XLSX。", 422)
    try:
        content = base64.b64decode(data.content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise DomainError("INVALID_PAYLOAD", "原件编码无效。", 422) from None
    if not content or len(content) > 8_388_608:
        raise DomainError("FILE_TOO_LARGE", "原件须非空且不超过8MB。", 422)
    hash_value = hashlib.sha256(content).hexdigest()
    request = {
        "title": data.title,
        "source_label": data.source_label,
        "filename": data.filename,
        "content_hash": hash_value,
        "visibility": data.visibility,
        "expected_revision": data.expected_revision,
    }
    return content, media, request, digest(request)


def upload(s, ctx, product_id, data, store, *, attempt=None):
    product = require_access(s, ctx, product_id)
    content, media, request, fingerprint = upload_contents(data)
    key = s.scalar(
        select(RequestKey).where(
            RequestKey.actor_id == ctx.actor_id,
            RequestKey.key == data.idempotency_key,
        )
    )
    if key:
        receipt = s.get(Receipt, key.receipt_id)
        if (
            key.digest != fingerprint
            or not receipt
            or receipt.product_id != product_id
            or receipt.operation != "evidence.original.upload"
        ):
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "原上传请求对应了不同文件。")
        return receipt_view(receipt)
    intent = digest(
        ["evidence.original.upload", ctx.category_id, product.id, ctx.requester_id, request]
    )
    previous = s.scalar(
        select(Receipt).where(
            Receipt.category_id == ctx.category_id,
            Receipt.product_id == product.id,
            Receipt.intent_digest == intent,
        )
    )
    if previous:
        s.add(
            RequestKey(
                tenant_id=ctx.tenant_id,
                category_id=ctx.category_id,
                actor_id=ctx.actor_id,
                key=data.idempotency_key,
                digest=fingerprint,
                receipt_id=previous.id,
            )
        )
        return receipt_view(previous)
    product = require_access(s, ctx, product_id, write=True, lock=True)
    if product_id is not None:
        product = s.scalar(select(Product).where(Product.id == product_id).with_for_update())
    if s.get(Principal, ctx.actor_id).kind != "human" or ctx.run_id or ctx.agent_run_id:
        raise DomainError("FORBIDDEN_SCOPE", "此入口只接收人员授权上传。", 403)
    if product.revision != data.expected_revision:
        raise DomainError("VERSION_CONFLICT", "型号范围已变化，请读取当前版本。")
    if attempt is not None:
        from pdos_next.upload_lifecycle import require_reserved

        require_reserved(s, ctx, product.id, attempt, fingerprint)
    if hasattr(store, "put_scoped"):
        reference = store.put_scoped(
            content,
            media_type=media,
            tenant_id=ctx.tenant_id,
            product_id=product.id,
            category_id=ctx.category_id,
            requester_id=ctx.requester_id,
            upload_id=attempt.id if attempt is not None else uuid4(),
        )
    else:
        reference = store.put_new(content, media_type=media)
    if attempt is not None:
        from pdos_next.upload_lifecycle import require_reserved

        require_reserved(s, ctx, product.id, attempt, fingerprint, reference)
    subject = UploadedOriginal(
        id=reference.id,
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        product_id=product.id,
        owner_id=ctx.requester_id,
        title=data.title,
        filename=data.filename,
        source_label=data.source_label,
        visibility=data.visibility,
        media_type=media,
        byte_count=len(content),
        content_hash=request["content_hash"],
        storage_key=reference.server_storage_key,
    )
    s.add(subject)
    s.flush()
    s.add(
        OriginalSecurity(
            tenant_id=ctx.tenant_id,
            category_id=ctx.category_id,
            product_id=product.id,
            original_id=subject.id,
        )
    )
    if attempt is not None:
        from pdos_next.models import now

        attempt.status, attempt.terminal_at = "committed", now()
        attempt.revision += 1
    command = Command(
        category_id=ctx.category_id,
        command_id=uuid4(),
        idempotency_key=data.idempotency_key,
        operation="evidence.original.upload",
        product_id=product.id,
        expected_revision=data.expected_revision,
        payload=request,
    )
    receipt = append_receipt(
        s, ctx, command, "uploaded_original", subject, fingerprint, intent, subject.visibility
    )
    s.add(
        RequestKey(
            tenant_id=ctx.tenant_id,
            actor_id=ctx.actor_id,
            key=data.idempotency_key,
            digest=fingerprint,
            receipt_id=receipt.id,
        )
    )
    return receipt_view(receipt)


def original_view(s, row, ctx=None, store=None):
    from pdos_next.original_security import view

    source = s.scalar(select(Artifact).where(Artifact.original_id == row.id))
    return {
        "id": str(row.id),
        "title": row.title,
        "filename": row.filename,
        "source_label": row.source_label,
        "media_type": row.media_type,
        "byte_count": row.byte_count,
        "content_hash": row.content_hash,
        "status": row.status,
        "parse_code": row.parse_code,
        "scan_status": row.scan_status,
        "revision": row.revision,
        "visibility": row.visibility,
        "artifact_id": str(source.id) if source else None,
        "locator_map": row.locator_map,
        "security": view(s, row, ctx, store),
    }


def _parse_manifest(result):
    """The parser-declared location inventory; never a completeness declaration."""
    expected = result.expected_locations
    if not expected:
        return None
    kinds = {location.kind for location in expected}
    if len(kinds) != 1:
        raise DomainError("INTEGRITY_MISMATCH", "解析位置库存混用不同基线。")
    return {
        "parser_version": result.parser_version,
        "basis": kinds.pop(),
        "expected_locations": [asdict(location) for location in expected],
    }


def parse_uploaded(engine, reference: dict, store):
    from pdos_next.original_security import require_safe, runtime_for

    ctx = event_context(reference)
    tenant, original_id = UUID(reference["tenant_id"]), UUID(reference["subject_id"])
    product_id = UUID(reference["product_id"]) if reference.get("product_id") else None
    with tenant_session(
        engine,
        tenant,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        category_id=ctx.category_id,
    ) as s:
        require_access(s, ctx, product_id)
        row = s.get(UploadedOriginal, original_id)
        if not row or row.product_id != product_id:
            raise DomainError("SOURCE_UNAVAILABLE", "待处理原件不可用。", 403)
        row = require_original(s, ctx, product_id, original_id)
        safety_basis = require_safe(s, ctx, row)
        runtime = runtime_for(s)
        if row.status != "uploaded" and row.parse_code != "ISOLATION_UNAVAILABLE":
            return {"status": row.status, "original_id": str(row.id)}
        object_ref = object_reference(row)
        # Keep current product/ACL protection through the bounded byte read.
        error_code, content = None, None
        try:
            content = read_registered_bytes(store, object_ref, tenant, product_id, ctx.category_id)
        except StorageFailure as failure:
            error_code = failure.code
    # Object access and isolated parsing occur outside the domain transaction.
    result = None
    try:
        if error_code:
            raise StorageFailure(error_code, "原件读取失败。")
        result = runtime.parser(
            content, media_type=object_ref.media_type, limits=ParseLimits(max_input_bytes=8_388_608)
        )
        if result.source_sha256 != object_ref.content_sha256:
            raise ParseFailure("INTEGRITY_MISMATCH", "解析依据与原件不一致。")
        if len(result.text.encode()) > 200_000:
            raise ParseFailure("TEXT_OUTPUT_TOO_LARGE", "解析文本超过当前来源大小限制。")
    except (ParseFailure, StorageFailure) as failure:
        error_code = failure.code
    with tenant_session(
        engine,
        tenant,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        category_id=ctx.category_id,
    ) as s:
        product = require_access(s, ctx, product_id, write=True, lock=True)
        row = require_original(s, ctx, product_id, original_id, lock=True)
        if require_safe(s, ctx, row) != safety_basis:
            raise DomainError("SOURCE_STALE", "解析期间安全依据已变化，未提交派生资料。")
        if row.status != "uploaded" and row.parse_code != "ISOLATION_UNAVAILABLE":
            return {"status": row.status, "original_id": str(row.id)}
        row.revision += 1
        row.parse_code = None
        row.parse_manifest = None
        if error_code:
            row.status, row.parse_code = "failed", error_code
        elif result.status == "needs_ocr":
            row.status, row.parse_code = "needs_ocr", "OCR_REQUIRED"
            row.parse_manifest = _parse_manifest(result)
        else:
            payload = ArtifactPayload(
                title=row.title,
                content=result.text,
                source_label=row.source_label,
                visibility=row.visibility,
            )
            artifact = Artifact(
                tenant_id=tenant,
                category_id=ctx.category_id,
                product_id=product_id,
                owner_id=ctx.requester_id,
                original_id=row.id,
                content_hash=digest(result.text),
                **payload.model_dump(),
            )
            s.add(artifact)
            row.status = "parsed"
            # Each derived line retains its original page/cell/line locator.
            boundaries = [
                match.end()
                for match in re.finditer(
                    r"\r\n|[\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]", result.text
                )
            ]
            offset = 0
            locations = []
            for segment in result.as_dict()["segments"]:
                if segment["location"]["kind"] == "line":
                    start_line = end_line = segment["location"]["line"]
                else:
                    start = result.text.find(segment["text"], offset)
                    if start < 0:
                        raise DomainError(
                            "INTEGRITY_MISMATCH", "来源定位无法核对，未形成派生资料。"
                        )
                    end = start + len(segment["text"])
                    start_line = bisect_right(boundaries, start) + 1
                    end_line = max(start_line, bisect_left(boundaries, end) + 1)
                    offset = end
                locations.append(
                    {
                        "derived_line_start": start_line,
                        "derived_line_end": end_line,
                        "location": segment["location"],
                        "value_kind": segment["value_kind"],
                    }
                )
            if row.media_type == "application/pdf" and result.warnings:
                row.parse_code = "PARTIAL_TEXT"
            row.locator_map = locations
            row.parse_manifest = _parse_manifest(result)
        s.flush()
        command = Command(
            category_id=ctx.category_id,
            command_id=uuid4(),
            idempotency_key=f"parse:{row.id}:{safety_basis[1]}",
            operation="evidence.original.parse",
            product_id=product.id,
            expected_revision=row.revision,
            payload={"original_id": str(row.id), "status": row.status},
        )
        append_receipt(
            s,
            ctx,
            command,
            "uploaded_original",
            row,
            digest(command.payload),
            digest(["parse", row.id, row.content_hash, safety_basis[1]]),
            row.visibility,
        )
        return {"status": row.status, "original_id": str(row.id)}
