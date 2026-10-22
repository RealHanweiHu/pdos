"""Small closed rules for a physical ready/hold event, never sample acceptance."""

import json
from datetime import UTC, datetime

from pdos_next.errors import DomainError


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate event key")
        value[key] = item
    return value


def validate_event(payload, *, lot_id, actual_configuration_id, build_id, line):
    """The whole cited line must state the same physical event, with no extra keys."""
    keys = {
        "sample_id",
        "lot_id",
        "actual_configuration_id",
        "build_id",
        "state",
        "purpose",
        "occurred_at",
    }
    try:
        if payload.event_source.quote.strip() != line.strip():
            raise ValueError("not a whole event line")
        event = json.loads(line, object_pairs_hook=_unique_object)
        if not isinstance(event, dict) or set(event) != keys:
            raise ValueError("closed event fields required")
        expected = {
            "sample_id": str(payload.sample_id),
            "lot_id": str(lot_id),
            "actual_configuration_id": str(actual_configuration_id),
            "build_id": str(build_id),
            "state": payload.state,
            "purpose": payload.purpose,
        }
        if any(event[key] != value for key, value in expected.items()):
            raise ValueError("event identity differs")
        if not isinstance(event["occurred_at"], str):
            raise ValueError("event time missing")
        occurred = datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00"))
        if occurred.tzinfo is None or occurred.utcoffset() is None:
            raise ValueError("event time naive")
        if occurred.astimezone(UTC) != payload.occurred_at:
            raise ValueError("event time differs")
    except (ValueError, TypeError, KeyError, OverflowError):
        raise DomainError(
            "SAMPLE_EVENT_MISMATCH",
            "原文须以完整事件JSON固定同一样件、批次、实际配置、轮次、状态、用途与发生时点。",
            422,
        ) from None


def validate_time(occurred, *, at, actual_at, lot_at, start_at=None, previous_at=None):
    if occurred > at:
        raise DomainError("SAMPLE_EVENT_IN_FUTURE", "实物状态只能记录已发生的事件。", 422)
    if occurred < max(actual_at, lot_at):
        raise DomainError(
            "SAMPLE_EVENT_BEFORE_OUTPUT", "实物状态不能早于实际配置观察和批次产出。", 422
        )
    if start_at is not None and occurred < start_at:
        raise DomainError("SAMPLE_EVENT_BEFORE_START", "可交样事件不能早于本轮真实开工。", 422)
    if previous_at is not None and occurred <= previous_at:
        raise DomainError(
            "SAMPLE_EVENT_NOT_NEWER", "继版实物状态必须比当前事实更新，不能回填旧事件回退状态。"
        )


def availability(state, fixed_purpose, requested_purpose, *, current):
    if not current:
        return "unknown"
    if state == "hold":
        return "hold"
    return "ready" if state == "ready" and fixed_purpose == requested_purpose else "unknown"


def require_manufacturing(authority):
    if not (
        authority.get("authorized") is True
        and authority.get("qualified") is True
        and "manufacturing" in authority.get("roles", [])
    ):
        raise DomainError(
            "MANUFACTURING_AUTHORITY_REQUIRED",
            "须当前具名制造职责及针对本用途的有效资格；产品写权限不替代专业权威。",
            403,
        )
