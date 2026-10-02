"""Pure source selection, projection and SQL contracts; no model or database."""

from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy import Insert
from sqlalchemy.dialects import postgresql

from app.ai import meeting_event_queue as q
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.meeting_reading import KEY
from app.auth.roles import Action
from app.domain.ai_meeting_draft_content import CAPABILITIES, OPERATIONS
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.meetings import MeetingService

NOW = datetime(2026, 9, 27, tzinfo=UTC)
TENANT, PROJECT, MEETING, TRANSCRIPT, ACTOR, PRINCIPAL = (UUID(int=i) for i in range(1, 7))


def event(action: str = "status_completed", **changes: Any) -> dict[str, Any]:
    return (
        dict(
            id=10,
            tenant_id=TENANT,
            project_id=PROJECT,
            entity_id=MEETING,
            source="meeting_service",
            entity="meeting",
            event_id="meeting:original",
            timestamp=NOW,
            payload=dict(meeting_id=str(MEETING), action=action, status="completed"),
        )
        | changes
    )


def snapshot(**changes: Any) -> dict[str, Any]:
    return (
        dict(
            source_complete=True,
            superseded=False,
            digest="a" * 64,
            transcript={"content_digest": "b" * 64},
        )
        | changes
    )


class Rows:
    def __init__(self, value: Any):
        self.value = value

    def mappings(self) -> Any:
        return self

    def scalars(self) -> Any:
        return self

    def all(self) -> Any:
        return self.value

    def scalar_one_or_none(self) -> Any:
        return self.value

    def scalar_one(self) -> Any:
        return self.value

    def __iter__(self) -> Any:
        return iter(self.value)


class Connection:
    def __init__(self, value: Any = None):
        self.value = value
        self.statements: list[Any] = []
        self.saved: list[dict[str, Any]] = []
        self.savepoints = 0

    def execute(self, statement: Any) -> Rows:
        self.statements.append(statement)
        if isinstance(statement, Insert):
            self.saved.append(statement.compile().params)
            return Rows(None)
        if "clock_timestamp()" in str(statement):
            return Rows(NOW)
        if "SELECT cehub_ai.ai_meeting_event_receipts.id" in str(statement):
            operation = statement.compile().params.get("operation_key_1")
            if any(value.get("operation_key") == operation for value in self.saved):
                return Rows(UUID(int=100))
        return Rows(self.value)

    def begin_nested(self) -> Any:
        self.savepoints += 1
        raise AssertionError("new runs must be created in a top-level transaction")


@pytest.mark.parametrize("action", sorted(q.TRIGGER_ACTIONS))
def test_exact_original_actions(action: str) -> None:
    assert q.trigger_action(event(action)) == action


@pytest.mark.parametrize("action", ["status_changed", "status_in_progress", "archived", "created"])
def test_other_meeting_actions_are_not_model_triggers(action: str) -> None:
    with pytest.raises(q.SkipMeetingEvent, match="action_not_supported"):
        q.trigger_action(event(action))


def test_trigger_requires_original_completed_status_and_meeting_identity() -> None:
    item = event("transcript_uploaded")
    item["payload"]["status"] = "in_progress"
    with pytest.raises(q.SkipMeetingEvent, match="event_not_completed"):
        q.trigger_action(item)
    with pytest.raises(q.SkipMeetingEvent, match="event_source_invalid"):
        q.trigger_action(event(entity_id=UUID(int=99)))


@pytest.mark.parametrize("rows", [[], [dict(actor_user_id=None)], [dict(actor_user_id=ACTOR)] * 2])
def test_event_requires_one_original_named_audit(rows: list[Any]) -> None:
    with pytest.raises(q.SkipMeetingEvent, match="event_source_invalid"):
        q.event_audit(Connection(rows), event(), "status_completed")  # type: ignore[arg-type]


def test_event_audit_query_pins_original_scope_action_and_time() -> None:
    c = Connection([dict(actor_user_id=ACTOR)])
    q.event_audit(c, event(), "status_completed")  # type: ignore[arg-type]
    compiled = c.statements[0].compile()
    assert set(compiled.params.values()) == {
        TENANT,
        PROJECT,
        MEETING,
        "meeting:original",
        "meeting",
        "meeting.status_completed",
        NOW,
    }


