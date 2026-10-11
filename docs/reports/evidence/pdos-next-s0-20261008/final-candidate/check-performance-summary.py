"""Pure synthetic gate checks; no database, model or actual performance sampling."""

import contextlib
import io
import json
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPOSITORY / "pdos-next/tools"))
import s0_b8_performance_summary as summary

SOURCE = summary.snapshot()
ROWS = [dict(success=True, http_status=200, elapsed_seconds=.01,
             app_sql_count=1, auth_sql_count=1) for _ in range(30)]
HTTP = []
for case in range(30):
    def call(method, path, operation=""):
        HTTP.append(dict(phase="call", test_node=f"case-{case}", request_id=len(HTTP)+1,
                         method=method, path=path, operation=operation, status=200,
                         seconds=.01, sql_count=2))
    call("GET", "/verification-launch")
    for operation in ("test.run.plan", "verification.schedule.promise", "test.run.start"):
        call("POST", "/verification-launch/inputs", operation)
        call("POST", "/commands/preview", operation)
        call("POST", "/commands", operation)
        if operation == "test.run.start":
            call("POST", "/commands", operation)
    call("GET", "/verification-launch")


def metadata():
    return dict(source_sha256=SOURCE, source_unchanged=True, test_exit=0)


BASE = {
    "short-paths.json": {**metadata(), "samples": {k:deepcopy(ROWS) for k in summary.SHORT_LIMITS}},
    "b4-launch.json": {**metadata(), "http": HTTP},
    "quality-samples.json": {"outcome":"passed", "samples":{k:deepcopy(ROWS) for k in summary.QUALITY_LIMITS}},
    "b5-quality.json": metadata(),
    "heavy-change-samples.json": {"outcome":"passed", "samples":{k:deepcopy(ROWS) for k in summary.HEAVY_LIMITS}},
    "b6-change.json": metadata(),
}
CHECKS = []


def check(label, mutate=None, expected=0):
    with tempfile.TemporaryDirectory(prefix="s0-b8-summary-") as temp:
        directory = Path(temp) / "final-candidate/performance"
        directory.mkdir(parents=True)
        baseline = Path(temp) / "baseline"
        baseline.mkdir()
        (baseline / "short-paths.json").write_text(json.dumps({"summary":{k:{} for k in summary.SHORT_LIMITS}}))
        data = deepcopy(BASE)
        if mutate:
            mutate(data)
        for name, value in data.items():
            (directory / name).write_text(json.dumps(value))
        for prefix, count in (("b4", 30), ("b5", 1), ("b6", 1)):
            (directory / (prefix + "-junit.xml")).write_text(
                f'<testsuites><testsuite tests="{count}" failures="0" errors="0" skipped="0">'
                + '<testcase name="actual"/>' * count + '</testsuite></testsuites>'
            )
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                code = summary.main(directory)
        except (RuntimeError, KeyError):
            code = "rejected"
        assert code == expected, (label, code, expected)
        CHECKS.append(dict(case=label, passed=True, result=code))


check("all_32_groups_complete")
check("publication_29_samples", lambda d:d["heavy-change-samples.json"]["samples"]["coverage_publication"].pop(), "rejected")
check("quality_failed_sample", lambda d:d["quality-samples.json"]["samples"]["quality_read"][0].update(success=False), "rejected")
check("quality_pytest_failed", lambda d:d["b5-quality.json"].update(test_exit=1), "rejected")
check("heavy_pytest_failed", lambda d:d["b6-change.json"].update(test_exit=1), "rejected")
check("source_changed", lambda d:d["b4-launch.json"].update(source_unchanged=False), "rejected")
check("source_drift", lambda d:d["b5-quality.json"].update(source_sha256={}), "rejected")
check("nan_timing", lambda d:d["short-paths.json"]["samples"]["draft_save"][0].update(elapsed_seconds=float("nan")), "rejected")
check("negative_timing", lambda d:d["quality-samples.json"]["samples"]["quality_read"][0].update(elapsed_seconds=-1), "rejected")
check("negative_app_sql", lambda d:d["heavy-change-samples.json"]["samples"]["change_capture"][0].update(app_sql_count=-1,auth_sql_count=2), "rejected")
check("boolean_sql", lambda d:d["short-paths.json"]["samples"]["draft_save"][0].update(app_sql_count=True), "rejected")
check("b4_failed_http", lambda d:d["b4-launch.json"]["http"][0].update(status=403), "rejected")
check("missing_quality_inputs", lambda d:d["quality-samples.json"]["samples"].pop("capa_candidate_inputs"), "rejected")
check("empty_sample_group", lambda d:d["short-paths.json"]["samples"].update(workspace_read=[]), "rejected")
check("threshold_exceeded", lambda d:d["short-paths.json"]["samples"].update(workspace_read=[{**r,"elapsed_seconds":2.0} for r in ROWS]), 1)
assert len([p for p in SOURCE if "/skill_packages/" in p and p.endswith(".md")]) == 12
assert "pdos-next/server/pdos_next/security_runtime/parser-image.json" in SOURCE
CHECKS.append(dict(case="skill_and_parser_runtime_configuration_frozen", passed=True))
for label, xml, count in (
    ("missing_junit_cases", '<testsuites><testsuite tests="1"/></testsuites>', 1),
    ("failed_junit_case", '<testsuites><testsuite tests="1"><testcase><failure/></testcase></testsuite></testsuites>', 1),
    ("skipped_junit_case", '<testsuites><testsuite tests="1"><testcase><skipped/></testcase></testsuite></testsuites>', 1),
    ("incomplete_b4_junit", '<testsuites><testsuite tests="1"><testcase/></testsuite></testsuites>', 30),
):
    with tempfile.TemporaryDirectory(prefix="s0-b8-junit-") as temp:
        path = Path(temp) / "sample.xml"
        path.write_text(xml)
        try:
            summary.require_junit(path, count)
        except RuntimeError:
            CHECKS.append(dict(case=label, passed=True, result="rejected"))
        else:
            raise AssertionError(label)
destination = Path(__file__).with_name("performance-summary-guards-final.json")
with destination.open("x") as stream:
    json.dump(dict(synthetic_tool_checks_only=True, actual_performance_run=False, checks=CHECKS), stream, indent=2)
    stream.write("\n")
print(len(CHECKS), "summary guards passed; no database or actual timing")
