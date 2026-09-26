"""Typed organization template edits and deterministic business rehearsal."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.gates import GateSignoffStatus, GateSlot, gate_signoffs_ready
from app.domain.process_template_approval_routes import ApprovalRoutes
from app.domain.process_template_approval_routes import routes as approval_routes
from app.domain.process_template_fields import IssueField
from app.domain.process_template_fields import definitions as issue_fields
from app.domain.process_template_gates import (
    GateRequirements,
    baseline,
    configure_requirements,
    requirements,
)
from app.domain.process_template_named_signers import NamedSlots, named_slots
from app.domain.process_template_reminders import ReminderPolicy
from app.domain.process_template_reminders import policy as reminder_policy
from app.domain.process_template_risk_fields import RiskField
from app.domain.process_template_risk_fields import definitions as risk_fields
from app.domain.process_template_routing import TaskRoute, configure_routes
from app.domain.process_template_task_fields import TaskField
from app.domain.process_template_task_fields import definitions as task_fields
from app.domain.project_templates import (
    ProjectTemplateError,
    ProjectTemplateSelection,
    compile_selection,
    difference,
)

RESPONSIBILITIES = (
    "product_management",
    "industrial_design",
    "mechanical",
    "hardware",
    "firmware",
    "design_quality",
    "supplier_quality",
    "industrial_engineering",
)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ConfiguredFeature(Input):
    label: str = Field(min_length=1, max_length=200)
    label_en: str = Field(min_length=1, max_length=200)
    default: bool


class ConfiguredTask(Input):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9-]{0,63}$")
    stage: str = Field(min_length=1, max_length=64)
    responsibility: str = Field(min_length=1, max_length=64)
    discipline: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=512)
    title_en: str = Field(min_length=1, max_length=512)
    depends_on: list[str] = Field(max_length=200)
    output: str = Field(min_length=1, max_length=5000)
    receiver: str = Field(min_length=1, max_length=2000)
    required_features: list[str] = Field(max_length=30)
    hard_milestone: bool
    minimum_evidence: list[Literal["work_output", "versioned_output", "receiver_confirmation"]] = (
        Field(min_length=1, max_length=20)
    )


class ConfiguredStage(Input):
    code: str = Field(min_length=1, max_length=64)
    sequence: int = Field(ge=1, le=30)
    name: str = Field(min_length=1, max_length=200)
    name_en: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)


class TemplateConfiguration(Input):
    name: str = Field(min_length=1, max_length=200)
    name_en: str = Field(min_length=1, max_length=200)
    features: dict[str, ConfiguredFeature] = Field(max_length=30)
    tasks: list[ConfiguredTask] = Field(min_length=1, max_length=200)
    named_gate_slots: NamedSlots | None = None
    risk_fields: list[RiskField] | None = Field(default=None, max_length=30)
    task_fields: list[TaskField] | None = Field(default=None, max_length=30)
    issue_fields: list[IssueField] | None = Field(default=None, max_length=30)
    approval_routes: ApprovalRoutes | None = None
    reminder_policy: ReminderPolicy | None = None
    task_routes: dict[str, TaskRoute] | None = Field(default=None, max_length=200)
    gate_requirements: GateRequirements | None = None
    stages: list[ConfiguredStage] | None = Field(default=None, min_length=1, max_length=30)
    extension_requests: list[str] = Field(default_factory=list, max_length=30)


class GateRehearsal(Input):
    stage: str = Field(min_length=1, max_length=64)
    signoffs: dict[GateSlot, GateSignoffStatus] = Field(default_factory=dict, max_length=3)
    expected_ready: bool


class RehearsalCase(Input):
    name: str = Field(min_length=1, max_length=200)
    features: dict[str, bool] = Field(default_factory=dict, max_length=30)
    completed_codes: list[str] = Field(default_factory=list, max_length=200)
    expect_valid: bool = True
    expected_ready: dict[str, bool] = Field(default_factory=dict, max_length=200)
    gate_checks: list[GateRehearsal] = Field(default_factory=list, max_length=30)


def configuration_difference(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    old = before | {"feature_values": {k: v["default"] for k, v in before["features"].items()}}
    new = after | {"feature_values": {k: v["default"] for k, v in after["features"].items()}}
    summary = difference(old, new)
    old_tasks, new_tasks = (
        {task["code"]: task for task in item["tasks"]} for item in (before, after)
    )
    old_gates, new_gates = requirements(before), requirements(after)
    old_fields, new_fields = (
        {item.key: item.model_dump(mode="json") for item in issue_fields(snapshot)}
        for snapshot in (before, after)
    )
    if "named_gate_slots" in before or "named_gate_slots" in after:
        old_named, new_named = named_slots(before), named_slots(after)
        summary["named_signer_changes"] = [
            {"stage": stage, "before": old_named.get(stage, []), "after": new_named.get(stage, [])}
            for stage in sorted(old_named.keys() | new_named.keys())
            if old_named.get(stage, []) != new_named.get(stage, [])
        ]
    if "task_fields" in before or "task_fields" in after:
        old_task_fields, new_task_fields = (
            {item.key: item.model_dump(mode="json") for item in task_fields(snapshot)}
            for snapshot in (before, after)
        )
        summary["task_field_changes"] = [
            {"key": key, "before": old_task_fields.get(key), "after": new_task_fields.get(key)}
            for key in sorted(old_task_fields.keys() | new_task_fields.keys())
            if old_task_fields.get(key) != new_task_fields.get(key)
        ]
    if "risk_fields" in before or "risk_fields" in after:
        old_risk_fields, new_risk_fields = (
            {item.key: item.model_dump(mode="json") for item in risk_fields(snapshot)}
            for snapshot in (before, after)
        )
        summary["risk_field_changes"] = [
            {"key": key, "before": old_risk_fields.get(key), "after": new_risk_fields.get(key)}
            for key in sorted(old_risk_fields.keys() | new_risk_fields.keys())
            if old_risk_fields.get(key) != new_risk_fields.get(key)
        ]
    return summary | {
        "name": {"before": before["name"], "after": after["name"]},
        "name_en": {"before": before["name_en"], "after": after["name_en"]},
        "feature_definitions": [
            {"key": key, "before": before["features"].get(key), "after": after["features"].get(key)}
            for key in sorted(before["features"].keys() | after["features"].keys())
            if before["features"].get(key) != after["features"].get(key)
        ],
        "issue_field_changes": [
            {"key": key, "before": old_fields.get(key), "after": new_fields.get(key)}
            for key in sorted(old_fields.keys() | new_fields.keys())
            if old_fields.get(key) != new_fields.get(key)
        ],
        "approval_route_changes": [
            {
                "stage": stage,
                "before": approval_routes(before).get(stage, {}),
                "after": approval_routes(after).get(stage, {}),
            }
            for stage in sorted(approval_routes(before).keys() | approval_routes(after).keys())
            if approval_routes(before).get(stage, {}) != approval_routes(after).get(stage, {})
        ],
        "reminder_changes": [
            {
                "key": key,
                "before": reminder_policy(before).model_dump(mode="json")[key],
                "after": value,
            }
            for key, value in reminder_policy(after).model_dump(mode="json").items()
            if value != reminder_policy(before).model_dump(mode="json")[key]
        ],
        "route_changes": [
            {
                "code": code,
                "before": before.get("task_routes", {}).get(code),
                "after": after.get("task_routes", {}).get(code),
            }
            for code in sorted(
                before.get("task_routes", {}).keys() | after.get("task_routes", {}).keys()
            )
            if before.get("task_routes", {}).get(code) != after.get("task_routes", {}).get(code)
        ],
        "gate_changes": [
            {
                "stage": stage,
                "slot": slot,
                "before": old_gates[stage][slot],
                "after": value,
            }
            for stage, slots in new_gates.items()
            for slot, value in slots.items()
            if value != old_gates[stage][slot]
        ],
        "stage_changes": [
            {"code": new_stage["code"], "before": old_stage, "after": new_stage}
            for old_stage, new_stage in zip(before["stages"], after["stages"], strict=True)
            if old_stage != new_stage
        ],
        "task_changes": [
            {"code": key, "before": old_tasks.get(key), "after": new_tasks.get(key)}
            for key in sorted(old_tasks.keys() | new_tasks.keys())
            if old_tasks.get(key) != new_tasks.get(key)
        ],
    }


def configure(
    base: dict[str, Any], config: TemplateConfiguration, template_id: str, version: int
) -> dict[str, Any]:
    """Only configuration with a real downstream consumer is publishable."""
    old = {task["code"]: task for task in base["tasks"]}
    tasks = {task.code: task.model_dump() for task in config.tasks}
    if len(tasks) != len(config.tasks):
        raise ProjectTemplateError("任务编号不可重复")
    contract = base.get("contract_tasks", old)
    protected = dict(contract) | {key: task for key, task in old.items() if task["hard_milestone"]}
    if protected.keys() - tasks.keys():
        raise ProjectTemplateError("基础流程和已设硬里程碑须保留；额外普通任务可经差异修订移除")
    if base["features"].keys() - config.features.keys():
        raise ProjectTemplateError("基础功能字段须保留，以免既有适用条件失效")
    if any(
        not key.isascii() or not key.replace("_", "").isalnum() or len(key) > 64
        for key in config.features
    ):
        raise ProjectTemplateError("功能标识须为64位以内的英文字母、数字和下划线")
    configured_stages = (
        [stage.model_dump() for stage in config.stages]
        if config.stages is not None
        else deepcopy(base["stages"])
    )
    if [(stage["code"], stage["sequence"]) for stage in configured_stages] != [
        (stage["code"], stage["sequence"]) for stage in base["stages"]
    ]:
        raise ProjectTemplateError("阶段类型和顺序须保留；增删或重排阶段需先完成对应硬闸扩展")
    stages = {stage["code"]: stage["sequence"] for stage in configured_stages}
    for key, task in tasks.items():
        if task["stage"] not in stages or task["responsibility"] not in RESPONSIBILITIES:
            raise ProjectTemplateError("任务须使用已有阶段和专业职责；组织权限不能通过模板改写")
        if len(set(task["depends_on"])) != len(task["depends_on"]) or key in task["depends_on"]:
            raise ProjectTemplateError("任务前置不能重复或指向自身")
        if set(task["depends_on"]) - tasks.keys():
            raise ProjectTemplateError("任务前置不存在")
        if set(task["required_features"]) - config.features.keys():
            raise ProjectTemplateError("任务适用条件引用了不存在的功能")
        for dependency in task["depends_on"]:
            predecessor = tasks[dependency]
            if stages[predecessor["stage"]] > stages[task["stage"]]:
                raise ProjectTemplateError("前置任务不能位于后续阶段")
            if not set(predecessor["required_features"]).issubset(task["required_features"]):
                raise ProjectTemplateError("前置任务可能被功能条件排除，不能让后续任务自动绕过它")
        if key in protected:
            previous = protected[key]
            if (
                previous["stage"] != task["stage"]
                or set(previous["depends_on"]) - set(task["depends_on"])
                or set(task["required_features"]) - set(previous["required_features"])
                or (previous["hard_milestone"] and not task["hard_milestone"])
                or set(previous["minimum_evidence"]) - set(task["minimum_evidence"])
            ):
                raise ProjectTemplateError("不能弱化基础任务的阶段、前置、适用范围、冻结或证据要求")
    payload = deepcopy(base)
    payload.update(
        id=template_id,
        version=version,
        name=config.name,
        name_en=config.name_en,
        features={k: v.model_dump() for k, v in config.features.items()},
        tasks=list(tasks.values()),
        stages=configured_stages,
        gate_requirements=configure_requirements(base, config.gate_requirements),
        task_routes=configure_routes(base, config.task_routes, tasks),
        reminder_policy=(config.reminder_policy or reminder_policy(base)).model_dump(mode="json"),
        evidence_status="organization_configuration",
        pending_extensions=config.extension_requests,
        contract_tasks=deepcopy(contract),
    )
    payload["approval_routes"] = approval_routes(
        payload
        | {
            "approval_routes": config.approval_routes
            if config.approval_routes is not None
            else base.get("approval_routes", {})
        }
    )
    if config.named_gate_slots is not None or "named_gate_slots" in base:
        payload["named_gate_slots"] = named_slots(
            payload
            | {
                "named_gate_slots": config.named_gate_slots
                if config.named_gate_slots is not None
                else base.get("named_gate_slots", {})
            }
        )
    if config.task_fields is not None or "task_fields" in base:
        payload["task_fields"] = [
            item.model_dump(mode="json")
            for item in task_fields(
                {
                    "task_fields": config.task_fields
                    if config.task_fields is not None
                    else base.get("task_fields", [])
                }
            )
        ]
    if config.risk_fields is not None or "risk_fields" in base:
        payload["risk_fields"] = [
            item.model_dump(mode="json")
            for item in risk_fields(
                {
                    "risk_fields": config.risk_fields
                    if config.risk_fields is not None
                    else base.get("risk_fields", [])
                }
            )
        ]
    payload["issue_fields"] = [
        item.model_dump(mode="json")
        for item in issue_fields(
            {
                "issue_fields": config.issue_fields
                if config.issue_fields is not None
                else base.get("issue_fields", [])
            }
        )
    ]
    # Validate the complete graph even if a feature is disabled in the default selection.
    selection = ProjectTemplateSelection(
        template_id=template_id,
        version=version,
        features={key: True for key in config.features},
        reason="组织模板全任务结构核对",
    )
    compile_selection(selection, templates=[payload])
    return payload


def rehearse(snapshot: dict[str, Any], cases: list[RehearsalCase]) -> dict[str, Any]:
    output = []
    positive = negative = False
    gate_requirements = requirements(snapshot)
    gate_baseline = baseline(snapshot)
    tightened = {
        (stage, slot)
        for stage, slots in gate_requirements.items()
        for slot, value in slots.items()
        if value != gate_baseline[stage][slot]
    }
    gate_positive: set[tuple[str, GateSlot]] = set()
    gate_negative: set[tuple[str, GateSlot]] = set()
    for case in cases:
        try:
            selected = compile_selection(
                ProjectTemplateSelection(
                    template_id=snapshot["id"],
                    version=snapshot["version"],
                    features=case.features,
                    reason=case.name,
                ),
                templates=[snapshot],
            )
            tasks = {task["code"]: task for task in selected["tasks"]}
            if set(case.completed_codes) - tasks.keys():
                raise ProjectTemplateError("已完成任务包含不适用或不存在的编号")
            if set(case.expected_ready) - tasks.keys():
                raise ProjectTemplateError("预期判断包含不适用或不存在的编号")
            completed = set(case.completed_codes)
            states = {
                key: {
                    "ready": key not in completed and not (set(task["depends_on"]) - completed),
                    "completed": key in completed,
                    "waiting_for": sorted(set(task["depends_on"]) - completed),
                }
                for key, task in tasks.items()
            }
            checks = [
                {
                    "code": key,
                    "expected_ready": wanted,
                    "actual_ready": states[key]["ready"],
                    "matches": wanted == states[key]["ready"],
                }
                for key, wanted in sorted(case.expected_ready.items())
            ]
            gate_checks = []
            case_gate_positive: set[tuple[str, GateSlot]] = set()
            case_gate_negative: set[tuple[str, GateSlot]] = set()
            for gate_case in case.gate_checks:
                if gate_case.stage not in gate_requirements:
                    raise ProjectTemplateError("签核演练引用了不存在的阶段")
                decision = gate_signoffs_ready(
                    gate_requirements[gate_case.stage], gate_case.signoffs
                )
                gate_checks.append(
                    {
                        "stage": gate_case.stage,
                        "signoffs": gate_case.signoffs,
                        "requirements": gate_requirements[gate_case.stage],
                        "expected_ready": gate_case.expected_ready,
                        "actual_ready": decision.ready,
                        "matches": gate_case.expected_ready == decision.ready,
                        "blockers": list(decision.blockers),
                    }
                )
                for stage, slot in tightened:
                    if stage != gate_case.stage:
                        continue
                    if gate_case.expected_ready and decision.ready:
                        case_gate_positive.add((stage, slot))
                    # Prove the tightened slot changes the result, with other slots satisfied.
                    original = gate_signoffs_ready(gate_baseline[stage], gate_case.signoffs)
                    if (
                        not gate_case.expected_ready
                        and not decision.ready
                        and original.ready
                        and f"signoff:{slot}" in decision.blockers
                    ):
                        case_gate_negative.add((stage, slot))
            passed = (
                case.expect_valid
                and bool(checks or gate_checks)
                and all(check["matches"] for check in checks + gate_checks)
            )
            positive |= passed and (
                any(case.expected_ready.values())
                or any(item["expected_ready"] for item in gate_checks)
            )
            negative |= passed and (
                any(not value for value in case.expected_ready.values())
                or any(not item["expected_ready"] for item in gate_checks)
            )
            if passed:
                gate_positive.update(case_gate_positive)
                gate_negative.update(case_gate_negative)
            output.append(
                {
                    "name": case.name,
                    "valid": True,
                    "passed": passed,
                    "checks": checks,
                    "tasks": states,
                    "gate_checks": gate_checks,
                }
            )
        except ProjectTemplateError as error:
            passed = not case.expect_valid
            negative |= passed
            output.append(
                {
                    "name": case.name,
                    "valid": False,
                    "passed": passed,
                    "error": str(error),
                    "checks": [],
                    "tasks": {},
                }
            )
    return {
        "cases": output,
        "has_positive": positive,
        "has_negative": negative,
        "gate_coverage": [
            {
                "stage": stage,
                "slot": slot,
                "positive": (stage, slot) in gate_positive,
                "negative": (stage, slot) in gate_negative,
            }
            for stage, slot in sorted(tightened)
        ],
        "passed": (
            bool(output)
            and positive
            and negative
            and all(row["passed"] for row in output)
            and tightened <= gate_positive
            and tightened <= gate_negative
        ),
        "scope": (
            "仅演练任务适用性/前置和签核状态要求；审批角色权限、业务证据、时间及容量另行联验，签核条件满足不等于Gate可通过。"
        ),
    }
