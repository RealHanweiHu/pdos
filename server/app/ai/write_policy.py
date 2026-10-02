"""DC-11 object/operation policy. Declarations never grant execution authority.

Read-only capabilities have no write tier. T0 describes the maximum permitted
operation; rollout, the tenant switch, an independent principal's scope, current
sources and version-bound qualification must all pass before direct execution.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field


class WriteTier(StrEnum):
    T0 = "t0"
    T1 = "t1"
    T2 = "t2"


class WriteMode(StrEnum):
    DISABLED = "disabled"
    CONFIRM = "confirm"
    AUTOMATIC = "automatic"


class TenantWriteMode(StrEnum):
    LEGACY = "legacy"
    TIERED = "tiered"


class WriteOperation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    label: str
    object_type: str
    action: str
    write_tier: WriteTier
    capability_key: str | None = None
    effect: str
    # Wired execution adapters explicitly opt in; a governance preference cannot
    # promote an unfinished adapter or an existing human apply command.
    adapter_ready: bool = False
    trial_ready: bool = False


_OPERATIONS = (
    WriteOperation(
        adapter_ready=True,
        trial_ready=True,
        key="meeting.minutes.draft",
        label="会议纪要草稿",
        object_type="meeting_minutes",
        action="draft",
        write_tier=WriteTier.T0,
        capability_key="knowledge_lite.meeting_minutes",
        effect="整理原转录引用，保存可撤回的草稿。",
    ),
    WriteOperation(
        adapter_ready=True,
        trial_ready=True,
        key="meeting.actions.draft",
        label="会议行动项草稿",
        object_type="meeting_action",
        action="draft",
        write_tier=WriteTier.T0,
        capability_key="knowledge_lite.meeting_actions",
        effect="提取行动项草稿；正式下达仍由人确认。",
    ),
    WriteOperation(
        adapter_ready=True,
        trial_ready=True,
        key="meeting.decisions.draft",
        label="会议决策草稿",
        object_type="meeting_decision",
        action="draft",
        write_tier=WriteTier.T0,
        capability_key="knowledge_lite.meeting_decisions",
        effect="记录讨论中的决策候选，保留逐条原文依据。",
    ),
    WriteOperation(
        adapter_ready=True,
        trial_ready=True,
        key="event.issue.create",
        capability_key="quality_intelligence.event_issue",
        label="事件自动建单",
        object_type="issue",
        action="create_from_event",
        write_tier=WriteTier.T0,
        effect="按测试失败或物料异常建单，同一来源事件去重。",
    ),
    WriteOperation(
        key="record.ai_fields.update",
        label="AI 维护字段",
        object_type="ai_fields",
        action="update",
        write_tier=WriteTier.T0,
        effect="更新 AI 摘要与分类；人工编辑后停止覆盖，业务状态单独保留。",
    ),
    WriteOperation(
        key="report.weekly.draft",
        label="周报初稿",
        object_type="weekly_report",
        action="draft",
        write_tier=WriteTier.T0,
        effect="汇总有据可查的周报草稿，正式发布与外发仍由人办理。",
    ),
    WriteOperation(
        key="test_report.rows.confirm",
        label="报告导入整批确认",
        object_type="test_report",
        action="confirm_rows",
        write_tier=WriteTier.T1,
        capability_key="quality_intelligence.test_report_import",
        effect="高置信行预选、低置信行提示，由人整批确认。",
    ),
    WriteOperation(
        key="formal_action.execute",
        label="正式裁决与对外动作",
        object_type="formal_record",
        action="execute",
        write_tier=WriteTier.T2,
        effect="签核、批准、基线、发布、外发、账号凭据与不可逆删除均由具名人员办理。",
    ),
)
WRITE_OPERATIONS = MappingProxyType({item.key: item for item in _OPERATIONS})
POLICY_VERSION = "dc11-write-policy.v1"


def operation_keys_for_capability(capability_key: str) -> tuple[str, ...]:
    return tuple(item.key for item in _OPERATIONS if item.capability_key == capability_key)


class OperationSetting(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: WriteMode = WriteMode.DISABLED
    minimum_confirmation_basis_points: int = Field(default=9000, ge=9000, le=10000)
    maximum_retraction_basis_points: int = Field(default=500, ge=0, le=500)


def default_settings() -> dict[str, OperationSetting]:
    return {
        key: OperationSetting()
        for key, operation in WRITE_OPERATIONS.items()
        if operation.write_tier is not WriteTier.T2
    }


def validate_settings(settings: dict[str, OperationSetting]) -> None:
    if set(settings) != set(default_settings()):
        raise ValueError("须完整保存已登记的操作设置，正式裁决不能授予 AI")
    for key, setting in settings.items():
        if WRITE_OPERATIONS[key].write_tier is WriteTier.T1 and setting.mode is WriteMode.AUTOMATIC:
            raise ValueError("报告导入须保留人工整批确认")


class WriteDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    route: str
    reason: str


def decide_write(
    operation_key: str,
    *,
    tenant_mode: TenantWriteMode,
    setting: OperationSetting,
    rollout_live: bool,
    principal_scope_valid: bool,
    sources_current: bool,
    qualification_current: bool,
    human_edited: bool = False,
) -> WriteDecision:
    """Runtime gate for trusted adapters; it never executes a business mutation.

    Qualification must be loaded from persisted, version-matching evaluation
    and trial receipts by the adapter, never accepted from a model or HTTP body.
    An unregistered object/operation is not covered by the T0 allowlist.
    """
    operation = WRITE_OPERATIONS.get(operation_key)
    if operation is None:
        return WriteDecision(route="blocked", reason="operation_unregistered")
    if operation.write_tier is WriteTier.T2:
        return WriteDecision(route="human", reason="human_decision_required")
    if tenant_mode is TenantWriteMode.LEGACY:
        return WriteDecision(route="legacy", reason="legacy_policy")
    if setting.mode is WriteMode.DISABLED:
        return WriteDecision(route="blocked", reason="operation_disabled")
    if not operation.adapter_ready:
        return WriteDecision(route="blocked", reason="adapter_pending")
    if not rollout_live:
        return WriteDecision(route="blocked", reason="rollout_not_live")
    if not principal_scope_valid:
        return WriteDecision(route="exception", reason="principal_scope_missing")
    if not sources_current:
        return WriteDecision(route="exception", reason="source_changed")
    if human_edited:
        return WriteDecision(route="exception", reason="human_edit_preserved")
    if operation.write_tier is WriteTier.T1 or setting.mode is WriteMode.CONFIRM:
        return WriteDecision(route="confirm", reason="human_confirmation_required")
    if not qualification_current:
        return WriteDecision(route="exception", reason="qualification_required")
    return WriteDecision(route="direct", reason="qualified_direct_write")
