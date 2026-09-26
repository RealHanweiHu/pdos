"""Creation-pinned requirements for named Gate signers and shared rehearsal."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, select

from app.db.schema import tables
from app.domain.gate_assignments import GateAssignmentError, validate_signers
from app.domain.gates import GateSlot
from app.domain.process_template_gates import requirements
from app.domain.project_templates import ProjectTemplateError

NamedSlots = dict[str, list[GateSlot]]
Scenario = Literal["qualified", "missing", "unqualified", "nonmember"]
SCENARIOS: tuple[Scenario, ...] = ("qualified", "missing", "unqualified", "nonmember")


def named_slots(snapshot: dict[str, Any]) -> NamedSlots:
    configured: NamedSlots = snapshot.get("named_gate_slots") or {}
    gates = requirements(snapshot)
    if configured.keys() - gates.keys():
        raise ProjectTemplateError("具名签核要求引用了不存在的阶段")
    result: NamedSlots = {}
    for stage, slots in sorted(configured.items()):
        if len(slots) != len(set(slots)) or any(
            slot not in gates[stage] or gates[stage][slot] == "not_applicable" for slot in slots
        ):
            raise ProjectTemplateError("具名签核只能选择适用的专业槽位，且不可重复")
        if slots:
            result[stage] = sorted(slots)
    return result


def creation_policy(c: Connection, tenant: UUID, project: UUID, stage: str) -> dict[str, Any]:
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
    required = named_slots(row["snapshot"]).get(stage, [])
    if not required:
        return {}
    return {
        "required_slots": required,
        "source": {
            "project_template_version_id": str(row["id"]),
            "template_id": row["template_id"],
            "template_version": row["template_version"],
            "template_digest": row["digest"],
        },
    }


class SignerCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage: str = Field(min_length=1, max_length=64)
    scenario: Scenario
    slot: GateSlot
    expected_valid: bool


def examples(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        SignerCase(
            stage=stage, slot=slot, scenario=scenario, expected_valid=scenario == "qualified"
        ).model_dump(mode="json")
        for stage, slots in named_slots(snapshot).items()
        for slot in slots
        for scenario in SCENARIOS
    ]


def rehearse(snapshot: dict[str, Any], cases: list[SignerCase]) -> dict[str, Any]:
    configured, gates = named_slots(snapshot), requirements(snapshot)
    results, covered = [], set()
    for case in cases:
        problem = None
        valid_input = case.stage in gates and case.slot in configured.get(case.stage, [])
        if valid_input:
            selected = {slot: f"person-{slot}" for slot in configured[case.stage]}
            people = {
                identity: {
                    "user_id": identity,
                    "display_name": f"模拟{slot}人员",
                    "role": "simulated",
                    "slots": [slot],
                }
                for slot, identity in selected.items()
            }
            identity = selected[case.slot]
            if case.scenario == "missing":
                del selected[case.slot]
            elif case.scenario == "unqualified":
                people[identity]["slots"] = []
            elif case.scenario == "nonmember":
                del people[identity]
            try:
                validate_signers(gates[case.stage], configured[case.stage], selected, people)
            except GateAssignmentError as error:
                problem = str(error)
        else:
            problem = "场景须引用此版要求具名的阶段与槽位"
        valid = problem is None
        matched = valid_input and valid == case.expected_valid
        if matched:
            covered.add((case.stage, case.slot, case.scenario))
        results.append(
            case.model_dump(mode="json")
            | {
                "actual_valid": valid,
                "matched": matched,
                "problem": problem,
            }
        )
    missing = [
        case
        for case in examples(snapshot)
        if (case["stage"], case["slot"], case["scenario"]) not in covered
    ]
    return {
        "passed": not missing and all(r["matched"] for r in results),
        "results": results,
        "missing": missing,
        "scope": "演练采用正式分派校验；人员为模拟数据，不代表实际签核或业务就绪。",
    }
