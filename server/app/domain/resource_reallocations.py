"""Named project consent and atomic application of cross-project reservation changes."""

from typing import Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy import Connection, Engine, select
from sqlalchemy.exc import IntegrityError

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.db.schema import tables
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _plain,
    _role,
    digest,
)
from app.domain.resource_reallocation_inputs import (
    ReallocationApply,
    ReallocationDecision,
    ReallocationDraft,
    ReallocationSubmit,
    capture,
)
from app.domain.resource_reservations import (
    ReservationAction,
    ReservationDraft,
    ResourceReservationService,
    _project,
)
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


def row(c: Connection, context: AuthContext, allocation: UUID) -> Any:
    t = tables.resource_reallocations
    result = (
        c.execute(select(t).where(t.c.tenant_id == context.tenant.id, t.c.id == allocation))
        .mappings()
        .one_or_none()
    )
    if result is None:
        raise ProductWorkAccessError("跨项目资源调整不存在")
    return result


def parts(c: Connection, context: AuthContext, allocation: UUID) -> list[Any]:
    t = tables.resource_reallocation_projects
    return list(
        c.execute(
            select(t)
            .where(t.c.tenant_id == context.tenant.id, t.c.allocation_id == allocation)
            .order_by(t.c.project_id)
        ).mappings()
    )


def access(c: Connection, context: AuthContext, project: UUID, allocation: Any) -> Any:
    _project(c, context, project)
    own = next((p for p in parts(c, context, allocation["id"]) if p["project_id"] == project), None)
    if own is None:
        raise ProductWorkAccessError("此调整不涉及当前项目")
    return own


def outcomes(c: Connection, context: AuthContext, allocation: UUID) -> tuple[list[Any], Any]:
    d, a = tables.resource_reallocation_decisions, tables.resource_reallocation_applications
    decisions = list(
        c.execute(
            select(d)
            .where(d.c.tenant_id == context.tenant.id, d.c.allocation_id == allocation)
            .order_by(d.c.created_at, d.c.id)
        ).mappings()
    )
    applied = (
        c.execute(
            select(a).where(a.c.tenant_id == context.tenant.id, a.c.allocation_id == allocation)
        )
        .mappings()
        .one_or_none()
    )
    return decisions, applied


def ensure_current(c: Connection, context: AuthContext, saved: Any) -> dict[str, Any]:
    command = ReallocationDraft.model_validate(saved["inputs"])
    current = capture(c, context, command)
    if current["preview_digest"] != saved["payload_digest"]:
        raise ProductWorkError(
            "原预约、项目负责人、容量、优先级或占用已变化，请按当前资料重新提出调整"
        )
    if not current["snapshot"]["capacity_clear"]:
        raise ProductWorkError("调整后仍有容量冲突或缺项，暂不能同意或应用")
    return dict(current["snapshot"])


def event(
    c: Connection,
    context: AuthContext,
    project: UUID,
    allocation: UUID,
    action: str,
    body: dict[str, Any],
) -> None:
    EventAuditWriter(
        c, tenant_id=context.tenant.id, actor_user_id=context.user.id, project_id=project
    ).record(
        EventDraft(
            event_id=f"resource-reallocation:{allocation}:{action}:{uuid4()}",
            event_type="RESOURCE_REALLOCATION_RECORDED",
            source="planning_service",
            entity_id=allocation,
            payload={"allocation_id": str(allocation), "action": action},
        ),
        AuditDraft(action=f"resource_reallocation.{action}", after_snapshot=body),
    )


