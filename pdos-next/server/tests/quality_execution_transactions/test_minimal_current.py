"""Actual direct quality commands; root owns execution on the verified PG target."""

# ruff: noqa: F401,F811 -- explicit imports register the existing real fixture tree

from copy import deepcopy
from uuid import uuid4

import pytest
from quality_execution.fixtures import (
    accepted_work,
    command,
    counts,
    create_issue,
    known_configuration,
    launch_work,
    operational_work,
    publish_policy,
    quality_work,
    ready_work,
    results_work,
    unconsumed,
)
from sqlalchemy import event, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value
from test_project_first_plan import post
from test_resource_dependency_execution import engines

from pdos_next import quality_result_bridge, request_proof
from pdos_next.domain.quality_execution import service
from pdos_next.domain.sample_handoff import service as samples
from pdos_next.domain.test_resources import retained
from pdos_next.domain.test_resources import service as resources
from pdos_next.domain.verification_launch.models import VerificationRunVersion
from pdos_next.domain.verification_results.models import MeasurementRecord
from pdos_next.models import Artifact, Outbox, now


def _ready(work):
    publish_policy(work)
    created, _ = create_issue(work)
    payload = {
        "issue_id": created["result"]["issue_id"],
        "expected_issue_revision": 1,
        "reason": "Actual named direct triage",
    }
    return created, payload


