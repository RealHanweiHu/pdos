"""Bilateral approval of pinned cross-project schedule proposals."""

import contextlib
from decimal import Decimal
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, or_, select, true

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.baseline_changes import BaselineDecision, latest_policy
from app.domain.formal_schedule import current_plan
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _plain,
    _role,
    digest,
)
from app.domain.project_execution import _person
from app.domain.resource_reservations import _project
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

SIDES = ("predecessor", "successor")


class CrossProjectProposal(Contract):
    request_id: UUID
    predecessor_project_id: UUID
    successor_project_id: UUID
    predecessor_node_id: UUID
    successor_node_id: UUID
    predecessor_digest: Digest
    successor_digest: Digest
    relation: Literal["fs", "ss", "ff", "sf"]
    lag: Decimal = Field(max_digits=24, decimal_places=8, allow_inf_nan=False)
    lag_unit: Literal["working_hours", "calendar_days"]
    reason: Text
    operation: Literal["add", "remove", "replace"] = "add"
    target_application_id: UUID | None = None

    @model_validator(mode="after")
    def distinct_projects(self) -> Self:
        if self.predecessor_project_id == self.successor_project_id:
            raise ValueError("跨项目依赖必须连接两个不同项目")
        if (self.operation != "add") != (self.target_application_id is not None):
            raise ValueError("解除或转接申请必须绑定当前有效关系；新增申请不能指定目标")
        return self


def endpoint(connection: Connection, context: AuthContext, project_id: UUID) -> dict[str, Any]:
    project = _project(connection, context, project_id)
    return _endpoint_basis(connection, context, project_id, project)


def _endpoint_basis(
    connection: Connection, context: AuthContext, project_id: UUID, project: Any
) -> dict[str, Any]:
    """Internal facts used only after normal access or an exact proposal share is established."""
    formal = current_plan(connection, context.tenant.id, project_id)
    policy = latest_policy(connection, context.tenant.id, project_id)
    approver = None
    if policy:
        with contextlib.suppress(ProductWorkError):
            approver = _plain(_person(connection, context, project_id, policy["approver_user_id"]))
    plan_nodes = {node["node_key"]: node for node in formal["plan"]["nodes"]} if formal else {}
    allocations = formal["allocations"] if formal else {}
    value = {
        "project_id": str(project_id),
        "project_name": project["name"],
        "baseline_id": str(formal["baseline_id"]) if formal else None,
        "baseline_version": formal["baseline_version"] if formal else None,
        "policy": _plain(policy) if policy else None,
        "approver": approver,
        "nodes": [
            {
                "id": str(node["id"]),
                "title": plan_nodes[node["node_key"]]["title"],
                "kind": node["node_kind"],
                "calendar_version_id": allocations[node["node_key"]]["calendar_version_id"],
            }
            for node in (formal["nodes"] if formal else [])
        ],
    }
    # Only fixed scheduling and authority facts are part of the reviewed basis.
    value = _plain(value)
    return {
        **value,
        "payload_digest": digest(value),
        "project_status": project["status"],
        "ready": bool(
            formal
            and policy
            and approver
            and project["status"] in ("approved", "active", "on_hold")
        ),
    }


def _shared_reader(
    connection: Connection, context: AuthContext, project_id: UUID, row: Any
) -> bool:
    sharing = row["snapshot"].get("sharing", {})
    if sharing.get("version") != "cross_schedule_approval.v1":
        return False
    side = next((side for side in SIDES if row[f"{side}_project_id"] == project_id), None)
    if side is None or row["snapshot"][side]["policy"]["approver_user_id"] != str(context.user.id):
        return False
    if {"project_id": str(project_id), "approver_user_id": str(context.user.id)} not in sharing.get(
        "audience", []
    ):
        return False
    try:
        _person(connection, context, project_id, context.user.id)
    except ProductWorkError:
        return False
    return True


def _shared_endpoint(
    connection: Connection, context: AuthContext, project_id: UUID
) -> dict[str, Any]:
    project = (
        connection.execute(
            select(tables.projects).where(
                tables.projects.c.tenant_id == context.tenant.id, tables.projects.c.id == project_id
            )
        )
        .mappings()
        .one()
    )
    return _endpoint_basis(connection, context, project_id, project)


