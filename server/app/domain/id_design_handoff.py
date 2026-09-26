"""Fixed ID deliverables with independent receiver-owned, item-by-item acceptance."""

from datetime import UTC, datetime
from typing import Any, Literal, Self
from uuid import UUID, uuid4, uuid5

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import Contract, Digest, Key, Text
from app.db.schema import tables
from app.domain.formal_schedule import current_plan
from app.domain.id_design import _event, _get, _prior
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _plain,
    _role,
    digest,
)
from app.domain.project_execution import _person
from app.domain.resource_reservations import _project


class IdHandoffResidual(Contract):
    description: Text
    owner_user_id: UUID
    due_at: AwareDatetime


class IdHandoffItem(Contract):
    item_key: Key
    title: Text
    criteria: Text
    document_id: UUID
    residuals: tuple[IdHandoffResidual, ...] = Field(default=(), max_length=20)


class IdHandoffSubmit(Contract):
    request_id: UUID
    freeze_id: UUID
    target_node_id: UUID
    expected_target_digest: Digest
    receiver_user_id: UUID
    expected_previous_handoff_id: UUID | None = None
    receiver_renewal_digest: Digest | None = None
    items: tuple[IdHandoffItem, ...] = Field(min_length=1, max_length=30)
    reason: Text

    @model_validator(mode="after")
    def unique_items(self) -> Self:
        if len({item.item_key for item in self.items}) != len(self.items):
            raise ValueError("交接条目编号不能重复")
        if self.receiver_renewal_digest and self.expected_previous_handoff_id is None:
            raise ValueError("调整接收人须对应原交接轮次")
        return self


class IdHandoffResponse(Contract):
    request_id: UUID
    expected_digest: Digest
    action: Literal["accept", "return"]
    reason: Text


def target_options(
    connection: Connection, context: AuthContext, project_id: UUID
) -> list[dict[str, Any]]:
    formal = current_plan(connection, context.tenant.id, project_id)
    if formal is None:
        return []
    plans = {node["node_key"]: node for node in formal["plan"]["nodes"]}
    options = []
    for row in formal["nodes"]:
        node = plans[row["node_key"]]
        from app.domain.id_handoff_runtime import target_basis

        basis = target_basis(row["id"], node)
        options.append(
            {
                **basis,
                "target_digest": digest(basis),
                "baseline_id": str(formal["baseline_id"]),
                "baseline_version": formal["baseline_version"],
            }
        )
    return options


def _responses(
    connection: Connection, context: AuthContext, project_id: UUID, handoff_id: UUID
) -> list[Any]:
    i, r = tables.id_design_handoff_items, tables.id_design_handoff_responses
    return list(
        connection.execute(
            select(r)
            .join(
                i,
                (r.c.item_id == i.c.id)
                & (r.c.tenant_id == i.c.tenant_id)
                & (r.c.project_id == i.c.project_id),
            )
            .where(
                r.c.tenant_id == context.tenant.id,
                r.c.project_id == project_id,
                i.c.handoff_id == handoff_id,
            )
        ).mappings()
    )


