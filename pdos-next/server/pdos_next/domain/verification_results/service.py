"""Append results to the retained Run chain; original-byte proof precedes every action.

Capture API: read_capture_report inside its gated transaction, extract_capture outside,
then prepare_capture in a fresh transaction. Host supplies the existing local store;
missing storage/retained-execution ports fail closed. No network, commit or reservation.
"""

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.contracts import Command
from pdos_next.database import category_for_product
from pdos_next.domain.measurement_evidence.schemas import ObservationSelection as SourceSelection
from pdos_next.domain.measurement_evidence.schemas import ReportBinding
from pdos_next.domain.measurement_evidence.verifier import (
    extract_observations,
    fixed_run_sha256,
    verify_measurement,
)
from pdos_next.domain.professional_authority.service import authority_time_current
from pdos_next.domain.verification import rules
from pdos_next.domain.verification.handlers import semantic_digest
from pdos_next.domain.verification.ports import Invocation
from pdos_next.domain.verification_front import service as front
from pdos_next.domain.verification_front.adapters import authority_dto
from pdos_next.domain.verification_front.models import FormalVerificationRequest
from pdos_next.domain.verification_handoff import service as physical
from pdos_next.domain.verification_launch import service as launch
from pdos_next.domain.verification_launch.models import (
    VerificationRunIdentity,
    VerificationRunVersion,
)
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Grant, Principal, Product, now
from pdos_next.object_storage import StorageFailure
from pdos_next.original_security import require_safe
from pdos_next.originals import object_reference, read_registered_bytes, require_original
from pdos_next.request_proof import (
    command_inputs_once,
    scope_is_held,
    snapshot_rows,
    snapshot_scalar,
)
from pdos_next.schemas.verification.contracts import (
    Measurement,
    ResultsSubmit,
    RunDisposition,
    RunReview,
)
from pdos_next.service import digest, source_for

from .adapters import ResultsCommands, kernel
from .models import (
    MeasurementImportCapture,
    MeasurementRecord,
    TestResultActionFact,
    TestResultProjection,
)
from .schemas import CaptureInput, ComputePayload, DispositionPayload, ImportPayload, ReviewPayload

PAYLOADS = {
    "test.results.import": ImportPayload,
    "test.result.compute": ComputePayload,
    "test.run.review": ReviewPayload,
    "test.disposition.decide": DispositionPayload,
}
OP_KEYS = {
    "test.results.import": "results_import",
    "test.result.compute": "result_compute",
    "test.run.review": "run_review",
    "test.disposition.decide": "disposition_decide",
}
RULES_VERSION = "pdos-verification-compute-results-v1"
RULES_SHA256 = hashlib.sha256(Path(rules.__file__).read_bytes()).hexdigest()
EFFECT = "追加核实原值及独立判定/具名结论；保留原执行与消费证明，不新增占用或外发批准。"
deduplicate_subject = {"test_run", "test_result_projection"}


def configure_store(engine, store):
    """Host-only dependency, not an enablement/qualification grant."""
    engine._pdos_results_store = store


def semantic(payload):
    raw = payload.model_dump(mode="json", exclude={"confirmation_token", "approval_token"})
    if "sources" in raw:
        raw["sources"].sort(key=lambda v: json.dumps(v, sort_keys=True))
    if len(json.dumps(raw, ensure_ascii=False).encode()) > 1_000_000:
        raise DomainError("INVALID_PAYLOAD", "结果载荷超过有界上限。", 422)
    return raw


def request_subject(payload):
    return payload.run_id


def replay_subject_type(payload):
    return "test_result_projection" if isinstance(payload, ComputePayload) else "test_run"


def _intent(ctx, command, payload):
    return digest(
        {"operation": command.operation, "actor": ctx.requester_id, "payload": semantic(payload)}
    )


def _row(s, ctx, pid, model, identity):
    return launch._row(s, ctx, pid, model, identity)


def _rr_read_session(s):
    return (
        isinstance(s, Session)
        and s.info.get("read_snapshot")
        and s.in_transaction()
        and not (s.new or s.dirty or s.deleted)
    )


def _held_read_session(s, ctx, pid):
    if not (isinstance(s, Session) and s.in_transaction() and not (s.new or s.dirty or s.deleted)):
        return False
    from pdos_next.database import require_context

    require_context(s, ctx)
    # A writer shares only exact immutable rows under its actual model gate.
    # Business, source-byte and terminal owner checks are never saved here.
    return scope_is_held(s, pid)


def _read_query_key(s, ctx, query):
    compiled = query.compile()
    return digest([vars(ctx), s.info.get("scope"), str(compiled), compiled.params])


def _union(*groups):
    result = {}
    for group in groups:
        for item in group:
            raw = item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            key = str(raw["artifact_id"])
            rev = raw["expected_revision"]
            if key in result and result[key] != rev:
                raise DomainError("SOURCE_STALE", "同一原文不能绑定不同版本。")
            result[key] = rev
    return [{"artifact_id": key, "expected_revision": result[key]} for key in sorted(result)]


def _base(s, ctx, pid, request_id, request_revision, run_id, run_revision, *, write=True):
    launch._human(s, ctx, pid, write=write)
    request_row = front._version(s, ctx, pid, request_id, request_revision)
    request = front._snapshot(request_row)
    front._current(s, ctx, pid, request_id, lock=write)
    launch._current(s, ctx, pid, run_id, lock=write)
    query = select(VerificationRunIdentity).where(
        VerificationRunIdentity.tenant_id == ctx.tenant_id,
        VerificationRunIdentity.product_id == pid,
        VerificationRunIdentity.id == run_id,
    )
    identity = s.scalar(query.with_for_update() if write else query)
    if identity is None or identity.request_id != request_id:
        raise DomainError("FORBIDDEN_SCOPE", "结果必须引用已有同范围Run身份。", 403)
    run_row = launch._version(s, ctx, pid, run_id, run_revision)
    run, plan = launch._snapshot(run_row)
    if run.request_id != request.id or run.build != request.build or run.scope != request.scope:
        raise DomainError("SOURCE_CHANGED", "Run和请求固定范围无法核对。")
    reads = _union(request_row.required_source_read_set, run_row.required_source_read_set)
    refs = physical._merge_refs(request_row.sources, run_row.sources)
    physical._basis(s, ctx, pid, reads, refs)
    return request_row, request, run_row, run, plan, reads, refs


def _read_report(s, ctx, pid, run, plan, artifact_id, artifact_revision, store):
    if store is None:
        raise DomainError("INTEGRATION_REQUIRED", "原件安全存储读取端口未配置。", 503)
    artifact = source_for(s, ctx, pid, artifact_id, artifact_revision)
    if artifact.original_id is None:
        raise DomainError("ORIGINAL_REQUIRED", "测量必须来自不可变原件，派生文本不能替代。")
    original = require_original(s, ctx, pid, artifact.original_id)
    lock = not getattr(s, "info", {}).get("read_snapshot", False)
    epoch, _ = require_safe(s, ctx, original, lock=lock)
    ref = object_reference(original)
    if ref.media_type not in {"text/plain", "application/x-ndjson", "application/jsonl"}:
        raise DomainError("UNSUPPORTED_REPORT", "首版只核验有界原生UTF-8 JSONL报告。", 422)
    if original.status != "parsed":
        raise DomainError("SOURCE_UNAVAILABLE", "原报告尚未形成可定位的固定派生来源。")
    if original.byte_count > 2_000_000:
        raise DomainError("REPORT_LIMIT_EXCEEDED", "原JSONL报告超过首版有界读取上限。", 422)
    content = _read_bytes(store, ref, ctx.tenant_id, pid)
    if (
        hashlib.sha256(content).hexdigest() != original.content_hash
        or len(content) != original.byte_count
    ):
        raise DomainError("INTEGRITY_MISMATCH", "原报告字节完整性无法核对。")
    current_epoch, _ = require_safe(s, ctx, original, lock=lock)
    if current_epoch != epoch:
        raise DomainError("SOURCE_STALE", "读取期间原件安全版本已变化。")
    binding = ReportBinding(
        scope=run.scope,
        run_id=run.id,
        run_revision=run.revision,
        request_id=run.request_id,
        request_revision=run.request_revision,
        run_basis_sha256=fixed_run_sha256(run, plan),
        report={
            "id": artifact.id,
            "revision": artifact.revision,
            "kind": "artifact",
            "position": "measurement-report",
        },
        original={
            "id": ref.id,
            "revision": ref.version,
            "sha256": ref.content_sha256,
            "size": ref.size_bytes,
            "media_type": ref.media_type,
        },
        security_epoch=epoch,
        pairs=tuple(
            {"sample": next(v for v in run.samples if v.id == c.sample_id), "item_id": c.item_id}
            for c in run.coverage
        ),
        execution_plan=plan,
    )
    return content, binding, artifact


