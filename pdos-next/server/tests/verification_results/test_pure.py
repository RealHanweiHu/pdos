"""Result append/kernel boundaries and original-byte proof; no database or credentials."""

import hashlib
import json
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from verification_launch.test_pure import started
from verification_launch.test_pure import work as launch_work

from pdos_next.domain.measurement_evidence.schemas import ReportBinding
from pdos_next.domain.measurement_evidence.verifier import (
    extract_observations,
    fixed_run_sha256,
    verify_measurement,
)
from pdos_next.domain.verification.handlers import semantic_digest
from pdos_next.domain.verification.ports import Invocation
from pdos_next.domain.verification_front.adapters import authority_dto
from pdos_next.domain.verification_launch.models import (
    VerificationRunCurrent,
    VerificationRunVersion,
)
from pdos_next.domain.verification_results import service
from pdos_next.domain.verification_results.adapters import ResultsCommands, RetainedSamples, kernel
from pdos_next.domain.verification_results.schemas import (
    CaptureInput,
    ComputePayload,
    ImportPayload,
)
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import (
    EventTime,
    ResultsSubmit,
    RunDisposition,
    RunReview,
)
from pdos_next.service import Context, digest


@pytest.fixture
def work():
    value = launch_work.__wrapped__()
    mutation = started(value)
    value.request, value.run = mutation.request, mutation.run
    value.recorded = []
    value.proved = []
    value.now = value.run.actual_start.occurred_at + timedelta(minutes=2)
    return value


def report(work, values=("1.5", "1.6"), **changes):
    rows = []
    for coverage, raw in zip(work.run.coverage, values, strict=False):
        sample = next(s for s in work.run.samples if s.id == coverage.sample_id)
        item = next(i for i in work.run.items if i.id == coverage.item_id)
        row = {
            "format": "pdos-measurement-jsonl-v1",
            "run_id": str(work.run.id),
            "sample_id": str(sample.id),
            "sample_revision": sample.revision,
            "actual_configuration": sample.actual_configuration.model_dump(mode="json"),
            "cavity": sample.cavity,
            "item_id": item.id,
            "raw_value": raw,
            "unit": item.unit,
            "conditions": work.run.execution.conditions,
            "environment": work.run.execution.environment,
            "equipment": work.run.execution.equipment.model_dump(mode="json"),
            "calibration": work.run.execution.calibration.model_dump(mode="json"),
            "method": item.method.model_dump(mode="json"),
            "executor_id": str(work.actor),
            "observed_at": (work.run.actual_start.occurred_at + timedelta(seconds=1)).isoformat(),
            "observed_timezone": "UTC",
        }
        row.update(changes)
        rows.append(row)
    content = ("\n".join(json.dumps(row) for row in rows) + "\n").encode()
    binding = ReportBinding(
        scope=work.run.scope,
        run_id=work.run.id,
        run_revision=work.run.revision,
        request_id=work.run.request_id,
        request_revision=work.run.request_revision,
        run_basis_sha256=fixed_run_sha256(work.run, work.plan),
        report={"id": uuid4(), "revision": 1, "kind": "artifact", "position": "measurement-report"},
        original={
            "id": uuid4(),
            "revision": 1,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size": len(content),
            "media_type": "text/plain",
        },
        security_epoch=1,
        pairs=tuple(
            {
                "sample": next(s for s in work.run.samples if s.id == c.sample_id),
                "item_id": c.item_id,
            }
            for c in work.run.coverage
        ),
        execution_plan=work.plan,
    )
    candidates = extract_observations(content, binding).observations
    measurements = tuple(c.to_measurement(uuid4()) for c in candidates)
    return content, binding, candidates, measurements


def event(work, at=None):
    return EventTime(occurred_at=at or work.now, original_timezone="UTC", source=work.source)