def _view(work, issue_id):
    response = work.quality.client.get(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/quality-execution",
        headers=work.quality.headers,
        params={"issue_id": issue_id},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    pointer = data["current_by_issue"][issue_id]
    return next(row for row in data["issues"] if row["id"] == pointer["issue_version_id"])


def _block_upstream(work, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("A direct quality action must not re-prove the upstream chain")

    for port in (
        "_pdos_quality_result_bridge",
        "_pdos_quality_result_refresh",
        "_pdos_quality_result_scope",
    ):
        monkeypatch.setattr(work.setup.engine, port, forbidden)
    for module, name in (
        (service, "_result"),
        (quality_result_bridge, "fixed_failure_result"),
        (quality_result_bridge, "recheck_fixed_failure_result"),
        (quality_result_bridge, "inspect_retained_execution"),
        (retained, "inspect_retained_execution"),
        (resources, "inspect_retained_execution"),
        (resources, "load_bundle"),
        (samples, "inspect_sample"),
        (samples, "inspect_execution"),
    ):
        monkeypatch.setattr(module, name, forbidden)


def test_direct_read_inputs_preview_confirmation_and_replay_do_not_reinspect_upstream(
    quality_work, monkeypatch
):
    work = quality_work
    created, payload = _ready(work)
    issue_id = payload["issue_id"]
    # Every failure in this exact selected Run already has a stored Issue.
    # Unknown first deliveries keep their separate initial verification path.
    for index in range(1, len(work.failure_run.measurements)):
        create_issue(work, index)
    _block_upstream(work, monkeypatch)
    before = counts(work)
    current = _view(work, issue_id)
    assert current["source_status"] == "current"
    assert current["capabilities"]["quality.issue.triage"] is True
    selected = work.quality.client.get(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/quality-execution",
        headers=work.quality.headers,
        params={"run_id": str(work.failure_run.id), "build_id": work.build_id},
    )
    assert selected.status_code == 200, selected.text
    assert len(selected.json()["failures"]) == len(work.failure_run.measurements)
    assert all(failure["available"] for failure in selected.json()["failures"])
    value = command(work, "quality.issue.triage", payload)
    reviewed = post(work.quality, value, True)
    assert reviewed.status_code == 200, reviewed.text
    assert counts(work) == before
    confirmed = reviewed.json()["command"]
    committed = post(work.quality, confirmed)
    assert committed.status_code == 200, committed.text
    saved = _view(work, issue_id)
    assert saved["revision"] == 2 and saved["issue"]["status"] == "triaged"
    assert saved["issue"]["failures"] == current["issue"]["failures"]
    assert saved["issue"]["history"][-1]["command_id"] == confirmed["command_id"]
    after = counts(work)
    replayed = post(work.quality, confirmed)
    assert replayed.status_code == 200 and replayed.json()["id"] == committed.json()["id"]
    assert counts(work) == after

    contained = command(
        work,
        "quality.issue.containment.record",
        {
            "issue_id": issue_id,
            "expected_issue_revision": 2,
            "action": {
                "id": str(uuid4()),
                "text": "Actual sourced containment with the direct confirmation protocol",
                "executor_id": str(work.quality.human),
                "evidence": [work.containment_source.model_dump(mode="json")],
                "at": {
                    "occurred_at": now().isoformat(),
                    "original_timezone": "UTC",
                    "source": work.containment_source.model_dump(mode="json"),
                },
            },
        },
    )
    preview = post(work.quality, contained, True)
    assert preview.status_code == 200, preview.text
    result = post(work.quality, preview.json()["command"])
    assert result.status_code == 200, result.text
    final = _view(work, created["result"]["issue_id"])
    assert final["revision"] == 3 and final["issue"]["status"] == "actioning"
    assert final["issue"]["failures"] == current["issue"]["failures"]


def test_issue_current_advanced_after_preview_rejects_without_consuming_or_new_effects(
    quality_work,
):
    work = quality_work
    _, payload = _ready(work)
    first = post(work.quality, command(work, "quality.issue.triage", payload), True)
    assert first.status_code == 200, first.text
    competing = {**payload, "reason": "Another named decision advances the exact Current"}
    second = post(work.quality, command(work, "quality.issue.triage", competing), True)
    assert second.status_code == 200, second.text
    accepted = post(work.quality, second.json()["command"])
    assert accepted.status_code == 200, accepted.text
    before = counts(work)
    refused = post(work.quality, first.json()["command"])
    assert refused.status_code == 409 and refused.json()["code"] == "VERSION_CONFLICT"
    unconsumed(work, first.json()["command"]["payload"]["confirmation_token"])
    assert counts(work) == before
    assert _view(work, payload["issue_id"])["revision"] == 2


def test_direct_source_withdrawn_after_preview_rejects_without_consuming_or_new_effects(
    quality_work,
):
    work = quality_work
    _, payload = _ready(work)
    reviewed = post(work.quality, command(work, "quality.issue.triage", payload), True)
    assert reviewed.status_code == 200, reviewed.text
    with Session(work.setup.admin) as session, session.begin():
        session.execute(
            update(Artifact).where(Artifact.id == work.failure_report).values(status="withdrawn")
        )
    before = counts(work)
    confirmed = reviewed.json()["command"]
    refused = post(work.quality, confirmed)
    assert refused.status_code == 409 and refused.json()["code"] == "SOURCE_UNAVAILABLE"
    unconsumed(work, confirmed["payload"]["confirmation_token"])
    assert counts(work) == before


def test_changed_payload_cannot_consume_but_original_preview_remains_usable(quality_work):
    work = quality_work
    _, payload = _ready(work)
    reviewed = post(work.quality, command(work, "quality.issue.triage", payload), True)
    assert reviewed.status_code == 200, reviewed.text
    confirmed = reviewed.json()["command"]
    changed = deepcopy(confirmed)
    changed["payload"]["reason"] = "A decision that was never previewed"
    before = counts(work)
    refused = post(work.quality, changed)
    assert refused.status_code == 409 and refused.json()["code"] == "CONFIRMATION_REQUIRED"
    assert refused.json()["detail"]["reason"] == "CONFIRMATION_SCOPE_CHANGED"
    unconsumed(work, confirmed["payload"]["confirmation_token"])
    assert counts(work) == before
    accepted = post(work.quality, confirmed)
    assert accepted.status_code == 200, accepted.text


def test_actual_command_identity_is_bound_to_saved_history_when_transport_key_changes(
    quality_work,
):
    work = quality_work
    _, payload = _ready(work)
    reviewed = post(work.quality, command(work, "quality.issue.triage", payload), True)
    assert reviewed.status_code == 200, reviewed.text
    confirmed = deepcopy(reviewed.json()["command"])
    confirmed["command_id"], confirmed["idempotency_key"] = str(uuid4()), str(uuid4())
    response = post(work.quality, confirmed)
    assert response.status_code == 200, response.text
    saved = _view(work, payload["issue_id"])
    assert saved["issue"]["history"][-1]["command_id"] == confirmed["command_id"]


@pytest.mark.parametrize("corruption", ["scope", "run_hash", "measurement_hash"])
def test_real_loaded_direct_failure_still_checks_complete_scope_and_material_hashes(
    quality_work, monkeypatch, corruption
):
    work = quality_work
    _, payload = _ready(work)
    value = command(work, "quality.issue.triage", payload)
    reviewed = post(work.quality, value, True)
    assert reviewed.status_code == 200, reviewed.text
    before = counts(work)
    original = request_proof.snapshot_get
    touched = []

    def corrupt_actual_projection(s, model, identity, **kwargs):
        row = original(s, model, identity, **kwargs)
        if row is not None and not touched:
            if corruption == "scope" and model is MeasurementRecord:
                set_committed_value(row, "project_id", uuid4())
            elif corruption == "run_hash" and model is VerificationRunVersion:
                set_committed_value(row, "snapshot_sha256", "0" * 64)
            elif corruption == "measurement_hash" and model is MeasurementRecord:
                set_committed_value(row, "measurement_sha256", "0" * 64)
            else:
                return row
            touched.append(row.id)
        return row

    # Only an already RLS-loaded ORM projection is altered; no Current/FK/RLS
    # is disabled and no malformed database row or synthetic authority is made.
    monkeypatch.setattr(request_proof, "snapshot_get", corrupt_actual_projection)
    refused = post(work.quality, reviewed.json()["command"])
    assert len(touched) == 1
    expected_status = 403 if corruption == "scope" else 409
    expected_code, expected_reason = {
        "scope": ("FORBIDDEN_SCOPE", "FORBIDDEN_SCOPE"),
        "run_hash": ("VALIDATION_FAILED", "INTEGRITY_MISMATCH"),
        "measurement_hash": ("SOURCE_STALE", "SOURCE_STALE"),
    }[corruption]
    assert refused.status_code == expected_status, refused.text
    assert refused.json()["code"] == expected_code
    assert refused.json()["detail"]["reason"] == expected_reason
    assert counts(work) == before
    unconsumed(work, reviewed.json()["command"]["payload"]["confirmation_token"])


def test_direct_late_outbox_failure_rolls_back_current_effects_and_confirmation(quality_work):
    work = quality_work
    _, payload = _ready(work)
    reviewed = post(work.quality, command(work, "quality.issue.triage", payload), True)
    assert reviewed.status_code == 200, reviewed.text
    confirmed = reviewed.json()["command"]
    before = counts(work)

    def rejected(_mapper, _connection, row):
        if row.type == "issue.triaged":
            raise RuntimeError("synthetic-direct-quality-outbox-failure")

    event.listen(Outbox, "before_insert", rejected)
    try:
        with pytest.raises(RuntimeError, match="synthetic-direct-quality-outbox-failure"):
            post(work.quality, confirmed)
    finally:
        event.remove(Outbox, "before_insert", rejected)
    assert counts(work) == before
    unconsumed(work, confirmed["payload"]["confirmation_token"])
    assert _view(work, payload["issue_id"])["revision"] == 1