def _public_proposal(row: Any, *, limited: bool) -> dict[str, Any]:
    value = _plain(row)
    if not limited:
        return value
    # This is a share of the submitted relation, never a partner project or current node list.
    value = {
        key: value[key]
        for key in (
            "id",
            "operation",
            "target_application_id",
            "relation",
            "lag",
            "lag_unit",
            "reason",
            "payload_digest",
            "created_at",
        )
    }
    snapshot = row["snapshot"]
    value["snapshot"] = {
        key: snapshot[key]
        for key in ("operation", "target_application_id", "relation", "lag", "lag_unit", "reason")
    }
    if snapshot.get("previous_relation"):
        value["snapshot"]["previous_relation"] = snapshot["previous_relation"]
    for side in SIDES:
        source = snapshot[side]
        value["snapshot"][side] = {
            **{
                key: source[key]
                for key in ("project_id", "project_name", "baseline_id", "baseline_version", "node")
            },
            "policy": {
                key: source["policy"][key]
                for key in ("id", "version", "approver_user_id", "authority_basis", "four_eyes")
            },
            "approver": {key: source["approver"][key] for key in ("id", "display_name")}
            if source["approver"]
            else None,
        }
    return value


def _decisions(connection: Connection, context: AuthContext, proposal_id: UUID) -> list[Any]:
    table = tables.cross_project_schedule_decisions
    return list(
        connection.execute(
            select(table)
            .where(table.c.tenant_id == context.tenant.id, table.c.proposal_id == proposal_id)
            .order_by(table.c.created_at, table.c.id)
        ).mappings()
    )


def _event(
    connection: Connection,
    context: AuthContext,
    project_id: UUID,
    record_id: UUID,
    action: str,
    snapshot: dict[str, Any],
) -> None:
    EventAuditWriter(
        connection,
        tenant_id=context.tenant.id,
        actor_user_id=context.user.id,
        project_id=project_id,
    ).record(
        EventDraft(
            event_id=f"cross-schedule:{record_id}:{action}:{uuid4()}",
            event_type="CROSS_PROJECT_SCHEDULE_RECORDED",
            source="planning_service",
            entity_id=record_id,
            payload={"record_id": str(record_id), "action": action},
        ),
        AuditDraft(
            action=f"cross_project_schedule.{action}",
            after_snapshot={
                "record_id": str(record_id),
                "action": action,
                "payload_digest": snapshot.get(
                    "payload_digest", snapshot.get("approved_payload_digest")
                ),
                "decision_id": snapshot["id"] if action not in ("prepare", "application") else None,
                "application_id": snapshot["id"] if action == "application" else None,
            },
        ),
    )


def _pair(connection: Connection, context: AuthContext, row: Any, *, write: bool = False) -> None:
    for project_id in sorted({row[f"{side}_project_id"] for side in SIDES}, key=str):
        _project(connection, context, project_id, write=write)
        if write:
            _person(connection, context, project_id, context.user.id)


