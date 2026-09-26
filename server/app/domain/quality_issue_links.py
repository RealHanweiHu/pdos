"""Explicit Issue/NCR relations and atomic quality escalation with independent states."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, RowMapping, exists, func, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.db.schema import tables
from app.domain.complaints import ComplaintDraft, ComplaintService
from app.domain.findings import FindingService
from app.domain.living_fmea import read_source
from app.domain.nonconformance import NcrDraft, NonconformanceService
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class Link(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    issue_id: UUID
    ncr_id: UUID
    expected_issue_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_ncr_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(min_length=1, max_length=4000)


class Escalate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    issue_id: UUID
    expected_issue_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_links_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    separate_nonconformity: bool = False
    reason: str = Field(min_length=1, max_length=4000)
    owner_user_id: UUID
    title: str = Field(min_length=1, max_length=512)
    source: Literal["internal", "field", "rma"]
    occurred_at: AwareDatetime
    nonconformity: str = Field(min_length=1, max_length=20000)
    requirement_reference: str = Field(min_length=1, max_length=20000)
    severity: Literal["critical", "high", "medium", "low"]
    target_date: date
    affected_quantity: int | None = Field(default=None, ge=0)
    affected_scope: str | None = Field(default=None, max_length=20000)
    document_ids: list[UUID] = Field(default_factory=list, max_length=100)


class Retract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(min_length=1, max_length=4000)


def authorize(c: Connection, context: AuthContext, project: UUID, action: Action) -> None:
    for required in (Action.WORK_ITEM_VIEW, Action.QUALITY_VIEW, action):
        FindingService._authorize_user(
            c,
            tenant_id=context.tenant.id,
            project_id=project,
            user_id=context.user.id,
            action=required,
        )
    if not c.execute(
        select(tables.projects.c.id).where(
            tables.projects.c.tenant_id == context.tenant.id, tables.projects.c.id == project
        )
    ).first():
        raise ProductWorkError("项目不可用")


def issue(c: Connection, tenant: UUID, project: UUID, id: UUID) -> dict[str, Any]:
    return read_source(c, tenant, project, "issue", id)


def ncr(c: Connection, tenant: UUID, project: UUID, id: UUID) -> dict[str, Any]:
    value = read_source(c, tenant, project, "ncr", id)
    complaint = ComplaintService._get(
        c, tenant_id=tenant, project_id=project, complaint_id=UUID(value["complaint_id"])
    )
    value["complaint"] = _plain(asdict(complaint))
    documents = []
    for reference in complaint.document_refs:
        try:
            document = read_source(c, tenant, project, "document", UUID(reference))
        except (ValueError, ProductWorkError):
            document = None
        documents.append({"id": reference, "value": document, "available": document is not None})
    value["complaint_documents"] = documents
    t = tables.capa_actions
    actions = (
        c.execute(
            select(t)
            .where(t.c.tenant_id == tenant, t.c.project_id == project, t.c.ncr_id == id)
            .order_by(t.c.created_at, t.c.id)
        )
        .mappings()
        .all()
    )
    value["actions"] = [_plain(dict(r)) for r in actions]
    return value


def links_query(
    tenant: UUID, project: UUID, issue_id: UUID | None = None, ncr_id: UUID | None = None
) -> Any:
    t = tables.quality_issue_links
    query = select(t).where(t.c.tenant_id == tenant, t.c.project_id == project)
    if issue_id is not None:
        query = query.where(t.c.issue_id == issue_id)
    if ncr_id is not None:
        query = query.where(t.c.ncr_id == ncr_id)
    return query


def retractions(c: Connection, tenant: UUID, ids: list[UUID]) -> dict[UUID, dict[str, Any]]:
    t = tables.quality_issue_link_retractions
    return {
        r["link_id"]: _plain(dict(r))
        for r in c.execute(
            select(t).where(t.c.tenant_id == tenant, t.c.link_id.in_(ids))
        ).mappings()
    }


def relation_digest(c: Connection, tenant: UUID, project: UUID, issue_id: UUID) -> str:
    links = (
        c.execute(
            links_query(tenant, project, issue_id=issue_id).order_by(
                tables.quality_issue_links.c.id
            )
        )
        .mappings()
        .all()
    )
    undone = retractions(c, tenant, [r["id"] for r in links])
    return digest([{"id": str(r["id"]), "retracted": undone.get(r["id"])} for r in links])


def options(
    engine: Engine,
    context: AuthContext,
    project: UUID,
    kind: Literal["issue", "ncr", "document"],
    offset: int,
) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        authorize(c, context, project, Action.QUALITY_VIEW)
        table = {
            "issue": tables.issues,
            "ncr": tables.nonconformance_reports,
            "document": tables.documents,
        }[kind]
        ids = (
            c.execute(
                select(table.c.id)
                .where(table.c.tenant_id == context.tenant.id, table.c.project_id == project)
                .order_by(table.c.created_at.desc(), table.c.id.desc())
                .offset(offset)
                .limit(31)
            )
            .scalars()
            .all()
        )
        items = []
        for id in ids[:30]:
            value = (
                ncr(c, context.tenant.id, project, id)
                if kind == "ncr"
                else read_source(c, context.tenant.id, project, kind, id)
            )
            items.append({"id": str(id), "value": value, "digest": digest(value)})
        return {"items": items, "next_offset": offset + 30 if len(ids) > 30 else None}


def listing(
    engine: Engine,
    context: AuthContext,
    project: UUID,
    issue_id: UUID | None,
    ncr_id: UUID | None,
    offset: int,
) -> dict[str, Any]:
    if (issue_id is None) == (ncr_id is None):
        raise ProductWorkError("请从具体问题或 NCR 查看关联")
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        authorize(c, context, project, Action.QUALITY_VIEW)
        if issue_id is not None:
            anchor = issue(c, context.tenant.id, project, issue_id)
        elif ncr_id is not None:
            anchor = ncr(c, context.tenant.id, project, ncr_id)
        else:
            raise ProductWorkError("请从原问题或 NCR 查看")
        t = tables.quality_issue_links
        result = (
            c.execute(
                links_query(context.tenant.id, project, issue_id, ncr_id)
                .order_by(t.c.created_at.desc(), t.c.id.desc())
                .offset(offset)
                .limit(21)
            )
            .mappings()
            .all()
        )
        undone = retractions(c, context.tenant.id, [r["id"] for r in result[:20]])
        people = {r["created_by_user_id"] for r in result[:20]}
        people.update(UUID(r["created_by_user_id"]) for r in undone.values())
        items = []
        for row in result[:20]:
            current_issue = (
                anchor if issue_id else issue(c, context.tenant.id, project, row["issue_id"])
            )
            current_ncr = anchor if ncr_id else ncr(c, context.tenant.id, project, row["ncr_id"])
            actor_values = [
                current_issue.get("owner_user_id"),
                current_issue.get("verifier_user_id"),
                current_ncr.get("owner_user_id"),
            ]
            actor_values.extend(a.get("owner_user_id") for a in current_ncr["actions"])
            people.update(UUID(str(v)) for v in actor_values if v)
            items.append(
                {
                    **_plain(dict(row)),
                    "issue": current_issue,
                    "ncr": current_ncr,
                    "retraction": undone.get(row["id"]),
                    "digest": digest(_plain(dict(row))),
                    "has_later_changes": row["snapshot"]["issue"] != current_issue
                    or row["snapshot"]["ncr"] != current_ncr,
                }
            )
        users = c.execute(
            select(tables.users.c.id, tables.users.c.display_name).where(
                tables.users.c.tenant_id == context.tenant.id, tables.users.c.id.in_(people)
            )
        ).all()
        members = c.execute(
            select(tables.users.c.id, tables.users.c.display_name)
            .join(
                tables.project_members,
                (tables.project_members.c.tenant_id == tables.users.c.tenant_id)
                & (tables.project_members.c.user_id == tables.users.c.id),
            )
            .where(
                tables.users.c.tenant_id == context.tenant.id,
                tables.project_members.c.project_id == project,
                tables.users.c.is_active.is_(True),
                tables.users.c.role.not_in(["supplier", "customer"]),
            )
            .order_by(tables.users.c.display_name, tables.users.c.id)
        ).all()
        return {
            "anchor": anchor,
            "anchor_digest": digest(anchor),
            "items": items,
            "links_digest": relation_digest(c, context.tenant.id, project, issue_id)
            if issue_id
            else None,
            "next_offset": offset + 20 if len(result) > 20 else None,
            "people": {str(r.id): r.display_name for r in users},
            "members": [{"id": str(r.id), "name": r.display_name} for r in members],
            "can_link": is_allowed(context.user.role, Action.CAPA_EXECUTE),
            "can_escalate": all(
                is_allowed(context.user.role, a)
                for a in (Action.COMPLAINT_CREATE, Action.CAPA_MANAGE)
            ),
            "can_retract": is_allowed(context.user.role, Action.CAPA_MANAGE),
        }


def replay(
    c: Connection, table: Any, context: AuthContext, request_id: UUID, fingerprint: str
) -> RowMapping | None:
    old = (
        c.execute(
            select(table).where(
                table.c.tenant_id == context.tenant.id,
                table.c.created_by_user_id == context.user.id,
                table.c.request_id == request_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if old and old["request_digest"] != fingerprint:
        raise ProductWorkError("此请求已用于其他操作，请保留原请求回执")
    return old


def event(c: Connection, context: AuthContext, project: UUID, row: RowMapping, action: str) -> None:
    EventAuditWriter(
        c, tenant_id=context.tenant.id, project_id=project, actor_user_id=context.user.id
    ).record(
        EventDraft(
            event_id=f"quality-issue-link:{row['id']}:{action}",
            event_type="QUALITY_ISSUE_LINK_RECORDED",
            source="quality_service",
            entity_id=row["id"],
            payload={"record_id": str(row["id"]), "action": action},
        ),
        AuditDraft(
            action="quality.issue_link." + action,
            after_snapshot={"record_id": str(row["id"]), "reason": row["reason"]},
        ),
    )


def write_link(
    c: Connection,
    context: AuthContext,
    project: UUID,
    request_id: UUID,
    fingerprint: str,
    current_issue: dict[str, Any],
    current_ncr: dict[str, Any],
    reason: str,
    origin: str,
) -> RowMapping:
    t, r = tables.quality_issue_links, tables.quality_issue_link_retractions
    active = c.execute(
        links_query(
            context.tenant.id, project, UUID(current_issue["id"]), UUID(current_ncr["id"])
        ).where(~exists().where(r.c.link_id == t.c.id))
    ).first()
    if active:
        raise ProductWorkError("双方已有有效关联，请在原记录继续办理")
    row = (
        c.execute(
            t.insert()
            .values(
                id=uuid4(),
                tenant_id=context.tenant.id,
                project_id=project,
                issue_id=UUID(current_issue["id"]),
                ncr_id=UUID(current_ncr["id"]),
                origin=origin,
                request_id=request_id,
                request_digest=fingerprint,
                created_by_user_id=context.user.id,
                created_at=c.execute(select(func.clock_timestamp())).scalar_one(),
                reason=reason,
                snapshot={"issue": current_issue, "ncr": current_ncr},
            )
            .returning(t)
        )
        .mappings()
        .one()
    )
    event(c, context, project, row, origin)
    return row


def link(engine: Engine, context: AuthContext, project: UUID, body: Link) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project):
            raise ProductWorkError("项目不可用")
        authorize(c, context, project, Action.CAPA_EXECUTE)
        fingerprint = digest(
            {"project": str(project), "body": body.model_dump(mode="json"), "action": "link"}
        )
        old = replay(c, tables.quality_issue_links, context, body.request_id, fingerprint)
        if old:
            return _plain(dict(old))
        left, right = (
            issue(c, context.tenant.id, project, body.issue_id),
            ncr(c, context.tenant.id, project, body.ncr_id),
        )
        if digest(left) != body.expected_issue_digest or digest(right) != body.expected_ncr_digest:
            raise ProductWorkError("原问题或质量记录已变化，请重新读取核对")
        return _plain(
            dict(
                write_link(
                    c,
                    context,
                    project,
                    body.request_id,
                    fingerprint,
                    left,
                    right,
                    body.reason,
                    "linked",
                )
            )
        )


def escalate(engine: Engine, context: AuthContext, project: UUID, body: Escalate) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project):
            raise ProductWorkError("项目不可用")
        authorize(c, context, project, Action.CAPA_MANAGE)
        authorize(c, context, project, Action.COMPLAINT_CREATE)
        fingerprint = digest(
            {"project": str(project), "body": body.model_dump(mode="json"), "action": "escalate"}
        )
        old = replay(c, tables.quality_issue_links, context, body.request_id, fingerprint)
        if old:
            return _plain(dict(old))
        left = issue(c, context.tenant.id, project, body.issue_id)
        if (
            digest(left) != body.expected_issue_digest
            or relation_digest(c, context.tenant.id, project, body.issue_id)
            != body.expected_links_digest
        ):
            raise ProductWorkError("问题或已有质量关联已变化，请先读取原记录")
        if (
            c.execute(
                links_query(context.tenant.id, project, issue_id=body.issue_id).limit(1)
            ).first()
            and not body.separate_nonconformity
        ):
            raise ProductWorkError("问题已有质量关联；确属另一独立不符合时请明确勾选并说明")
        if body.target_date < date.today():
            raise ProductWorkError("新质量整改目标日期不能早于今天")
        if not c.execute(
            select(tables.users.c.id).where(
                tables.users.c.tenant_id == context.tenant.id,
                tables.users.c.id == body.owner_user_id,
                tables.users.c.is_active.is_(True),
            )
        ).first():
            raise ProductWorkError("请选择当前有效的项目质量负责人")
        complaint = ComplaintService(engine).create(
            connection=c,
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project,
            draft=ComplaintDraft(
                customer_id=None,
                owner_user_id=body.owner_user_id,
                title=body.title,
                description=body.nonconformity,
                source=body.source,
                severity=body.severity,
                occurred_at=body.occurred_at,
                customer_reference=None,
                affected_scope=body.affected_scope,
                document_refs=body.document_ids,
            ),
        )
        result = NonconformanceService(engine).triage(
            connection=c,
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project,
            complaint_id=complaint.id,
            draft=NcrDraft(
                owner_user_id=body.owner_user_id,
                nonconformity=body.nonconformity,
                requirement_reference=body.requirement_reference,
                severity=body.severity,
                target_date=body.target_date,
                affected_quantity=body.affected_quantity,
                affected_scope=body.affected_scope,
            ),
        )
        right = ncr(c, context.tenant.id, project, result.ncr.id)
        return _plain(
            dict(
                write_link(
                    c,
                    context,
                    project,
                    body.request_id,
                    fingerprint,
                    left,
                    right,
                    body.reason,
                    "escalated",
                )
            )
        )


def retract(
    engine: Engine, context: AuthContext, project: UUID, link_id: UUID, body: Retract
) -> dict[str, Any]:
    with engine.begin() as c:
        if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project):
            raise ProductWorkError("项目不可用")
        authorize(c, context, project, Action.CAPA_MANAGE)
        t = tables.quality_issue_link_retractions
        fingerprint = digest(
            {"project": str(project), "link": str(link_id), "body": body.model_dump(mode="json")}
        )
        prior = replay(c, t, context, body.request_id, fingerprint)
        if prior:
            return _plain(dict(prior))
        original = (
            c.execute(
                links_query(context.tenant.id, project).where(
                    tables.quality_issue_links.c.id == link_id
                )
            )
            .mappings()
            .one_or_none()
        )
        if original is None or digest(_plain(dict(original))) != body.expected_digest:
            raise ProductWorkError("原关联记录不可用或版本不符")
        if c.execute(select(t.c.id).where(t.c.link_id == link_id)).first():
            raise ProductWorkError("此关联已解除，原问题和质量记录保留")
        row = (
            c.execute(
                t.insert()
                .values(
                    id=uuid4(),
                    tenant_id=context.tenant.id,
                    project_id=project,
                    link_id=link_id,
                    request_id=body.request_id,
                    request_digest=fingerprint,
                    created_by_user_id=context.user.id,
                    created_at=c.execute(select(func.clock_timestamp())).scalar_one(),
                    reason=body.reason,
                )
                .returning(t)
            )
            .mappings()
            .one()
        )
        event(c, context, project, row, "retracted")
        return _plain(dict(row))
