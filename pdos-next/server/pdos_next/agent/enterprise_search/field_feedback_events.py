"""Actual Field Outbox subjects, including every immutable intake/location version."""

from sqlalchemy import select

from pdos_next.domain.field_feedback.models import (
    ACTION,
    CREATE,
    EVENTS,
    LINK,
    LOCATE,
    FieldFeedbackVersion,
    FieldResponseRecord,
)

OPERATIONS = frozenset(EVENTS)
EVENT_TYPES = frozenset(EVENTS.values())


def targets(session, event, receipt):
    if receipt.operation not in OPERATIONS or EVENTS[receipt.operation] != event.type:
        return []
    model = FieldFeedbackVersion if receipt.operation in {CREATE, LOCATE} else FieldResponseRecord
    # Resolve through the committed native receipt, rather than event prose.
    query = select(model.id).where(
        model.tenant_id == event.tenant_id, model.category_id == event.category_id,
        model.product_id.is_not_distinct_from(receipt.product_id),
        model.receipt_id == receipt.id, model.command_id == receipt.command_id,
        model.operation == receipt.operation, model.id == event.subject_id,
        model.revision == event.subject_revision,
    )
    identities = list(session.scalars(query))
    if receipt.operation == LOCATE:
        # The previous fixed intake changes only its currentness; it must also
        # be rechecked after location, without rewriting its original content.
        lineage = select(FieldFeedbackVersion.feedback_id).where(
            FieldFeedbackVersion.tenant_id == event.tenant_id,
            FieldFeedbackVersion.id.in_(identities),
        )
        identities = list(session.scalars(select(FieldFeedbackVersion.id).where(
            FieldFeedbackVersion.tenant_id == event.tenant_id,
            FieldFeedbackVersion.category_id == event.category_id,
            FieldFeedbackVersion.feedback_id.in_(lineage),
        )))
    assert receipt.operation in {CREATE, LOCATE, ACTION, LINK}
    return [("field_feedback", identity) for identity in identities]
