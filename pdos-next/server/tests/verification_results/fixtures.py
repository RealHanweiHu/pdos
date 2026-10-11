"""Real stored synthetic reports and prior actual execution; root executes PG only."""

# ruff: noqa: F811 - imported fixtures register the existing dependency tree
import base64
import json
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from build_start.test_transactions import import_authority
from fastapi.testclient import TestClient
from security_fixture import secured_parse, synthetic_runtime
from sqlalchemy import inspect, select
from test_project_first_plan import cmd
from verification_handoff import fixtures as handoff
from verification_launch import fixtures as launch
from verification_launch.fixtures import (  # noqa: F401
    known_configuration,
    operational_work,
    ready_work,
)

from pdos_next.api import create_app
from pdos_next.database import tenant_session
from pdos_next.domain.verification_front import service as front
from pdos_next.domain.verification_launch import service as launch_service
from pdos_next.domain.verification_results import service
from pdos_next.domain.verification_results.schemas import CaptureInput
from pdos_next.models import Artifact, now
from pdos_next.object_storage import LocalPrivateObjectStore

OPERATIONS = set(service.PAYLOADS)


@pytest.fixture
def accepted_work(ready_work, monkeypatch):
    original_handoff = handoff.handoff

    def full_scope(work, *, operation="verification.handoff.offer", coverage=None, returned=()):
        if operation == "verification.handoff.accept":
            coverage, returned = None, ()
        return original_handoff(work, operation=operation, coverage=coverage, returned=returned)

    monkeypatch.setattr(handoff, "handoff", full_scope)
    fixture = launch.accepted_work.__wrapped__(ready_work, monkeypatch)
    try:
        yield next(fixture)
    finally:
        fixture.close()


@pytest.fixture
def launch_work(accepted_work, request, monkeypatch):
    # Only this results fixture creates a matching positive lab plan. The shared
    # launch fixture deliberately retains its original synthetic 20C scenario.
    conditions = {
        item["conditions"] for item in accepted_work.accepted_request["request_snapshot"]["items"]
    }
    assert conditions == {"23 C, dry"}, (
        "Positive result fixture needs one explicit accepted condition"
    )
    original_builder = launch.TestPlanBinding

    class ResultPlanBuilder:
        @staticmethod
        def model_validate(value):
            bound = deepcopy(value)
            bound["conditions"] = next(iter(conditions))
            return original_builder.model_validate(bound)

    # Patch the test-module construction alias; never modify the actual DTO's
    # model_validate implementation or any already stored plan/fact/clock.
    monkeypatch.setattr(launch, "TestPlanBinding", ResultPlanBuilder)
    fixture = launch.launch_work.__wrapped__(accepted_work, request, monkeypatch)
    try:
        yield next(fixture)
    finally:
        fixture.close()


