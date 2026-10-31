"""Actual verified answers, review reminders and native command seeds."""

from sqlalchemy import select

from pdos_next.category_scope import category_scope
from pdos_next.clock import now
from pdos_next.domain.preproject.category_models import KnowledgeCurrent, KnowledgeEntry
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Principal
from pdos_next.service import require_access

from .assistant_models import KnowledgeAnswerReview
from .assistant_reviews import status
from .assistant_sources import capture, recheck, require


def draft(session, ctx, data):
    category = category_scope(session, ctx, write=True)
    source = capture(session, ctx, data.run_id)
    run = source["run"]
    people = (
        session.execute(
            select(Principal.id, Principal.name)
            .outerjoin(
                Grant,
                ((Grant.tenant_id == Principal.tenant_id) & (Grant.principal_id == Principal.id)),
            )
            .where(
                Principal.tenant_id == ctx.tenant_id,
                Principal.active,
                Principal.kind == "human",
                (
                    (Grant.category_id == ctx.category_id)
                    & (Grant.expires_at.is_(None) | (Grant.expires_at > now()))
                )
                | (Principal.id == category.owner_id),
            )
        )
        .unique()
        .all()
    )
    # No date or applicability is invented. The Human supplies these required values.
    origin = {"run_id": str(run.id), "answer_digest": source["answer_digest"]}
    command_scope = {
        "category_id": str(ctx.category_id),
        "product_id": None,
        "expected_revision": category.revision,
    }
    if data.kind == "rule":
        require(
            all(identity == str(run.product_id) for identity in source["source_product_ids"]),
            "本回答引用了其他型号的资料。请从资料所属的实际型号或项目重新查询后整理经验候选，原回答会保留。",
            "FORBIDDEN_SCOPE",
            403,
        )
        product = require_access(session, ctx, run.product_id, write=False)
        command_scope.update(
            product_id=str(run.product_id) if run.product_id else None,
            expected_revision=product.revision,
        )
        payload = {
            "project_id": str(run.project_id) if run.project_id else None,
            "visibility": "private"
            if source["private"] or source["customer_original"]
            else "category",
            "title": "回答经验候选",
            "lesson": source["answer"][:4000],
            "evidence_summary": f"来自本人实际回答，{len(source['source_proof'])} 项固定来源。",
            "applicability_hypothesis": "待本人核对本次实际用途与适用边界。",
            "result_receipts": [],
            "sources": source["artifacts"],
            "reason": "本人从已核来源回答整理经验候选",
            "answer_origin": origin,
        }
        operation = "knowledge.candidate.create"
    else:
        require(
            not source["private"] and not source["customer_original"] or run.proposal_id,
            "这次回答含私有或客户资料；请先走原提案的去标识沉淀。",
            "FORBIDDEN_SCOPE",
            403,
        )
        payload = {
            "kind": "verified_answer",
            "content": {
                "title": "核实答案",
                "question": source["question"],
                "answer": source["answer"],
                "draft_origin": "ai_draft",
            },
            "answer_origin": origin,
        }
        operation = "category.knowledge.add"
        if source["private"] or source["customer_original"]:
            from pdos_next.domain.preproject.access import proposal

            original = proposal(session, ctx, run.proposal_id)
            operation = "category.knowledge.promote"
            payload.update(
                source_proposal_id=str(original.id),
                source_proposal_revision=original.revision,
                source_item_refs=[],
                deidentified_confirmed=False,
            )
    return {
        "command_scope": command_scope,
        "operation": operation,
        "payload": payload,
        "question": source["question"],
        "answer": source["answer"],
        "basis_count": len(source["source_proof"]),
        "people": [dict(row._mapping) for row in people],
        "default_responsible_id": str(ctx.requester_id),
        "draft_origin": "ai_draft",
    }


def verified_answers(session, ctx):
    category_scope(session, ctx)
    rows = session.execute(
        select(KnowledgeEntry, KnowledgeAnswerReview)
        .join(
            KnowledgeCurrent,
            (KnowledgeCurrent.tenant_id == KnowledgeEntry.tenant_id)
            & (KnowledgeCurrent.current_entry_id == KnowledgeEntry.id)
            & (KnowledgeCurrent.status == "active"),
        )
        .join(
            KnowledgeAnswerReview,
            (KnowledgeAnswerReview.tenant_id == KnowledgeEntry.tenant_id)
            & (KnowledgeAnswerReview.subject_kind == "category")
            & (KnowledgeAnswerReview.subject_id == KnowledgeEntry.id),
        )
        .where(
            KnowledgeEntry.tenant_id == ctx.tenant_id,
            KnowledgeEntry.category_id == ctx.category_id,
            KnowledgeEntry.kind == "verified_answer",
        )
        .order_by(KnowledgeEntry.created_at.desc(), KnowledgeEntry.id)
        .limit(100)
    ).all()
    items = []
    for entry, review in rows:
        try:
            recheck(session, review.source_proof)
        except DomainError:
            continue
        items.append(
            {
                "id": str(entry.id),
                "lineage_id": str(entry.lineage_id),
                "version": entry.version,
                "content": entry.content,
                "review": status(review),
                "basis_count": review.basis_count,
            }
        )
    category = category_scope(session, ctx)
    return {
        "items": items,
        "category_revision": category.revision,
        "can_manage_gaps": category.owner_id == ctx.requester_id,
        "as_of": now().isoformat(),
    }


