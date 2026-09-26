"""Original product opportunity versions and independently authorized case review queues."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import Field
from sqlalchemy import Engine, func, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, Role
from app.contracts.common_objects import Contract, Digest
from app.db.schema import tables
from app.domain.case_reviews import review_sources_current, visible_review
from app.domain.my_work import _page_summary
from app.domain.opportunities import _dto
from app.domain.product_evidence import evidence_quality
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _line_filter,
    _plain,
    _role,
    digest,
)
from app.domain.review_materials import authorize_materials


class OpportunityPipeline(Contract):
    search: str = Field(default="", max_length=200)
    market_space_id: UUID | None = None
    state: Literal["exploring", "evaluating", "selected", "deferred", "closed"] | None = None
    mine: bool = False
    include_archived: bool = False
    order: Literal["oldest", "score", "updated"] = "oldest"
    offset: int = Field(default=0, ge=0)
    revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class ReviewQueue(Contract):
    search: str = Field(default="", max_length=200)
    review_kind: Literal["dcp", "technical_review"] | None = None
    stage_code: str | None = Field(default=None, max_length=128)
    mine: bool = False
    include_drafts: bool = False
    focus: Literal["all", "signoff", "decision", "reprepare", "superseded", "draft"] = "all"
    offset: int = Field(default=0, ge=0)
    revision: Digest | None = None


def opportunity_query(context: AuthContext, command: OpportunityPipeline) -> Any:
    o, s, n, u = tables.opportunities, tables.market_spaces, tables.product_nodes, tables.users
    newer = o.alias("newer_pipeline_opportunity")
    q = (
        select(
            o,
            s.c.title.label("space_name"),
            s.c.lifecycle.label("space_lifecycle"),
            n.c.name.label("line_name"),
            u.c.display_name.label("owner_name"),
        )
        .select_from(
            o.join(s, (s.c.tenant_id == o.c.tenant_id) & (s.c.id == o.c.market_space_id))
            .outerjoin(n, (n.c.tenant_id == o.c.tenant_id) & (n.c.id == o.c.product_line_id))
            .outerjoin(u, (u.c.tenant_id == o.c.tenant_id) & (u.c.id == o.c.owner_user_id))
        )
        .where(
            o.c.tenant_id == context.tenant.id,
            _line_filter(o, context),
            ~select(newer.c.id)
            .where(
                newer.c.tenant_id == o.c.tenant_id,
                newer.c.series_id == o.c.series_id,
                newer.c.version > o.c.version,
            )
            .exists(),
        )
    )
    if context.user.role not in (Role.OWNER, Role.ADMIN):
        m = tables.market_space_members
        q = q.where(
            o.c.market_space_id.in_(
                select(m.c.market_space_id).where(
                    m.c.tenant_id == context.tenant.id, m.c.user_id == context.user.id
                )
            )
        )
    if not command.include_archived:
        q = q.where(s.c.lifecycle != "archived")
    if command.market_space_id:
        q = q.where(o.c.market_space_id == command.market_space_id)
    if command.search:
        q = q.where(
            o.c.title.icontains(command.search, autoescape=True)
            | s.c.title.icontains(command.search, autoescape=True)
        )
    if command.mine:
        q = q.where(o.c.owner_user_id == context.user.id)
    return q


def review_query(context: AuthContext, command: ReviewQueue) -> Any:
    r, p, c, e = (
        tables.case_reviews,
        tables.case_review_policies,
        tables.development_cases,
        tables.events,
    )
    newer_policy, newer_round = p.alias("pipeline_newer_policy"), r.alias("pipeline_newer_round")
    submitted = (
        select(func.max(e.c.timestamp))
        .where(
            e.c.tenant_id == r.c.tenant_id,
            e.c.entity_id == r.c.id,
            e.c.event_type == "REVIEW_RECORD_CHANGED",
            e.c.payload["action"].as_string() == "submit",
        )
        .correlate(r)
        .scalar_subquery()
    )
    q = (
        select(
            r,
            c.c.code.label("case_code"),
            c.c.title.label("case_title"),
            p.c.version.label("policy_version"),
            p.c.chair_user_id,
            p.c.reviewer_ids,
            p.c.four_eyes,
            submitted.label("submitted_at"),
            (
                ~select(newer_policy.c.id)
                .where(
                    newer_policy.c.tenant_id == p.c.tenant_id,
                    newer_policy.c.case_id == p.c.case_id,
                    newer_policy.c.review_kind == p.c.review_kind,
                    newer_policy.c.stage_code == p.c.stage_code,
                    newer_policy.c.version > p.c.version,
                )
                .exists()
            ).label("policy_current"),
            (
                ~select(newer_round.c.id)
                .where(
                    newer_round.c.tenant_id == r.c.tenant_id,
                    newer_round.c.case_id == r.c.case_id,
                    newer_round.c.review_kind == r.c.review_kind,
                    newer_round.c.stage_code == r.c.stage_code,
                    newer_round.c.round_no > r.c.round_no,
                )
                .exists()
            ).label("round_current"),
        )
        .select_from(
            r.join(
                p,
                (p.c.tenant_id == r.c.tenant_id)
                & (p.c.case_id == r.c.case_id)
                & (p.c.id == r.c.policy_id),
            ).join(c, (c.c.tenant_id == r.c.tenant_id) & (c.c.id == r.c.case_id))
        )
        .where(
            r.c.tenant_id == context.tenant.id,
            r.c.state.in_(("draft", "in_review") if command.include_drafts else ("in_review",)),
        )
    )
    if command.review_kind:
        q = q.where(r.c.review_kind == command.review_kind)
    if command.stage_code:
        q = q.where(r.c.stage_code == command.stage_code)
    if command.search:
        q = q.where(
            r.c.title.icontains(command.search, autoescape=True)
            | c.c.code.icontains(command.search, autoescape=True)
            | c.c.title.icontains(command.search, autoescape=True)
        )
    return q


class PortfolioProductPipelineService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def opportunities(self, context: AuthContext, command: OpportunityPipeline) -> dict[str, Any]:
        _role(context, Action.PRODUCT_WORK_VIEW)
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            query = opportunity_query(context, command)
            scope = query.subquery("opportunity_pipeline_scope")
            counts = {
                v.state: v.count
                for v in c.execute(
                    select(scope.c.state, func.count().label("count")).group_by(scope.c.state)
                )
            }
            spaces = [
                _plain(v)
                for v in c.execute(
                    select(scope.c.market_space_id.label("id"), scope.c.space_name.label("name"))
                    .distinct()
                    .order_by(scope.c.space_name, scope.c.market_space_id)
                ).mappings()
            ]
            o = tables.opportunities
            if command.state:
                query = query.where(o.c.state == command.state)
            order = (
                (o.c.opportunity_score.desc().nulls_last(), o.c.created_at, o.c.id)
                if command.order == "score"
                else (o.c.created_at.desc(), o.c.id)
                if command.order == "updated"
                else (o.c.created_at, o.c.id)
            )
            count, revision = c.execute(_page_summary(query, order)).one()
            if command.offset and command.revision != revision:
                raise ProductWorkError("机会版本、状态或读取范围已变化，请刷新第一页")
            page = list(
                c.execute(query.order_by(*order).offset(command.offset).limit(21)).mappings()
            )
            segment = tables.market_segments
            segments = {
                v["id"]: v
                for v in c.execute(
                    select(segment).where(
                        segment.c.tenant_id == context.tenant.id,
                        segment.c.id.in_({v["segment_id"] for v in page[:20]}),
                    )
                ).mappings()
            }
            items = []
            for row in page[:20]:
                detail = _dto(row, segments[row["segment_id"]])
                value = {
                    k: detail[k]
                    for k in (
                        "id",
                        "version",
                        "title",
                        "state",
                        "created_at",
                        "owner_user_id",
                        "importance",
                        "satisfaction",
                        "opportunity_score",
                        "scoring_policy_version",
                        "alternatives_missing",
                    )
                }
                value.update(
                    space_name=row["space_name"],
                    space_lifecycle=row["space_lifecycle"],
                    line_name=row["line_name"],
                    owner_name=row["owner_name"],
                    selected_solution_id=detail["selected_solution_id"],
                    solution_count=len(row["solutions"]),
                    revision_reason=row["revision_reason"],
                    source_warnings=evidence_quality(c, context, detail["sources"]),
                    version_age_days=str(
                        Decimal(str((now - row["created_at"]).total_seconds())) / 86400
                    ),
                    href=f"/product-work?space={row['market_space_id']}&tab=opportunities#opportunity-{row['id']}",
                )
                items.append(value)
            return {
                "items": items,
                "counts": counts,
                "spaces": spaces,
                "total": count,
                "revision": revision,
                "next_offset": command.offset + 20 if len(page) > 20 else None,
                "as_of": now.isoformat(),
            }

    def reviews(self, context: AuthContext, command: ReviewQueue) -> dict[str, Any]:
        _role(context, Action.DEVELOPMENT_CASE_VIEW)
        _role(context, Action.REQUIREMENT_VIEW)
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            candidates = list(
                c.execute(
                    review_query(context, command).order_by(tables.case_reviews.c.id)
                ).mappings()
            )
            visible = [r for r in candidates if visible_review(c, context, r["case_id"], r)]
            case_ids = {r["case_id"] for r in visible}
            cases = {
                v["id"]: v
                for v in c.execute(
                    select(tables.development_cases).where(
                        tables.development_cases.c.tenant_id == context.tenant.id,
                        tables.development_cases.c.id.in_(case_ids),
                    )
                ).mappings()
            }
            t = tables.case_review_signoffs
            signoffs: dict[UUID, list[Any]] = {}
            for v in c.execute(
                select(t)
                .where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.review_id.in_({r["id"] for r in visible}),
                )
                .order_by(t.c.created_at, t.c.id)
            ).mappings():
                signoffs.setdefault(v["review_id"], []).append(v)
            person_ids = {
                value
                for row in visible
                for value in (
                    row["created_by_user_id"],
                    row["chair_user_id"],
                    *(UUID(v) for v in row["reviewer_ids"]),
                )
            }
            u = tables.users
            people = {
                v["id"]: _plain(v)
                for v in c.execute(
                    select(u.c.id, u.c.display_name, u.c.is_active, u.c.role).where(
                        u.c.tenant_id == context.tenant.id, u.c.id.in_(person_ids)
                    )
                ).mappings()
            }
            items = []
            for row in visible:
                receipts = signoffs.get(row["id"], [])
                signed = {
                    str(v["reviewer_user_id"])
                    for v in receipts
                    if v["basis_digest"] == row["basis_digest"]
                }
                missing = [v for v in row["reviewer_ids"] if v not in signed]
                current = review_sources_current(c, context.tenant.id, cases[row["case_id"]], row)
                invalid_people = False
                for person in (row["chair_user_id"], *(UUID(v) for v in row["reviewer_ids"])):
                    identity = people.get(person, {})
                    if not identity.get("is_active") or identity.get("role") in (
                        "supplier",
                        "customer",
                    ):
                        invalid_people = True
                        continue
                    try:
                        authorize_materials(
                            c,
                            context.tenant.id,
                            row["case_id"],
                            person,
                            row["basis"].get("materials", []),
                        )
                    except ProductWorkAccessError:
                        invalid_people = True
                conflict = (
                    row["four_eyes"] and str(row["created_by_user_id"]) in row["reviewer_ids"]
                )
                state = (
                    "superseded"
                    if not row["policy_current"] or not row["round_current"]
                    else "reprepare"
                    if not current or invalid_people or conflict
                    else "draft"
                    if row["state"] == "draft"
                    else "signoff"
                    if missing
                    else "decision"
                )
                assigned = (
                    {row["created_by_user_id"], row["chair_user_id"]}
                    if state in ("superseded", "reprepare", "draft")
                    else {UUID(v) for v in missing}
                    if state == "signoff"
                    else {row["chair_user_id"]}
                )
                item = {
                    "id": str(row["id"]),
                    "case_id": str(row["case_id"]),
                    "case_code": row["case_code"],
                    "case_title": row["case_title"],
                    "title": row["title"],
                    "review_kind": row["review_kind"],
                    "stage_code": row["stage_code"],
                    "round_no": row["round_no"],
                    "version": row["version"],
                    "policy_version": row["policy_version"],
                    "policy_current": row["policy_current"],
                    "round_current": row["round_current"],
                    "source_current": current,
                    "invalid_people": invalid_people,
                    "four_eyes_conflict": conflict,
                    "state": row["state"],
                    "queue_state": state,
                    "created_at": row["created_at"],
                    "submitted_at": row["submitted_at"],
                    "preparer": people.get(row["created_by_user_id"]),
                    "chair": people.get(row["chair_user_id"]),
                    "missing_signers": [
                        people.get(
                            UUID(v), {"id": v, "display_name": "原人员不可用", "is_active": False}
                        )
                        for v in missing
                    ],
                    "signoffs": [
                        {
                            "reviewer": people.get(v["reviewer_user_id"]),
                            "outcome": v["outcome"],
                            "created_at": v["created_at"],
                            "basis_current": v["basis_digest"] == row["basis_digest"],
                        }
                        for v in receipts
                    ],
                    "mine": context.user.id in assigned,
                    "href": f"/cases/{row['case_id']}/reviews?review={row['id']}",
                }
                if not command.mine or item["mine"]:
                    items.append(_plain(item))
            counts = {
                state: sum(v["queue_state"] == state for v in items)
                for state in ("signoff", "decision", "reprepare", "superseded", "draft")
            }
            if command.focus != "all":
                items = [v for v in items if v["queue_state"] == command.focus]
            items.sort(
                key=lambda v: (
                    v["submitted_at"] is None,
                    v["submitted_at"] or v["created_at"],
                    v["id"],
                )
            )
            revision = digest(
                {
                    "items": items,
                    "counts": counts,
                    "filters": command.model_dump(mode="json", exclude={"offset", "revision"}),
                }
            )
            if command.offset and command.revision != revision:
                raise ProductWorkError("评审、签核、来源或原权限已有变化，请刷新第一页")
            page = items[command.offset : command.offset + 20]
            for entry in page:
                entry["waiting_days"] = (
                    str(
                        Decimal(
                            str(
                                (
                                    now - datetime.fromisoformat(entry["submitted_at"])
                                ).total_seconds()
                            )
                        )
                        / 86400
                    )
                    if entry["submitted_at"] and entry["state"] == "in_review"
                    else None
                )
            return {
                "items": page,
                "counts": counts,
                "total": len(items),
                "revision": revision,
                "next_offset": command.offset + 20 if command.offset + 20 < len(items) else None,
                "as_of": now.isoformat(),
            }
