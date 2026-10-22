"""Synthetic event notifications on unconnected actual Engines/Sessions only."""

import json
from threading import Barrier, Event, Thread
from types import ModuleType, SimpleNamespace

import pytest
from current_read_profiler import CurrentReadProfiler, OwnerTarget
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session


def restored(engine, profiler):
    for name, callback in (
        ("before_cursor_execute", profiler._before),
        ("after_cursor_execute", profiler._after),
        ("handle_error", profiler._error),
    ):
        assert event.contains(engine, name, callback) is False


def test_worker_nested_owners_pair_same_context_per_thread_and_never_borrow_root_section():
    engine = create_engine("sqlite://")
    owner = ModuleType("worker_same_engine_owners")
    shared_conn, shared_context = SimpleNamespace(engine=engine), object()
    before_sql, after_sql = Barrier(2), Barrier(2)
    tokens, outcomes, errors = [object(), object()], [], []
    profiler = None

    def inner_a(session):
        before_sql.wait(timeout=3)
        profiler._before(
            shared_conn,
            None,
            "SELECT HIDDEN_STATEMENT",
            {"token": "HIDDEN_ARG"},
            shared_context,
            False,
        )
        after_sql.wait(timeout=3)
        profiler._error(SimpleNamespace(execution_context=shared_context, connection=shared_conn))
        return tokens[0]

    def inner_b(session):
        before_sql.wait(timeout=3)
        profiler._before(
            shared_conn,
            None,
            "SELECT HIDDEN_STATEMENT",
            {"token": "HIDDEN_ARG"},
            shared_context,
            True,
        )
        after_sql.wait(timeout=3)
        profiler._after(shared_conn, None, "SELECT HIDDEN_STATEMENT", (), shared_context, True)
        return tokens[1]

    def outer(session, index):
        return owner.inner_a(session) if index == 0 else owner.inner_b(session)

    owner.inner_a, owner.inner_b, owner.outer = inner_a, inner_b, outer
    profiler = CurrentReadProfiler(
        engine,
        [
            OwnerTarget(owner, "inner_a", "physical._basis"),
            OwnerTarget(owner, "inner_b", "resources._load"),
            OwnerTarget(owner, "outer", "api_owner"),
        ],
        include_worker_threads=True,
    )

    def worker(index):
        try:
            with Session(engine) as session:
                outcomes.append((index, owner.outer(session, index)))
        except BaseException as error:
            errors.append(error)

    with profiler, profiler.section("root_http_start"):
        threads = [Thread(target=worker, args=(index,)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
            assert thread.is_alive() is False
        profiler._before(shared_conn, None, "SELECT ROOT_STATEMENT", (), shared_context, False)
        profiler._after(shared_conn, None, "SELECT ROOT_STATEMENT", (), shared_context, False)
    assert errors == [] and sorted(outcomes) == list(enumerate(tokens))
    assert owner.outer is outer and owner.inner_a is inner_a and owner.inner_b is inner_b
    report = profiler.report()
    assert report["scope"]["root_thread_only"] is False
    assert report["schema_version"] == "pdos-root-current-read-profile-v2"
    assert report["owners"]["api_owner"]["calls"] == 2
    assert report["owners"]["physical._basis"]["calls"] == 1
    assert report["owners"]["resources._load"]["calls"] == 1
    assert report["query_count"] == 3
    worker_queries = {row["owner"]: row for row in report["queries"] if row["owner"] != "root"}
    assert set(worker_queries) == {"physical._basis", "resources._load"}
    assert all(row["section"] == "unattributed" for row in worker_queries.values())
    assert worker_queries["physical._basis"]["failures"] == 1
    assert worker_queries["resources._load"]["failures"] == 0
    assert worker_queries["resources._load"]["executemany_calls"] == 1
    root_queries = [row for row in report["queries"] if row["owner"] == "root"]
    assert root_queries[0]["section"] == "root_http_start"
    assert report["conditions"]["unattributed_worker_section_queries"] == 2
    assert report["conditions"]["active_owner_calls_at_exit"] == 0
    assert report["conditions"]["unfinished_queries"] == 0
    assert "HIDDEN_STATEMENT" not in json.dumps(report) and "HIDDEN_ARG" not in json.dumps(report)
    restored(engine, profiler)


def test_other_engine_unknown_session_and_nonroot_section_are_not_inferred():
    engine, other = create_engine("sqlite://"), create_engine("sqlite://")
    owner = ModuleType("worker_scope_owners")
    token, outcomes, errors = object(), [], []
    profiler = None

    def read(session):
        conn, context = SimpleNamespace(engine=engine), object()
        profiler._before(conn, None, "SELECT PRIVATE_BINDING", (), context, False)
        profiler._after(conn, None, "SELECT PRIVATE_BINDING", (), context, False)
        return token

    owner.read = read
    profiler = CurrentReadProfiler(
        engine, [OwnerTarget(owner, "read", "fixed_owner")], include_worker_threads=True
    )

    def worker():
        try:
            with Session(other) as session:
                outcomes.append(owner.read(session))
            # No actual Session, no borrowed Root section or engine resolver call.
            resolver = SimpleNamespace(get_bind=lambda: pytest.fail("Resolver forbidden"))
            outcomes.append(owner.read(resolver))
            with pytest.raises(RuntimeError, match="Root thread"):
                with profiler.section("cannot_cross_thread"):
                    pytest.fail("Root section must be refused")
            foreign_conn, context = SimpleNamespace(engine=other), object()
            profiler._before(foreign_conn, None, "SELECT OTHER_ENGINE", (), context, False)
            profiler._after(foreign_conn, None, "SELECT OTHER_ENGINE", (), context, False)
        except BaseException as error:
            errors.append(error)

    with profiler, profiler.section("unrelated_root_section"):
        thread = Thread(target=worker)
        thread.start()
        thread.join(timeout=5)
        assert thread.is_alive() is False
    assert errors == [] and outcomes == [token, token]
    report = profiler.report()
    assert report["owners"] == {} and report["query_count"] == 2
    assert all(row["owner"] == row["section"] == "unattributed" for row in report["queries"])
    assert report["conditions"]["owner_calls_bound_to_another_engine"] == 1
    assert report["conditions"]["owner_calls_without_exact_engine_binding"] == 1
    assert report["sections"].keys() == {"unrelated_root_section"}
    assert owner.read is read
    restored(engine, profiler)


def test_worker_original_exception_is_identical_and_sql_failure_is_restored():
    engine = create_engine("sqlite://")
    owner = ModuleType("worker_failure_owner")
    failure, errors = ValueError("PRIVATE_EXCEPTION"), []
    profiler = None

    def fail(session):
        conn, context = SimpleNamespace(engine=engine), object()
        profiler._before(
            conn, None, "SELECT SECRET_FAILURE", {"password": "SECRET_PASSWORD"}, context, False
        )
        profiler._error(SimpleNamespace(execution_context=context, connection=conn))
        raise failure

    owner.fail = fail
    profiler = CurrentReadProfiler(
        engine, [OwnerTarget(owner, "fail", "retained.inspect")], include_worker_threads=True
    )

    def worker():
        try:
            with Session(engine) as session:
                owner.fail(session)
        except BaseException as error:
            errors.append(error)

    with profiler:
        thread = Thread(target=worker)
        thread.start()
        thread.join(timeout=5)
        assert thread.is_alive() is False
    assert errors == [failure] and errors[0] is failure and owner.fail is fail
    report = profiler.report()
    assert report["owners"]["retained.inspect"]["failures"] == 1
    assert report["query_count"] == report["queries"][0]["failures"] == 1
    assert "SECRET_PASSWORD" not in json.dumps(report) and "PRIVATE_EXCEPTION" not in json.dumps(
        report
    )
    restored(engine, profiler)


def test_exit_with_active_worker_restores_immediately_marks_partial_and_freezes_report():
    engine = create_engine("sqlite://")
    owner = ModuleType("worker_exit_owner")
    entered, release = Event(), Event()
    token, outcomes, errors = object(), [], []
    profiler = None

    def pending(session):
        conn, context = SimpleNamespace(engine=engine), object()
        profiler._before(conn, None, "SELECT STILL_PENDING", (), context, False)
        entered.set()
        assert release.wait(timeout=5)
        profiler._after(conn, None, "SELECT STILL_PENDING", (), context, False)
        return token

    owner.pending = pending
    profiler = CurrentReadProfiler(
        engine, [OwnerTarget(owner, "pending", "pending_owner")], include_worker_threads=True
    )

    def worker():
        try:
            with Session(engine) as session:
                outcomes.append(owner.pending(session))
        except BaseException as error:
            errors.append(error)

    try:
        with profiler:
            thread = Thread(target=worker)
            thread.start()
            assert entered.wait(timeout=5)
        assert owner.pending is pending
        restored(engine, profiler)
        report = profiler.report()
        frozen = json.dumps(report, sort_keys=True)
        assert report["conditions"]["active_owner_calls_at_exit"] == 1
        assert report["conditions"]["unfinished_queries"] == 1
        assert report["owners"] == {} and report["query_count"] == 0
    finally:
        release.set()
        thread.join(timeout=5)
    assert thread.is_alive() is False and errors == [] and outcomes == [token]
    assert json.dumps(profiler.report(), sort_keys=True) == frozen


def test_query_pair_mismatched_connection_does_not_silently_complete_another_query():
    engine = create_engine("sqlite://")
    profiler = CurrentReadProfiler(engine, [], include_worker_threads=True)
    context = object()
    first, other = SimpleNamespace(engine=engine), SimpleNamespace(engine=engine)
    with profiler:
        profiler._before(first, None, "SELECT PAIRING", (), context, False)
        profiler._after(other, None, "SELECT PAIRING", (), context, False)
    report = profiler.report()
    assert report["query_count"] == 0
    assert report["conditions"]["unmatched_completion_events"] == 1
    assert report["conditions"]["unfinished_queries"] == 1
    restored(engine, profiler)


def test_observation_failure_does_not_change_original_return_or_emit_data():
    engine = create_engine("sqlite://")
    owner = ModuleType("worker_observer_error_owner")
    token, outcomes, errors = object(), [], []
    profiler = None

    def read(session):
        # A broken synthetic event must not prevent the original owner returning.
        profiler._before(SimpleNamespace(engine=engine), None, None, object(), object(), False)
        return token

    owner.read = read
    profiler = CurrentReadProfiler(
        engine, [OwnerTarget(owner, "read", "observed_owner")], include_worker_threads=True
    )

    def worker():
        try:
            with Session(engine) as session:
                outcomes.append(owner.read(session))
        except BaseException as error:
            errors.append(error)

    with profiler:
        thread = Thread(target=worker)
        thread.start()
        thread.join(timeout=5)
    assert thread.is_alive() is False and errors == [] and outcomes == [token]
    report = profiler.report()
    assert report["owners"]["observed_owner"]["calls"] == 1 and report["query_count"] == 0
    assert report["conditions"]["query_observation_failures"] == 1
    assert owner.read is read
    restored(engine, profiler)


@pytest.mark.parametrize("value", [None, 1, "true"])
def test_worker_enablement_is_explicit_boolean(value):
    with pytest.raises(TypeError, match="explicit boolean"):
        CurrentReadProfiler(create_engine("sqlite://"), [], include_worker_threads=value)