def _read_bytes(store, ref, tenant_id, product_id):
    try:
        return read_registered_bytes(store, ref, tenant_id, product_id)
    except StorageFailure as error:
        code = "INTEGRITY_MISMATCH" if error.code == "INTEGRITY_MISMATCH" else "STORAGE_UNAVAILABLE"
        raise DomainError(code, "原件字节不可完整读取，请核对受控原件存储。", 503) from None


@dataclass(frozen=True)
class ReadReport:
    content: bytes
    binding: ReportBinding
    source_basis: dict
    reads: list
    refs: list


@dataclass(frozen=True)
class PreparedCapture:
    report: ReadReport
    observations: tuple
    measurements: tuple


def recover_capture(s, ctx, pid, input):
    """A readable same-intent capture is returned before bytes, extraction or new proof."""
    from pdos_next.database import require_context
    from pdos_next.domain.supply_execution.service import _read_evidence
    from pdos_next.service import require_access

    require_context(s, ctx)
    require_access(s, ctx, pid)
    existing = s.scalar(
        select(MeasurementImportCapture).where(
            MeasurementImportCapture.tenant_id == ctx.tenant_id,
            MeasurementImportCapture.product_id == pid,
            MeasurementImportCapture.owner_id == ctx.requester_id,
            MeasurementImportCapture.capture_key == input.capture_key,
        )
    )
    if existing is None:
        return None
    if existing.input_digest != digest(input.model_dump(mode="json")):
        raise DomainError("DUPLICATE_INTENT_CONFLICT", "捕获编号已绑定不同报告/范围。")
    result = _capture_response(existing)
    result["capture"]["source_status"] = _read_evidence(s, ctx, pid, existing)
    return result


def read_capture_report(s, ctx, pid, input: CaptureInput, store):
    from pdos_next.service import require_access

    require_access(s, ctx, pid)
    _, _, row, run, plan, reads, refs = _base(
        s,
        ctx,
        pid,
        input.request_id,
        input.expected_request_revision,
        input.run_id,
        input.expected_run_revision,
        write=False,
    )
    if run.status != "running":
        raise DomainError("INVALID_STATE", "报告候选必须引用真实运行中的Run。")
    content, binding, artifact = _read_report(
        s, ctx, pid, run, plan, input.report_artifact_id, input.expected_report_revision, store
    )
    if row.visibility == "category" and artifact.visibility != "category":
        raise DomainError("FORBIDDEN_SCOPE", "私有原报告不能扩大到共享Run。", 403)
    reads = _union(
        reads, [{"artifact_id": str(artifact.id), "expected_revision": artifact.revision}]
    )
    basis, private = physical._basis(s, ctx, pid, reads, refs)
    if row.visibility == "category" and private:
        raise DomainError("FORBIDDEN_SCOPE", "私有原件不能扩大到共享结果。", 403)
    return ReadReport(content, binding, basis, reads, refs)


def extract_capture(input: CaptureInput, report: ReadReport):
    selections = tuple(
        SourceSelection.model_validate(v.model_dump(mode="json")) for v in input.selections
    )
    value = extract_observations(report.content, report.binding, selections)
    return PreparedCapture(
        report, value.observations, tuple(v.to_measurement(uuid4()) for v in value.observations)
    )


def prepare_capture(s, ctx, pid, input: CaptureInput, prepared: PreparedCapture):
    existing = recover_capture(s, ctx, pid, input)
    if existing is not None:
        return existing
    if not isinstance(prepared, PreparedCapture):
        raise DomainError("INTEGRATION_REQUIRED", "报告候选须经服务器两阶段核验。", 503)
    store = getattr(s.get_bind(), "_pdos_results_store", None)
    current = read_capture_report(s, ctx, pid, input, store)
    if (
        current.binding != prepared.report.binding
        or current.source_basis != prepared.report.source_basis
    ):
        raise DomainError("SOURCE_STALE", "提取期间Run或原件依据已变化。")
    key = digest(input.model_dump(mode="json"))
    existing = s.scalar(
        select(MeasurementImportCapture).where(
            MeasurementImportCapture.tenant_id == ctx.tenant_id,
            MeasurementImportCapture.product_id == pid,
            MeasurementImportCapture.owner_id == ctx.requester_id,
            MeasurementImportCapture.capture_key == input.capture_key,
        )
    )
    if existing:
        if existing.input_digest != key:
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "捕获编号已绑定不同报告/范围。")
        return _capture_response(existing)
    product = s.get(Product, pid)
    if product.revision != input.expected_product_revision:
        raise DomainError("VERSION_CONFLICT", "产品已变化，请重新核对候选。")
    request_row, _, run_row, _, _, _, _ = _base(
        s,
        ctx,
        pid,
        input.request_id,
        input.expected_request_revision,
        input.run_id,
        input.expected_run_revision,
    )
    _capture_current(s, ctx, pid, request_row, run_row)
    if not prepared.measurements or len(prepared.measurements) != len(prepared.observations):
        raise DomainError("INTEGRITY_MISMATCH", "捕获原值与原件定位不能缺失或错配。")
    for observation, measurement in zip(prepared.observations, prepared.measurements, strict=True):
        verified = verify_measurement(
            current.content, current.binding, measurement, launch._snapshot(run_row)[0]
        )
        if verified.observation != observation:
            raise DomainError("INTEGRITY_MISMATCH", "捕获候选须完全等于核实的原件观测。")
    capture = MeasurementImportCapture(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        product_id=pid,
        project_id=run_row.project_id,
        build_id=run_row.build_id,
        request_id=input.request_id,
        run_id=input.run_id,
        owner_id=ctx.requester_id,
        # Retained measurements keep this immutable proof in their upstream
        # audience. Shared Runs already reject private reports and read sets.
        # Candidate listing and import remain bound to the capturing person.
        visibility=run_row.visibility,
        status="prepared",
        revision=1,
        capture_key=input.capture_key,
        input_digest=key,
        run_version_id=run_row.id,
        run_revision=run_row.revision,
        run_sha256=run_row.snapshot_sha256,
        request_version_id=request_row.id,
        request_revision=request_row.revision,
        input_snapshot={
            "input": input.model_dump(mode="json"),
            "measurements": [v.model_dump(mode="json") for v in prepared.measurements],
        },
        observations=[v.model_dump(mode="json") for v in prepared.observations],
        report_binding=current.binding.model_dump(mode="json"),
        sources=current.refs,
        required_source_read_set=current.reads,
        source_basis=current.source_basis,
        reason=input.reason,
    )
    s.add(capture)
    s.flush()
    return _capture_response(capture)


def _capture_current(s, ctx, pid, request_row, run_row):
    """New capture only; exact same-key history was authorized and returned above."""
    _, current_request = front._current(s, ctx, pid, request_row.request_id, lock=True)
    _, current_run = launch._current(s, ctx, pid, run_id=run_row.run_id, lock=True)
    if (
        current_request is None
        or current_run is None
        or current_request.id != request_row.id
        or current_run.id != run_row.id
    ):
        raise DomainError("VERSION_CONFLICT", "新捕获须绑定当前正式请求与Run版本。")


def _capture_response(row):
    payload = {
        "request_id": str(row.request_id),
        "expected_request_revision": row.request_revision,
        "run_id": str(row.run_id),
        "expected_run_revision": row.run_revision,
        "capture_id": str(row.id),
        "expected_capture_revision": row.revision,
        "final": False,
        "sources": row.sources,
        "reason": row.reason,
    }
    return {
        "capture": {
            "id": str(row.id),
            "revision": row.revision,
            "run_id": str(row.run_id),
            "request_id": str(row.request_id),
            "status": row.status,
            "created_at": row.created_at.isoformat(),
            "observations": row.observations,
            "source_status": "current",
            "applied_action_id": None,
            "applied_run_version_id": None,
            "report_binding": row.report_binding,
            "sources": row.sources,
            "required_source_read_set": row.required_source_read_set,
            "results_import_payload": payload,
        },
        "results_import_payload": payload,
        "required_source_read_set": row.required_source_read_set,
    }