def reminders(session, ctx):
    from .models import DesignRuleCurrent, KnowledgeCandidateCurrent

    # Current pointers ensure superseded versions never produce a duplicate reminder.
    current = select(KnowledgeCurrent.current_entry_id).where(KnowledgeCurrent.status == "active")
    candidate = select(KnowledgeCandidateCurrent.version_id)
    rule = select(DesignRuleCurrent.version_id)
    rows = session.scalars(
        select(KnowledgeAnswerReview)
        .where(
            KnowledgeAnswerReview.tenant_id == ctx.tenant_id,
            KnowledgeAnswerReview.responsible_id == ctx.requester_id,
            KnowledgeAnswerReview.review_due_at <= now(),
            (
                (KnowledgeAnswerReview.subject_kind == "category")
                & KnowledgeAnswerReview.subject_id.in_(current)
            )
            | (
                (KnowledgeAnswerReview.subject_kind == "candidate")
                & KnowledgeAnswerReview.subject_id.in_(candidate)
            )
            | (
                (KnowledgeAnswerReview.subject_kind == "rule")
                & KnowledgeAnswerReview.subject_id.in_(rule)
            ),
        )
        .order_by(KnowledgeAnswerReview.review_due_at, KnowledgeAnswerReview.id)
        .limit(100)
    ).all()
    return {
        "items": [
            {
                "subject_kind": row.subject_kind,
                "subject_id": str(row.subject_id),
                "category_id": str(row.category_id),
                "review_due_at": row.review_due_at.isoformat(),
                "applicability_scope": row.applicability_scope,
            }
            for row in rows
        ],
        "as_of": now().isoformat(),
    }


def review_draft(session, ctx, data):
    from pdos_next.domain.preproject.access import proposal
    from pdos_next.domain.preproject.category_models import PromotionProof

    from .assistant_sources import review_for

    category_scope(session, ctx, write=True)
    entry = session.get(KnowledgeEntry, data.entry_id)
    require(
        entry is not None
        and entry.category_id == ctx.category_id
        and entry.kind == "verified_answer",
        "这条核实答案当前不可读。",
        "FORBIDDEN_SCOPE",
        403,
    )
    pointer = session.scalar(
        select(KnowledgeCurrent).where(
            KnowledgeCurrent.current_entry_id == entry.id, KnowledgeCurrent.status == "active"
        )
    )
    previous = review_for(session, "category", entry.id)
    require(pointer is not None and previous is not None, "原知识版本已变化。", "VERSION_CONFLICT")
    recheck(session, previous.source_proof)
    payload = {
        "kind": "verified_answer",
        "content": entry.content,
        "supersedes": {"lineage_id": str(entry.lineage_id), "expected_version": entry.version},
        "knowledge_review": {
            "responsible_id": str(previous.responsible_id),
            "applicability_scope": previous.applicability_scope,
            "review_due_at": previous.review_due_at.isoformat(),
        },
    }
    operation = "category.knowledge.add"
    proof = session.scalar(
        select(PromotionProof).where(PromotionProof.knowledge_entry_id == entry.id)
    )
    if proof:
        original = proposal(session, ctx, proof.source_proposal_id)
        operation = "category.knowledge.promote"
        payload.update(
            source_proposal_id=str(original.id),
            source_proposal_revision=original.revision,
            source_item_refs=proof.source_item_refs,
            deidentified_confirmed=False,
        )
    people = session.execute(
        select(Principal.id, Principal.name)
        .join(
            Grant, (Grant.tenant_id == Principal.tenant_id) & (Grant.principal_id == Principal.id)
        )
        .where(
            Principal.tenant_id == ctx.tenant_id,
            Principal.active,
            Principal.kind == "human",
            Grant.category_id == ctx.category_id,
            Grant.expires_at.is_(None) | (Grant.expires_at > now()),
        )
    ).all()
    return {
        "command_scope": {
            "category_id": str(ctx.category_id),
            "product_id": None,
            "expected_revision": entry.version,
        },
        "operation": operation,
        "payload": payload,
        "question": entry.content["question"],
        "answer": entry.content["answer"],
        "basis_count": previous.basis_count,
        "people": [dict(row._mapping) for row in people],
        "default_responsible_id": str(previous.responsible_id),
        "draft_origin": "ai_draft",
    }
