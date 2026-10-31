"""Test-only replay controls; scripted SQL transport, no database or Docker."""

from types import SimpleNamespace

import pytest

from tests.enterprise_search import embedding_ann_fixture as fixture


def observed_run(monkeypatch, *, strategy="iterative", status="same_execution_matched", option="0"):
    if option is None:
        monkeypatch.delenv("PDOS_ANN_REPLAY_PLAN", raising=False)
    else:
        monkeypatch.setenv("PDOS_ANN_REPLAY_PLAN", option)
    monkeypatch.setenv("PDOS_ANN_AUTO_PLAN", "1")
    callbacks, replays, originals = {}, [], []
    pools = [200, 400, 800] if strategy == "iterative" else [None]
    counts = [4, 7, 11] if strategy == "iterative" else [11]
    source_ids = [f"synthetic-control-source-{index}" for index in range(11)]

    class Observer:
        def __init__(self, _connection):
            pass

        def before(self, _sql):
            pass

        def after(self, _sql):
            pass

        def close(self):
            pass

        def collect(self, sanitize):
            plans = []
            if status == "same_execution_matched":
                for index in range(len(pools)):
                    ann = strategy == "iterative" and index == len(pools) - 1
                    node = {"Node Type": "Index Scan" if ann else "Seq Scan", "Actual Loops": 1}
                    if ann:
                        node["Index Name"] = fixture.HNSW_INDEX
                    plans.append(sanitize({"Plan": node}))
            return {"status": status, "plans": plans}

    def listen(_connection, name, callback):
        callbacks[name] = callback

    def remove(_connection, name, callback):
        assert callbacks.pop(name) is callback

    def production(_session, _ctx, _data, _profile, _vector, *, strategy, scan_evidence):
        stages = [
            {
                "strategy": strategy,
                "pool_limit": pool,
                "candidate_chunks": pool,
                "returned_sources": count,
                "source_ids": source_ids[:count],
            }
            for pool, count in zip(pools, counts, strict=True)
        ]
        scan_evidence.update(executed_strategy=strategy, attempts=stages)
        sqls = (["SELECT semantic_eligible_chunk"] if strategy == "iterative" else []) + [
            "SELECT semantic_source_ranks "
            + ("iterative_semantic_neighbors" if strategy == "iterative" else "exact_semantic_pool")
            for _pool in pools
        ]
        for sql in sqls:
            originals.append(sql)
            for name in ("before_cursor_execute", "after_cursor_execute"):
                callbacks[name](None, None, sql, {}, None, False)
        return [{"source_id": identity} for identity in source_ids]

    def explain(sql, _parameters):
        assert not callbacks
        replays.append(sql)
        return SimpleNamespace(
            scalar_one=lambda: [{"Plan": {"Node Type": "Seq Scan", "Actual Loops": 1}}]
        )

    connection = SimpleNamespace(exec_driver_sql=explain)
    monkeypatch.setattr(fixture.event, "listen", listen)
    monkeypatch.setattr(fixture.event, "remove", remove)
    monkeypatch.setattr(fixture, "AutoPlanCapture", Observer)
    monkeypatch.setattr(fixture, "semantic_rows", production)
    monkeypatch.setattr(fixture, "settings", lambda _session: {"enable_seqscan": "on"})
    monkeypatch.setattr(fixture, "prepared_statement_counts", lambda *_args: {})
    rows, observation = fixture.semantic_with_plan(
        SimpleNamespace(connection=lambda: connection), None, None, None, None, strategy
    )
    assert observation["strategy_elapsed_ms"] >= 0
    scope = observation["strategy_elapsed_scope"]
    assert scope["clock"] == "perf_counter"
    assert scope["includes"] == ["production_semantic_rows", "observer_SET_callbacks"]
    assert scope["excludes"] == [
        "observer_setup", "collect", "log_parsing", "independent_replay",
        "prepared_statement_counts",
    ]
    assert scope["cross_replay_mode_causal_comparison"] is False
    return rows, observation, originals, replays