def _projection_basis(run, plan):
    def event(value):
        return value.model_dump(mode="json", exclude={"received_at"}) if value else None

    return {
        "fixed_run_sha256": fixed_run_sha256(run, plan),
        "measurements": [
            v.model_dump(mode="json") for v in sorted(run.measurements, key=lambda v: str(v.id))
        ],
        "actual_end": event(run.actual_end),
        "final_result": event(run.final_result),
        "final": run.final_result is not None,
        "rules_version": RULES_VERSION,
        "rules_sha256": RULES_SHA256,
    }


def _basis_sha(run, plan):
    return digest(_projection_basis(run, plan))


def _retained(s, ctx, pid, run_row):
    from pdos_next.domain.test_resources import service as resources

    function = getattr(resources, "inspect_retained_execution", None)
    if not callable(function):
        raise DomainError("INTEGRATION_REQUIRED", "原Run历史执行与消费证明未接通。", 503)
    value = function(s, ctx, pid, run_row, at=now(), write=False)
    if not isinstance(value, dict) or value.get("current") is not True:
        raise DomainError("RETAINED_EXECUTION_UNAVAILABLE", "原Run执行证明/来源安全无法当前核对。")
    if not value.get("original_start_intent") or not value.get("reservation"):
        raise DomainError("RETAINED_EXECUTION_UNAVAILABLE", "原开测意图与消费证明缺失。")
    return value


@dataclass
class Bound:
    request_row: object
    request: object
    run_row: object
    run: object
    plan: object
    authority: dict
    retained: dict
    reads: list
    refs: list
    source_basis: dict
    reports: dict
    measurements: tuple
    proofs: dict
    capture: object = None
    projection: object = None
    original: object = None


def _report_for_capture(s, ctx, pid, row, run, plan):
    binding = ReportBinding.model_validate(row.report_binding)
    content, current, _ = _read_report(
        s,
        ctx,
        pid,
        run,
        plan,
        binding.report.id,
        binding.report.revision,
        getattr(s.get_bind(), "_pdos_results_store", None),
    )
    if current.run_revision < binding.run_revision or current.model_dump(
        exclude={"run_revision"}
    ) != binding.model_dump(exclude={"run_revision"}):
        raise DomainError("SOURCE_STALE", "原报告、Run固定执行或原件安全版本已变化。")
    basis, _ = physical._basis(s, ctx, pid, row.required_source_read_set, row.sources)
    if basis != row.source_basis:
        raise DomainError("SOURCE_STALE", "原报告捕获的安全依据已变化。")
    return content, binding


def _measurement_records(s, ctx, pid, run):
    fixed = {m.id: m for m in run.measurements}
    query = select(MeasurementRecord).where(
        MeasurementRecord.tenant_id == ctx.tenant_id,
        MeasurementRecord.product_id == pid,
        MeasurementRecord.run_id == run.id,
        MeasurementRecord.id.in_(fixed),
    )
    rows = (
        snapshot_rows(s, (MeasurementRecord, _read_query_key(s, ctx, query)), query, scope_id=pid)
        if _held_read_session(s, ctx, pid)
        else list(s.scalars(query))
    )
    rows = [row for row in rows if row.id in fixed]
    if len(rows) != len(fixed):
        raise DomainError("INTEGRITY_MISMATCH", "固定Run原测量记录缺失。")
    for row in rows:
        if (
            row.measurement_sha256 != digest(row.measurement)
            or Measurement.model_validate(row.measurement) != fixed[row.id]
        ):
            raise DomainError("INTEGRITY_MISMATCH", "原测量记录与Run固定值不一致。")
    return rows


def _measurement_capture(s, ctx, pid, measurement):
    """A readable retained measurement delegates proof access, not candidate ownership.

    The candidate cannot be listed or submitted by a different person. Its
    immutable proof follows the fixed Run audience so a readable formal result
    can recheck it; original Artifact/Original ACL is checked on every read.
    """
    query = select(MeasurementImportCapture).where(
        MeasurementImportCapture.tenant_id == ctx.tenant_id,
        MeasurementImportCapture.product_id == pid,
        MeasurementImportCapture.id == measurement.capture_id,
        MeasurementImportCapture.run_id == measurement.run_id,
        MeasurementImportCapture.request_id == measurement.request_id,
        MeasurementImportCapture.build_id == measurement.build_id,
        MeasurementImportCapture.project_id == measurement.project_id,
    )
    row = (
        snapshot_scalar(
            s,
            (MeasurementImportCapture, _read_query_key(s, ctx, query)),
            query,
            scope_id=pid,
        )
        if _held_read_session(s, ctx, pid)
        else s.scalar(query)
    )
    if row is None:
        raise DomainError("INTEGRITY_MISMATCH", "原测量捕获证明不在同一固定范围。")
    return row


@command_inputs_once
def _load(s, ctx, command, product, payload, *, require_reads=True):
    if command.product_id != product.id or product.tenant_id != ctx.tenant_id:
        raise DomainError("FORBIDDEN_SCOPE", "结果不在当前服务器产品。", 403)
    write = not getattr(s, "info", {}).get("read_snapshot", False)
    if not write:
        from pdos_next.service import require_access

        require_access(s, ctx, product.id, write=True, lock=False)
    row, request, run_row, run, plan, reads, refs = _base(
        s,
        ctx,
        product.id,
        payload.request_id,
        payload.expected_request_revision,
        payload.run_id,
        payload.expected_run_revision,
        write=write,
    )
    authority = front._assess(
        s, ctx, product.id, row.project_id, command.operation, request.purpose, write=write
    )
    _authority_guard(ctx, payload, authority)
    retained = _retained(s, ctx, product.id, run_row)
    reads = _union(
        reads, authority["required_source_read_set"], retained.get("required_source_read_set", [])
    )
    refs = physical._merge_refs(
        refs, [v.model_dump(mode="json") for v in getattr(payload, "sources", ())]
    )
    events = [getattr(payload, "at", None), getattr(payload, "actual_end", None)]
    reads = _union(
        reads,
        [
            {"artifact_id": str(e.source.id), "expected_revision": e.source.revision}
            for e in events
            if e and e.source.kind == "artifact"
        ],
    )
    original = s.scalar(
        select(TestResultActionFact).where(
            TestResultActionFact.tenant_id == ctx.tenant_id,
            TestResultActionFact.product_id == product.id,
            TestResultActionFact.actor_id == ctx.requester_id,
            TestResultActionFact.operation == command.operation,
            TestResultActionFact.intent_digest == _intent(ctx, command, payload),
        )
    )
    reports, proofs = {}, {}
    old = _measurement_records(s, ctx, product.id, run)
    for measurement_row in old:
        capture = _measurement_capture(s, ctx, product.id, measurement_row)
        if capture.id not in reports:
            reports[capture.id] = _report_for_capture(s, ctx, product.id, capture, run, plan)
        content, binding = reports[capture.id]
        verified = verify_measurement(
            content, binding, Measurement.model_validate(measurement_row.measurement), run
        )
        if digest(verified.model_dump(mode="json")) != digest(measurement_row.verified_observation):
            raise DomainError("SOURCE_STALE", "原测量位置/值核验依据已变化。")
        proofs[measurement_row.id] = verified
        reads = _union(reads, measurement_row.required_source_read_set)
        refs = physical._merge_refs(refs, measurement_row.sources)
    captured = None
    new_measurements = ()
    if isinstance(payload, ImportPayload) and payload.capture_id:
        captured = _row(s, ctx, product.id, MeasurementImportCapture, payload.capture_id)
        if (
            captured.owner_id != ctx.requester_id
            or captured.run_id != run.id
            or captured.request_id != request.id
            or captured.revision != payload.expected_capture_revision
            or captured.run_revision != payload.expected_run_revision
            or captured.run_sha256 != run_row.snapshot_sha256
        ):
            raise DomainError("CAPTURE_SCOPE_MISMATCH", "候选并非本次精确Run基准。")
        reports[captured.id] = _report_for_capture(s, ctx, product.id, captured, run, plan)
        content, binding = reports[captured.id]
        new_measurements = tuple(
            Measurement.model_validate(v) for v in captured.input_snapshot["measurements"]
        )
        for measurement in new_measurements:
            proofs[measurement.id] = verify_measurement(content, binding, measurement, run)
        reads = _union(reads, captured.required_source_read_set)
        refs = physical._merge_refs(refs, captured.sources)
    projection = None
    if isinstance(payload, ReviewPayload):
        projection = _row(s, ctx, product.id, TestResultProjection, payload.projection_id)
        if (
            projection.run_id != run.id
            or projection.revision != payload.expected_projection_revision
            or projection.basis_sha256 != payload.expected_basis_sha256
            or projection.basis_sha256 != _basis_sha(run, plan)
        ):
            raise DomainError("RESULT_BASIS_CHANGED", "专业决定的固定判定/全部测量摘要已变化。")
        reads = _union(reads, projection.required_source_read_set)
        refs = physical._merge_refs(refs, projection.sources)
    if isinstance(payload, ComputePayload) and payload.expected_basis_sha256 != _basis_sha(
        run, plan
    ):
        raise DomainError("RESULT_BASIS_CHANGED", "计算必须绑定当前完整原值与固定判据。")
    basis, private = physical._basis(s, ctx, product.id, reads, refs)
    if run_row.visibility == "category" and private:
        raise DomainError("FORBIDDEN_SCOPE", "私有资料不能扩大为共享结果。", 403)
    if require_reads:
        supplied = {str(v.artifact_id): v.expected_revision for v in command.source_read_set}
        if any(supplied.get(v["artifact_id"]) != v["expected_revision"] for v in reads):
            raise DomainError(
                "MISSING_REQUIRED_EVIDENCE", "须绑定结果/原件/历史执行/当前专业全部来源。"
            )
    bound = Bound(
        row,
        request,
        run_row,
        run,
        plan,
        authority,
        retained,
        reads,
        refs,
        basis,
        reports,
        new_measurements,
        proofs,
        captured,
        projection,
        original,
    )
    _refresh_phase_proofs(s, ctx, product.id, command.operation, bound)
    return bound


