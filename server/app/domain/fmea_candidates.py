"""Deterministic, immutable FMEA revision inputs and explicit human disposition.

No model-generated content, inference of causality, scoring or publication lives here.
The same packet builder is used by business events, catch-up and stale-input checks.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, RowMapping, exists, func, select
from sqlalchemy.dialects.postgresql import insert

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.db.schema import tables
from app.domain import living_fmea as fmea
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

TRIGGERS = frozenset(
    {
        "ISSUE_CREATED",
        "ISSUE_UPDATED",
        "ISSUE_STATUS_CHANGED",
        "QUALITY_ISSUE_LINK_RECORDED",
        "NCR_STATUS_CHANGED",
        "ROOT_CAUSE_ANALYSIS_CHANGED",
        "CAPA_ACTION_CREATED",
        "CAPA_ACTION_STATUS_CHANGED",
        "EFFECTIVENESS_REVIEWED",
        "NCR_PREVENTIVE_DISPOSITION_APPROVED",
        "FMEA_VERSION_PUBLISHED",
    }
)


class Excluded(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: Literal["ncr", "capa_action"]
    id: UUID
    reason: str = Field(min_length=1, max_length=4000)


class Disposition(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    action: Literal["draft_created", "not_applicable"]
    reason: str = Field(min_length=1, max_length=4000)
    entry_id: UUID | None = None
    expected_version_id: UUID | None = None
    content: fmea.Content | None = None
    excluded_sources: list[Excluded] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def coherent(self) -> Disposition:
        if self.action == "draft_created" and self.content is None:
            raise ValueError("转入修订须填写实际失效模式内容")
        if self.action == "not_applicable" and (
            self.content is not None
            or self.entry_id is not None
            or self.expected_version_id is not None
            or self.excluded_sources
        ):
            raise ValueError("不适用处置只登记专业理由")
        if len({(r.kind, r.id) for r in self.excluded_sources}) != len(self.excluded_sources):
            raise ValueError("同一原记录只填写一次不适用理由")
        return self


def packet(c: Connection, tenant: UUID, project: UUID, issue_id: UUID) -> dict[str, Any]:
    """All explicit related facts, current publication bindings and actual source validity."""
    issue = fmea.read_source(c, tenant, project, "issue", issue_id)
    sources: list[dict[str, Any]] = [
        {
            "kind": "issue",
            "id": str(issue_id),
            "expected_digest": digest(issue),
            "value": issue,
        }
    ]
    link, retract = tables.quality_issue_links, tables.quality_issue_link_retractions
    links = (
        c.execute(
            select(link)
            .where(
                link.c.tenant_id == tenant,
                link.c.project_id == project,
                link.c.issue_id == issue_id,
                ~exists().where(retract.c.link_id == link.c.id),
            )
            .order_by(link.c.id)
        )
        .mappings()
        .all()
    )
    for relation in links:
        ncr_id = relation["ncr_id"]
        ncr = fmea.read_source(c, tenant, project, "ncr", ncr_id)
        sources.append(
            {"kind": "ncr", "id": str(ncr_id), "expected_digest": digest(ncr), "value": ncr}
        )
        action = tables.capa_actions
        ids = c.execute(
            select(action.c.id)
            .where(
                action.c.tenant_id == tenant,
                action.c.project_id == project,
                action.c.ncr_id == ncr_id,
            )
            .order_by(action.c.id)
        ).scalars()
        for id in ids:
            value = fmea.read_source(c, tenant, project, "capa_action", id)
            sources.append(
                {
                    "kind": "capa_action",
                    "id": str(id),
                    "expected_digest": digest(value),
                    "value": value,
                }
            )
    pub, version = tables.fmea_publications, tables.fmea_versions
    active = (
        select(pub.c.id, pub.c.version_id)
        .join(version, version.c.id == pub.c.version_id)
        .where(pub.c.tenant_id == tenant, pub.c.project_id == project)
        .distinct(pub.c.entry_id)
        .order_by(pub.c.entry_id, version.c.version.desc())
        .subquery()
    )
    published = (
        c.execute(
            select(version, active.c.id.label("publication_id"))
            .join(active, active.c.version_id == version.c.id)
            .where(version.c.body["references"].contains([{"kind": "issue", "id": str(issue_id)}]))
            .order_by(version.c.entry_id)
        )
        .mappings()
        .all()
    )
    required = {(r["kind"], r["id"], r["expected_digest"]) for r in sources}
    bindings = []
    addressed_all: set[tuple[str, str, str]] = set()
    for row in published:
        values, gaps = fmea.current_sources(c, row)
        cited = {(r["kind"], r["id"], r["expected_digest"]) for r in values}
        d, candidate = tables.fmea_candidate_dispositions, tables.fmea_revision_candidates
        disposition = (
            c.execute(
                select(d.c.excluded_sources, candidate.c.snapshot)
                .join(candidate, candidate.c.id == d.c.candidate_id)
                .where(
                    d.c.tenant_id == tenant, d.c.project_id == project, d.c.version_id == row["id"]
                )
            )
            .mappings()
            .one_or_none()
        )
        exclusions = disposition["excluded_sources"] if disposition else []
        excluded_keys = {(r["kind"], r["id"]) for r in exclusions}
        addressed = cited | {
            (r["kind"], r["id"], r["expected_digest"])
            for r in (disposition["snapshot"]["sources"] if disposition else [])
            if (r["kind"], r["id"]) in excluded_keys
        }
        if not gaps:
            addressed_all.update(addressed)
        bindings.append(
            {
                "entry_id": str(row["entry_id"]),
                "version_id": str(row["id"]),
                "publication_id": str(row["publication_id"]),
                "version": row["version"],
                "title": row["body"]["title"],
                "sources": values,
                "source_gaps": gaps,
                "excluded_sources": exclusions,
                "all_inputs_addressed": not gaps and required <= addressed,
            }
        )
    reason = (
        "covered"
        if required <= addressed_all
        else "uncovered_issue"
        if not bindings
        else "source_changed"
        if any(r["source_gaps"] for r in bindings)
        else "quality_inputs_unlinked"
    )
    return {
        "issue": issue,
        "sources": sources,
        "links": [
            {"id": str(r["id"]), "ncr_id": str(r["ncr_id"]), "reason": r["reason"]} for r in links
        ],
        "publications": bindings,
        "reason": reason,
    }


def record_event(
    c: Connection,
    tenant: UUID,
    project: UUID,
    actor: UUID | None,
    id: UUID,
    issue_id: UUID,
    action: str,
) -> None:
    EventAuditWriter(c, tenant_id=tenant, project_id=project, actor_user_id=actor).record(
        EventDraft(
            event_id=f"fmea-candidate:{id}",
            event_type="FMEA_CANDIDATE_RECORDED",
            source="quality_service",
            entity_id=id,
            payload={"issue_id": str(issue_id), "action": action},
        ),
        AuditDraft(
            action="fmea.candidate." + action,
            after_snapshot={"record_id": str(id), "issue_id": str(issue_id)},
        ),
    )


def capture(
    c: Connection,
    tenant: UUID,
    project: UUID,
    issue_id: UUID,
    actor: UUID | None,
    event_row_id: int | None = None,
) -> RowMapping | None:
    current = packet(c, tenant, project, issue_id)
    if current["reason"] == "covered":
        return None
    t = tables.fmea_revision_candidates
    fingerprint = digest(current)
    row = (
        c.execute(
            insert(t)
            .values(
                id=uuid4(),
                tenant_id=tenant,
                project_id=project,
                issue_id=issue_id,
                input_digest=fingerprint,
                snapshot=current,
                source_event_row_id=event_row_id,
                created_by_user_id=actor,
                created_at=c.execute(select(func.clock_timestamp())).scalar_one(),
            )
            .on_conflict_do_nothing(constraint="uq_fmea_candidate_input")
            .returning(t)
        )
        .mappings()
        .one_or_none()
    )
    if row:
        record_event(c, tenant, project, actor, row["id"], issue_id, "discovered")
        return row
    return (
        c.execute(
            select(t).where(
                t.c.tenant_id == tenant,
                t.c.project_id == project,
                t.c.issue_id == issue_id,
                t.c.input_digest == fingerprint,
            )
        )
        .mappings()
        .one()
    )


def observe(
    c: Connection,
    tenant: UUID,
    project: UUID,
    actor: UUID | None,
    event_type: str,
    entity_id: UUID,
    event_row_id: int,
) -> None:
    """Called after the original business write, in its transaction; no new business facts."""
    if event_type not in TRIGGERS:
        return
    issue_ids: set[UUID] = set()
    ncr_id: UUID | None = None
    link = tables.quality_issue_links
    if event_type.startswith("ISSUE_"):
        issue_ids.add(entity_id)
    elif event_type == "QUALITY_ISSUE_LINK_RECORDED":
        r = tables.quality_issue_link_retractions
        row = c.execute(
            select(link.c.issue_id).where(
                link.c.tenant_id == tenant, link.c.project_id == project, link.c.id == entity_id
            )
        ).first()
        if row is None:
            row = c.execute(
                select(link.c.issue_id)
                .join(r, r.c.link_id == link.c.id)
                .where(r.c.tenant_id == tenant, r.c.project_id == project, r.c.id == entity_id)
            ).first()
        if row:
            issue_ids.add(row.issue_id)
    elif event_type == "FMEA_VERSION_PUBLISHED":
        p, v = tables.fmea_publications, tables.fmea_versions
        publication = (
            c.execute(
                select(p).where(
                    p.c.tenant_id == tenant, p.c.project_id == project, p.c.id == entity_id
                )
            )
            .mappings()
            .one()
        )
        # Removed associations must also be reconsidered.
        versions = [publication["version_id"]]
        if publication["previous_publication_id"]:
            versions.append(
                c.execute(
                    select(p.c.version_id).where(
                        p.c.tenant_id == tenant, p.c.id == publication["previous_publication_id"]
                    )
                ).scalar_one()
            )
        for body in c.execute(
            select(v.c.body).where(v.c.tenant_id == tenant, v.c.id.in_(versions))
        ).scalars():
            issue_ids.update(UUID(r["id"]) for r in body["references"] if r["kind"] == "issue")
    elif event_type in {"NCR_STATUS_CHANGED", "NCR_PREVENTIVE_DISPOSITION_APPROVED"}:
        ncr_id = entity_id
    else:
        t = (
            tables.root_cause_analyses
            if event_type == "ROOT_CAUSE_ANALYSIS_CHANGED"
            else tables.effectiveness_reviews
            if event_type == "EFFECTIVENESS_REVIEWED"
            else tables.capa_actions
        )
        ncr_id = c.execute(
            select(t.c.ncr_id).where(
                t.c.tenant_id == tenant, t.c.project_id == project, t.c.id == entity_id
            )
        ).scalar_one_or_none()
    if ncr_id:
        r = tables.quality_issue_link_retractions
        issue_ids.update(
            c.execute(
                select(link.c.issue_id).where(
                    link.c.tenant_id == tenant,
                    link.c.project_id == project,
                    link.c.ncr_id == ncr_id,
                    ~exists().where(r.c.link_id == link.c.id),
                )
            ).scalars()
        )
    for issue_id in sorted(issue_ids):
        capture(c, tenant, project, issue_id, actor, event_row_id)


def _get(c: Connection, tenant: UUID, project: UUID, candidate: UUID) -> RowMapping:
    t = tables.fmea_revision_candidates
    row = (
        c.execute(
            select(t).where(t.c.tenant_id == tenant, t.c.project_id == project, t.c.id == candidate)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkError("修订候选不存在或不可读")
    return row


def view(c: Connection, tenant: UUID, project: UUID, row: RowMapping) -> dict[str, Any]:
    current = packet(c, tenant, project, row["issue_id"])
    d = tables.fmea_candidate_dispositions
    disposition = (
        c.execute(
            select(d).where(
                d.c.tenant_id == tenant, d.c.project_id == project, d.c.candidate_id == row["id"]
            )
        )
        .mappings()
        .one_or_none()
    )
    names = {
        person.id: person.display_name
        for person in c.execute(
            select(tables.users.c.id, tables.users.c.display_name).where(
                tables.users.c.tenant_id == tenant,
                tables.users.c.id.in_(
                    [
                        row["created_by_user_id"],
                        disposition["created_by_user_id"] if disposition else None,
                    ]
                ),
            )
        ).all()
    }
    status = (
        disposition["action"]
        if disposition
        else "covered"
        if current["reason"] == "covered"
        else "stale"
        if digest(current) != row["input_digest"]
        else "pending"
    )
    return {
        **_plain(dict(row)),
        "status": status,
        "current": current,
        "current_digest": digest(current),
        "disposition": _plain(dict(disposition)) if disposition else None,
        "people": {str(id): name for id, name in names.items()},
    }


def listing(engine: Engine, context: AuthContext, project: UUID, offset: int) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        fmea.authorize(c, context, project, Action.QUALITY_VIEW)
        t = tables.fmea_revision_candidates
        values = (
            c.execute(
                select(t)
                .where(t.c.tenant_id == context.tenant.id, t.c.project_id == project)
                .order_by(t.c.created_at.desc(), t.c.id.desc())
                .offset(offset)
                .limit(21)
            )
            .mappings()
            .all()
        )
        return {
            "items": [view(c, context.tenant.id, project, row) for row in values[:20]],
            "next_offset": offset + 20 if len(values) > 20 else None,
            "can_edit": is_allowed(context.user.role, Action.CAPA_EXECUTE),
        }


def detail(engine: Engine, context: AuthContext, project: UUID, candidate: UUID) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        fmea.authorize(c, context, project, Action.QUALITY_VIEW)
        return view(c, context.tenant.id, project, _get(c, context.tenant.id, project, candidate))


def scan(
    engine: Engine, context: AuthContext, project: UUID, after_issue_id: UUID | None
) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project):
            raise ProductWorkError("项目不可用")
        fmea.authorize(c, context, project, Action.CAPA_EXECUTE)
        t = tables.issues
        query = select(t.c.id).where(t.c.tenant_id == context.tenant.id, t.c.project_id == project)
        if after_issue_id:
            query = query.where(t.c.id > after_issue_id)
        ids = c.execute(query.order_by(t.c.id).limit(31)).scalars().all()
        candidates = [
            capture(c, context.tenant.id, project, id, context.user.id) for id in ids[:30]
        ]
        return {
            "examined": min(30, len(ids)),
            "candidate_ids": [str(r["id"]) for r in candidates if r],
            "next_after_issue_id": str(ids[29]) if len(ids) > 30 else None,
        }


def refresh(engine: Engine, context: AuthContext, project: UUID, candidate: UUID) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project):
            raise ProductWorkError("项目不可用")
        fmea.authorize(c, context, project, Action.CAPA_EXECUTE)
        old = _get(c, context.tenant.id, project, candidate)
        row = capture(c, context.tenant.id, project, old["issue_id"], context.user.id)
        return {"candidate": view(c, context.tenant.id, project, row or old)}


def dispose(
    engine: Engine, context: AuthContext, project: UUID, candidate: UUID, request: Disposition
) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project):
            raise ProductWorkError("项目不可用")
        fmea.authorize(c, context, project, Action.CAPA_EXECUTE)
        t = tables.fmea_candidate_dispositions
        fingerprint = digest(
            {
                "project": str(project),
                "candidate": str(candidate),
                "request": request.model_dump(mode="json"),
            }
        )
        prior = (
            c.execute(
                select(t).where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.created_by_user_id == context.user.id,
                    t.c.request_id == request.request_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if prior:
            if prior["request_digest"] != fingerprint:
                raise ProductWorkError("此请求已用于其他候选处置")
            return _plain(dict(prior))
        row = _get(c, context.tenant.id, project, candidate)
        state = view(c, context.tenant.id, project, row)
        if state["status"] != "pending" or request.expected_digest != row["input_digest"]:
            raise ProductWorkError("候选已处理、来源已有变化或当前发布已覆盖，请重新读取")
        version: dict[str, Any] | None = None
        if request.action == "draft_created":
            assert request.content is not None
            refs = {(r.kind, str(r.id)): r.expected_digest for r in request.content.references}
            excluded = {(r.kind, str(r.id)) for r in request.excluded_sources}
            source_keys = {(r["kind"], r["id"]) for r in row["snapshot"]["sources"]}
            if excluded - source_keys or excluded & refs.keys():
                raise ProductWorkError("原记录须明确选择引用或不适用，不可两者并存")
            for ref in row["snapshot"]["sources"]:
                key = (ref["kind"], ref["id"])
                if refs.get(key) != ref["expected_digest"] and key not in excluded:
                    raise ProductWorkError(
                        "请逐项核对候选实际来源并保留引用，非适用质量记录须写明理由"
                    )
            saved = fmea.save(
                engine,
                context,
                project,
                fmea.Draft(
                    request_id=uuid5(request.request_id, "fmea-candidate-draft"),
                    entry_id=request.entry_id,
                    expected_version_id=request.expected_version_id,
                    content=request.content,
                ),
                connection=c,
            )
            version = saved["version"]
        result = (
            c.execute(
                t.insert()
                .values(
                    id=uuid4(),
                    tenant_id=context.tenant.id,
                    project_id=project,
                    candidate_id=candidate,
                    action=request.action,
                    reason=request.reason,
                    request_id=request.request_id,
                    request_digest=fingerprint,
                    created_by_user_id=context.user.id,
                    created_at=c.execute(select(func.clock_timestamp())).scalar_one(),
                    entry_id=UUID(version["entry_id"]) if version else None,
                    version_id=UUID(version["id"]) if version else None,
                    excluded_sources=[r.model_dump(mode="json") for r in request.excluded_sources],
                )
                .returning(t)
            )
            .mappings()
            .one()
        )
        record_event(
            c,
            context.tenant.id,
            project,
            context.user.id,
            result["id"],
            row["issue_id"],
            request.action,
        )
        return _plain(dict(result))
