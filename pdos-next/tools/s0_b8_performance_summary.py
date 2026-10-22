"""Summarize complete successful B8 samples without hiding failures or setup IO."""

import json
import math
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree

from s0_performance import LOAD_FIELDS, LOAD_POLICY, SAMPLES, eligible_rows
from s0_source_manifest import snapshot

SHORT_LIMITS = {
    "draft_save": 1,
    "draft_create": 1,
    "t1_preview": 2,
    "t1_confirmation": 2,
    "same_key_replay": 1,
    "workspace_read": 1,
    "readiness_read": 1,
    "configuration_read_21_sources": 1,
}
HEAVY_LIMITS = {
    "manufacturing_resource_read": 1,
    "change_capture": 3,
    "change_impact_inputs": 1,
    "change_impact": 3,
    "change_impact_replay": 1,
    "coverage_publication": 3,
}
QUALITY_LIMITS = {
    "quality_read": 1,
    "quality_containment_inputs": 1,
    "quality_containment_preview": 2,
    "quality_containment_confirmation": 2,
    "capa_candidate_read": 1,
    "capa_candidate_inputs": 1,
}


def load(path):
    return json.loads(path.read_text())


def percentile(values, fraction):
    return sorted(values)[math.ceil(len(values) * fraction) - 1]


def combined_sql(row):
    counts = [row["app_sql_count"], row["auth_sql_count"]]
    if any(type(value) is not int or value < 0 for value in counts):
        raise RuntimeError("Application and auth SQL counts must be nonnegative integers")
    return sum(counts)


def summarize(rows, limit, *, allow_legacy=True):
    selected = eligible_rows(rows, allow_legacy=allow_legacy)
    legacy = bool(rows) and not any(key in rows[0] for key in LOAD_FIELDS)
    if len(selected) < SAMPLES or (legacy and len(rows) != SAMPLES):
        raise RuntimeError("Each required path needs thirty eligible successful samples")
    # Preserve collection order: surplus eligible rows cannot select a faster percentile.
    used = selected[:SAMPLES]
    values = [row["elapsed_seconds"] for row in used]
    sql = [row["sql_count"] for row in used]
    if any(
        type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in values
    ) or any(type(value) is not int or value < 0 for value in sql):
        raise RuntimeError("Samples require finite nonnegative timings and nonnegative SQL counts")
    p95 = percentile(values, 0.95)
    return {
        "samples": SAMPLES,
        "observed_samples": len(rows),
        "eligible_samples_observed": len(selected),
        "excluded_samples": len(rows) - len(selected),
        "unused_valid_samples": len(selected) - SAMPLES,
        "legacy_scope": legacy,
        "load_validated": not legacy,
        "failures": 0,
        "p50_seconds": percentile(values, 0.5),
        "p95_seconds": p95,
        "sql_range": [min(sql), max(sql)],
        "limit_seconds": limit,
        "passed": p95 <= limit,
    }


def b4_case_groups(calls):
    selected = defaultdict(list)
    for call in sorted(calls, key=lambda value: value["request_id"]):
        path, operation = call["path"], call["operation"]
        if call["method"] == "GET" and path.endswith("/verification-launch"):
            selected["launch_read"].append(call)
        elif call["method"] == "POST" and path.endswith("/verification-launch/inputs"):
            selected[operation + "_inputs"].append(call)
        elif operation in {"test.run.plan", "verification.schedule.promise", "test.run.start"}:
            if path.endswith("/commands/preview"):
                selected[operation + "_preview"].append(call)
            elif path.endswith("/commands"):
                selected[operation + "_commit"].append(call)
    required = {"launch_read": 2, "test.run.start_commit": 2}
    for operation in ("test.run.plan", "verification.schedule.promise", "test.run.start"):
        required[operation + "_inputs"] = 1
        required[operation + "_preview"] = 1
        required.setdefault(operation + "_commit", 1)
    if set(selected) != set(required) or any(
        len(selected[label]) != count for label, count in required.items()
    ):
        raise RuntimeError("B4 call grouping is incomplete or mixes initial commit with replay")
    grouped = defaultdict(list)
    for label, rows in selected.items():
        for index, row in enumerate(rows):
            name = (
                ("launch_read_before" if index == 0 else "launch_read_running")
                if label == "launch_read"
                else "test.run.start_replay"
                if label == "test.run.start_commit" and index == 1
                else label
            )
            grouped[name].append(
                {
                    **row,
                    "success": row["status"] == 200,
                    "elapsed_seconds": row["seconds"],
                    # SQL is attached by the profiler after teardown; the live B4 counter
                    # consults only the recorded load fields and HTTP business success.
                    "sql_count": row.get("sql_count"),
                }
            )
    return grouped


