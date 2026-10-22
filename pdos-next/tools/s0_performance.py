"""Measure synthetic authenticated short paths against the current category-root candidate."""

import importlib.util
import json
import math
import os
import subprocess
from collections import Counter
from hashlib import sha256
from time import perf_counter
from uuid import uuid4

from current_read_profiler import CurrentReadProfiler
from local_environment import ROOT, environment, read_state, verified
from s0_source_manifest import snapshot
from sqlalchemy import event

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-s0-20261008/model-project/performance"
SAMPLES = 30
MAX_ATTEMPTS = 90
LOAD_POLICY = "start-or-end-1min-exceeds-logical-cpus-v1"
LOAD_FIELDS = (
    "load_policy",
    "logical_cpu_count",
    "load_averages",
    "excluded_from_performance",
    "exclusion_reason",
)
PROFILE_CALLS = []


class PerformancePending(RuntimeError):
    """The finite replacement budget ended before thirty eligible samples."""


def load_snapshot():
    try:
        values = os.getloadavg()
    except (AttributeError, OSError):
        values = (None, None, None)
    return dict(zip(("1min", "5min", "15min"), values, strict=True))


def start_sample_load():
    return {"logical_cpu_count": os.cpu_count(), "start": load_snapshot()}


def exclusion_reason(cores, averages):
    if type(cores) is not int or cores < 1:
        return "logical_cpu_count_unavailable"
    if type(averages) is not dict or set(averages) != {"start", "end"}:
        return "load_averages_unavailable"
    for boundary in ("start", "end"):
        values = averages[boundary]
        if type(values) is not dict or set(values) != {"1min", "5min", "15min"}:
            return "load_averages_unavailable"
        if any(
            type(value) not in (int, float) or not math.isfinite(value) or value < 0
            for value in values.values()
        ):
            return "load_averages_unavailable"
    if any(averages[boundary]["1min"] > cores for boundary in ("start", "end")):
        return "system_load_exceeds_logical_cpu_count"
    return None


def finish_sample_load(start):
    averages = {"start": start["start"], "end": load_snapshot()}
    reason = exclusion_reason(start["logical_cpu_count"], averages)
    return {
        "load_policy": LOAD_POLICY,
        "logical_cpu_count": start["logical_cpu_count"],
        "load_averages": averages,
        "excluded_from_performance": reason is not None,
        "exclusion_reason": reason,
    }


def eligible_rows(rows, *, allow_legacy=False):
    """Validate raw load records; never suppress a business failure."""
    if any(row.get("success") is not True for row in rows):
        raise RuntimeError("A business failure cannot be excluded by system load")
    present = [any(key in row for key in LOAD_FIELDS) for row in rows]
    if present and not any(present):
        if allow_legacy:
            return list(rows)
        raise RuntimeError("Legacy samples have no recorded load eligibility")
    if present and not all(present):
        raise RuntimeError("Legacy and load-recorded samples cannot be mixed")
    selected = []
    for row in rows:
        if row.get("load_policy") != LOAD_POLICY or any(key not in row for key in LOAD_FIELDS):
            raise RuntimeError("Incomplete or unknown sample load policy")
        reason = exclusion_reason(row["logical_cpu_count"], row["load_averages"])
        if (
            type(row["excluded_from_performance"]) is not bool
            or row["excluded_from_performance"] != (reason is not None)
            or row["exclusion_reason"] != reason
        ):
            raise RuntimeError("Sample load eligibility disagrees with its raw measurements")
        if reason is None:
            selected.append(row)
    return selected


def sampling_counts(rows, labels):
    counts = {}
    for label in labels:
        observed = rows.get(label, ())
        successful = [row for row in observed if row.get("success") is True]
        eligible = len(eligible_rows(successful))
        counts[label] = {
            "observed": len(observed),
            "eligible": eligible,
            "excluded": len(successful) - eligible,
            "failed": len(observed) - len(successful),
        }
    return counts


def sample_attempts(rows, labels, *, target=SAMPLES, max_attempts=MAX_ATTEMPTS):
    """Bounded real replacements, with no sleep or manufactured samples."""
    labels = tuple(labels)
    if (
        not labels
        or any(type(label) is not str or not label for label in labels)
        or len(set(labels)) != len(labels)
        or type(target) is not int
        or target < 1
        or type(max_attempts) is not int
        or max_attempts < 1
    ):
        raise ValueError("Select nonempty unique paths and a finite positive sample budget")
    for attempt in range(max_attempts):
        if all(len(eligible_rows(rows.get(label, ()))) >= target for label in labels):
            return
        yield attempt
    if any(len(eligible_rows(rows.get(label, ()))) < target for label in labels):
        raise PerformancePending("Performance sampling pending: replacement budget exhausted")


