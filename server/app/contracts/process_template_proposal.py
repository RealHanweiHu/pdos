"""Model-proposed edits to existing template vocabulary, never executable policy."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field

from app.domain.process_template_approval_routes import (
    ApprovalRehearsal,
    ApprovalRoutes,
    rehearse_approvals,
)
from app.domain.process_template_configuration import (
    ConfiguredFeature,
    ConfiguredStage,
    ConfiguredTask,
    Input,
    TemplateConfiguration,
    configuration_difference,
    configure,
    rehearse,
)
from app.domain.process_template_configuration import (
    RehearsalCase as ConfiguredRehearsalCase,
)
from app.domain.process_template_field_rehearsal import FieldRehearsal, rehearse_fields
from app.domain.process_template_fields import IssueField
from app.domain.process_template_gates import GateRequirements
from app.domain.process_template_named_signers import NamedSlots, SignerCase
from app.domain.process_template_named_signers import rehearse as rehearse_signers
from app.domain.process_template_reminder_rehearsal import ReminderRehearsal, rehearse_reminders
from app.domain.process_template_reminders import ReminderPolicy
from app.domain.process_template_risk_field_rehearsal import (
    RiskFieldRehearsal,
    rehearse_risk_fields,
)
from app.domain.process_template_risk_fields import RiskField
from app.domain.process_template_route_rehearsal import RouteRehearsal, rehearse_routes
from app.domain.process_template_routing import TaskRoute
from app.domain.process_template_task_field_rehearsal import (
    TaskFieldRehearsal,
    rehearse_task_fields,
)
from app.domain.process_template_task_fields import TaskField
from app.domain.project_templates import ProjectTemplateError

RequirementText = Annotated[str, Field(min_length=1, max_length=2000)]


class RequirementExplanation(Input):
    source: Literal["instruction", "acceptance_criteria"]
    quote: str = Field(min_length=1, max_length=2000)
    disposition: Literal["configured", "unchanged", "extension", "clarification"]
    explanation: str = Field(min_length=1, max_length=2000)
    task_codes: list[str] = Field(default_factory=list, max_length=200)
    feature_keys: list[str] = Field(default_factory=list, max_length=30)


class RehearsalCase(Input):
    # Keep the frozen v1 model output shape; v2 uses the extended rehearsal model.
    name: str = Field(min_length=1, max_length=200)
    features: dict[str, bool] = Field(default_factory=dict, max_length=30)
    completed_codes: list[str] = Field(default_factory=list, max_length=200)
    expect_valid: bool = True
    expected_ready: dict[str, bool] = Field(default_factory=dict, max_length=200)


class ProcessTemplateAssessment(Input):
    summary: str = Field(min_length=1, max_length=2000)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    name_en: str | None = Field(default=None, min_length=1, max_length=200)
    task_upserts: list[ConfiguredTask] = Field(default_factory=list, max_length=200)
    task_removals: list[str] = Field(default_factory=list, max_length=200)
    feature_upserts: dict[str, ConfiguredFeature] = Field(default_factory=dict, max_length=30)
    extension_requests: list[RequirementText] = Field(default_factory=list, max_length=20)
    open_questions: list[RequirementText] = Field(default_factory=list, max_length=10)
    requirements: list[RequirementExplanation] = Field(min_length=1, max_length=50)
    cases: list[RehearsalCase] = Field(min_length=2, max_length=20)


V1 = "process-template-configuration-v1"
V2 = "process-template-configuration-v2"
V3 = "process-template-configuration-v3"
V4 = "process-template-configuration-v4"
V5 = "process-template-configuration-v5"
V6 = "process-template-configuration-v6"
V7 = "process-template-configuration-v7"
V8 = "process-template-configuration-v8"
V9 = "process-template-configuration-v9"


class RequirementExplanationV2(RequirementExplanation):
    stage_codes: list[str] = Field(default_factory=list, max_length=30)


class ProcessTemplateAssessmentV2(Input):
    summary: str = Field(min_length=1, max_length=2000)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    name_en: str | None = Field(default=None, min_length=1, max_length=200)
    task_upserts: list[ConfiguredTask] = Field(default_factory=list, max_length=200)
    task_removals: list[str] = Field(default_factory=list, max_length=200)
    feature_upserts: dict[str, ConfiguredFeature] = Field(default_factory=dict, max_length=30)
    stage_upserts: list[ConfiguredStage] = Field(default_factory=list, max_length=30)
    gate_requirements: GateRequirements | None = None
    extension_requests: list[RequirementText] = Field(default_factory=list, max_length=20)
    open_questions: list[RequirementText] = Field(default_factory=list, max_length=10)
    requirements: list[RequirementExplanationV2] = Field(min_length=1, max_length=50)
    cases: list[ConfiguredRehearsalCase] = Field(min_length=2, max_length=20)


class ProcessTemplateAssessmentV3(ProcessTemplateAssessmentV2):
    task_routes: dict[str, TaskRoute] | None = Field(default=None, max_length=200)
    routing_cases: list[RouteRehearsal] = Field(default_factory=list, max_length=20)


class ProcessTemplateAssessmentV4(ProcessTemplateAssessmentV3):
    reminder_policy: ReminderPolicy | None = None
    reminder_cases: list[ReminderRehearsal] = Field(default_factory=list, max_length=20)


class ProcessTemplateAssessmentV5(ProcessTemplateAssessmentV4):
    approval_routes: ApprovalRoutes | None = None
    approval_cases: list[ApprovalRehearsal] = Field(default_factory=list, max_length=100)


class ProcessTemplateAssessmentV6(ProcessTemplateAssessmentV5):
    issue_fields: list[IssueField] | None = Field(default=None, max_length=30)
    field_cases: list[FieldRehearsal] = Field(default_factory=list, max_length=100)


class ProcessTemplateAssessmentV7(ProcessTemplateAssessmentV6):
    task_fields: list[TaskField] | None = Field(default=None, max_length=30)
    task_field_cases: list[TaskFieldRehearsal] = Field(default_factory=list, max_length=100)


class ProcessTemplateAssessmentV8(ProcessTemplateAssessmentV7):
    named_gate_slots: NamedSlots | None = None
    signer_cases: list[SignerCase] = Field(default_factory=list, max_length=400)


class ProcessTemplateAssessmentV9(ProcessTemplateAssessmentV8):
    risk_fields: list[RiskField] | None = Field(default=None, max_length=30)
    risk_field_cases: list[RiskFieldRehearsal] = Field(default_factory=list, max_length=100)


Assessment = (
    ProcessTemplateAssessment
    | ProcessTemplateAssessmentV2
    | ProcessTemplateAssessmentV3
    | ProcessTemplateAssessmentV4
    | ProcessTemplateAssessmentV5
    | ProcessTemplateAssessmentV6
    | ProcessTemplateAssessmentV7
    | ProcessTemplateAssessmentV8
    | ProcessTemplateAssessmentV9
)


def output_type(
    version: str,
) -> type[Assessment]:
    if version == V1:
        return ProcessTemplateAssessment
    if version == V2:
        return ProcessTemplateAssessmentV2
    if version == V3:
        return ProcessTemplateAssessmentV3
    if version == V4:
        return ProcessTemplateAssessmentV4
    if version == V5:
        return ProcessTemplateAssessmentV5
    if version == V6:
        return ProcessTemplateAssessmentV6
    if version == V7:
        return ProcessTemplateAssessmentV7
    if version == V8:
        return ProcessTemplateAssessmentV8
    if version == V9:
        return ProcessTemplateAssessmentV9
    raise ProjectTemplateError("生成合同版本不受支持，不能用当前合同改写旧记录")


def materialize(source: dict[str, Any], assessment: Assessment) -> dict[str, Any]:
    """Calculate review evidence using exactly the frozen original template.

    Explanations and examples remain AI suggestions. A computed rehearsal is
    review evidence, not phase acceptance or permission to publish.
    """
    base = source["base_snapshot"]
    original = {task["code"]: task for task in base["tasks"]}
    upserts = {task.code: task.model_dump(mode="json") for task in assessment.task_upserts}
    removals = set(assessment.task_removals)
    if len(upserts) != len(assessment.task_upserts) or len(removals) != len(
        assessment.task_removals
    ):
        raise ProjectTemplateError("建议中含重复任务操作")
    if removals - original.keys() or removals & upserts.keys():
        raise ProjectTemplateError("建议移除的任务不存在或同时要求修改")
    tasks = {key: value for key, value in original.items() if key not in removals}
    tasks.update(upserts)
    extensions = list(
        dict.fromkeys(
            [
                *base.get("pending_extensions", []),
                *assessment.extension_requests,
                *("待澄清：" + question for question in assessment.open_questions),
            ]
        )
    )
    stages = base["stages"]
    gates = None
    if isinstance(assessment, ProcessTemplateAssessmentV2):
        updates = {stage.code: stage.model_dump(mode="json") for stage in assessment.stage_upserts}
        if len(updates) != len(assessment.stage_upserts) or updates.keys() - {
            stage["code"] for stage in stages
        }:
            raise ProjectTemplateError("阶段修改不能重复或增加未接通的阶段类型")
        stages = [updates.get(stage["code"], stage) for stage in stages]
        gates = assessment.gate_requirements
    configuration = TemplateConfiguration.model_validate(
        {
            "name": assessment.name or base["name"],
            "name_en": assessment.name_en or base["name_en"],
            "features": base["features"]
            | {
                key: value.model_dump(mode="json")
                for key, value in assessment.feature_upserts.items()
            },
            "tasks": list(tasks.values()),
            "stages": stages if isinstance(assessment, ProcessTemplateAssessmentV2) else None,
            "gate_requirements": gates,
            "task_routes": assessment.task_routes
            if isinstance(assessment, ProcessTemplateAssessmentV3)
            else None,
            "reminder_policy": assessment.reminder_policy
            if isinstance(assessment, ProcessTemplateAssessmentV4)
            else None,
            "approval_routes": assessment.approval_routes
            if isinstance(assessment, ProcessTemplateAssessmentV5)
            else None,
            "named_gate_slots": assessment.named_gate_slots
            if isinstance(assessment, ProcessTemplateAssessmentV8)
            else None,
            "risk_fields": assessment.risk_fields
            if isinstance(assessment, ProcessTemplateAssessmentV9)
            else None,
            "task_fields": assessment.task_fields
            if isinstance(assessment, ProcessTemplateAssessmentV7)
            else None,
            "issue_fields": assessment.issue_fields
            if isinstance(assessment, ProcessTemplateAssessmentV6)
            else None,
            "extension_requests": extensions,
        }
    )
    snapshot = configure(base, configuration, source["template_id"], 1)
    for explanation in assessment.requirements:
        if isinstance(explanation, RequirementExplanationV2) and set(explanation.stage_codes) - {
            stage["code"] for stage in stages
        }:
            raise ProjectTemplateError("要求说明引用了不存在的阶段")
        if explanation.quote not in source[explanation.source]:
            raise ProjectTemplateError("要求说明必须引用已保存的原文")
        if set(explanation.task_codes) - (original.keys() | tasks.keys()):
            raise ProjectTemplateError("要求说明引用了不存在的任务")
        if set(explanation.feature_keys) - configuration.features.keys():
            raise ProjectTemplateError("要求说明引用了不存在的功能条件")
        if explanation.disposition == "extension" and not assessment.extension_requests:
            raise ProjectTemplateError("无法表达的要求须列为待决扩展")
        if explanation.disposition == "clarification" and not assessment.open_questions:
            raise ProjectTemplateError("待澄清的要求须列出具体问题")
    result = {
        "configuration": configuration.model_dump(
            mode="json",
            exclude=(
                set()
                if isinstance(assessment, ProcessTemplateAssessmentV9)
                and assessment.risk_fields is not None
                else {"risk_fields"}
            )
            | (
                set()
                if isinstance(assessment, ProcessTemplateAssessmentV8)
                and assessment.named_gate_slots is not None
                else {"named_gate_slots"}
            )
            | (
                set()
                if isinstance(assessment, ProcessTemplateAssessmentV7)
                and assessment.task_fields is not None
                else {"task_fields"}
            )
            | (
                set()
                if isinstance(assessment, ProcessTemplateAssessmentV6)
                else {"issue_fields"}
                if isinstance(assessment, ProcessTemplateAssessmentV5)
                else {"approval_routes", "issue_fields"}
            ),
        ),
        "difference": {
            key: value
            for key, value in configuration_difference(base, snapshot).items()
            if (isinstance(assessment, ProcessTemplateAssessmentV6) or key != "issue_field_changes")
            and (
                isinstance(assessment, ProcessTemplateAssessmentV5)
                or key != "approval_route_changes"
            )
        },
        "rehearsal": rehearse(
            snapshot,
            [
                ConfiguredRehearsalCase.model_validate(case.model_dump())
                for case in assessment.cases
            ],
        ),
        "pending_extensions": extensions,
    }

    if isinstance(assessment, ProcessTemplateAssessmentV3):
        result["routing_rehearsal"] = rehearse_routes(snapshot, assessment.routing_cases)
    if isinstance(assessment, ProcessTemplateAssessmentV4):
        result["reminder_rehearsal"] = rehearse_reminders(snapshot, assessment.reminder_cases)
    if isinstance(assessment, ProcessTemplateAssessmentV5):
        result["approval_rehearsal"] = rehearse_approvals(snapshot, assessment.approval_cases)
    if isinstance(assessment, ProcessTemplateAssessmentV6):
        result["field_rehearsal"] = rehearse_fields(snapshot, assessment.field_cases)
    if isinstance(assessment, ProcessTemplateAssessmentV7):
        result["task_field_rehearsal"] = rehearse_task_fields(snapshot, assessment.task_field_cases)
    if isinstance(assessment, ProcessTemplateAssessmentV8):
        result["signer_rehearsal"] = rehearse_signers(snapshot, assessment.signer_cases)
    if isinstance(assessment, ProcessTemplateAssessmentV9):
        result["risk_field_rehearsal"] = rehearse_risk_fields(snapshot, assessment.risk_field_cases)
    return result
