"""Read the entire approved scope against current tasks, evidence and confirmations."""

from collections import Counter
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.change_execution_followups import records, response_gaps
from app.domain.change_execution_results import _access, _assess_references, _gaps
from app.domain.change_execution_tasks import _bindings, _state
from app.domain.product_workspace import _plain


def read(engine: Engine, *, context: AuthContext, project_id: UUID, ecr_id: UUID) -> dict[str, Any]:
    _access(engine, context, project_id, Action.CHANGE_VIEW)
    tenant_id = context.tenant.id
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        return _read(c, tenant_id, project_id, ecr_id)


def _read(c: Connection, tenant_id: UUID, project_id: UUID, ecr_id: UUID) -> dict[str, Any]:
    state = _state(c, tenant_id, project_id, ecr_id)
    scope = state["approved_scope"]
    version = scope["version"] if scope else None
    bindings = _bindings(c, tenant_id, project_id, ecr_id)
    current_bindings = {
        b["item_key"]: b for b in bindings if version and b["scope_version_id"] == version["id"]
    }
    binding_ids = [UUID(b["id"]) for b in current_bindings.values()]
    followups = records(c, tenant_id, project_id, binding_ids)
    r, cf = tables.change_execution_results, tables.change_execution_confirmations
    latest = (
        {
            str(row["binding_id"]): _plain(dict(row))
            for row in c.execute(
                select(r)
                .where(
                    r.c.tenant_id == tenant_id,
                    r.c.project_id == project_id,
                    r.c.binding_id.in_(binding_ids),
                )
                .distinct(r.c.binding_id)
                .order_by(r.c.binding_id, r.c.revision_number.desc())
            ).mappings()
        }
        if binding_ids
        else {}
    )
    confirmations = (
        {
            str(row["result_id"]): _plain(dict(row))
            for row in c.execute(
                select(cf).where(
                    cf.c.tenant_id == tenant_id,
                    cf.c.project_id == project_id,
                    cf.c.result_id.in_([UUID(value["id"]) for value in latest.values()]),
                )
            ).mappings()
        }
        if latest
        else {}
    )
    evidence_cache: dict[tuple[str, str], dict[str, Any] | None] = {}
    items = []
    actor_ids = set()
    for item in version["snapshot"]["items"] if version else []:
        binding = current_bindings.get(item["key"])
        result = latest.get(binding["id"]) if binding else None
        confirmation = confirmations.get(result["id"]) if result else None
        refs = []
        gaps = []
        required = item["action"] != "none"
        if result is not None and binding is not None:
            basis = {
                "binding": binding,
                "ecr": state["ecr"],
                "scope_bound": bool(version and state["ecr"]["status"] == "approved"),
                "scope_changes": state["source_changes"],
                "follow_ups": [f for f in followups if f["binding_id"] == binding["id"]],
            }
            refs = _assess_references(
                c,
                tenant_id,
                project_id,
                basis,
                result["snapshot"]["references"],
                evidence_cache=evidence_cache,
            )
            gaps = _gaps(basis, refs) + response_gaps(basis, result["snapshot"])
        if not required:
            status = "no_action"
        elif binding is None:
            status = "unassigned"
            gaps.append("尚未安排本条范围的实际执行任务")
        elif result is None:
            status = "no_result"
            gaps.append("尚未登记本条范围的实际结果与对应证据")
        elif confirmation and confirmation["outcome"] == "returned":
            status = "returned"
        elif gaps:
            status = "evidence_gaps"
        elif confirmation and confirmation["outcome"] == "verified":
            status = "verified"
        elif result["outcome"] == "ready_for_confirmation":
            status = "awaiting_confirmation"
        elif result["outcome"] == "needs_follow_up":
            status = "follow_up"
        else:
            status = "recorded"
        task = binding["task"] if binding else None
        if task and task["assignee_user_id"]:
            actor_ids.add(UUID(task["assignee_user_id"]))
        if result:
            actor_ids.add(UUID(result["created_by_user_id"]))
            if result["reviewer_user_id"]:
                actor_ids.add(UUID(result["reviewer_user_id"]))
        items.append(
            {
                "item": item,
                "required": required,
                "follow_up_count": sum(f["binding_id"] == binding["id"] for f in followups)
                if binding
                else 0,
                "status": status,
                "binding_id": binding["id"] if binding else None,
                "completion_criteria": binding["snapshot"]["completion_criteria"]
                if binding
                else None,
                "task": task,
                "result": {
                    key: result[key]
                    for key in (
                        "id",
                        "revision_number",
                        "created_by_user_id",
                        "reviewer_user_id",
                        "created_at",
                        "outcome",
                    )
                }
                if result
                else None,
                "result_scope": {
                    key: result["snapshot"][key]
                    for key in (
                        "completed_scope",
                        "excluded_scope",
                        "criteria_response",
                        "follow_up",
                    )
                }
                if result
                else None,
                "confirmation": {
                    key: confirmation[key]
                    for key in (
                        "outcome",
                        "note",
                        "created_by_user_id",
                        "created_at",
                    )
                }
                if confirmation
                else None,
                "evidence": [
                    {
                        "kind": ref["kind"],
                        "id": ref["id"],
                        "role": ref["role"],
                        "correspondence": ref["correspondence"],
                        "changed": ref["changed"],
                        "assessment": ref["assessment"],
                    }
                    for ref in refs
                ],
                "gaps": gaps,
            }
        )
    u = tables.users
    people = (
        [
            _plain(dict(row))
            for row in c.execute(
                select(u.c.id, u.c.display_name).where(
                    u.c.tenant_id == tenant_id,
                    u.c.id.in_(actor_ids),
                )
            ).mappings()
        ]
        if actor_ids
        else []
    )
    required_items = [item for item in items if item["required"]]
    counts = dict(Counter(item["status"] for item in items))
    scope_gaps = []
    if version is None:
        scope_gaps.append("尚无已提交分析的范围版本")
    if not state["can_assign"]:
        scope_gaps.append("当前批准范围、版本或设计资料需要重新核对")
    if any(item["item"]["conclusion"] == "unknown" for item in items):
        scope_gaps.append("范围中仍有未判定的影响")
    return {
        "ecr": state["ecr"],
        "scope": {
            "id": version["id"],
            "revision_number": version["revision_number"],
            "coverage": version["snapshot"]["coverage"],
            "exclusions": version["snapshot"]["exclusions"],
        }
        if version
        else None,
        "items": items,
        "people": people,
        "counts": counts,
        "required_count": len(required_items),
        "scope_gaps": scope_gaps,
        "source_changes": state["source_changes"],
        "historical_binding_count": len(bindings) - len(current_bindings),
        "all_required_verified": bool(required_items)
        and not scope_gaps
        and all(item["status"] == "verified" for item in required_items),
        "read_at": datetime.now(UTC).isoformat(),
    }
