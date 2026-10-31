"""Native role records under the shared ordinary-RLS source projector.

No Artifact is synthesized. Draft documents, formally published document links,
named project reports and physical handoff facts keep their own fixed identity.
"""

from sqlalchemy import Text, and_, cast, column, exists, func, literal, select, tuple_
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import aliased

from pdos_next.domain.manufacturing_baseline.models import PreparationCurrent, PreparationVersion
from pdos_next.domain.manufacturing_baseline.publication_models import (
    ManufacturingBaselinePublication,
    ManufacturingBaselinePublicationCurrent,
    ManufacturingPublicationDocument,
)
from pdos_next.domain.verification_front.models import (
    FormalVerificationCurrent,
    FormalVerificationRequest,
)
from pdos_next.domain.verification_handoff.models import VerificationHandoffFact
from pdos_next.domain.work_management.models import ProjectStatusUpdate

FAMILIES = frozenset({"project_status", "manufacturing_document", "verification_handoff"})
MODELS = {
    "project_status": (ProjectStatusUpdate,),
    "manufacturing_document": (PreparationVersion, ManufacturingPublicationDocument),
    "verification_handoff": (VerificationHandoffFact,),
}


def scope(left, right):
    return and_(
        *(
            getattr(left, key) == getattr(right, key)
            for key in ("tenant_id", "category_id", "product_id", "project_id")
        )
    )


def document_facts(document):
    from .business_sources import array_fields

    data = document.body["input"]
    # Sources and snapshots contain literal customer/input references. Keep only
    # the actual employee-authored document fields, never those containers.
    steps = (
        func.jsonb_array_elements(func.coalesce(data["steps"], literal("[]").cast(JSONB)))
        .table_valued(column("value", JSONB), with_ordinality="ordinal")
        .render_derived(name="native_instruction_steps")
    )
    value = steps.c.value
    parameters = array_fields(
        value["parameters"],
        ("key", "unit", "nominal", "lower", "upper", "nature", "condition"),
        name="native_instruction_parameters",
    )
    from sqlalchemy.dialects.postgresql import aggregate_order_by

    instruction = (
        select(
            func.coalesce(
                func.jsonb_agg(
                    aggregate_order_by(
                        func.jsonb_build_object(
                            "key",
                            value["key"],
                            "text",
                            value["text"],
                            "safety_notes",
                            value["safety_notes"],
                            "parameters",
                            parameters,
                        ),
                        steps.c.ordinal,
                    )
                ),
                func.jsonb_build_array(),
            )
        )
        .select_from(steps)
        .scalar_subquery()
    )
    checks = array_fields(
        data["checks"],
        (
            "key",
            "feature",
            "method",
            "frequency",
            "sampling_method",
            "reaction_plan",
            "responsible_role",
            ("criterion_key", ("criterion", "key")),
            ("criterion_unit", ("criterion", "unit")),
            ("criterion_nominal", ("criterion", "nominal")),
            ("criterion_lower", ("criterion", "lower")),
            ("criterion_upper", ("criterion", "upper")),
            ("criterion_nature", ("criterion", "nature")),
        ),
        name="native_control_checks",
    )
    return func.jsonb_build_object(
        "document_kind",
        document.kind,
        "document_id",
        document.id,
        "document_revision",
        document.revision,
        "series_id",
        document.series_id,
        "title",
        document.title,
        "process_id",
        document.process_id,
        "process_revision",
        document.process_revision,
        "operation_key",
        document.operation_key,
        "conditions",
        data["conditions"],
        "steps",
        instruction,
        "checks",
        checks,
        "declared_gaps",
        array_fields(
            document.body["gaps"], ("code", "message"), name="native_document_declared_gaps"
        ),
        "continuation_permission",
        "not_evaluated",
    )


