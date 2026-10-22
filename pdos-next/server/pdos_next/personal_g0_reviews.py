"""Pending named G0 reviews under the caller's ordinary personal RR/RLS scope."""

from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select

from pdos_next import models
from pdos_next.domain.preproject.models import Proposal, ProposalDecision, ProposalSubmission
from pdos_next.errors import DomainError
from pdos_next.personal_views import _personal

VERSION = "personal-g0-reviews/v1"


def _pending(ctx):
    # Select columns explicitly: a queue head never loads the fixed document,
    # proposal/source bodies, or an ORM entity that could lazily load them.
    return (
        select(
            Proposal.id.label("proposal_id"),
            Proposal.title,
            Proposal.revision.label("proposal_revision"),
            Proposal.status,
            Proposal.category_id,
            models.Category.name.label("category_name"),
            Proposal.owner_id,
            models.Principal.name.label("owner_name"),
            ProposalSubmission.reviewer_id,
            ProposalSubmission.id.label("submission_id"),
            ProposalSubmission.revision.label("submission_revision"),
            ProposalSubmission.created_at.label("submitted_at"),
            ProposalSubmission.document_digest,
        )
        .select_from(Proposal)
        .join(
            ProposalSubmission,
            and_(
                ProposalSubmission.tenant_id == Proposal.tenant_id,
                ProposalSubmission.category_id == Proposal.category_id,
                ProposalSubmission.proposal_id == Proposal.id,
                ProposalSubmission.id == Proposal.current_submission_id,
            ),
        )
        .join(
            models.Category,
            and_(
                models.Category.tenant_id == Proposal.tenant_id,
                models.Category.id == Proposal.category_id,
            ),
        )
        .outerjoin(
            models.Principal,
            and_(
                models.Principal.tenant_id == Proposal.tenant_id,
                models.Principal.id == Proposal.owner_id,
            ),
        )
        .where(
            Proposal.tenant_id == ctx.tenant_id,
            Proposal.status == "in_review",
            ProposalSubmission.reviewer_id == ctx.requester_id,
            func.m3_reviewer(Proposal.tenant_id, Proposal.category_id, Proposal.id),
            ~exists().where(
                ProposalDecision.tenant_id == Proposal.tenant_id,
                ProposalDecision.category_id == Proposal.category_id,
                ProposalDecision.proposal_id == Proposal.id,
                ProposalDecision.submission_id == ProposalSubmission.id,
            ),
        )
    )


def read(session, ctx, *, cursor=None, page_size=50):
    """The route supplies one read-only RR transaction; never switch its scope."""
    _personal(session, ctx)
    if type(page_size) is not int or not 1 <= page_size <= 100:
        raise DomainError("VALIDATION_FAILED", "每页数量须为 1–100 的整数。", 422)
    if cursor is not None:
        try:
            cursor = cursor if isinstance(cursor, UUID) else UUID(cursor)
        except (ValueError, TypeError, AttributeError):
            raise DomainError("VALIDATION_FAILED", "分页位置须为提交记录 UUID。", 422) from None

    pending = _pending(ctx)
    page = pending
    if cursor is not None:
        anchor = session.execute(
            pending.with_only_columns(ProposalSubmission.id, ProposalSubmission.created_at).where(
                ProposalSubmission.id == cursor
            )
        ).first()
        if anchor is None:
            raise DomainError(
                "FORBIDDEN_SCOPE", "分页位置已不属于本人待评审事项，请刷新列表。", 403
            )
        page = page.where(
            or_(
                ProposalSubmission.created_at < anchor.created_at,
                and_(
                    ProposalSubmission.created_at == anchor.created_at,
                    ProposalSubmission.id < anchor.id,
                ),
            )
        )

    total = session.scalar(select(func.count()).select_from(pending.subquery()))
    rows = (
        session.execute(
            page.order_by(ProposalSubmission.created_at.desc(), ProposalSubmission.id.desc()).limit(
                page_size + 1
            )
        )
        .mappings()
        .all()
    )
    visible = rows[:page_size]
    return {
        "version": VERSION,
        "principal_id": str(ctx.requester_id),
        "as_of": session.scalar(select(func.transaction_timestamp())).isoformat(),
        "total_pending": total,
        "items": [
            {
                "proposal_id": str(row["proposal_id"]),
                # This is the current proposal head, not the fixed submission body.
                "title": row["title"],
                "proposal_revision": row["proposal_revision"],
                "status": row["status"],
                "category": {"id": str(row["category_id"]), "name": row["category_name"]},
                "owner": {"id": str(row["owner_id"]), "name": row["owner_name"]},
                "reviewer_id": str(row["reviewer_id"]),
                "submission": {
                    "id": str(row["submission_id"]),
                    "revision": row["submission_revision"],
                    "submitted_at": row["submitted_at"].isoformat(),
                    "document_digest": row["document_digest"],
                },
            }
            for row in visible
        ],
        "next_cursor": str(visible[-1]["submission_id"]) if len(rows) > page_size else None,
    }
