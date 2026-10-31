"""Review metadata beside real native knowledge versions and their original receipts."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select

from pdos_next.category_scope import category_scope
from pdos_next.models import Grant, Principal, now

from .assistant_models import KnowledgeAnswerReview
from .assistant_sources import capture, inherited_proof, recheck, require


def validate_review(session, ctx, metadata, *, new_date=True):
    category = category_scope(session, ctx)
    person = session.get(Principal, metadata.responsible_id)
    grant = session.scalar(
        select(Grant).where(
            Grant.tenant_id == ctx.tenant_id,
            Grant.category_id == ctx.category_id,
            Grant.principal_id == metadata.responsible_id,
        )
    )
    require(
        person is not None
        and person.tenant_id == ctx.tenant_id
        and person.active
        and person.kind == "human"
        and (
            category.owner_id == person.id
            or grant is not None
            and (grant.expires_at is None or grant.expires_at > now())
        ),
        "负责人须是本品类当前有权的实际人员。",
        "FORBIDDEN_SCOPE",
        403,
    )
    require(
        not new_date or metadata.review_due_at > now(),
        "请选择实际未来的复核日期。",
        "VALIDATION_FAILED",
        422,
    )


def prepare(session, ctx, payload, *, shared=False, previous=None, promoted=False):
    metadata = getattr(payload, "knowledge_review", None)
    origin = getattr(payload, "answer_origin", None)
    if metadata is None and origin is None and previous is None:
        return None
    require(
        ctx.actor_id == ctx.requester_id and not ctx.agent_run_id and not ctx.run_id,
        "知识沉淀与复核由本人发起。",
        "FORBIDDEN_SCOPE",
        403,
    )
    if metadata is None:
        from .assistant_schemas import KnowledgeReview

        metadata = KnowledgeReview(
            responsible_id=previous.responsible_id,
            applicability_scope=previous.applicability_scope,
            review_due_at=previous.review_due_at,
        )
    validate_review(
        session, ctx, metadata, new_date=getattr(payload, "knowledge_review", None) is not None
    )
    source = (
        capture(session, ctx, origin.run_id, expected_digest=origin.answer_digest)
        if origin
        else None
    )
    proof = (
        inherited_proof(session, source["source_proof"])
        if source
        else previous.source_proof
        if previous
        else []
    )
    if getattr(payload, "kind", None) == "verified_answer":
        require(
            source is not None or previous is not None and previous.origin_run_id is not None,
            "核实答案须来自实际回答或其原知识版本。",
            "MISSING_REQUIRED_EVIDENCE",
            422,
        )
    if (getattr(payload, "kind", None) == "verified_answer" and not promoted) or (
        hasattr(payload, "sources") and not payload.sources and not promoted
    ):
        require(
            bool(proof),
            "核实答案须保留实际回答依据或原去标识证明。",
            "MISSING_REQUIRED_EVIDENCE",
            422,
        )
    actual = recheck(session, proof) if proof else {}
    restricted = bool(source and (source["private"] or source["customer_original"])) or any(
        row["private"] or row["customer_original"] for row in actual.values()
    )
    require(
        not shared or promoted or not restricted,
        "客户或私有来源须走原去标识沉淀，不能直接进入共享知识。",
        "FORBIDDEN_SCOPE",
        403,
    )
    # Native promotion retains its private proposal proof. Never copy those
    # private source identities into the shared answer's retrieval metadata.
    return {
        **metadata.model_dump(mode="json"),
        "origin_run_id": str(origin.run_id)
        if origin
        else str(previous.origin_run_id)
        if previous and previous.origin_run_id
        else None,
        "answer_digest": source["answer_digest"]
        if source
        else previous.answer_digest
        if previous
        else None,
        "source_proof": [] if promoted else proof,
        "basis_count": max(
            len(proof),
            getattr(previous, "basis_count", 0),
            len({(ref.kind, ref.id, ref.revision) for ref in getattr(payload, "sources", [])}),
        ),
        "private": restricted,
    }


def append(session, ctx, command, kind, subject_id, receipt_id, prepared, *, verified=False):
    if prepared is None:
        return
    session.add(
        KnowledgeAnswerReview(
            tenant_id=ctx.tenant_id,
            category_id=ctx.category_id,
            subject_kind=kind,
            subject_id=subject_id,
            responsible_id=UUID(prepared["responsible_id"]),
            applicability_scope=prepared["applicability_scope"],
            review_due_at=datetime.fromisoformat(prepared["review_due_at"]),
            origin_run_id=UUID(prepared["origin_run_id"]) if prepared["origin_run_id"] else None,
            answer_digest=prepared["answer_digest"],
            source_proof=prepared["source_proof"],
            basis_count=prepared["basis_count"],
            verified_by=ctx.requester_id if verified else None,
            command_id=command.command_id,
            receipt_id=receipt_id,
        )
    )


def status(row, at=None):
    if row is None:
        return {"state": "unverified", "priority": 0}
    overdue = (at or now()) >= row.review_due_at
    return {
        "state": "needs_review" if overdue else "verified" if row.verified_by else "draft",
        "label": "待复核" if overdue else "已核实" if row.verified_by else "AI 草稿",
        "priority": -1 if overdue else 1 if row.verified_by else 0,
        "responsible_id": str(row.responsible_id),
        "applicability_scope": row.applicability_scope,
        "review_due_at": row.review_due_at.isoformat(),
        "verified_by": str(row.verified_by) if row.verified_by else None,
        "draft_origin": "ai_draft",
        "basis_count": getattr(row, "basis_count", len(getattr(row, "source_proof", []))),
    }
