"""Three real synthetic PG/HTTP change closures; executed only by the root task.

The existing result/Issue/CAPA chain supplies real fixed facts. These tests never
replace original-byte, qualification, graph-owner or common-transaction ports.
"""

# ruff: noqa: F811 - imported fixtures register the shared dependency tree
from copy import deepcopy
from datetime import datetime, timedelta
from typing import get_args
from uuid import UUID, uuid4

import pytest
from build_start.test_transactions import import_authority
from quality_execution.fixtures import (  # noqa: F401
    accepted_work,
    create_issue,
    draft_capa,
    known_configuration,
    launch_work,
    operational_work,
    publish_policy,
    quality_work,
    ready_work,
    results_work,
)
from sqlalchemy import event, func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_project_first_plan import cmd, post

from pdos_next.database import tenant_session
from pdos_next.domain.change_execution import service
from pdos_next.domain.change_execution.models import (
    ChangeCurrent,
    ChangeGraphCapture,
    ChangeRequestVersion,
)
from pdos_next.domain.professional_authority import service as professional
from pdos_next.domain.professional_authority.models import ProfessionalCurrent
from pdos_next.models import Artifact, Audit, Confirmation, Outbox, Receipt, now
from pdos_next.schemas.change_control.contracts import Facet


@pytest.fixture
def change_work(quality_work):
    work = quality_work
    # Independent change-only credentials precede Issue creation and its named
    # actions. They do not add powers to the previously saved physical Start.
    work.change_credential_fields = {
        "subject_id": str(work.quality.human),
        "operations": sorted(service.PAYLOADS),
        "valid_from": (now() - timedelta(minutes=1)).isoformat(),
        "valid_until": (now() + timedelta(hours=2)).isoformat(),
    }
    work.change_credentials = {
        kind: import_authority(
            work,
            "quality",
            kind,
            external_id=f"synthetic-change-{work.build_id}-{kind}",
            **work.change_credential_fields,
        )
        for kind in ("duty", "qualification")
    }
    prior = getattr(work.setup.engine, "_pdos_change_store", None)
    service.configure_store(work.setup.engine, work.report_store)
    try:
        publish_policy(work)
        receipt, _ = create_issue(work)
        work.issue_receipt, work.issue_view = draft_capa(work, receipt)
        work.issue_id = UUID(work.issue_view["issue_id"])
        work.capa_id = UUID(work.issue_view["issue"]["capa"]["id"])
        yield work
    finally:
        service.configure_store(work.setup.engine, prior)


def counts(work):
    with tenant_session(work.setup.engine, work.setup.tenant) as s:
        return {
            model.__tablename__: s.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == work.setup.tenant)
            )
            for model in (
                ChangeRequestVersion,
                ChangeCurrent,
                ChangeGraphCapture,
                Receipt,
                Audit,
                Outbox,
                Confirmation,
            )
        }


def current(work, change_id):
    with tenant_session(work.setup.engine, work.setup.tenant) as s:
        pointer = s.scalar(
            select(ChangeCurrent).where(
                ChangeCurrent.product_id == work.setup.product,
                ChangeCurrent.change_id == UUID(str(change_id)),
            )
        )
        row = s.get(ChangeRequestVersion, pointer.version_id)
        return {name: deepcopy(getattr(row, name)) for name in row.__table__.columns.keys()}, {
            "version_id": pointer.version_id,
            "revision": pointer.revision,
        }


def create_payload(work):
    revision = work.issue_view["revision"]
    return {
        "title": "Synthetic failure requires dual-lane impact",
        "reason": "Proposal only; no implementation, qualification or release",
        "roots": [{"id": str(work.issue_id), "revision": revision, "kind": "issue", "key": None}],
        "references": [
            {
                "id": str(work.issue_id),
                "revision": revision,
                "kind": "capa",
                "key": str(work.capa_id),
            }
        ],
        "sources": [work.hypothesis_source.model_dump(mode="json")],
        "visibility": "private",
    }


def command(work, operation, payload):
    value = cmd(work.quality, operation, deepcopy(payload))
    response = work.quality.client.post(
        f"/v1/products/{work.setup.product}/change-execution/inputs",
        headers=work.quality.headers,
        json=value,
    )
    assert response.status_code == 200, response.text
    assert response.json()["allowed"] is True
    value["source_read_set"] = response.json()["required_source_read_set"]
    return value, response.json()


