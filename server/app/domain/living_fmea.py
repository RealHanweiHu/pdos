"""Human-owned FMEA revisions and source-bound publication, separate from CAPA closure."""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, RowMapping, func, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.db.schema import tables
from app.domain.change_impact_scope import _query as engineering_query
from app.domain.change_impact_scope import source as engineering_source
from app.domain.findings import FindingService
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

Kind = Literal[
    "requirement",
    "specification",
    "bom_item",
    "test_case",
    "test_run",
    "issue",
    "ncr",
    "capa_action",
    "document",
]
TABLES = {
    k: getattr(tables, t)
    for k, t in {
        "requirement": "requirements",
        "specification": "specifications",
        "bom_item": "development_bom_items",
        "test_case": "test_cases",
        "test_run": "test_runs",
        "issue": "issues",
        "ncr": "nonconformance_reports",
        "capa_action": "capa_actions",
        "document": "documents",
    }.items()
}


class Reference(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: Kind
    id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    relationship: str = Field(min_length=1, max_length=2000)
    locator: str = Field(default="", max_length=2000)


class Control(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    key: UUID
    kind: Literal["prevention", "detection"]
    description: str = Field(min_length=1, max_length=4000)
    verification: str = Field(min_length=1, max_length=4000)


class Content(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=300)
    design_function: str = Field(min_length=1, max_length=4000)
    failure_mode: str = Field(min_length=1, max_length=4000)
    effect: str = Field(min_length=1, max_length=4000)
    possible_cause: str = Field(min_length=1, max_length=4000)
    cause_status: Literal["hypothesis", "evidence_supported", "unknown"] = "unknown"
    controls: list[Control] = Field(default_factory=list, max_length=50)
    control_gaps: str = Field(min_length=1, max_length=4000)
    severity: int | None = Field(default=None, strict=True, ge=1, le=10)
    occurrence: int | None = Field(default=None, strict=True, ge=1, le=10)
    detection: int | None = Field(default=None, strict=True, ge=1, le=10)
    scoring_method: str = Field(min_length=1, max_length=4000)
    scoring_basis: str = Field(min_length=1, max_length=4000)
    unknown_reason: str = Field(default="", max_length=4000)
    next_action: str = Field(min_length=1, max_length=4000)
    references: list[Reference] = Field(default_factory=list, max_length=100)
    reason: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def consistent(self) -> Content:
        if len({c.key for c in self.controls}) != len(self.controls):
            raise ValueError("同一控制措施请保留唯一编号")
        if len({(r.kind, r.id) for r in self.references}) != len(self.references):
            raise ValueError("同一来源请合并关联说明")
        if (
            any(v is None for v in (self.severity, self.occurrence, self.detection))
            and not self.unknown_reason
        ):
            raise ValueError("未评分项须记录缺失依据或后续评估安排")
        if self.cause_status == "evidence_supported" and not any(
            r.kind in {"test_run", "ncr", "document"} for r in self.references
        ):
            raise ValueError("有证据支持的原因须引用实际测试、NCR 或项目文件")
        return self


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    entry_id: UUID | None = None
    expected_version_id: UUID | None = None
    content: Content


class Publication(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    version_id: UUID
    expected_publication_id: UUID | None = None
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(min_length=1, max_length=4000)
    details_confirmed: Literal[True]


def authorize(c: Connection, context: AuthContext, project: UUID, action: Action) -> None:
    if (
        c.execute(
            select(tables.projects.c.id).where(
                tables.projects.c.tenant_id == context.tenant.id, tables.projects.c.id == project
            )
        ).scalar_one_or_none()
        is None
    ):
        raise ProductWorkError("项目不存在或不可读")
    FindingService._authorize_user(
        c, tenant_id=context.tenant.id, project_id=project, user_id=context.user.id, action=action
    )
    # Engineering evidence and quality facts keep their original access boundary.
    FindingService._authorize_user(
        c,
        tenant_id=context.tenant.id,
        project_id=project,
        user_id=context.user.id,
        action=Action.PRODUCT_ENGINEERING_VIEW,
    )


def source_query(kind: Kind, tenant: UUID, project: UUID) -> Any:
    if kind not in {"ncr", "capa_action"}:
        return engineering_query(kind, tenant, project)
    t = TABLES[kind]
    return select(t).where(t.c.tenant_id == tenant, t.c.project_id == project)


def read_source(c: Connection, tenant: UUID, project: UUID, kind: Kind, id: UUID) -> dict[str, Any]:
    if kind not in {"ncr", "capa_action"}:
        return engineering_source(c, tenant, project, kind, id)
    row = (
        c.execute(source_query(kind, tenant, project).where(TABLES[kind].c.id == id))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkError("关联质量记录不存在或不可读")
    value = dict(row)
    if kind == "ncr":
        root = tables.root_cause_analyses
        review = tables.effectiveness_reviews
        approved = (
            c.execute(
                select(root)
                .where(
                    root.c.tenant_id == tenant,
                    root.c.project_id == project,
                    root.c.ncr_id == id,
                    root.c.status == "approved",
                )
                .order_by(root.c.version.desc())
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        effective = (
            c.execute(
                select(review)
                .where(
                    review.c.tenant_id == tenant,
                    review.c.project_id == project,
                    review.c.ncr_id == id,
                )
                .order_by(review.c.review_number.desc())
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        value["approved_root_cause"] = dict(approved) if approved else None
        value["latest_effectiveness_review"] = dict(effective) if effective else None
    else:
        value["ncr"] = read_source(c, tenant, project, "ncr", row["ncr_id"])
    return _plain(value)


def sources(
    engine: Engine, context: AuthContext, project: UUID, kind: Kind, offset: int
) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        authorize(c, context, project, Action.QUALITY_VIEW)
        ids = list(
            c.execute(
                source_query(kind, context.tenant.id, project)
                .with_only_columns(TABLES[kind].c.id)
                .order_by(TABLES[kind].c.id)
                .offset(offset)
                .limit(31)
            ).scalars()
        )
        result = []
        for id in ids[:30]:
            value = read_source(c, context.tenant.id, project, kind, id)
            result.append(
                {
                    "kind": kind,
                    "id": str(id),
                    "digest": digest(value),
                    "value": value,
                    "label": str(
                        value.get("code")
                        or value.get("title")
                        or value.get("part_number")
                        or value.get("filename")
                        or id
                    ),
                }
            )
        return {"items": result, "next_offset": offset + 30 if len(ids) > 30 else None}


def latest(c: Connection, tenant: UUID, project: UUID, entry: UUID) -> RowMapping | None:
    t = tables.fmea_versions
    return (
        c.execute(
            select(t)
            .where(t.c.tenant_id == tenant, t.c.project_id == project, t.c.entry_id == entry)
            .order_by(t.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )


def publication(c: Connection, tenant: UUID, project: UUID, entry: UUID) -> RowMapping | None:
    p, v = tables.fmea_publications, tables.fmea_versions
    return (
        c.execute(
            select(p)
            .join(v, v.c.id == p.c.version_id)
            .where(p.c.tenant_id == tenant, p.c.project_id == project, p.c.entry_id == entry)
            .order_by(v.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )


def current_sources(c: Connection, row: RowMapping) -> tuple[list[dict[str, Any]], list[str]]:
    result, gaps = [], []
    for ref in Content.model_validate(row["body"]).references:
        try:
            value = read_source(c, row["tenant_id"], row["project_id"], ref.kind, ref.id)
            valid = digest(value) == ref.expected_digest
        except ProductWorkError:
            value, valid = None, False
        if not valid:
            gaps.append(f"{ref.kind}:{ref.id}")
        result.append({**ref.model_dump(mode="json"), "current_value": value, "current": valid})
    return result, gaps


def detail_connection(
    c: Connection, tenant: UUID, project: UUID, entry: UUID, before_version: int | None = None
) -> dict[str, Any]:
    row = latest(c, tenant, project, entry)
    if row is None:
        raise ProductWorkError("FMEA 条目不存在")
    pub = publication(c, tenant, project, entry)
    values, gaps = current_sources(c, row)
    t = tables.fmea_versions
    query = select(t).where(
        t.c.tenant_id == tenant, t.c.project_id == project, t.c.entry_id == entry
    )
    if before_version is not None:
        query = query.where(t.c.version < before_version)
    history = c.execute(query.order_by(t.c.version.desc()).limit(21)).mappings().all()
    ids = [r["id"] for r in history[:20]]
    publications = (
        c.execute(
            select(tables.fmea_publications).where(
                tables.fmea_publications.c.tenant_id == tenant,
                tables.fmea_publications.c.version_id.in_(ids),
            )
        )
        .mappings()
        .all()
    )
    published_version = (
        c.execute(select(t).where(t.c.id == pub["version_id"], t.c.tenant_id == tenant))
        .mappings()
        .one()
        if pub
        else None
    )
    published_gaps = (
        gaps
        if published_version and published_version["id"] == row["id"]
        else current_sources(c, published_version)[1]
        if published_version
        else []
    )
    people = {r["created_by_user_id"] for r in [row, *history]}
    dispositions, candidates = tables.fmea_candidate_dispositions, tables.fmea_revision_candidates
    candidate_origins = (
        c.execute(
            select(dispositions, candidates.c.issue_id)
            .join(candidates, candidates.c.id == dispositions.c.candidate_id)
            .where(
                dispositions.c.tenant_id == tenant,
                dispositions.c.project_id == project,
                dispositions.c.version_id.in_(ids),
            )
        )
        .mappings()
        .all()
    )
    people.update(r["created_by_user_id"] for r in candidate_origins)
    people.update(p["published_by_user_id"] for p in publications)
    if pub:
        people.add(pub["published_by_user_id"])
    names = {
        str(r.id): r.display_name
        for r in c.execute(
            select(tables.users.c.id, tables.users.c.display_name).where(
                tables.users.c.tenant_id == tenant, tables.users.c.id.in_(people)
            )
        )
    }
    return _plain(
        {
            "entry_id": entry,
            "people": names,
            "latest": dict(row),
            "publication": dict(pub) if pub else None,
            "published_version": dict(published_version) if published_version else None,
            "published_source_gaps": published_gaps,
            "sources": values,
            "source_gaps": gaps,
            "digest": digest(
                {
                    "latest": _plain(dict(row)),
                    "publication": _plain(dict(pub)) if pub else None,
                    "sources": values,
                }
            ),
            "history": [dict(r) for r in history[:20]],
            "publications": [dict(r) for r in publications],
            "candidate_origins": [dict(r) for r in candidate_origins],
            "next_before_version": history[19]["version"] if len(history) > 20 else None,
        }
    )


def detail(
    engine: Engine,
    context: AuthContext,
    project: UUID,
    entry: UUID,
    before_version: int | None = None,
) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        authorize(c, context, project, Action.QUALITY_VIEW)
        return detail_connection(c, context.tenant.id, project, entry, before_version)


def listing(engine: Engine, context: AuthContext, project: UUID, offset: int) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        authorize(c, context, project, Action.QUALITY_VIEW)
        e = tables.fmea_entries
        entries = (
            c.execute(
                select(e.c.id)
                .where(e.c.tenant_id == context.tenant.id, e.c.project_id == project)
                .order_by(e.c.created_at.desc(), e.c.id.desc())
                .offset(offset)
                .limit(31)
            )
            .scalars()
            .all()
        )
        items = []
        for entry in entries[:30]:
            row, pub = (
                latest(c, context.tenant.id, project, entry),
                publication(c, context.tenant.id, project, entry),
            )
            if row:
                items.append(
                    {
                        "id": str(entry),
                        "latest_version_id": str(row["id"]),
                        "version": row["version"],
                        "title": row["body"]["title"],
                        "published_version_id": str(pub["version_id"]) if pub else None,
                    }
                )
        return {
            "items": items,
            "next_offset": offset + 30 if len(entries) > 30 else None,
            "can_edit": is_allowed(context.user.role, Action.CAPA_EXECUTE),
            "can_publish": is_allowed(context.user.role, Action.QUALITY_MANAGE),
        }


def event(
    c: Connection, context: AuthContext, project: UUID, id: UUID, entry: UUID, kind: str
) -> None:
    EventAuditWriter(
        c, tenant_id=context.tenant.id, actor_user_id=context.user.id, project_id=project
    ).record(
        EventDraft(
            event_id=f"{kind}:{id}",
            event_type=kind,
            source="quality_service",
            entity_id=id,
            payload={"entry_id": str(entry), "record_id": str(id)},
        ),
        AuditDraft(
            action=kind.lower(), after_snapshot={"entry_id": str(entry), "record_id": str(id)}
        ),
    )


def save(
    engine: Engine,
    context: AuthContext,
    project: UUID,
    draft: Draft,
    *,
    connection: Connection | None = None,
) -> dict[str, Any]:
    with (
        (
            nullcontext(connection)
            if connection is not None
            else engine.connect().execution_options(isolation_level="REPEATABLE READ")
        ) as c,
        nullcontext() if connection is not None else c.begin(),
    ):
        if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project):
            raise ProductWorkError("项目不可用")
        authorize(c, context, project, Action.CAPA_EXECUTE)
        t = tables.fmea_versions
        fingerprint = digest({"project": str(project), "body": draft.model_dump(mode="json")})
        prior = (
            c.execute(
                select(t).where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.created_by_user_id == context.user.id,
                    t.c.request_id == draft.request_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if prior:
            if prior["request_digest"] != fingerprint:
                raise ProductWorkError("此请求已用于其他 FMEA 修订")
            return _plain({"version": dict(prior), "replayed": True})
        old = latest(c, context.tenant.id, project, draft.entry_id) if draft.entry_id else None
        if draft.entry_id and old is None:
            raise ProductWorkError("FMEA 条目不存在")
        if draft.expected_version_id != (old["id"] if old else None):
            raise ProductWorkError("已有其他修订，请重新读取当前版本后补充")
        values = []
        for ref in draft.content.references:
            value = read_source(c, context.tenant.id, project, ref.kind, ref.id)
            if digest(value) != ref.expected_digest:
                raise ProductWorkError("关联资料已变化，请重新读取原值并核对")
            values.append({**ref.model_dump(mode="json"), "value": value})
        now, entry = (
            c.execute(select(func.clock_timestamp())).scalar_one(),
            draft.entry_id or uuid4(),
        )
        if old is None:
            c.execute(
                tables.fmea_entries.insert().values(
                    id=entry,
                    tenant_id=context.tenant.id,
                    project_id=project,
                    created_by_user_id=context.user.id,
                    created_at=now,
                )
            )
        row = (
            c.execute(
                t.insert()
                .values(
                    id=uuid4(),
                    tenant_id=context.tenant.id,
                    project_id=project,
                    entry_id=entry,
                    version=old["version"] + 1 if old else 1,
                    previous_version_id=old["id"] if old else None,
                    request_id=draft.request_id,
                    request_digest=fingerprint,
                    created_by_user_id=context.user.id,
                    created_at=now,
                    body=draft.content.model_dump(mode="json"),
                    sources=values,
                )
                .returning(t)
            )
            .mappings()
            .one()
        )
        event(c, context, project, row["id"], entry, "FMEA_VERSION_RECORDED")
        return _plain({"version": dict(row), "replayed": False})


def publish(
    engine: Engine, context: AuthContext, project: UUID, entry: UUID, request: Publication
) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project):
            raise ProductWorkError("项目不可用")
        authorize(c, context, project, Action.QUALITY_MANAGE)
        t = tables.fmea_publications
        fingerprint = digest(
            {"project": str(project), "entry": str(entry), "body": request.model_dump(mode="json")}
        )
        old = (
            c.execute(
                select(t).where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.published_by_user_id == context.user.id,
                    t.c.request_id == request.request_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if old:
            if old["request_digest"] != fingerprint:
                raise ProductWorkError("此请求已用于其他发布")
            return _plain({"publication": dict(old), "replayed": True})
        state = detail_connection(c, context.tenant.id, project, entry)
        current = state["publication"]
        if (
            state["latest"]["id"] != str(request.version_id)
            or (current["id"] if current else None)
            != (str(request.expected_publication_id) if request.expected_publication_id else None)
            or state["digest"] != request.expected_digest
        ):
            raise ProductWorkError("版本、来源或当前发布记录已有变化，请重新核对")
        if state["source_gaps"]:
            raise ProductWorkError("关联记录已变化或不可用，请先保存重新核对的修订")
        if not state["latest"]["sources"]:
            raise ProductWorkError("发布前须关联至少一项实际需求、设计、测试或质量资料")
        if current and current["version_id"] == str(request.version_id):
            raise ProductWorkError("此版本已发布，无需再次发布")
        row = (
            c.execute(
                t.insert()
                .values(
                    id=uuid4(),
                    tenant_id=context.tenant.id,
                    project_id=project,
                    entry_id=entry,
                    version_id=request.version_id,
                    previous_publication_id=request.expected_publication_id,
                    request_id=request.request_id,
                    request_digest=fingerprint,
                    published_by_user_id=context.user.id,
                    published_at=c.execute(select(func.clock_timestamp())).scalar_one(),
                    reason=request.reason,
                )
                .returning(t)
            )
            .mappings()
            .one()
        )
        event(c, context, project, row["id"], entry, "FMEA_VERSION_PUBLISHED")
        return _plain({"publication": dict(row), "replayed": False})


def coverage(engine: Engine, context: AuthContext, project: UUID, offset: int) -> dict[str, Any]:
    """Only explicit current publication links count; adjacency/text never implies coverage."""
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        authorize(c, context, project, Action.QUALITY_VIEW)
        issues = (
            c.execute(
                source_query("issue", context.tenant.id, project)
                .order_by(tables.issues.c.id)
                .offset(offset)
                .limit(31)
            )
            .mappings()
            .all()
        )
        p, v = tables.fmea_publications, tables.fmea_versions
        active = (
            select(p.c.entry_id, p.c.version_id)
            .join(v, v.c.id == p.c.version_id)
            .where(p.c.tenant_id == context.tenant.id, p.c.project_id == project)
            .distinct(p.c.entry_id)
            .order_by(p.c.entry_id, v.c.version.desc())
            .subquery()
        )
        validity: dict[UUID, bool] = {}
        items = []
        for issue in issues[:30]:
            linked = (
                c.execute(
                    select(v)
                    .join(active, active.c.version_id == v.c.id)
                    .where(
                        v.c.body["references"].contains([{"kind": "issue", "id": str(issue["id"])}])
                    )
                )
                .mappings()
                .all()
            )
            links = []
            for version in linked:
                if version["id"] not in validity:
                    validity[version["id"]] = not current_sources(c, version)[1]
                links.append(
                    {
                        "entry_id": str(version["entry_id"]),
                        "version_id": str(version["id"]),
                        "version": version["version"],
                        "title": version["body"]["title"],
                        "sources_current": validity[version["id"]],
                    }
                )
            value = _plain(dict(issue))
            items.append(
                {
                    "issue": value,
                    "digest": digest(value),
                    "links": links,
                    "coverage": "associated_current"
                    if any(r["sources_current"] for r in links)
                    else "needs_review"
                    if links
                    else "uncovered",
                }
            )
        return {
            "items": items,
            "next_offset": offset + 30 if len(issues) > 30 else None,
            "meaning": (
                "仅核对当前发布版本的显式关联和来源有效性；"
                "关联不代表风险已受控或 Issue/CAPA 已关闭。"
            ),
        }