@pytest.fixture
def results_work(launch_work, monkeypatch, tmp_path):
    work = launch_work
    launch.started(work, monkeypatch)  # Explicit server clock port; real PG RLS and writes.
    # Results-only credentials are new current facts after real execution. They
    # do not authorize or alter the saved Start; retained proof independently
    # rechecks its original, operation-specific signer and source facts.
    work.result_authority = {
        kind: import_authority(
            work,
            "quality",
            kind,
            subject_id=str(work.quality.human),
            operations=sorted(OPERATIONS),
            external_id=f"synthetic-results-{work.build_id}-{kind}",
        )
        for kind in ("duty", "qualification")
    }
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as session:
        _, row = launch_service._current(
            session, work.quality.ctx, work.setup.product, run_id=work.binding.run_id
        )
        run, plan = launch_service._snapshot(row)
        work.original_start = deepcopy(row.run_snapshot)
        work.original_start_id = row.id
    work.report_store = LocalPrivateObjectStore(tmp_path / "result-originals")
    prior_store = getattr(work.setup.engine, "_pdos_results_store", None)
    prior_security = getattr(work.setup.engine, "_pdos_security_runtime", None)
    original_clients = {
        name: getattr(work, name).client for name in ("quality", "engineer", "setup")
    }
    client = TestClient(
        create_app(
            work.setup.engine,
            work.setup.auth,
            object_store=work.report_store,
            security_runtime=synthetic_runtime(),
        )
    )
    for name in original_clients:
        getattr(work, name).client = client
    try:
        rows = []
        for pair in run.coverage:
            sample = next(s for s in run.samples if s.id == pair.sample_id)
            item = next(i for i in run.items if i.id == pair.item_id)
            rows.append(
                {
                    "format": "pdos-measurement-jsonl-v1",
                    "run_id": str(run.id),
                    "sample_id": str(sample.id),
                    "sample_revision": sample.revision,
                    "actual_configuration": sample.actual_configuration.model_dump(mode="json"),
                    "cavity": sample.cavity,
                    "item_id": item.id,
                    "raw_value": "10.0000",
                    "unit": item.unit,
                    "conditions": run.execution.conditions,
                    "environment": run.execution.environment,
                    "equipment": run.execution.equipment.model_dump(mode="json"),
                    "calibration": run.execution.calibration.model_dump(mode="json"),
                    "method": item.method.model_dump(mode="json"),
                    "executor_id": str(work.quality.human),
                    "observed_at": now().isoformat(),
                    "observed_timezone": "UTC",
                }
            )
        work.report_rows = rows
        work.report_artifact = upload_report(work, rows)
        yield work
    finally:
        client.close()
        for name, previous in original_clients.items():
            getattr(work, name).client = previous
        service.configure_store(work.setup.engine, prior_store)
        from pdos_next.original_security import configure

        configure(work.setup.engine, prior_security)


def _row_values(row):
    """Take plain column values before tenant_session commits and expires ORM state."""
    return SimpleNamespace(
        **{
            column.key: deepcopy(getattr(row, column.key))
            for column in inspect(row).mapper.column_attrs
        }
    )


def current_rows(work):
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as session:
        _, request_row = front._current(
            session, work.quality.ctx, work.setup.product, UUID(work.request_id)
        )
        _, run_row = launch_service._current(
            session, work.quality.ctx, work.setup.product, run_id=work.binding.run_id
        )
        run, plan = launch_service._snapshot(run_row)
        return SimpleNamespace(
            request=_row_values(request_row), row=_row_values(run_row), run=run, plan=plan
        )


def upload_report(work, rows):
    visibility = current_rows(work).row.visibility
    content = ("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n").encode()
    response = work.quality.client.post(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/originals",
        headers=work.quality.headers,
        json={
            "title": "Synthetic exact measurement JSONL",
            "filename": f"report-{uuid4()}.txt",
            "source_label": "Synthetic instrument source",
            "visibility": visibility,
            "content_base64": base64.b64encode(content).decode(),
            "idempotency_key": str(uuid4()),
            "expected_revision": 1,
        },
    )
    assert response.status_code == 200, response.text
    original_id = response.json()["subject_id"]
    reference = {
        "tenant_id": str(work.setup.tenant),
        "category_id": str(work.setup.category),
        "actor_id": str(work.quality.human),
        "requester_id": str(work.quality.human),
        "product_id": str(work.setup.product),
        "subject_id": original_id,
    }
    result = secured_parse(work.setup.engine, reference, work.report_store)
    assert result["status"] == "parsed", result
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as session:
        row = session.scalar(
            select(Artifact).where(
                Artifact.tenant_id == work.setup.tenant,
                Artifact.product_id == work.setup.product,
                Artifact.original_id == UUID(original_id),
            )
        )
        assert row is not None
        return row.id


