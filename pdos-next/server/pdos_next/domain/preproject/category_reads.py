"""Scope-bound material reads with stable keyset pagination."""

from uuid import UUID

from sqlalchemy import any_, column, func, literal, select, tuple_
from sqlalchemy.dialects.postgresql import JSONB

from pdos_next.clock import now

from .access import fail, proposal
from .category_models import (
    KnowledgeCurrent,
    KnowledgeEntry,
    ParameterCurrent,
    ParameterVersion,
    PromotionProof,
)


def _scope(s, ctx, page_size):
    from pdos_next.category_scope import category_scope

    category_scope(s, ctx)
    if not 1 <= page_size <= 200:
        fail("VALIDATION_FAILED", "page_size_invalid", "分页大小须在 1 到 200 之间。")


def _row(row):
    result = {}
    for field in row.__table__.columns:
        value = getattr(row, field.name)
        if isinstance(value, UUID):
            value = str(value)
        elif hasattr(value, "isoformat"):
            value = value.isoformat()
        result[field.name] = value
    return result


def parameters(s, ctx, *, parameter_ids=None, include_history=False, cursor=None, page_size=50):
    _scope(s, ctx, page_size)
    query = select(ParameterVersion).where(
        ParameterVersion.tenant_id == ctx.tenant_id, ParameterVersion.category_id == ctx.category_id
    )
    if not include_history:
        query = query.join(
            ParameterCurrent,
            (
                (ParameterCurrent.tenant_id == ParameterVersion.tenant_id)
                & (ParameterCurrent.category_id == ParameterVersion.category_id)
                & (ParameterCurrent.parameter_id == ParameterVersion.parameter_id)
                & (ParameterCurrent.current_version == ParameterVersion.version)
            ),
        )
    if parameter_ids is not None:
        query = query.where(ParameterVersion.parameter_id.in_(parameter_ids))
    if cursor:
        try:
            identity, version = cursor.split(":")
            identity, version = UUID(identity), int(version)
            if version < 1:
                raise ValueError
        except (ValueError, TypeError):
            fail("VALIDATION_FAILED", "cursor_invalid", "分页游标无效。")
        query = query.where(
            tuple_(ParameterVersion.parameter_id, ParameterVersion.version)
            > tuple_(identity, version)
        )
    rows = s.scalars(
        query.order_by(ParameterVersion.parameter_id, ParameterVersion.version).limit(page_size + 1)
    ).all()
    page = rows[:page_size]
    return {
        "items": [_row(row) for row in page],
        "next_cursor": f"{page[-1].parameter_id}:{page[-1].version}"
        if len(rows) > page_size
        else None,
        "as_of": now().isoformat(),
    }


def knowledge(
    s,
    ctx,
    *,
    kind=None,
    status="active",
    origin=None,
    region=None,
    include_history=False,
    cursor=None,
    page_size=50,
    _filters=(),
):
    _scope(s, ctx, page_size)
    if status not in {None, "active", "withdrawn"}:
        fail("VALIDATION_FAILED", "knowledge_status_invalid", "资料状态无效。")
    if origin not in {None, "human", "ai_draft", "imported"}:
        fail("VALIDATION_FAILED", "knowledge_origin_invalid", "来源类型无效。")
    join = (
        (KnowledgeCurrent.tenant_id == KnowledgeEntry.tenant_id)
        & (KnowledgeCurrent.category_id == KnowledgeEntry.category_id)
        & (KnowledgeCurrent.lineage_id == KnowledgeEntry.lineage_id)
    )
    if not include_history:
        join &= KnowledgeCurrent.current_entry_id == KnowledgeEntry.id
    query = (
        select(KnowledgeEntry, KnowledgeCurrent.status)
        .join(KnowledgeCurrent, join)
        .where(
            KnowledgeEntry.tenant_id == ctx.tenant_id, KnowledgeEntry.category_id == ctx.category_id
        )
    )
    query = query.where(*_filters)
    if kind:
        query = query.where(KnowledgeEntry.kind == kind)
    if status is not None:
        query = query.where(KnowledgeCurrent.status == status)
    if origin:
        query = query.where(KnowledgeEntry.origin == origin)
    if region:
        query = query.where(region == any_(KnowledgeEntry.regions))
    if cursor:
        try:
            identity, version = cursor.split(":")
            identity, version = UUID(identity), int(version)
            if version < 1:
                raise ValueError
        except (ValueError, TypeError):
            fail("VALIDATION_FAILED", "cursor_invalid", "分页游标无效。")
        query = query.where(
            tuple_(KnowledgeEntry.lineage_id, KnowledgeEntry.version) > tuple_(identity, version)
        )
    rows = s.execute(
        query.order_by(KnowledgeEntry.lineage_id, KnowledgeEntry.version).limit(page_size + 1)
    ).all()
    page = rows[:page_size]
    from .root_sources import project_knowledge

    return {
        "items": project_knowledge(
            s,
            ctx,
            [
                {
                    **_row(row),
                    "status": "withdrawn" if row.action == "withdraw" else "active",
                    "lineage_status": current_status,
                }
                for row, current_status in page
            ],
        ),
        "next_cursor": f"{page[-1][0].lineage_id}:{page[-1][0].version}"
        if len(rows) > page_size
        else None,
        "as_of": now().isoformat(),
    }