def record_profile_call(call):
    PROFILE_CALLS.append(call)


def profile_case_calls(node):
    return [row for row in PROFILE_CALLS if row["phase"] == "call" and row["test_node"] == node]


def command(work, operation, payload, *, sources=()):
    return {
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "operation": operation,
        "category_id": str(work.category),
        "product_id": str(work.product),
        "expected_revision": 1,
        "source_read_set": list(sources),
        "payload": payload,
    }


def checked(response):
    if response.status_code != 200:
        raise RuntimeError(f"Baseline request failed: HTTP {response.status_code}")
    return response.json()


def post(work, request):
    return work.client.post(
        f"/v1/categories/{work.category}/commands", headers=work.headers, json=request
    )


def measure(work, label, call):
    queries = Counter()

    def count(_conn, _cursor, statement, _params, _context, _many):
        # Inspect only table names; never export statements or parameters.
        lowered = statement.lower()
        for table in ("grants", "principals", "artifact_versions", "parts"):
            if f"from {table}" in lowered or f"join {table}" in lowered:
                queries[table] += 1

    response, error = None, None
    elapsed, load_record = None, None
    app = CurrentReadProfiler(work.engine, (), case_label=label, include_worker_threads=True)
    auth = CurrentReadProfiler(work.auth, (), case_label=label, include_worker_threads=True)
    load_start = start_sample_load()
    event.listen(work.engine, "after_cursor_execute", count)
    try:
        with app, auth:
            started = perf_counter()
            try:
                response = call()
            finally:
                elapsed = perf_counter() - started
                load_record = finish_sample_load(load_start)
            value = checked(response)
    except Exception as caught:
        error = caught
    finally:
        event.remove(work.engine, "after_cursor_execute", count)
    if elapsed is None and error is not None:
        # No actual HTTP callback started; preserve the setup/instrumentation error.
        raise error
    if load_record is None:
        load_record = finish_sample_load(load_start)
    app_report, auth_report = app.report(), auth.report()
    sample = {
        "elapsed_seconds": elapsed,
        "http_status": response.status_code if response is not None else None,
        "app_sql_count": app_report["query_count"],
        "auth_sql_count": auth_report["query_count"],
        "authorization_table_reads": {
            key: value for key, value in queries.items() if key in {"grants", "principals"}
        },
        "read_table_counts": dict(queries),
        "app_profile": app_report,
        "auth_profile": auth_report,
        **load_record,
    }
    if error is not None:
        error.performance_sample = sample
        raise error
    return value, sample


def short_measure(work, label, call, rows, validate):
    sample = {}
    try:
        value, sample = measure(work, label, call)
        validate(value)
    except Exception as error:
        rows.append(
            {
                **getattr(error, "performance_sample", sample),
                "success": False,
                "error_type": type(error).__name__,
            }
        )
        raise
    rows.append({**sample, "success": True})
    return value


def require_result(condition):
    if not condition:
        raise AssertionError("Measured short path failed its actual result guard")


def percentile(values, p):
    return sorted(values)[math.ceil(len(values) * p) - 1]


def short_summary(rows):
    selected = eligible_rows(rows)[:SAMPLES]
    if len(selected) != SAMPLES:
        raise PerformancePending("Short path has fewer than thirty eligible samples")
    return {
        "samples": SAMPLES,
        "observed_samples": len(rows),
        "eligible_samples_observed": len(eligible_rows(rows)),
        "excluded_samples": len(rows) - len(eligible_rows(rows)),
        "unused_valid_samples": len(eligible_rows(rows)) - SAMPLES,
        "failures": 0,
        "legacy_scope": False,
        "p50_seconds": percentile([row["elapsed_seconds"] for row in selected], 0.5),
        "p95_seconds": percentile([row["elapsed_seconds"] for row in selected], 0.95),
        "app_sql_range": [
            min(row["app_sql_count"] for row in selected),
            max(row["app_sql_count"] for row in selected),
        ],
        "auth_sql_range": [
            min(row["auth_sql_count"] for row in selected),
            max(row["auth_sql_count"] for row in selected),
        ],
    }


