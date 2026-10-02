"""Explicit project topic evidence, with original object permissions and versions."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, select, true

from app.ai.change_professional_sources import SEATS as ENGINEERING_SEATS
from app.auth.repository import AuthContext, AuthRepository
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.case_requirements import _relations
from app.domain.product_definitions import _row as definition_row
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _plain,
    _role,
    digest,
)

SEATS = {"product_manager": "产品经理 / 定义与商业依据", **ENGINEERING_SEATS}
TABLES = {
    "task": tables.tasks,
    "issue": tables.issues,
    "risk": tables.risks,
    "decision": tables.decisions,
    "specification": tables.specifications,
}
FIELDS = {
    "id",
    "code",
    "title",
    "description",
    "status",
    "priority",
    "due_date",
    "severity",
    "target_date",
    "likelihood",
    "impact",
    "mitigation_plan",
    "rationale",
    "outcome",
    "decision_kind",
    "context",
    "options",
    "trade_offs",
    "consequence",
    "evidence_refs",
    "root_cause",
    "resolution",
    "closure_criteria",
    "closure_evidence_ref",
    "contingency_plan",
    "expected_output",
    "completion_evidence_ref",
    "verification_method",
    "acceptance_criteria",
    "criticality",
    "decided_at",
    "historical_source",
    "version",
    "content",
    "updated_at",
    "created_at",
}


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: Literal[
        "task",
        "issue",
        "risk",
        "decision",
        "specification",
        "product_definition",
        "cost_gap_observation",
        "cost_alternative",
        "cost_backtest",
    ]
    id: UUID
    seats: list[str] = Field(min_length=1, max_length=9)

    @model_validator(mode="after")
    def valid_seats(self) -> Selection:
        if len(set(self.seats)) != len(self.seats) or any(v not in SEATS for v in self.seats):
            raise ValueError("请选择有效且不重复的专业席位")
        return self


class Preparation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selections: list[Selection] = Field(min_length=2, max_length=30)

    @model_validator(mode="after")
    def distinct(self) -> Preparation:
        if len({(v.kind, v.id) for v in self.selections}) != len(self.selections):
            raise ValueError("同一资料请合并分配给相关席位")
        return self


def actor(c: Connection, tenant: UUID, actor_id: UUID) -> AuthContext:
    context = AuthRepository(c.engine).find_user_context(actor_id)
    if (
        context is None
        or context.tenant.id != tenant
        or not context.user.is_active
        or context.tenant.status != "active"
    ):
        raise ProductWorkAccessError("原发起人已不可用")
    return context


def linked_definitions(
    c: Connection, context: AuthContext, project: UUID, wanted: list[UUID] | None = None
) -> list[Any]:
    p, cases = tables.projects, tables.development_cases
    case = (
        c.execute(
            select(cases)
            .join(p, (p.c.tenant_id == cases.c.tenant_id) & (p.c.development_case_id == cases.c.id))
            .where(p.c.tenant_id == context.tenant.id, p.c.id == project)
        )
        .mappings()
        .one_or_none()
    )
    if case is None:
        return []
    ids = [UUID(v["requirement_id"]) for v in _relations(c, context, case)]
    d, link = tables.product_definitions, tables.definition_requirement_links
    candidates = (
        c.execute(
            select(d)
            .where(
                d.c.tenant_id == context.tenant.id,
                d.c.state == "published",
                (d.c.id.in_(wanted) if wanted is not None else true()),
                d.c.id.in_(
                    select(link.c.definition_id).where(
                        link.c.tenant_id == context.tenant.id, link.c.requirement_id.in_(ids)
                    )
                ),
            )
            .order_by(d.c.published_at.desc(), d.c.id)
            .limit(101)
        )
        .mappings()
        .all()
    )
    result = []
    for value in candidates:
        try:
            _role(context, Action.PRODUCT_WORK_VIEW)
            value = definition_row(c, context, value["market_space_id"], value["id"])
        except ProductWorkAccessError:
            continue
        result.append(value)
    return result


def options(c: Connection, context: AuthContext, project: UUID) -> dict[str, Any]:
    choices = []
    for kind, table in TABLES.items():
        records = c.execute(
            select(table)
            .where(table.c.tenant_id == context.tenant.id, table.c.project_id == project)
            .where(*([table.c.withdrawn_at.is_(None)] if kind == "issue" else []))
            .order_by(table.c.created_at.desc(), table.c.id)
            .limit(100)
        ).mappings()
        for row in records:
            choices.append(
                {
                    "kind": kind,
                    "id": str(row["id"]),
                    "title": row.get("title")
                    or row.get("rationale")
                    or row.get("code")
                    or "已记录裁决",
                    "status": row.get("status") or row.get("outcome"),
                }
            )
    for row in linked_definitions(c, context, project)[:100]:
        choices.append(
            {
                "kind": "product_definition",
                "id": str(row["id"]),
                "title": row["title"],
                "status": row["state"],
            }
        )
    from app.ai.cost_discussion_sources import options as cost_options

    choices.extend(cost_options(c, context, project))
    return {
        "items": choices,
        "seats": [{"key": k, "label": v} for k, v in SEATS.items()],
        "limit_per_kind": 100,
        "notice": "每类最多列最近100项。产品定义须已发布、由本项目实际需求继承且当前可读；"
        "草稿和无关联资料不纳入。成本观察、方案和回测保留原版本及用途，来源变化会提示重核。",
    }


def state(
    c: Connection, tenant: UUID, project: UUID, actor_id: UUID, selections: list[dict[str, Any]]
) -> dict[str, Any]:
    context = actor(c, tenant, actor_id)
    chosen = Preparation.model_validate({"selections": selections}).selections
    definitions = (
        {
            r["id"]: r
            for r in linked_definitions(
                c, context, project, [v.id for v in chosen if v.kind == "product_definition"]
            )
        }
        if any(v.kind == "product_definition" for v in chosen)
        else {}
    )
    refs, missing = [], []
    projections: dict[str, dict[str, Any]] = {
        key: {
            "key": key,
            "label": label,
            "reference_ids": [],
            "shared_reference_ids": [],
            "missing": [],
        }
        for key, label in SEATS.items()
    }
    for value in chosen:
        key = f"{value.kind}:{value.id}"
        from app.ai.cost_discussion_sources import KINDS as COST_KINDS
        from app.ai.cost_discussion_sources import projection as cost_projection
        from app.ai.cost_discussion_sources import references as cost_references

        if value.kind in COST_KINDS:
            title, fields, omitted = cost_projection(c, context, project, value.kind, value.id)
            cost_refs = cost_references(title, value.kind, value.id, fields, omitted)
            refs.extend(cost_refs)
            missing.extend(omitted)
            for seat_key in value.seats:
                projections[seat_key]["reference_ids"].extend(r["reference_id"] for r in cost_refs)
            continue
        if value.kind == "product_definition":
            definition = definitions.get(value.id)
            if definition is None:
                raise ProductWorkError("所选产品定义已不可读、未发布或不再属于本项目需求来源")
            release = (
                c.execute(
                    select(tables.definition_releases)
                    .where(
                        tables.definition_releases.c.tenant_id == tenant,
                        tables.definition_releases.c.product_id == definition["product_id"],
                    )
                    .order_by(tables.definition_releases.c.sequence.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            fields = {
                k: definition[k]
                for k in (
                    "id",
                    "title",
                    "version",
                    "revision_number",
                    "state",
                    "published_at",
                    "content",
                    "strategy_ref",
                )
            }
            # Only business definition fields; review assignments are not model evidence.
            fields["content"] = {
                k: v
                for k, v in definition["content"].items()
                if k not in {"owner_user_id", "reviewers"}
            }
            fields["current_publication"] = (
                {k: release[k] for k in ("id", "sequence", "action", "definition_id")}
                if release
                else None
            )
            if (
                not release
                or release["action"] != "publish"
                or release["definition_id"] != value.id
            ):
                missing.append("所选定义为历史发布依据，当前发布链已变化，不能当作当前完整要求")
            strategy = (
                c.execute(
                    select(tables.product_strategies).where(
                        tables.product_strategies.c.tenant_id == tenant,
                        tables.product_strategies.c.id == definition["strategy_id"],
                        tables.product_strategies.c.market_space_id
                        == definition["market_space_id"],
                    )
                )
                .mappings()
                .one_or_none()
            )
            ref = definition["strategy_ref"]
            if (
                strategy
                and strategy["state"] == "published"
                and strategy["version"] == ref["version"]
                and (strategy["approval"] or {}).get("payload_digest") == ref["digest"]
            ):
                fields["adopted_business_canvas"] = {
                    k: strategy[k]
                    for k in (
                        "id",
                        "title",
                        "version",
                        "canvas",
                        "route_comparisons",
                        "professional_constraints",
                    )
                }
            else:
                fields["adopted_business_canvas"] = None
                missing.append("定义所固定的商业策略版本已不可核对，未用当前草稿替代原商业依据")
            title = definition["title"]
        else:
            table = TABLES[value.kind]
            row = (
                c.execute(
                    select(table).where(
                        table.c.tenant_id == tenant,
                        table.c.project_id == project,
                        table.c.id == value.id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None or (value.kind == "issue" and row.get("withdrawn_at") is not None):
                raise ProductWorkError("所选资料不存在、已撤回或不属于当前项目")
            fields = {
                k: v
                for k, v in row.items()
                if k in FIELDS and (k != "historical_source" or v is not None)
            }
            if value.kind == "decision" and row.get("historical_source"):
                from app.domain.decision_intake_state import source_states

                origin = UUID(row["historical_source"]["source_row_id"])
                state = source_states(c, tenant, [{"id": origin}]).get(origin)
                fields["historical_origin_state"] = (
                    {k: v for k, v in state.items() if k != "association_snapshot"}
                    if state
                    else {"state": "unavailable"}
                )
                fields["historical_origin_state"]["on_this_decision"] = bool(
                    state and state["current_decision_id"] == str(value.id)
                )
            title = str(row.get("title") or row.get("code") or "已记录裁决")
        fields = _plain(fields)
        if len(json_encoded(fields)) > 20000:
            raise ProductWorkError(f"资料「{title}」超过本次单项容量，请先缩小所选业务资料")
        refs.append(
            {
                "reference_id": key,
                "category": "project_topic_evidence",
                "label": title,
                "fields": fields,
                "digest": digest(fields),
                "omitted_fields": [],
            }
        )
        for seat_key in value.seats:
            projections[seat_key]["reference_ids"].append(key)
    selected = [v for v in projections.values() if v["reference_ids"]]
    for seat in selected:
        seat["missing"] = list(dict.fromkeys(missing))
        seat["status"] = "partial" if missing else "available"
    if len(selected) < 2 or len({frozenset(v["reference_ids"]) for v in selected}) < 2:
        raise ProductWorkError("请给至少两个席位分配不同的实际依据；相同资料适合先做单次分析")
    body = {
        "source_kind": "project_discussion",
        "ecr_id": None,
        "topic_id": str(project),
        "actor_id": str(actor_id),
        "selections": [v.model_dump(mode="json") for v in chosen],
        "model_context": {
            "references": refs,
            "professional_projections": selected,
            "coverage": {
                "depth": 1,
                "gaps": [{"message": v} for v in sorted(set(missing))],
                "scope_gaps": ["仅覆盖明确选定资料，未据此证明业务影响范围完整"],
            },
        },
        "omissions": [],
    }
    if len(json_encoded(body)) > 140000:
        raise ProductWorkError("本次资料超过讨论容量，请减少选定资料")
    return {**body, "digest": digest(body)}


def json_encoded(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
