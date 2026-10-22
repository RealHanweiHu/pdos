"""Thirty fresh fixed captures, actual impact commits and host coverage publications.

Setup and the additional publication-basis capture are excluded from timings.
No mock replaces source IO, authority, registry, transaction or commit.
"""

# ruff: noqa: F401,F811 -- explicit imports register the existing fixture tree
import json
import os
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from time import perf_counter
from uuid import UUID, uuid4

import pytest
from change_coverage_transactions.test_publication import (
    accepted_work,
    change_work,
    engines,
    known_configuration,
    launch_work,
    operational_work,
    publish,
    quality_work,
    ready_work,
    registered_original,
    results_work,
)
from change_execution.test_transactions import command, create_payload, created
from conftest import setup
from current_read_profiler import CurrentReadProfiler
from pdos_next.change_order_service import current_fixed
from pdos_next.change_order_service import snapshot as change_snapshot
from pdos_next.database import tenant_session
from pdos_next.domain.change_control.rules import digest
from pdos_next.domain.change_coverage_owner import owner, schemas, trust
from pdos_next.schemas.change_control.contracts import GraphSnapshot
from s0_performance import (
    LOAD_POLICY,
    MAX_ATTEMPTS,
    PerformancePending,
    finish_sample_load,
    measure,
    sample_attempts,
    sampling_counts,
    start_sample_load,
)
from test_project_first_plan import cmd, post

ROWS = defaultdict(list)
LABELS = (
    "manufacturing_resource_read",
    "change_capture",
    "change_impact_inputs",
    "change_impact",
    "change_impact_replay",
    "coverage_publication",
)
OUTCOME = "pending"
PENDING_REASON = None


def save():
    directory = Path(os.environ["S0_PERFORMANCE_DIRECTORY"]).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "heavy-change-samples.json").write_text(
        json.dumps(
            {
                "expected_samples_per_path": 30,
                "synthetic_only": True,
                "llm_calls": 0,
                "setup_excluded": True,
                "outcome": OUTCOME,
                "required_paths": LABELS,
                "load_policy": LOAD_POLICY,
                "max_attempts_per_phase": MAX_ATTEMPTS,
                "pending_reason": PENDING_REASON,
                "sampling_counts": sampling_counts(ROWS, LABELS),
                "fixture_scope": (
                    "one tenant; distinct first-submit impact and publication subjects"
                ),
                "coverage_publication_transport": (
                    "trusted host domain command with actual transaction commit"
                ),
                "samples": dict(ROWS),
            },
            indent=2,
        )
        + "\n"
    )


def http_measure(work, label, callback, validate):
    sample = {}
    try:
        value, sample = measure(work.setup, label, callback)
        validate(value)
    except Exception as error:
        ROWS[label].append(
            {
                **getattr(error, "performance_sample", sample),
                "success": False,
                "error_type": type(error).__name__,
            }
        )
        save()
        raise
    ROWS[label].append({**sample, "success": True})
    save()
    return value


def publication_measure(work, callback, validate):
    label = "coverage_publication"
    load_start = start_sample_load()
    profile = CurrentReadProfiler(work.setup.engine, (), case_label=label)
    sample = {}
    elapsed, load_record = None, None
    try:
        with profile:
            started = perf_counter()
            try:
                value = callback()
            finally:
                elapsed = perf_counter() - started
                load_record = finish_sample_load(load_start)
        sample = {
            "elapsed_seconds": elapsed,
            "app_sql_count": profile.report()["query_count"],
            "auth_sql_count": 0,
            "app_profile": profile.report(),
            **load_record,
        }
        validate(value)
    except Exception as error:
        if load_record is None:
            load_record = finish_sample_load(load_start)
        ROWS[label].append(
            {
                **sample,
                "elapsed_seconds": elapsed,
                "app_sql_count": profile.report()["query_count"],
                "auth_sql_count": 0,
                "app_profile": profile.report(),
                **load_record,
                "success": False,
                "error_type": type(error).__name__,
            }
        )
        save()
        raise
    ROWS[label].append({**sample, "success": True})
    save()
    return value


def test_actual_capture_impact_and_coverage_publication(change_work):
    global OUTCOME, PENDING_REASON
    directory = Path(os.environ["S0_PERFORMANCE_DIRECTORY"]).resolve()
    if (directory / "heavy-change-samples.json").exists():
        raise RuntimeError("Preserve completed change performance evidence")
    ROWS.clear()
    OUTCOME, PENDING_REASON = "pending", None
    save()
    work = change_work
    identities = set()
    try:
        resource_path = (
            f"/v1/categories/{work.setup.category}/products/{work.setup.product}"
            f"/builds/{work.build_id}/resources/inspect"
        )
        for _ in sample_attempts(ROWS, ("manufacturing_resource_read",)):
            http_measure(
                work,
                "manufacturing_resource_read",
                lambda: work.setup.client.post(
                    resource_path,
                    headers=work.setup.headers,
                    json={
                        "project_id": work.config["project"],
                        "expected_build_revision": 1,
                        "process": {
                            "id": work.config["process"]["subject_id"],
                            "revision": work.config["process"]["subject_revision"],
                        },
                        "execution": work.scope.model_dump(mode="json"),
                        "operation_key": "assembly",
                    },
                ),
                lambda value: require(
                    value["current"] is True
                    and value["state"] == "known"
                    and value["fact"] is not None
                    and bool(value["required_source_read_set"])
                    and bool(value["relations"])
                    and any(
                        item["resource"]["id"] == str(work.resource_id) and item["current"] is True
                        for item in value["resources"]
                    )
                ),
            )
        for sample in sample_attempts(ROWS, LABELS[1:]):
            saved = fresh_sample(work, sample, identities)
            identities.add(saved["id"])
        assert len(identities) == len(ROWS["coverage_publication"]) and set(ROWS) == set(LABELS)
        assert all(row["success"] for rows in ROWS.values() for row in rows)
    except PerformancePending:
        OUTCOME, PENDING_REASON = "pending", "replacement_budget_exhausted"
        save()
        pytest.skip("Performance sampling pending: replacement budget exhausted")
    except Exception:
        OUTCOME = "failed"
        save()
        raise
    except BaseException:
        OUTCOME, PENDING_REASON = "pending", "interrupted"
        save()
        raise
    OUTCOME = "passed"
    save()