def promotion_proof(s, ctx, proof_id):
    _scope(s, ctx, 1)
    row = s.scalar(
        select(PromotionProof).where(
            PromotionProof.tenant_id == ctx.tenant_id,
            PromotionProof.category_id == ctx.category_id,
            PromotionProof.id == proof_id,
        )
    )
    if not row:
        fail("NOT_FOUND", "promotion_proof_not_found", "证明不存在或不可读。", 404)
    proposal(s, ctx, row.source_proposal_id)
    return _row(row)


def competitors(s, ctx, *, parameter_ids=None, brand=None, nature=None, cursor=None, page_size=50):
    """Filter current shared observations before pagination, then group exact contexts.

    `brand` is an exact match. Both parameter/nature predicates apply to the same
    metric or feature, rather than unrelated observations on the same competitor.
    Prices retain their original currency, date, tax, shipping and channel fields.
    """
    if nature not in {None, "measured", "claimed", "inferred", "unknown"}:
        fail("VALIDATION_FAILED", "competitor_nature_invalid", "竞品数据性质无效。")
    selected = None if parameter_ids is None else {str(identity) for identity in parameter_ids}
    predicates = []
    if brand is not None:
        predicates.append(KnowledgeEntry.content["brand"].astext == brand)
    if selected is not None or nature is not None:
        arrays = func.coalesce(KnowledgeEntry.content["metrics"], literal([], type_=JSONB)).op(
            "||"
        )(func.coalesce(KnowledgeEntry.content["features"], literal([], type_=JSONB)))
        metric = (
            func.jsonb_array_elements(arrays)
            .table_valued(column("value", JSONB))
            .alias("observation")
        )
        checks = []
        if selected is not None:
            checks.append(metric.c.value["parameter_id"].astext.in_(sorted(selected)))
        if nature is not None:
            checks.append(metric.c.value["nature"].astext == nature)
        predicates.append(
            select(1).select_from(metric).where(*checks).correlate(KnowledgeEntry).exists()
        )
    page = knowledge(
        s,
        ctx,
        kind="competitor",
        status="active",
        include_history=False,
        cursor=cursor,
        page_size=page_size,
        _filters=predicates,
    )
    for entry in page["items"]:
        content = dict(entry["content"])
        groups = {}
        for field in ("metrics", "features"):
            observations = [
                item
                for item in content.get(field, [])
                if (selected is None or str(item.get("parameter_id")) in selected)
                and (nature is None or item.get("nature") == nature)
            ]
            content[field] = observations
            for item in observations:
                key = (
                    item.get("parameter_id"),
                    item.get("parameter_version"),
                    item.get("unit"),
                    item.get("condition_note"),
                )
                group = groups.setdefault(
                    key,
                    {
                        "parameter_id": key[0],
                        "parameter_version": key[1],
                        "unit": key[2],
                        "condition_note": key[3],
                        "metrics": [],
                        "features": [],
                    },
                )
                group[field].append(item)
        entry["content"] = content
        entry["comparison_groups"] = list(groups.values())
    return page
