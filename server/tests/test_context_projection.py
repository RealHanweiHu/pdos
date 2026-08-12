from __future__ import annotations

import pytest

from app.ai.context_projection import ContextProjectionError, project_gateway_context


def test_project_gateway_context_only_emits_explicitly_allowlisted_structure() -> None:
    projection = project_gateway_context(
        {
            "project": {
                "id": "project-1",
                "code": "PRJ-001",
                "name": "Motor Controller",
                "status": "active",
                "current_stage": {"code": "dvt", "name": "DVT", "sequence": 5},
                "confidential_notes": "do not send",
            },
            "execution": {
                "open_issue_count": 2,
                "issues_created_last_7_days": 1,
                "open_risk_count": 1,
                "overdue_task_count": 3,
                "stage_progress_percent": 71,
                "next_gate_due_in_days": 4,
                "remaining_tokens_today": 1_500_000,
                "agent_runs_today": 2,
                "raw_issue_text": "sensitive original text",
            },
            "trigger": {
                "event_type": "ISSUE_CREATED",
                "entity": "issue",
                "entity_id": "issue-1",
                "timestamp": "2026-08-11T20:00:00Z",
                "payload": {"description": "raw source"},
            },
            "references": [
                {
                    "entity": "issue",
                    "entity_id": "issue-1",
                    "label": "ISS-001",
                    "object_storage_key": "tenant/project/private.pdf",
                }
            ],
            "api_key": "must-never-leave",
            "document_original": "must-never-leave",
        }
    )

    assert projection.payload == {
        "project": {
            "id": "project-1",
            "code": "PRJ-001",
            "name": "Motor Controller",
            "status": "active",
            "current_stage": {"code": "dvt", "name": "DVT", "sequence": 5},
        },
        "execution": {
            "open_issue_count": 2,
            "issues_created_last_7_days": 1,
            "open_risk_count": 1,
            "overdue_task_count": 3,
            "stage_progress_percent": 71,
            "next_gate_due_in_days": 4,
            "remaining_tokens_today": 1_500_000,
            "agent_runs_today": 2,
        },
        "trigger": {
            "event_type": "ISSUE_CREATED",
            "entity": "issue",
            "entity_id": "issue-1",
            "timestamp": "2026-08-11T20:00:00Z",
        },
        "references": [{"entity": "issue", "entity_id": "issue-1", "label": "ISS-001"}],
    }
    assert set(projection.removed_paths) == {
        "api_key",
        "document_original",
        "execution.raw_issue_text",
        "project.confidential_notes",
        "references[0].object_storage_key",
        "trigger.payload",
    }


def test_project_gateway_context_rejects_non_json_values_in_allowed_fields() -> None:
    with pytest.raises(ContextProjectionError, match="project.id must be JSON-safe"):
        project_gateway_context({"project": {"id": object()}})


def test_project_gateway_context_rejects_wrong_container_shapes() -> None:
    with pytest.raises(ContextProjectionError, match="references must be a list"):
        project_gateway_context({"references": {"entity": "issue"}})
