"""Explicit ID freeze evidence bound to formal execution checkpoints."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.formal_schedule import current_plan, current_states
from app.domain.id_design import _event, _get, _prior
from app.domain.id_handoff_runtime import target_basis
from app.domain.product_workspace import ProductWorkError, _plain, _role, digest
from app.domain.project_execution import _person
from app.domain.resource_reservations import _project

# Stable key explicitly declared by the approved NPD templates, never inferred from a title.
REQUIRED_CHECKPOINT_KEYS = frozenset({"ID-FREEZE"})


class IdCheckpointBinding(Contract):
    request_id: UUID
    variant_id: UUID
    expected_target_digest: Digest
    expected_version: int = Field(ge=0)
    reason: Text


def latest_bindings(connection: Connection, tenant_id: UUID, project_id: UUID) -> dict[UUID, Any]:
    t = tables.id_design_checkpoint_bindings
    result: dict[UUID, Any] = {}
    for row in connection.execute(
        select(t)
        .where(t.c.tenant_id == tenant_id, t.c.project_id == project_id)
        .order_by(t.c.version.desc(), t.c.id)
    ).mappings():
        result.setdefault(row["node_id"], row)
    return result


def checkpoint_conditions(
    connection: Connection, tenant_id: UUID, project_id: UUID, formal: dict[str, Any] | None
) -> dict[UUID, list[dict[str, Any]]]:
    from app.domain.id_design_activation import active_freeze_ids, current_freeze_lineage

    bindings = latest_bindings(connection, tenant_id, project_id)
    if formal is None and not bindings:
        return {}
    by_key = {row["node_key"]: row for row in formal["plan"]["nodes"]} if formal else {}
    nodes = {row["id"]: row for row in formal["nodes"]} if formal else {}
    required = set(bindings) | {
        row["id"] for row in nodes.values() if row["node_key"] in REQUIRED_CHECKPOINT_KEYS
    }
    if not required:
        return {}
    f = tables.id_design_freezes
    freezes = {
        row["variant_id"]: row
        for row in connection.execute(
            select(f).where(f.c.tenant_id == tenant_id, f.c.project_id == project_id)
        ).mappings()
    }
    by_id = {row["id"]: row for row in freezes.values()}
    active = active_freeze_ids(connection, tenant_id, project_id)
    result: dict[UUID, Any] = {}
    for node_id in required:
        binding = bindings.get(node_id)
        node = nodes.get(node_id)
        reason = None
        frozen = None
        timestamp = None
        lineage: list[dict[str, Any]] = []
        if binding is None:
            reason = "ID冻结检查点尚未绑定实际设计方案"
        elif (
            node is None
            or digest(target_basis(node_id, by_key[node["node_key"]])) != binding["target_digest"]
        ):
            reason = "ID检查点或正式责任已变化，请重新确认方案绑定"
        else:
            original = freezes.get(binding["variant_id"])
            if original is None:
                reason = "绑定的ID方案尚未取得完整确认并冻结"
            else:
                leaf, lineage = current_freeze_lineage(
                    connection, tenant_id, project_id, original["id"]
                )
                frozen = by_id[leaf]
                if leaf not in active:
                    reason = "修订设计已冻结但尚未正式启用"
                else:
                    timestamp = max(
                        [
                            frozen["created_at"],
                            *[datetime.fromisoformat(row["created_at"]) for row in lineage],
                        ]
                    )
        result[node_id] = [
            {
                "kind": "id_freeze_checkpoint",
                "handoff_id": None,
                "target_point": "finish",
                "binding_id": str(binding["id"]) if binding else None,
                "version": binding["version"] if binding else 0,
                "freeze_id": str(frozen["id"]) if frozen else None,
                "activation_ids": [row["id"] for row in lineage],
                "accepted": reason is None,
                "accepted_at": timestamp.isoformat() if timestamp else None,
                "reason": reason,
            }
        ]
    return result


class IdDesignCheckpointService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(self, context: AuthContext, project_id: UUID) -> dict[str, Any]:
        _role(context, Action.PRODUCT_ENGINEERING_VIEW)
        with self.engine.connect() as connection:
            project = _project(connection, context, project_id)
            formal = current_plan(connection, context.tenant.id, project_id)
            if not formal:
                return {"items": [], "can_bind": False}
            bindings = latest_bindings(connection, context.tenant.id, project_id)
            conditions = checkpoint_conditions(connection, context.tenant.id, project_id, formal)
            by_key = {row["node_key"]: row for row in formal["plan"]["nodes"]}
            states, _ = current_states(connection, context.tenant.id, project_id, formal)
            states_by_node = {row["node_id"]: row for row in states}
            return {
                "can_bind": is_allowed(context.user.role, Action.PROJECT_EDIT)
                and project["status"] in ("approved", "active", "on_hold"),
                "items": [
                    {
                        "node_id": str(row["id"]),
                        "node_kind": row["node_kind"],
                        **target_basis(row["id"], by_key[row["node_key"]]),
                        "target_digest": digest(target_basis(row["id"], by_key[row["node_key"]])),
                        "required": row["node_key"] in REQUIRED_CHECKPOINT_KEYS,
                        "binding": _plain(bindings[row["id"]]) if row["id"] in bindings else None,
                        "conditions": conditions.get(row["id"], []),
                        "completed": bool(states_by_node[str(row["id"])].get("actual_finish"))
                        or states_by_node[str(row["id"])]["status"]
                        in ("done", "skipped", "completed"),
                    }
                    for row in formal["nodes"]
                    if row["node_kind"] in ("task", "milestone")
                ],
            }

    def bind(
        self, context: AuthContext, project_id: UUID, node_id: UUID, command: IdCheckpointBinding
    ) -> dict[str, Any]:
        _role(context, Action.PROJECT_EDIT)
        fingerprint = digest(
            {
                "project_id": str(project_id),
                "node_id": str(node_id),
                **command.model_dump(mode="json"),
            }
        )
        with self.engine.begin() as connection:
            project = _project(connection, context, project_id, write=True)
            _person(connection, context, project_id, context.user.id)
            t = tables.id_design_checkpoint_bindings
            prior = _prior(connection, context, t, command.request_id, fingerprint)
            if prior:
                return _plain(prior)
            if project["status"] not in ("approved", "active", "on_hold"):
                raise ProductWorkError("当前项目状态不能设置ID检查点")
            formal = current_plan(connection, context.tenant.id, project_id)
            node = (
                next((row for row in formal["nodes"] if row["id"] == node_id), None)
                if formal
                else None
            )
            if formal is None or not node or node["node_kind"] not in ("task", "milestone"):
                raise ProductWorkError("请选择正式计划中的Task或里程碑")
            plan_node = next(
                row for row in formal["plan"]["nodes"] if row["node_key"] == node["node_key"]
            )
            target = target_basis(node_id, plan_node)
            if digest(target) != command.expected_target_digest:
                raise ProductWorkError("正式检查点或责任已变化，请刷新")
            states, _ = current_states(connection, context.tenant.id, project_id, formal)
            state = next(row for row in states if row["node_id"] == str(node_id))
            if state.get("actual_finish") or state["status"] in ("done", "skipped", "completed"):
                raise ProductWorkError(
                    "已结束检查点不能改写其设计绑定，请按正式计划变更设置后续检查点"
                )
            variant = _get(
                connection, context, project_id, tables.id_design_variants, command.variant_id
            )
            previous = latest_bindings(connection, context.tenant.id, project_id).get(node_id)
            if (previous["version"] if previous else 0) != command.expected_version:
                raise ProductWorkError("检查点绑定已有新版本，请刷新")
            row = (
                connection.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        node_id=node_id,
                        variant_id=command.variant_id,
                        version=command.expected_version + 1,
                        previous_binding_id=previous["id"] if previous else None,
                        snapshot={
                            "target": target,
                            "variant": _plain(variant),
                            "baseline_id": str(formal["baseline_id"]),
                        },
                        target_digest=command.expected_target_digest,
                        reason=command.reason,
                        created_by_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=fingerprint,
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            _event(
                connection, context, project_id, row["id"], "freeze_checkpoint_bound", _plain(row)
            )
            from app.domain.schedule_forecasts import automatic_forecast

            automatic_forecast(
                connection,
                context.tenant.id,
                project_id,
                context.user.id,
                "ID冻结检查点绑定后更新预测",
                datetime.now(UTC),
            )
            return _plain(row)
