"""Named responsibility amendments follow scenario approval and baseline application."""

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Connection, select

from app.auth.repository import AuthContext
from app.contracts.common_objects import PlanNode
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError
from app.domain.project_execution import _person
from app.domain.tasks import TaskScopeError, TaskService, TaskUpdate

if TYPE_CHECKING:
    from app.domain.project_schedule_scenarios import NodeResponsibilityChange


def revise_responsibilities(
    c: Connection,
    ctx: AuthContext,
    project: UUID,
    nodes: list[PlanNode],
    states: dict[str, Any],
    ids: dict[str, str],
    changes: tuple["NodeResponsibilityChange", ...],
) -> tuple[list[PlanNode], list[dict[str, Any]]]:
    by_key = {node.node_key: node for node in nodes}
    result = []
    people = {person for item in changes for person in (item.owner_user_id, item.receiver_user_id)}
    people.update(
        person for node in nodes for person in (node.owner_user_id, node.receiver_user_id) if person
    )
    names = (
        dict(
            c.execute(
                select(tables.users.c.id, tables.users.c.display_name).where(
                    tables.users.c.tenant_id == ctx.tenant.id, tables.users.c.id.in_(people)
                )
            )
            .tuples()
            .all()
        )
        if changes
        else {}
    )
    for item in changes:
        key = ids.get(str(item.node_id))
        if key is None or key not in by_key:
            raise ProductWorkError(
                "责任调整须引用当前正式计划保留的节点，新增或替换节点请在新增区配置"
            )
        state, node = states[key], by_key[key]
        if state.get("actual_finish") or state.get("status") in ("done", "skipped", "completed"):
            raise ProductWorkError("已结束节点保留原具名责任")
        if (node.owner_user_id, node.receiver_user_id) == (
            item.owner_user_id,
            item.receiver_user_id,
        ):
            raise ProductWorkError("请选择实际需要变更的负责人或接收人")
        for person in (item.owner_user_id, item.receiver_user_id):
            _person(c, ctx, project, person)
        if state.get("task_id"):
            try:
                TaskService._validate_member(
                    c, tenant_id=ctx.tenant.id, project_id=project, user_id=item.owner_user_id
                )
            except TaskScopeError:
                raise ProductWorkError("任务接手负责人须为有效项目成员，请先补齐成员资格") from None
        result.append(
            {
                **item.model_dump(mode="json"),
                "node_key": key,
                "title": node.title,
                "previous_owner_user_id": str(node.owner_user_id) if node.owner_user_id else None,
                "previous_receiver_user_id": str(node.receiver_user_id)
                if node.receiver_user_id
                else None,
                "previous_owner_name": names.get(node.owner_user_id),
                "previous_receiver_name": names.get(node.receiver_user_id),
                "owner_name": names[item.owner_user_id],
                "receiver_name": names[item.receiver_user_id],
                "task_id": state.get("task_id"),
                "previous_task_assignee_user_id": state.get("assignee_user_id")
                if state.get("task_id")
                else None,
            }
        )
        by_key[key] = node.model_copy(
            update={
                "owner_user_id": item.owner_user_id,
                "receiver_user_id": item.receiver_user_id,
            }
        )
    return [by_key[node.node_key] for node in nodes], result


def apply_task_responsibilities(
    c: Connection, ctx: AuthContext, project: UUID, snapshot: dict[str, Any]
) -> list[dict[str, str]]:
    """Project scope and scenario freshness are already locked/rechecked by the caller."""
    changed = []
    nodes = {node["node_key"]: node for node in snapshot["plan"]["nodes"]}
    for item in snapshot["result"]["changes"].get("responsibility_changes", []):
        if not item.get("task_id"):
            continue
        owner = nodes[item["node_key"]]["owner_user_id"]
        task = (
            c.execute(
                select(tables.tasks)
                .where(
                    tables.tasks.c.tenant_id == ctx.tenant.id,
                    tables.tasks.c.project_id == project,
                    tables.tasks.c.id == UUID(item["task_id"]),
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if (
            task is None
            or task["status"] in ("done", "skipped")
            or (str(task["assignee_user_id"]) if task["assignee_user_id"] else None)
            != item["previous_task_assignee_user_id"]
        ):
            raise ProductWorkError("任务状态或实际负责人已变化，请重新准备责任调整")
        if str(task["assignee_user_id"]) == owner:
            continue
        try:
            TaskService(c.engine).update(
                tenant_id=ctx.tenant.id,
                actor_user_id=ctx.user.id,
                project_id=project,
                task_id=task["id"],
                patch=TaskUpdate(changes={"assignee_user_id": UUID(owner)}),
                connection=c,
            )
        except TaskScopeError:
            raise ProductWorkError("任务接手人的项目成员资格已变化，请重新核对") from None
        changed.append({"task_id": str(task["id"]), "assignee_user_id": owner})
    return changed
