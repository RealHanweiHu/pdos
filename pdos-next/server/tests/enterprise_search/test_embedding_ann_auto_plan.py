"""Same-execution attribution and redaction controls; no Docker/database calls."""

import json
from types import SimpleNamespace

import pytest

from tests.enterprise_search.embedding_ann_auto_plan import (
    CONFIG,
    AutoPlanCapture,
    match_plans,
    normalized_sql,
    sql_digest,
)
from tests.enterprise_search.embedding_ann_fixture import HNSW_INDEX, safe_plan

SQL = "SELECT semantic_source_ranks.source_id WHERE tenant_id=%(tenant)s LIMIT %(limit)s"
SERVER_SQL = "SELECT semantic_source_ranks.source_id WHERE tenant_id=$1 LIMIT $2"
SECRET = "SYNTHETIC_VECTOR_AND_SOURCE_BODY_MUST_NOT_ESCAPE"


def log_record(sql=SERVER_SQL, *, pid=77, loops=1, index=True):
    node = {
        "Node Type": "Index Scan" if index else "Seq Scan",
        "Actual Loops": loops,
        "Filter": SECRET,
        "Output": [SECRET],
    }
    if index:
        node["Index Name"] = HNSW_INDEX
    value = {"Query Text": sql, "Plan": node, "Query Parameters": SECRET}
    return (
        f"2026-10-29 12:00:00 UTC [{pid}] LOG:  duration: 1.234 ms  plan:\n"
        + json.dumps(value, indent=2)
        + "\n"
    )


def test_sql_match_preserves_parameter_aliases_constants_and_literal_contents():
    assert normalized_sql(SQL) == normalized_sql(SERVER_SQL)
    assert sql_digest(SQL) == sql_digest(SERVER_SQL)
    assert normalized_sql("a=%(x)s OR b=%(x)s") == "a=$1 OR b=$1"
    assert normalized_sql("a=$3 OR b=$3") == "a=$1 OR b=$1"
    assert normalized_sql("a=$1 OR b=$2") != normalized_sql("a=$1 OR b=$1")
    assert normalized_sql("SELECT 'two  spaces %(x)s' LIMIT 1") != normalized_sql(
        "SELECT 'two spaces %(x)s' LIMIT 1"
    )
    assert sql_digest(SERVER_SQL + " OFFSET 1") != sql_digest(SERVER_SQL + " OFFSET 2")


def test_strict_same_query_pid_order_count_match_returns_only_safe_actual_plans():
    logs = log_record(pid=88) + log_record() + log_record(index=False)
    result = match_plans(logs, 77, [SQL, SQL], safe_plan)
    assert result["status"] == "same_execution_matched"
    assert result["expected_statements"] == result["observed_statements"] == 2
    assert result["plans"][0]["Plan"]["Index Name"] == HNSW_INDEX
    assert result["plans"][1]["Plan"]["Node Type"] == "Seq Scan"
    assert SECRET not in json.dumps(result) and "Query Text" not in json.dumps(result)


@pytest.mark.parametrize(
    "logs,statements,status",
    [
        (log_record(pid=88), [SQL], "actual_plan_missing"),
        (log_record(), [SQL, SQL], "actual_plan_missing"),
        (log_record() * 2, [SQL], "query_sequence_mismatch"),
        (log_record(SERVER_SQL + " OFFSET 1"), [SQL], "query_sequence_mismatch"),
        (
            log_record(SERVER_SQL + " OFFSET 2") + log_record(SERVER_SQL + " OFFSET 1"),
            [SQL + " OFFSET 1", SQL + " OFFSET 2"],
            "query_sequence_mismatch",
        ),
        (log_record(loops=None), [SQL], "log_plan_invalid"),
        (log_record()[:-30], [SQL], "log_plan_invalid"),
    ],
    ids=["wrong_pid", "missing", "extra", "different_sql", "order", "no_analyze", "truncated"],
)
def test_missing_mismatch_order_extra_or_unanalyzed_plan_never_attributes(logs, statements, status):
    result = match_plans(logs, 77, statements, safe_plan)
    assert result["status"] == status and result["plans"] == []
    assert SECRET not in json.dumps(result)


