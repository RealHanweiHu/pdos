"""Immutable generation-time policy evidence for event Issue proposals, never a grant."""

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Connection, select

from app.ai.capability_contract import resolve_capability
from app.ai.issue_event_proposal import KEY, OPERATION
from app.ai.write_policy import POLICY_VERSION, WRITE_OPERATIONS
from app.db.schema import tables
from app.domain.product_workspace import _plain

VERSION = "event-issue-generation-binding-v1"
REASONS = {
    "trial_candidate": "生成时已固定试运行政策与项目授权；实际办理仍须核对当前条件，不代表自动资格",
    "policy_missing": "生成时尚未登记写入政策，仅保留建议证据",
    "policy_contract_unknown": "生成时政策合同版本不可识别，仅保留建议证据",
    "policy_not_tiered": "生成时未采用分级写入政策，仅保留建议证据",
    "operation_not_enabled": "生成时未启用此操作，仅保留建议证据",
    "principal_unverified": "生成时独立 AI 身份不可核对，仅保留建议证据",
    "scope_not_enabled": "生成时此项目未有效授权该 AI 操作，仅保留建议证据",
    "rollout_not_live": "生成时能力未开放正式运行，仅保留建议证据",
    "trial_not_ready": "生成时试运行适配尚未就绪，仅保留建议证据",
    "not_recorded": "此历史运行未固定生成时政策与授权，不补记为试运行候选",
}


def read_for_run(c: Connection, row: Any) -> dict[str, Any] | None:
    t = tables.ai_issue_generation_bindings
    original = (
        c.execute(
            select(t).where(
                t.c.tenant_id == row["tenant_id"],
                t.c.project_id == row["project_id"],
                t.c.run_id == row["id"],
                t.c.requested_by_user_id == row["requested_by_user_id"],
            )
        )
        .mappings()
        .one_or_none()
    )
    return dict(original) if original is not None else None


def capture(
    c: Connection, row: Any, source_snapshot: dict[str, Any], now: datetime
) -> dict[str, Any]:
    """Called only for a new run under the caller's tenant-then-project write locks."""
    if (
        source_snapshot.get("tenant_id") != str(row["tenant_id"])
        or source_snapshot.get("project_id") != str(row["project_id"])
        or row["run_context"].get("issue_event_source") != source_snapshot
    ):
        raise ValueError("生成绑定与原运行来源不一致")
    original = read_for_run(c, row)
    if original is not None:
        if (
            original["event_row_id"] != source_snapshot["event_row_id"]
            or original["source_digest"] != source_snapshot["source_digest"]
        ):
            raise ValueError("原生成绑定不得替换")
        return original
    policy_table = tables.ai_write_policies
    policy = (
        c.execute(
            select(policy_table)
            .where(policy_table.c.tenant_id == row["tenant_id"])
            .order_by(policy_table.c.revision.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    principal = scope = None
    if policy is not None:
        p = tables.ai_principals
        principal = (
            c.execute(
                select(p).where(p.c.tenant_id == row["tenant_id"], p.c.id == policy["principal_id"])
            )
            .mappings()
            .one_or_none()
        )
    s = tables.ai_write_scope_revisions
    scope = (
        c.execute(
            select(s)
            .where(
                s.c.tenant_id == row["tenant_id"],
                s.c.project_id == row["project_id"],
                s.c.operation_key == OPERATION,
            )
            .order_by(s.c.revision.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    operation = WRITE_OPERATIONS.get(OPERATION)
    rollout = resolve_capability(KEY).rollout.value
    trial_ready = operation is not None and operation.trial_ready
    setting = policy["operation_settings"].get(OPERATION) if policy is not None else None
    reason = (
        "policy_missing"
        if policy is None
        else "policy_contract_unknown"
        if policy["contract_version"] != POLICY_VERSION
        else "policy_not_tiered"
        if policy["mode"] != "tiered"
        else "operation_not_enabled"
        if not isinstance(setting, dict) or setting.get("mode") not in {"confirm", "automatic"}
        else "principal_unverified"
        if principal is None
        or principal["principal_kind"] != "ai"
        or principal["principal_key"] != "pdos-agent"
        else "scope_not_enabled"
        if scope is None or not scope["enabled"] or scope["principal_id"] != principal["id"]
        else "rollout_not_live"
        if rollout != "live"
        else "trial_not_ready"
        if not trial_ready
        else "trial_candidate"
    )
    policy_snapshot = (
        {
            **{
                k: policy[k]
                for k in (
                    "id",
                    "principal_id",
                    "contract_version",
                    "revision",
                    "mode",
                    "created_at",
                )
            },
            "operation_key": OPERATION,
            "operation_setting": setting,
        }
        if policy is not None
        else None
    )
    scope_snapshot = (
        {
            k: scope[k]
            for k in ("id", "revision", "principal_id", "operation_key", "enabled", "created_at")
        }
        if scope is not None
        else None
    )
    snapshot = _plain(
        {
            "version": VERSION,
            "operation_key": OPERATION,
            "tenant_id": row["tenant_id"],
            "project_id": row["project_id"],
            "run_id": row["id"],
            "request_id": row["request_id"],
            "requested_by_user_id": row["requested_by_user_id"],
            "run_version": row["context_version"],
            "run_created_at": row["created_at"],
            "event_row_id": source_snapshot["event_row_id"],
            "event_id": source_snapshot["event_id"],
            "source_digest": source_snapshot["source_digest"],
            "source_kind": source_snapshot["source_kind"],
            "source_key": source_snapshot["source_key"],
            "policy": policy_snapshot,
            "scope": scope_snapshot,
            "principal": {
                k: principal[k] for k in ("id", "principal_key", "principal_kind", "display_name")
            }
            if principal is not None
            else None,
            "rollout": rollout,
            "trial_ready": trial_ready,
        }
    )
    value = {
        "id": uuid4(),
        "tenant_id": row["tenant_id"],
        "project_id": row["project_id"],
        "run_id": row["id"],
        "requested_by_user_id": row["requested_by_user_id"],
        "event_row_id": source_snapshot["event_row_id"],
        "source_digest": source_snapshot["source_digest"],
        "policy_id": policy["id"] if policy is not None else None,
        "principal_id": principal["id"] if principal is not None else None,
        "scope_revision_id": scope["id"] if scope is not None else None,
        "capture_kind": "trial_candidate" if reason == "trial_candidate" else "evidence_only",
        "reason_code": reason,
        "snapshot": snapshot,
        "created_at": now,
    }
    c.execute(tables.ai_issue_generation_bindings.insert().values(**value))
    return value


def summary(binding: dict[str, Any] | None) -> dict[str, Any]:
    if binding is None:
        return {
            "status": "not_recorded",
            "binding_id": None,
            "capture_kind": None,
            "reason_code": "not_recorded",
            "reason": REASONS["not_recorded"],
            "policy_id": None,
            "principal_id": None,
            "scope_revision_id": None,
            "created_at": None,
            "policy": None,
            "scope": None,
            "rollout": None,
            "trial_ready": None,
        }
    snapshot = binding["snapshot"]
    return _plain(
        {
            "status": binding["capture_kind"],
            "binding_id": binding["id"],
            **{
                key: binding[key]
                for key in (
                    "capture_kind",
                    "reason_code",
                    "policy_id",
                    "principal_id",
                    "scope_revision_id",
                    "created_at",
                )
            },
            "reason": REASONS.get(binding["reason_code"], "原生成绑定需要核对"),
            **{key: snapshot.get(key) for key in ("policy", "scope", "rollout", "trial_ready")},
        }
    )
