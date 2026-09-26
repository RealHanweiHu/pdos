"""Deterministic allowlist projection for context that may leave PDOS."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type ProjectionPolicy = None | dict[str, ProjectionPolicy] | tuple[dict[str, ProjectionPolicy]]


class ContextProjectionError(ValueError):
    """Raised when an allowlisted field does not have its frozen JSON shape."""


@dataclass(frozen=True)
class ContextProjection:
    payload: dict[str, JsonValue]
    removed_paths: tuple[str, ...]


PROJECT_GATEWAY_POLICY: dict[str, ProjectionPolicy] = {
    "loop": {"step": None, "step_limit": None},
    "tool_observations": (
        {
            "tool": None,
            "status": None,
            "shown_count": None,
            "total_count": None,
            "truncated": None,
            "continuation": None,
            "error_code": None,
            "request": {
                "name": None,
                "query": None,
                "after_id": None,
                "offset": None,
                "limit": None,
            },
        },
    ),
    "question": None,
    "test_plan": {
        "product_type": None,
        "previous_proposal": None,
        "items": (
            {
                "key": None,
                "title": None,
                "category": None,
                "method": None,
                "acceptance_criteria": None,
                "required": None,
                "applicable": None,
                "exclusion_reason": None,
                "applicability": None,
                "evidence_requirements": None,
            },
        ),
    },
    "project": {
        "id": None,
        "code": None,
        "name": None,
        "status": None,
        "current_stage": {
            "code": None,
            "name": None,
            "sequence": None,
        },
    },
    "execution": {
        "open_issue_count": None,
        "issues_created_last_7_days": None,
        "open_risk_count": None,
        "overdue_task_count": None,
        "stage_progress_percent": None,
        "next_gate_due_in_days": None,
        "remaining_tokens_today": None,
        "agent_runs_today": None,
    },
    "trigger": {
        "event_type": None,
        "entity": None,
        "entity_id": None,
        "timestamp": None,
    },
    "references": (
        {
            "reference_id": None,
            "entity": None,
            "entity_id": None,
            "label": None,
            "href": None,
            "excerpt": None,
        },
    ),
    "multimodal": {
        "status": None,
        "documents": (
            {
                "document_id": None,
                "filename": None,
                "media_type": None,
                "extraction_status": None,
                "fragments": (
                    {
                        "reference_id": None,
                        "document_id": None,
                        "ordinal": None,
                        "locator": None,
                        "excerpt": None,
                    },
                ),
                "shown_fragment_count": None,
                "total_fragment_count": None,
                "truncated": None,
            },
        ),
        "requested_document_count": None,
        "available_document_count": None,
        "unavailable_document_count": None,
        "shown_fragment_count": None,
        "total_fragment_count": None,
        "truncated": None,
    },
    "user": {
        "perspective_role": None,
        "role_lens": None,
        "project_roles": (
            {
                "role": None,
                "active_member_count": None,
            },
        ),
        "decision_mode": None,
        "review_required": None,
        "apply_requires_separate_human_action": None,
    },
}


def _path(parent: str, child: str) -> str:
    return f"{parent}.{child}" if parent else child


def _project_mapping(
    source: Mapping[Any, object],
    policy: dict[str, ProjectionPolicy],
    *,
    parent_path: str,
    removed_paths: list[str],
) -> dict[str, JsonValue]:
    output: dict[str, JsonValue] = {}
    for raw_key, value in source.items():
        key = str(raw_key)
        current_path = _path(parent_path, key)
        if key not in policy:
            removed_paths.append(current_path)
            continue
        output[key] = _project_value(
            value,
            policy[key],
            path=current_path,
            removed_paths=removed_paths,
        )
    return output


def _project_value(
    value: object,
    policy: ProjectionPolicy,
    *,
    path: str,
    removed_paths: list[str],
) -> JsonValue:
    if policy is None:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        raise ContextProjectionError(f"{path} must be JSON-safe")
    if isinstance(policy, dict):
        if not isinstance(value, Mapping):
            raise ContextProjectionError(f"{path} must be an object")
        return _project_mapping(
            value,
            policy,
            parent_path=path,
            removed_paths=removed_paths,
        )
    if not isinstance(value, list):
        raise ContextProjectionError(f"{path} must be a list")
    item_policy = policy[0]
    projected_items: list[JsonValue] = []
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        if not isinstance(item, Mapping):
            raise ContextProjectionError(f"{item_path} must be an object")
        projected_items.append(
            _project_mapping(
                item,
                item_policy,
                parent_path=item_path,
                removed_paths=removed_paths,
            )
        )
    return projected_items


def project_gateway_context(source: Mapping[str, object]) -> ContextProjection:
    """Return the only context shape permitted to cross the model gateway."""

    removed_paths: list[str] = []
    payload = _project_mapping(
        source,
        PROJECT_GATEWAY_POLICY,
        parent_path="",
        removed_paths=removed_paths,
    )
    return ContextProjection(payload=payload, removed_paths=tuple(sorted(removed_paths)))
