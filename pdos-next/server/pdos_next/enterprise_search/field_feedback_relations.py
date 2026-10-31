"""One-hop Field edges from exact native version references, never text similarity."""

from sqlalchemy import Integer, and_, cast, column, func, literal, select
from sqlalchemy.dialects.postgresql import JSONB, UUID

from pdos_next.domain.build_execution.models import BuildLot
from pdos_next.domain.change_execution.models import ChangeRequestVersion
from pdos_next.domain.field_feedback.models import FieldFeedbackVersion, FieldResponseRecord

from .readable_sources import readable


def append_edges(edge, kinds):
    if "field_feedback" not in kinds:
        return
    feedback, response = map(readable, (FieldFeedbackVersion, FieldResponseRecord))
    paired = select(response).join(feedback, and_(
        feedback.tenant_id == response.tenant_id,
        feedback.category_id == response.category_id,
        feedback.product_id.is_not_distinct_from(response.product_id),
        feedback.project_id.is_not_distinct_from(response.project_id),
        feedback.id == response.feedback_version_id,
        feedback.feedback_id == response.feedback_id,
        feedback.revision == response.feedback_revision,
    ))
    edge("field_feedback", feedback.id, "field_feedback", response.id,
         "field_response", paired)
    edge("field_feedback", response.id, "field_feedback", feedback.id,
         "response_field", paired)
    if "build" in kinds:
        lot = readable(BuildLot)
        batch = feedback.body["location"]["batch"]
        fixed_batch = select(feedback).join(lot, and_(
            lot.tenant_id == feedback.tenant_id, lot.category_id == feedback.category_id,
            lot.product_id == feedback.product_id, lot.project_id == feedback.project_id,
            lot.id == cast(batch["id"].astext, UUID),
            lot.revision == cast(batch["revision"].astext, Integer),
        )).where(feedback.body["location"]["state"].astext == "known")
        edge("field_feedback", feedback.id, "build", lot.id, "field_batch", fixed_batch)
        edge("build", lot.id, "field_feedback", feedback.id, "batch_field", fixed_batch)
    if "change" not in kinds:
        return
    change = readable(ChangeRequestVersion)
    refs = func.jsonb_array_elements(
        func.coalesce(change.request_snapshot["roots"], literal("[]").cast(JSONB)).op("||")(
            func.coalesce(change.request_snapshot["references"], literal("[]").cast(JSONB))
        )
    ).table_valued(column("value", JSONB)).render_derived(name="registered_field_change_refs")
    ref = refs.c.value
    fixed = select(change).join(refs, literal(True)).join(feedback, and_(
        feedback.tenant_id == change.tenant_id,
        feedback.category_id == change.category_id,
        feedback.product_id == change.product_id, feedback.project_id == change.project_id,
        feedback.feedback_id == cast(ref["id"].astext, UUID),
        feedback.revision == cast(ref["revision"].astext, Integer),
    )).where(ref["kind"].astext == "field_feedback")
    edge("change", change.id, "field_feedback", feedback.id, "change_field", fixed)
    edge("field_feedback", feedback.id, "change", change.id, "field_change", fixed)
