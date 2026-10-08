"""Current cost recovery evidence for the canonical, named Issue close action."""

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Digest
from app.db.schema import tables
from app.domain.cost_backtests import source_state
from app.domain.cost_gaps import assess, latest
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.knowledge_push import KnowledgeAccessError
from app.domain.material_exceptions import _authorize
from app.domain.product_workspace import digest


class CostClosureError(ValueError):
    """The selected recovery no longer supports closing this original Issue."""


class CostClosureAccessError(PermissionError):
    """The verifier cannot currently read the original cost sources."""


class CostClosureReference(Contract):
    case_id: UUID
    observation_id: UUID
    source_digest: Digest


def cases(c: Connection, tenant: UUID, project: UUID, issue: UUID) -> list[Any]:
    t = tables.cost_gap_cases
    return list(
        c.execute(
            select(t)
            .where(t.c.tenant_id == tenant, t.c.project_id == project, t.c.issue_id == issue)
            .order_by(t.c.id)
        ).mappings()
    )


def recovery(c: Connection, tenant: UUID, project: UUID, case: Any) -> dict[str, Any]:
    observation = latest(c, tenant, case["id"])
    if observation is None:
        return {"ready": False, "reasons": ["尚无成本观察记录"], "reference": None}
    calculation = observation["snapshot"]["calculation"]
    current = source_state(c, tenant, project, calculation)
    assessment = assess(case, calculation, current, observation)
    reasons = list(assessment["reasons"])
    if observation["state"] != "within_target" or assessment["state"] != "within_target":
        reasons.append("最新同口径成本尚未回到目标内，请沿原问题重新核对计算")
    signature = digest(
        {
            "case_id": str(case["id"]),
            "scope_key": case["scope_key"],
            "observation_id": str(observation["id"]),
            "version": observation["version"],
            "calculation_digest": calculation["calculation_digest"],
            "source_digest": calculation["source_digest"],
            "assessment": assessment,
        }
    )
    return {
        "ready": not reasons,
        "reasons": reasons,
        "state": assessment["state"],
        "observation_version": observation["version"],
        "comparison": assessment["metric"]["comparison"],
        "currency": calculation["command"]["currency"],
        "reference": {
            "case_id": str(case["id"]),
            "observation_id": str(observation["id"]),
            "source_digest": signature,
        }
        if not reasons
        else None,
    }


def read_issue_cost_closure(
    c: Connection, context: AuthContext, project: UUID, issue: UUID
) -> dict[str, Any]:
    entries = cases(c, context.tenant.id, project, issue)
    if not entries:
        return {"required": False, "ready": True, "items": []}
    try:
        _authorize(c, context, project)
    except KnowledgeAccessError:
        return {
            "required": True,
            "ready": False,
            "items": [],
            "access_denied": True,
            "reason": "当前无权读取成本恢复依据，请由有权限的具名验证人核对",
        }
    items = [
        {
            "case_id": str(entry["id"]),
            "title": entry["subsystem"]
            + (" · NRE预算" if entry["basis"] == "nre" else " · 单位成本"),
            "closure": recovery(c, context.tenant.id, project, entry),
        }
        for entry in entries
    ]
    return {"required": True, "ready": all(v["closure"]["ready"] for v in items), "items": items}


def validate_cost_issue_closure(
    c: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    issue_id: UUID,
    actor_user_id: UUID,
    expected_sources: list[CostClosureReference] | None = None,
) -> dict[str, Any]:
    # The caller holds the project write lock, shared by cost input/rollup writes.
    entries = cases(c, tenant_id, project_id, issue_id)
    result: dict[str, Any] = {"policy": "cost.issue_closure.current_cost.v1", "sources": []}
    if not entries:
        if expected_sources:
            raise CostClosureError("所选成本恢复引用不属于此原问题")
        return result
    references = {v.case_id: v for v in expected_sources or []}
    if len(references) != len(expected_sources or []) or set(references) != {
        entry["id"] for entry in entries
    }:
        raise CostClosureError("关闭原问题须明确选择全部关联Cost Gap的当前恢复记录")
    try:
        for action in (Action.PRODUCT_ENGINEERING_VIEW, Action.WORK_ITEM_VIEW):
            KnowledgeCorrectionService._authorize(c, tenant_id, actor_user_id, project_id, action)
    except KnowledgeAccessError as error:
        raise CostClosureAccessError("当前无权核对成本恢复依据") from error
    for entry in entries:
        current = recovery(c, tenant_id, project_id, entry)
        if (
            not current["ready"]
            or references[entry["id"]].model_dump(mode="json") != current["reference"]
        ):
            raise CostClosureError("成本观察、目标或原件已变化，须按当前同口径恢复记录重新核对")
        result["sources"].append(
            {
                **current["reference"],
                "observation_version": current["observation_version"],
                "comparison": current["comparison"],
                "currency": current["currency"],
            }
        )
    return result