def handler(
    work, *, accepted=True, retained=True, qualified=True, roles=("quality",), actor_kind="human"
):
    authority = authority_dto(
        {
            "scope": work.run.scope.model_dump(mode="json"),
            "roles": roles,
            "authorized": True,
            "qualified": qualified,
        },
        work.actor,
        work.now,
    )
    authority = authority.model_copy(update={"actor_kind": actor_kind})

    def record(mutation):
        work.recorded.append(mutation)
        return mutation.run

    commands = ResultsCommands(
        authority,
        work.request,
        record,
        accepted_confirmation=accepted,
        fixed_run=work.run,
        fixed_runs=(work.run,),
    )

    def proof(scope, measurement, run):
        assert scope == work.run.scope and run.id == work.run.id
        if measurement.id not in work.proved:
            raise DomainError("INTEGRITY_MISMATCH", "No original proof")

    def prior(scope, run):
        if not retained:
            raise DomainError("RETAINED_EXECUTION_UNAVAILABLE", "No prior effect")

    return kernel(commands, work.request.build, lambda *_: None, proof, prior)


def execute(work, payload, operation, **changes):
    invocation = Invocation(
        command_id=uuid4(),
        operation=operation,
        subject_id=work.run.id,
        expected_revision=work.run.revision,
        semantic_digest=semantic_digest(payload),
    )
    handler(work, **changes).execute(invocation, payload)
    mutation = work.recorded[-1]
    work.request, work.run = mutation.request, mutation.run
    return mutation


def import_payload(work, measurements, final=False):
    return ResultsSubmit(
        measurements=measurements,
        at=event(work),
        final=final,
        actual_end=event(work) if final else None,
        incomplete_reason=None if final else "Explicit remaining readings",
        next_owner_id=None if final else work.actor,
    )


def test_two_batches_keep_start_and_consumption_then_separate_review_disposition(work):
    initial = work.run
    _, _, _, measurements = report(work)
    work.proved = [m.id for m in measurements]
    first = execute(work, import_payload(work, measurements[:1]), "test.results.import")
    assert first.run.status == "running" and first.run.result == "indeterminate"
    assert len(first.run.partial_returns[0].pending_coverage) == 1
    assert first.request.timeline.final_result is None
    work.now += timedelta(seconds=1)
    final = execute(work, import_payload(work, measurements[1:], True), "test.results.import")
    assert final.run.status == "results_pending" and final.run.result == "pass"
    assert (
        final.run.actual_start == initial.actual_start and final.run.execution == initial.execution
    )
    assert final.request.status == "reported"
    basis = service._basis_sha(final.run, work.plan)
    work.now += timedelta(seconds=1)
    reviewed = execute(
        work, RunReview(text="Named synthetic review", at=event(work)), "test.run.review"
    )
    assert reviewed.run.result == "pass" and reviewed.run.status == "reviewed"
    assert reviewed.request == final.request
    assert service._basis_sha(reviewed.run, work.plan) == basis
    work.now += timedelta(seconds=1)
    disposed = execute(
        work,
        RunDisposition(text="Internal test disposition only", at=event(work)),
        "test.disposition.decide",
    )
    assert disposed.run.status == "disposed" and disposed.request.status == "disposed"
    assert disposed.run.measurements == measurements
    assert service._basis_sha(disposed.run, work.plan) == basis
    # Only the earlier launch reserved, and result ports have no reserve effects.
    assert len(work.reserved) == 1


def test_final_run_does_not_complete_unaccepted_request_gap(work):
    work.request = work.request.model_copy(
        update={"items": (work.request.items[0].model_copy(update={"sample_count": 3}),)}
    )
    work.run = work.run.model_copy(update={"items": work.request.items})
    _, _, _, measurements = report(work)
    work.proved = [m.id for m in measurements]
    execute(work, import_payload(work, measurements, True), "test.results.import")
    assert work.run.status == "results_pending" and work.run.result == "pass"
    assert work.request.status == "executing" and work.request.timeline.final_result is None
    work.now += timedelta(seconds=1)
    execute(
        work,
        RunReview(text="Known Run outcome, request gap remains", at=event(work)),
        "test.run.review",
    )
    work.now += timedelta(seconds=1)
    execute(work, RunDisposition(text="This Run only", at=event(work)), "test.disposition.decide")
    assert work.run.status == "disposed" and work.request.status == "executing"
    assert work.request.timeline.disposed is None