@pytest.mark.parametrize("count", [0, 1, 2])
def test_completion_uses_unique_current_complete_transcript(
    monkeypatch: pytest.MonkeyPatch,
    count: int,
) -> None:
    monkeypatch.setattr(q, "transcript_snapshot", lambda *args: snapshot())
    c = Connection([UUID(int=20 + n) for n in range(count)])
    if count != 1:
        with pytest.raises(
            q.SkipMeetingEvent, match="transcript_missing" if not count else "transcript_ambiguous"
        ):
            q.select_transcript(c, event(), {}, "status_completed")  # type: ignore[arg-type]
    else:
        assert q.select_transcript(c, event(), {}, "status_completed") == (UUID(int=20), "a" * 64)  # type: ignore[arg-type]
    sql = str(c.statements[0])
    assert "superseded_at IS NULL" in sql and "uploaded_at <=" in sql


def test_missing_or_superseded_sources_do_not_count_as_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(q, "transcript_snapshot", lambda *args: snapshot(source_complete=False))
    with pytest.raises(q.SkipMeetingEvent, match="transcript_missing"):
        q.select_transcript(Connection([TRANSCRIPT]), event(), {}, "status_completed")  # type: ignore[arg-type]


def test_attribution_uses_exact_original_transcript_and_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(q, "transcript_snapshot", lambda *args: snapshot())
    audit = {
        "context": {
            "transcript_id": str(TRANSCRIPT),
            "result": {"transcript_id": str(TRANSCRIPT), "digest": "a" * 64},
        }
    }
    assert q.select_transcript(
        cast(Any, None), event(), audit, "transcript_speakers_confirmed"
    ) == (
        TRANSCRIPT,
        "a" * 64,
    )
    audit["context"]["result"]["digest"] = "c" * 64  # type: ignore[index]
    with pytest.raises(q.SkipMeetingEvent, match="transcript_changed"):
        q.select_transcript(None, event(), audit, "transcript_speakers_confirmed")  # type: ignore[arg-type]


@pytest.fixture
def admitted(monkeypatch: pytest.MonkeyPatch) -> Any:
    current = dict(
        id=UUID(int=30),
        mode="tiered",
        principal_id=PRINCIPAL,
        created_at=NOW - timedelta(seconds=1),
        operation_settings={op: {"mode": "automatic"} for op in OPERATIONS.values()},
    )
    grant = dict(
        id=UUID(int=31), enabled=True, principal_id=PRINCIPAL, created_at=NOW - timedelta(seconds=1)
    )
    calls: list[Any] = []
    monkeypatch.setattr(q, "event_audit", lambda *args: dict(id=1, actor_user_id=ACTOR))
    monkeypatch.setattr(
        KnowledgeCorrectionService, "_authorize", lambda *args: calls.append(args[-1])
    )
    monkeypatch.setattr(q, "lock_project_write_scope", lambda *args, **kw: True)
    monkeypatch.setattr(
        MeetingService,
        "_get",
        lambda *args, **kw: SimpleNamespace(status="completed", deleted_at=None, archived_at=None),
    )
    monkeypatch.setattr(q, "policy", lambda *args: current)
    monkeypatch.setattr(q, "latest_scope", lambda *args: grant)
    monkeypatch.setattr(q, "require_live_key", lambda key: calls.append(key))
    monkeypatch.setattr(q, "select_transcript", lambda *args: (TRANSCRIPT, "a" * 64))

    def enqueue(*args: Any, **kw: Any) -> dict[str, Any]:
        calls.append(kw)
        return dict(run_id=str(UUID(int=90)), status="queued", reused=False, source_digest="d" * 64)

    monkeypatch.setattr(
        q, "MeetingReadingService", lambda *args, **kw: SimpleNamespace(enqueue_event=enqueue)
    )
    return current, grant, calls


def test_enqueue_reuses_capability_scope_actor_and_transaction(admitted: Any) -> None:
    _, _, calls = admitted
    evidence: dict[str, Any] = {}
    result = q.MeetingEventQueue(cast(Any, None), cast(Any, None))._enqueue(
        cast(Any, Connection(PRINCIPAL)), event(), "minutes", evidence
    )
    assert result["status"] == "queued"
    assert KEY in calls and CAPABILITIES["minutes"] in calls
    assert Action.MEETING_VIEW in calls and Action.MEETING_TRANSCRIPT_UPLOAD in calls
    assert calls[-1]["event"]["actor_user_id"] == ACTOR
    assert calls[-1]["policy_id"] == UUID(int=30)
    assert calls[-1]["scope_revision_id"] == UUID(int=31)
    assert evidence["transcript_id"] == TRANSCRIPT


