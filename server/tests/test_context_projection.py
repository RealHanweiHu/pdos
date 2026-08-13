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
                    "reference_id": "issue:issue-1",
                    "entity": "issue",
                    "entity_id": "issue-1",
                    "label": "ISS-001",
                    "href": "/projects/project-1?tab=issues&issue_id=issue-1",
                    "excerpt": "Issue remains open.",
                    "object_storage_key": "tenant/project/private.pdf",
                }
            ],
            "multimodal": {
                "status": "ready",
                "documents": [
                    {
                        "document_id": "document-1",
                        "filename": "evidence.pdf",
                        "media_type": "application/pdf",
                        "extraction_status": "extracted",
                        "fragments": [
                            {
                                "reference_id": "document:document-1:fragment:1",
                                "document_id": "document-1",
                                "ordinal": 1,
                                "locator": "page:1",
                                "excerpt": "Scoped evidence.",
                                "object_key": "must-not-leave",
                            }
                        ],
                        "shown_fragment_count": 1,
                        "total_fragment_count": 1,
                        "truncated": False,
                        "sha256": "must-not-leave",
                    }
                ],
                "requested_document_count": 1,
                "available_document_count": 1,
                "unavailable_document_count": 0,
                "shown_fragment_count": 1,
                "total_fragment_count": 1,
                "truncated": False,
            },
            "user": {
                "perspective_role": "engineer",
                "role_lens": "Review engineering evidence without write authority.",
                "project_roles": [{"role": "engineer", "active_member_count": 2}],
                "decision_mode": "advisory_only",
                "review_required": True,
                "apply_requires_separate_human_action": True,
                "username": "must-not-leave",
            },
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
        "references": [
            {
                "reference_id": "issue:issue-1",
                "entity": "issue",
                "entity_id": "issue-1",
                "label": "ISS-001",
                "href": "/projects/project-1?tab=issues&issue_id=issue-1",
                "excerpt": "Issue remains open.",
            }
        ],
        "multimodal": {
            "status": "ready",
            "documents": [
                {
                    "document_id": "document-1",
                    "filename": "evidence.pdf",
                    "media_type": "application/pdf",
                    "extraction_status": "extracted",
                    "fragments": [
                        {
                            "reference_id": "document:document-1:fragment:1",
                            "document_id": "document-1",
                            "ordinal": 1,
                            "locator": "page:1",
                            "excerpt": "Scoped evidence.",
                        }
                    ],
                    "shown_fragment_count": 1,
                    "total_fragment_count": 1,
                    "truncated": False,
                }
            ],
            "requested_document_count": 1,
            "available_document_count": 1,
            "unavailable_document_count": 0,
            "shown_fragment_count": 1,
            "total_fragment_count": 1,
            "truncated": False,
        },
        "user": {
            "perspective_role": "engineer",
            "role_lens": "Review engineering evidence without write authority.",
            "project_roles": [{"role": "engineer", "active_member_count": 2}],
            "decision_mode": "advisory_only",
            "review_required": True,
            "apply_requires_separate_human_action": True,
        },
    }
    assert set(projection.removed_paths) == {
        "api_key",
        "document_original",
        "execution.raw_issue_text",
        "project.confidential_notes",
        "references[0].object_storage_key",
        "multimodal.documents[0].fragments[0].object_key",
        "multimodal.documents[0].sha256",
        "trigger.payload",
        "user.username",
    }


def test_project_gateway_context_rejects_non_json_values_in_allowed_fields() -> None:
    with pytest.raises(ContextProjectionError, match="project.id must be JSON-safe"):
        project_gateway_context({"project": {"id": object()}})


def test_project_gateway_context_rejects_wrong_container_shapes() -> None:
    with pytest.raises(ContextProjectionError, match="references must be a list"):
        project_gateway_context({"references": {"entity": "issue"}})
