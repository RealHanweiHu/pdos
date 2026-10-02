"""Resolve a generated draft's route from server-owned sources, never HTTP flags."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection

from app.ai.observations import digest
from app.ai.write_policy import OperationSetting, TenantWriteMode, decide_write
from app.domain.ai_meeting_write_monitor import quality_monitor, sampled_draft
from app.domain.ai_meeting_write_readiness import assess_generated_write
from app.domain.ai_write_qualification_state import QualificationState


def resolve_direct_route(
    c: Connection, *, draft: dict[str, Any], setting: dict[str, Any], as_of: datetime
) -> dict[str, Any]:
    """Caller has verified live rollout, current source and independent AI scope.

    The tenant's explicit automatic preference is the authorization; current
    trusted evidence supplies qualification, not a model's confidence. Persist
    this exact decision with the immutable draft in the same transaction.
    """
    readiness = assess_generated_write(c, draft=draft, as_of=as_of)
    receipt: dict[str, Any] = {
        "version": "dc11-meeting-write-execution.v1",
        "route": "confirm",
        "reason": "qualification_required",
        "reason_label": "自动写入材料尚未满足，已转为逐次确认。",
        "sampled": False,
        "checked_at": as_of.isoformat(),
        "readiness": readiness,
    }
    if readiness["state"] != "current" or readiness.get("qualification_state") is None:
        return receipt
    state = QualificationState.model_validate(readiness["qualification_state"])
    if (
        state.state != "current"
        or state.configuration is None
        or state.policy_id != draft["policy_id"]
        or state.tenant_id != draft["tenant_id"]
        or state.project_id != draft["project_id"]
    ):
        return receipt
    binding_digest = digest(state.binding.model_dump(mode="json"))
    monitor = quality_monitor(
        c,
        tenant_id=draft["tenant_id"],
        project_id=draft["project_id"],
        policy_id=draft["policy_id"],
        operation_key=state.operation_key,
        binding_digest=binding_digest,
        configuration=state.configuration,
        as_of=as_of,
    )
    receipt.update(
        binding_digest=binding_digest,
        configuration=state.configuration.model_dump(mode="json"),
        monitor=monitor,
    )
    decision = decide_write(
        state.operation_key,
        tenant_mode=TenantWriteMode.TIERED,
        setting=OperationSetting.model_validate(setting),
        rollout_live=True,
        principal_scope_valid=True,
        sources_current=True,
        qualification_current=not monitor["stopped"],
    )
    if decision.route != "direct":
        receipt["reason"] = "quality_stop" if monitor["stopped"] else decision.reason
        receipt["reason_label"] = (
            "自动草稿撤回比例超过门槛，已暂停自动写入并转为逐次确认。"
            "原草稿和回执保留；须按恢复协议重新核对政策与试运行。"
            if monitor["stopped"]
            else "当前写入条件未满足，已转为逐次确认。"
        )
        return receipt
    receipt.update(
        route="direct",
        reason="qualified_direct_write",
        reason_label="AI已写入草稿。",
        sampled=sampled_draft(UUID(str(draft["id"])), state.configuration),
        policy_id=str(draft["policy_id"]),
        scope_revision_id=str(draft["scope_revision_id"]),
        writer_principal_id=str(draft["principal_id"]),
        requested_by_user_id=str(draft["requested_by_user_id"]),
    )
    return receipt
