"""Template signoff policy compiled into the existing Gate additions consumer."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, select

from app.db.schema import tables
from app.domain.gates import (
    GateRequirement,
    GateSlot,
    gate_policy_for_workflow,
    promote_requirement,
)
from app.domain.project_templates import ProjectTemplateError

GateRequirements = dict[str, dict[GateSlot, GateRequirement]]


def baseline(snapshot: dict[str, Any]) -> GateRequirements:
    return {
        stage["code"]: dict(gate_policy_for_workflow(snapshot["workflow"], stage["code"])[1])
        for stage in snapshot["stages"]
    }


def requirements(snapshot: dict[str, Any]) -> GateRequirements:
    result = baseline(snapshot)
    changes = snapshot.get("gate_requirements") or {}
    if set(changes) - result.keys():
        raise ProjectTemplateError("审批配置引用了不存在的阶段")
    for stage, slots in changes.items():
        if set(slots) - result[stage].keys():
            raise ProjectTemplateError("审批配置须使用现有产品、工程、品质签核槽位")
        for slot, requirement in slots.items():
            current = result[stage][slot]
            if requirement not in {"not_applicable", "conditional", "required"} or (
                current != requirement and promote_requirement(current, requirement) is None
            ):
                raise ProjectTemplateError("模板审批配置不能降低现有硬闸")
            result[stage][slot] = requirement
    return result


def configure_requirements(
    base: dict[str, Any], changes: GateRequirements | None
) -> GateRequirements:
    previous = requirements(base)
    if changes is None:
        return previous
    result = requirements(base | {"gate_requirements": changes})
    for stage, slots in previous.items():
        for slot, previous_value in slots.items():
            requested = result[stage][slot]
            if (
                requested != previous_value
                and promote_requirement(previous_value, requested) is None
            ):
                raise ProjectTemplateError("不能降低作为依据的模板签核要求；回退须另行明确发布旧版")
    return result


def adopt(
    connection: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    actor_user_id: UUID,
    snapshot: dict[str, Any],
    template_version_id: UUID,
) -> None:
    """Called only inside project creation, before any Gate review round exists."""
    base, configured = baseline(snapshot), requirements(snapshot)
    gates = connection.execute(
        select(tables.gates.c.id, tables.stages.c.code)
        .join(
            tables.stages,
            (tables.stages.c.tenant_id == tables.gates.c.tenant_id)
            & (tables.stages.c.id == tables.gates.c.stage_id),
        )
        .where(tables.gates.c.tenant_id == tenant_id, tables.gates.c.project_id == project_id)
    ).mappings()
    for gate in gates:
        for slot, requirement in configured[gate["code"]].items():
            if requirement == base[gate["code"]][slot]:
                continue
            connection.execute(
                tables.gate_signoff_additions.insert().values(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    project_id=project_id,
                    gate_id=gate["id"],
                    slot=slot,
                    requirement=requirement,
                    active=True,
                    added_by_user_id=actor_user_id,
                    reason=(
                        f"创建项目采用 {snapshot['name']} v{snapshot['version']}；"
                        f"项目模板记录 {template_version_id}；配置摘要 {snapshot['digest']}"
                    ),
                )
            )