def test_original_read_failure_does_not_expose_storage_path(work, monkeypatch):
    from pdos_next.object_storage import StorageFailure

    def unavailable(*_):
        raise StorageFailure(
            "private-root/token/path", "Sensitive private path must never be shown"
        )

    monkeypatch.setattr(service, "read_registered_bytes", unavailable)
    with pytest.raises(DomainError) as error:
        service._read_bytes(object(), object(), work.run.scope.tenant_id, work.run.scope.product_id)
    assert error.value.reason == "STORAGE_UNAVAILABLE"
    assert "private-root" not in error.value.message and "Sensitive" not in error.value.message


def test_report_binding_uses_real_original_bytes_and_security_epoch(work, tmp_path, monkeypatch):
    from pdos_next.object_storage import LocalPrivateObjectStore

    content, _, _, _ = report(work)
    store = LocalPrivateObjectStore(tmp_path / "pure-originals")
    reference = store.put_new(content, media_type="text/plain")
    original = SimpleNamespace(
        id=reference.id,
        media_type="text/plain",
        status="parsed",
        revision=1,
        byte_count=len(content),
        content_hash=hashlib.sha256(content).hexdigest(),
    )
    artifact = SimpleNamespace(
        id=uuid4(), revision=1, original_id=reference.id, content="derived coordinates differ"
    )
    monkeypatch.setattr(service, "source_for", lambda *_: artifact)
    monkeypatch.setattr(service, "require_original", lambda *_, **__: original)
    monkeypatch.setattr(service, "object_reference", lambda _: reference)
    monkeypatch.setattr(service, "require_safe", lambda *_, **kwargs: (7, {}))
    ctx = Context(work.run.scope.tenant_id, work.actor, work.actor)
    read, binding, _ = service._read_report(
        None, ctx, work.run.scope.product_id, work.run, work.plan, artifact.id, 1, store
    )
    assert read == content and binding.original.sha256 == hashlib.sha256(content).hexdigest()
    assert binding.security_epoch == 7 and binding.report.id == artifact.id
    epochs = iter((7, 8))
    monkeypatch.setattr(service, "require_safe", lambda *_, **kwargs: (next(epochs), {}))
    with pytest.raises(DomainError) as error:
        service._read_report(
            None, ctx, work.run.scope.product_id, work.run, work.plan, artifact.id, 1, store
        )
    assert error.value.reason == "SOURCE_STALE"


def test_final_empty_batch_uses_all_previously_verified_readings(work):
    _, _, _, measurements = report(work)
    work.proved = [m.id for m in measurements]
    execute(work, import_payload(work, measurements), "test.results.import")
    assert work.run.final_result is None and work.run.result == "indeterminate"
    work.now += timedelta(seconds=1)
    execute(work, import_payload(work, (), True), "test.results.import")
    assert work.run.result == "pass" and work.run.status == "results_pending"


@pytest.mark.parametrize("raw", [None, "not numeric", "NaN"])
def test_complete_unknown_raw_values_remain_indeterminate(work, raw):
    _, _, candidates, measurements = report(work, values=(raw, "1.6"))
    work.proved = [m.id for m in measurements]
    execute(work, import_payload(work, measurements, True), "test.results.import")
    assert work.run.result == "indeterminate" and work.run.status == "results_pending"
    assert work.run.measurements[0].raw_value == raw
    assert candidates[0].value_state != "known"


@pytest.mark.parametrize(
    "changes", [{"executor_id": None}, {"calibration": None}, {"observed_at": None}]
)
def test_report_metadata_is_not_backfilled_from_execution(work, changes):
    content, binding, candidates, measurements = report(work, **changes)
    assert candidates[0].missing
    assert (
        verify_measurement(content, binding, measurements[0], work.run).observation == candidates[0]
    )
    work.proved = [m.id for m in measurements]
    execute(work, import_payload(work, measurements, True), "test.results.import")
    assert work.run.result == "indeterminate"


