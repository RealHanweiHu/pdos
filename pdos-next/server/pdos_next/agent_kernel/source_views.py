"""Readable source metadata and exact Run bindings; no original text or model path."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import Field, ValidationError
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import load_only

from pdos_next.contracts import SourceRead
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Principal, UploadedOriginal
from pdos_next.request_proof import batch_read, scoped_rows
from pdos_next.schema_base import StrictModel
from pdos_next.service import require_access, source_for

from .models import AgentRun
from .run_reconciliation import owner

ARTIFACT_FIELDS = (
    "id",
    "tenant_id",
    "category_id",
    "product_id",
    "owner_id",
    "visibility",
    "title",
    "revision",
    "status",
    "original_id",
    "created_at",
)
ORIGINAL_FIELDS = (
    "id",
    "tenant_id",
    "category_id",
    "product_id",
    "owner_id",
    "visibility",
    "revision",
    "filename",
    "status",
    "parse_code",
    "scan_status",
    "content_hash",
    "byte_count",
    "media_type",
    "storage_key",
)


class SourcePage(StrictModel):
    product_id: UUID | None = None
    proposal_id: UUID | None = None
    cursor: UUID | None = None
    page_size: int = Field(default=20, ge=1, le=50)


def _scope(ctx, product_id, proposal_id):
    return {
        "category_id": str(ctx.category_id),
        "product_id": str(product_id) if product_id else None,
        "proposal_id": str(proposal_id) if proposal_id else None,
    }


def _human(session, ctx, product_id=None, proposal_id=None):
    require_access(session, ctx, product_id)
    actor = session.get(Principal, ctx.actor_id)
    if (
        ctx.category_id is None
        or ctx.actor_id != ctx.requester_id
        or ctx.run_id
        or ctx.agent_run_id
        or actor is None
        or actor.kind != "human"
        or not actor.active
        or actor.tenant_id != ctx.tenant_id
    ):
        raise DomainError("FORBIDDEN_SCOPE", "资料只向当前品类内的具名本人显示。", 403)
    if proposal_id is not None:
        from pdos_next.domain.preproject.access import proposal

        proposal(session, ctx, proposal_id)


def _query(ctx, product_id):
    query = (
        select(Artifact)
        .where(
            Artifact.tenant_id == ctx.tenant_id,
            Artifact.category_id == ctx.category_id,
        )
        .options(
            load_only(*(getattr(Artifact, field) for field in ARTIFACT_FIELDS), raiseload=True)
        )
    )
    if product_id is None:
        return query.where(Artifact.product_id.is_(None))
    return query.where(or_(Artifact.product_id.is_(None), Artifact.product_id == product_id))


def _metadata(session, rows, ctx, consumer_product_id):
    """Reuse actual ordinary-RLS ORM heads in this one read-only RR transaction."""
    # batch_read recognizes these already loaded identities through the existing
    # snapshot proof adapter. source_for still checks scope/status/version/safety.
    batch_read(session, Artifact, [row.id for row in rows])
    originals = {}
    for row in rows:
        if row.original_id is None:
            continue
        product_id = (
            row.product_id
            if row.product_id not in (None, consumer_product_id)
            else consumer_product_id
        )
        query = (
            select(UploadedOriginal)
            .where(
                UploadedOriginal.tenant_id == ctx.tenant_id,
                UploadedOriginal.category_id == ctx.category_id,
                UploadedOriginal.id == row.original_id,
                or_(
                    UploadedOriginal.product_id.is_(None), UploadedOriginal.product_id == product_id
                ),
            )
            .options(
                load_only(
                    *(getattr(UploadedOriginal, field) for field in ORIGINAL_FIELDS), raiseload=True
                )
            )
        )
        # The exact existing require_original scoped-read key, backed by its
        # actual RLS query. Its later safety recheck reuses these metadata only.
        loaded = scoped_rows(
            session, (UploadedOriginal, ctx.category_id, product_id, row.original_id), query
        )
        if loaded:
            originals[row.original_id] = loaded[0]
    batch_read(session, UploadedOriginal, originals)
    return originals


def _head(session, ctx, product_id, row, originals, *, expected_revision=None):
    original = originals.get(row.original_id)
    if original is not None and original.product_id != row.product_id:
        raise DomainError("INTEGRITY_MISMATCH", "资料与原件的固定范围无法核对。", 409)
    code = None
    try:
        if row.original_id is not None and original is None:
            # The ordinary metadata query already proved the linked Original
            # unavailable. Do not fall through to require_original's full row.
            raise DomainError("SOURCE_UNAVAILABLE", "原件不在当前授权范围。", 403)
        actual = source_for(session, ctx, product_id, row.id, expected_revision or row.revision)
        if actual is not row or actual.revision != row.revision:
            raise DomainError("INTEGRITY_MISMATCH", "资料版本无法与当前读取快照核对。", 409)
    except DomainError as error:
        if error.reason not in {
            "SOURCE_UNAVAILABLE",
            "SOURCE_STALE",
            "FORBIDDEN_SCOPE",
            "ORIGINAL_SECURITY_BLOCKED",
            "ORIGINAL_SECURITY_UNAVAILABLE",
        }:
            raise
        code = error.reason
    return {
        "artifact_id": str(row.id),
        "artifact_revision": row.revision,
        "title": row.title,
        "product_id": str(row.product_id) if row.product_id else None,
        "status": row.status,
        "original": {
            "id": str(original.id),
            "revision": original.revision,
            "filename": original.filename,
            "parse_status": original.status,
            "parse_code": original.parse_code,
            "scan_status": original.scan_status,
        }
        if original
        else None,
        "availability": {"available": code is None, "code": code},
    }


def read_list(session, ctx, page):
    _human(session, ctx, page.product_id, page.proposal_id)
    query = _query(ctx, page.product_id)
    if page.cursor is not None:
        anchor = session.scalar(query.where(Artifact.id == page.cursor))
        if anchor is None:
            raise DomainError("FORBIDDEN_SCOPE", "资料分页位置已不可读，请刷新当前范围。", 403)
        query = query.where(
            or_(
                Artifact.created_at < anchor.created_at,
                and_(Artifact.created_at == anchor.created_at, Artifact.id < anchor.id),
            )
        )
    rows = list(
        session.scalars(
            query.order_by(Artifact.created_at.desc(), Artifact.id.desc()).limit(page.page_size + 1)
        )
    )
    visible = rows[: page.page_size]
    originals = _metadata(session, visible, ctx, page.product_id)
    return {
        "version": "agent-input-sources/v1",
        "principal_id": str(ctx.requester_id),
        "scope": _scope(ctx, page.product_id, page.proposal_id),
        "as_of": session.scalar(select(func.transaction_timestamp())).isoformat(),
        "items": [_head(session, ctx, page.product_id, row, originals) for row in visible],
        "next_cursor": str(visible[-1].id) if len(rows) > page.page_size else None,
    }


def _bindings(run):
    if not isinstance(run.read_sources, list):
        raise DomainError("INTEGRITY_MISMATCH", "原运行的资料绑定格式无法核对。", 409)
    values = {}
    try:
        for raw in run.read_sources:
            if not isinstance(raw, dict) or set(raw) != {
                "artifact_id",
                "expected_revision",
                "product_id",
            }:
                raise ValueError("Exact bound source fields are required")
            ref = SourceRead.model_validate(
                {key: raw[key] for key in ("artifact_id", "expected_revision")}
            )
            product_id = UUID(raw["product_id"]) if raw["product_id"] is not None else None
            if ref.artifact_id in values:
                raise ValueError("Bound artifact identities must not repeat")
            values[ref.artifact_id] = (ref.expected_revision, product_id)
    except (TypeError, ValueError, ValidationError, KeyError) as error:
        raise DomainError("INTEGRITY_MISMATCH", "原运行的资料绑定无法完整核对。", 409) from error
    return values


def read_bindings(session, ctx, run_id):
    row = session.scalar(
        select(AgentRun)
        .where(
            AgentRun.tenant_id == ctx.tenant_id,
            AgentRun.category_id == ctx.category_id,
            AgentRun.id == run_id,
        )
        .options(
            load_only(
                AgentRun.id,
                AgentRun.tenant_id,
                AgentRun.category_id,
                AgentRun.product_id,
                AgentRun.proposal_id,
                AgentRun.requester_id,
                AgentRun.session_id,
                AgentRun.read_sources,
                raiseload=True,
            )
        )
    )
    owner(session, ctx, row)
    _human(session, ctx, row.product_id, row.proposal_id)
    refs = _bindings(row)
    # Binding history may contain actual source Products different from the Run
    # scope. Ordinary source RLS and source_for retain those exact parent fences.
    heads = list(
        session.scalars(
            select(Artifact)
            .where(
                Artifact.tenant_id == ctx.tenant_id,
                Artifact.category_id == ctx.category_id,
                Artifact.id.in_(refs),
            )
            .options(
                load_only(*(getattr(Artifact, field) for field in ARTIFACT_FIELDS), raiseload=True)
            )
        )
    )
    by_id = {head.id: head for head in heads}
    originals = _metadata(session, heads, ctx, row.product_id)
    items = []
    for identity, (revision, product_id) in sorted(refs.items(), key=lambda value: str(value[0])):
        head = by_id.get(identity)
        if head is not None and head.product_id != product_id:
            raise DomainError("INTEGRITY_MISMATCH", "原资料绑定与当前型号范围无法核对。", 409)
        items.append(
            {
                "artifact_id": str(identity),
                "expected_revision": revision,
                "product_id": str(product_id) if product_id else None,
                "current": _head(
                    session, ctx, row.product_id, head, originals, expected_revision=revision
                )
                if head is not None
                else None,
            }
        )
    return {
        "version": "agent-run-source-bindings/v1",
        "principal_id": str(ctx.requester_id),
        "scope": _scope(ctx, row.product_id, row.proposal_id),
        "as_of": session.scalar(select(func.transaction_timestamp())).isoformat(),
        "run_id": str(row.id),
        "session_id": str(row.session_id),
        "items": items,
    }


def router(*, transaction, context_dependency):
    result = APIRouter()

    @result.get("/v1/categories/{category_id}/agent-input-sources")
    def listing(page: Annotated[SourcePage, Query()], ctx=context_dependency):
        with transaction(ctx, read_snapshot=True) as session:
            return read_list(session, ctx, page)

    @result.get("/v1/categories/{category_id}/agent-runs/{run_id}/source-bindings")
    def bindings(request: Request, run_id: UUID, ctx=context_dependency):
        if request.query_params:
            raise DomainError("VALIDATION_FAILED", "运行资料绑定不接受额外查询条件。", 422)
        with transaction(ctx, read_snapshot=True) as session:
            return read_bindings(session, ctx, run_id)

    return result
