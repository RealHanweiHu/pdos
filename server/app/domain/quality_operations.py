"""Human quality commands: original domain gates plus version-bound replay receipts."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, func, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, Role, is_allowed
from app.db.schema import tables
from app.domain.capa_actions import CapaActionDraft, CapaActionService
from app.domain.effectiveness import EffectivenessReviewDraft, EffectivenessService
from app.domain.findings import FindingService
from app.domain.nonconformance import NonconformanceService
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.quality_responsibilities import historical_capa_owners
from app.domain.root_causes import RootCauseDraft, RootCauseService
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Evidence(Strict):
    kind: Literal["document", "event", "test_run"]
    reference: str = Field(min_length=1, max_length=256)
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    locator: str = Field(default="", max_length=2000)


class Transition(Strict):
    action: Literal["ncr_transition"]
    to_status: Literal["containment", "root_cause", "action", "verification", "closed"]
    containment_action: str | None = Field(default=None, min_length=1, max_length=20000)
    effectiveness_criteria: str | None = Field(default=None, min_length=1, max_length=20000)
    observation_due_at: AwareDatetime | None = None


class RootCreate(Strict):
    action: Literal["root_create"]
    method: Literal["5why", "fishbone", "8d", "other"]
    analysis: str = Field(min_length=1, max_length=20000)
    root_cause: str = Field(min_length=1, max_length=20000)
    evidence: list[Evidence] = Field(default_factory=list, max_length=100)


class RootApprove(Strict):
    action: Literal["root_approve"]
    root_cause_id: UUID
    evidence: list[Evidence] = Field(min_length=1, max_length=100)


class ActionCreate(Strict):
    action: Literal["action_create"]
    owner_user_id: UUID
    action_type: Literal["corrective", "preventive"]
    description: str = Field(min_length=1, max_length=20000)
    due_date: date


class ActionTransition(Strict):
    action: Literal["action_transition"]
    action_id: UUID
    to_status: Literal["in_progress", "completed"]
    completion_summary: str | None = Field(default=None, min_length=1, max_length=20000)
    evidence: list[Evidence] = Field(default_factory=list, max_length=100)


class Review(Strict):
    action: Literal["effectiveness_review"]
    actual_result: str = Field(min_length=1, max_length=20000)
    result: Literal["effective", "ineffective"]
    evidence: list[Evidence] = Field(min_length=1, max_length=100)


class Preventive(Strict):
    action: Literal["preventive_not_applicable"]
    reason: str = Field(min_length=1, max_length=20000)


class Command(Strict):
    request_id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    body: Annotated[
        Transition
        | RootCreate
        | RootApprove
        | ActionCreate
        | ActionTransition
        | Review
        | Preventive,
        Field(discriminator="action"),
    ]


ACTIONS = {
    "ncr_transition": Action.CAPA_MANAGE,
    "root_create": Action.CAPA_EXECUTE,
    "root_approve": Action.CAPA_VERIFY,
    "action_create": Action.CAPA_EXECUTE,
    "action_transition": Action.CAPA_EXECUTE,
    "effectiveness_review": Action.CAPA_VERIFY,
    "preventive_not_applicable": Action.CAPA_VERIFY,
}


def authorize(c: Connection, context: AuthContext, project: UUID, action: Action) -> None:
    FindingService._authorize_user(
        c, tenant_id=context.tenant.id, project_id=project, user_id=context.user.id, action=action
    )


def state(c: Connection, tenant: UUID, project: UUID, ncr: UUID) -> dict[str, Any]:
    record = NonconformanceService._get(c, tenant_id=tenant, project_id=project, ncr_id=ncr)
    value: dict[str, Any] = {"ncr": asdict(record)}
    for key, table, order in [
        ("root_causes", tables.root_cause_analyses, "version"),
        ("actions", tables.capa_actions, "created_at"),
        ("reviews", tables.effectiveness_reviews, "review_number"),
    ]:
        value[key] = [
            dict(r)
            for r in c.execute(
                select(table)
                .where(
                    table.c.tenant_id == tenant,
                    table.c.project_id == project,
                    table.c.ncr_id == ncr,
                )
                .order_by(table.c[order], table.c.id)
            ).mappings()
        ]
    return _plain(value)


def evidence_value(
    c: Connection, tenant: UUID, project: UUID, kind: str, reference: str
) -> dict[str, Any]:
    table = {
        "document": tables.documents,
        "event": tables.events,
        "test_run": tables.test_runs,
    }.get(kind)
    if table is None:
        raise ProductWorkError("当前办理只接实际项目文件、事件和测试记录")
    query = select(table).where(table.c.tenant_id == tenant, table.c.project_id == project)
    try:
        query = (
            query.where(table.c.event_id == reference)
            if kind == "event"
            else query.where(table.c.id == UUID(reference))
        )
    except ValueError as error:
        raise ProductWorkError("原证据编号无效") from error
    row = c.execute(query.order_by(table.c.id).limit(1)).mappings().one_or_none()
    if row is None:
        raise ProductWorkError("原证据不存在或不可读")
    value = dict(row)
    if kind == "document":
        value = {
            k: value[k]
            for k in ("id", "filename", "sha256", "media_type", "classification", "created_at")
        }
    return _plain(value)


def evidence_options(
    engine: Engine,
    context: AuthContext,
    project: UUID,
    ncr: UUID,
    kind: Literal["document", "event", "test_run"],
    offset: int,
) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        authorize(c, context, project, Action.QUALITY_VIEW)
        NonconformanceService._get(c, tenant_id=context.tenant.id, project_id=project, ncr_id=ncr)
        t = {"document": tables.documents, "event": tables.events, "test_run": tables.test_runs}[
            kind
        ]
        reference_column = t.c.event_id if kind == "event" else t.c.id
        ids = (
            c.execute(
                select(reference_column)
                .where(t.c.tenant_id == context.tenant.id, t.c.project_id == project)
                .order_by(t.c.id.desc())
                .offset(offset)
                .limit(31)
            )
            .scalars()
            .all()
        )
        items = []
        for id in ids[:30]:
            value = evidence_value(c, context.tenant.id, project, kind, str(id))
            items.append(
                {
                    "kind": kind,
                    "reference": str(id),
                    "expected_digest": digest(value),
                    "value": value,
                }
            )
        return {"items": items, "next_offset": offset + 30 if len(ids) > 30 else None}


def workspace(
    engine: Engine, context: AuthContext, project: UUID, ncr: UUID, offset: int
) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        authorize(c, context, project, Action.QUALITY_VIEW)
        current = state(c, context.tenant.id, project, ncr)
        receipts = (
            c.execute(
                select(tables.quality_operation_receipts)
                .where(
                    tables.quality_operation_receipts.c.tenant_id == context.tenant.id,
                    tables.quality_operation_receipts.c.ncr_id == ncr,
                )
                .order_by(
                    tables.quality_operation_receipts.c.created_at.desc(),
                    tables.quality_operation_receipts.c.id.desc(),
                )
                .offset(offset)
                .limit(21)
            )
            .mappings()
            .all()
        )
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
        people = {
            UUID(str(r[k]))
            for rows in (current["root_causes"], current["actions"], current["reviews"])
            for r in rows
            for k in r
            if k.endswith("_user_id") and r[k]
        }
        people.update(r["created_by_user_id"] for r in receipts[:20])
        people.update(
            UUID(str(v)) for k, v in current["ncr"].items() if k.endswith("_user_id") and v
        )
        names = c.execute(
            select(tables.users.c.id, tables.users.c.display_name).where(
                tables.users.c.tenant_id == context.tenant.id, tables.users.c.id.in_(people)
            )
        ).all()
        record_evidence: dict[str, list[dict[str, Any]]] = {}
        for record in current["root_causes"] + current["actions"] + current["reviews"]:
            entries = []
            for ref in record["evidence_refs"]:
                try:
                    value = evidence_value(
                        c, context.tenant.id, project, ref["kind"], ref["reference"]
                    )
                    entries.append(
                        {**ref, "value": value, "expected_digest": digest(value), "available": True}
                    )
                except ProductWorkError:
                    entries.append({**ref, "available": False})
            record_evidence[record["id"]] = entries
        now = c.execute(select(func.clock_timestamp())).scalar_one()
        last_failure = next(
            (r for r in reversed(current["reviews"]) if r["result"] == "ineffective"), None
        )
        followup_action_ids = (
            [
                a["id"]
                for a in current["actions"]
                if datetime.fromisoformat(a["created_at"])
                > datetime.fromisoformat(last_failure["reviewed_at"])
            ]
            if last_failure
            else []
        )
        return {
            **current,
            "digest": digest(current),
            "record_evidence": record_evidence,
            "followup_action_ids": followup_action_ids,
            "members": [{"id": str(r.id), "name": r.display_name} for r in members],
            "people": {str(r.id): r.display_name for r in names},
            "actor_id": str(context.user.id),
            "historical_action_owner_ids": [
                str(id)
                for id in sorted(
                    historical_capa_owners(c, context.tenant.id, project, ncr), key=str
                )
            ],
            "can_manage": is_allowed(context.user.role, Action.CAPA_MANAGE),
            "can_execute": is_allowed(context.user.role, Action.CAPA_EXECUTE),
            "can_verify": context.user.role == Role.QUALITY
            and is_allowed(context.user.role, Action.CAPA_VERIFY),
            "server_time": now.isoformat(),
            "receipts": [_plain(dict(r)) for r in receipts[:20]],
            "next_offset": offset + 20 if len(receipts) > 20 else None,
        }


def evidence_payload(
    c: Connection, context: AuthContext, project: UUID, values: list[Evidence]
) -> list[dict[str, object]]:
    if len({(r.kind, r.reference) for r in values}) != len(values):
        raise ProductWorkError("同一证据请合并引用说明")
    for ref in values:
        value = evidence_value(c, context.tenant.id, project, ref.kind, ref.reference)
        if digest(value) != ref.expected_digest:
            raise ProductWorkError("证据已有变化，请重新读取核对")
    return [{"kind": r.kind, "reference": r.reference} for r in values]


def execute(
    engine: Engine, context: AuthContext, project: UUID, ncr: UUID, request: Command
) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project):
            raise ProductWorkError("项目不可用")
        command = request.body
        authorize(c, context, project, ACTIONS[command.action])
        needs_quality = (
            isinstance(command, (RootApprove, Review, Preventive))
            or isinstance(command, Transition)
            and command.to_status == "closed"
        )
        role = c.execute(
            select(tables.users.c.role).where(
                tables.users.c.tenant_id == context.tenant.id, tables.users.c.id == context.user.id
            )
        ).scalar_one()
        if needs_quality and role != Role.QUALITY:
            raise PermissionError("此操作须由品质角色办理")
        fingerprint = digest(
            {"project": str(project), "ncr": str(ncr), "request": request.model_dump(mode="json")}
        )
        t = tables.quality_operation_receipts
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
                raise ProductWorkError("此请求已用于其他质量操作")
            return _plain(dict(prior))
        before = state(c, context.tenant.id, project, ncr)
        if digest(before) != request.expected_digest:
            raise ProductWorkError("质量记录已有进展，请重新读取后按当前版本办理")
        common: dict[str, Any] = dict(
            connection=c,
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            project_id=project,
            ncr_id=ncr,
        )
        evidence_sources = []
        refs: list[dict[str, object]] = []
        if isinstance(command, (RootCreate, RootApprove, ActionTransition, Review)):
            refs = evidence_payload(c, context, project, command.evidence)
            evidence_sources = [
                {
                    **ref.model_dump(mode="json"),
                    "value": evidence_value(c, context.tenant.id, project, ref.kind, ref.reference),
                }
                for ref in command.evidence
            ]
        result: Any
        if isinstance(command, Transition):
            result = NonconformanceService(engine).transition(
                **common, **command.model_dump(exclude={"action"})
            )
        elif isinstance(command, RootCreate):
            result = RootCauseService(engine).create(
                **common,
                draft=RootCauseDraft(
                    method=command.method,
                    analysis=command.analysis,
                    root_cause=command.root_cause,
                    evidence_refs=refs,
                ),
            )
        elif isinstance(command, RootApprove):
            root = next(
                (r for r in before["root_causes"] if r["id"] == str(command.root_cause_id)), None
            )
            if root is None or {(r["kind"], r["reference"]) for r in root["evidence_refs"]} != {
                (r["kind"], r["reference"]) for r in refs
            }:
                raise ProductWorkError("请完整核对原根因版本的实际证据")
            result = RootCauseService(engine).approve(**common, root_cause_id=command.root_cause_id)
        elif isinstance(command, ActionCreate):
            if command.due_date < date.today():
                raise ProductWorkError("措施目标日期不能早于今天")
            active = c.execute(
                select(tables.users.c.id).where(
                    tables.users.c.tenant_id == context.tenant.id,
                    tables.users.c.id == command.owner_user_id,
                    tables.users.c.is_active.is_(True),
                )
            ).first()
            if active is None:
                raise ProductWorkError("请选择有效的项目措施负责人")
            result = CapaActionService(engine).create(
                **common,
                draft=CapaActionDraft(
                    owner_user_id=command.owner_user_id,
                    action_type=command.action_type,
                    description=command.description,
                    due_date=command.due_date,
                ),
            )
        elif isinstance(command, ActionTransition):
            result = CapaActionService(engine).transition(
                **common,
                action_id=command.action_id,
                to_status=command.to_status,
                completion_summary=command.completion_summary,
                evidence_refs=refs,
            )
        elif isinstance(command, Review):
            result = EffectivenessService(engine).review(
                **common,
                draft=EffectivenessReviewDraft(
                    actual_result=command.actual_result, result=command.result, evidence_refs=refs
                ),
            )
        else:
            result = NonconformanceService(engine).approve_preventive_not_applicable(
                **common, reason=command.reason
            )
        after = state(c, context.tenant.id, project, ncr)
        row = (
            c.execute(
                t.insert()
                .values(
                    id=uuid4(),
                    tenant_id=context.tenant.id,
                    project_id=project,
                    ncr_id=ncr,
                    request_id=request.request_id,
                    request_digest=fingerprint,
                    created_by_user_id=context.user.id,
                    created_at=c.execute(select(func.clock_timestamp())).scalar_one(),
                    command=command.model_dump(mode="json"),
                    result={"record": _plain(asdict(result)), "evidence_sources": evidence_sources},
                    before_digest=digest(before),
                    after_digest=digest(after),
                )
                .returning(t)
            )
            .mappings()
            .one()
        )
        EventAuditWriter(
            c, tenant_id=context.tenant.id, project_id=project, actor_user_id=context.user.id
        ).record(
            EventDraft(
                event_id=f"quality-operation:{row['id']}",
                event_type="QUALITY_OPERATION_RECORDED",
                source="quality_service",
                entity_id=row["id"],
                payload={"ncr_id": str(ncr), "action": command.action},
            ),
            AuditDraft(
                action="quality.operation.recorded",
                after_snapshot={"receipt_id": str(row["id"]), "command": command.action},
            ),
        )
        return _plain(dict(row))
