"""Pure admission limits over owner-read current facts; no authority or run creation."""

from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID

from pdos_next.errors import DomainError

from .schemas import AutomationSpec, Trigger


def _require(condition, message, code, status=409):
    if not condition:
        raise DomainError(code, message, status)


def _instant(value):
    _require(
        isinstance(value, datetime) and value.utcoffset() is not None,
        "自动化限额须使用服务器的明确时区时刻。",
        "VALIDATION_FAILED",
        422,
    )
    return value.astimezone(UTC)


def validate_admission(
    current: Mapping, trigger: Trigger, *, spec: AutomationSpec, at: datetime
) -> None:
    """Check one new admission; the owner locks, deduplicates and records it atomically.

    A successful return is not service authorization. The caller must also verify
    the actual published spec, skills, source scope and available budget. Original
    request replay is resolved by that owner before invoking these new-run limits.
    """
    trigger = Trigger.model_validate(trigger)
    spec = AutomationSpec.model_validate(spec)
    required = {
        "state",
        "revision",
        "published_version_id",
        "admitted_count",
        "last_admitted_at",
    }
    _require(
        isinstance(current, Mapping) and required <= current.keys(),
        "自动化当前记录缺少实际受理水位。",
        "INTEGRITY_MISMATCH",
    )
    revision = current["revision"]
    _require(
        type(revision) is int and revision > 0,
        "自动化当前版本无效。",
        "INTEGRITY_MISMATCH",
    )
    _require(
        revision == trigger.expected_rule_revision,
        "自动化规则已变化，请读取当前版本。",
        "VERSION_CONFLICT",
    )
    published = current["published_version_id"]
    try:
        published = UUID(str(published)) if published is not None else None
    except (ValueError, TypeError, AttributeError):
        raise DomainError("INTEGRITY_MISMATCH", "自动化发布版本无法核对。") from None
    _require(
        published == trigger.version_id,
        "触发须固定当前已发布规则版本。",
        "VERSION_CONFLICT",
    )
    _require(current["state"] == "active", "自动化规则当前未激活。", "INVALID_STATE")
    count, last = current["admitted_count"], current["last_admitted_at"]
    _require(
        type(count) is int and count >= 0 and ((count == 0) == (last is None)),
        "自动化次数与最后受理时刻不一致。",
        "INTEGRITY_MISMATCH",
    )
    point = _instant(at)
    if last is not None:
        last = _instant(last)
        _require(point >= last, "服务器时刻早于已受理记录，请核对。", "VERSION_CONFLICT")
    _require(count < spec.max_runs, "自动化已达到累计受理次数上限。", "RATE_LIMITED")
    _require(
        last is None or (point - last).total_seconds() >= spec.cooldown_seconds,
        "自动化尚在冷却期内。",
        "RATE_LIMITED",
    )
