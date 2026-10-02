"""Pure checks for current Issue projections and immutable-history availability."""

from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from sqlalchemy import Connection, Engine
from sqlalchemy.dialects import postgresql

from app.api.issue_risks import issue_response
from app.domain import issues, search_sources, task_takeover_residuals
from app.domain.decision_intake_targets import project_options
from app.domain.issue_intake_reuse import project_issue_options

TENANT, PROJECT, ACTOR, ISSUE, WITHDRAWAL = (UUID(int=i) for i in range(1, 6))
NOW = datetime(2026, 9, 27, tzinfo=UTC)


def record() -> issues.IssueRecord:
    return issues.IssueRecord(
        id=ISSUE,
        project_id=PROJECT,
        stage_id=None,
        owner_user_id=None,
        verifier_user_id=None,
        sample_id=None,
        reported_by_user_id=None,
        title="原失败问题",
        description="原失败说明",
        issue_type="test_failure",
        status="open",
        severity="high",
        root_cause=None,
        resolution=None,
        closure_criteria=None,
        closure_evidence_ref=None,
        reopen_count=0,
        target_date=None,
        closed_at=None,
        created_at=NOW,
        updated_at=NOW,
        created_by_ai_principal_id=UUID(int=6),
        ai_writer_name="PDOS Agent",
        withdrawn_at=NOW,
        ai_withdrawal_id=WITHDRAWAL,
    )


def sql(statement: Any) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[no-untyped-call]


@pytest.mark.parametrize("kind", ["issue", "task", "risk"])
def test_search_and_residuals_filter_only_current_issues(kind: Any) -> None:
    search = search_sources.statement(
        kind, tenant=TENANT, user=ACTOR, role="owner", terms=["失败"], project_id=PROJECT
    )
    residual = task_takeover_residuals.statement(kind, TENANT, PROJECT)
    for statement in (search, residual):
        assert ("issues.withdrawn_at IS NULL" in sql(statement)) == (kind == "issue")


def test_list_excludes_withdrawn_but_single_get_preserves_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    connection.execute.return_value.mappings.return_value.__iter__.return_value = iter(())
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = connection
    service = issues.IssueService(cast(Engine, engine))
    assert service.list(tenant_id=TENANT, project_id=PROJECT) == []
    assert "issues.withdrawn_at IS NULL" in sql(connection.execute.call_args.args[0])
    original = record()
    connection.execute.return_value.mappings.return_value.one_or_none.return_value = {"id": ISSUE}
    monkeypatch.setattr(issues, "_record_from_row", lambda _: original)
    assert service.get(tenant_id=TENANT, project_id=PROJECT, issue_id=ISSUE) == original
    query = connection.execute.call_args.args[0]
    assert "issues.withdrawn_at IS NULL" not in sql(query)
    response = issue_response(original)
    assert response.status == "open" and response.closed_at is None
    assert response.withdrawn_at == NOW and response.ai_withdrawal_id == WITHDRAWAL
    assert issues._issue_snapshot(original)["ai_withdrawal_id"] == str(WITHDRAWAL)


@pytest.mark.parametrize("operation", ["edit", "template_fields", "transition"])
def test_withdrawn_issue_is_terminal_before_business_mutation(
    operation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection, engine = MagicMock(), MagicMock()
    engine.begin.return_value.__enter__.return_value = connection
    service = issues.IssueService(cast(Engine, engine))
    monkeypatch.setattr(issues, "lock_project_write_scope", lambda *args, **kwargs: True)
    monkeypatch.setattr(service, "_get_record", lambda *args, **kwargs: record())
    with pytest.raises(issues.IssueTerminalError):
        if operation == "transition":
            service.transition(
                tenant_id=TENANT,
                actor_user_id=ACTOR,
                project_id=PROJECT,
                issue_id=ISSUE,
                to_status="analysis",
            )
        else:
            service.update(
                tenant_id=TENANT,
                actor_user_id=ACTOR,
                project_id=PROJECT,
                issue_id=ISSUE,
                patch=issues.IssueUpdate(
                    changes={"template_fields": {}}
                    if operation == "template_fields"
                    else {"title": "改写"}
                ),
            )
    connection.execute.assert_not_called()


@pytest.mark.parametrize("kind", ["issue", "decision"])
def test_new_targets_exclude_withdrawn_without_changing_historical_reader(kind: Any) -> None:
    c = MagicMock()
    c.execute.return_value.mappings.return_value.all.return_value = []
    project_options(cast(Connection, c), TENANT, PROJECT, kind=kind)
    assert ("issues.withdrawn_at IS NULL" in sql(c.execute.call_args.args[0])) == (kind == "issue")
    project_issue_options(cast(Connection, c), TENANT, PROJECT)
    assert "issues.withdrawn_at IS NULL" in sql(c.execute.call_args.args[0])


@pytest.mark.parametrize(
    ("event_type", "actor", "trusted", "captures"),
    [
        ("ISSUE_CREATED", None, True, False),
        ("ISSUE_CREATED", None, False, True),
        ("ISSUE_CREATED", ACTOR, True, True),
        ("ISSUE_UPDATED", ACTOR, True, True),
    ],
)
def test_only_trusted_ai_creation_skips_automatic_fmea_candidate(
    event_type: str,
    actor: UUID | None,
    trusted: bool,
    captures: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain import fmea_candidates

    c, capture = MagicMock(), MagicMock()
    c.execute.return_value.scalar_one_or_none.return_value = UUID(int=7) if trusted else None
    monkeypatch.setattr(fmea_candidates, "capture", capture)
    fmea_candidates.observe(cast(Connection, c), TENANT, PROJECT, actor, event_type, ISSUE, 21)
    assert capture.called is captures
    if event_type == "ISSUE_CREATED" and actor is None:
        statement = c.execute.call_args.args[0]
        query = sql(statement)
        params = statement.compile().params
        assert "ai_issue_event_results" in query and "audit_log" in query
        assert "audit_log.actor_user_id IS NULL" in query
        assert "issues.reported_by_user_id IS NULL" in query
        assert "issues.created_by_ai_principal_id IS NOT NULL" in query
        assert {
            "origin",
            "writer_principal_id",
            "result_id",
            "run_id",
            "model_invocation_id",
            "source_event_row_id",
        } <= set(params.values())
        assert "create_issue" in params.values()
    else:
        c.execute.assert_not_called()
