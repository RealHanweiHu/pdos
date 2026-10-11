"""Measure synthetic authenticated short paths without changing business behavior."""

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
from sqlalchemy import event

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-s0-20261008/baseline"


def command(work, operation, payload, *, sources=()):
    return {
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "operation": operation,
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
    return work.client.post("/v1/commands", headers=work.headers, json=request)


def measure(work, label, call):
    queries = Counter()

    def count(_conn, _cursor, statement, _params, _context, _many):
        # Inspect only table names; never export statements or parameters.
        lowered = statement.lower()
        for table in ("grants", "principals"):
            if f"from {table}" in lowered or f"join {table}" in lowered:
                queries[table] += 1

    event.listen(work.engine, "after_cursor_execute", count)
    try:
        with (
            CurrentReadProfiler(
                work.engine, (), case_label=label, include_worker_threads=True
            ) as app,
            CurrentReadProfiler(
                work.auth, (), case_label=label, include_worker_threads=True
            ) as auth,
        ):
            started = perf_counter()
            response = call()
            elapsed = perf_counter() - started
            value = checked(response)
    finally:
        event.remove(work.engine, "after_cursor_execute", count)
    app_report, auth_report = app.report(), auth.report()
    return value, {
        "elapsed_seconds": elapsed,
        "http_status": response.status_code,
        "app_sql_count": app_report["query_count"],
        "auth_sql_count": auth_report["query_count"],
        "authorization_table_reads": dict(queries),
        "app_profile": app_report,
        "auth_profile": auth_report,
    }


def percentile(values, p):
    return sorted(values)[math.ceil(len(values) * p) - 1]


def run():
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
            "t1_preview",
            "t1_confirmation",
            "same_key_replay",
            "workspace_read",
            "readiness_read",
        ):
            samples[label] = []
            for sample_index in range(30):
                if label == "draft_save":
                    request = command(
                        work, "evidence.artifact.register", artifact_request["payload"]
                    )
                    call = lambda request=request: post(work, request)
                elif label in {"t1_preview", "t1_confirmation"}:
                    request = command(
                        work,
                        "evidence.claim.record",
                        {
                            "artifact_id": source,
                            "line": 1,
                            "quote": "Pressure: 150 PSI",
                            "statement": f"Synthetic pressure; condition unknown: {label}:{sample_index}",
                            "visibility": "private",
                        },
                        sources=({"artifact_id": source, "expected_revision": 1},),
                    )
                    receipt = checked(post(work, request))
                    preview_url = (
                        f"/v1/products/{work.product}/receipts/{receipt['id']}/revert-preview"
                    )
                    if label == "t1_preview":
                        call = lambda url=preview_url: work.client.post(url, headers=work.headers)
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
                        call = lambda request=request: post(work, request)
                elif label == "same_key_replay":
                    call = lambda: post(work, replay_request)
                else:
                    suffix = "workspace" if label == "workspace_read" else "build-start"
                    call = lambda suffix=suffix: work.client.get(
                        f"/v1/products/{work.product}/{suffix}", headers=work.headers
                    )
                value, sample = measure(work, label, call)
                if label == "same_key_replay" and value["id"] != original_receipt:
                    raise RuntimeError("Replay did not return original receipt")
                samples[label].append(sample)
        report = {
            "candidate_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "business_source_sha256": {
                str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest()
                for p in sorted((ROOT / "server/pdos_next").rglob("*.py"))
            },
            "database": {"name": "pdos_test", "port": state["port"], "marker": state["marker"]},
            "scope": {
                "synthetic_only": True,
                "single_request": True,
                "llm_calls": 0,
                "authenticated_asgi_testclient": True,
                "network_latency_included": False,
                "setup_excluded_from_request_time": True,
                "source_count": 32,
                "claims": 60,
                "sql_successful_statements_only": True,
                "all_same_engine_worker_threads_counted": True,
                "readiness_fixture": "empty build collection; no actual launch measured",
                "credential_or_source_text_emitted": False,
            },
            "fixture_setup_seconds": setup_elapsed,
            "summary": {
                label: {
                    "samples": len(rows),
                    "failures": 0,
                    "p50_seconds": percentile([row["elapsed_seconds"] for row in rows], 0.5),
                    "p95_seconds": percentile([row["elapsed_seconds"] for row in rows], 0.95),
                    "app_sql_range": [
                        min(row["app_sql_count"] for row in rows),
                        max(row["app_sql_count"] for row in rows),
                    ],
                    "auth_sql_range": [
                        min(row["auth_sql_count"] for row in rows),
                        max(row["auth_sql_count"] for row in rows),
                    ],
                }
                for label, rows in samples.items()
            },
            "samples": samples,
        }
        REPORT.mkdir(parents=True, exist_ok=True)
        output = REPORT / "short-paths.json"
        if output.exists():
            raise RuntimeError("Preserve existing baseline; do not overwrite")
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    finally:
        fixture.close()
        engine_fixture.close()


if __name__ == "__main__":
    run()