def created(work):
    value, inputs = command(work, "change.request.create", create_payload(work))
    response = post(work.quality, value)  # Canonical T0: no material confirmation.
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["subject_type"] == "change_request"
    return receipt, value, inputs["change_id"]


def capture(work, change_id, *, key=None):
    payload = {
        "capture_key": key or str(uuid4()),
        "change_id": str(change_id),
        "expected_change_revision": 1,
        "reason": "Capture only fixed owner reads; completeness remains unknown",
    }
    response = work.quality.client.post(
        f"/v1/products/{work.setup.product}/change-execution/captures",
        headers=work.quality.headers,
        json=payload,
    )
    assert response.status_code == 200, response.text
    return response.json(), payload


def capture_post(work, payload):
    return work.quality.client.post(
        f"/v1/products/{work.setup.product}/change-execution/captures",
        headers=work.quality.headers,
        json=payload,
    )


def test_current_issue_capa_create_cross_key_one_receipt_exact_sources_and_private_scope(
    change_work,
):
    work = change_work
    before = counts(work)
    receipt, value, change_id = created(work)
    saved, pointer = current(work, change_id)
    assert saved["id"] == UUID(receipt["subject_id"]) and pointer["revision"] == 1
    assert saved["project_id"] == UUID(work.config["project"])
    assert saved["request_snapshot"]["roots"] == value["payload"]["roots"]
    assert saved["request_snapshot"]["references"] == value["payload"]["references"]
    assert saved["request_snapshot"]["orders"] == []
    assert set(r["artifact_id"] for r in work.issue_view["required_source_read_set"]) <= {
        r["artifact_id"] for r in saved["required_source_read_set"]
    }
    origins = {b["source_origin"] for b in saved["source_basis"]["evidence"].values()}
    assert origins == {"registered_native_text", "uploaded_original"}
    after = counts(work)
    for model in (ChangeRequestVersion, ChangeCurrent, Receipt, Audit, Outbox):
        assert after[model.__tablename__] == before[model.__tablename__] + 1
    assert after[Confirmation.__tablename__] == before[Confirmation.__tablename__]

    alias = {**deepcopy(value), "command_id": str(uuid4()), "idempotency_key": str(uuid4())}
    replay = post(work.quality, alias)
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == receipt["id"] and counts(work) == after

    opaque = deepcopy(alias)
    opaque.update(command_id=str(uuid4()), idempotency_key=str(uuid4()))
    opaque["payload"]["reason"] = "Different sourced request with an opaque client locator"
    opaque["payload"]["sources"][0]["position"] = "unverified client display position"
    refused = post(work.quality, opaque)
    assert refused.status_code == 422 and refused.json()["code"] == "MISSING_REQUIRED_EVIDENCE"
    forged = deepcopy(opaque)
    forged.update(command_id=str(uuid4()), idempotency_key=str(uuid4()))
    forged["payload"] = create_payload(work)
    forged["payload"]["references"][0]["key"] = str(uuid4())
    refused = post(work.quality, forged)
    assert refused.status_code == 409 and refused.json()["code"] == "FIXED_REFERENCE_MISMATCH"
    shared = deepcopy(alias)
    shared.update(command_id=str(uuid4()), idempotency_key=str(uuid4()))
    shared["payload"]["visibility"] = "product"
    refused = post(work.quality, shared)
    assert refused.status_code == 403 and refused.json()["code"] == "AUDIENCE_USE_FORBIDDEN"
    refused = post(work.engineer, alias)
    assert refused.status_code == 403 and refused.json()["code"] in {
        "FORBIDDEN_SCOPE",
        "SOURCE_UNAVAILABLE",
    }
    assert counts(work) == after

    source_id = UUID(work.policy_input["sources"][0]["artifact_id"])
    with Session(work.setup.admin) as s, s.begin():
        s.execute(update(Artifact).where(Artifact.id == source_id).values(status="withdrawn"))
    refused = post(work.quality, value)
    assert refused.status_code == 409 and refused.json()["code"] == "SOURCE_UNAVAILABLE"
    # Native sources without a safety epoch cannot undergo status ABA: the
    # deployed terminal-withdrawal constraint requires a new source identity.
    with pytest.raises(DBAPIError), Session(work.setup.admin) as s, s.begin():
        s.execute(update(Artifact).where(Artifact.id == source_id).values(status="active"))
    assert counts(work) == after and current(work, change_id)[1] == pointer


