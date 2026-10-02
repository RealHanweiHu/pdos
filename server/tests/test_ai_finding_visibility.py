"""Pure SQL compilation and projection wiring checks; no database fixtures."""

from typing import Any

import pytest
from sqlalchemy import Select, false, func, select
from sqlalchemy.dialects import postgresql

from app.ai import rollout_guard
from app.ai.finding_visibility import finding_attention_visibility
from app.ai.runtime_contract import agents_for_event
from app.db.schema import tables
from app.events.catalog import definition_for


def compiled(query: Select[Any]) -> tuple[str, dict[str, Any]]:
    result = query.compile(dialect=postgresql.dialect())  # type: ignore[no-untyped-call]
    return str(result), result.params


def test_silence_requires_explicit_boolean_false_direct_receipt() -> None:
    sql, params = compiled(select(tables.findings.c.id).where(finding_attention_visibility()))
    assert params["capture_mode_1"] == "direct"
    assert params["param_1"] == {"route": "direct", "sampled": False}
    assert "CAST(cehub_ai.ai_meeting_drafts.write_receipt AS JSONB) @>" in sql
    # Missing receipts must not turn SQL UNKNOWN into a silently missing item.
    assert False in params.values() and "coalesce(" in sql
    assert "AND NOT (cehub_ai.ai_meeting_drafts.capture_mode" in sql


def test_any_named_handling_removes_pending_draft_without_deleting_history() -> None:
    sql, params = compiled(select(tables.findings.c.id).where(finding_attention_visibility()))
    assert params["action_1"] == ["confirm", "edit", "withdraw", "publish"]
    assert params["status_1"] == ["pending_review", "accepted"]
    assert "findings.status NOT IN" in sql
    assert "AND NOT (EXISTS (SELECT cehub_ai.ai_meeting_draft_actions.id" in sql
    assert "DELETE" not in sql and "UPDATE" not in sql


def test_draft_and_actions_are_correlated_to_original_tenant_and_project() -> None:
    sql, _ = compiled(select(tables.findings.c.id).where(finding_attention_visibility()))
    for expected in (
        "ai_meeting_drafts.tenant_id = cehub_ai.findings.tenant_id",
        "ai_meeting_drafts.project_id = cehub_ai.findings.project_id",
        "ai_meeting_drafts.finding_id = cehub_ai.findings.id",
        "ai_meeting_draft_actions.tenant_id = cehub_ai.ai_meeting_drafts.tenant_id",
        "ai_meeting_draft_actions.project_id = cehub_ai.ai_meeting_drafts.project_id",
        "ai_meeting_draft_actions.draft_id = cehub_ai.ai_meeting_drafts.id",
    ):
        assert expected in sql
    assert "FROM cehub_ai.ai_meeting_drafts, cehub_ai.findings" not in sql
    assert "FROM cehub_ai.ai_meeting_draft_actions, cehub_ai.ai_meeting_drafts" not in sql
    assert "NOT (EXISTS (SELECT cehub_ai.ai_meeting_drafts.id" in sql


@pytest.mark.parametrize("count", [False, True])
def test_list_and_count_both_include_original_rollout_and_attention(count: bool) -> None:
    query = select(func.count(tables.findings.c.id) if count else tables.findings.c.id).where(
        rollout_guard.employee_finding_visibility()
    )
    sql, params = compiled(query)
    assert "findings.agent_key, cehub_ai.findings.finding_type" in sql
    assert "ai_meeting_drafts.write_receipt AS JSONB" in sql
    assert "ai_meeting_draft_actions.action IN" in sql
    assert ["intake_organization", "meeting_plan"] in params.values()


def test_employee_entry_points_share_predicate_but_single_get_keeps_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import ai
    from app.domain import findings, my_work, review_inbox

    for module in (ai, findings, my_work, review_inbox):
        assert module.employee_finding_visibility is rollout_guard.employee_finding_visibility
    monkeypatch.setattr(rollout_guard, "finding_attention_visibility", false)
    for module in (ai, findings, my_work, review_inbox):
        sql, _ = compiled(select(tables.findings.c.id).where(module.employee_finding_visibility()))
        assert sql.endswith("WHERE false")
    # The record selector used by get/history retains draft linkage, not queue filtering.
    sql, _ = compiled(findings._finding_select())
    assert "AS ai_draft_id" in sql
    assert "write_receipt" not in sql and "ai_meeting_draft_actions" not in sql


def test_created_event_remains_audit_only_not_notification_or_agent_trigger() -> None:
    from app.domain.webhook_sources import SOURCE_EVENTS

    event = definition_for("AI_FINDING_CREATED")
    assert set(event.consumers) == {"review_inbox", "timeline_projection"}
    assert not agents_for_event(event.event_type)
    assert event.event_type not in SOURCE_EVENTS
