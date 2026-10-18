"""Current recipient review metadata for one already-resolved actual promise."""

from sqlalchemy import and_, select

from pdos_next.domain.work_fulfillment.models import WorkCommitmentReview as Review
from pdos_next.domain.work_fulfillment.models import WorkCommitmentReviewCurrent as Current
from pdos_next.domain.work_management.models import BINDING
from pdos_next.errors import DomainError


def commitment_fulfilled(s, ctx, promise):
    """No body, old review history, confirmation or original source is reread."""
    if (promise.tenant_id, promise.category_id) != (ctx.tenant_id, ctx.category_id):
        raise DomainError("FORBIDDEN_SCOPE", "承诺履行来源不在当前实际范围内。", 403)
    value = (
        s.execute(
            select(
                Current.version_id,
                Current.revision,
                Current.state,
                Review.id.label("review_id"),
                Review.revision.label("review_revision"),
                Review.state.label("review_state"),
                Review.commitment_revision,
                Review.series_id,
                Review.task_id,
                Review.promisor_id,
                Review.recipient_id,
            )
            .select_from(Current)
            .outerjoin(
                Review,
                and_(
                    *(getattr(Review, key) == getattr(Current, key) for key in BINDING),
                    Review.commitment_id == Current.commitment_id,
                    Review.id == Current.version_id,
                    Review.revision == Current.revision,
                    Review.state == Current.state,
                ),
            )
            .where(
                *(getattr(Current, key) == getattr(promise, key) for key in BINDING),
                Current.commitment_id == promise.id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if value is None:
        return False
    if (
        (value["version_id"], value["revision"], value["state"])
        != (value["review_id"], value["review_revision"], value["review_state"])
        or value["state"] not in {"open", "fulfilled"}
        or value["revision"] < 1
        or (
            value["commitment_revision"],
            value["series_id"],
            value["task_id"],
            value["promisor_id"],
            value["recipient_id"],
        )
        != (
            promise.revision,
            promise.series_id,
            promise.task_id,
            promise.promisor_id,
            promise.recipient_id,
        )
    ):
        raise DomainError("INTEGRITY_MISMATCH", "承诺履行Current与固定接收者记录无法核对。")
    return value["state"] == "fulfilled"