def fresh_sample(work, sample, identities):
    create = create_payload(work)
    create["title"] += f" impact performance {sample}"
    command_value, inputs = command(work, "change.request.create", create)
    response = post(work.quality, command_value)
    assert response.status_code == 200, response.text
    change_id = inputs["change_id"]
    root = f"/v1/categories/{work.setup.category}/products/{work.setup.product}/change-execution"
    body = {
        "capture_key": str(uuid4()),
        "change_id": str(change_id),
        "expected_change_revision": 1,
        "reason": "Synthetic fixed performance capture",
    }
    captured = http_measure(
        work,
        "change_capture",
        lambda: work.quality.client.post(
            root + "/captures",
            headers=work.quality.headers,
            json=body,
        ),
        lambda value: require("impact_payload" in value and "capture" in value),
    )
    impact = cmd(work.quality, "change.impact.compute", captured["impact_payload"])
    impact_inputs = http_measure(
        work,
        "change_impact_inputs",
        lambda: work.quality.client.post(
            root + "/inputs", headers=work.quality.headers, json=impact
        ),
        lambda value: require(value["allowed"] is True and bool(value["required_source_read_set"])),
    )
    impact["source_read_set"] = impact_inputs["required_source_read_set"]
    impact_saved = http_measure(
        work,
        "change_impact",
        lambda: post(work.quality, impact),
        lambda value: require(value["subject_revision"] == 2),
    )
    http_measure(
        work,
        "change_impact_replay",
        lambda: post(work.quality, impact),
        lambda value: require(value["id"] == impact_saved["id"]),
    )

    # A separate fresh proposal gives publication its own unchanged fixed origin.
    payload = create_payload(work)
    payload["title"] += f" coverage performance {sample}"
    value, inputs = command(work, "change.request.create", payload)
    receipt = post(work.quality, value)
    assert receipt.status_code == 200, receipt.text
    publication_change_id = inputs["change_id"]
    response = work.quality.client.post(
        root + "/captures",
        headers=work.quality.headers,
        json={
            **body,
            "capture_key": str(uuid4()),
            "change_id": publication_change_id,
        },
    )
    assert response.status_code == 200, response.text
    graph = GraphSnapshot.model_validate(response.json()["capture"]["graph"])
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as session:
        _, row = current_fixed(
            session, work.quality.ctx, work.setup.product, UUID(publication_change_id)
        )
        request = change_snapshot(row)
        scope, purpose = owner.fixed_seed(
            session, work.quality.ctx, work.setup.product, (*request.roots, *request.references)
        )
        basis = owner.inspect_basis(
            session, work.quality.ctx, work.setup.product, change_id=request.id, purpose=purpose
        )
        material = schemas.CoverageMaterial(
            schema_version="pdos-controlled-change-coverage-v1",
            scope=scope,
            purpose=purpose,
            change_id=request.id,
            origin_version_id=row.id,
            origin_revision=row.revision,
            owner_id=row.owner_id,
            visibility=row.visibility,
            publisher_id=work.quality.human,
            roots=request.roots,
            nodes=tuple(node.ref for node in graph.nodes),
            units=tuple(
                {"unit": f"object:{node.ref.identity}", "object_identity": node.ref.identity}
                for node in graph.nodes
            ),
            facets=tuple(
                {
                    "facet": facet,
                    "nodes": tuple(node.ref for node in graph.nodes),
                    "statement": "Synthetic fixed fixture enumeration; no production attestation",
                }
                for facet in schemas.FACETS
            ),
            closure_sha256=basis["closure_sha256"],
            valid_from=graph.captured_at,
            valid_until=graph.captured_at + timedelta(hours=1),
            nature="synthetic",
        )
    original = registered_original(
        work,
        material.model_dump(mode="json"),
        title=f"Synthetic complete coverage performance {sample}",
    )
    issuer = trust.configure(
        work.setup.engine,
        work.professional_issuer,
        scope=scope,
        approvals=(schemas.OriginalApproval(source=original, material_sha256=digest(material)),),
    )
    publication = schemas.CoverageImport(
        project_id=scope.project_id,
        change_id=material.change_id,
        purpose=purpose,
        source=original,
        reason="Synthetic trusted fixed performance publication",
    )
    try:
        command_id, key = uuid4(), str(uuid4())
        saved = publication_measure(
            work,
            lambda: publish(work, issuer, publication, command_id, key),
            lambda value: require(
                value["operation"] == schemas.OPERATION
                and value["subject_revision"] == 1
                and value["subject_type"] == schemas.FAMILY
                and value["id"] not in identities
            ),
        )
    finally:
        trust.disable(work.setup.engine, scope=scope)
    return saved


def require(condition):
    if not condition:
        raise AssertionError("Measured request did not produce the expected business result")