def capture(work, indices=(0,), *, artifact_id=None, key=None):
    fixed = current_rows(work)
    value = CaptureInput(
        capture_key=key or str(uuid4()),
        expected_product_revision=1,
        request_id=work.request_id,
        expected_request_revision=fixed.request.revision,
        run_id=work.binding.run_id,
        expected_run_revision=fixed.row.revision,
        report_artifact_id=artifact_id or work.report_artifact,
        expected_report_revision=1,
        selections=[
            {
                "line": i + 1,
                "sample_id": work.report_rows[i]["sample_id"],
                "item_id": work.report_rows[i]["item_id"],
            }
            for i in indices
        ],
        reason="Synthetic original-byte selection",
    )
    result = work.quality.client.post(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/verification-results/captures",
        headers=work.quality.headers,
        json=value.model_dump(mode="json"),
    )
    assert result.status_code == 200, result.text
    return result.json(), value.model_dump(mode="json")


def event_ref(work, operation, fixed, *, text=None, basis=None):
    at = now()
    data = {
        "request_id": str(fixed.request.request_id),
        "run_id": str(fixed.run.id),
        "purpose": work.binding.purpose,
        "operation": operation,
        "occurred_at": at.isoformat(),
        "actor_id": str(work.quality.human),
    }
    if text is not None:
        data.update(text=text, basis_sha256=basis)
    reference = handoff.artifact(work.quality, json.dumps(data))
    return {
        "occurred_at": at.isoformat(),
        "original_timezone": "UTC",
        "source": handoff.event_source(launch.SimpleRef(reference)).model_dump(mode="json"),
    }, reference


def command(work, operation, *, captured=None, final=False, **changes):
    fixed = current_rows(work)
    value = {
        "request_id": str(fixed.request.request_id),
        "expected_request_revision": fixed.request.revision,
        "run_id": str(fixed.run.id),
        "expected_run_revision": fixed.run.revision,
        "reason": "Synthetic sourced result action",
        **deepcopy(changes),
    }
    basis = service._basis_sha(fixed.run, fixed.plan)
    if operation == "test.result.compute":
        value.setdefault("expected_basis_sha256", basis)
    else:
        sources = []
        if operation == "test.results.import":
            if captured:
                value.update(
                    capture_id=captured["capture"]["id"],
                    expected_capture_revision=captured["capture"]["revision"],
                )
            value["final"] = final
            if final:
                end, reference = event_ref(work, "test.run.end", fixed)
                value["actual_end"] = end
                sources.append(reference)
            else:
                value.update(
                    incomplete_reason="Remaining raw readings pending",
                    next_owner_id=str(work.quality.human),
                )
        else:
            from sqlalchemy import select

            from pdos_next.domain.verification_results.models import TestResultProjection

            with tenant_session(
                work.setup.engine,
                work.setup.tenant,
                actor_id=work.quality.human,
                category_id=work.setup.category,
            ) as session:
                projection = session.scalar(
                    select(TestResultProjection).where(
                        TestResultProjection.tenant_id == work.setup.tenant,
                        TestResultProjection.product_id == work.setup.product,
                        TestResultProjection.run_id == fixed.run.id,
                        TestResultProjection.basis_sha256 == basis,
                    )
                )
                assert projection is not None
                projection_id = projection.id
                projection_revision = projection.revision
            value.update(
                projection_id=str(projection_id),
                expected_projection_revision=projection_revision,
                expected_basis_sha256=basis,
            )
            value.setdefault("text", "Synthetic named professional conclusion, no external release")
        at, reference = event_ref(work, operation, fixed, text=value.get("text"), basis=basis)
        value["at"] = at
        sources.append(reference)
        value.setdefault("sources", sources)
    result = cmd(work.quality, operation, value)
    response = work.quality.client.post(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/verification-results/inputs",
        headers=work.quality.headers,
        json=result,
    )
    assert response.status_code == 200, response.text
    result["source_read_set"] = response.json()["required_source_read_set"]
    return result


def listing(work, *, caller=None):
    caller = caller or work.quality
    result = caller.client.get(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/verification-results",
        headers=caller.headers,
        params={"build_id": work.build_id, "run_id": str(work.binding.run_id)},
    )
    assert result.status_code == 200, result.text
    return result.json()
