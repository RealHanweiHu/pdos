"""Unconnected pure wrapper checks; SQL events are explicit synthetic notifications."""

import sys
from pathlib import Path
from threading import Thread
from types import ModuleType, SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from current_read_profiler import CurrentReadProfiler, OwnerTarget
from sqlalchemy import create_engine, event


def engine_without_connections(monkeypatch):
    engine = create_engine("sqlite://")
    monkeypatch.setattr(engine, "connect", lambda *a, **k: pytest.fail("DB forbidden"))
    return engine


def test_nested_root_and_thread_boundary_count_once_restore_exact_returns(monkeypatch):
    engine = engine_without_connections(monkeypatch)
    other = engine_without_connections(monkeypatch)
    owner = ModuleType("explicit_fake_owners")
    token = object()
    observed = []
    profile = None

    def inner():
        context = object()
        conn = SimpleNamespace(engine=engine)
        profile._before(conn, None, "SELECT secret_literal", {"secret": "private"}, context, False)
        profile._after(conn, None, "SELECT secret_literal", {"secret": "private"}, context, False)
        return token

    def outer():
        assert owner.inner() is token
        thread = Thread(target=lambda: observed.append(owner.inner()))
        thread.start()
        thread.join()
        conn = SimpleNamespace(engine=other)
        context = object()
        profile._before(conn, None, "SELECT other_engine", (), context, False)
        profile._after(conn, None, "SELECT other_engine", (), context, False)
        return token

    owner.inner, owner.outer = inner, outer
    profile = CurrentReadProfiler(
        engine,
        [OwnerTarget(owner, "inner", "physical._basis"), OwnerTarget(owner, "outer", "retained")],
    )
    with profile:
        with profile.section("future_window_wait"):
            pass  # Label only; this test never sleeps or changes any clock.
        with profile.section("business"):
            assert owner.outer() is token
    assert observed == [token]
    assert owner.inner is inner and owner.outer is outer
    report = profile.report()
    assert report["owners"]["physical._basis"]["calls"] == 1
    assert report["owners"]["retained"]["calls"] == 1
    assert report["query_count"] == 1
    query = report["queries"][0]
    assert query["owner"] == "physical._basis" and query["section"] == "business"
    assert query["verb"] == "SELECT" and len(query["statement_sha256"]) == 64
    assert "secret_literal" not in repr(report) and "private" not in repr(report)
    assert report["owners"]["retained"]["inclusive_ns"] >= query["elapsed_ns"]
    assert report["sections"]["future_window_wait"]["calls"] == 1
    for name, callback in (
        ("before_cursor_execute", profile._before),
        ("handle_error", profile._error),
    ):
        assert event.contains(engine, name, callback) is False


def test_original_owner_exception_and_failed_sql_observation_survive_finally(monkeypatch):
    engine = engine_without_connections(monkeypatch)
    owner = ModuleType("explicit_fake_failure_owner")
    original_error = ValueError("original private error")
    profile = None

    def fail():
        conn = SimpleNamespace(engine=engine)
        context = object()
        profile._before(conn, None, "SELECT hidden", {"token": "not_emitted"}, context, False)
        profile._error(SimpleNamespace(execution_context=context, connection=conn))
        raise original_error

    owner.fail = fail
    profile = CurrentReadProfiler(engine, [OwnerTarget(owner, "fail", "resources._load")])
    with pytest.raises(ValueError) as caught, profile:
        owner.fail()
    assert caught.value is original_error
    assert owner.fail is fail
    report = profile.report()
    assert report["query_count"] == report["queries"][0]["failures"] == 1
    assert report["owners"]["resources._load"]["failures"] == 1
    assert report["conditions"]["unfinished_queries"] == 0
    assert "not_emitted" not in repr(report) and "original private error" not in repr(report)
    assert event.contains(engine, "after_cursor_execute", profile._after) is False


def test_nested_install_is_rejected_and_partial_install_failure_restores(monkeypatch):
    engine = engine_without_connections(monkeypatch)
    owner = ModuleType("explicit_fake_setup_owner")

    def original():
        return 17

    owner.read = original
    target = OwnerTarget(owner, "read", "front._recheck")
    first = CurrentReadProfiler(engine, [target])
    with first:
        with pytest.raises(RuntimeError, match="ownership"):
            with CurrentReadProfiler(engine, [target]):
                pytest.fail("Nested install forbidden")
        assert owner.read() == 17
    assert owner.read is original
    assert first.report()["owners"]["front._recheck"]["calls"] == 1
    listen = event.listen

    def broken(target, name, callback, *args, **kwargs):
        if name == "after_cursor_execute":
            raise RuntimeError("explicit simulated install failure")
        return listen(target, name, callback, *args, **kwargs)

    monkeypatch.setattr(event, "listen", broken)
    failed = CurrentReadProfiler(engine, [target])
    with pytest.raises(RuntimeError, match="simulated"), failed:
        pytest.fail("Partial installation must fail before case execution")
    assert owner.read is original
    assert event.contains(engine, "before_cursor_execute", failed._before) is False
    assert failed.report()["query_count"] == 0
