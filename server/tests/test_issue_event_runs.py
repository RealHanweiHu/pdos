"""Pure SQL and orchestration checks; all connections and gateways are in-memory fakes."""

from contextlib import nullcontext
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy import Connection, Engine, Insert, Select, Update
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError

from app.ai import application_domain_context as domain_context
from app.ai import issue_event_runs as r
from app.ai.application_gateway import ApplicationModelGateway
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.issue_event_proposal import (
    PROMPT,
    IssueEventProposal,
    IssueEventProposalError,
    source_snapshot,
)
from app.domain.product_workspace import digest

NOW = datetime(2026, 9, 27, tzinfo=UTC)
TENANT, PROJECT, ACTOR, RUN, INVOCATION, CASE, REQUEST, RESULT = (UUID(int=i) for i in range(1, 9))


def internal() -> dict[str, Any]:
    event = dict(
        id=14,
        event_id="original-failed-event",
        event_type="TEST_FAILED",
        tenant_id=str(TENANT),
        project_id=str(PROJECT),
        entity_id=str(CASE),
        timestamp=NOW.isoformat(),
    )
    return dict(
        source_status="current",
        source_kind="test_failure",
        source_digest="a" * 64,
        title="原失败测试",
        event_row_id=14,
        event_id=event["event_id"],
        event_type=event["event_type"],
        existing_issue=None,
        source=dict(
            event=event,
            source_key=f"test_case:{CASE}",
            origin_kind="legacy_test_case",
            current_case=dict(id=str(CASE), status="failed", title="原失败测试"),
            original_result=dict(status="failed", result_notes="原失败说明"),
            audit={"secret": "RAW_AUDIT_MUST_NOT_LEAK"},
        ),
    )


def output() -> IssueEventProposal:
    return IssueEventProposal.model_validate(
        dict(
            disposition="create_issue",
            title="测试失败问题",
            description="原失败说明",
            severity="high",
            citations=[dict(reference_id="test.original.result_notes", exact_quote="原失败说明")],
        )
    )


def run(**changes: Any) -> dict[str, Any]:
    return (
        dict(
            id=RUN,
            tenant_id=TENANT,
            project_id=PROJECT,
            requested_by_user_id=ACTOR,
            request_id=str(REQUEST),
            agent_key=r.AGENT_KEY,
            context_version=r.RUN_VERSION,
            status="running",
            error_code=None,
            created_at=NOW,
            completed_at=None,
            run_context=dict(
                issue_event_source=source_snapshot(internal()),
                issue_event_event_row_id=14,
                issue_event_expected_digest="a" * 64,
                issue_event_source_title="原失败测试",
                issue_event_prompt_version=PROMPT.version,
                issue_event_schema_digest=digest(IssueEventProposal.model_json_schema()),
                budget_runtime={"keep": "original budget control"},
            ),
        )
        | changes
    )


def saved_result(row: dict[str, Any]) -> dict[str, Any]:
    return dict(
        id=RESULT,
        tenant_id=TENANT,
        project_id=PROJECT,
        run_id=RUN,
        model_invocation_id=INVOCATION,
        event_row_id=14,
        source_digest="a" * 64,
        source_snapshot=row["run_context"]["issue_event_source"],
        proposal=output().model_dump(mode="json"),
        created_at=NOW,
    )


class Rows:
    def __init__(self, value: Any):
        self.value = value

    def mappings(self) -> "Rows":
        return self

    def one(self) -> Any:
        return self.value

    def one_or_none(self) -> Any:
        return self.value

    def first(self) -> Any:
        return self.value

    def scalar_one(self) -> Any:
        return self.value

    def scalar_one_or_none(self) -> Any:
        return self.value

    def __iter__(self) -> Any:
        return iter(self.value)