def write_short_text(output, text):
    with output.open("x") as stream:
        stream.write(text)


def run():
    output = REPORT / "short-paths.json"
    if output.exists():
        raise RuntimeError("Preserve existing baseline; do not overwrite")
    initial_sources = snapshot()
    state = verified(read_state())
    os.environ.update(environment(state))
    spec = importlib.util.spec_from_file_location(
        "s0_baseline_fixtures", ROOT / "server/tests/conftest.py"
    )
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    engine_fixture = fixtures.engines.__wrapped__()
    engines = next(engine_fixture)
    fixture = fixtures.setup.__wrapped__(engines)
    setup_started = perf_counter()
    work = next(fixture)
    setup_elapsed = perf_counter() - setup_started
    samples = {}
    try:
        artifact_request = command(
            work,
            "evidence.artifact.register",
            {
                "title": "S0 baseline synthetic input",
                "source_label": "Synthetic only",
                "content": "Pressure: 150 PSI\nTest condition unknown\n",
                "visibility": "private",
            },
        )
        source = checked(post(work, artifact_request))["subject_id"]
        replay_request = command(work, "evidence.artifact.register", artifact_request["payload"])
        original_receipt = checked(post(work, replay_request))["id"]
        for label in (
            "draft_save",
            "draft_create",
            "t1_preview",
            "t1_confirmation",
            "same_key_replay",
            "workspace_read",
            "readiness_read",
        ):
            samples[label] = []
            for sample_index in sample_attempts(samples, (label,)):
                if label == "draft_save":
                    request = command(
                        work, "evidence.artifact.register", artifact_request["payload"]
                    )

                    def call(request=request):
                        return post(work, request)
                elif label == "draft_create":
                    request = command(
                        work,
                        "evidence.artifact.register",
                        {
                            **artifact_request["payload"],
                            "title": f"New synthetic draft {sample_index}",
                        },
                    )

                    def call(request=request):
                        return post(work, request)
                elif label in {"t1_preview", "t1_confirmation"}:
                    request = command(
                        work,
                        "evidence.claim.record",
                        {
                            "artifact_id": source,
                            "line": 1,
                            "quote": "Pressure: 150 PSI",
                            "statement": (
                                f"Synthetic pressure; condition unknown: {label}:{sample_index}"
                            ),
                            "visibility": "private",
                        },
                        sources=({"artifact_id": source, "expected_revision": 1},),
                    )
                    receipt = checked(post(work, request))
                    preview_url = (
                        f"/v1/categories/{work.category}/products/{work.product}"
                        f"/receipts/{receipt['id']}/revert-preview"
                    )
                    if label == "t1_preview":

                        def call(url=preview_url):
                            return work.client.post(url, headers=work.headers)
                    else:
                        preview = checked(work.client.post(preview_url, headers=work.headers))
                        request = command(
                            work,
                            "ai.run.revert",
                            {
                                "receipt_id": receipt["id"],
                                "confirmation_token": preview["confirmation_token"],
                            },
                        )

                        def call(request=request):
                            return post(work, request)
                elif label == "same_key_replay":

                    def call():
                        return post(work, replay_request)
                else:
                    suffix = "workspace" if label == "workspace_read" else "build-start"

                    def call(suffix=suffix):
                        return work.client.get(
                            f"/v1/categories/{work.category}/products/{work.product}/{suffix}",
                            headers=work.headers,
                        )

                short_measure(
                    work,
                    label,
                    call,
                    samples[label],
                    lambda value, label=label: require_result(
                        label != "same_key_replay" or value["id"] == original_receipt
                    ),
                )
        config_spec = importlib.util.spec_from_file_location(
            "s0_configuration_fixtures", ROOT / "server/tests/test_configurations.py"
        )
        config = importlib.util.module_from_spec(config_spec)
        config_spec.loader.exec_module(config)
        chain = config.configuration_chain(work)
        refs, reads = [], []
        for index in range(20):
            identity = checked(
                post(
                    work,
                    command(
                        work,
                        "evidence.artifact.register",
                        {
                            "title": f"Independent configuration source {index}",
                            "content": config.TEXT,
                            "source_label": "Synthetic performance fixture",
                            "visibility": "private",
                        },
                    ),
                )
            )["subject_id"]
            refs.append(
                {
                    "artifact_id": identity,
                    "expected_revision": 1,
                    "line": 1,
                    "quote": config.TEXT,
                }
            )
            reads.append({"artifact_id": identity, "expected_revision": 1})
        payload = config.revision_payload(config.listed(work)["boms"][0], chain["reference"])
        payload["sources"] = refs
        _, _, review = config.accepted(
            work, config.command(work, "engineering.bom.revise", payload, [*reads, *chain["reads"]])
        )
        assert len(review["after"]["required_source_read_set"]) == 21
        samples["configuration_read_21_sources"] = []
        for _ in sample_attempts(samples, ("configuration_read_21_sources",)):

            def call():
                return work.client.get(
                    f"/v1/categories/{work.category}/products/{work.product}/configurations",
                    headers=work.headers,
                )

            short_measure(
                work,
                "configuration_read_21_sources",
                call,
                samples["configuration_read_21_sources"],
                lambda value: require_result(
                    len(value["boms"][0]["required_source_read_set"]) == 21
                ),
            )
        report = {
            "candidate_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "business_source_sha256": {
                str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest()
                for p in sorted((ROOT / "server/pdos_next").rglob("*.py"))
            },
            "source_sha256": initial_sources,
            "source_unchanged": snapshot() == initial_sources,
            "database": {"name": "pdos_test", "port": state["port"], "marker": state["marker"]},
            "scope": {
                "synthetic_only": True,
                "single_request": True,
                "llm_calls": 0,
                "authenticated_asgi_testclient": True,
                "network_latency_included": False,
                "setup_excluded_from_request_time": True,
                "draft_save_semantics": (
                    "Equivalent new-key intent alias; comparable to B0/B2 label"
                ),
                "draft_create_semantics": "Unique title for each new persisted draft",
                "claims": len(samples["t1_preview"]) + len(samples["t1_confirmation"]),
                "configuration_fixture": "2 BOM revisions, engineering, process; 21 direct sources",
                "sql_successful_statements_only": True,
                "all_same_engine_worker_threads_counted": True,
                "readiness_fixture": "empty build collection; no actual launch measured",
                "credential_or_source_text_emitted": False,
            },
            "fixture_setup_seconds": setup_elapsed,
            "outcome": "passed",
            "load_policy": LOAD_POLICY,
            "expected_samples_per_path": SAMPLES,
            "max_attempts_per_phase": MAX_ATTEMPTS,
            "sampling_counts": sampling_counts(samples, samples),
            "summary": {label: short_summary(rows) for label, rows in samples.items()},
            "samples": samples,
        }
        REPORT.mkdir(parents=True, exist_ok=True)
        output = REPORT / "short-paths.json"
        if output.exists():
            raise RuntimeError("Preserve existing baseline; do not overwrite")
        with output.open("x") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    except PerformancePending:
        REPORT.mkdir(parents=True, exist_ok=True)
        write_short_text(
            output,
            json.dumps(
                {
                    "outcome": "pending",
                    "pending_reason": "replacement_budget_exhausted",
                    "source_sha256": initial_sources,
                    "source_unchanged": snapshot() == initial_sources,
                    "load_policy": LOAD_POLICY,
                    "expected_samples_per_path": SAMPLES,
                    "max_attempts_per_phase": MAX_ATTEMPTS,
                    "sampling_counts": sampling_counts(samples, samples),
                    "samples": samples,
                    "summary": {},
                },
                indent=2,
            )
            + "\n",
        )
        raise
    except Exception as error:
        if output.exists():
            raise
        REPORT.mkdir(parents=True, exist_ok=True)
        write_short_text(
            output,
            json.dumps(
                {
                    "outcome": "failed",
                    "error_type": type(error).__name__,
                    "source_sha256": initial_sources,
                    "source_unchanged": snapshot() == initial_sources,
                    "load_policy": LOAD_POLICY,
                    "samples": samples,
                    "summary": {},
                },
                indent=2,
            )
            + "\n",
        )
        raise
    finally:
        fixture.close()
        engine_fixture.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--b8", action="store_true", help="Use only the verified B8 fixture")
    arguments = parser.parse_args()
    if arguments.b8:
        import s0_b8_environment as checkpoint

        checkpoint.state()
        REPORT = checkpoint.REPORT / "performance"
    run()