def projectors(native, readable, selected):
    result = []
    if "project_status" in selected:
        update = readable(ProjectStatusUpdate)
        newer = aliased(update, name="later_named_project_update")
        latest = ~exists(
            select(1)
            .select_from(newer)
            .where(
                scope(newer, update),
                tuple_(newer.created_at, newer.id) > tuple_(update.created_at, update.id),
            )
        ).correlate(update)
        facts = func.jsonb_build_object(
            "record_kind",
            "named_project_status",
            "operation",
            update.operation,
            "fact_summary",
            update.fact_summary,
            "next_steps",
            update.next_steps,
            "task_refs",
            update.task_refs,
            "recorded_by",
            update.actor_id,
            "recorded_at",
            update.created_at,
            "continuation_permission",
            "not_evaluated",
        )
        from .field_feedback_sources import artifact_reads

        result.append(
            native(
                "project_status",
                update,
                None,
                latest,
                update.project_id,
                literal("项目具名状态 · ") + update.fact_summary,
                facts,
                update.reads.op("||")(artifact_reads(update)),
            )
        )
    if "manufacturing_document" in selected:
        doc, pointer = map(readable, (PreparationVersion, PreparationCurrent))
        current = and_(
            scope(pointer, doc), pointer.kind == doc.kind, pointer.series_id == doc.series_id
        )
        facts = func.jsonb_build_object(
            "record_kind",
            "manufacturing_draft",
            "status",
            doc.status,
            "document",
            document_facts(doc),
            "record_policy",
            "仅为原生制造草稿；最新草稿不等于正式发布或当前执行许可。",
        )
        result.append(
            native(
                "manufacturing_document",
                doc,
                (pointer, current),
                pointer.version_id == doc.id,
                doc.series_id,
                doc.title,
                facts,
                doc.required_source_read_set,
                condition=doc.kind.in_(("work_instruction", "control_plan")),
            )
        )

        link, publication, active = map(
            readable,
            (
                ManufacturingPublicationDocument,
                ManufacturingBaselinePublication,
                ManufacturingBaselinePublicationCurrent,
            ),
        )
        fixed_doc = and_(
            scope(link, doc),
            link.document_id == doc.id,
            link.document_kind == doc.kind,
            link.document_revision == doc.revision,
            link.process_id == doc.process_id,
            link.process_revision == doc.process_revision,
            link.operation_key == doc.operation_key,
        )
        fixed_publication = and_(
            scope(link, publication),
            link.publication_id == publication.id,
            link.publication_revision == publication.revision,
        )
        active_publication = and_(
            scope(active, publication), active.series_id == publication.series_id
        )
        facts = func.jsonb_build_object(
            "record_kind",
            "published_manufacturing_document",
            "status",
            publication.status,
            "publication_id",
            publication.id,
            "publication_revision",
            publication.revision,
            "document",
            document_facts(doc),
            "record_policy",
            "该正式发布固定引用此文档版本；不替代原生适用性或继续执行核验。",
        )
        reads = (
            select(doc.required_source_read_set.op("||")(publication.required_source_read_set))
            .select_from(doc)
            .join(publication, fixed_publication)
            .where(fixed_doc)
            .correlate(link)
            .scalar_subquery()
        )
        result.append(
            native(
                "manufacturing_document",
                link,
                (active, active_publication),
                active.version_id == publication.id,
                link.id,
                literal("正式制造资料 · ") + doc.title,
                facts,
                reads,
                joins=((doc, fixed_doc), (publication, fixed_publication)),
                record_owner=publication.owner_id,
                record_visibility=publication.visibility,
                record_revision=link.publication_revision,
                extra_private=doc.visibility != "category",
            )
        )
    if "verification_handoff" in selected:
        fact, request, pointer = map(
            readable,
            (
                VerificationHandoffFact,
                FormalVerificationRequest,
                FormalVerificationCurrent,
            ),
        )
        fixed_request = and_(
            scope(fact, request),
            fact.request_id == request.request_id,
            fact.next_request_version_id == request.id,
            fact.next_request_revision == request.revision,
        )
        active_request = and_(
            pointer.tenant_id == fact.tenant_id,
            pointer.category_id == fact.category_id,
            pointer.product_id == fact.product_id,
            pointer.request_id == fact.request_id,
        )
        facts = func.jsonb_build_object(
            "record_kind",
            "physical_verification_handoff",
            "operation",
            fact.operation,
            "status_as_recorded",
            fact.status,
            "request_id",
            fact.request_id,
            "request_version_id",
            fact.request_version_id,
            "request_revision",
            fact.request_revision,
            "next_request_version_id",
            fact.next_request_version_id,
            "next_request_revision",
            fact.next_request_revision,
            "build_id",
            request.build_id,
            "reason",
            fact.reason,
            "continuation_permission",
            "not_evaluated",
        )
        result.append(
            native(
                "verification_handoff",
                fact,
                (pointer, active_request),
                pointer.request_version_id == fact.next_request_version_id,
                fact.request_id,
                literal("实物验证交接 · ") + cast(fact.request_id, Text),
                facts,
                fact.required_source_read_set,
                joins=((request, fixed_request),),
                extra_private=request.visibility != "category",
            )
        )
    return result
