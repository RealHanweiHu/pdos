"""Professional task routing, resolved by named humans in the source scope."""

from __future__ import annotations

from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from app.contracts.common_objects import PlanNode
from app.domain.project_templates import ProjectTemplateError

ProfessionalRole = Literal[
    "product_management",
    "industrial_design",
    "mechanical",
    "hardware",
    "firmware",
    "design_quality",
    "supplier_quality",
    "industrial_engineering",
]


class TaskRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner: ProfessionalRole | None = None
    receiver: ProfessionalRole | None = None

    @model_validator(mode="after")
    def one_destination(self) -> Self:
        if self.owner is None and self.receiver is None:
            raise ValueError("路由至少指定一个负责人或接收人职责；取消路由请移除该项")
        return self


def configure_routes(
    base: dict[str, Any],
    changes: dict[str, TaskRoute] | None,
    tasks: dict[str, Any],
) -> dict[str, Any]:
    routes = (
        changes
        if changes is not None
        else {
            code: TaskRoute.model_validate(value)
            for code, value in base.get("task_routes", {}).items()
        }
    )
    if routes.keys() - tasks.keys():
        raise ProjectTemplateError("办理路由引用了不存在的任务；移除任务时须同时修订路由")
    return {code: route.model_dump(mode="json") for code, route in routes.items()}


def planned_routes(
    template: dict[str, Any],
    bindings: dict[ProfessionalRole, str],
) -> list[dict[str, Any]]:
    selected = {task["code"] for task in template["tasks"]}
    routes = []
    for code, raw in sorted(template.get("task_routes", {}).items()):
        if code not in selected:
            continue
        route = TaskRoute.model_validate(raw)
        for slot, responsibility in (("owner", route.owner), ("receiver", route.receiver)):
            if responsibility is not None:
                routes.append(
                    {
                        "node_key": code,
                        "slot": slot,
                        "responsibility": responsibility,
                        "user_id": bindings.get(responsibility),
                    }
                )
    return routes


def resolve(
    template: dict[str, Any],
    bindings: dict[ProfessionalRole, UUID],
    nodes: tuple[PlanNode, ...],
) -> dict[str, Any]:
    """Require submitted assignments to match the human-previewed configured route."""
    people = {key: str(value) for key, value in bindings.items()}
    routes = planned_routes(template, people)
    targets = {node.node_key: node for node in nodes}
    for route in routes:
        code, slot = route["node_key"], route["slot"]
        node = targets[code]
        submitted = node.owner_user_id if slot == "owner" else node.receiver_user_id
        if (str(submitted) if submitted else None) != route["user_id"]:
            raise ProjectTemplateError(f"{code}的{slot}与模板职责路由不一致，请先更新具名联系人")
    if not routes and not bindings:
        return {}
    return {"template_digest": template["digest"], "bindings": people, "routes": routes}