@pytest.mark.parametrize(
    "condition,code",
    [
        ("retained", "RETAINED_EXECUTION_UNAVAILABLE"),
        ("confirmed", "CONFIRMATION_REQUIRED"),
        ("qualified", "QUALIFICATION_REQUIRED"),
        ("proved", "INTEGRITY_MISMATCH"),
    ],
)
def test_missing_actual_proof_or_authority_blocks_before_record(work, condition, code):
    _, _, _, measurements = report(work)
    work.proved = [m.id for m in measurements] if condition != "proved" else []
    kwargs = (
        {"retained": False}
        if condition == "retained"
        else (
            {"accepted": False}
            if condition == "confirmed"
            else {"qualified": False}
            if condition == "qualified"
            else {}
        )
    )
    with pytest.raises(DomainError) as error:
        execute(work, import_payload(work, measurements, True), "test.results.import", **kwargs)
    assert error.value.reason == code and not work.recorded


def test_duplicate_pair_cannot_replace_original_reading_or_new_id(work):
    _, _, _, measurements = report(work)
    work.proved = [m.id for m in measurements]
    execute(work, import_payload(work, measurements[:1]), "test.results.import")
    before = work.run
    replacement = measurements[0].model_copy(update={"id": uuid4(), "raw_value": "1.99"})
    work.proved.append(replacement.id)
    with pytest.raises(DomainError) as error:
        execute(work, import_payload(work, (replacement,)), "test.results.import")
    assert error.value.reason == "MEASUREMENT_ALREADY_RECORDED" and work.run == before


def test_final_must_cover_all_fixed_pairs_even_if_request_partially_accepted(work):
    _, _, _, measurements = report(work)
    work.proved = [m.id for m in measurements]
    with pytest.raises(DomainError) as error:
        execute(work, import_payload(work, measurements[:1], True), "test.results.import")
    assert error.value.reason == "INCOMPLETE_FINAL_SCOPE" and not work.recorded


def test_retained_port_never_reserves_or_releases():
    port = RetainedSamples(lambda *_: None)
    for method in (port.inspect, port.reserve):
        with pytest.raises(DomainError) as error:
            method()
        assert error.value.reason == "INVALID_OPERATION"


def test_capture_selects_source_values_and_not_request_defaults(work):
    content, binding, _, _ = report(work, values=(None, "9.000"))
    input = CaptureInput(
        capture_key="synthetic-source-key",
        expected_product_revision=1,
        request_id=work.request.id,
        expected_request_revision=work.request.revision,
        run_id=work.run.id,
        expected_run_revision=work.run.revision,
        report_artifact_id=binding.report.id,
        expected_report_revision=1,
        selections=[{"line": 2, "sample_id": work.run.samples[1].id, "item_id": "dimension"}],
        reason="synthetic original selection",
    )
    prepared = service.extract_capture(input, service.ReadReport(content, binding, {}, [], []))
    assert len(prepared.measurements) == 1 and prepared.measurements[0].raw_value == "9.000"
    assert prepared.observations[0].line == 2
    with pytest.raises(ValidationError):
        CaptureInput.model_validate({**input.model_dump(mode="json"), "raw_value": "1.5"})


def test_basis_stable_for_receive_clocks_and_t2_status_but_changes_raw(work):
    _, _, _, measurements = report(work)
    work.proved = [m.id for m in measurements]
    execute(work, import_payload(work, measurements, True), "test.results.import")
    original = service._basis_sha(work.run, work.plan)
    changed = work.run.model_copy(
        update={
            "revision": 50,
            "status": "disposed",
            "final_result": work.run.final_result.model_copy(
                update={"received_at": work.now + timedelta(days=1)}
            ),
        }
    )
    assert service._basis_sha(changed, work.plan) == original
    changed = work.run.model_copy(
        update={
            "measurements": (
                measurements[0].model_copy(update={"raw_value": "1.50"}),
                measurements[1],
            )
        }
    )
    assert service._basis_sha(changed, work.plan) != original