def test_graph_capture_exact_key_fixed_roots_unknown_facets_expiry_and_qualification_aba(
    change_work,
    monkeypatch,
):
    work = change_work
    _, _, change_id = created(work)
    captured, payload = capture(work, change_id)
    original = deepcopy(captured["capture"])
    graph = original["graph"]
    assert graph["roots"] == create_payload(work)["roots"]
    assert graph["scope"]["project_id"] == work.config["project"]
    assert graph["nature"] == "synthetic"
    assert {c["facet"] for c in graph["coverage"]} == set(get_args(Facet))
    assert all(c["status"] == "unknown" and c["reason"] for c in graph["coverage"])
    assert {n["ref"]["kind"] for n in graph["nodes"]} >= {
        "issue",
        "build",
        "sample",
        "test_run",
        "engineering_configuration",
        "bom",
        "manufacturing_configuration",
        "operation",
    }
    assert {
        (r["artifact_id"], r["expected_revision"])
        for r in work.issue_view["required_source_read_set"]
    } <= {(r["artifact_id"], r["expected_revision"]) for r in captured["required_source_read_set"]}
    from pdos_next.domain.verification_launch.models import (
        VerificationRunCurrent,
        VerificationRunVersion,
    )

    with tenant_session(work.setup.engine, work.setup.tenant) as session:
        pointed = session.scalar(
            select(VerificationRunCurrent).where(
                VerificationRunCurrent.product_id == work.setup.product,
                VerificationRunCurrent.run_id == work.binding.run_id,
            )
        )
        run_version = session.get(VerificationRunVersion, pointed.run_version_id)
        assert run_version.run_id == pointed.run_id
        assert run_version.revision == pointed.run_revision >= 3
        planned = session.scalar(
            select(VerificationRunVersion).where(
                VerificationRunVersion.product_id == work.setup.product,
                VerificationRunVersion.run_id == pointed.run_id,
                VerificationRunVersion.revision == 1,
            )
        )
        assert planned.status == "planned" and planned.operation == "test.run.plan"
        current_run_ref = ("test_run", str(pointed.run_id), pointed.run_revision)
        planned_run_ref = ("test_run", str(pointed.run_id), planned.revision)
    captured_refs = {
        (n["ref"]["kind"], n["ref"]["id"], n["ref"]["revision"]) for n in graph["nodes"]
    }
    assert current_run_ref in captured_refs
    assert planned_run_ref not in captured_refs
    for failure in work.issue_view["issue"]["failures"]:
        for kind, key in (("test_run", "run"), ("sample", "sample"), ("build", "build")):
            fixed = failure[key]
            assert (kind, fixed["id"], fixed["revision"]) in captured_refs
    baseline = counts(work)
    replay = capture_post(work, payload)
    assert replay.status_code == 200 and replay.json()["capture"] == original
    changed = capture_post(work, {**payload, "reason": "A different capture intent"})
    assert changed.status_code == 409 and changed.json()["code"] == "IDEMPOTENCY_CONFLICT"
    assert counts(work) == baseline
    impact, _ = command(work, "change.impact.compute", captured["impact_payload"])
    missing = {**deepcopy(impact), "source_read_set": []}
    refused = post(work.quality, missing)
    assert refused.status_code == 422 and refused.json()["code"] == "MISSING_REQUIRED_EVIDENCE"
    assert counts(work) == baseline

    prior = work.change_credentials["qualification"]
    revoked = import_authority(
        work,
        "quality",
        "qualification",
        external_id=f"synthetic-change-{work.build_id}-qualification",
        previous_id=prior["subject_id"],
        expected_previous_revision=prior["subject_revision"],
        state="revoked",
        **work.change_credential_fields,
    )
    refused = post(work.quality, impact)
    assert refused.status_code == 403 and refused.json()["code"] == "QUALIFICATION_REQUIRED"
    restored = import_authority(
        work,
        "quality",
        "qualification",
        external_id=f"synthetic-change-{work.build_id}-qualification",
        previous_id=revoked["subject_id"],
        expected_previous_revision=revoked["subject_revision"],
        state="active",
        **work.change_credential_fields,
    )
    with tenant_session(work.setup.engine, work.setup.tenant) as s:
        p = s.scalar(
            select(ProfessionalCurrent).where(
                ProfessionalCurrent.fact_id == UUID(restored["subject_id"])
            )
        )
        assert p.fact_revision == 3 and p.epoch == 3
    after_aba = counts(work)
    refused = post(work.quality, impact)
    assert refused.status_code == 409 and refused.json()["code"] == "SOURCE_STALE"
    assert counts(work) == after_aba and current(work, change_id)[1]["revision"] == 1
    # A new exact snapshot is required after ABA; the prior capture stays fixed.
    fresh, _ = capture(work, change_id)
    assert fresh["capture"]["id"] != original["id"]
    fresh_impact, _ = command(work, "change.impact.compute", fresh["impact_payload"])
    expiry = datetime.fromisoformat(fresh["capture"]["expires_at"])
    with monkeypatch.context() as patch:
        patch.setattr(service, "now", lambda: expiry + timedelta(microseconds=1))
        refused = post(work.quality, fresh_impact)
    assert refused.status_code == 409 and refused.json()["code"] == "GRAPH_CAPTURE_EXPIRED"
    with tenant_session(work.setup.engine, work.setup.tenant) as s:
        old = s.get(ChangeGraphCapture, UUID(original["id"]))
        assert old.graph_snapshot == graph
        assert old.expires_at.isoformat() == original["expires_at"]


