"""Fixed native Field facts, using the shared source/RLS/original dependency port."""

from sqlalchemy import Text, and_, case, cast, column, func, literal, select
from sqlalchemy.dialects.postgresql import JSONB

from pdos_next.domain.field_feedback.models import (
    FieldFeedbackCurrent,
    FieldFeedbackVersion,
    FieldResponseRecord,
)


def artifact_reads(model):
    """The native retained basis includes parent and linked-result originals.

    An action's direct command reads alone deliberately omit historical parents;
    search must retain all of its actual native basis for privacy/scan filtering.
    """
    roots = func.jsonb_array_elements(model.source_basis["artifacts"]).table_valued(
        column("value", JSONB),
    ).render_derived(name="field_basis_" + model.__table__.name)
    return select(func.coalesce(func.jsonb_agg(func.jsonb_build_object(
        "artifact_id", roots.c.value["id"], "expected_revision", roots.c.value["revision"],
    )), func.jsonb_build_array())).select_from(roots).correlate(model).scalar_subquery()


def projectors(native, readable):
    """Customer/field reported text is untrusted; performed staff facts stay distinct.

    Never manufacture an Issue or an accepted configuration from a reported
    label. Category-only intake remains searchable before a real T1 location.
    """
    feedback, pointer, response = map(
        readable, (FieldFeedbackVersion, FieldFeedbackCurrent, FieldResponseRecord)
    )
    current = and_(
        pointer.tenant_id == feedback.tenant_id,
        pointer.category_id == feedback.category_id,
        pointer.feedback_id == feedback.feedback_id,
    )
    common = ("仅表示已登记的来源、定位或独立跟进；客户意见与承认声明不批准放行，"
              "链接结果不代替实施或复验。")
    facts = func.jsonb_build_object(
        "record_kind", "field_feedback", "operation", feedback.operation,
        "feedback_id", feedback.feedback_id, "feedback_revision", feedback.revision,
        "title", feedback.body["title"], "description", feedback.body["description"],
        "channel", feedback.body["channel"], "feedback_kind", feedback.body["feedback_kind"],
        "reported", feedback.body["reported"], "received_at", feedback.body["received_at"],
        "purpose", feedback.body["purpose"], "location", feedback.body["location"],
        "location_status", case(
            (feedback.body["location"]["state"].astext == "known", "known"), else_="unknown",
        ),
        "continuation_permission", "not_evaluated", "record_policy", common,
    )
    result = [native(
        "field_feedback", feedback, (pointer, current), pointer.version_id == feedback.id,
        feedback.feedback_id, feedback.body["title"].astext, facts, artifact_reads(feedback),
        nature="untrusted", optional_scope=True,
        extra_customer_original=feedback.body["channel"].astext == "customer",
    )]
    fixed_parent = and_(
        feedback.tenant_id == response.tenant_id,
        feedback.category_id == response.category_id,
        feedback.product_id.is_not_distinct_from(response.product_id),
        feedback.project_id.is_not_distinct_from(response.project_id),
        feedback.feedback_id == response.feedback_id,
        feedback.id == response.feedback_version_id,
        feedback.revision == response.feedback_revision,
    )
    response_pointer = and_(
        pointer.tenant_id == response.tenant_id,
        pointer.category_id == response.category_id,
        pointer.feedback_id == response.feedback_id,
    )
    performed = func.jsonb_build_object(
        "record_kind", "field_response", "operation", response.operation,
        "feedback_id", response.feedback_id, "feedback_version_id", response.feedback_version_id,
        "feedback_revision", response.feedback_revision, "response_kind", response.response_kind,
        "description", response.body["description"], "occurred_at", response.body["occurred_at"],
        "result_receipts", response.body["result_receipts"],
        "actor_id", response.actor_id, "record_policy", common,
        "continuation_permission", "not_evaluated",
    )
    result.append(native(
        "field_feedback", response, (pointer, response_pointer),
        pointer.version_id == response.feedback_version_id,
        response.feedback_id,
        literal("现场反馈跟进 · ") + cast(response.response_kind, Text),
        performed, artifact_reads(response), joins=((feedback, fixed_parent),), optional_scope=True,
        extra_private=feedback.visibility != "category",
        extra_customer_original=feedback.body["channel"].astext == "customer",
    ))
    return result