@pytest.mark.parametrize(
    "change,reason",
    [
        ("mode", "automatic_not_enabled"),
        ("grant", "scope_not_enabled"),
        ("policy_time", "event_before_authorization"),
        ("grant_time", "event_before_authorization"),
    ],
)
def test_automatic_and_authorization_must_precede_event(
    admitted: Any, change: str, reason: str
) -> None:
    current, grant, calls = admitted
    if change == "mode":
        current["operation_settings"][OPERATIONS["minutes"]]["mode"] = "confirm"
    elif change == "grant":
        grant["enabled"] = False
    else:
        (current if change == "policy_time" else grant)["created_at"] = NOW + timedelta(seconds=1)
    with pytest.raises(q.SkipMeetingEvent, match=reason):
        q.MeetingEventQueue(None, None)._enqueue(Connection(PRINCIPAL), event(), "minutes", {})  # type: ignore[arg-type]
    assert not any(isinstance(call, dict) for call in calls)


class TransactionEngine:
    def __init__(self, c: Connection):
        self.c = c
        self.active = False
        self.begun = self.committed = self.rolled_back = 0
        self.after_rollback: Any = None

    @contextmanager
    def begin(self) -> Any:
        assert not self.active
        self.active = True
        self.begun += 1
        checkpoint = len(self.c.saved)
        try:
            yield self.c
        except BaseException:
            self.rolled_back += 1
            del self.c.saved[checkpoint:]
            if self.after_rollback:
                self.after_rollback()
            raise
        else:
            self.committed += 1
        finally:
            self.active = False


def transaction_queue(monkeypatch: pytest.MonkeyPatch, c: Connection | None = None) -> Any:
    engine = TransactionEngine(c or Connection())
    queue = q.MeetingEventQueue(cast(Any, engine), cast(Any, None))
    monkeypatch.setattr(queue, "_lock", lambda *args: {"id": UUID(int=80), "last_event_row_id": 0})
    return queue, engine


@pytest.mark.parametrize("outcome", ["queued", "reused", "skipped"])
def test_each_event_keeps_three_immutable_receipts_in_top_level_transactions(
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
) -> None:
    queue, engine = transaction_queue(monkeypatch)
    c = engine.c

    def enqueue(*args: Any) -> dict[str, Any]:
        assert engine.active
        if outcome == "skipped":
            # Model the tentative run insert before budget freezing fails.
            c.saved.append({"tentative_run": True})
            raise BudgetLedgerError("APPLICATION_QUEUE_BUDGET_REQUIRED")
        return dict(
            run_id=str(UUID(int=90)),
            status="queued",
            reused=outcome == "reused",
            source_digest="d" * 64,
        )

    monkeypatch.setattr(queue, "_enqueue", enqueue)
    counts = queue._project_event(event())
    assert counts[outcome] == 3 and len(c.saved) == 3 and c.savepoints == 0
    assert engine.begun == (6 if outcome == "skipped" else 3)
    assert engine.rolled_back == (3 if outcome == "skipped" else 0)
    assert engine.committed == 3
    assert {value["operation_key"] for value in c.saved} == set(OPERATIONS.values())
    assert all(value["status"] == outcome for value in c.saved)
    assert all(value["receipt"]["message"] == q.REASONS[value["reason"]] for value in c.saved)
    assert all("tentative_run" not in value for value in c.saved)
    if outcome != "skipped":
        assert all(isinstance(value["run_id"], UUID) for value in c.saved)
    else:
        assert all(value["run_id"] is None and value["receipt"]["run"] == {} for value in c.saved)


def test_unknown_error_rolls_back_and_does_not_record_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue, engine = transaction_queue(monkeypatch)

    def fail(*args: Any) -> Any:
        engine.c.saved.append({"tentative_run": True})
        raise RuntimeError("unexpected database failure")

    monkeypatch.setattr(queue, "_enqueue", fail)
    with pytest.raises(RuntimeError, match="unexpected database failure"):
        queue._project_event(event())
    assert engine.c.saved == []
    assert engine.rolled_back == 1 and engine.begun == 1 and engine.committed == 0


def test_existing_operation_receipts_are_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    queue, engine = transaction_queue(monkeypatch, Connection(UUID(int=100)))
    assert queue._project_event(event()) == dict(queued=0, reused=0, skipped=0)
    assert not engine.c.saved and not engine.c.savepoints and engine.begun == 3


def test_skip_rechecks_after_rollback_and_preserves_concurrent_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue, engine = transaction_queue(monkeypatch)

    def fail(*args: Any) -> Any:
        raise BudgetLedgerError("APPLICATION_QUEUE_BUDGET_REQUIRED")

    engine.after_rollback = lambda: setattr(engine.c, "value", UUID(int=100))
    monkeypatch.setattr(queue, "_enqueue", fail)
    assert queue._project_operation(event(), "minutes") is None
    assert engine.begun == 2 and engine.rolled_back == 1
    assert engine.c.saved == []