class FakeConnection:
    def __init__(self, row: dict[str, Any], *, evidence: bool = True):
        self.row = deepcopy(row)
        self.result: dict[str, Any] | None = None
        self.generation_binding: dict[str, Any] | None = None
        self.statements: list[Any] = []
        self.evidence = evidence
        self.run_inserts: list[dict[str, Any]] = []
        self.bound: list[bool] = []

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def execution_options(self, **options: Any) -> "FakeConnection":
        return self

    def begin(self) -> Any:
        return nullcontext(self)

    def begin_nested(self) -> Any:
        raise AssertionError("new run budget freeze must use top-level transaction")

    def execute(self, statement: Any) -> Rows:
        self.statements.append(statement)
        compiled = statement.compile(dialect=postgresql.dialect())  # type: ignore[no-untyped-call]
        if isinstance(statement, Insert):
            values = dict(compiled.params)
            if statement.table.name == "ai_issue_event_results":
                self.result = values
                return Rows(None)
            if statement.table.name == "ai_issue_generation_bindings":
                self.generation_binding = values
                return Rows(None)
            assert statement.table.name == "agent_runs", "must not insert Finding or business Issue"
            self.run_inserts.append(values)
            self.row = {**self.row, **values}
            return Rows(self.row)
        if isinstance(statement, Update):
            assert cast(Any, statement.table).name == "agent_runs", (
                "must not mutate business records"
            )
            self.row.update(
                {
                    key: value
                    for key, value in compiled.params.items()
                    if key in {"status", "error_code", "run_context", "completed_at", "updated_at"}
                }
            )
            return Rows(self.row)
        assert isinstance(statement, Select)
        sql = str(compiled)
        if "cehub_core.tenants" in sql:
            return Rows("active")
        if "ai_issue_generation_bindings" in sql:
            return Rows(self.generation_binding)
        if "ai_write_policies" in sql or "ai_write_scope_revisions" in sql:
            return Rows(None)
        if "clock_timestamp()" in sql:
            return Rows(NOW)
        if "application_result_checkpoints" in sql:
            return Rows((INVOCATION,) if self.evidence else None)
        if "ai_issue_event_results" in sql:
            return Rows(self.result)
        if sql.startswith("SELECT cehub_ai.agent_runs.run_context"):
            return Rows(self.row["run_context"])
        if "agent_runs" in sql:
            return Rows(self.row)
        raise AssertionError(sql)


class FakeEngine:
    def __init__(self, c: FakeConnection):
        self.c = c

    def connect(self) -> FakeConnection:
        return self.c

    def begin(self) -> Any:
        return nullcontext(self.c)


class FakeGateway:
    creation_budget_profile = object()

    def __init__(self, *, success: bool = True, invocation_id: UUID | None = INVOCATION):
        self.calls = 0
        self.success = success
        self.invocation_id = invocation_id

    def invoke_structured(self, invocation: Any, output_type: Any) -> Any:
        self.calls += 1
        assert output_type is IssueEventProposal
        assert invocation.agent_key == "quality_intelligence"
        return SimpleNamespace(
            status="succeeded" if self.success else "degraded",
            output=output() if self.success else None,
            invocation_id=self.invocation_id,
            error_code=None,
        )


def setup_execution(
    monkeypatch: pytest.MonkeyPatch, *, evidence: bool = True, gateway: FakeGateway | None = None
) -> tuple[r.IssueEventRuns, FakeConnection, FakeGateway]:
    row = run()
    c = FakeConnection(row, evidence=evidence)
    g = gateway or FakeGateway()
    monkeypatch.setattr(r, "require_live_key", lambda key: None)
    monkeypatch.setattr(r, "lock_project_write_scope", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        r, "_rebuild", lambda *args, **kwargs: (internal(), source_snapshot(internal()))
    )
    monkeypatch.setattr(domain_context, "record", lambda *args, **kwargs: None)
    monkeypatch.setattr(domain_context, "sources_current", lambda *args, **kwargs: True)
    monkeypatch.setattr(r, "bind_write", lambda *args, success=True: c.bound.append(success))
    # This unit fixture proves proposal persistence, not the separately tested
    # application transaction. Keep budget creation's no-savepoint assertion.
    from app.domain.ai_issue_applications import IssueApplicationService

    monkeypatch.setattr(
        IssueApplicationService,
        "apply_generated",
        lambda *args: {"route": "confirm", "reason": "qualification_required"},
    )
    service = r.IssueEventRuns(
        cast(Engine, FakeEngine(c)), gateway=cast(ApplicationModelGateway, g)
    )
    return service, c, g


