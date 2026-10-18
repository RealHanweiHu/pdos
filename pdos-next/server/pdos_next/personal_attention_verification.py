"""Named verification returns under current source RLS, without issuing authority.

Return arrays are append-only. Resolve each pair's latest assignment before
selecting this person, then remove coverage already received or actually returned.
The common reader owns project/person ACL, paging and the final metadata DTO.
"""

from sqlalchemy import String, and_, case, cast, column, exists, func, literal, select, true
from sqlalchemy.dialects.postgresql import JSONB

from pdos_next import models as registered_models  # noqa: F401 -- registry before domain children
from pdos_next.domain.verification_front.models import (
    FormalVerificationCurrent,
    FormalVerificationRequest,
)
from pdos_next.domain.verification_launch.models import (
    VerificationRunCurrent,
    VerificationRunVersion,
)
from pdos_next.personal_attention_common import columns


def _elements(value, name):
    # An absent/non-array field supplies no assignment. Never infer an owner.
    array = case(
        (func.jsonb_typeof(value) == "array", value),
        else_=cast(literal("[]"), JSONB),
    )
    return (
        func.jsonb_array_elements(array)
        .table_valued(column("value", JSONB), with_ordinality="position")
        .render_derived()
        .lateral(name)
    )


def _pair_present(array, sample, item, name, *, nested=None, object_key=None):
    entries = _elements(array, name)
    pairs = _elements(entries.c.value[nested], name + "_coverage") if nested else entries
    query = select(literal(1)).select_from(entries)
    if nested:
        query = query.join(pairs, true())
    pair = entries.c.value[object_key] if object_key else pairs.c.value
    return exists(
        query.where(
            pair["sample_id"].astext == sample,
            pair["item_id"].astext == item,
        ).correlate_except(entries, pairs)
    )


def _heads(model, logical_id, title):
    return (
        model.tenant_id.label("tenant_id"),
        model.category_id.label("category_id"),
        model.product_id.label("product_id"),
        model.project_id.label("project_id"),
        model.build_id.label("build_id"),
        logical_id.label("source_id"),
        model.id.label("version_id"),
        model.revision.label("revision"),
        model.created_at.label("recorded_at"),
        title.label("title"),
        model.status.label("state"),
    )


def _item(ctx, ranked, *, kind, stage, reason):
    heads = (
        "tenant_id",
        "category_id",
        "product_id",
        "project_id",
        "build_id",
        "source_id",
        "version_id",
        "revision",
        "recorded_at",
        "title",
        "state",
    )
    grouped = (
        select(
            *(ranked.c[name] for name in heads),
            func.count().label("coverage_count"),
        )
        .where(
            ranked.c.last_assignment == 1,
            ranked.c.next_owner == str(ctx.requester_id),
        )
        .group_by(*(ranked.c[name] for name in heads))
        .subquery(stage + "_pending")
    )
    return select(
        *columns(
            key=literal(kind + ":") + cast(grouped.c.source_id, String),
            kind=kind,
            queue="receive",
            tenant_id=grouped.c.tenant_id,
            source_id=grouped.c.source_id,
            version_id=grouped.c.version_id,
            revision=grouped.c.revision,
            epoch=None,
            category_id=grouped.c.category_id,
            product_id=grouped.c.product_id,
            project_id=grouped.c.project_id,
            recorded_at=grouped.c.recorded_at,
            title=grouped.c.title,
            reason=reason,
            state=grouped.c.state,
            responsible_id=ctx.requester_id,
            responsibility="named_return_owner",
            target="project",
            blocked_code=None,
            blocked_message=None,
            due_at=None,
            valid_until=None,
            details=func.jsonb_build_object(
                "stage",
                stage,
                "coverage_count",
                grouped.c.coverage_count,
                "build_id",
                cast(grouped.c.build_id, String),
            ),
        )
    ).select_from(grouped)


