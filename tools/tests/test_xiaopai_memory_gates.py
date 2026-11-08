"""Rule-judged memory gates and the no-memory baseline; standard JSON and no services."""

import pytest
from xiaopai_memory_gates import CASE_VERSION, score

CASES = {"version": CASE_VERSION, "cases": [
    {"id": "R1", "kind": "recall", "owner": "owner", "expect_runs": ["last-week"],
     "status": "candidate"},
    {"id": "I1", "kind": "isolation", "owner": "owner", "forbidden_runs": ["peer-run"],
     "status": "candidate"},
    {"id": "N1", "kind": "injection", "owner": "owner", "status": "candidate"},
    {"id": "D1", "kind": "deletion", "owner": "owner", "forbidden_runs": ["hidden-run"],
     "status": "candidate"},
    {"id": "G1", "kind": "degradation", "owner": "owner", "expect_runs": ["last-week"],
     "status": "candidate"},
]}


def clean():
    real = [
        {"group": "real", "case_id": "R1", "returned": [{"run": "last-week", "owner": "owner"}]},
        {"group": "real", "case_id": "I1", "returned": []},
        {"group": "real", "case_id": "N1", "returned": [], "proposals_admitted": 0},
        {"group": "real", "case_id": "D1", "returned": []},
        {"group": "real", "case_id": "G1", "returned": [{"run": "last-week", "owner": "owner"}],
         "index_pending": 1},
    ]
    base = [{"group": "no_memory", "case_id": row["case_id"], "returned": [], "memory_reads": 0,
             "episode_written": False} for row in real]
    return real + base


def test_clean_run_passes_every_gate_and_reports_the_no_memory_baseline():
    report = score(CASES, clean())
    assert report["blocked"] is False and set(report["gates"].values()) == {0}
    assert report["groups"]["real"]["recall_at_5"] == 1.0
    assert report["groups"]["no_memory"]["recall_at_5"] == 0.0
    assert report["recall_gain_over_no_memory"] == 1.0
    assert set(report["unavailable_groups"]) == {"ideal", "ablation"}
    assert report["candidates"] == ["D1", "G1", "I1", "N1", "R1"]


@pytest.mark.parametrize("case_id, change, gate", [
    ("I1", {"returned": [{"run": "peer-run", "owner": "peer"}]}, "cross_access"),
    ("N1", {"proposals_admitted": 1}, "injection_write"),
    ("R1", {"unconfirmed_constraints_sent": 1}, "unconfirmed_write"),
    ("D1", {"returned": [{"run": "hidden-run", "owner": "owner"}]}, "deletion_residue"),
    ("G1", {"returned": [], "index_pending": 3}, "fake_zero"),
])
def test_any_single_violation_blocks_release(case_id, change, gate):
    rows = clean()
    for row in rows:
        if row["group"] == "real" and row["case_id"] == case_id:
            row.update(change)
    report = score(CASES, rows)
    assert report["blocked"] is True and report["gates"][gate] >= 1
    assert {"group": "real", "case_id": case_id, "gate": gate} in report["violations"]


def test_no_memory_group_must_read_and_write_nothing():
    rows = clean()
    rows[-1]["memory_reads"] = 1
    report = score(CASES, rows)
    assert report["gates"]["memory_off_access"] == 1 and report["blocked"]


def test_reported_degradation_is_not_a_fake_zero_and_unknown_groups_are_refused():
    rows = clean()
    rows[4].update(returned=[], semantic="unavailable", degradation_reported=True)
    assert score(CASES, rows)["gates"]["fake_zero"] == 0
    with pytest.raises(ValueError):
        score(CASES, [{"group": "ideal", "case_id": "R1", "returned": []}])
    with pytest.raises(ValueError):
        score({"version": CASE_VERSION, "cases": [{"id": "X", "kind": "recall"}]}, [])