def test_gateway_projection_keeps_actual_existing_issue_information() -> None:
    snapshot = source_snapshot(internal())
    snapshot["context"]["existing_issue_id"] = str(RESULT)
    context = r.model_context(snapshot)
    assert str(RESULT) in context["question"]
    assert '"test_status":"failed"' in context["question"]
    assert set(context) == {"question", "references"}
    assert "RAW_AUDIT_MUST_NOT_LEAK" not in str(context)


def test_success_requires_checkpoint_and_persists_only_immutable_proposal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, c, gateway = setup_execution(monkeypatch)
    result = service._execute(cast(Any, c.row), c.row["run_context"]["issue_event_source"])
    assert gateway.calls == 1
    assert result["status"] == "succeeded"
    assert result["proposal"] == output().model_dump(mode="json")
    assert result["result_id"] == str(c.result["id"])  # type: ignore[index]
    assert c.bound == [True]
    assert c.row["run_context"]["budget_runtime"] == {"keep": "original budget control"}
    assert "RAW_AUDIT_MUST_NOT_LEAK" not in str(result)


@pytest.mark.parametrize(
    "gateway,evidence", [(FakeGateway(invocation_id=None), True), (FakeGateway(), False)]
)
def test_missing_real_receipt_never_saves_success(
    monkeypatch: pytest.MonkeyPatch, gateway: FakeGateway, evidence: bool
) -> None:
    service, c, _ = setup_execution(monkeypatch, gateway=gateway, evidence=evidence)
    result = service._execute(cast(Any, c.row), c.row["run_context"]["issue_event_source"])
    assert result["status"] == "degraded"
    assert result["proposal"] is None
    assert c.result is None
    assert c.bound == [False]
    assert result["error_code"] == "EVENT_ISSUE_RECEIPT_MISSING"


def test_source_change_after_generation_does_not_persist_proposal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, c, _ = setup_execution(monkeypatch)
    monkeypatch.setattr(domain_context, "sources_current", lambda *args, **kwargs: False)
    result = service._execute(cast(Any, c.row), c.row["run_context"]["issue_event_source"])
    assert result["error_code"] == "EVENT_ISSUE_SOURCE_CHANGED"
    assert c.result is None


