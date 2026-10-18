"""Fixed promise goal reads and start insertion contracts, without PostgreSQL."""

# ruff: noqa: I001 -- Initialize the metadata registry before child imports.
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy.engine import Engine

from pdos_next import models  # noqa: F401
from pdos_next.domain.automations import fulfillment_sources as actual
from pdos_next.domain.automations import fulfillment_sql as storage
from pdos_next.domain.automations import service_commands_sql as commands
from pdos_next.domain.automations import service_runtime as runtime
from pdos_next.domain.automations import trigger_sources as sources
from pdos_next.domain.automations.models import AutomationRuleCurrent
from pdos_next.errors import DomainError
from pdos_next.models import Base
import test_trigger_sources as original_sources

case = original_sources.case
relative = original_sources.relative

AT = datetime(2026, 10, 18, 10, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_connection(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Fulfillment source pure checks cannot connect")

    monkeypatch.setattr(Engine, "connect", deny)
    monkeypatch.setattr(Engine, "raw_connection", deny)


class Reader:
    def __init__(self, value):
        self.value, self.statements = value, []

    def execute(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(mappings=lambda: SimpleNamespace(one_or_none=lambda: self.value))

    def add(self, _value):
        raise AssertionError("No business writes in a target read")

    def flush(self):
        raise AssertionError("No business flush in a target read")


def review(case, state="fulfilled"):
    identity = uuid4()
    return {
        "version_id": identity,
        "revision": 2,
        "state": state,
        "review_id": identity,
        "review_revision": 2,
        "review_state": state,
        "commitment_revision": case.commitment.revision,
        "series_id": case.commitment.series_id,
        "task_id": case.commitment.task_id,
        "promisor_id": case.commitment.promisor_id,
        "recipient_id": case.commitment.recipient_id,
    }


@pytest.mark.parametrize("state,expected", [(None, False), ("open", False), ("fulfilled", True)])
def test_exact_current_recipient_review_metadata_keeps_no_review_and_returned_open(
    case, state, expected
):
    reader = Reader(review(case, state) if state else None)
    assert actual.commitment_fulfilled(reader, case.ctx, case.commitment) is expected
    statement = reader.statements[0]
    params = statement.compile().params.values()
    assert {
        case.ctx.tenant_id,
        case.ctx.category_id,
        case.pid,
        case.project.id,
        case.commitment.id,
        case.commitment.owner_id,
        case.commitment.visibility,
    } <= set(params)
    assert all(
        column.name not in {"body", "command", "source_basis", "sources", "reads"}
        for column in statement.selected_columns
    )
    sql = str(statement)
    assert "LEFT OUTER JOIN work_commitment_reviews" in sql
    assert "work_commitment_review_currents.commitment_id" in sql
    assert "work_commitment_reviews.state = work_commitment_review_currents.state" in sql
    assert "confirmations" not in sql and "request_keys" not in sql


@pytest.mark.parametrize(
    "field,value",
    [
        ("review_id", None),
        ("review_revision", 1),
        ("state", "unknown"),
        ("review_state", "open"),
        ("commitment_revision", 99),
        ("series_id", None),
        ("task_id", None),
        ("promisor_id", None),
        ("recipient_id", None),
    ],
)
def test_mismatched_current_review_or_other_recipient_is_not_a_fulfillment(case, field, value):
    saved = review(case) | {field: value}
    with pytest.raises(DomainError) as error:
        actual.commitment_fulfilled(Reader(saved), case.ctx, case.commitment)
    assert error.value.reason == "INTEGRITY_MISMATCH"


def test_goal_is_separate_from_nullable_clock_and_original_target_identity(case):
    spec = relative(case, source_kind="commitment")
    opened = sources.relative_due(case.sql, case.ctx, spec)
    case.fulfillment_read.return_value = True
    fulfilled = sources.relative_due(case.sql, case.ctx, spec)
    assert not opened["goal_reached"] and fulfilled["goal_reached"]
    assert opened["origin"] == fulfilled["origin"]
    assert opened["target_key"] == fulfilled["target_key"]
    assert opened["scheduled_at"] == fulfilled["scheduled_at"]
    case.commitment.promised_at = None
    case.commitment_read.return_value = (
        case.commitment,
        case.promise.model_copy(update={"promised_at": None}),
        case.commitment_pointer,
    )
    unknown = sources.relative_due(case.sql, case.ctx, spec)
    assert unknown["scheduled_at"] is None and unknown["goal_reached"]
    assert unknown["origin"]["source_at"] is None
    assert "goal_reached" not in unknown["origin"]
    case.task_read.assert_not_called()


def test_plan_clock_does_not_query_independent_promise_fulfillment(case):
    assert sources.relative_due(case.sql, case.ctx, relative(case))["goal_reached"] is False
    case.fulfillment_read.assert_not_called()


class TickSQL:
    def __init__(self, pointer, pending=()):
        self.pointer, self.pending = pointer, list(pending)
        self.executed = []

    def scalar(self, statement):
        return (
            self.pointer
            if statement.column_descriptions[0]["entity"] is AutomationRuleCurrent
            else None
        )

    def scalars(self, _statement):
        return self.pending

    def execute(self, statement, parameters):
        self.executed.append((str(statement), parameters))

    def flush(self):
        return None

    def expire(self, _row):
        return None


def tick_case(monkeypatch, *, goal=False, condition="eligible", pending=()):
    ref = {
        key: str(uuid4())
        for key in ("tenant_id", "category_id", "owner_id", "writer_id", "grant_id")
    }
    grant = SimpleNamespace(
        id=uuid4(), rule_id=uuid4(), published_version_id=uuid4(), expires_at=None
    )
    pointer = SimpleNamespace(
        state="active",
        published_version_id=grant.published_version_id,
        admitted_count=0,
        last_admitted_at=None,
    )
    spec = SimpleNamespace(trigger_kind="relative_milestone", max_runs=10, cooldown_seconds=0)
    sql = TickSQL(pointer, pending)

    @contextmanager
    def session(*_args):
        yield sql

    monkeypatch.setattr(runtime, "session", session)
    monkeypatch.setattr(runtime, "now", lambda: AT)
    monkeypatch.setattr(runtime, "saved", Mock(return_value=(grant, None, spec)))
    relative_read = Mock(
        return_value={
            "goal_reached": goal,
            "scheduled_at": None,
            "target_key": "commitment:current",
            "origin": {"source_kind": "commitment"},
        }
    )
    condition_read, stop = Mock(return_value=condition), Mock()
    monkeypatch.setattr(runtime, "relative_due", relative_read)
    monkeypatch.setattr(runtime, "condition_state", condition_read)
    monkeypatch.setattr(runtime, "stop", stop)
    return SimpleNamespace(
        ref=ref, sql=sql, stop=stop, condition=condition_read, relative=relative_read
    )


def test_nullable_fulfilled_goal_stops_before_task_waiting_and_never_admits(monkeypatch):
    value = tick_case(monkeypatch, goal=True, condition="waiting")
    assert runtime.tick(object(), value.ref) == {
        "state": "stopped",
        "wake_at": None,
        "reason": "GOAL_REACHED",
    }
    value.condition.assert_not_called()
    assert value.stop.call_args.args[1:] == (value.ref, "GOAL_REACHED")
    assert not value.sql.executed


@pytest.mark.parametrize("condition", ["eligible", "waiting"])
def test_returned_remains_active_and_old_queued_target_is_superseded(monkeypatch, condition):
    old = SimpleNamespace(
        trigger_kind="relative_milestone",
        trigger_key="commitment:old",
        origin={},
        state="queued",
        error_code=None,
    )
    value = tick_case(monkeypatch, condition=condition, pending=[old])
    result = runtime.tick(object(), value.ref)
    assert result == {"state": "active", "wake_at": (AT + timedelta(seconds=30)).isoformat()}
    assert (old.state, old.error_code) == ("suppressed", "SOURCE_SUPERSEDED")
    value.stop.assert_not_called()
    assert not value.sql.executed


def test_explicit_task_completed_stop_condition_remains_independent(monkeypatch):
    value = tick_case(monkeypatch, goal=False, condition="goal_reached")
    assert runtime.tick(object(), value.ref)["reason"] == "GOAL_REACHED"
    assert value.condition.call_count == 1 and value.stop.call_count == 1


def test_new_goal_stop_drains_only_queued_attempts_through_existing_narrow_start(monkeypatch):
    ref = {"grant_id": str(uuid4())}
    targets, executed = [uuid4(), uuid4()], []

    class SQL:
        def scalars(self, statement):
            assert "state" in str(statement) and "queued" in statement.compile().params.values()
            return targets

        def execute(self, statement, params):
            executed.append((str(statement), params))

    @contextmanager
    def session(*_args):
        yield SQL()

    monkeypatch.setattr(runtime, "session", session)
    # Restore the actual function: tick_case's stop monkeypatch is local to its test.
    runtime.stop(object(), ref, "GOAL_REACHED")
    assert "automation_service_stop" in executed[0][0]
    assert [params["attempt"] for _, params in executed[1:]] == targets
    assert all("automation_service_start" in sql for sql, _ in executed[1:])


def test_hook_is_after_category_and_replay_before_source_wait_and_run_creation():
    captured = commands._function(
        "automation_service_start", "attempt_id uuid", commands.START, "uuid"
    )
    hooked = storage.insert_start_hook(captured)
    assert captured.count(storage.START_ANCHOR) == 1
    assert hooked.count(storage.start_hook()) == 1
    assert (
        hooked.index("FROM public.categories WHERE")
        < hooked.index("IF a.state='admitted'")
        < hooked.index("automation_commitment_source_state(a.id)")
    )
    assert (
        hooked.index("automation_commitment_source_state(a.id)")
        < hooked.index("SELECT x.error_code INTO reason")
        < hooked.index("point<a.due_at")
        < hooked.index("INSERT INTO public.agent_runs")
    )
    for invalid in (
        "",
        captured.replace(storage.START_ANCHOR, ""),
        hooked,
        captured + storage.START_ANCHOR,
    ):
        with pytest.raises(ValueError):
            storage.insert_start_hook(invalid)
    assert "state='admitted'" not in storage.start_hook()
    assert "SOURCE_SUPERSEDED" in storage.SOURCE_STATE
    assert "current_review.state='fulfilled'" in storage.SOURCE_STATE
    assert "work_receipt_project_visible" in storage.SOURCE_STATE
    assert "Task.completed" not in storage.SOURCE_STATE
    assert "task.state" not in storage.SOURCE_STATE and "conditions" not in storage.SOURCE_STATE
    assert "UPDATE public.work_" not in storage.SOURCE_STATE + storage.start_hook()
    assert "INSERT INTO public.agent_runs" not in storage.SOURCE_STATE + storage.start_hook()
    assert all("GRANT EXECUTE" not in sql for sql in storage.upgrade_sql())
    assert storage.rollback_sql() == (f"DROP FUNCTION public.{storage.SIGNATURE}",)


def test_sql_helper_uses_real_metadata_aliases_and_no_source_or_history_bodies():
    import re

    aliases = {
        "a": "automation_service_attempts",
        "g": "automation_service_grants",
        "v": "automation_rule_versions",
        "promise": "work_commitment_versions",
        "w": "work_commitment_versions",
        "current_promise": "work_commitment_currents",
        "review": "work_commitment_reviews",
        "current_review": "work_commitment_review_currents",
    }
    unquoted = re.sub(r"'(?:''|[^'])*'", "''", storage.SOURCE_STATE)
    for alias, table in aliases.items():
        assert set(re.findall(rf"\b{alias}\.([a-z_]+)\b", unquoted)) <= set(
            Base.metadata.tables[table].c.keys()
        )
    assert "promise.body" not in storage.SOURCE_STATE and "review.body" not in storage.SOURCE_STATE
    assert (
        "request_keys" not in storage.SOURCE_STATE and "confirmations" not in storage.SOURCE_STATE
    )
    assert "promise.promised_at+make_interval" in storage.SOURCE_STATE
