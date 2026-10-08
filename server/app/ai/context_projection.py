"""Deterministic allowlist projection for context that may leave PDOS."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type ProjectionPolicy = None | dict[str, ProjectionPolicy] | tuple[ProjectionPolicy]


class ContextProjectionError(ValueError):
    """Raised when an allowlisted field does not have its frozen JSON shape."""


@dataclass(frozen=True)
class ContextProjection:
    payload: dict[str, JsonValue]
    removed_paths: tuple[str, ...]


# Explicit domain fields; internal membership, credentials and audit identities
# in category_bundle remain outside the model projection.
_PARAMETER_POLICY: dict[str, ProjectionPolicy] = {
    key: None
    for key in (
        "key",
        "label",
        "unit",
        "conditions",
        "direction",
        "verification_method",
        "acceptance_criterion",
    )
}
_NOTE_POLICY: dict[str, ProjectionPolicy] = {
    **{key: None for key in ("kind", "title", "body", "state")},
    "citation_ids": (None,),
}
_CATEGORY_POLICY: dict[str, ProjectionPolicy] = {
    "code": None,
    "title": None,
    **{key: (None,) for key in ("user_groups", "regions", "use_scenarios", "research_questions")},
    "parameters": (_PARAMETER_POLICY,),
    "notes": (_NOTE_POLICY,),
}
_PROPOSAL_DOCUMENT_POLICY: dict[str, ProjectionPolicy] = {
    "narrative": None,
    "questions": (None,),
    "risks": (None,),
    **{
        key: ({**{field: None for field in fields}, "source_ids": (None,)},)
        for key, fields in {
            "specifications": (
                "parameter_id",
                "parameter_version",
                "direction",
                "id",
                "label",
                "value",
                "unit",
                "conditions",
                "state",
            ),
            "options": (
                "key",
                "name",
                "audience",
                "positioning",
                "use_path",
                "price_band",
                "tradeoffs",
            ),
            "differences": ("area", "baseline", "proposed", "impact"),
            "competitors": (
                "name",
                "audience",
                "use_path",
                "price_band",
                "strengths",
                "pain_points",
                "comparison_basis",
            ),
            "user_voices": ("quote", "context", "pain_point"),
        }.items()
    },
}
_PREPROJECT_POLICY: dict[str, ProjectionPolicy] = {
    "goal": None,
    "user_brief": None,
    "previous_assessment": {
        "goal": None,
        "stage": None,
        "candidate_digest": None,
        "questions": ({"id": None, "question": None, "options": (None,), "recommendation": None},),
        "category": _CATEGORY_POLICY,
        "proposal": {"title": None, "entry_kind": None, "document": _PROPOSAL_DOCUMENT_POLICY},
    },
    "category": {
        **{key: None for key in ("category_id", "category_line_id", "category_name")},
        **{
            key: (None,)
            for key in ("user_groups", "regions", "use_scenarios", "research_questions")
        },
        "parameters": ({**_PARAMETER_POLICY, "parameter_id": None, "version": None},),
        "knowledge": (
            {
                **{key: None for key in ("id", "kind", "title", "body")},
                "regions": (None,),
                "source_refs": (
                    {
                        key: None
                        for key in ("kind", "ref_id", "version", "as_of", "digest", "locator")
                    },
                ),
            },
        ),
        "research_drafts": (
            {
                "public_data": {
                    "notes": (_NOTE_POLICY,),
                    "citations": ({"reference_id": None, "label": None, "href": None},),
                    "remaining_questions": (None,),
                    "coverage": None,
                }
            },
        ),
    },
}


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
    "history": ({"role": None, "content": None},),
    "history_truncated": None,
    "preproject": _PREPROJECT_POLICY,
    "research": {
        **{
            key: None
            for key in (
                "remaining",
                "search_remaining",
                "read_remaining",
                "searches",
                "read_attempts",
                "sources_read",
                "candidate_count",
                "candidates_truncated",
            )
        },
        "candidates": ({"url": None, "title": None, "snippet": None},),
        "last_action": ({"action": None, "target": None, "status": None},),
        "failures": (
            {
                key: None
                for key in ("tool", "target", "source_host", "error_code", "reason", "attribution")
            },
        ),
        "observations": (
            {
                "tool": None,
                "target": None,
                "status": None,
                "warnings": None,
                "provider_key": None,
                "providers_tried": (None,),
                "error_code": None,
                "shown_count": None,
                "total_count": None,
            },
        ),
    },
    "report_mapping": {
        "headers": ({"column": None},),
        "sample_rows": ({"row": None, "cells": ({"column": None, "value": None},)},),
        "total_rows": None,
    },
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
        "events": ({"event_id": None},),
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
            "source_host": None,
            "title_origin": None,
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
    if value is None:
        return None
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
        projected_items.append(
            _project_value(item, item_policy, path=item_path, removed_paths=removed_paths)
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