def test_impact_terminal_outbox_failure_rolls_back_version_pointer_receipt_but_keeps_capture(
    change_work,
):
    work = change_work
    _, _, change_id = created(work)
    captured, _ = capture(work, change_id)
    value, _ = command(work, "change.impact.compute", captured["impact_payload"])
    before = counts(work)
    old, old_pointer = current(work, change_id)

    def fail(_mapper, _connection, _target):
        raise RuntimeError("Synthetic terminal change outbox failure")

    event.listen(Outbox, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="Synthetic terminal change outbox failure"):
            post(work.quality, value)
    finally:
        event.remove(Outbox, "before_insert", fail)
    assert counts(work) == before and current(work, change_id) == (old, old_pointer)
    with tenant_session(work.setup.engine, work.setup.tenant) as s:
        fixed_capture = s.get(ChangeGraphCapture, UUID(captured["capture"]["id"]))
        assert fixed_capture.graph_snapshot == captured["capture"]["graph"]

    result = post(work.quality, value)
    assert result.status_code == 200, result.text
    receipt = result.json()
    saved, pointer = current(work, change_id)
    assert receipt["subject_type"] == "change_request" and receipt["subject_revision"] == 2
    assert pointer == {"version_id": UUID(receipt["subject_id"]), "revision": 2}
    assert saved["previous_version_id"] == old["id"] and saved["previous_revision"] == 1
    assert saved["request_snapshot"]["status"] == "analysis"
    assert saved["request_snapshot"]["roots"] == old["request_snapshot"]["roots"]
    assert saved["request_snapshot"]["orders"] == []
    assessment = saved["request_snapshot"]["assessments"][0]
    assert assessment["graph"] == captured["capture"]["graph"]
    assert set(x["facet"] for x in assessment["unknown"]) == set(get_args(Facet))
    after = counts(work)
    for model in (ChangeRequestVersion, Receipt, Audit, Outbox):
        assert after[model.__tablename__] == before[model.__tablename__] + 1
    for model in (ChangeCurrent, ChangeGraphCapture, Confirmation):
        assert after[model.__tablename__] == before[model.__tablename__]
    with tenant_session(work.setup.engine, work.setup.tenant) as s:
        for model in (Audit, Outbox):
            assert (
                s.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.receipt_id == UUID(receipt["id"]))
                )
                == 1
            )
    alias = {**deepcopy(value), "idempotency_key": str(uuid4()), "command_id": str(uuid4())}
    replay = post(work.quality, alias)
    assert replay.status_code == 200 and replay.json()["id"] == receipt["id"]
    assert counts(work) == after
    professional.disable_issuer(work.setup.engine, work.professional_issuer.key)
    refused = post(work.quality, value)
    assert refused.status_code == 403 and refused.json()["code"] == "QUALIFICATION_REQUIRED"
    assert counts(work) == after and current(work, change_id)[1] == pointer
