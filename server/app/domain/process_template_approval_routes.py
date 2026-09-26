"""Versioned professional signoff dependencies, independent of signing permissions."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, select

from app.db.schema import tables
from app.domain.gates import GateRequirement, GateSignoffStatus, GateSlot, gate_signoffs_ready
from app.domain.process_template_gates import requirements
from app.domain.project_templates import ProjectTemplateError

ApprovalRoutes = dict[str, dict[GateSlot, list[GateSlot]]]


def routes(snapshot: dict[str, Any]) -> ApprovalRoutes:
    configured: ApprovalRoutes = snapshot.get("approval_routes") or {}
    gates = requirements(snapshot)
    if configured.keys() - gates.keys():
        raise ProjectTemplateError("签核先后依赖引用了不存在的阶段")
    result: ApprovalRoutes = {}
    for stage, slots in sorted(configured.items()):
        normalized: dict[GateSlot, list[GateSlot]] = {}
        for slot, predecessors in sorted(slots.items()):
            if slot not in gates[stage] or set(predecessors) - gates[stage].keys():
                raise ProjectTemplateError("签核依赖只能使用产品、工程和品质槽位")
            if len(predecessors) != len(set(predecessors)) or slot in predecessors:
                raise ProjectTemplateError("签核依赖不能重复或依赖自己")
            if predecessors and any(
                gates[stage][item] == "not_applicable" for item in [slot, *predecessors]
            ):
                raise ProjectTemplateError("配置先后依赖的签核双方都必须适用；请先调整签核要求")
            if predecessors:
                normalized[slot] = sorted(predecessors)
        for slot in normalized:
            seen: set[GateSlot] = set()
            pending = list(normalized[slot])
            while pending:
                current = pending.pop()
                if current == slot:
                    raise ProjectTemplateError("签核先后依赖不能形成循环")
                if current not in seen:
                    seen.add(current)
                    pending.extend(normalized.get(current, []))
        if normalized:
            result[stage] = normalized
    return result


def signing_blockers(
    dependencies: Mapping[GateSlot, list[GateSlot]],
    requirements: Mapping[GateSlot, GateRequirement],
    statuses: Mapping[GateSlot, GateSignoffStatus],
    slot: GateSlot,
) -> list[GateSlot]:
    blockers = gate_signoffs_ready(requirements, statuses).blockers
    return [prior for prior in dependencies.get(slot, []) if f"signoff:{prior}" in blockers]


def downstream(dependencies: Mapping[GateSlot, list[GateSlot]], slot: GateSlot) -> list[GateSlot]:
    affected: set[GateSlot] = set()
    pending = [slot]
    while pending:
        current = pending.pop()
        for target, predecessors in dependencies.items():
            if current in predecessors and target not in affected:
                affected.add(target)
                pending.append(target)
    return sorted(affected)


def creation_snapshot(c: Connection, tenant: UUID, project: UUID, stage: str) -> dict[str, Any]:
    v = tables.project_template_versions
    row = (
        c.execute(
            select(v).where(
                v.c.tenant_id == tenant,
                v.c.project_id == project,
                v.c.revision == 1,
                v.c.status.in_(("active", "superseded")),
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["difference"].get("adoption_scope") != "project_creation":
        return {}
    dependencies = routes(row["snapshot"]).get(stage, {})
    if not dependencies:
        return {}
    return {
        "dependencies": dependencies,
        "source": {
            "project_template_version_id": str(row["id"]),
            "template_id": row["template_id"],
            "template_version": row["template_version"],
            "template_digest": row["digest"],
        },
    }


class ApprovalRehearsal(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    stage: str = Field(min_length=1, max_length=64)
    slot: GateSlot
    signoffs: dict[GateSlot, GateSignoffStatus] = Field(default_factory=dict, max_length=3)
    expected_allowed: bool


def rehearse_approvals(snapshot: dict[str, Any], cases: list[ApprovalRehearsal]) -> dict[str, Any]:
    configured, gates = routes(snapshot), requirements(snapshot)
    required = {
        (stage, slot, prior)
        for stage, slots in configured.items()
        for slot, priors in slots.items()
        for prior in priors
    }
    positives: set[tuple[str, str, str]] = set()
    negatives: set[tuple[str, str, str]] = set()
    results = []
    for case in cases:
        dependencies = configured.get(case.stage, {})
        valid = case.stage in gates and bool(dependencies.get(case.slot))
        blockers = (
            signing_blockers(dependencies, gates[case.stage], case.signoffs, case.slot)
            if valid
            else []
        )
        allowed = valid and not blockers
        passed = valid and allowed == case.expected_allowed
        if passed:
            for prior in dependencies[case.slot]:
                edge = (case.stage, case.slot, prior)
                if allowed:
                    positives.add(edge)
                elif blockers == [prior]:
                    negatives.add(edge)
        results.append(
            {
                "name": case.name,
                "inputs": case.model_dump(mode="json"),
                "valid": valid,
                "allowed": allowed,
                "passed": passed,
                "blockers": blockers,
                "invalidated_on_change": downstream(dependencies, case.slot),
            }
        )
    return {
        "cases": results,
        "coverage": [
            {
                "stage": stage,
                "slot": slot,
                "prior": prior,
                "positive": (stage, slot, prior) in positives,
                "negative": (stage, slot, prior) in negatives,
            }
            for stage, slot, prior in sorted(required)
        ],
        "passed": required <= positives
        and required <= negatives
        and all(item["passed"] for item in results),
        "scope": (
            "只演练签核先后条件；每条依赖需覆盖前置满足及仅该前置未满足。"
            "正式签核仍核验人员权限，最终过闸仍核验业务证据。"
            "修改上游签核会使下游已签结果回到待确认。"
        ),
    }