@pytest.mark.parametrize("bad", ["naive", "duplicate"])
def test_source_event_rejects_naive_or_duplicate_fields(bad):
    line = (
        '{"occurred_at":"2026-10-02T12:00:00"}'
        if bad == "naive"
        else '{"occurred_at":"2026-10-02T12:00:00Z","occurred_at":"2026-10-02T12:00:00Z"}'
    )
    with pytest.raises(DomainError) as error:
        service._parse_event(line)
    assert error.value.reason == "INVALID_EVENT_EVIDENCE"


def test_equivalent_event_offsets_compare_same_instant():
    assert service._parse_event('{"occurred_at":"2026-10-02T12:00:00Z"}') == service._parse_event(
        '{"occurred_at":"2026-10-02T05:00:00-07:00"}'
    )


@pytest.mark.parametrize("changed", ["request", "run", "missing_request", "missing_run", None])
def test_new_capture_requires_both_current_version_pointers(work, monkeypatch, changed):
    request_row = SimpleNamespace(id=uuid4(), request_id=work.request.id)
    run_row = SimpleNamespace(id=uuid4(), run_id=work.run.id)
    current_request = (
        None
        if changed == "missing_request"
        else SimpleNamespace(id=uuid4() if changed == "request" else request_row.id)
    )
    current_run = (
        None
        if changed == "missing_run"
        else SimpleNamespace(id=uuid4() if changed == "run" else run_row.id)
    )
    monkeypatch.setattr(service.front, "_current", lambda *_, **__: (object(), current_request))
    monkeypatch.setattr(service.launch, "_current", lambda *_, **__: (object(), current_run))
    if changed:
        with pytest.raises(DomainError) as error:
            service._capture_current(None, None, work.run.scope.product_id, request_row, run_row)
        assert error.value.reason == "VERSION_CONFLICT"
    else:
        service._capture_current(None, None, work.run.scope.product_id, request_row, run_row)


@pytest.mark.parametrize(
    "change", ["issuer", "authority", "retained_issuer", "ledger", "source", "reads", None]
)
def test_original_store_callback_epoch_drift_is_rejected_before_proof_use(
    work, monkeypatch, change
):
    from pdos_next.object_storage import ObjectRef

    state = {
        "authority_epoch": 1,
        "retained_epoch": 1,
        "ledger": "fixed",
        "source": "fixed",
        "reads": [],
    }

    def authority(*_, **__):
        return {
            "scope": work.run.scope.model_dump(mode="json"),
            "subject_id": str(work.actor),
            "operation": "test.results.import",
            "purpose": work.request.purpose,
            "qualified": True,
            "authorized": True,
            "roles": ["quality"],
            "fact_refs": [{"epoch": state["authority_epoch"]}],
            "facts_revision": digest(state["authority_epoch"]),
            "valid_until": (work.now + timedelta(hours=1)).isoformat(),
            "required_source_read_set": [],
        }

    def retained(*_, **__):
        return {
            "current": True,
            "source_basis": state["source"],
            "facts_revision": digest(state["retained_epoch"]),
            "reservation": state["ledger"],
            "required_source_read_set": state["reads"],
            "original_start_intent": "a" * 64,
            "checked_at": work.now.isoformat(),
            "execution_window_elapsed": False,
        }

    initial_authority, initial_retained = deepcopy(authority()), deepcopy(retained())
    bound = SimpleNamespace(
        run_row=object(),
        request_row=SimpleNamespace(project_id=work.run.scope.project_id),
        request=work.request,
        authority=initial_authority,
        retained=initial_retained,
    )
    monkeypatch.setattr(service.front, "_assess", authority)
    monkeypatch.setattr(service, "_retained", retained)
    data = b"Explicit own temporary original bytes"
    sha = hashlib.sha256(data).hexdigest()
    identity = uuid4()
    reference = ObjectRef(
        identity, 1, sha, len(data), "text/plain", f"originals/{identity.hex}/v1/{sha}"
    )

    class ControlledStore:
        def read_original(self, reference):
            if change in {"issuer", "authority"}:
                state["authority_epoch"] += 1
            elif change == "retained_issuer":
                state["retained_epoch"] += 1
            elif change == "ledger":
                state["ledger"] = "changed"
            elif change == "source":
                state["source"] = "changed"
            elif change == "reads":
                state["reads"] = [{"artifact_id": str(uuid4()), "expected_revision": 1}]
            return data

    assert (
        service._read_bytes(
            ControlledStore(), reference, work.run.scope.tenant_id, work.run.scope.product_id
        )
        == data
    )
    ctx = Context(work.run.scope.tenant_id, work.actor, work.actor)
    if change:
        with pytest.raises(DomainError) as error:
            service._refresh_phase_proofs(
                None, ctx, work.run.scope.product_id, "test.results.import", bound
            )
        assert error.value.reason == "SOURCE_STALE" and not work.recorded
    else:
        service._refresh_phase_proofs(
            None, ctx, work.run.scope.product_id, "test.results.import", bound
        )


