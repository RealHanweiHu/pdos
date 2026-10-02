"""Pure contract checks for the worker's boolean-only AI success predicate."""

import runpy
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from sqlalchemy import Connection
from sqlalchemy.dialects import postgresql

from app.domain.ai_issue_silent_events import is_silent_ai_issue_event

ROOT = Path(__file__).resolve().parents[2]
TENANT, PROJECT, ISSUE = (UUID(int=i) for i in range(1, 4))


def event(**changes: Any) -> dict[str, Any]:
    return {
        "id": 31,
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "entity_id": ISSUE,
        "event_type": "ISSUE_CREATED",
        "payload": {"origin": "ai"},
        **changes,
    }


@pytest.mark.parametrize("answer", [True, False])
def test_helper_uses_only_exact_parameterized_boolean_predicate(answer: bool) -> None:
    c = MagicMock()
    c.execute.return_value.scalar_one.return_value = answer
    assert is_silent_ai_issue_event(cast(Connection, c), event()) is answer
    statement, parameters = c.execute.call_args.args
    query = str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[no-untyped-call]
    assert "cehub_ai.is_silent_ai_issue_event" in query
    assert "JOIN" not in query and "payload" not in query
    assert parameters == {
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "event_row_id": 31,
        "issue_id": ISSUE,
    }


@pytest.mark.parametrize("changes", [{"event_type": "ISSUE_UPDATED"}, {"project_id": None}])
def test_unrelated_events_need_no_privileged_read(changes: dict[str, Any]) -> None:
    c = MagicMock()
    assert not is_silent_ai_issue_event(cast(Connection, c), event(**changes))
    c.execute.assert_not_called()


def test_trust_read_error_propagates() -> None:
    c = MagicMock()
    c.execute.side_effect = RuntimeError("predicate unavailable")
    with pytest.raises(RuntimeError, match="predicate unavailable"):
        is_silent_ai_issue_event(cast(Connection, c), event())


def test_migration_and_security_bootstrap_preserve_the_same_narrow_contract() -> None:
    migration = runpy.run_path(
        str(ROOT / "server/migrations/versions/0388_ai_issue_silent_events.py")
    )
    ddl = migration["DDL"].strip()
    bootstrap = (ROOT / "infra/postgres/security/agent-runtime.sql").read_text()
    assert migration["down_revision"] == "0387_ai_issue_withdrawals"
    assert ddl in bootstrap
    assert "RETURNS boolean" in ddl
    assert "LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog" in ddl
    for table in (
        "cehub_event.events",
        "cehub_audit.audit_log",
        "cehub_project.issues",
        "cehub_ai.ai_issue_applications",
    ):
        assert table in ddl
    for relation in (
        "app.issue_event_row_id=e.id",
        "app.issue_id=e.entity_id",
        "e.id=p_event AND e.tenant_id=p_tenant AND e.project_id=p_project",
        "e.entity_id=p_issue",
        "a.actor_user_id IS NULL",
        "i.created_by_ai_principal_id=app.principal_id",
        "a.context->>'application_id'=app.id::text",
        "a.context->>'result_id'=app.result_id::text",
        "a.context->>'run_id'=app.run_id::text",
        "a.context->>'model_invocation_id'=app.model_invocation_id::text",
        "a.context->>'source_event_row_id'=app.source_event_row_id::text",
    ):
        assert relation in ddl
    assert "FROM PUBLIC" in ddl and "FROM pdos_agent" in ddl
    assert "GRANT EXECUTE ON FUNCTION" in ddl and "TO pdos_worker" in ddl
    assert "r.rolname IN ('pdos_worker','pdos_agent')" in ddl
    assert "GRANT SELECT" not in ddl


def test_upgrade_and_downgrade_only_manage_the_predicate(monkeypatch: pytest.MonkeyPatch) -> None:
    migration = runpy.run_path(
        str(ROOT / "server/migrations/versions/0388_ai_issue_silent_events.py")
    )
    calls: list[Any] = []
    monkeypatch.setattr(migration["op"], "execute", calls.append)
    migration["upgrade"]()
    migration["downgrade"]()
    assert calls == [
        migration["DDL"],
        "DROP FUNCTION cehub_ai.is_silent_ai_issue_event(uuid,uuid,bigint,uuid)",
    ]