class ResourceReallocationService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def options(
        self,
        context: AuthContext,
        project: UUID,
        resource: UUID,
        search: str = "",
        before: UUID | None = None,
    ) -> dict[str, Any]:
        _role(context, Action.TENANT_MANAGE)
        with self.engine.connect() as c:
            _project(c, context, project)
            r, p, n = tables.resource_reservations, tables.projects, tables.schedule_nodes
            query = (
                select(r, p.c.name.label("project_name"), n.c.contract.label("node_contract"))
                .join(p, (p.c.tenant_id == r.c.tenant_id) & (p.c.id == r.c.project_id))
                .join(n, (n.c.tenant_id == r.c.tenant_id) & (n.c.id == r.c.node_id))
                .where(
                    r.c.tenant_id == context.tenant.id,
                    r.c.resource_id == resource,
                    r.c.state.in_(("proposed", "reserved")),
                )
            )
            if search:
                query = query.where(
                    p.c.name.ilike("%" + search.replace("%", "\\%").replace("_", "\\_") + "%")
                )
            if before:
                query = query.where(r.c.id < before)
            found = list(c.execute(query.order_by(r.c.id.desc()).limit(51)).mappings())
            return {
                "items": [
                    {
                        "id": str(v["id"]),
                        "project_id": str(v["project_id"]),
                        "project_name": v["project_name"],
                        "node_id": str(v["node_id"]),
                        "state": v["state"],
                        "capacity_version_id": str(v["capacity_version_id"]),
                        "window_start": v["window_start"].isoformat(),
                        "window_end": v["window_end"].isoformat(),
                        "parallel_units": str(v["parallel_units"]),
                        "occupancy_policy": v["occupancy_policy"],
                        "basis": v["basis"],
                        "payload_digest": digest(
                            _plain({column.name: v[column.name] for column in r.c})
                        ),
                    }
                    for v in found[:50]
                ],
                "next": str(found[49]["id"]) if len(found) > 50 else None,
            }

    def list(
        self, context: AuthContext, project: UUID, before: UUID | None = None
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            actual = _project(c, context, project)
            t, p = tables.resource_reallocations, tables.resource_reallocation_projects
            query = (
                select(t)
                .join(p, (p.c.tenant_id == t.c.tenant_id) & (p.c.allocation_id == t.c.id))
                .where(t.c.tenant_id == context.tenant.id, p.c.project_id == project)
            )
            if before:
                cursor = c.execute(query.where(t.c.id == before)).mappings().one_or_none()
                if cursor is None:
                    raise ProductWorkError("历史游标不属于本项目")
                query = query.where(
                    (t.c.created_at < cursor["created_at"])
                    | ((t.c.created_at == cursor["created_at"]) & (t.c.id < before))
                )
            found = list(
                c.execute(query.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21)).mappings()
            )
            admin = is_allowed(context.user.role, Action.TENANT_MANAGE)
            items = []
            for value in found[:20]:
                participants = parts(c, context, value["id"])
                own = next(p for p in participants if p["project_id"] == project)
                decisions, application = outcomes(c, context, value["id"])
                stopped = any(d["action"] in ("reject", "withdraw") for d in decisions)
                accepted = {d["project_id"] for d in decisions if d["action"] == "approve"}
                ready = not stopped and len(accepted) == len(participants)
                items.append(
                    {
                        "id": str(value["id"]),
                        "created_at": value["created_at"].isoformat(),
                        "title": value["title"],
                        "payload_digest": value["payload_digest"],
                        "project_count": len(participants),
                        "approved_count": len(accepted),
                        "status": "applied"
                        if application
                        else "stopped"
                        if stopped
                        else "ready"
                        if ready
                        else "pending",
                        "parts": [
                            _plain(p) for p in participants if admin or p["project_id"] == project
                        ],
                        "decisions": [
                            _plain(d) for d in decisions if admin or d["project_id"] == project
                        ],
                        "can_decide": not application
                        and not stopped
                        and project not in accepted
                        and actual["owner_user_id"] == own["owner_user_id"] == context.user.id,
                        "can_withdraw": not application
                        and not stopped
                        and value["created_by_user_id"] == context.user.id
                        and admin,
                        "can_apply": not application and ready and admin,
                        "application": {
                            "id": str(application["id"]),
                            "created_at": application["created_at"].isoformat(),
                            "items": [
                                v
                                for v in application["receipt"]["items"]
                                if admin or v["project_id"] == str(project)
                            ],
                        }
                        if application
                        else None,
                    }
                )
            return {
                "items": items,
                "next": str(found[19]["id"]) if len(found) > 20 else None,
                "can_propose": admin,
            }

    def preview(
        self, context: AuthContext, project: UUID, draft: ReallocationDraft
    ) -> dict[str, Any]:
        _role(context, Action.TENANT_MANAGE)
        with self.engine.begin() as c:
            _project(c, context, project)
            result = capture(c, context, draft)
            if str(project) not in {p["id"] for p in result["snapshot"]["projects"]}:
                raise ProductWorkError("调整中须包含当前项目的实际预约")
            return result

    def submit(
        self, context: AuthContext, project: UUID, command: ReallocationSubmit
    ) -> dict[str, Any]:
        try:
            return self._submit(context, project, command)
        except IntegrityError as error:
            raise ProductWorkError("调整方案未重复保存；请刷新原记录或重试同一请求") from error

    def _submit(
        self, context: AuthContext, project: UUID, command: ReallocationSubmit
    ) -> dict[str, Any]:
        _role(context, Action.TENANT_MANAGE)
        with self.engine.begin() as c:
            _project(c, context, project)
            t = tables.resource_reallocations
            fingerprint = digest(command.model_dump(mode="json"))
            prior = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.created_by_user_id == context.user.id,
                        t.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                access(c, context, project, prior)
                if prior["request_digest"] != fingerprint:
                    raise ProductWorkError("请求编号已用于另一份跨项目调整")
                return {"id": str(prior["id"])}
            draft = ReallocationDraft.model_validate(
                command.model_dump(exclude={"expected_preview_digest"})
            )
            prepared = capture(c, context, draft)
            if prepared["preview_digest"] != command.expected_preview_digest:
                raise ProductWorkError("预览依据已变化，请重新预览后提交")
            snapshot = prepared["snapshot"]
            if str(project) not in {p["id"] for p in snapshot["projects"]}:
                raise ProductWorkError("调整中须包含当前项目")
            allocation = uuid4()
            c.execute(
                t.insert().values(
                    id=allocation,
                    tenant_id=context.tenant.id,
                    title=draft.title,
                    inputs=draft.model_dump(mode="json"),
                    snapshot=snapshot,
                    payload_digest=prepared["preview_digest"],
                    created_by_user_id=context.user.id,
                    request_id=command.request_id,
                    request_digest=fingerprint,
                )
            )
            for participant in snapshot["projects"]:
                pid = UUID(participant["id"])
                own_items = [item for item in snapshot["items"] if item["project_id"] == str(pid)]
                own_ids = {item["reservation_id"] for item in own_items}
                view = {
                    "project": participant,
                    "items": own_items,
                    "conflicts": [
                        v for v in snapshot["conflicts"] if v["reservation_id"] in own_ids
                    ],
                    "unknown": [v for v in snapshot["unknown"] if v["reservation_id"] in own_ids],
                    "capacity_clear": snapshot["capacity_clear"],
                    "reason": draft.reason,
                }
                c.execute(
                    tables.resource_reallocation_projects.insert().values(
                        tenant_id=context.tenant.id,
                        allocation_id=allocation,
                        project_id=pid,
                        owner_user_id=UUID(participant["owner_user_id"]),
                        body=view,
                    )
                )
                for item in own_items:
                    c.execute(
                        tables.resource_reallocation_items.insert().values(
                            tenant_id=context.tenant.id,
                            allocation_id=allocation,
                            project_id=pid,
                            reservation_id=UUID(item["reservation_id"]),
                            capacity_version_id=UUID(item["target"]["capacity_version_id"]),
                            policy_id=UUID(item["policy_id"]),
                        )
                    )
                event(c, context, pid, allocation, "proposed", view)
            return {"id": str(allocation)}

    def decide(
        self, context: AuthContext, project: UUID, command: ReallocationDecision
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            saved = row(c, context, command.allocation_id)
            own = access(c, context, project, saved)
            t = tables.resource_reallocation_decisions
            fingerprint = digest({"project_id": str(project), **command.model_dump(mode="json")})
            prior = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.actor_user_id == context.user.id,
                        t.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != fingerprint:
                    raise ProductWorkError("请求编号已用于另一项确认")
                return _plain(prior)
            # Shared inventory lock serializes decisions and application after project locks.
            for part in parts(c, context, saved["id"]):
                c.execute(
                    select(tables.projects.c.id)
                    .where(
                        tables.projects.c.tenant_id == context.tenant.id,
                        tables.projects.c.id == part["project_id"],
                    )
                    .with_for_update()
                )
            decisions, applied = outcomes(c, context, saved["id"])
            if applied or any(d["action"] in ("reject", "withdraw") for d in decisions):
                raise ProductWorkError("此调整已结束，请查看原回执")
            if saved["payload_digest"] != command.expected_digest:
                raise ProductWorkError("确认内容与所选版本不一致")
            if command.action == "withdraw":
                _role(context, Action.TENANT_MANAGE)
                if saved["created_by_user_id"] != context.user.id:
                    raise ProductWorkAccessError("仅提出人可撤回调整")
            else:
                actual = _project(c, context, project)
                if (
                    context.user.id != own["owner_user_id"]
                    or actual["owner_user_id"] != context.user.id
                ):
                    raise ProductWorkAccessError("仅此项目当前具名负责人可确认本项目影响")
                _role(context, Action.PROJECT_EDIT)
                if any(d["project_id"] == project for d in decisions):
                    raise ProductWorkError("本项目已有确认，请查看原记录")
                if command.action == "approve":
                    ensure_current(c, context, saved)
            record = (
                c.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        allocation_id=saved["id"],
                        project_id=None if command.action == "withdraw" else project,
                        action=command.action,
                        reason=command.reason,
                        payload_digest=saved["payload_digest"],
                        actor_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=fingerprint,
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            event(c, context, project, saved["id"], command.action, _plain(record))
            return _plain(record)

    def apply(
        self, context: AuthContext, project: UUID, command: ReallocationApply
    ) -> dict[str, Any]:
        _role(context, Action.TENANT_MANAGE)
        try:
            with self.engine.begin() as c:
                saved = row(c, context, command.allocation_id)
                access(c, context, project, saved)
                t = tables.resource_reallocation_applications
                fingerprint = digest(
                    {"project_id": str(project), **command.model_dump(mode="json")}
                )
                # Lock every project in the same order as preview and approval.
                for part in parts(c, context, saved["id"]):
                    _project(c, context, part["project_id"], write=True)
                decisions, applied = outcomes(c, context, saved["id"])
                if applied:
                    return _plain(applied)
                if (
                    saved["payload_digest"] != command.expected_digest
                    or any(d["action"] != "approve" for d in decisions)
                    or {d["project_id"] for d in decisions}
                    != {p["project_id"] for p in parts(c, context, saved["id"])}
                ):
                    raise ProductWorkError("各受影响项目须对同一版本全部具名同意后，再独立应用")
                snapshot = ensure_current(c, context, saved)
                service = ResourceReservationService(self.engine)
                released, proposed = {}, {}
                for item in snapshot["items"]:
                    old = item["original"]
                    if old["state"] == "reserved":
                        released[item["reservation_id"]] = service._act_in_transaction(
                            c,
                            context,
                            UUID(item["project_id"]),
                            UUID(item["reservation_id"]),
                            ReservationAction(
                                request_id=uuid5(saved["id"], f"release:{item['reservation_id']}"),
                                expected_digest=digest(old),
                                action="release",
                                reason=command.reason,
                            ),
                        )
                for item in snapshot["items"]:
                    old = item["original"]
                    if old["state"] == "reserved":
                        target = ReservationDraft.model_validate(
                            {
                                **item["target"],
                                "request_id": str(
                                    uuid5(saved["id"], f"proposal:{item['reservation_id']}")
                                ),
                            }
                        )
                        proposed[item["reservation_id"]] = service._propose_in_transaction(
                            c,
                            context,
                            UUID(item["project_id"]),
                            target,
                            owner_user_id=UUID(old["owner_user_id"]),
                        )
                    else:
                        proposed[item["reservation_id"]] = {**old, "payload_digest": digest(old)}
                receipts = []
                for item in sorted(
                    snapshot["items"], key=lambda item: (item["rank"], item["reservation_id"])
                ):
                    current = proposed[item["reservation_id"]]
                    reserved = service._act_in_transaction(
                        c,
                        context,
                        UUID(item["project_id"]),
                        UUID(current["id"]),
                        ReservationAction(
                            request_id=uuid5(saved["id"], f"reserve:{item['reservation_id']}"),
                            expected_digest=current["payload_digest"],
                            action="reserve",
                            reason=command.reason,
                        ),
                    )
                    receipt = {
                        "project_id": item["project_id"],
                        "previous_reservation_id": item["reservation_id"],
                        "reservation_id": reserved["id"],
                        "original_state": item["original"]["state"],
                        "reservation": reserved,
                    }
                    if item["reservation_id"] in released:
                        replacement_id = uuid4()
                        c.execute(
                            tables.resource_reservation_replacements.insert().values(
                                id=replacement_id,
                                tenant_id=context.tenant.id,
                                project_id=UUID(item["project_id"]),
                                previous_reservation_id=UUID(item["reservation_id"]),
                                replacement_reservation_id=UUID(reserved["id"]),
                                reason=command.reason,
                                snapshot={
                                    "previous": released[item["reservation_id"]],
                                    "replacement": reserved,
                                },
                                actor_user_id=context.user.id,
                                request_id=uuid5(
                                    saved["id"], f"replacement:{item['reservation_id']}"
                                ),
                                request_digest=digest(receipt),
                            )
                        )
                        receipt["replacement_id"] = str(replacement_id)
                    receipts.append(receipt)
                result = (
                    c.execute(
                        t.insert()
                        .values(
                            id=uuid4(),
                            tenant_id=context.tenant.id,
                            allocation_id=saved["id"],
                            payload_digest=saved["payload_digest"],
                            receipt={
                                "items": receipts,
                                "baseline_changed": False,
                                "commitments_changed": False,
                            },
                            actor_user_id=context.user.id,
                            request_id=command.request_id,
                            request_digest=fingerprint,
                        )
                        .returning(t)
                    )
                    .mappings()
                    .one()
                )
                for part in parts(c, context, saved["id"]):
                    event(
                        c,
                        context,
                        part["project_id"],
                        saved["id"],
                        "applied",
                        {
                            "application_id": str(result["id"]),
                            "items": [
                                v for v in receipts if v["project_id"] == str(part["project_id"])
                            ],
                        },
                    )
                return _plain(result)
        except IntegrityError as error:
            raise ProductWorkError(
                "调整未生效，原预约均保留；请刷新并核对容量、优先级及业务执行条件"
            ) from error