def test_retained_proof_display_clock_and_elapsed_window_do_not_revoke_old_execution():
    value = {
        "current": True,
        "checked_at": "2026-10-02T00:00:00Z",
        "execution_window_elapsed": False,
        "actual_start": {"source": "fixed"},
        "original_start_intent": "a" * 64,
        "reservation": "fixed",
        "required_source_read_set": [],
        "source_nature": "synthetic",
    }
    assert service._retained_stamp(value) == service._retained_stamp(
        {**value, "checked_at": "2026-10-03T00:00:00Z", "execution_window_elapsed": True}
    )
    assert service._retained_stamp(value) != service._retained_stamp(
        {**value, "source_nature": "changed"}
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"final": True},
        {"capture_id": None},
        {"next_owner_id": uuid4()},
        {"tenant_id": uuid4()},
        {"measurements": []},
    ],
)
def test_closed_import_schema_requires_real_capture_or_explicit_final(work, changes):
    raw = dict(
        request_id=work.request.id,
        expected_request_revision=work.request.revision,
        run_id=work.run.id,
        expected_run_revision=work.run.revision,
        capture_id=uuid4(),
        expected_capture_revision=1,
        at=event(work),
        reason="synthetic import",
    )
    with pytest.raises(ValidationError):
        ImportPayload.model_validate({**raw, **changes})


def test_semantic_intent_excludes_only_private_confirmation_tokens(work):
    payload = ImportPayload(
        request_id=work.request.id,
        expected_request_revision=work.request.revision,
        run_id=work.run.id,
        expected_run_revision=work.run.revision,
        final=True,
        actual_end=event(work),
        at=event(work),
        reason="synthetic final empty",
    )
    assert service.semantic(payload) == service.semantic(
        payload.model_copy(update={"confirmation_token": "x" * 30})
    )
    assert service.replay_subject_type(payload) == "test_run"
    computed = ComputePayload(
        **payload.model_dump(
            exclude={
                "confirmation_token",
                "at",
                "actual_end",
                "final",
                "capture_id",
                "expected_capture_revision",
                "incomplete_reason",
                "next_owner_id",
                "sources",
            }
        ),
        expected_basis_sha256="a" * 64,
    )
    assert service.replay_subject_type(computed) == "test_result_projection"


