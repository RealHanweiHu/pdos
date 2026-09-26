"""Human project reservations; proposals never occupy shared capacity."""

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import Connection, Engine, func, select
from sqlalchemy.exc import IntegrityError

from app.auth.repository import AuthContext
from app.auth.roles import Action, Role, is_allowed
from app.contracts.common_objects import (
    ApprovalRef,
    Contract,
    Digest,
    Quantity,
    ScheduleNode,
    ScheduleSource,
    Text,
    TimeWindow,
)
from app.contracts.object_operations import ReservationChangedPayload
from app.contracts.planning_records import ResourceReservation
from app.db.schema import tables
from app.domain.organization import active_delegated_principals
from app.domain.plan_scenarios import _calendar_access
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _plain,
    _role,
    digest,
)
from app.domain.resource_capacity import _intervals
from app.domain.working_time import CalendarDefinition, WorkingTime
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

POLICY_VERSION = "resource.admin_fcfs_no_preemption.v1"


class ReservationDraft(Contract):
    request_id: UUID
    task_id: UUID | None = None
    node_id: UUID | None = None
    capacity_version_id: UUID
    window_start: AwareDatetime
    window_end: AwareDatetime
    parallel_units: Quantity = Field(gt=0, le=1000)
    occupancy_policy: Literal["working_only", "through_waiting"]
    basis: Text

    @model_validator(mode="after")
    def window(self) -> Self:
        if (self.task_id is None) == (self.node_id is None):
            raise ValueError("请选择实际任务或已登记的排程节点，两者仅填一项")
        start, end = self.window_start.astimezone(UTC), self.window_end.astimezone(UTC)
        if not timedelta(0) < end - start <= timedelta(days=3660) or any(
            value.second or value.microsecond for value in (start, end)
        ):
            raise ValueError("预约窗口须为正、按整分钟填写且不超过十年")
        return self


class ReservationAction(Contract):
    request_id: UUID
    expected_digest: Digest
    action: Literal["reserve", "cancel", "release"]
    reason: Text