def _retained_stamp(value):
    # A naturally elapsed window does not undo a retained physical effect. Only
    # these two display clocks are excluded; all scope/issuer/source/epoch/ledger
    # facts, fixed Start identities and the complete read-set remain bound.
    return digest(
        {
            key: item
            for key, item in value.items()
            if key not in {"checked_at", "execution_window_elapsed"}
        }
    )


def _refresh_phase_proofs(s, ctx, pid, operation, bound):
    """Recheck mutable host/runtime facts after every original-byte read in this phase.

    Database locks cannot protect an opaque issuer or runtime registry from a host
    revocation during store I/O. No proof is reused across validate/preview/apply.
    Retained resource callbacks run first; final current professional assessment
    follows them, before the kernel or any persistent effect may use the proof.
    """
    try:
        retained = _retained(s, ctx, pid, bound.run_row)
        authority = front._assess(
            s,
            ctx,
            pid,
            bound.request_row.project_id,
            operation,
            bound.request.purpose,
            write=not getattr(s, "info", {}).get("read_snapshot", False),
        )
    except DomainError:
        raise DomainError(
            "SOURCE_STALE", "原件读取期间专业或原执行证明已失效，请重新核对。"
        ) from None
    if digest(authority) != digest(bound.authority) or _retained_stamp(retained) != _retained_stamp(
        bound.retained
    ):
        raise DomainError("SOURCE_STALE", "原件读取期间专业、来源或原消费版本已变化，请重新核对。")
    bound.authority, bound.retained = authority, retained