def _handoff(ctx):
    request, current = FormalVerificationRequest, FormalVerificationCurrent
    returned = _elements(request.request_snapshot["returns"], "named_handoff_return")
    coverage = _elements(returned.c.value["coverage"], "named_handoff_return_pair")
    sample, item = coverage.c.value["sample_id"].astext, coverage.c.value["item_id"].astext
    ranked = (
        select(
            *_heads(request, request.request_id, request.request_snapshot["title"].astext),
            returned.c.value["next_owner_id"].astext.label("next_owner"),
            func.row_number()
            .over(
                partition_by=(request.tenant_id, request.request_id, sample, item),
                order_by=returned.c.position.desc(),
            )
            .label("last_assignment"),
        )
        .select_from(request)
        .join(
            current,
            and_(
                current.tenant_id == request.tenant_id,
                current.category_id == request.category_id,
                current.product_id == request.product_id,
                current.request_id == request.request_id,
                current.request_version_id == request.id,
                current.request_revision == request.revision,
            ),
        )
        .join(returned, true())
        .join(coverage, true())
        .where(
            request.tenant_id == ctx.tenant_id,
            request.status.in_(("offered", "accepted", "scheduled", "executing")),
            _pair_present(
                request.request_snapshot["offered_coverage"], sample, item, "handoff_offered_pair"
            ),
            ~_pair_present(
                request.request_snapshot["acceptances"],
                sample,
                item,
                "handoff_accepted",
                nested="coverage",
            ),
        )
        .subquery("handoff_return_assignments")
    )
    return _item(
        ctx,
        ranked,
        kind="verification_handoff_return",
        stage="handoff_return",
        reason="交样退缺项将你列为下一责任人，仍有未接收范围；请查看原验证记录补缺。",
    )


def _results(ctx):
    run, current = VerificationRunVersion, VerificationRunCurrent
    request, request_current = FormalVerificationRequest, FormalVerificationCurrent
    returned = _elements(run.run_snapshot["partial_returns"], "named_results_return")
    coverage = _elements(returned.c.value["pending_coverage"], "named_results_return_pair")
    sample, item = coverage.c.value["sample_id"].astext, coverage.c.value["item_id"].astext
    ranked = (
        select(
            *_heads(run, run.run_id, request.request_snapshot["title"].astext),
            returned.c.value["next_owner_id"].astext.label("next_owner"),
            func.row_number()
            .over(
                partition_by=(run.tenant_id, run.run_id, sample, item),
                order_by=returned.c.position.desc(),
            )
            .label("last_assignment"),
        )
        .select_from(run)
        .join(
            current,
            and_(
                current.tenant_id == run.tenant_id,
                current.category_id == run.category_id,
                current.product_id == run.product_id,
                current.request_id == run.request_id,
                current.run_id == run.run_id,
                current.run_version_id == run.id,
                current.run_revision == run.revision,
            ),
        )
        .join(
            request_current,
            and_(
                request_current.tenant_id == run.tenant_id,
                request_current.category_id == run.category_id,
                request_current.product_id == run.product_id,
                request_current.request_id == run.request_id,
            ),
        )
        .join(
            request,
            and_(
                request.tenant_id == request_current.tenant_id,
                request.category_id == request_current.category_id,
                request.product_id == request_current.product_id,
                request.request_id == request_current.request_id,
                request.id == request_current.request_version_id,
                request.revision == request_current.request_revision,
                request.project_id == run.project_id,
                request.build_id == run.build_id,
            ),
        )
        .join(returned, true())
        .join(coverage, true())
        .where(
            run.tenant_id == ctx.tenant_id,
            run.status == "running",
            request.status != "disposed",
            _pair_present(run.run_snapshot["coverage"], sample, item, "results_requested_pair"),
            ~_pair_present(
                run.run_snapshot["measurements"],
                sample,
                item,
                "results_measurement",
                object_key="coverage",
            ),
        )
        .subquery("results_return_assignments")
    )
    return _item(
        ctx,
        ranked,
        kind="verification_result_return",
        stage="results_return",
        reason="部分结果将你列为下一责任人，仍有未返回测量的范围；请查看原测试记录补缺。",
    )


def queries(ctx, queue=None):
    """Two read-only SELECTs; the common reader applies final current caller ACL."""
    return (_handoff(ctx), _results(ctx)) if queue is None or queue == "receive" else ()