def b4_groups(report):
    if report["test_exit"] != 0 or report.get("source_unchanged") is not True:
        raise RuntimeError("B4 business verification failed; timings are diagnostic only")
    nodes = defaultdict(list)
    for call in report["http"]:
        if call.get("phase") == "call":
            nodes[call["test_node"]].append(call)
    if len(nodes) < SAMPLES:
        raise RuntimeError("B4 requires at least thirty real completed business cases")
    grouped = defaultdict(list)
    for calls in nodes.values():
        if any(call.get("status") != 200 for call in calls):
            raise RuntimeError("A failed B4 business call cannot be excluded by system load")
        for label, rows in b4_case_groups(calls).items():
            grouped[label].extend(rows)
    return grouped


def require_b4_junit(path, report):
    root = ElementTree.parse(path).getroot()
    cases = list(root.iter("testcase"))
    suites = list(root.iter("testsuite"))
    if sum(int(suite.get("tests", "0")) for suite in suites) != len(cases):
        raise RuntimeError("B4 JUnit test totals disagree with actual cases")
    # Other XML children (e.g. captured stdout) are not failed business phases.
    completed = sum(
        not any(child.tag in {"error", "failure", "skipped"} for child in case) for case in cases
    )
    actual = len({row["test_node"] for row in report["http"] if row.get("phase") == "call"})
    for case in cases:
        for child in case:
            if child.tag in {"error", "failure"} or (
                child.tag == "skipped"
                and "Performance replacement slots unused" not in child.get("message", "")
            ):
                raise RuntimeError("B4 has failed or pending business cases")
    if completed != actual or actual < SAMPLES:
        raise RuntimeError("B4 JUnit must match its actual completed business cases")


def require_junit(path, count):
    root = ElementTree.parse(path).getroot()
    suites = list(root.iter("testsuite"))
    cases = list(root.iter("testcase"))
    if (
        len(cases) != count
        or sum(int(suite.get("tests", "0")) for suite in suites) != count
        or any(
            int(suite.get(key, "0"))
            for suite in suites
            for key in ("errors", "failures", "skipped")
        )
        or any(child.tag in ("error", "failure", "skipped") for case in cases for child in case)
    ):
        raise RuntimeError("Required business cases must all complete successfully")


def measured_business_groups(directory, prefix, filename, limits, source):
    samples = load(directory / filename)
    run = load(directory / (prefix + ".json"))
    require_junit(directory / (prefix.split("-", 1)[0] + "-junit.xml"), 1)
    if (
        run["test_exit"] != 0
        or run.get("source_unchanged") is not True
        or run.get("source_sha256") != source
        or samples["outcome"] != "passed"
        or samples.get("sampling_mode", "full") != "full"
        or samples.get("all_observations_successful", True) is not True
        or ("source_sha256" in samples and samples["source_sha256"] != source)
        or samples.get("source_unchanged", True) is not True
        or set(samples["samples"]) != set(limits)
    ):
        raise RuntimeError(f"{prefix} business verification or sample completeness failed")
    return {
        label: summarize(
            [{**row, "sql_count": combined_sql(row)} for row in samples["samples"][label]],
            limit,
        )
        for label, limit in limits.items()
    }


