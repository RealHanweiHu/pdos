"""Freeze an actual research deliverable; never expand nested references implicitly."""

import json
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, select

from app.auth.repository import AuthContext
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError, _plain, digest
from app.domain.research_measurement_sources import authorize_scope, source, subject_table

COMMON = (
    "id",
    "market_space_id",
    "product_line_id",
    "owner_user_id",
    "series_id",
    "supersedes_id",
    "version",
    "revision_number",
    "title",
    "state",
    "created_at",
    "updated_at",
)
CONTENT_FIELDS = {
    "research_task": (
        "question",
        "user_groups",
        "regions",
        "time_scope",
        "method",
        "expected_decision",
        "stop_conditions",
        "findings",
        "unresolved",
        "sources",
        "conclusion",
        "completed_at",
        "cancellation_reason",
    ),
    "scoped_work_item": (
        "receiver_user_id",
        "action_type",
        "expected_output",
        "completion_criteria",
        "acceptance_required",
        "due_at",
        "evidence",
        "result_note",
        "accepted_by_user_id",
        "accepted_at",
        "cancellation_reason",
    ),
    "opportunity": (
        "segment_id",
        "desired_outcome_id",
        "parent_opportunity_id",
        "importance",
        "satisfaction",
        "importance_basis",
        "satisfaction_basis",
        "scoring_policy_version",
        "opportunity_score",
        "solutions",
        "selected_solution_id",
        "revision_reason",
    ),
    "strategy": (
        "opportunity_id",
        "canvas",
        "route_comparisons",
        "cost_summary",
        "selected_solution_id",
        "professional_constraints",
        "unknowns",
        "decision_reason",
        "approval",
        "published_snapshot",
    ),
    "definition": (
        "product_id",
        "strategy_id",
        "strategy_ref",
        "content",
        "review_round",
        "review_digest",
        "approval",
        "published_at",
    ),
}


def delivery_source(
    c: Connection,
    context: AuthContext,
    space: UUID,
    line: UUID | None,
    kind: str,
    identity: UUID,
) -> dict[str, Any]:
    basis = source(c, context, space, line, kind, identity)
    t = subject_table(kind)
    row = (
        c.execute(
            select(t).where(
                t.c.tenant_id == context.tenant.id,
                t.c.market_space_id == space,
                t.c.product_line_id.is_not_distinct_from(line),
                t.c.id == identity,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkAccessError("原交付对象不在当前可读范围")
    record = _plain({k: row[k] for k in (*COMMON, *CONTENT_FIELDS[kind]) if k in row})
    record["kind"] = kind
    if len(json.dumps(record, ensure_ascii=False).encode("utf-8")) > 1_048_576:
        raise ProductWorkError("交付正文超过当前1 MiB容量上限，未截断或登记部分内容")
    return {
        **basis,
        "record": record,
        "record_digest": digest(record),
        "scope_note": "固定该对象版本的业务正文；内嵌引用仅保留原记录，完整引用材料沿原权限读取。",
    }


def delivery_options(
    c: Connection,
    context: AuthContext,
    space: UUID,
    line: UUID | None,
    kind: str,
    series_id: UUID,
    before_id: UUID | None = None,
) -> dict[str, Any]:
    authorize_scope(c, context, space, line)
    t = subject_table(kind)
    conditions = [
        t.c.tenant_id == context.tenant.id,
        t.c.market_space_id == space,
        t.c.product_line_id.is_not_distinct_from(line),
        (t.c.series_id if "series_id" in t.c else t.c.id) == series_id,
    ]
    if before_id:
        conditions.append(t.c.id < before_id)
    found = (
        c.execute(select(t).where(*conditions).order_by(t.c.id.desc()).limit(31)).mappings().all()
    )
    return {
        "items": [
            {
                **_plain({k: r[k] for k in COMMON if k in r}),
                "kind": kind,
                "title": r.get("title") or r.get("question"),
                "series_id": str(r.get("series_id") or r["id"]),
            }
            for r in found[:30]
        ],
        "next_before_id": str(found[29]["id"]) if len(found) > 30 else None,
    }