def test_prefixed_multiline_json_is_supported_without_retaining_text():
    lines = log_record().splitlines()
    logs = lines[0] + "\n" + "\n".join(
        "2026-10-29 12:00:00 UTC [77] " + line for line in lines[1:]
    )
    result = match_plans(logs, 77, [SQL], safe_plan)
    assert result["status"] == "same_execution_matched"
    assert SECRET not in json.dumps(result)


class Driver:
    def __init__(self, configuration=CONFIG):
        self.configuration = configuration
        self.closed = False
        self.info = SimpleNamespace(
            backend_pid=77, transaction_status=SimpleNamespace(name="INTRANS")
        )
        self.executed = []

    def cursor(self):
        driver = self

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

            def execute(self, statement):
                driver.executed.append(statement)

            def fetchone(self):
                return tuple(driver.configuration[name] for name in CONFIG)

        return Cursor()


def capture(monkeypatch, driver=None):
    monkeypatch.setenv("PDOS_ANN_AUTO_PLAN", "1")
    monkeypatch.setenv("PDOS_ANN_CONTAINER", "explicit-local-test-container")
    driver = driver or Driver()
    connection = SimpleNamespace(connection=SimpleNamespace(driver_connection=driver))
    return AutoPlanCapture(connection), driver


def test_nearest_only_duration_bracket_on_same_driver_and_safe_actual_capture(monkeypatch):
    observer, driver = capture(monkeypatch)
    observer.before("SELECT semantic_eligible_chunk")
    observer.after("SELECT semantic_eligible_chunk")
    observer.before(SQL)
    observer.after(SQL)
    observer.close()
    assert driver.executed[1:] == [
        "SET LOCAL auto_explain.log_min_duration = 0",
        "SET LOCAL auto_explain.log_min_duration = -1",
    ]
    result = observer.collect(safe_plan, timeout=0, reader=lambda *_: log_record())
    assert result["status"] == "same_execution_matched"
    assert result["enabled"] is True and observer.completed == 1
    assert SECRET not in json.dumps(result)


def test_no_flag_does_not_touch_driver_and_is_explicit_replay_only(monkeypatch):
    monkeypatch.delenv("PDOS_ANN_AUTO_PLAN", raising=False)
    observer = AutoPlanCapture(None)
    observer.before(SQL)
    observer.after(SQL)
    observer.close()
    assert observer.collect(safe_plan) == {"status": "replay_only", "plans": [], "enabled": False}


def test_parameter_logging_or_missing_root_configuration_is_rejected_without_values(monkeypatch):
    altered = {**CONFIG, "auto_explain.log_parameter_max_length": SECRET}
    with pytest.raises(AssertionError, match="configuration does not match") as error:
        capture(monkeypatch, Driver(altered))
    assert SECRET not in str(error.value)


def test_log_reader_failure_does_not_surface_raw_stderr_or_credit(monkeypatch):
    observer, _driver = capture(monkeypatch)
    observer.before(SQL)
    observer.after(SQL)

    def fail(*_args):
        raise RuntimeError(SECRET)

    result = observer.collect(safe_plan, timeout=0, reader=fail)
    assert result["status"] == "log_read_failed" and result["plans"] == []
    assert SECRET not in json.dumps(result)


def test_close_disarms_duration_after_local_non_aborted_failure(monkeypatch):
    observer, driver = capture(monkeypatch)
    observer.before(SQL)
    observer.close()
    assert driver.executed[-1] == "SET LOCAL auto_explain.log_min_duration = -1"
    assert not observer.active


def test_close_on_already_closed_driver_preserves_original_keyboard_interrupt(monkeypatch):
    observer, driver = capture(monkeypatch)
    observer.before(SQL)
    driver.closed = True
    # A closed driver has no usable transaction; close must neither inspect its
    # transaction nor issue a SET that could mask the original cancellation.
    driver.info = None
    with pytest.raises(KeyboardInterrupt):
        try:
            raise KeyboardInterrupt
        finally:
            observer.close()
    assert driver.executed[-1] == "SET LOCAL auto_explain.log_min_duration = 0"
    assert not observer.active