def main(directory):
    directory = directory.resolve()
    output = directory / "performance-summary.json"
    if output.exists():
        raise RuntimeError("Preserve completed performance evidence")
    short = load(directory / "short-paths.json")
    if (
        short.get("source_unchanged") is not True
        or short.get("source_sha256") != snapshot()
        or short.get("outcome", "passed") != "passed"
    ):
        raise RuntimeError("Short-path source changed during sampling")
    if set(short["samples"]) != set(SHORT_LIMITS):
        raise RuntimeError("Required short-path sample groups are missing")
    summary = {}
    for label, limit in SHORT_LIMITS.items():
        rows = [
            {
                **row,
                "success": row["http_status"] == 200,
                "sql_count": combined_sql(row),
            }
            for row in short["samples"][label]
        ]
        summary[label] = summarize(rows, limit)
    b4_run = load(directory / "b4-launch.json")
    require_b4_junit(directory / "b4-junit.xml", b4_run)
    if b4_run.get("source_sha256") != short.get("source_sha256"):
        raise RuntimeError("B4 and short paths must measure the same frozen source")
    for label, rows in b4_groups(b4_run).items():
        limit = (
            1
            if label.startswith("launch_read") or label.endswith(("_inputs", "_replay"))
            else 3
            if label == "test.run.start_commit"
            else 2
        )
        summary[label] = summarize(rows, limit)
    for prefix, filename, limits in (
        ("b5-quality", "quality-samples.json", QUALITY_LIMITS),
        ("b6-change", "heavy-change-samples.json", HEAVY_LIMITS),
    ):
        summary.update(
            measured_business_groups(directory, prefix, filename, limits, short["source_sha256"])
        )
    baseline = load(directory.parent.parent / "baseline/short-paths.json")
    report = {
        "synthetic_only": True,
        "llm_calls": 0,
        "setup_excluded": True,
        "sampling_mode": "full",
        "load_policy": LOAD_POLICY,
        "legacy_scope": any(value["legacy_scope"] for value in summary.values()),
        "load_validated": all(value["load_validated"] for value in summary.values()),
        "all_required_groups_complete": True,
        "all_thresholds_passed": all(value["passed"] for value in summary.values()),
        "summary": summary,
        "comparable_b0": {
            label: {"before": value, "after": summary[label]}
            for label, value in baseline["summary"].items()
        },
        "historical_heavy_baseline": {
            "successful_single_start_seconds": 42.29,
            "single_impact_seconds": 197.79,
            "failed_publication_seconds": 1061,
            "failed_publication_engine_aggregate_sql": 585493,
            "is_p95": False,
            "sql_scope_comparable": False,
            "failed_publication_is_success_baseline": False,
        },
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if report["all_thresholds_passed"] and report["load_validated"] else 1


def containment_only(directory):
    directory = directory.resolve()
    output = directory / "containment-performance-summary.json"
    if output.exists():
        raise RuntimeError("Preserve completed containment iteration evidence")
    samples = load(directory / "quality-samples.json")
    run = load(directory / "b5-quality.json")
    label = "quality_containment_confirmation"
    source = snapshot()
    require_junit(directory / "b5-junit.xml", 1)
    if (
        run["test_exit"] != 0
        or run.get("source_unchanged") is not True
        or run.get("source_sha256") != source
        or samples.get("source_sha256") != source
        or samples.get("source_unchanged") is not True
        or samples.get("outcome") != "passed"
        or samples.get("sampling_mode") != "containment"
        or samples.get("all_observations_successful") is not True
        or samples.get("required_paths") != [label]
        or set(samples["samples"]) != {label}
        or set(samples.get("preparation_samples", {}))
        != set(QUALITY_LIMITS) - {label, "capa_candidate_read", "capa_candidate_inputs"}
    ):
        raise RuntimeError(
            "Containment iteration requires current real completed business evidence"
        )
    # Preparation still must succeed. Its timing has no iteration acceptance threshold.
    for rows in samples["preparation_samples"].values():
        eligible_rows(rows)
        if len(rows) != len(samples["samples"][label]):
            raise RuntimeError(
                "Each containment commit needs its real read/input/preview preparation"
            )
    result = summarize(
        [{**row, "sql_count": combined_sql(row)} for row in samples["samples"][label]],
        QUALITY_LIMITS[label],
        allow_legacy=False,
    )
    report = {
        "sampling_mode": "containment",
        "source_sha256": source,
        "load_policy": LOAD_POLICY,
        "legacy_scope": False,
        "setup_excluded": True,
        "llm_calls": 0,
        "all_iteration_groups_complete": True,
        "all_thresholds_passed": result["passed"],
        "full_s0_performance_pass": False,
        "preparation_has_iteration_threshold": False,
        "summary": {label: result},
    }
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["summary"], indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--containment-only", action="store_true")
    arguments = parser.parse_args()
    raise SystemExit(
        containment_only(arguments.directory)
        if arguments.containment_only
        else main(arguments.directory)
    )