class IdDesignHandoffService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(self, context: AuthContext, project_id: UUID) -> dict[str, Any]:
        _role(context, Action.PRODUCT_ENGINEERING_VIEW)
        with self.engine.connect() as connection:
            project = _project(connection, context, project_id)
            data: dict[str, Any] = {"targets": target_options(connection, context, project_id)}
            for key, table in [
                ("handoffs", tables.id_design_handoffs),
                ("items", tables.id_design_handoff_items),
                ("responses", tables.id_design_handoff_responses),
            ]:
                data[key] = [
                    _plain(row)
                    for row in connection.execute(
                        select(table)
                        .where(
                            table.c.tenant_id == context.tenant.id, table.c.project_id == project_id
                        )
                        .order_by(table.c.created_at, table.c.id)
                    ).mappings()
                ]
            from app.domain.id_handoff_runtime import acceptance_conditions

            live = {
                entry["handoff_id"]: entry
                for entries in acceptance_conditions(
                    connection,
                    context.tenant.id,
                    project_id,
                    current_plan(connection, context.tenant.id, project_id),
                ).values()
                for entry in entries
            }
            from app.domain.id_design_activation import active_freeze_ids

            active = active_freeze_ids(connection, context.tenant.id, project_id)
            data["active_freeze_ids"] = [str(value) for value in active]
            q = tables.id_design_reacceptance_requirements
            data["reacceptance_requirements"] = [
                _plain(row)
                for row in connection.execute(
                    select(q).where(
                        q.c.tenant_id == context.tenant.id,
                        q.c.project_id == project_id,
                        q.c.freeze_id.in_(active),
                    )
                ).mappings()
            ]
            current_targets = {row["node_id"]: row for row in data["targets"]}
            superseded = {
                row["previous_handoff_id"] for row in data["handoffs"] if row["previous_handoff_id"]
            }
            for handoff in data["handoffs"]:
                items = [row for row in data["items"] if row["handoff_id"] == handoff["id"]]
                item_ids = {row["id"] for row in items}
                responses = [row for row in data["responses"] if row["item_id"] in item_ids]
                handoff["status"] = (
                    "returned"
                    if any(row["action"] == "return" for row in responses)
                    else "accepted"
                    if len(responses) == len(items) and items
                    else "submitted"
                )
                target = current_targets.get(handoff["target_node_id"])
                handoff["current"] = bool(
                    target
                    and target["target_digest"] == handoff["snapshot"]["target"]["target_digest"]
                )
                if handoff["id"] in live:
                    handoff["current"] = live[handoff["id"]]["basis_current"]
                    handoff["basis_reason"] = live[handoff["id"]]["basis_reason"]
                handoff["replacement_handoff_id"] = next(
                    (
                        row["id"]
                        for row in data["handoffs"]
                        if row["previous_handoff_id"] == handoff["id"]
                    ),
                    None,
                )
                handoff["superseded"] = (
                    handoff["id"] in superseded or UUID(handoff["freeze_id"]) not in active
                )
            data["can_submit"] = is_allowed(
                context.user.role, Action.PRODUCT_ENGINEERING_EDIT
            ) and project["status"] in ("approved", "active", "on_hold")
            data["can_respond"] = is_allowed(context.user.role, Action.WORK_ITEM_EDIT) and project[
                "status"
            ] in ("approved", "active", "on_hold")
            return data

    def submit(
        self, context: AuthContext, project_id: UUID, command: IdHandoffSubmit
    ) -> dict[str, Any]:
        _role(context, Action.PRODUCT_ENGINEERING_EDIT)
        signing = command.model_dump(mode="json")
        if "receiver_renewal_digest" not in command.model_fields_set:
            signing.pop("receiver_renewal_digest")
        fingerprint = digest({"project_id": str(project_id), **signing})
        with self.engine.begin() as connection:
            project = _project(connection, context, project_id, write=True)
            _person(connection, context, project_id, context.user.id)
            table = tables.id_design_handoffs
            prior = _prior(connection, context, table, command.request_id, fingerprint)
            if prior:
                return _plain(prior)
            if project["status"] not in ("approved", "active", "on_hold"):
                raise ProductWorkError("当前项目状态不能提交交接")
            freeze = _get(
                connection, context, project_id, tables.id_design_freezes, command.freeze_id
            )
            from app.domain.id_design_activation import active_freeze_ids

            if freeze["id"] not in active_freeze_ids(connection, context.tenant.id, project_id):
                raise ProductWorkError("该冻结版本未启用或已被替代，不能提交新的交接")
            revision = _get(
                connection, context, project_id, tables.id_design_revisions, freeze["revision_id"]
            )
            if revision["owner_user_id"] != context.user.id and not is_allowed(
                context.user.role, Action.PROJECT_EDIT
            ):
                raise ProductWorkAccessError("仅冻结设计负责人或项目管理人员可提交交接")
            _person(connection, context, project_id, command.receiver_user_id)
            if command.receiver_user_id == context.user.id:
                raise ProductWorkError("交付与接收须由不同人员办理")
            target = next(
                (
                    row
                    for row in target_options(connection, context, project_id)
                    if row["node_id"] == str(command.target_node_id)
                ),
                None,
            )
            if target is None or target["target_digest"] != command.expected_target_digest:
                raise ProductWorkError("下游正式节点或责任已变化，请刷新交接依据")
            if str(command.receiver_user_id) not in (
                target["owner_user_id"],
                target["receiver_user_id"],
            ):
                raise ProductWorkError("接收人须为下游正式节点的责任人或接收人")
            previous = (
                connection.execute(
                    select(table)
                    .where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.project_id == project_id,
                        table.c.freeze_id == command.freeze_id,
                        table.c.target_node_id == command.target_node_id,
                    )
                    .order_by(table.c.version.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if (previous["id"] if previous else None) != command.expected_previous_handoff_id:
                raise ProductWorkError("交接轮次已变化，请刷新")
            previous_current = True
            if previous:
                from app.domain.id_handoff_runtime import acceptance_conditions

                conditions = acceptance_conditions(
                    connection,
                    context.tenant.id,
                    project_id,
                    current_plan(connection, context.tenant.id, project_id),
                )
                previous_current = next(
                    entry["basis_current"]
                    for entry in conditions[command.target_node_id]
                    if entry["handoff_id"] == str(previous["id"])
                )
            if (
                previous
                and not command.receiver_renewal_digest
                and previous_current
                and previous["snapshot"]["target"]["target_digest"] == target["target_digest"]
                and not any(
                    row["action"] == "return"
                    for row in _responses(connection, context, project_id, previous["id"])
                )
            ):
                raise ProductWorkError("当前交接尚未退回；请先由接收人说明缺项")
            item_values = []
            for item in command.items:
                document = _get(connection, context, project_id, tables.documents, item.document_id)
                for residual in item.residuals:
                    _person(connection, context, project_id, residual.owner_user_id)
                    if residual.due_at <= datetime.now(UTC):
                        raise ProductWorkError("遗留项须明确有效责任人及后续处理期限")
                item_values.append(
                    {
                        **item.model_dump(mode="json"),
                        "artifact_snapshot": {
                            key: str(document[key]) for key in ("id", "filename", "sha256")
                        },
                    }
                )
            snapshot = {
                "freeze": _plain(freeze),
                "revision": _plain(revision),
                "target": target,
                "items": item_values,
                "receiver_user_id": str(command.receiver_user_id),
            }
            if command.receiver_renewal_digest:
                if (
                    previous is None
                    or previous["payload_digest"] != command.receiver_renewal_digest
                ):
                    raise ProductWorkError("原交接内容已变化，请刷新后重新核对")
                responses = _responses(connection, context, project_id, previous["id"])
                if any(row["action"] == "return" for row in responses) or len(responses) >= len(
                    previous["snapshot"]["items"]
                ):
                    raise ProductWorkError("仅可接续尚未全部接收且未退回的交接；已退回请完整补齐")
                if previous["receiver_user_id"] == command.receiver_user_id:
                    raise ProductWorkError("请选择另一位当前正式节点的有效接收人")
                if (
                    any(
                        digest(snapshot.get(key)) != digest(previous["snapshot"].get(key))
                        for key in ("freeze", "revision", "items")
                    )
                    or target["target_digest"] != previous["snapshot"]["target"]["target_digest"]
                ):
                    raise ProductWorkError(
                        "原交付、证据或下游责任已有变化，请按当前安排完整重新交接"
                    )
                u = tables.users
                names = {
                    str(row.id): row.display_name
                    for row in connection.execute(
                        select(u.c.id, u.c.display_name).where(
                            u.c.tenant_id == context.tenant.id,
                            u.c.id.in_(
                                [
                                    context.user.id,
                                    previous["receiver_user_id"],
                                    command.receiver_user_id,
                                ]
                            ),
                        )
                    )
                }
                snapshot["receiver_renewal"] = {
                    "previous_handoff_id": str(previous["id"]),
                    "previous_digest": previous["payload_digest"],
                    "previous_receiver_user_id": str(previous["receiver_user_id"]),
                    "previous_receiver_name": names[str(previous["receiver_user_id"])],
                    "receiver_name": names[str(command.receiver_user_id)],
                    "actor_user_id": str(context.user.id),
                    "actor_name": names[str(context.user.id)],
                    "reason": command.reason,
                }
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        freeze_id=command.freeze_id,
                        target_node_id=command.target_node_id,
                        receiver_user_id=command.receiver_user_id,
                        previous_handoff_id=command.expected_previous_handoff_id,
                        version=(previous["version"] if previous else 0) + 1,
                        snapshot=snapshot,
                        payload_digest=digest(snapshot),
                        reason=command.reason,
                        created_by_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=fingerprint,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            for item_value in item_values:
                values = {**item_value, "document_id": UUID(item_value["document_id"])}
                connection.execute(
                    tables.id_design_handoff_items.insert().values(
                        **values,
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        handoff_id=row["id"],
                        created_by_user_id=context.user.id,
                        request_id=uuid5(command.request_id, item_value["item_key"]),
                        request_digest=digest(item_value),
                    )
                )
            _event(connection, context, project_id, row["id"], "handoff_submitted", _plain(row))
            from app.domain.schedule_forecasts import automatic_forecast

            automatic_forecast(
                connection,
                context.tenant.id,
                project_id,
                context.user.id,
                "ID交接提交后更新接收条件",
                datetime.now(UTC),
            )
            return _plain(row)

    def respond(
        self, context: AuthContext, project_id: UUID, item_id: UUID, command: IdHandoffResponse
    ) -> dict[str, Any]:
        _role(context, Action.WORK_ITEM_EDIT)
        fingerprint = digest(
            {
                "project_id": str(project_id),
                "item_id": str(item_id),
                **command.model_dump(mode="json"),
            }
        )
        with self.engine.begin() as connection:
            project = _project(connection, context, project_id, write=True)
            _person(connection, context, project_id, context.user.id)
            table = tables.id_design_handoff_responses
            prior = _prior(connection, context, table, command.request_id, fingerprint)
            if prior:
                return _plain(prior)
            if project["status"] not in ("approved", "active", "on_hold"):
                raise ProductWorkError("当前项目状态不能办理交接")
            item = _get(connection, context, project_id, tables.id_design_handoff_items, item_id)
            handoff = _get(
                connection, context, project_id, tables.id_design_handoffs, item["handoff_id"]
            )
            from app.domain.id_design_activation import active_freeze_ids

            if handoff["freeze_id"] not in active_freeze_ids(
                connection, context.tenant.id, project_id
            ):
                raise ProductWorkError("此交接对应的设计已被替代，请办理新版本交接")
            if handoff["receiver_user_id"] != context.user.id:
                raise ProductWorkAccessError("仅具名接收人可逐项验收或退回")
            if handoff["payload_digest"] != command.expected_digest:
                raise ProductWorkError("接收依据与提交版本不一致")
            h = tables.id_design_handoffs
            if connection.execute(
                select(h.c.id).where(
                    h.c.tenant_id == context.tenant.id,
                    h.c.project_id == project_id,
                    h.c.previous_handoff_id == handoff["id"],
                )
            ).first():
                raise ProductWorkError("已有新一轮交接，请按当前版本办理")
            responses = _responses(connection, context, project_id, handoff["id"])
            if any(row["item_id"] == item_id or row["action"] == "return" for row in responses):
                raise ProductWorkError("条目已办理或交接已退回，请查看最新轮次")
            if command.action == "accept":
                target = next(
                    (
                        row
                        for row in target_options(connection, context, project_id)
                        if row["node_id"] == str(handoff["target_node_id"])
                    ),
                    None,
                )
                if (
                    target is None
                    or target["target_digest"] != handoff["snapshot"]["target"]["target_digest"]
                ):
                    raise ProductWorkError("正式下游节点或责任已变化，请退回重新提交")
                document = _get(
                    connection, context, project_id, tables.documents, item["document_id"]
                )
                if document["sha256"] != item["artifact_snapshot"]["sha256"]:
                    raise ProductWorkError("交付证据已变化，请退回补齐")
                for residual in item["residuals"]:
                    _person(connection, context, project_id, UUID(residual["owner_user_id"]))
                    if datetime.fromisoformat(residual["due_at"]) <= datetime.now(UTC):
                        raise ProductWorkError("遗留项期限已过，请退回重新安排")
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        item_id=item_id,
                        action=command.action,
                        accepted_digest=command.expected_digest,
                        reason=command.reason,
                        created_by_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=fingerprint,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            _event(
                connection,
                context,
                project_id,
                row["id"],
                "handoff_item_accepted" if command.action == "accept" else "handoff_item_returned",
                _plain(row),
            )
            from app.domain.schedule_forecasts import automatic_forecast

            if current_plan(connection, context.tenant.id, project_id) is not None:
                automatic_forecast(
                    connection,
                    context.tenant.id,
                    project_id,
                    context.user.id,
                    "ID交接办理后更新接收条件",
                    datetime.now(UTC),
                )
            return _plain(row)
