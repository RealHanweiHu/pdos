"""Load eligibility, real replacement budgeting and honest metric scope; no database."""

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def tools(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]))
    return (
        importlib.import_module("s0_performance"),
        importlib.import_module("s0_b8_performance_summary"),
    )


def row(core, *, start=0, end=0, cores=4, seconds=0.5, sql=7, longer=0):
    averages = {
        "start": {"1min": start, "5min": longer, "15min": longer},
        "end": {"1min": end, "5min": longer, "15min": longer},
    }
    reason = core.exclusion_reason(cores, averages)
    return {
        "success": True,
        "elapsed_seconds": seconds,
        "sql_count": sql,
        "load_policy": core.LOAD_POLICY,
        "logical_cpu_count": cores,
        "load_averages": averages,
        "excluded_from_performance": reason is not None,
        "exclusion_reason": reason,
    }


@pytest.mark.parametrize("start,end,excluded", [(4, 4, False), (4.01, 0, True), (0, 4.01, True)])
def test_only_start_or_end_one_minute_above_logical_cores_excludes(tools, start, end, excluded):
    core, _ = tools
    value = row(core, start=start, end=end, longer=100)
    assert value["excluded_from_performance"] is excluded
    assert core.eligible_rows([value]) == ([] if excluded else [value])


def test_actual_os_boundaries_and_all_three_averages_are_retained(tools, monkeypatch):
    core, _ = tools
    values = iter([(1.0, 2.0, 3.0), (5.0, 6.0, 7.0)])
    monkeypatch.setattr(core.os, "cpu_count", lambda: 4)
    monkeypatch.setattr(core.os, "getloadavg", lambda: next(values))
    value = core.finish_sample_load(core.start_sample_load())
    assert value["logical_cpu_count"] == 4
    assert value["load_averages"] == {
        "start": {"1min": 1.0, "5min": 2.0, "15min": 3.0},
        "end": {"1min": 5.0, "5min": 6.0, "15min": 7.0},
    }
    assert value["exclusion_reason"] == "system_load_exceeds_logical_cpu_count"


@pytest.mark.parametrize("cores", [None, 0, -1, True])
def test_unknown_cpu_count_is_pending_eligibility_not_fabricated_capacity(tools, cores):
    core, _ = tools
    value = row(core, cores=cores)
    assert value["exclusion_reason"] == "logical_cpu_count_unavailable"
    assert core.eligible_rows([value]) == []


def test_os_load_unavailable_never_becomes_an_eligible_sample(tools, monkeypatch):
    core, _ = tools

    def unavailable():
        raise OSError("unavailable")

    monkeypatch.setattr(core.os, "getloadavg", unavailable)
    monkeypatch.setattr(core.os, "cpu_count", lambda: 4)
    value = core.finish_sample_load(core.start_sample_load())
    assert value["exclusion_reason"] == "load_averages_unavailable"
    assert core.eligible_rows([{"success": True, **value}]) == []


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), -1, True])
def test_invalid_raw_load_is_preserved_as_excluded(tools, bad):
    core, _ = tools
    value = row(core, start=bad)
    assert core.eligible_rows([value]) == []
    assert value["exclusion_reason"] == "load_averages_unavailable"


def test_excluded_slow_rows_and_sql_never_enter_percentiles_or_sql_range(tools):
    core, summary = tools
    excluded = row(core, start=5, seconds=100, sql=999999)
    observed = [excluded, *[row(core) for _ in range(30)]]
    result = summary.summarize(observed, 1, allow_legacy=False)
    assert result["p95_seconds"] == 0.5 and result["sql_range"] == [7, 7]
    assert result["samples"] == 30 and result["observed_samples"] == 31
    assert result["excluded_samples"] == 1 and result["load_validated"] is True
    assert observed[0] == excluded


def test_surplus_valid_rows_do_not_select_the_fastest_thirty(tools):
    core, summary = tools
    observed = [row(core, seconds=2, sql=11) for _ in range(30)] + [row(core, seconds=0.1)]
    result = summary.summarize(observed, 1, allow_legacy=False)
    assert result["p95_seconds"] == 2 and result["passed"] is False
    assert result["sql_range"] == [11, 11] and result["unused_valid_samples"] == 1


