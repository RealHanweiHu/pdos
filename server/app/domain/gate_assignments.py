"""Named Gate reviewers fixed per round, with original role permissions retained."""

from dataclasses import asdict
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, select

from app.auth.roles import Role
from app.db.schema import tables
from app.domain.gates import GateService, GateSlot, may_sign_gate_slot
from app.domain.product_workspace import digest


class GateAssignmentError(ValueError):
    def __init__(self, message: str, slot: GateSlot | None = None):
        super().__init__(message)
        self.slot = slot


class GateAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_basis: str = Field(pattern=r"^[a-f0-9]{64}$")
    replace_round_id: UUID | None = None
    signers: dict[GateSlot, UUID] = Field(default_factory=dict, max_length=3)
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")

    def signature(self) -> str:
        return digest(self.model_dump(mode="json"))


def members(
    c: Connection, tenant: UUID, project: UUID, *, lock: bool = False
) -> list[dict[str, Any]]:
    u, m = tables.users, tables.project_members
    slots: tuple[GateSlot, ...] = ("product", "engineering", "quality")
    query = (
        select(u.c.id, u.c.display_name, u.c.role)
        .join(m, (m.c.tenant_id == u.c.tenant_id) & (m.c.user_id == u.c.id))
        .where(u.c.tenant_id == tenant, m.c.project_id == project, u.c.is_active.is_(True))
        .order_by(u.c.id)
    )
    if lock:
        query = query.with_for_update(read=True)
    return [
        {
            "user_id": str(row.id),
            "display_name": row.display_name,
            "role": row.role,
            "slots": [slot for slot in slots if may_sign_gate_slot(Role(row.role), slot)],
        }
        for row in c.execute(query)
    ]


def validate_signers(
    requirements: dict[GateSlot, Any],
    required: list[GateSlot],
    signers: dict[GateSlot, str],
    people: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    for slot in required:
        if slot not in signers:
            raise GateAssignmentError("本项目创建版要求为该签核槽位指定实际人员", slot)
    selected: dict[str, Any] = {}
    for slot, user in signers.items():
        person = people.get(user)
        if requirements.get(slot) == "not_applicable":
            raise GateAssignmentError("不适用的签核槽位不能分派人员", slot)
        if person is None or slot not in person["slots"]:
            raise GateAssignmentError("请为每个具名槽位选择仍在本项目且有对应签核权限的成员", slot)
        selected[slot] = {key: person[key] for key in ("user_id", "display_name", "role")}
    return selected


def resolve(
    c: Connection,
    tenant: UUID,
    project: UUID,
    request: GateAssignmentRequest,
    requirements: dict[GateSlot, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    people = {p["user_id"]: p for p in members(c, tenant, project, lock=True)}
    selected = validate_signers(
        requirements,
        policy.get("required_slots", []),
        {slot: str(user) for slot, user in request.signers.items()},
        people,
    )
    return {
        "request_id": str(request.request_id),
        "request_digest": request.signature(),
        "replaces_round_id": str(request.replace_round_id) if request.replace_round_id else None,
        "reason": request.reason.strip(),
        "signers": selected,
        **({"required_policy": policy} if policy else {}),
    }


def require_assignee(
    c: Connection,
    tenant: UUID,
    project: UUID,
    routing: dict[str, Any],
    slot: GateSlot,
    user: UUID,
) -> None:
    assigned = routing.get("assignment", {}).get("signers", {}).get(slot)
    if assigned is None:
        return
    if assigned["user_id"] != str(user):
        raise GateAssignmentError("本槽位须由本轮指定的签核人本人办理")
    person = next(
        (p for p in members(c, tenant, project, lock=True) if p["user_id"] == str(user)), None
    )
    if person is None or slot not in person["slots"]:
        raise GateAssignmentError(
            "指定人员已不具备当前项目签核资格，请由项目负责人更换并开启新轮次"
        )


def options(c: Connection, tenant: UUID, project: UUID, gate: UUID) -> dict[str, Any]:
    from app.domain.process_template_named_signers import creation_policy

    row = GateService._gate_row(c, tenant_id=tenant, project_id=project, gate_id=gate)
    return {
        "required_policy": creation_policy(c, tenant, project, row["stage_code"]),
        "requirements": GateService._requirements_for_gate(
            c,
            tenant_id=tenant,
            project_id=project,
            gate_id=gate,
            workflow_code=row["workflow_code"],
            stage_code=row["stage_code"],
        ),
        "members": members(c, tenant, project),
        "signing_basis": GateService._record_from_row(c, tenant_id=tenant, row=row).signing_basis,
    }


def history(
    c: Connection,
    tenant: UUID,
    project: UUID,
    gate: UUID,
    before: int | None,
    round_id: UUID | None = None,
) -> dict[str, Any]:
    GateService._gate_row(c, tenant_id=tenant, project_id=project, gate_id=gate)
    t = tables.gate_signoff_rounds
    query = select(t).where(t.c.tenant_id == tenant, t.c.project_id == project, t.c.gate_id == gate)
    if round_id is not None:
        query = query.where(t.c.id == round_id)
    if before is not None:
        query = query.where(t.c.round_number < before)
    rows = list(c.execute(query.order_by(t.c.round_number.desc()).limit(21)).mappings())
    items = []
    for row in rows[:20]:
        items.append(
            {
                "id": str(row["id"]),
                "round_number": row["round_number"],
                "status": row["status"],
                "opened_at": row["opened_at"],
                "opened_by_user_id": str(row["opened_by_user_id"]),
                "supersede_reason": row["supersede_reason"],
                "routing_snapshot": row["routing_snapshot"],
                "signoffs": [
                    asdict(GateService._signoff_record(s))
                    for s in GateService._signoff_rows(
                        c,
                        tenant_id=tenant,
                        project_id=project,
                        gate_id=gate,
                        round_id=row["id"],
                    )
                ],
            }
        )
    return {"items": items, "next_before": rows[19]["round_number"] if len(rows) > 20 else None}