def test_final_locked_source_check_prevents_racing_change(monkeypatch: pytest.MonkeyPatch) -> None:
    service, c, _ = setup_execution(monkeypatch)
    calls = 0

    def rebuild(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise IssueEventProposalError("source_changed", "来源已变化")
        return internal(), source_snapshot(internal())

    monkeypatch.setattr(r, "_rebuild", rebuild)
    result = service._execute(cast(Any, c.row), c.row["run_context"]["issue_event_source"])
    assert calls == 3
    assert result["error_code"] == "EVENT_ISSUE_SOURCE_CHANGED"
    assert c.result is None


def test_changed_prompt_prevents_any_gateway_call(monkeypatch: pytest.MonkeyPatch) -> None:
    service, c, gateway = setup_execution(monkeypatch)
    c.row["run_context"]["issue_event_prompt_version"] = "old-version"
    result = service._execute(cast(Any, c.row), c.row["run_context"]["issue_event_source"])
    assert gateway.calls == 0
    assert result["status"] == "degraded"


def test_unknown_sql_error_is_not_hidden_as_business_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, c, gateway = setup_execution(monkeypatch)

    def failed(*args: Any, **kwargs: Any) -> Any:
        raise SQLAlchemyError("connection unavailable")

    monkeypatch.setattr(r, "_rebuild", failed)
    with pytest.raises(SQLAlchemyError):
        service._execute(cast(Any, c.row), c.row["run_context"]["issue_event_source"])
    assert gateway.calls == 0
    assert c.result is None


def test_mutable_context_is_not_success_receipt() -> None:
    row = run(status="succeeded")
    row["run_context"].update(
        issue_event_result_id=str(RESULT),
        issue_event_invocation_id=str(INVOCATION),
        issue_event_result={"untrusted": "cached output"},
    )
    assert r.receipt(row)["proposal"] is None
    actual = saved_result(row)
    assert r.receipt(row, actual)["proposal"] == actual["proposal"]
    actual["project_id"] = UUID(int=999)
    assert r.receipt(row, actual)["proposal"] is None


def test_result_query_matches_original_run_scope_and_result_id() -> None:
    row = run(status="succeeded")
    row["run_context"]["issue_event_result_id"] = str(RESULT)
    c = FakeConnection(row)
    c.result = saved_result(row)
    assert r.result_for_run(cast(Connection, c), row) == c.result
    row["run_context"]["issue_event_result_id"] = str(UUID(int=99))
    assert r.result_for_run(cast(Connection, c), row) is None


def test_checkpoint_query_uses_actual_schema_and_exact_normalized_output() -> None:
    statement = r.result_evidence_query(run(), INVOCATION, UUID(int=200), output())
    compiled = statement.compile(dialect=postgresql.dialect())  # type: ignore[no-untyped-call]
    assert "application_result_checkpoints" in str(compiled)
    assert "model_invocations.model_call_id" not in str(compiled)
    assert output().model_dump(mode="json") in compiled.params.values()
    assert {TENANT, PROJECT, RUN, INVOCATION}.issubset(
        {v for v in compiled.params.values() if isinstance(v, UUID)}
    )


def test_history_scope_and_event_filter_prefer_immutable_result() -> None:
    query = r.history_query(TENANT, ACTOR, PROJECT, 14)
    compiled = query.compile(dialect=postgresql.dialect())  # type: ignore[no-untyped-call]
    assert "LEFT OUTER JOIN cehub_ai.ai_issue_event_results" in str(compiled)
    assert "coalesce(" in str(compiled)
    for expected in (TENANT, PROJECT, ACTOR, r.RUN_VERSION, r.AGENT_KEY, 14):
        assert expected in compiled.params.values()


def test_source_rebuild_checks_scope_and_exact_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    value = internal()
    snapshot = source_snapshot(value)
    monkeypatch.setattr(r, "_read", lambda *args, **kwargs: value)
    assert r._rebuild(cast(Connection, None), TENANT, ACTOR, PROJECT, snapshot)[1] == snapshot
    changed = deepcopy(snapshot)
    changed["source_digest"] = "b" * 64
    with pytest.raises(IssueEventProposalError, match="已经变化"):
        r._rebuild(cast(Connection, None), TENANT, ACTOR, PROJECT, changed)
    with pytest.raises(IssueEventProposalError, match="范围"):
        r._rebuild(cast(Connection, None), TENANT, ACTOR, UUID(int=999), snapshot)


@pytest.mark.parametrize("event_id", [0, -1, True, "1"])
def test_request_rejects_invalid_event_id(event_id: Any) -> None:
    with pytest.raises(ValueError):
        r.Request(request_id=REQUEST, event_row_id=event_id, expected_digest="a" * 64)


def test_creation_refuses_unbudgeted_gateway_before_run_insert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NewConnection(FakeConnection):
        def execute(self, statement: Any) -> Rows:
            if isinstance(statement, Select) and "agent_runs" in str(statement):
                return Rows(None)
            return super().execute(statement)

    c = NewConnection(run())
    gateway = SimpleNamespace(creation_budget_profile=None)
    monkeypatch.setattr(r, "_access", lambda *args, **kwargs: None)
    monkeypatch.setattr(r, "_read", lambda *args, **kwargs: internal())
    monkeypatch.setattr(r, "require_live_key", lambda key: None)
    monkeypatch.setattr(r, "lock_project_write_scope", lambda *args, **kwargs: True)
    service = r.IssueEventRuns(
        cast(Engine, FakeEngine(c)), gateway=cast(ApplicationModelGateway, gateway)
    )
    context = SimpleNamespace(tenant=SimpleNamespace(id=TENANT), user=SimpleNamespace(id=ACTOR))
    with pytest.raises(BudgetLedgerError, match="APPLICATION_QUEUE_BUDGET_REQUIRED"):
        service.create(
            context=cast(Any, context),
            project_id=PROJECT,
            request=r.Request(request_id=REQUEST, event_row_id=14, expected_digest="a" * 64),
        )
    assert not c.run_inserts


def test_creation_freezes_budget_after_new_run_in_same_top_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NewConnection(FakeConnection):
        def execute(self, statement: Any) -> Rows:
            if isinstance(statement, Select) and "agent_runs" in str(statement):
                return Rows(None)
            return super().execute(statement)

    c = NewConnection(run())
    monkeypatch.setattr(r, "_access", lambda *args, **kwargs: None)
    monkeypatch.setattr(r, "_read", lambda *args, **kwargs: internal())
    monkeypatch.setattr(r, "require_live_key", lambda key: None)
    monkeypatch.setattr(r, "lock_project_write_scope", lambda *args, **kwargs: True)
    frozen = []

    def freeze(connection: Any, gateway: Any, **values: Any) -> None:
        assert connection is c
        assert len(c.run_inserts) == 1
        assert c.run_inserts[0]["status"] == "running"
        assert c.run_inserts[0]["event_row_ids"] == []
        frozen.append(values)

    monkeypatch.setattr(r, "freeze_created_application_run", freeze)
    monkeypatch.setattr(r.IssueEventRuns, "_execute", lambda *args: {"queued_for_test": True})
    service = r.IssueEventRuns(
        cast(Engine, FakeEngine(c)), gateway=cast(ApplicationModelGateway, FakeGateway())
    )
    context = SimpleNamespace(
        tenant=SimpleNamespace(id=TENANT), user=SimpleNamespace(id=ACTOR, auth_version=4)
    )
    result = service.create(
        context=cast(Any, context),
        project_id=PROJECT,
        request=r.Request(request_id=REQUEST, event_row_id=14, expected_digest="a" * 64),
    )
    assert result == {"queued_for_test": True}
    assert frozen[0]["purpose"] == "event_issue"
    assert frozen[0]["auth_version"] == 4
    assert c.generation_binding is not None
    assert c.generation_binding["run_id"] == c.row["id"]
    assert c.generation_binding["capture_kind"] == "evidence_only"
    assert c.generation_binding["reason_code"] == "policy_missing"
    assert c.generation_binding["snapshot"]["source_digest"] == "a" * 64
    assert "cehub_core.tenants" in str(c.statements[0])
    assert "FOR UPDATE" in str(c.statements[0])


def test_completed_request_replays_immutable_receipt_without_call_or_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = run(status="succeeded")
    row["run_context"]["issue_event_result_id"] = str(RESULT)
    c = FakeConnection(row)
    c.result = saved_result(row)
    gateway = FakeGateway()
    monkeypatch.setattr(r, "_access", lambda *args, **kwargs: None)
    monkeypatch.setattr(r, "require_live_key", lambda key: None)
    monkeypatch.setattr(r, "lock_project_write_scope", lambda *args, **kwargs: True)
    monkeypatch.setattr(r, "try_resume", lambda *args, **kwargs: False)
    service = r.IssueEventRuns(
        cast(Engine, FakeEngine(c)), gateway=cast(ApplicationModelGateway, gateway)
    )
    context = SimpleNamespace(
        tenant=SimpleNamespace(id=TENANT), user=SimpleNamespace(id=ACTOR, auth_version=4)
    )
    request = r.Request(request_id=REQUEST, event_row_id=14, expected_digest="a" * 64)
    result = service.create(context=cast(Any, context), project_id=PROJECT, request=request)
    assert result["result_id"] == str(RESULT)
    assert result["proposal"] == output().model_dump(mode="json")
    assert gateway.calls == 0
    assert not c.run_inserts
    assert c.generation_binding is None
    assert result["generation_binding"]["status"] == "not_recorded"
    with pytest.raises(IssueEventProposalError, match="其他输入"):
        service.create(
            context=cast(Any, context),
            project_id=PROJECT,
            request=request.model_copy(update={"event_row_id": 15}),
        )