def test_preview_uses_no_new_occupancy_and_masks_only_new_server_clocks(work, monkeypatch):
    content, binding, candidates, measurements = report(work)
    work.proved = [m.id for m in measurements]
    raw = ImportPayload(
        request_id=work.request.id,
        expected_request_revision=work.request.revision,
        run_id=work.run.id,
        expected_run_revision=work.run.revision,
        capture_id=uuid4(),
        expected_capture_revision=1,
        final=True,
        actual_end=event(work),
        at=event(work),
        reason="new result reason",
    )
    ctx = Context(work.run.scope.tenant_id, work.actor, work.actor)
    command = SimpleNamespace(
        operation="test.results.import",
        product_id=work.run.scope.product_id,
        command_id=uuid4(),
        expected_revision=1,
    )
    product = SimpleNamespace(id=command.product_id)
    authority = {
        "scope": work.run.scope.model_dump(mode="json"),
        "authorized": True,
        "qualified": True,
        "roles": ["quality"],
    }
    row = VerificationRunVersion(
        id=uuid4(),
        tenant_id=work.run.scope.tenant_id,
        product_id=work.run.scope.product_id,
        project_id=work.run.scope.project_id,
        build_id=work.run.build.id,
        build_revision=work.run.build.revision,
        request_id=work.run.request_id,
        request_revision=work.run.request_revision,
        run_id=work.run.id,
        revision=work.run.revision,
        status=work.run.status,
        run_snapshot=work.run.model_dump(mode="json"),
        snapshot_sha256=digest(work.run.model_dump(mode="json")),
        authority_snapshot=authority,
        input_snapshot={"original_start_intent": "a" * 64},
        operation="test.run.start",
        intent_digest="a" * 64,
        execution_plan=work.plan.model_dump(mode="json"),
        plan_sha256=digest(work.plan.model_dump(mode="json")),
        sources=[],
        required_source_read_set=[],
        created_at=work.run.actual_start.received_at,
    )
    bound = service.Bound(
        SimpleNamespace(id=uuid4()),
        work.request,
        row,
        work.run,
        work.plan,
        authority,
        {"current": True},
        [],
        [],
        {},
        {uuid4(): (content, binding)},
        measurements,
        {m.id: verify_measurement(content, binding, m, work.run) for m in measurements},
        SimpleNamespace(observations=[c.model_dump(mode="json") for c in candidates]),
    )
    monkeypatch.setattr(service, "_load", lambda *_: bound)
    monkeypatch.setattr(service, "_guards", lambda *_: None)
    monkeypatch.setattr(service, "_new_write", lambda *_: None)
    original_created_at = work.now.isoformat()
    monkeypatch.setattr(
        service,
        "_request_view",
        lambda *_: {
            "id": str(bound.request_row.id),
            "revision": work.request.revision,
            "status": work.request.status,
            "reason": "old reason",
            "created_at": original_created_at,
            "zero_occupancy": False,
            "request_snapshot": work.request.model_dump(mode="json"),
        },
    )
    monkeypatch.setattr(service, "_check_source", lambda *_: None)
    monkeypatch.setattr(service, "now", lambda: work.now)
    pointer = VerificationRunCurrent(
        id=uuid4(),
        tenant_id=work.run.scope.tenant_id,
        product_id=work.run.scope.product_id,
        request_id=work.run.request_id,
        run_id=work.run.id,
        run_version_id=row.id,
        run_revision=row.revision,
    )

    # This preview contract owns clocks and zero new effects. The SQL owner is
    # covered by the real chain; its exact current set still uses real snapshots.
    session = SimpleNamespace(info={"read_snapshot": True}, scalar=lambda _: None)
    current_reads = []

    def current_runs(s, context, product_id, request_id, *, lock=False):
        assert s is session and context is ctx and not lock
        assert (product_id, request_id) == (work.run.scope.product_id, work.run.request_id)
        current_reads.append((pointer, row))
        return ((pointer, row),)

    monkeypatch.setattr(service.launch, "_currents_for_request", current_runs)
    first = service.preview_view(session, ctx, command, product, raw)
    work.now += timedelta(minutes=1)
    second = service.preview_view(session, ctx, command, product, raw)
    assert digest(first) == digest(second)
    assert first["after"]["request"]["reason"] == raw.reason
    assert first["after"]["request"]["zero_occupancy"] is False
    assert first["after"]["run"]["zero_occupancy"] is False
    assert first["after"]["run"]["run_snapshot"]["final_result"]["received_at"] is None
    assert first["after"]["run"]["run_snapshot"][
        "actual_start"
    ] == work.run.actual_start.model_dump(mode="json")
    assert first["after"]["occupancy_effect"] == "none_retain_original_start_and_consumption"
    assert current_reads == [(pointer, row), (pointer, row)]
    assert not work.recorded