def _project(
    connection: Connection, context: AuthContext, project_id: UUID, *, write: bool = False
) -> Any:
    _calendar_access(context)
    _role(context, Action.WORK_ITEM_EDIT if write else Action.WORK_ITEM_VIEW)
    statement = select(tables.projects).where(
        tables.projects.c.tenant_id == context.tenant.id, tables.projects.c.id == project_id
    )
    row = (
        connection.execute(statement.with_for_update() if write else statement)
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkAccessError("项目不存在或不可访问")
    if context.user.role not in {Role.OWNER, Role.ADMIN}:
        principals = (
            context.user.id,
            *active_delegated_principals(
                connection, tenant_id=context.tenant.id, delegate_user_id=context.user.id
            ),
        )
        if (
            connection.execute(
                select(tables.project_members.c.id).where(
                    tables.project_members.c.tenant_id == context.tenant.id,
                    tables.project_members.c.project_id == project_id,
                    tables.project_members.c.user_id.in_(principals),
                )
            ).first()
            is None
        ):
            raise ProductWorkAccessError("当前不具备项目访问权限")
    return row


def legacy_inventory_missing(connection: Connection, context: AuthContext, resource: Any) -> bool:
    return bool(
        connection.execute(
            select(func.cehub_project.resource_inventory_missing(context.tenant.id, resource["id"]))
        ).scalar_one()
    )


def _record(row: Any) -> dict[str, Any]:
    return {**_plain(row), "payload_digest": digest(_plain(row))}


def _receipt(
    connection: Connection,
    context: AuthContext,
    project_id: UUID,
    request_id: UUID,
    fingerprint: str,
) -> Any:
    table = tables.resource_reservation_receipts
    prior = (
        connection.execute(
            select(table).where(
                table.c.tenant_id == context.tenant.id,
                table.c.project_id == project_id,
                table.c.actor_user_id == context.user.id,
                table.c.request_id == request_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if prior and prior["request_digest"] != fingerprint:
        raise ProductWorkError("请求编号已用于不同预约操作")
    return prior


def _write_receipt(
    connection: Connection,
    context: AuthContext,
    row: Any,
    receipt_id: UUID,
    request_id: UUID,
    fingerprint: str,
    reason: str,
    priority_review: dict[str, Any] | None = None,
) -> None:
    connection.execute(
        tables.resource_reservation_receipts.insert().values(
            id=receipt_id,
            tenant_id=context.tenant.id,
            project_id=row["project_id"],
            reservation_id=row["id"],
            actor_user_id=context.user.id,
            request_id=request_id,
            request_digest=fingerprint,
            snapshot=_plain(row),
            reason=reason,
        )
    )
    event_type = "RESOURCE_RESERVATION_RECORDED"
    payload = {"reservation_id": str(row["id"]), "state": row["state"], "version": row["version"]}
    if row["state"] in ("reserved", "released"):
        event_type = "RESOURCE_RESERVATION_CHANGED"
        payload = ReservationChangedPayload(
            object_id=row["id"],
            object_version=row["version"],
            operation_id=request_id,
            correlation_id=row["id"],
            causation_event_row_id=None,
            project_id=row["project_id"],
            resource_id=row["resource_id"],
            from_state="proposed" if row["state"] == "reserved" else "reserved",
            to_state=row["state"],
            capacity_version=row["contract"]["capacity_version"],
        ).model_dump(mode="json")
    EventAuditWriter(
        connection,
        tenant_id=context.tenant.id,
        actor_user_id=context.user.id,
        project_id=row["project_id"],
    ).record(
        EventDraft(
            event_id=f"resource-reservation:{receipt_id}",
            event_type=event_type,
            source="planning_service",
            entity_id=row["id"],
            payload=payload,
        ),
        AuditDraft(
            action="resource_reservation." + row["state"],
            after_snapshot=_plain(row),
            context={
                "reason": reason,
                **({"priority_review": priority_review} if priority_review else {}),
            },
        ),
    )


class ResourceReservationService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def list(
        self, context: AuthContext, project_id: UUID, *, target_id: UUID | None = None
    ) -> dict[str, Any]:
        with self.engine.connect() as connection:
            project = _project(connection, context, project_id)
            table = tables.resource_reservations
            rows = list(
                connection.execute(
                    select(table)
                    .where(table.c.tenant_id == context.tenant.id, table.c.project_id == project_id)
                    .order_by(table.c.created_at.desc(), table.c.id)
                    .limit(201)
                ).mappings()
            )
            has_more = len(rows) > 200
            rows = rows[:200]
            if target_id is not None:
                target = (
                    connection.execute(
                        select(table).where(
                            table.c.tenant_id == context.tenant.id,
                            table.c.project_id == project_id,
                            table.c.id == target_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if target is None:
                    raise ProductWorkAccessError("所选预约不存在或不属于当前项目")
                rows = [target]
                has_more = False
            task_rows = list(
                connection.execute(
                    select(tables.tasks.c.id, tables.tasks.c.title, tables.tasks.c.status)
                    .where(
                        tables.tasks.c.tenant_id == context.tenant.id,
                        tables.tasks.c.project_id == project_id,
                        tables.tasks.c.status.not_in(("done", "skipped", "pending_approval")),
                    )
                    .order_by(tables.tasks.c.title)
                    .limit(1001)
                ).mappings()
            )
            node_ids = {row["node_id"] for row in rows}
            nodes = {
                row["id"]: str(row["task_id"]) if row["task_id"] else None
                for row in connection.execute(
                    select(tables.schedule_nodes).where(
                        tables.schedule_nodes.c.tenant_id == context.tenant.id,
                        tables.schedule_nodes.c.project_id == project_id,
                        tables.schedule_nodes.c.id.in_(node_ids),
                    )
                ).mappings()
            }
            resources = {
                row["id"]: row
                for row in connection.execute(
                    select(tables.planning_resources).where(
                        tables.planning_resources.c.tenant_id == context.tenant.id,
                        tables.planning_resources.c.id.in_({row["resource_id"] for row in rows}),
                    )
                ).mappings()
            }
            users = {
                row.id: row.display_name
                for row in connection.execute(
                    select(tables.users.c.id, tables.users.c.display_name).where(
                        tables.users.c.tenant_id == context.tenant.id,
                        tables.users.c.id.in_(
                            {row["owner_user_id"] for row in rows}
                            | {row["user_id"] for row in resources.values() if row["user_id"]}
                        ),
                    )
                )
            }
            from app.domain.schedule_nodes import list_nodes

            node_choices = list_nodes(connection, context, project_id)
            node_details = {node["id"]: node for node in node_choices}
            links = tables.resource_reservation_replacements
            replacements = list(
                connection.execute(
                    select(links)
                    .where(
                        links.c.tenant_id == context.tenant.id,
                        links.c.project_id == project_id,
                        (links.c.previous_reservation_id.in_([row["id"] for row in rows[:200]]))
                        | (
                            links.c.replacement_reservation_id.in_(
                                [row["id"] for row in rows[:200]]
                            )
                        ),
                    )
                    .order_by(links.c.created_at, links.c.id)
                ).mappings()
            )
            pb, pv = tables.resource_priority_bindings, tables.resource_priority_versions
            priorities = {
                v["reservation_id"]: _plain(dict(v))
                for v in connection.execute(
                    select(
                        pb.c.reservation_id, pb.c.rank, pv.c.version, pv.c.valid_until, pv.c.status
                    )
                    .join(pv, (pv.c.tenant_id == pb.c.tenant_id) & (pv.c.id == pb.c.policy_id))
                    .where(
                        pb.c.tenant_id == context.tenant.id,
                        pb.c.reservation_id.in_({r["id"] for r in rows}),
                    )
                ).mappings()
            }
            return {
                "replacements": [_plain(row) for row in replacements],
                "nodes": [node for node in node_choices if node["reservable"]],
                "items": [
                    {
                        **_record(row),
                        "priority_policy": priorities.get(row["id"]),
                        "resource_name": resources[row["resource_id"]]["name"],
                        "resource_user_id": str(resources[row["resource_id"]]["user_id"])
                        if resources[row["resource_id"]]["user_id"]
                        else None,
                        "resource_user_name": users.get(resources[row["resource_id"]]["user_id"]),
                        "owner_name": users.get(row["owner_user_id"]),
                        "task_id": nodes[row["node_id"]],
                        "node_title": node_details.get(str(row["node_id"]), {}).get(
                            "title", "项目排程节点"
                        ),
                        "node_kind": node_details.get(str(row["node_id"]), {}).get("node_kind"),
                    }
                    for row in rows[:200]
                ],
                "has_more": has_more,
                "tasks": [_plain(row) for row in task_rows[:1000]],
                "has_more_tasks": len(task_rows) > 1000,
                "can_propose": is_allowed(context.user.role, Action.WORK_ITEM_EDIT)
                and project["status"] not in ("completed", "archived"),
                "can_reserve": is_allowed(context.user.role, Action.TENANT_MANAGE),
                "policy_version": "resource.priority.v1",
                "project_status": project["status"],
            }

    def propose(
        self, context: AuthContext, project_id: UUID, draft: ReservationDraft
    ) -> dict[str, Any]:
        with self.engine.begin() as connection:
            return self._propose_in_transaction(connection, context, project_id, draft)

    def _propose_in_transaction(
        self,
        connection: Connection,
        context: AuthContext,
        project_id: UUID,
        draft: ReservationDraft,
        *,
        owner_user_id: UUID | None = None,
    ) -> dict[str, Any]:
        project = _project(connection, context, project_id, write=True)
        fingerprint = digest({"action": "propose", **draft.model_dump(mode="json")})
        previous = _receipt(connection, context, project_id, draft.request_id, fingerprint)
        if previous:
            return _record(previous["snapshot"])
        if project["status"] in ("completed", "archived"):
            raise ProductWorkError("已结束项目不能提出新预约")
        from app.domain.schedule_nodes import require_reservable_node

        node = None
        task = None
        if draft.node_id is not None:
            node = require_reservable_node(connection, context, project_id, draft.node_id)
        else:
            task = (
                connection.execute(
                    select(tables.tasks).where(
                        tables.tasks.c.tenant_id == context.tenant.id,
                        tables.tasks.c.project_id == project_id,
                        tables.tasks.c.id == draft.task_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if task is None or task["status"] in ("done", "skipped", "pending_approval"):
                raise ProductWorkError("请选择当前项目中可执行的实际任务")
        cap = (
            connection.execute(
                select(tables.resource_capacity_versions).where(
                    tables.resource_capacity_versions.c.tenant_id == context.tenant.id,
                    tables.resource_capacity_versions.c.id == draft.capacity_version_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if cap is None:
            raise ProductWorkError("容量版本不存在")
        connection.execute(
            select(tables.planning_resources.c.id)
            .where(
                tables.planning_resources.c.tenant_id == context.tenant.id,
                tables.planning_resources.c.id == cap["resource_id"],
            )
            .with_for_update()
        ).scalar_one()
        calendar = (
            connection.execute(
                select(tables.work_calendar_versions).where(
                    tables.work_calendar_versions.c.tenant_id == context.tenant.id,
                    tables.work_calendar_versions.c.id == cap["calendar_version_id"],
                )
            )
            .mappings()
            .one()
        )
        engine = WorkingTime(CalendarDefinition.model_validate(calendar["definition"]))
        if _plain(asdict(engine.evidence)) != cap["calendar_evidence"]:
            raise ProductWorkError("时区规则已变化，请发布新容量")
        spans = (
            _intervals(engine, draft.window_start.astimezone(UTC), draft.window_end.astimezone(UTC))
            if draft.occupancy_policy == "working_only"
            else [(draft.window_start.astimezone(UTC), draft.window_end.astimezone(UTC))]
        )
        if not spans:
            raise ProductWorkError("预约窗口内没有占用时段")
        node_table = tables.schedule_nodes
        if node is None:
            node = (
                connection.execute(
                    select(node_table).where(
                        node_table.c.tenant_id == context.tenant.id,
                        node_table.c.project_id == project_id,
                        node_table.c.task_id == draft.task_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
        if node is None:
            if task is None:
                raise ProductWorkError("预约必须关联实际任务")
            node_id = uuid4()
            node_contract = ScheduleNode(
                id=node_id,
                tenant_id=context.tenant.id,
                project_id=project_id,
                node_kind="task",
                source=ScheduleSource(
                    kind="task",
                    tenant_id=context.tenant.id,
                    project_id=project_id,
                    ref_id=task["id"],
                    as_of=task["updated_at"],
                    digest=digest(_plain(task)),
                ),
                calendar_id=calendar["calendar_id"],
            )
            node = (
                connection.execute(
                    node_table.insert()
                    .values(
                        id=node_id,
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        task_id=draft.task_id,
                        calendar_version_id=calendar["id"],
                        contract=node_contract.model_dump(mode="json"),
                    )
                    .returning(node_table)
                )
                .mappings()
                .one()
            )
        from app.domain.resource_priorities import PREFIX, active, bind

        priority_policy = active(connection, context.tenant.id, cap["resource_id"])
        row_id = uuid4()
        contract = ResourceReservation(
            id=row_id,
            tenant_id=context.tenant.id,
            project_id=project_id,
            version=1,
            resource_id=cap["resource_id"],
            capacity_version=cap["version"],
            calendar_version=calendar["version"],
            node_id=node["id"],
            owner_user_id=owner_user_id or context.user.id,
            window=TimeWindow(start=draft.window_start, end=draft.window_end),
            amount=draft.parallel_units,
            unit="slots",
            priority_policy_version=PREFIX + str(priority_policy["id"]),
            state="proposed",
            approval=None,
            reservation_receipt_id=None,
            reserved_at=None,
            released_at=None,
            release_reason=None,
        )
        table = tables.resource_reservations
        row = (
            connection.execute(
                table.insert()
                .values(
                    id=row_id,
                    tenant_id=context.tenant.id,
                    project_id=project_id,
                    node_id=node["id"],
                    resource_id=cap["resource_id"],
                    capacity_version_id=cap["id"],
                    owner_user_id=owner_user_id or context.user.id,
                    created_by_user_id=context.user.id,
                    window_start=draft.window_start,
                    window_end=draft.window_end,
                    parallel_units=draft.parallel_units,
                    occupancy_policy=draft.occupancy_policy,
                    basis=draft.basis,
                    version=1,
                    state="proposed",
                    contract=contract.model_dump(mode="json"),
                )
                .returning(table)
            )
            .mappings()
            .one()
        )
        bind(connection, context, row, priority_policy)
        for start, end in spans:
            connection.execute(
                tables.resource_reservation_intervals.insert().values(
                    tenant_id=context.tenant.id, reservation_id=row_id, start=start, end=end
                )
            )
        _write_receipt(
            connection, context, row, uuid4(), draft.request_id, fingerprint, draft.basis
        )
        return _record(row)

    def act(
        self,
        context: AuthContext,
        project_id: UUID,
        reservation_id: UUID,
        command: ReservationAction,
    ) -> dict[str, Any]:
        try:
            return self._act(context, project_id, reservation_id, command)
        except IntegrityError as error:
            raise ProductWorkError(
                "预约未生效：容量版本、可用时段或并发占用已变化，请刷新后调整"
            ) from error

    def _act(
        self,
        context: AuthContext,
        project_id: UUID,
        reservation_id: UUID,
        command: ReservationAction,
    ) -> dict[str, Any]:
        with self.engine.begin() as connection:
            return self._act_in_transaction(
                connection, context, project_id, reservation_id, command
            )

    def _act_in_transaction(
        self,
        connection: Connection,
        context: AuthContext,
        project_id: UUID,
        reservation_id: UUID,
        command: ReservationAction,
    ) -> dict[str, Any]:
        project = _project(connection, context, project_id, write=True)
        connection.execute(select(func.cehub_project.lock_resource_inventory(context.tenant.id)))
        table = tables.resource_reservations
        row = (
            connection.execute(
                select(table).where(
                    table.c.tenant_id == context.tenant.id,
                    table.c.project_id == project_id,
                    table.c.id == reservation_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ProductWorkAccessError("预约不存在或不属于当前项目")
        admin = is_allowed(context.user.role, Action.TENANT_MANAGE)
        if command.action == "reserve" and not admin:
            raise ProductWorkAccessError("由资源管理员确认正式预约")
        if command.action != "reserve" and not admin and context.user.id != row["owner_user_id"]:
            raise ProductWorkAccessError("由预约负责人或资源管理员取消和释放")
        resource = (
            connection.execute(
                select(tables.planning_resources)
                .where(
                    tables.planning_resources.c.tenant_id == context.tenant.id,
                    tables.planning_resources.c.id == row["resource_id"],
                )
                .with_for_update()
            )
            .mappings()
            .one()
        )
        row = (
            connection.execute(
                select(table)
                .where(table.c.tenant_id == context.tenant.id, table.c.id == reservation_id)
                .with_for_update()
            )
            .mappings()
            .one()
        )
        fingerprint = digest(
            {"reservation_id": str(reservation_id), **command.model_dump(mode="json")}
        )
        previous = _receipt(connection, context, project_id, command.request_id, fingerprint)
        if previous:
            return _record(previous["snapshot"])
        if digest(_plain(row)) != command.expected_digest:
            raise ProductWorkError("预约已有新版本，请刷新")
        allowed = {
            "reserve": {"proposed"},
            "cancel": {"proposed", "reserved"},
            "release": {"reserved"},
        }
        if row["state"] not in allowed[command.action]:
            raise ProductWorkError("当前预约状态不支持此操作")
        now = datetime.now(UTC)
        receipt_id = uuid4()
        changes = {
            "state": {"reserve": "reserved", "cancel": "cancelled", "release": "released"}[
                command.action
            ],
            "version": row["version"] + 1,
        }
        priority_review = None
        if command.action == "reserve":
            from app.domain.resource_priorities import confirm

            priority_review = confirm(connection, context, row)
            if project["status"] not in ("approved", "active"):
                raise ProductWorkError("项目执行批准后才能确认正式预约")
            if row["window_end"] <= now:
                raise ProductWorkError("预约窗口已结束，请重新提出预约")
            from app.domain.schedule_nodes import require_reservable_node

            require_reservable_node(connection, context, project_id, row["node_id"])
            if (
                resource["user_id"]
                and connection.execute(
                    select(tables.users.c.id).where(
                        tables.users.c.tenant_id == context.tenant.id,
                        tables.users.c.id == resource["user_id"],
                        tables.users.c.is_active.is_(True),
                    )
                ).first()
                is None
            ):
                raise ProductWorkError("资源人员已失效")
            if legacy_inventory_missing(connection, context, resource):
                raise ProductWorkError("存在尚未归并的旧资源占用，须先完成资源盘点")
            if (
                connection.execute(
                    select(tables.resource_capacity_intervals.c.start)
                    .where(
                        tables.resource_capacity_intervals.c.tenant_id == context.tenant.id,
                        tables.resource_capacity_intervals.c.capacity_version_id
                        == row["capacity_version_id"],
                    )
                    .limit(1)
                ).first()
                is None
            ):
                raise ProductWorkError("此旧容量版本缺少可预约时段，请发布新容量后重新提出预约")
            approval = ApprovalRef(
                approval_id=receipt_id,
                payload_digest=command.expected_digest,
                policy_version=row["contract"]["priority_policy_version"],
                approved_by_user_id=context.user.id,
                approved_at=now,
            )
            changes.update(
                approval=approval.model_dump(mode="json"),
                reservation_receipt_id=str(receipt_id),
                reserved_at=now.isoformat(),
            )
        else:
            changes.update(released_at=now.isoformat(), release_reason=command.reason)
        contract = ResourceReservation.model_validate({**row["contract"], **changes})
        updated = (
            connection.execute(
                table.update()
                .where(table.c.tenant_id == context.tenant.id, table.c.id == reservation_id)
                .values(
                    state=contract.state,
                    version=contract.version,
                    contract=contract.model_dump(mode="json"),
                    updated_at=now,
                )
                .returning(table)
            )
            .mappings()
            .one()
        )
        _write_receipt(
            connection,
            context,
            updated,
            receipt_id,
            command.request_id,
            fingerprint,
            command.reason,
            priority_review=priority_review,
        )
        return _record(updated)

    def history(
        self, context: AuthContext, project_id: UUID, reservation_id: UUID
    ) -> dict[str, Any]:
        with self.engine.connect() as connection:
            _project(connection, context, project_id)
            table = tables.resource_reservation_receipts
            rows = list(
                connection.execute(
                    select(table)
                    .where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.project_id == project_id,
                        table.c.reservation_id == reservation_id,
                    )
                    .order_by(table.c.created_at, table.c.id)
                ).mappings()
            )
            return {"items": [_plain(row) for row in rows]}
