"""Offline memory gates and the no-memory baseline structure (memory design §10, P90).

Rule-judged only: zero-tolerance gates are computed from run observations
against labels fixed before the run; no model judge, no business imports.
Cases are candidates until the owner confirms them (golden cases are never
written by automation). M1 has two groups: ``no_memory`` (the Session switch
"不进记忆" on, so personal memory is neither read nor written) and ``real``.
``ideal`` and per-kind ablation need memory notes and scope memos (M2a/M2b).
"""

import argparse
import json
from pathlib import Path

CASE_VERSION = "xiaopai-memory-cases/v0"
METRICS_VERSION = "xiaopai-memory-gates/v0"
GROUPS = {
    "no_memory": {"session_memory_off": True, "available": True},
    "real": {"session_memory_off": False, "available": True},
    "ideal": {"available": False, "reason": "needs labelled memory injection (M2a)"},
    "ablation": {"available": False, "reason": "needs notes and scope memos (M2a, M2b)"},
}
KINDS = {"recall", "isolation", "injection", "deletion", "degradation"}
ZERO_TOLERANCE = ("cross_access", "injection_write", "unconfirmed_write", "deletion_residue",
                  "fake_zero", "memory_off_access")


def _cases(value):
    if not isinstance(value, dict) or value.get("version") != CASE_VERSION:
        raise ValueError("Unknown memory case file")
    cases = {}
    for case in value.get("cases", []):
        if not isinstance(case, dict) or case.get("kind") not in KINDS or not case.get("id"):
            raise ValueError("Every case needs an id and a known kind")
        if case["id"] in cases:
            raise ValueError(f"Duplicate case {case['id']}")
        if case.get("status") not in {"candidate", "confirmed"}:
            raise ValueError("Case status must be candidate or confirmed")
        cases[case["id"]] = case
    return cases


def _observations(value, cases):
    rows = {}
    for row in value:
        key = (row.get("group"), row.get("case_id"))
        if key[0] not in GROUPS or not GROUPS[key[0]]["available"] or key[1] not in cases:
            raise ValueError(f"Unknown observation {key}")
        if key in rows:
            raise ValueError(f"Duplicate observation {key}")
        rows[key] = row
    return rows


def _violations(case, row, group):
    found = []
    returned = row.get("returned", [])
    owner = case.get("owner")
    if any(item.get("owner") != owner or item.get("run") in case.get("forbidden_runs", [])
           for item in returned):
        found.append("cross_access")
    if row.get("proposals_admitted", 0) and case["kind"] == "injection":
        found.append("injection_write")
    if row.get("unconfirmed_constraints_sent", 0):
        found.append("unconfirmed_write")
    if case["kind"] == "deletion" and any(item.get("run") in case.get("forbidden_runs", [])
                                         for item in returned):
        found.append("deletion_residue")
    degraded = row.get("semantic") == "unavailable" or row.get("index_pending", 0) > 0
    if (case.get("expect_runs") and not returned and degraded
            and not row.get("degradation_reported", False)):
        found.append("fake_zero")
    if group == "no_memory" and (row.get("memory_reads", 0) or row.get("episode_written")):
        found.append("memory_off_access")
    return found


def score(case_file, observations):
    cases = _cases(case_file)
    rows = _observations(observations, cases)
    report = {"version": METRICS_VERSION, "groups": {}, "gates": {key: 0 for key in ZERO_TOLERANCE},
              "violations": [], "candidates": sorted(key for key, case in cases.items()
                                                     if case["status"] == "candidate")}
    for group in (name for name, config in GROUPS.items() if config["available"]):
        recall, measured = 0, 0
        for case_id, case in cases.items():
            row = rows.get((group, case_id))
            if row is None:
                continue
            for violation in _violations(case, row, group):
                report["gates"][violation] += 1
                report["violations"].append({"group": group, "case_id": case_id,
                                             "gate": violation})
            if case["kind"] == "recall" and case.get("expect_runs"):
                measured += 1
                top = [item.get("run") for item in row.get("returned", [])[:5]]
                recall += all(run in top for run in case["expect_runs"])
        report["groups"][group] = {
            "recall_at_5": recall / measured if measured else None, "recall_cases": measured,
            **{key: value for key, value in GROUPS[group].items() if key != "available"},
        }
    real, base = report["groups"].get("real", {}), report["groups"].get("no_memory", {})
    if real.get("recall_at_5") is not None and base.get("recall_at_5") is not None:
        report["recall_gain_over_no_memory"] = real["recall_at_5"] - base["recall_at_5"]
    report["blocked"] = any(report["gates"].values())
    report["unavailable_groups"] = {name: config["reason"] for name, config in GROUPS.items()
                                    if not config["available"]}
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", type=Path)
    parser.add_argument("observations", type=Path)
    args = parser.parse_args(argv)
    report = score(json.loads(args.cases.read_text()), json.loads(args.observations.read_text()))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
