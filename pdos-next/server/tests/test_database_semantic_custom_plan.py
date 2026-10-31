"""Per-Select psycopg dispatch controls; engine construction never connects."""

from types import SimpleNamespace

import pytest
from sqlalchemy import column, create_engine, event, select, table, text

from pdos_next.database import _semantic_custom_plan, engine_for

OPTION = "pdos_semantic_custom_plan"


class Cursor:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def execute(self, sql, parameters, **kwargs):
        self.calls.append((sql, parameters, kwargs))
        if self.error is not None:
            raise self.error


def context(query, options=None):
    return SimpleNamespace(
        invoked_statement=query,
        execution_options=query.get_execution_options() if options is None else options,
    )


@pytest.mark.parametrize("parameters", [{}, {"bound": object()}], ids=["empty", "bound"])
def test_marked_select_uses_original_sql_parameters_once_and_handles_dispatch(parameters):
    query = select(1).execution_options(**{OPTION: True})
    sql = "SELECT %(bound)s"
    cursor = Cursor()
    assert _semantic_custom_plan(cursor, sql, parameters, context(query)) is True
    assert len(cursor.calls) == 1
    assert cursor.calls[0][0] is sql and cursor.calls[0][1] is parameters
    assert cursor.calls[0][2] == {"prepare": False}


@pytest.mark.parametrize("flag", [None, False, 0, 1, "true", "1"])
def test_only_strict_true_select_option_changes_driver_dispatch(flag):
    query = select(1).execution_options(**{OPTION: flag})
    cursor = Cursor()
    assert _semantic_custom_plan(cursor, "SELECT 1", {}, context(query)) is None
    assert not cursor.calls


@pytest.mark.parametrize(
    "query",
    [
        text("SELECT 1").execution_options(**{OPTION: True}),
        table("synthetic", column("value")).insert().execution_options(**{OPTION: True}),
        select(1).union_all(select(2)).execution_options(**{OPTION: True}),
        None,
    ],
    ids=["text", "insert", "compound", "driver_sql"],
)
def test_non_select_compilation_never_uses_custom_dispatch(query):
    cursor = Cursor()
    assert _semantic_custom_plan(cursor, "unchanged", {}, context(query, {OPTION: True})) is None
    assert not cursor.calls


def test_cached_mark_or_connection_option_cannot_mark_current_unmarked_select():
    query = select(1)
    execution = context(query, {OPTION: True})
    execution.compiled = SimpleNamespace(statement=select(1).execution_options(**{OPTION: True}))
    cursor = Cursor()
    assert _semantic_custom_plan(cursor, "SELECT 1", {}, execution) is None
    assert not cursor.calls


def test_effective_non_true_option_does_not_override_statement_dispatch():
    query = select(1).execution_options(**{OPTION: True})
    cursor = Cursor()
    assert _semantic_custom_plan(cursor, "SELECT 1", {}, context(query, {OPTION: 1})) is None
    assert not cursor.calls


def test_driver_failure_propagates_without_retry_or_fallback():
    query = select(1).execution_options(**{OPTION: True})
    error = RuntimeError("synthetic driver failure")
    cursor = Cursor(error)
    with pytest.raises(RuntimeError) as caught:
        _semantic_custom_plan(cursor, "SELECT 1", {}, context(query))
    assert caught.value is error and len(cursor.calls) == 1
    assert cursor.calls[0][2] == {"prepare": False}


def test_hook_registered_on_each_factory_engine_only_without_opening_a_connection(monkeypatch):
    import psycopg

    def forbidden_connection(*_args, **_kwargs):
        pytest.fail("Pure engine registration check must never connect")

    monkeypatch.setattr(psycopg, "connect", forbidden_connection)
    url = "postgresql+psycopg://synthetic@localhost:1/never_connect"
    first, second = engine_for(url), engine_for(url)
    unrelated = create_engine(url)
    try:
        assert first is not second
        for engine in (first, second):
            assert event.contains(engine, "do_execute", _semantic_custom_plan)
            assert engine.hide_parameters is True
        assert not event.contains(unrelated, "do_execute", _semantic_custom_plan)
    finally:
        for engine in (first, second, unrelated):
            engine.dispose()
