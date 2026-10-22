"""Read-only upload authorization and owned request recovery; original POSTs own writes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import load_only

from pdos_next.errors import DomainError
from pdos_next.models import (
    Artifact,
    Receipt,
    RequestKey,
    UploadAttempt,
    UploadedOriginal,
)
from pdos_next.original_security import view as security_view
from pdos_next.request_proof import batch_read, request_proof
from pdos_next.schema_base import StrictModel
from pdos_next.service import require_access

from .source_views import ARTIFACT_FIELDS, ORIGINAL_FIELDS, _head, _human, _metadata, _scope

OPERATION = "evidence.original.upload"


class UploadScope(StrictModel):
    product_id: UUID | None = None
    proposal_id: UUID | None = None


class UploadRecovery(UploadScope):
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


def _conflict():
    raise DomainError("DUPLICATE_INTENT_CONFLICT", "原上传请求对应不同内容或范围，请核对原请求。")


def _integrity():
    raise DomainError("INTEGRITY_MISMATCH", "原上传登记与回执无法完整核对，请保留原请求。")


def read_target(session, ctx, page):
    _human(session, ctx, page.product_id, page.proposal_id)
    target = require_access(session, ctx, page.product_id)
    can_write = True
    try:
        require_access(session, ctx, page.product_id, write=True)
    except DomainError as error:
        if error.reason != "FORBIDDEN_SCOPE":
            raise
        can_write = False
    return {
        "version": "agent-upload-target/v1",
        "principal_id": str(ctx.requester_id),
        "scope": _scope(ctx, page.product_id, page.proposal_id),
        "as_of": session.scalar(select(func.transaction_timestamp())).isoformat(),
        "target": {
            "kind": "product" if page.product_id else "category",
            "id": str(page.product_id or target.category_id),
            "revision": target.revision,
        },
        "authorization": {"can_write": can_write, "code": None if can_write else "FORBIDDEN_SCOPE"},
        "constraints": {
            "max_bytes": 8_388_608,
            "extensions": [".txt", ".md", ".pdf", ".xlsx"],
            "default_visibility": "private",
        },
    }


def _attempt(session, ctx, product_id, *, identity=None, key=None):
    query = select(
        UploadAttempt.id,
        UploadAttempt.revision,
        UploadAttempt.status,
        UploadAttempt.request_digest,
    ).where(
        UploadAttempt.tenant_id == ctx.tenant_id,
        UploadAttempt.category_id == ctx.category_id,
        UploadAttempt.product_id == product_id,
        UploadAttempt.owner_id == ctx.requester_id,
    )
    query = (
        query.where(UploadAttempt.id == identity)
        if identity
        else query.where(UploadAttempt.request_key == key)
    )
    return session.execute(query).mappings().one_or_none()


def _original(session, ctx, product_id, identity):
    row = session.scalar(
        select(UploadedOriginal)
        .where(
            UploadedOriginal.tenant_id == ctx.tenant_id,
            UploadedOriginal.category_id == ctx.category_id,
            UploadedOriginal.product_id == product_id,
            UploadedOriginal.owner_id == ctx.requester_id,
            UploadedOriginal.id == identity,
        )
        .options(
            load_only(
                *(getattr(UploadedOriginal, field) for field in (*ORIGINAL_FIELDS, "title")),
                raiseload=True,
            )
        )
    )
    if row is None:
        return None, None
    # This actual ordinary-RLS head query also proves a missing derivation, so
    # the security Guard need not issue its fallback full Artifact SELECT.
    source = session.scalar(
        select(Artifact)
        .where(
            Artifact.tenant_id == ctx.tenant_id,
            Artifact.category_id == ctx.category_id,
            Artifact.original_id == identity,
        )
        .options(
            load_only(
                *(getattr(Artifact, field) for field in ARTIFACT_FIELDS),
                raiseload=True,
            )
        )
    )
    if source is not None and source.product_id != product_id:
        _integrity()
    request_proof(session).read_rows[(Artifact, ("original", identity))] = source
    batch_read(session, UploadedOriginal, [identity])
    security = security_view(session, row, ctx)
    original = {
        "id": str(row.id),
        "revision": row.revision,
        "title": row.title,
        "filename": row.filename,
        "parse_status": row.status,
        "parse_code": row.parse_code,
        "scan_status": row.scan_status,
        "security": {key: security[key] for key in ("state", "reasons", "epoch", "source_state")},
    }
    current = None
    if source is not None:
        originals = _metadata(session, [source], ctx, product_id)
        current = _head(session, ctx, product_id, source, originals)
    return original, current


def read_receipt(session, ctx, request_key, page):
    _human(session, ctx, page.product_id, page.proposal_id)
    key = (
        session.execute(
            select(RequestKey.digest, RequestKey.receipt_id).where(
                RequestKey.tenant_id == ctx.tenant_id,
                RequestKey.category_id == ctx.category_id,
                RequestKey.actor_id == ctx.requester_id,
                RequestKey.key == str(request_key),
            )
        )
        .mappings()
        .one_or_none()
    )
    receipt, attempt, original, source = None, None, None, None
    state = "not_observed"
    if key is not None:
        if key["digest"] != page.request_digest:
            _conflict()
        saved = (
            session.execute(
                select(
                    Receipt.id,
                    Receipt.operation,
                    Receipt.subject_type,
                    Receipt.subject_id,
                    Receipt.subject_revision,
                    Receipt.actor_id,
                    Receipt.requester_id,
                    Receipt.created_at,
                    Receipt.request_digest,
                ).where(
                    Receipt.id == key["receipt_id"],
                    Receipt.tenant_id == ctx.tenant_id,
                    Receipt.category_id == ctx.category_id,
                    Receipt.product_id == page.product_id,
                    Receipt.actor_id == ctx.requester_id,
                    Receipt.requester_id == ctx.requester_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if saved is None:
            _conflict()
        if saved["operation"] != OPERATION or saved["subject_type"] != "uploaded_original":
            _conflict()
        if saved["request_digest"] != page.request_digest or saved["subject_revision"] != 1:
            _integrity()
        receipt = {
            field: str(saved[field]) if field in {"id", "subject_id"} else saved[field]
            for field in ("id", "operation", "subject_type", "subject_id", "subject_revision")
        }
        receipt.update(
            writer_id=str(saved["actor_id"]),
            requester_id=str(saved["requester_id"]),
            created_at=saved["created_at"].isoformat(),
        )
        state = "committed"
        attempt = _attempt(session, ctx, page.product_id, identity=saved["subject_id"])
        if attempt is not None and (
            attempt["status"] != "committed" or attempt["request_digest"] != page.request_digest
        ):
            _integrity()
        original, source = _original(session, ctx, page.product_id, saved["subject_id"])
    else:
        attempt = _attempt(session, ctx, page.product_id, key=str(request_key))
        if attempt is not None:
            if attempt["request_digest"] != page.request_digest:
                _conflict()
            if attempt["status"] not in {"reserved", "abandoned"}:
                _integrity()
            state = attempt["status"]
            # A pending/closed reservation is not a committed original. A
            # contradictory actual row is an error, never a success inference.
            if (
                session.scalar(
                    select(UploadedOriginal.id).where(
                        UploadedOriginal.tenant_id == ctx.tenant_id,
                        UploadedOriginal.category_id == ctx.category_id,
                        UploadedOriginal.product_id == page.product_id,
                        UploadedOriginal.id == attempt["id"],
                    )
                )
                is not None
            ):
                _integrity()
    return {
        "version": "agent-upload-receipt/v1",
        "principal_id": str(ctx.requester_id),
        "scope": _scope(ctx, page.product_id, page.proposal_id),
        "as_of": session.scalar(select(func.transaction_timestamp())).isoformat(),
        "request_key": str(request_key),
        "request_digest": page.request_digest,
        "state": state,
        "receipt": receipt,
        "attempt": {
            "id": str(attempt["id"]),
            "revision": attempt["revision"],
            "status": attempt["status"],
        }
        if attempt is not None
        else None,
        "original": original,
        "source": source,
    }


def _unique_query(request):
    keys = [key for key, _ in request.query_params.multi_items()]
    if len(keys) != len(set(keys)):
        raise DomainError("VALIDATION_FAILED", "上传读取不能重复指定同一查询条件。", 422)


def router(*, transaction, context_dependency):
    result = APIRouter()

    @result.get("/v1/categories/{category_id}/agent-upload-target")
    def target(request: Request, page: Annotated[UploadScope, Query()], ctx=context_dependency):
        _unique_query(request)
        with transaction(ctx, read_snapshot=True) as session:
            return read_target(session, ctx, page)

    @result.get("/v1/categories/{category_id}/agent-upload-receipts/{request_key}")
    def receipt(
        request: Request,
        request_key: UUID,
        page: Annotated[UploadRecovery, Query()],
        ctx=context_dependency,
    ):
        _unique_query(request)
        with transaction(ctx, read_snapshot=True) as session:
            return read_receipt(session, ctx, request_key, page)

    return result