def test_high_load_cannot_hide_a_business_error(tools):
    core, summary = tools
    failed = {**row(core, start=5), "success": False}
    with pytest.raises(RuntimeError, match="business failure"):
        summary.summarize([failed, *[row(core) for _ in range(30)]], 1)
    counts = core.sampling_counts({"commit": [failed]}, ["commit"])
    assert counts["commit"] == {"observed": 1, "eligible": 0, "excluded": 0, "failed": 1}


def test_an_exclusion_flag_must_match_raw_start_end_measurements(tools):
    core, _ = tools
    forged = {**row(core, start=5), "excluded_from_performance": False, "exclusion_reason": None}
    with pytest.raises(RuntimeError, match="disagrees"):
        core.eligible_rows([forged])


def test_partial_eligible_rows_cannot_produce_a_pass_or_partial_p95(tools):
    core, summary = tools
    with pytest.raises(RuntimeError, match="thirty eligible"):
        summary.summarize([row(core) for _ in range(29)] + [row(core, end=5)], 1)


def test_real_replacements_continue_until_thirty_eligible_without_discarding_raw_rows(tools):
    core, _ = tools
    rows = {"commit": []}
    attempted = []
    for attempt in core.sample_attempts(rows, ("commit",)):
        attempted.append(attempt)
        rows["commit"].append(row(core, end=5 if attempt == 0 else 0))
    assert attempted == list(range(31))
    assert len(rows["commit"]) == 31 and len(core.eligible_rows(rows["commit"])) == 30


def test_persistent_high_load_exhausts_finite_budget_as_pending(tools):
    core, _ = tools
    rows = {"commit": []}
    with pytest.raises(core.PerformancePending, match="budget exhausted"):
        for _ in core.sample_attempts(rows, ("commit",), max_attempts=3):
            rows["commit"].append(row(core, end=5))
    assert len(rows["commit"]) == 3 and len(core.eligible_rows(rows["commit"])) == 0


def test_grouped_paths_need_thirty_each_and_keep_surplus_from_real_cases(tools):
    core, _ = tools
    rows = {"read": [], "commit": []}
    for attempt in core.sample_attempts(rows, ("read", "commit")):
        rows["read"].append(row(core))
        rows["commit"].append(row(core, end=5 if attempt == 0 else 0))
    assert len(rows["read"]) == 31 and len(rows["commit"]) == 31
    assert len(core.eligible_rows(rows["commit"])) == 30


def test_old_no_load_evidence_is_explicit_legacy_and_cannot_mix_with_new_samples(tools):
    core, summary = tools
    old = [{"success": True, "elapsed_seconds": 0.5, "sql_count": 7} for _ in range(30)]
    result = summary.summarize(old, 1)
    assert result["legacy_scope"] is True and result["load_validated"] is False
    with pytest.raises(RuntimeError, match="Legacy samples"):
        summary.summarize(old, 1, allow_legacy=False)
    with pytest.raises(RuntimeError, match="cannot be mixed"):
        summary.summarize([*old, row(core)], 1)


def test_non_200_response_preserves_observed_load_and_sql_as_business_failure(tools, monkeypatch):
    core, _ = tools

    class Profile:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def report(self):
            return {"query_count": 1}

    monkeypatch.setattr(core, "CurrentReadProfiler", Profile)
    monkeypatch.setattr(core.event, "listen", lambda *_args: None)
    monkeypatch.setattr(core.event, "remove", lambda *_args: None)
    monkeypatch.setattr(core.os, "cpu_count", lambda: 4)
    monkeypatch.setattr(core.os, "getloadavg", lambda: (5, 5, 5))
    with pytest.raises(RuntimeError, match="HTTP 403") as caught:
        core.measure(
            SimpleNamespace(engine=object(), auth=object()),
            "commit",
            lambda: SimpleNamespace(status_code=403),
        )
    observed = caught.value.performance_sample
    assert observed["http_status"] == 403 and observed["excluded_from_performance"] is True
    assert observed["app_sql_count"] == observed["auth_sql_count"] == 1


def test_empty_required_path_set_cannot_be_vacuously_complete(tools):
    core, _ = tools
    with pytest.raises(ValueError, match="nonempty unique"):
        list(core.sample_attempts({}, ()))


def test_existing_short_evidence_is_never_overwritten_on_failed_or_pending_write(tools, tmp_path):
    core, _ = tools
    output = tmp_path / "short-paths.json"
    output.write_text("original preserved\n")
    with pytest.raises(FileExistsError):
        core.write_short_text(output, "new pending or failure\n")
    assert output.read_text() == "original preserved\n"