class CrossProjectScheduleService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(
        self, context: AuthContext, project_id: UUID, *, proposal_id: UUID | None = None
    ) -> dict[str, Any]:
        with self.engine.connect() as connection:
            own = endpoint(connection, context, project_id)
            table = tables.cross_project_schedule_proposals
            rows = (
                connection.execute(
                    select(table)
                    .where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.id == proposal_id if proposal_id is not None else true(),
                        or_(
                            table.c.predecessor_project_id == project_id,
                            table.c.successor_project_id == project_id,
                        ),
                    )
                    .order_by(table.c.created_at.desc(), table.c.id)
                    .limit(201)
                )
                .mappings()
                .all()
            )
            from app.domain.cross_project_schedule_runtime import application_heads

            active = application_heads(connection, context.tenant.id)
            apps = tables.cross_project_schedule_applications
            applications = {
                row["proposal_id"]: row
                for row in connection.execute(
                    select(apps).where(
                        apps.c.tenant_id == context.tenant.id,
                        apps.c.proposal_id.in_([row["id"] for row in rows]),
                    )
                ).mappings()
            }
            items = []
            endpoints = {project_id: own}
            for row in rows[:200]:
                limited = False
                try:
                    _pair(connection, context, row)
                except ProductWorkAccessError:
                    if not _shared_reader(connection, context, project_id, row):
                        continue
                    limited = True
                for side in SIDES:
                    pid = row[f"{side}_project_id"]
                    if pid not in endpoints:
                        endpoints[pid] = (
                            _shared_endpoint(connection, context, pid)
                            if limited
                            else endpoint(connection, context, pid)
                        )
                current = all(
                    endpoints[row[f"{side}_project_id"]]["payload_digest"]
                    == row["snapshot"][side]["endpoint_digest"]
                    for side in SIDES
                )
                decisions = _decisions(connection, context, row["id"])
                status = "pending"
                if any(d["action"] in ("reject", "withdraw") for d in decisions):
                    status = "closed"
                elif len(decisions) == 2:
                    status = "approved_pending_application"
                application = applications.get(row["id"])
                active_relation = next(
                    (
                        app
                        for app in active
                        if app["predecessor_node_id"] == row["predecessor_node_id"]
                        and app["successor_node_id"] == row["successor_node_id"]
                        and app["relation"] == row["relation"]
                    ),
                    None,
                )
                target_relation = next(
                    (
                        app
                        for app in active
                        if app["id"] == row["target_application_id"]
                        and app["operation"] != "remove"
                    ),
                    None,
                )
                destination_relation = (
                    active_relation
                    if active_relation
                    and (not target_relation or active_relation["id"] != target_relation["id"])
                    else None
                )
                if row["operation"] != "add" and not application:
                    current = current and target_relation is not None
                    if row["operation"] == "replace":
                        current = (
                            current
                            and (destination_relation["id"] if destination_relation else None)
                            == row["destination_application_id"]
                        )
                if application:
                    current = all(
                        endpoints[row[f"{side}_project_id"]]["baseline_id"]
                        == str(row[f"{side}_baseline_id"])
                        and any(
                            node["id"] == str(row[f"{side}_node_id"])
                            for node in endpoints[row[f"{side}_project_id"]]["nodes"]
                        )
                        for side in SIDES
                    )
                    status = (
                        ("removed" if application["operation"] == "remove" else "applied")
                        if active_relation and active_relation["id"] == application["id"]
                        else "superseded"
                    )
                own_side = next(side for side in SIDES if row[f"{side}_project_id"] == project_id)
                policy = own["policy"]
                undecided = (
                    not any(d["project_id"] == project_id for d in decisions)
                    and status == "pending"
                )
                can_decide = bool(
                    undecided
                    and policy
                    and str(row[f"{own_side}_policy_id"]) == policy["id"]
                    and policy["approver_user_id"] == str(context.user.id)
                    and (not policy["four_eyes"] or row["created_by_user_id"] != context.user.id)
                )
                items.append(
                    {
                        **_public_proposal(row, limited=limited),
                        "access_mode": "proposal_only" if limited else "both_projects",
                        "decisions": [
                            {
                                key: _plain(d)[key]
                                for key in (
                                    "id",
                                    "project_id",
                                    "action",
                                    "actor_user_id",
                                    "reason",
                                    "created_at",
                                )
                            }
                            for d in decisions
                        ],
                        "status": status,
                        "application": {
                            key: _plain(application)[key]
                            for key in ("id", "created_at", "reason", "replaces_application_id")
                        }
                        if application
                        else None,
                        "can_request_removal": not limited
                        and status == "applied"
                        and is_allowed(context.user.role, Action.PROJECT_EDIT),
                        "current_relation_application_id": str(row["target_application_id"])
                        if row["operation"] == "replace"
                        else str(active_relation["id"])
                        if active_relation
                        else None,
                        "destination_application_id": str(row["destination_application_id"])
                        if row["destination_application_id"]
                        else None,
                        "can_apply": not limited
                        and status == "approved_pending_application"
                        and current
                        and is_allowed(context.user.role, Action.PROJECT_EDIT)
                        and all(endpoints[row[f"{side}_project_id"]]["ready"] for side in SIDES),
                        "is_current": current,
                        "can_decide": can_decide,
                        "can_approve": can_decide
                        and current
                        and all(endpoints[row[f"{side}_project_id"]]["ready"] for side in SIDES),
                        "can_withdraw": not limited
                        and not decisions
                        and row["created_by_user_id"] == context.user.id,
                    }
                )
            return {
                "endpoint": own,
                "items": items,
                "has_more": len(rows) > 200,
                "can_prepare": is_allowed(context.user.role, Action.PROJECT_EDIT),
            }

    def prepare(
        self, context: AuthContext, project_id: UUID, command: CrossProjectProposal
    ) -> dict[str, Any]:
        _role(context, Action.PROJECT_EDIT)
        values = command.model_dump()
        if project_id not in (command.predecessor_project_id, command.successor_project_id):
            raise ProductWorkAccessError("申请必须包含当前项目")
        fingerprint = digest(
            {"project_id": str(project_id), "command": command.model_dump(mode="json")}
        )
        with self.engine.begin() as connection:
            _pair(connection, context, values, write=True)
            table = tables.cross_project_schedule_proposals
            prior = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.created_by_user_id == context.user.id,
                        table.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != fingerprint:
                    raise ProductWorkError("请求编号已用于另一项跨项目申请")
                return _plain(prior)
            target = original = destination = None
            if command.operation != "add":
                from app.domain.cross_project_schedule_runtime import application_heads

                heads = application_heads(connection, context.tenant.id)
                target = next(
                    (
                        app
                        for app in heads
                        if app["id"] == command.target_application_id
                        and app["operation"] != "remove"
                    ),
                    None,
                )
                if target is None or {
                    target["predecessor_project_id"],
                    target["successor_project_id"],
                } != {command.predecessor_project_id, command.successor_project_id}:
                    raise ProductWorkError("原关系已变化，或新旧关系不属于同一对项目")
                original = (
                    connection.execute(
                        select(table).where(
                            table.c.tenant_id == context.tenant.id,
                            table.c.id == target["proposal_id"],
                        )
                    )
                    .mappings()
                    .one()
                )
                if command.operation == "remove" and (
                    any(
                        target[key] != values[key]
                        for key in (
                            "predecessor_project_id",
                            "successor_project_id",
                            "predecessor_node_id",
                            "successor_node_id",
                            "relation",
                        )
                    )
                    or original["lag"] != command.lag
                    or original["lag_unit"] != command.lag_unit
                ):
                    raise ProductWorkError("解除申请须完整绑定原关系条件")
                if command.operation == "replace":
                    destination = next(
                        (
                            app
                            for app in heads
                            if app["id"] != target["id"]
                            and app["predecessor_node_id"] == command.predecessor_node_id
                            and app["successor_node_id"] == command.successor_node_id
                            and app["relation"] == command.relation
                        ),
                        None,
                    )
                    if destination and destination["operation"] != "remove":
                        raise ProductWorkError("目标关系已独立生效，请先处理重复关系")
            snapshot: dict[str, Any] = {
                "operation": command.operation,
                "destination_application_id": str(destination["id"]) if destination else None,
                "target_application_id": str(command.target_application_id)
                if command.target_application_id
                else None,
                "relation": command.relation,
                "lag": str(command.lag),
                "lag_unit": command.lag_unit,
                "reason": command.reason,
            }
            if target:
                assert original is not None
                snapshot["previous_relation"] = {
                    "application_id": str(target["id"]),
                    "proposal_id": str(original["id"]),
                    "relation": original["relation"],
                    "lag": str(original["lag"]),
                    "lag_unit": original["lag_unit"],
                    **{
                        side: {
                            key: original["snapshot"][side][key]
                            for key in (
                                "project_id",
                                "project_name",
                                "baseline_id",
                                "baseline_version",
                                "node",
                            )
                        }
                        for side in SIDES
                    },
                }
            pinned = {}
            for side in SIDES:
                ep = endpoint(connection, context, values[f"{side}_project_id"])
                if not ep["ready"] or ep["payload_digest"] != values[f"{side}_digest"]:
                    raise ProductWorkError("项目基线、节点或批准政策已变化或未就绪，请刷新两侧计划")
                node = next(
                    (n for n in ep["nodes"] if n["id"] == str(values[f"{side}_node_id"])), None
                )
                if node is None:
                    raise ProductWorkError("依赖节点必须属于当前正式基线")
                snapshot[side] = {
                    key: ep[key]
                    for key in (
                        "project_id",
                        "project_name",
                        "baseline_id",
                        "baseline_version",
                        "policy",
                        "approver",
                    )
                }
                snapshot[side].update(node=node, endpoint_digest=ep["payload_digest"])
                pinned[f"{side}_baseline_id"] = UUID(ep["baseline_id"])
                pinned[f"{side}_policy_id"] = UUID(ep["policy"]["id"])
            snapshot["sharing"] = {
                "version": "cross_schedule_approval.v1",
                "audience": [
                    {
                        "project_id": snapshot[side]["project_id"],
                        "approver_user_id": snapshot[side]["policy"]["approver_user_id"],
                    }
                    for side in SIDES
                ],
                "scope": "submitted_relation_nodes_baselines_named_authority_and_decisions",
            }
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        **{
                            key: values[key]
                            for key in (
                                "predecessor_project_id",
                                "successor_project_id",
                                "predecessor_node_id",
                                "successor_node_id",
                                "relation",
                                "lag",
                                "lag_unit",
                                "reason",
                                "request_id",
                            )
                        },
                        **pinned,
                        operation=command.operation,
                        target_application_id=command.target_application_id,
                        destination_application_id=destination["id"] if destination else None,
                        snapshot=snapshot,
                        payload_digest=digest(snapshot),
                        created_by_user_id=context.user.id,
                        request_digest=fingerprint,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            for side in SIDES:
                _event(
                    connection,
                    context,
                    values[f"{side}_project_id"],
                    row["id"],
                    "prepare",
                    _plain(row),
                )
            return _plain(row)

    def decide(
        self, context: AuthContext, project_id: UUID, proposal_id: UUID, command: BaselineDecision
    ) -> dict[str, Any]:
        with self.engine.begin() as connection:
            _project(connection, context, project_id)
            table = tables.cross_project_schedule_proposals
            row = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.id == proposal_id,
                        or_(
                            table.c.predecessor_project_id == project_id,
                            table.c.successor_project_id == project_id,
                        ),
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ProductWorkAccessError("申请不存在或不可访问")
            if command.action == "withdraw":
                _pair(connection, context, row, write=True)
            elif _shared_reader(connection, context, project_id, row):
                _role(context, Action.WORK_ITEM_EDIT)
                for pid in sorted(
                    (row["predecessor_project_id"], row["successor_project_id"]), key=str
                ):
                    connection.execute(
                        select(tables.projects.c.id)
                        .where(
                            tables.projects.c.tenant_id == context.tenant.id,
                            tables.projects.c.id == pid,
                        )
                        .with_for_update()
                    ).scalar_one()
                _person(connection, context, project_id, context.user.id)
            else:
                _pair(connection, context, row, write=True)
            decisions = tables.cross_project_schedule_decisions
            fingerprint = digest(
                {
                    "project_id": str(project_id),
                    "proposal_id": str(proposal_id),
                    "command": command.model_dump(mode="json"),
                }
            )
            prior = (
                connection.execute(
                    select(decisions).where(
                        decisions.c.tenant_id == context.tenant.id,
                        decisions.c.actor_user_id == context.user.id,
                        decisions.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != fingerprint:
                    raise ProductWorkError("请求编号已用于另一项确认")
                return _plain(prior)
            conclusions = _decisions(connection, context, proposal_id)
            if any(d["action"] != "approve" or d["project_id"] == project_id for d in conclusions):
                raise ProductWorkError("申请或当前一侧已有结论，请保留历史并重新申请")
            if command.expected_digest != row["payload_digest"]:
                raise ProductWorkError("申请与审阅版本不一致，请刷新")
            side = next(s for s in SIDES if row[f"{s}_project_id"] == project_id)
            policy = latest_policy(connection, context.tenant.id, project_id)
            if command.action == "withdraw":
                if conclusions or row["created_by_user_id"] != context.user.id:
                    raise ProductWorkAccessError("仅提交人可在双方尚未裁决时撤回")
            elif (
                policy is None
                or policy["id"] != row[f"{side}_policy_id"]
                or policy["approver_user_id"] != context.user.id
                or (policy["four_eyes"] and row["created_by_user_id"] == context.user.id)
            ):
                raise ProductWorkAccessError(
                    "仅当前政策中的具名批准人可办理，并须遵守提交与批准分人要求"
                )
            if command.action == "approve":
                if row["operation"] != "add":
                    from app.domain.cross_project_schedule_runtime import active_applications

                    if not any(
                        app["id"] == row["target_application_id"]
                        for app in active_applications(connection, context.tenant.id)
                    ):
                        raise ProductWorkError("原关系已变化，请重新准备申请")
                if row["operation"] == "replace":
                    from app.domain.cross_project_schedule_runtime import application_heads

                    destination = next(
                        (
                            head
                            for head in application_heads(connection, context.tenant.id)
                            if head["id"] != row["target_application_id"]
                            and head["predecessor_node_id"] == row["predecessor_node_id"]
                            and head["successor_node_id"] == row["successor_node_id"]
                            and head["relation"] == row["relation"]
                        ),
                        None,
                    )
                    if (destination["id"] if destination else None) != row[
                        "destination_application_id"
                    ] or (destination and destination["operation"] != "remove"):
                        raise ProductWorkError("转接目标历史已变化，请重新准备申请")
                for s in SIDES:
                    ep = _shared_endpoint(connection, context, row[f"{s}_project_id"])
                    if (
                        not ep["ready"]
                        or ep["payload_digest"] != row["snapshot"][s]["endpoint_digest"]
                    ):
                        raise ProductWorkError("任一侧基线或批准依据已变化，请重新准备申请")
            result = (
                connection.execute(
                    decisions.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        proposal_id=proposal_id,
                        project_id=project_id,
                        action=command.action,
                        actor_user_id=context.user.id,
                        approved_payload_digest=row["payload_digest"],
                        reason=command.reason,
                        request_id=command.request_id,
                        request_digest=fingerprint,
                    )
                    .returning(decisions)
                )
                .mappings()
                .one()
            )
            for s in SIDES:
                _event(
                    connection,
                    context,
                    row[f"{s}_project_id"],
                    proposal_id,
                    command.action,
                    _plain(result),
                )
            return _plain(result)