@pytest.mark.parametrize("option", [None, "1"], ids=["default", "explicit_one"])
def test_default_or_one_preserves_every_original_replay_without_attributing_it(monkeypatch, option):
    _rows, observation, originals, replays = observed_run(monkeypatch, option=option)
    assert len(originals) == len(replays) == 4
    assert replays == ["EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql for sql in originals]
    assert observation["hnsw_exercised"] is True  # Actual final plan, not replay's Seq Scan.
    for entry in observation["executions"] + observation["probe_executions"]:
        replay = entry["explain_replay"]
        assert replay["enabled"] is True and replay["plan"] is not None
        assert replay["ann_recall_attribution"] is False
        assert replay["is_second_execution_in_same_read_snapshot"] is True
        assert replay["reason"] == "enabled_by_test_option"


@pytest.mark.parametrize("strategy", ["exact", "iterative"])
def test_zero_preserves_matched_actual_exact_and_multi_pool_plans_without_replay(
    monkeypatch, strategy
):
    rows, observation, originals, replays = observed_run(monkeypatch, strategy=strategy)
    assert len(rows) == 11 and not replays
    assert len(originals) == (4 if strategy == "iterative" else 1)
    assert observation["hnsw_exercised"] is (strategy == "iterative")
    assert observation["actual_plan_capture"]["status"] == "same_execution_matched"
    assert [entry["pool_limit"] for entry in observation["executions"]] == (
        [200, 400, 800] if strategy == "iterative" else [None]
    )
    for entry in observation["executions"]:
        assert entry["plan"] is not None and entry["plan_attribution"] == "same_execution_matched"
    for entry in observation["executions"] + observation["probe_executions"]:
        replay = entry["explain_replay"]
        assert replay["enabled"] is False and replay["plan"] is None
        assert replay["hnsw_exercised"] is False
        assert replay["ann_recall_attribution"] is False
        assert replay["is_second_execution_in_same_read_snapshot"] is False
        assert replay["reason"] == "disabled_by_test_option_actual_matched"
    assert all(
        entry["plan_attribution"] == "not_observed" for entry in observation["probe_executions"]
    )


@pytest.mark.parametrize(
    "status", ["actual_plan_missing", "query_sequence_mismatch", "log_read_failed"]
)
def test_zero_failed_capture_has_no_credit_and_never_implicitly_replays(monkeypatch, status):
    rows, observation, originals, replays = observed_run(monkeypatch, status=status)
    assert len(rows) == 11 and len(originals) == 4 and not replays
    assert observation["plan"] is None
    assert observation["hnsw_exercised"] is observation["any_stage_hnsw_exercised"] is False
    assert observation["actual_plan_capture"]["status"] == status
    for entry in observation["executions"]:
        assert entry["plan"] is None and entry["plan_attribution"] == status
        assert entry["explain_replay"]["reason"] == "disabled_by_test_option_capture_unattributed"
        assert entry["explain_replay"]["plan"] is None


@pytest.mark.parametrize("auto", [None, "0", "true"], ids=["unset", "off", "not_one"])
def test_zero_without_explicit_auto_observer_rejects_before_connection(monkeypatch, auto):
    monkeypatch.setenv("PDOS_ANN_REPLAY_PLAN", "0")
    if auto is None:
        monkeypatch.delenv("PDOS_ANN_AUTO_PLAN", raising=False)
    else:
        monkeypatch.setenv("PDOS_ANN_AUTO_PLAN", auto)
    with pytest.raises(ValueError, match="requires PDOS_ANN_AUTO_PLAN=1"):
        fixture.semantic_with_plan(None, None, None, None, None, "iterative")


@pytest.mark.parametrize("option", ["", "false", "true", "2", " 0"])
def test_invalid_replay_option_rejects_before_connection(monkeypatch, option):
    monkeypatch.setenv("PDOS_ANN_REPLAY_PLAN", option)
    with pytest.raises(ValueError, match="must be 0 or 1"):
        fixture.semantic_with_plan(None, None, None, None, None, "iterative")