def test_partial_event_remains_retryable_without_recreating_completed_operations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue, engine = transaction_queue(monkeypatch)
    attempted: list[str] = []

    def enqueue(c: Any, event: Any, kind: str, evidence: Any) -> dict[str, Any]:
        attempted.append(kind)
        if kind == "decisions":
            raise RuntimeError("temporary unexpected failure")
        return dict(run_id=str(UUID(int=90)), status="queued", reused=False, source_digest="d" * 64)

    monkeypatch.setattr(queue, "_enqueue", enqueue)
    with pytest.raises(RuntimeError):
        queue._project_event(event())
    assert len(engine.c.saved) == 2
    with pytest.raises(RuntimeError):
        queue._project_event(event())
    assert attempted == ["minutes", "actions", "decisions", "decisions"]
    assert len(engine.c.saved) == 2


def test_pending_query_is_tenant_bound_and_recovers_late_commits_without_success_filter() -> None:
    compiled = q.pending_events_query().limit(100).compile(dialect=postgresql.dialect())  # type: ignore[no-untyped-call]
    sql = str(compiled)
    assert "LIMIT" in sql and "last_event_row_id" not in sql
    assert "ai_meeting_event_receipts.tenant_id = cehub_event.events.tenant_id" in sql
    assert "ai_meeting_event_receipts.event_row_id = cehub_event.events.id" in sql
    assert "status" not in sql.split("WHERE", 1)[1]
    assert 3 in compiled.params.values()


@pytest.mark.parametrize("limit", [0, 1001])
def test_invalid_batch_size_never_scans(limit: int) -> None:
    with pytest.raises(ValueError, match="batch size"):
        q.MeetingEventQueue(None, None).dispatch_once(limit)  # type: ignore[arg-type]


def test_dispatch_total_batch_bound_and_cursor_cannot_drop_old_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BatchConnection(Connection):
        def execute(self, statement: Any) -> Rows:
            self.statements.append(statement)
            if "SELECT DISTINCT" in str(statement):
                return Rows([TENANT, UUID(int=91)])
            if "SELECT cehub_event.events.id" in str(statement):
                assert statement._limit_clause.value == 2
                return Rows([event(), event(id=11)])
            return Rows(None)

    c = BatchConnection()
    engine: Any = SimpleNamespace(connect=lambda: nullcontext(c), begin=lambda: nullcontext(c))
    calls: list[Any] = []
    monkeypatch.setattr(
        q,
        "AgentDispatcher",
        lambda *args, **kw: SimpleNamespace(
            _lock_tenant_consumer=lambda *args, **kw: None,
            _cursor=lambda *args, **kw: {"id": UUID(int=80), "last_event_row_id": 100},
        ),
    )
    queue = q.MeetingEventQueue(engine, cast(Any, None))

    def project(*args: Any) -> dict[str, int]:
        calls.append(args[0]["id"])
        return dict(queued=3, reused=0, skipped=0)

    monkeypatch.setattr(queue, "_project_event", project)
    result = queue.dispatch_once(2)
    assert result.scanned_event_count == 2 and result.queued_count == 6
    assert calls == [10, 11]
    updates = [s.compile().params for s in c.statements if getattr(s, "is_update", False)]
    assert len(updates) == 2 and all(value["last_event_row_id"] == 100 for value in updates)


@pytest.mark.parametrize("identity", [None, UUID(int=90)])
def test_execute_only_queued_receipt_bound_runs(
    monkeypatch: pytest.MonkeyPatch, identity: UUID | None
) -> None:
    c = Connection(identity)
    engine: Any = SimpleNamespace(connect=lambda: nullcontext(c))
    calls: list[Any] = []
    monkeypatch.setattr(
        q,
        "MeetingReadingService",
        lambda *args, **kw: SimpleNamespace(execute_queued=lambda run_id: calls.append(run_id)),
    )
    result = q.MeetingEventQueue(engine, cast(Any, None)).execute_next()
    assert result is (identity is not None)
    assert calls == ([] if identity is None else [identity])
    compiled = c.statements[0].compile()
    assert compiled.params["status_1"] == "queued"
    assert "degraded" not in compiled.params.values()
    assert "ai_meeting_event_receipts.tenant_id = cehub_ai.agent_runs.tenant_id" in str(compiled)
