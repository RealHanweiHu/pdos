"""Independent activation of a revised frozen ID with inherited receiver obligations."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.id_design import _event, _get, _prior
from app.domain.product_workspace import ProductWorkError, _plain, _role, digest
from app.domain.project_execution import _person
from app.domain.resource_reservations import _project


class IdActivationDraft(Contract):
    request_id: UUID
    expected_basis_digest: Digest
    reason: Text


def active_freeze_ids(connection: Connection, tenant_id: UUID, project_id: UUID) -> set[UUID]:
    f, b, a = (
        tables.id_design_freezes,
        tables.id_design_change_branches,
        tables.id_design_activations,
    )
    freezes = list(
        connection.execute(
            select(f).where(f.c.tenant_id == tenant_id, f.c.project_id == project_id)
        ).mappings()
    )
    branches = set(
        connection.execute(
            select(b.c.variant_id).where(b.c.tenant_id == tenant_id, b.c.project_id == project_id)
        ).scalars()
    )
    activations = list(
        connection.execute(
            select(a).where(a.c.tenant_id == tenant_id, a.c.project_id == project_id)
        ).mappings()
    )
    replaced = {row["old_freeze_id"] for row in activations}
    activated = {row["new_freeze_id"] for row in activations}
    return {
        row["id"]
        for row in freezes
        if row["id"] not in replaced
        and (row["variant_id"] not in branches or row["id"] in activated)
    }


def current_freeze_lineage(
    connection: Connection, tenant_id: UUID, project_id: UUID, freeze_id: UUID
) -> tuple[UUID, list[dict[str, Any]]]:
    t = tables.id_design_activations
    rows = {
        row["old_freeze_id"]: row
        for row in connection.execute(
            select(t).where(
                t.c.tenant_id == tenant_id,
                t.c.project_id == project_id,
            )
        ).mappings()
    }
    current, visited, lineage = freeze_id, set(), []
    while current in rows:
        if current in visited:
            raise ProductWorkError("冻结版本替代链存在冲突，不能推断当前版本")
        visited.add(current)
        row = rows[current]
        lineage.append(_plain(row))
        current = row["new_freeze_id"]
    return current, lineage


def activation_basis(
    connection: Connection, context: AuthContext, project_id: UUID, freeze_id: UUID
) -> dict[str, Any]:
    from app.domain.formal_schedule import current_plan
    from app.domain.id_design_revision_branch import approval_basis, branch_for_variant
    from app.domain.id_handoff_runtime import target_basis

    new = _get(connection, context, project_id, tables.id_design_freezes, freeze_id)
    branch = branch_for_variant(connection, context, project_id, new["variant_id"])
    if branch is None:
        raise ProductWorkError("初始设计冻结无需变更启用")
    old = _get(
        connection, context, project_id, tables.id_design_freezes, branch["source_freeze_id"]
    )
    if old["id"] not in active_freeze_ids(connection, context.tenant.id, project_id):
        raise ProductWorkError("原冻结版本已被替代，不能再从旧版本启用另一修订")
    ecr = _get(
        connection, context, project_id, tables.engineering_change_requests, branch["ecr_id"]
    )
    if ecr["status"] != "approved" or digest(approval_basis(ecr)) != branch["approval_digest"]:
        raise ProductWorkError("修订来源的ECR批准已不一致")
    h, i, r = (
        tables.id_design_handoffs,
        tables.id_design_handoff_items,
        tables.id_design_handoff_responses,
    )
    all_h = list(
        connection.execute(
            select(h)
            .where(
                h.c.tenant_id == context.tenant.id,
                h.c.project_id == project_id,
                h.c.freeze_id == old["id"],
            )
            .order_by(h.c.id)
        ).mappings()
    )
    replaced = {row["previous_handoff_id"] for row in all_h if row["previous_handoff_id"]}
    heads = [row for row in all_h if row["id"] not in replaced]
    items = list(
        connection.execute(
            select(i)
            .where(
                i.c.tenant_id == context.tenant.id,
                i.c.project_id == project_id,
                i.c.handoff_id.in_([row["id"] for row in heads]),
            )
            .order_by(i.c.id)
        ).mappings()
    )
    responses = list(
        connection.execute(
            select(r)
            .where(
                r.c.tenant_id == context.tenant.id,
                r.c.project_id == project_id,
                r.c.item_id.in_([row["id"] for row in items]),
            )
            .order_by(r.c.id)
        ).mappings()
    )
    q = tables.id_design_reacceptance_requirements
    previous_requirements = list(
        connection.execute(
            select(q)
            .where(
                q.c.tenant_id == context.tenant.id,
                q.c.project_id == project_id,
                q.c.freeze_id == old["id"],
            )
            .order_by(q.c.id)
        ).mappings()
    )
    target_ids = {row["target_node_id"] for row in heads + previous_requirements}
    formal = current_plan(connection, context.tenant.id, project_id)
    current = {}
    if formal:
        plans = {row["node_key"]: row for row in formal["plan"]["nodes"]}
        current = {
            row["id"]: target_basis(row["id"], plans[row["node_key"]]) for row in formal["nodes"]
        }
    targets = [
        {
            "node_id": str(node_id),
            "required": node_id in current,
            "current": current.get(node_id),
            "previous_title": next(
                (
                    row["snapshot"]["target"]["title"]
                    for row in heads
                    if row["target_node_id"] == node_id
                ),
                "原交接节点",
            ),
        }
        for node_id in sorted(target_ids, key=str)
    ]
    return {
        "branch": _plain(branch),
        "old_freeze": _plain(old),
        "new_freeze": _plain(new),
        "handoffs": [_plain(row) for row in heads],
        "items": [_plain(row) for row in items],
        "responses": [_plain(row) for row in responses],
        "inherited_requirements": [_plain(row) for row in previous_requirements],
        "targets": targets,
    }


def decorate_activations(
    connection: Connection, context: AuthContext, project_id: UUID, freezes: list[dict[str, Any]]
) -> None:
    active = active_freeze_ids(connection, context.tenant.id, project_id)
    for freeze in freezes:
        freeze["active"] = UUID(freeze["id"]) in active
        freeze["activation_basis"] = None
        freeze["activation_digest"] = None
        freeze["activation_blocked_reason"] = None
        if not freeze["active"]:
            try:
                basis = activation_basis(connection, context, project_id, UUID(freeze["id"]))
                freeze["activation_basis"] = {
                    "targets": basis["targets"],
                    "old_version": basis["branch"]["snapshot"]["frozen_revision"]["version"],
                }
                freeze["activation_digest"] = digest(basis)
            except ProductWorkError as error:
                freeze["activation_blocked_reason"] = str(error)


class IdDesignActivationService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def apply(
        self, context: AuthContext, project_id: UUID, freeze_id: UUID, command: IdActivationDraft
    ) -> dict[str, Any]:
        _role(context, Action.PROJECT_EDIT)
        fingerprint = digest(
            {
                "project_id": str(project_id),
                "freeze_id": str(freeze_id),
                **command.model_dump(mode="json"),
            }
        )
        with self.engine.begin() as connection:
            project = _project(connection, context, project_id, write=True)
            _person(connection, context, project_id, context.user.id)
            t = tables.id_design_activations
            prior = _prior(connection, context, t, command.request_id, fingerprint)
            if prior:
                return _plain(prior)
            if project["status"] not in ("approved", "active", "on_hold"):
                raise ProductWorkError("当前项目状态不能启用设计修订")
            basis = activation_basis(connection, context, project_id, freeze_id)
            if digest(basis) != command.expected_basis_digest:
                raise ProductWorkError("设计启用或受影响交接依据已变化，请刷新后确认")
            row = (
                connection.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        branch_id=UUID(basis["branch"]["id"]),
                        old_freeze_id=UUID(basis["old_freeze"]["id"]),
                        new_freeze_id=freeze_id,
                        snapshot=basis,
                        basis_digest=command.expected_basis_digest,
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
            for target in basis["targets"]:
                if not target["required"]:
                    continue
                connection.execute(
                    tables.id_design_reacceptance_requirements.insert().values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        activation_id=row["id"],
                        freeze_id=freeze_id,
                        target_node_id=UUID(target["node_id"]),
                        snapshot=target,
                        created_by_user_id=context.user.id,
                        request_id=uuid5(command.request_id, target["node_id"]),
                        request_digest=digest(target),
                    )
                )
            _event(
                connection, context, project_id, row["id"], "revised_design_activated", _plain(row)
            )
            from app.domain.formal_schedule import current_plan
            from app.domain.schedule_forecasts import automatic_forecast

            if current_plan(connection, context.tenant.id, project_id) is not None:
                automatic_forecast(
                    connection,
                    context.tenant.id,
                    project_id,
                    context.user.id,
                    "新设计启用后更新下游重新接收要求",
                    datetime.now(UTC),
                )
            return _plain(row)