def _parse_event(line):
    def unique(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("duplicate event key")
            value[key] = item
        return value

    try:
        value = json.loads(line, object_pairs_hook=unique)
        time = datetime.fromisoformat(value["occurred_at"])
        if time.tzinfo is None or time.utcoffset() is None:
            raise ValueError("aware time required")
        value["occurred_at"] = time.astimezone(UTC)
        return value
    except (ValueError, TypeError, KeyError):
        raise DomainError(
            "INVALID_EVENT_EVIDENCE", "结果事件必须为唯一字段/含偏移时间的原JSON。", 422
        ) from None


def _event(s, ctx, pid, bound, payload, event, operation):
    if event.source.kind != "artifact" or event.effective_at is not None:
        raise DomainError(
            "INVALID_EVENT_EVIDENCE", "真实事件须固定原文，不使用生效/计划时钟。", 422
        )
    source = source_for(s, ctx, pid, event.source.id, event.source.revision)
    match = re.fullmatch(r"line:(\d+);quote_sha256:([0-9a-f]{64})", event.source.position)
    lines = source.content.splitlines()
    if match is None or not 1 <= int(match[1]) <= len(lines):
        raise DomainError("INVALID_EVENT_EVIDENCE", "结果事件位置无法核对。", 422)
    line = lines[int(match[1]) - 1]
    if hashlib.sha256(line.encode()).hexdigest() != match[2]:
        raise DomainError("INVALID_EVENT_EVIDENCE", "事件行原值摘要不一致。", 422)
    expected = {
        "request_id": str(bound.request.id),
        "run_id": str(bound.run.id),
        "purpose": bound.request.purpose,
        "operation": operation,
        "occurred_at": event.occurred_at,
        "actor_id": str(ctx.requester_id),
    }
    if isinstance(payload, ReviewPayload) and operation != "test.run.end":
        expected.update(text=payload.text, basis_sha256=payload.expected_basis_sha256)
    if _parse_event(line) != expected or event.occurred_at > now():
        raise DomainError("INVALID_EVENT_EVIDENCE", "事件事实未绑定本Run/本人/目的/真实时间。", 422)


def _authority_guard(ctx, payload, a):
    roles = {"quality", "test"} if isinstance(payload, ImportPayload) else {"quality"}
    if (
        a.get("authorized") is not True
        or a.get("subject_id") != str(ctx.requester_id)
        or not roles.intersection(a.get("roles", ()))
    ):
        raise DomainError("FORBIDDEN_OPERATION", "结果办理职责未授权。", 403)
    if a.get("qualified") is not True or not authority_time_current(a, now()):
        raise DomainError("QUALIFICATION_REQUIRED", "当前本人缺少该Run用途的结果办理资格。", 403)


def _guards(s, ctx, command, product, payload, bound):
    _authority_guard(ctx, payload, bound.authority)
    if hasattr(payload, "at"):
        _event(s, ctx, product.id, bound, payload, payload.at, command.operation)
    if isinstance(payload, ImportPayload) and payload.actual_end:
        _event(s, ctx, product.id, bound, payload, payload.actual_end, "test.run.end")
    if getattr(payload, "next_owner_id", None):
        physical._assignee(s, ctx, product.id, bound.request_row.project_id, payload.next_owner_id)
    if bound.original:
        basis, _ = physical._basis(
            s, ctx, product.id, bound.original.required_source_read_set, bound.original.sources
        )
        if (
            basis != bound.original.source_basis
            or not front._recheck(
                s, ctx, product.id, bound.original.project_id, bound.original.authority_snapshot
            )["current"]
        ):
            raise DomainError("SOURCE_STALE", "原结果办理的来源或具名专业事实已失效。")


def validate(s, ctx, command, product, payload):
    bound = _load(s, ctx, command, product, payload)
    _guards(s, ctx, command, product, payload, bound)


def _new_write(s, ctx, command, product, payload, bound):
    if command.expected_revision != product.revision:
        raise DomainError("VERSION_CONFLICT", "型号版本已变化。")
    lock = not getattr(s, "info", {}).get("read_snapshot", False)
    request_pointer, request = front._current(s, ctx, product.id, payload.request_id, lock=lock)
    run_pointer, run = launch._current(s, ctx, product.id, run_id=payload.run_id, lock=lock)
    if request.id != bound.request_row.id or run.id != bound.run_row.id:
        raise DomainError("VERSION_CONFLICT", "Run或正式请求已有后继版本。")
    if isinstance(payload, ImportPayload):
        if bound.run.status != "running":
            raise DomainError("INVALID_STATE", "仅运行中的Run可追加部分/最终结果。")
        if rules.pairs(tuple(v.coverage for v in bound.measurements)) & rules.pairs(
            tuple(v.coverage for v in bound.run.measurements)
        ):
            raise DomainError("MEASUREMENT_ALREADY_RECORDED", "已记录原读数不能改ID重新导入。")
        pending = rules.pairs(bound.run.coverage) - rules.pairs(
            tuple(v.coverage for v in bound.run.measurements + bound.measurements)
        )
        if (
            not payload.final
            and pending
            and (not payload.incomplete_reason or not payload.next_owner_id)
        ):
            raise DomainError(
                "PARTIAL_RESPONSIBILITY_REQUIRED", "部分返回的缺项须有原因与下一责任人。", 422
            )
    if isinstance(payload, DispositionPayload) and bound.run.status != "reviewed":
        raise DomainError("INVALID_STATE", "处置须先有具名专业复核。")
    if (
        isinstance(payload, ReviewPayload)
        and not isinstance(payload, DispositionPayload)
        and bound.run.status != "results_pending"
    ):
        raise DomainError("INVALID_STATE", "专业复核须先完整最终返回。")
    return request_pointer, run_pointer


def _payload_kernel(payload, bound):
    if isinstance(payload, ImportPayload):
        return ResultsSubmit(
            measurements=bound.measurements,
            at=payload.at,
            final=payload.final,
            actual_end=payload.actual_end,
            incomplete_reason=payload.incomplete_reason,
            next_owner_id=payload.next_owner_id,
        )
    return (RunDisposition if isinstance(payload, DispositionPayload) else RunReview)(
        text=payload.text, at=payload.at
    )


def _check_source(s, ctx, pid, bound, scope, source, purpose):
    if scope != bound.run.scope:
        raise DomainError("FORBIDDEN_SCOPE", "测量证据跨越固定Run范围。", 403)
    if source.kind == "artifact":
        # JSONL locators are in immutable original bytes, not derived Artifact lines.
        for content, binding in bound.reports.values():
            if source.id == binding.report.id and source.revision == binding.report.revision:
                match = re.fullmatch(r"line:(\d+);quote_sha256:([0-9a-f]{64})", source.position)
                lines = content.decode("utf-8").splitlines()
                if (
                    match
                    and 1 <= int(match[1]) <= len(lines)
                    and hashlib.sha256(lines[int(match[1]) - 1].encode()).hexdigest() == match[2]
                ):
                    return
                raise DomainError("SOURCE_CHANGED", "原测量JSONL行位置或原值摘要已变化。")
        artifact = source_for(s, ctx, pid, source.id, source.revision)
        match = re.fullmatch(r"line:(\d+);quote_sha256:([0-9a-f]{64})", source.position)
        lines = artifact.content.splitlines()
        if (
            match
            and 1 <= int(match[1]) <= len(lines)
            and hashlib.sha256(lines[int(match[1]) - 1].encode()).hexdigest() == match[2]
        ):
            return
        raise DomainError("SOURCE_UNAVAILABLE", "结果引用的原文位置未核对。")
    fixed = [
        item
        for i in bound.run.items
        for item in (
            i.drawing,
            i.method,
            i.criterion_source,
            i.criterion.source if i.criterion else None,
        )
    ]
    fixed.extend(v.source for v in bound.request.documents if v.source)
    if bound.run.execution:
        fixed.extend((bound.run.execution.equipment, bound.run.execution.calibration))
    if source in fixed and bound.retained.get("current") is True:
        return
    raise DomainError("SOURCE_UNAVAILABLE", "领域方法/设备引用不在已核对的固定执行证明。")


def _kernel(s, ctx, command, product, payload, bound, save, *, accepted=False):
    authority = authority_dto(bound.authority, ctx.requester_id, now())
    # The request parent is already serialized by _base. Only current immutable
    # siblings participate; history cannot multiply coverage or mark completion.
    siblings = tuple(
        launch._snapshot(row)[0]
        for _, row in launch._currents_for_request(
            s,
            ctx,
            product.id,
            bound.request.id,
            lock=not s.info.get("read_snapshot", False),
        )
    )
    if any(run.scope != bound.run.scope or run.build != bound.run.build for run in siblings):
        raise DomainError("INTEGRITY_MISMATCH", "同请求Run集合的固定范围无法核对。")
    commands = ResultsCommands(
        authority,
        bound.request,
        save,
        accepted_confirmation=accepted,
        fixed_run=bound.run,
        fixed_runs=siblings,
    )

    def original(scope, measurement, run):
        proof = bound.proofs.get(measurement.id)
        if (
            scope != bound.run.scope
            or run.id != bound.run.id
            or proof is None
            or proof.measurement != measurement
        ):
            raise DomainError("INTEGRITY_MISMATCH", "测量原值尚未由固定原件证明。")

    def retained(scope, run):
        if (
            scope != bound.run.scope
            or run.id != bound.run.id
            or bound.retained.get("current") is not True
        ):
            raise DomainError("RETAINED_EXECUTION_UNAVAILABLE", "原Run消费归属未证明。")

    return kernel(
        commands,
        bound.run.build,
        lambda *args: _check_source(s, ctx, product.id, bound, *args),
        original,
        retained,
    )


def _invocation(command, payload, value):
    return Invocation(
        command_id=command.command_id,
        operation=command.operation,
        subject_id=payload.run_id,
        expected_revision=payload.expected_run_revision,
        semantic_digest=semantic_digest(value),
    )


def _projection(s, ctx, product, bound, run_row, run):
    sha = _basis_sha(run, bound.plan)
    row = s.scalar(
        select(TestResultProjection).where(
            TestResultProjection.tenant_id == ctx.tenant_id,
            TestResultProjection.product_id == product.id,
            TestResultProjection.run_id == run.id,
            TestResultProjection.basis_sha256 == sha,
        )
    )
    if row:
        return row
    computed, result = rules.compute_results(
        run, run.measurements, final=run.final_result is not None
    )
    row = TestResultProjection(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        product_id=product.id,
        project_id=run_row.project_id,
        build_id=run_row.build_id,
        request_id=run.request_id,
        run_id=run.id,
        revision=1,
        owner_id=run_row.owner_id,
        visibility=run_row.visibility,
        status="computed",
        run_version_id=run_row.id,
        run_revision=run.revision,
        run_sha256=run_row.snapshot_sha256,
        basis_sha256=sha,
        rules_version=RULES_VERSION,
        rules_sha256=RULES_SHA256,
        input_snapshot=_projection_basis(run, bound.plan),
        result=result,
        computed_results=[v.model_dump(mode="json") for v in computed],
        sources=bound.refs,
        required_source_read_set=bound.reads,
        source_basis=bound.source_basis,
    )
    s.add(row)
    s.flush()
    return row


def _record(s, ctx, command, product, payload, bound, pointers, mutation):
    request_pointer, run_pointer = pointers
    previous, old = bound.run_row, bound.request_row
    request_row = old
    if mutation.request.revision != bound.request.revision:
        request_row = FormalVerificationRequest(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            product_id=product.id,
            project_id=old.project_id,
            build_id=old.build_id,
            build_revision=old.build_revision,
            request_id=old.request_id,
            revision=mutation.request.revision,
            previous_request_id=old.id,
            previous_revision=old.revision,
            owner_id=old.owner_id,
            visibility=old.visibility,
            status=mutation.request.status,
            operation=command.operation,
            preparation_id=old.preparation_id,
            preparation_revision=old.preparation_revision,
            preparation_sha256=old.preparation_sha256,
            purpose=old.purpose,
            request_snapshot=mutation.request.model_dump(mode="json"),
            input_snapshot=deepcopy(old.input_snapshot),
            snapshot_sha256=digest(mutation.request.model_dump(mode="json")),
            sources=bound.refs,
            required_source_read_set=bound.reads,
            authority_snapshot=bound.authority,
            intent_digest=_intent(ctx, command, payload),
            reason=payload.reason,
        )
        s.add(request_row)
        s.flush()
        request_pointer.request_version_id, request_pointer.request_revision = (
            request_row.id,
            request_row.revision,
        )
    raw = deepcopy(previous.input_snapshot)
    # Retain the original launch input/reservation/binding. A result intent never
    # becomes the proof of the earlier physical effect.
    raw["result_input"] = semantic(payload)
    raw["original_start_intent"] = bound.retained["original_start_intent"]
    run = mutation.run
    row = VerificationRunVersion(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        product_id=product.id,
        project_id=previous.project_id,
        build_id=previous.build_id,
        build_revision=previous.build_revision,
        request_id=previous.request_id,
        request_version_id=previous.request_version_id,
        request_revision=previous.request_revision,
        run_id=previous.run_id,
        revision=run.revision,
        previous_run_version_id=previous.id,
        previous_revision=previous.revision,
        owner_id=previous.owner_id,
        writer_id=ctx.requester_id,
        visibility=previous.visibility,
        status=run.status,
        operation=command.operation,
        run_snapshot=run.model_dump(mode="json"),
        execution_plan=previous.execution_plan,
        plan_sha256=previous.plan_sha256,
        input_snapshot=raw,
        snapshot_sha256=digest(run.model_dump(mode="json")),
        sources=bound.refs,
        required_source_read_set=bound.reads,
        source_basis=bound.source_basis,
        authority_snapshot=bound.authority,
        intent_digest=_intent(ctx, command, payload),
        reason=payload.reason,
    )
    s.add(row)
    s.flush()
    run_pointer.run_version_id, run_pointer.run_revision = row.id, row.revision
    if isinstance(payload, ImportPayload):
        samples = {v.id: v for v in run.samples}
        for measurement in bound.measurements:
            sample = samples[measurement.coverage.sample_id]
            s.add(
                MeasurementRecord(
                    id=measurement.id,
                    tenant_id=ctx.tenant_id,
                    product_id=product.id,
                    project_id=row.project_id,
                    build_id=row.build_id,
                    request_id=row.request_id,
                    run_id=row.run_id,
                    revision=1,
                    owner_id=row.owner_id,
                    visibility=row.visibility,
                    status="recorded",
                    run_version_id=row.id,
                    run_revision=row.revision,
                    sample_id=sample.id,
                    sample_revision=sample.revision,
                    actual_configuration_id=sample.actual_configuration.id,
                    actual_configuration_revision=sample.actual_configuration.revision,
                    item_id=measurement.coverage.item_id,
                    capture_id=bound.capture.id,
                    measurement=measurement.model_dump(mode="json"),
                    measurement_sha256=digest(measurement.model_dump(mode="json")),
                    verified_observation=bound.proofs[measurement.id].model_dump(mode="json"),
                    sources=bound.refs,
                    required_source_read_set=bound.reads,
                    source_basis=bound.source_basis,
                )
            )
        s.flush()
    projection = _projection(s, ctx, product, bound, row, run)
    s.add(
        TestResultActionFact(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            product_id=product.id,
            project_id=row.project_id,
            build_id=row.build_id,
            request_id=row.request_id,
            run_id=row.run_id,
            revision=1,
            owner_id=row.owner_id,
            visibility=row.visibility,
            status="recorded",
            operation=command.operation,
            actor_id=ctx.requester_id,
            intent_digest=_intent(ctx, command, payload),
            request_version_id=old.id,
            request_revision=old.revision,
            next_request_version_id=request_row.id,
            next_request_revision=request_row.revision,
            run_version_id=previous.id,
            run_revision=previous.revision,
            next_run_version_id=row.id,
            next_run_revision=row.revision,
            capture_id=bound.capture.id if bound.capture else None,
            projection_id=projection.id,
            input_snapshot=semantic(payload),
            authority_snapshot=bound.authority,
            event=payload.at.model_dump(mode="json"),
            sources=bound.refs,
            required_source_read_set=bound.reads,
            source_basis=bound.source_basis,
            reason=payload.reason,
        )
    )
    s.flush()
    return row


def apply(s, ctx, command, product, payload):
    bound = _load(s, ctx, command, product, payload)
    _guards(s, ctx, command, product, payload, bound)
    pointers = _new_write(s, ctx, command, product, payload, bound)
    if isinstance(payload, ComputePayload):
        return (
            _projection(s, ctx, product, bound, bound.run_row, bound.run),
            "test_result_projection",
            bound.run_row.visibility,
        )
    saved = []

    def record(mutation):
        row = _record(s, ctx, command, product, payload, bound, pointers, mutation)
        saved.append(row)
        return row

    value = _payload_kernel(payload, bound)
    _kernel(s, ctx, command, product, payload, bound, record, accepted=True).execute(
        _invocation(command, payload, value), value
    )
    return saved[0], "test_run", bound.run_row.visibility


def replay_subject(s, ctx, command, product, payload):
    bound = _load(s, ctx, command, product, payload)
    _guards(s, ctx, command, product, payload, bound)
    if isinstance(payload, ComputePayload):
        return s.scalar(
            select(TestResultProjection).where(
                TestResultProjection.tenant_id == ctx.tenant_id,
                TestResultProjection.product_id == product.id,
                TestResultProjection.run_id == bound.run.id,
                TestResultProjection.basis_sha256 == _basis_sha(bound.run, bound.plan),
            )
        )
    return (
        _row(s, ctx, product.id, VerificationRunVersion, bound.original.next_run_version_id)
        if bound.original
        else None
    )


def _projection_view(row):
    return {
        "id": str(row.id),
        "revision": row.revision,
        "run_id": str(row.run_id),
        "run_version_id": str(row.run_version_id),
        "run_revision": row.run_revision,
        "basis_sha256": row.basis_sha256,
        "result": row.result,
        "computed_results": row.computed_results,
        "input_snapshot": row.input_snapshot,
        "rules_version": row.rules_version,
        "rules_sha256": row.rules_sha256,
        "created_at": row.created_at.isoformat(),
        "sources": row.sources,
        "required_source_read_set": row.required_source_read_set,
    }


def _run_view(row, run, plan, *, current=False, prospective=False):
    view = launch._run_view(row, run, current=current, prospective=prospective)
    view.update(
        basis_sha256=_basis_sha(run, plan),
        current_projection=None,
        capabilities={key: False for key in OP_KEYS.values()},
        authority={},
        authority_snapshot=row.authority_snapshot,
        zero_occupancy=False if run.actual_start else run.status == "planned",
        occupancy=None if run.actual_start else [],
        sample_usage=None if run.actual_start else [],
        occupancy_evaluation="not_evaluated_saved_effects" if run.actual_start else "not_started",
        original_start_intent=row.input_snapshot.get("original_start_intent")
        or (row.intent_digest if row.operation == "test.run.start" else None),
    )
    return view


def _request_view(s, ctx, pid, row, request, *, current=True):
    view = physical._request_view(s, ctx, pid, row, request, current=current)
    view["zero_occupancy"] = request.timeline.actual_start is None
    return view


def _prospective(s, ctx, command, product, payload, bound):
    value = _payload_kernel(payload, bound)
    preview, mutation = _kernel(s, ctx, command, product, payload, bound, lambda _: None)._prepare(
        authority_dto(bound.authority, ctx.requester_id, now()),
        _invocation(command, payload, value),
        value,
    )
    if not preview.allowed:
        raise DomainError("MISSING_REQUIRED_EVIDENCE", "固定结果范围/原值尚未满足。")
    return mutation


def preview_view(s, ctx, command, product, payload):
    bound = _load(s, ctx, command, product, payload)
    _guards(s, ctx, command, product, payload, bound)
    _new_write(s, ctx, command, product, payload, bound)
    before_request = _request_view(s, ctx, product.id, bound.request_row, bound.request)
    before_run = _run_view(bound.run_row, bound.run, bound.plan, current=True)
    projection = bound.projection
    if projection is None:
        projection = s.scalar(
            select(TestResultProjection).where(
                TestResultProjection.tenant_id == ctx.tenant_id,
                TestResultProjection.product_id == product.id,
                TestResultProjection.run_id == bound.run.id,
                TestResultProjection.basis_sha256 == _basis_sha(bound.run, bound.plan),
            )
        )
    before_projection = _projection_view(projection) if projection else None
    after_request, after_run = deepcopy(before_request), deepcopy(before_run)
    run = bound.run
    if not isinstance(payload, ComputePayload):
        mutation = _prospective(s, ctx, command, product, payload, bound)
        run = mutation.run
        if mutation.request.revision != bound.request.revision:
            after_request.update(
                id=None,
                revision=mutation.request.revision,
                status=mutation.request.status,
                previous_request_id=str(bound.request_row.id),
                previous_revision=bound.request.revision,
                reason=payload.reason,
                created_at=None,
                sha256=None,
                request_snapshot=physical._preview_receives(
                    mutation.request.model_dump(mode="json"), bound.request.model_dump(mode="json")
                ),
                timeline=physical._preview_receives(
                    mutation.request.timeline.model_dump(mode="json"),
                    bound.request.timeline.model_dump(mode="json"),
                ),
                zero_occupancy=False,
            )
        after_run.update(
            id=None,
            revision=run.revision,
            status=run.status,
            result=run.result,
            run_snapshot=physical._preview_receives(
                run.model_dump(mode="json"), bound.run.model_dump(mode="json")
            ),
            created_at=None,
            reason=payload.reason,
            basis_sha256=_basis_sha(run, bound.plan),
            previous_run_version_id=str(bound.run_row.id),
            previous_revision=bound.run.revision,
            zero_occupancy=False,
        )
    computed, result = rules.compute_results(
        run, run.measurements, final=run.final_result is not None
    )
    after_projection = (
        before_projection
        if projection and projection.basis_sha256 == _basis_sha(run, bound.plan)
        else {
            "id": None,
            "revision": 1,
            "run_id": str(run.id),
            "run_version_id": None,
            "run_revision": run.revision,
            "basis_sha256": _basis_sha(run, bound.plan),
            "result": result,
            "computed_results": [v.model_dump(mode="json") for v in computed],
            "input_snapshot": _projection_basis(run, bound.plan),
            "created_at": None,
            "rules_version": RULES_VERSION,
            "rules_sha256": RULES_SHA256,
            "sources": bound.refs,
            "required_source_read_set": bound.reads,
        }
    )
    returned = [v.coverage.model_dump(mode="json") for v in bound.measurements]
    present = rules.pairs(tuple(v.coverage for v in run.measurements))
    return {
        "operation": command.operation,
        "effect": EFFECT,
        "before": {"request": before_request, "run": before_run, "projection": before_projection},
        "after": {
            "request": after_request,
            "run": after_run,
            "projection": after_projection,
            "observations": bound.capture.observations if bound.capture else [],
            "coverage": {
                "accepted": [v.model_dump(mode="json") for v in run.coverage],
                "returned": returned,
                "pending": [
                    v.model_dump(mode="json")
                    for v in run.coverage
                    if (v.sample_id, v.item_id) not in present
                ],
            },
            "occupancy_effect": "none_retain_original_start_and_consumption",
            "measurement_effect": "append_verified_original_values"
            if bound.measurements
            else "none",
        },
        "authority": bound.authority,
        "required_source_read_set": bound.reads,
        "reason": payload.reason,
    }


def inputs(s, ctx, product_id, command: Command):
    if command.product_id != product_id or command.operation not in PAYLOADS:
        raise DomainError("FORBIDDEN_SCOPE", "结果输入不在固定产品/操作范围。", 403)
    payload = PAYLOADS[command.operation].model_validate(command.payload)
    product = s.scalar(
        select(Product).where(Product.id == product_id, Product.tenant_id == ctx.tenant_id)
    )
    if product is None:
        raise DomainError("FORBIDDEN_SCOPE", "产品不可见。", 403)
    bound = _load(s, ctx, command, product, payload, require_reads=False)
    blockers = []
    try:
        _guards(s, ctx, command, product, payload, bound)
        _new_write(s, ctx, command, product, payload, bound)
        if not isinstance(payload, ComputePayload):
            _prospective(s, ctx, command, product, payload, bound)
    except DomainError as error:
        if error.status == 403 or error.reason == "SOURCE_UNAVAILABLE":
            raise
        blockers.append({"code": error.reason, "detail": error.message})
    return {
        "operation": command.operation,
        "request_id": str(payload.request_id),
        "run_id": str(payload.run_id),
        "allowed": not blockers,
        "authority": bound.authority,
        "basis_sha256": _basis_sha(bound.run, bound.plan),
        "required_source_read_set": bound.reads,
        "source_status": "current",
        "blockers": blockers,
        "observations": bound.capture.observations if bound.capture else [],
        "occupancy_effect": "none_retain_original_start_and_consumption",
    }


def _report_sources(s, ctx, pid):
    """Only bytes actually read through current original gates get original_line.

    The displayed JSONL fragments are candidate locations, not verified readings or
    professional conclusions. Derived Artifact coordinates are never substituted.
    """
    store = getattr(s.get_bind(), "_pdos_results_store", None)
    if store is None:
        return []
    rows = s.scalars(
        select(Artifact)
        .where(
            Artifact.tenant_id == ctx.tenant_id,
            Artifact.product_id == pid,
            Artifact.original_id.is_not(None),
        )
        .order_by(Artifact.created_at.desc(), Artifact.id)
    ).all()
    result = []
    for row in rows:
        try:
            source_for(s, ctx, pid, row.id, row.revision)
            original = require_original(s, ctx, pid, row.original_id)
            epoch, _ = require_safe(s, ctx, original, lock=False)
            if (
                original.media_type != "text/plain"
                or original.byte_count > 2_000_000
                or original.status != "parsed"
            ):
                continue
            content = _read_bytes(store, object_reference(original), ctx.tenant_id, pid)
            if (
                len(content) != original.byte_count
                or hashlib.sha256(content).hexdigest() != original.content_hash
            ):
                continue
            text = content.decode("utf-8", errors="strict")
            lines = text.splitlines()
            fragments = []
            for number, line in enumerate(lines, 1):
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if not isinstance(raw, dict) or raw.get("format") != "pdos-measurement-jsonl-v1":
                    continue
                fragments.append(
                    {
                        "original_line": number,
                        "fragment": line[:2000],
                        "truncated": len(line) > 2000,
                    }
                )
            current_epoch, _ = require_safe(s, ctx, original, lock=False)
            if current_epoch != epoch or not fragments:
                continue
            result.append(
                {
                    "artifact_id": str(row.id),
                    "artifact_revision": row.revision,
                    "title": row.title,
                    "source_status": "current",
                    "original_id": str(original.id),
                    "original_revision": original.revision,
                    "original_sha256": original.content_hash,
                    "security_epoch": epoch,
                    "lines": fragments,
                    "has_more": False,
                    "verification": "original_bytes_integrity_checked_format_not_verified",
                    "derived_line_not_assumed": True,
                }
            )
        except (DomainError, UnicodeError):
            continue
    return result


def _read_capabilities(s, ctx, pid, row, request_row, run, request, plan, view):
    """Current proofs surround original I/O; no confirmation, write or reservation."""
    from pdos_next.service import require_access

    write_access = True
    try:
        require_access(s, ctx, pid, write=True, lock=False)
    except DomainError as error:
        if error.status != 403:
            raise
        write_access = False
    retained = _retained(s, ctx, pid, row)
    reads = _union(
        row.required_source_read_set,
        request_row.required_source_read_set,
        retained.get("required_source_read_set", []),
    )
    refs = physical._merge_refs(row.sources, request_row.sources)
    reports = {}
    for measurement in _measurement_records(s, ctx, pid, run):
        capture = _measurement_capture(s, ctx, pid, measurement)
        if capture.id not in reports:
            reports[capture.id] = _report_for_capture(s, ctx, pid, capture, run, plan)
        content, binding = reports[capture.id]
        verified = verify_measurement(
            content, binding, Measurement.model_validate(measurement.measurement), run
        )
        if digest(verified.model_dump(mode="json")) != digest(measurement.verified_observation):
            raise DomainError("SOURCE_STALE", "原测量证明与现核实字节不一致。")
    refreshed = _retained(s, ctx, pid, row)
    if _retained_stamp(retained) != _retained_stamp(refreshed):
        raise DomainError("SOURCE_STALE", "原件读取期间原执行或资源证明已变化。")
    retained = refreshed
    for operation, key in OP_KEYS.items():
        authority = front._assess(
            s, ctx, pid, row.project_id, operation, request.purpose, write=False
        )
        view["authority"][key] = authority
        reads = _union(reads, authority["required_source_read_set"])
        state = (
            run.status == "running"
            if key == "results_import"
            else (
                run.status == "results_pending"
                if key == "run_review"
                else run.status == "reviewed"
                if key == "disposition_decide"
                else run.actual_start is not None
            )
        )
        positive = (
            write_access
            and authority.get("authorized") is True
            and authority.get("qualified") is True
            and authority.get("subject_id") == str(ctx.requester_id)
            and authority_time_current(authority, now())
        )
        view["capabilities"][key] = bool(state and positive)
    physical._basis(s, ctx, pid, reads, refs)
    view["required_source_read_set"] = reads
    view["current_evaluation"] = "evaluated_current_retained_execution"
    view["original_start_intent"] = retained["original_start_intent"]
    view["occupancy"], view["sample_usage"] = retained["occupancy"], retained["sample_usage"]
    view["occupancy_evaluation"] = "retained_current_evidence_saved_effects"


def _next_owners(s, ctx, pid, project_id):
    rows = s.scalars(
        select(Principal)
        .join(
            Grant, (Grant.tenant_id == Principal.tenant_id) & (Grant.principal_id == Principal.id)
        )
        .where(
            Principal.tenant_id == ctx.tenant_id,
            Principal.kind == "human",
            Principal.active.is_(True),
            Grant.category_id == category_for_product(pid),
            Grant.can_write.is_(True),
            (Grant.expires_at.is_(None) | (Grant.expires_at > now())),
        )
        .order_by(Principal.id)
    ).all()
    result = []
    for principal in rows:
        try:
            result.append(physical._assignee(s, ctx, pid, project_id, principal.id))
        except DomainError:
            continue
    return result


def list_results(s, ctx, product_id, *, build_id=None, run_id=None):
    launch._human(s, ctx, product_id)
    if build_id is not None:
        build = front._build(s, ctx, product_id, build_id)
        _, _, _, reads = front._linked(s, ctx, product_id, build)
        physical._sources(s, ctx, product_id, reads)
    selected_run = None
    if run_id is not None:
        _, selected_run = launch._current(s, ctx, product_id, run_id=run_id)
        if selected_run is None or (build_id and selected_run.build_id != build_id):
            raise DomainError("FORBIDDEN_SCOPE", "Run不在当前固定Build范围。", 403)
        launch._read_evidence(s, ctx, product_id, selected_run)

    def scoped(model):
        q = select(model).where(model.tenant_id == ctx.tenant_id, model.product_id == product_id)
        if build_id is not None:
            q = q.where(model.build_id == build_id)
        if run_id is not None:
            q = q.where(model.run_id == run_id)
        return q

    run_rows = s.scalars(
        scoped(VerificationRunVersion).order_by(
            VerificationRunVersion.created_at.desc(), VerificationRunVersion.id
        )
    ).all()
    result = {
        "requests": [],
        "runs": [],
        "captures": [],
        "measurements": [],
        "projections": [],
        "actions": [],
        "current_by_request": {},
        "current_by_run": {},
        "reference_samples": [],
        "report_sources": [],
        "next_owners": [],
        "capabilities": {k: False for k in OP_KEYS.values()},
        "has_more": False,
        "unavailable_count": 0,
    }
    requests, run_views, sample_keys, owner_keys = {}, {}, set(), set()
    for row in run_rows:
        try:
            status = launch._read_evidence(s, ctx, product_id, row)
            run, plan = launch._snapshot(row)
            pointer, current_row = launch._current(s, ctx, product_id, run_id=row.run_id)
            current = current_row is not None and current_row.id == row.id
            if row.request_id not in requests:
                request_pointer, request_row = front._current(s, ctx, product_id, row.request_id)
                request_status = launch._read_evidence(s, ctx, product_id, request_row)
                request = front._snapshot(request_row)
                request_view = _request_view(s, ctx, product_id, request_row, request)
                request_view["source_status"] = request_status
                requests[row.request_id] = (request_row, request, request_view)
                result["requests"].append(request_view)
                result["current_by_request"][str(row.request_id)] = {
                    "request_version_id": str(request_row.id),
                    "revision": request_row.revision,
                }
                if row.project_id not in owner_keys:
                    result["next_owners"].extend(_next_owners(s, ctx, product_id, row.project_id))
                    owner_keys.add(row.project_id)
            request_row, request, request_view = requests[row.request_id]
            view = _run_view(row, run, plan, current=current)
            view["source_status"] = status
            if current:
                result["current_by_run"][str(row.run_id)] = {
                    "run_version_id": str(row.id),
                    "revision": row.revision,
                }
                if (
                    status == "current"
                    and request_view["source_status"] == "current"
                    and run.actual_start
                ):
                    try:
                        _read_capabilities(
                            s, ctx, product_id, row, request_row, run, request, plan, view
                        )
                    except DomainError as error:
                        if error.status == 403:
                            raise
                        view["capabilities"] = {k: False for k in OP_KEYS.values()}
                        view["blockers"].append({"code": error.reason, "detail": error.message})
                for sample in run.samples:
                    if sample.id not in sample_keys:
                        from pdos_next.domain.build_execution.models import SampleUnit

                        actual_sample = s.scalar(
                            select(SampleUnit).where(
                                SampleUnit.tenant_id == ctx.tenant_id,
                                SampleUnit.product_id == product_id,
                                SampleUnit.id == sample.id,
                                SampleUnit.build_id == row.build_id,
                            )
                        )
                        if actual_sample is None:
                            raise DomainError(
                                "FORBIDDEN_SCOPE", "固定样件当前显示范围不可见。", 403
                            )
                        result["reference_samples"].append(
                            {
                                "id": str(sample.id),
                                "label": actual_sample.label,
                                "revision": sample.revision,
                                "actual_configuration": sample.actual_configuration.model_dump(
                                    mode="json"
                                ),
                                "cavity": sample.cavity,
                                "fixed_run_reference": True,
                            }
                        )
                        sample_keys.add(sample.id)
            result["runs"].append(view)
            run_views.setdefault(row.run_id, []).append(view)
        except DomainError as error:
            if error.status != 403:
                result["unavailable_count"] += 1
    for model, key in (
        (MeasurementImportCapture, "captures"),
        (MeasurementRecord, "measurements"),
        (TestResultProjection, "projections"),
        (TestResultActionFact, "actions"),
    ):
        query = scoped(model)
        if model is MeasurementImportCapture:
            query = query.where(MeasurementImportCapture.owner_id == ctx.requester_id)
        rows = s.scalars(query.order_by(model.created_at.desc(), model.id)).all()
        for row in rows:
            if row.run_id not in run_views:
                continue
            try:
                status = launch._read_evidence(s, ctx, product_id, row)
                if key == "captures":
                    view = _capture_response(row)["capture"]
                    action = s.scalar(
                        select(TestResultActionFact).where(
                            TestResultActionFact.tenant_id == ctx.tenant_id,
                            TestResultActionFact.product_id == product_id,
                            TestResultActionFact.capture_id == row.id,
                        )
                    )
                    view.update(
                        source_status=status,
                        applied_action_id=str(action.id) if action else None,
                        applied_run_version_id=str(action.next_run_version_id) if action else None,
                    )
                elif key == "projections":
                    view = _projection_view(row)
                    for run_view in run_views[row.run_id]:
                        if run_view["basis_sha256"] == row.basis_sha256:
                            run_view["current_projection"] = {
                                "id": str(row.id),
                                "revision": row.revision,
                                "basis_sha256": row.basis_sha256,
                                "result": row.result,
                            }
                elif key == "measurements":
                    view = {
                        "id": str(row.id),
                        "run_id": str(row.run_id),
                        "revision": row.revision,
                        "run_version_id": str(row.run_version_id),
                        "run_revision": row.run_revision,
                        "measurement": row.measurement,
                        "verified_observation": row.verified_observation,
                        "capture_id": str(row.capture_id),
                        "measurement_sha256": row.measurement_sha256,
                        "sources": row.sources,
                        "required_source_read_set": row.required_source_read_set,
                        "created_at": row.created_at.isoformat(),
                    }
                else:
                    view = {
                        "id": str(row.id),
                        "revision": row.revision,
                        "run_id": str(row.run_id),
                        "operation": row.operation,
                        "actor_id": str(row.actor_id),
                        "input_snapshot": row.input_snapshot,
                        "run_version_id": str(row.run_version_id),
                        "next_run_version_id": str(row.next_run_version_id),
                        "request_version_id": str(row.request_version_id),
                        "next_request_version_id": str(row.next_request_version_id),
                        "projection_id": str(row.projection_id),
                        "event": row.event,
                        "reason": row.reason,
                        "sources": row.sources,
                        "required_source_read_set": row.required_source_read_set,
                        "created_at": row.created_at.isoformat(),
                        "authority_snapshot": row.authority_snapshot,
                    }
                view["source_status"] = status
                result[key].append(view)
            except DomainError as error:
                if error.status != 403:
                    result["unavailable_count"] += 1
    result["report_sources"] = _report_sources(s, ctx, product_id) if result["runs"] else []
    result["next_owners"] = list({v["id"]: v for v in result["next_owners"]}.values())
    return result
