"""Exact readable Run/event/measurement proof for the quality host.

This bridge reads archived result truth and retained execution. It does not
reserve, consume, grant a role, choose a policy, mutate a Run or create an Issue.
"""

import hashlib
from uuid import UUID

from sqlalchemy import select

from pdos_next.domain.measurement_evidence.verifier import verify_measurement
from pdos_next.domain.quality_execution.ports import FixedQualityResult
from pdos_next.domain.quality_issues.ports import VerifiedRun
from pdos_next.domain.test_resources.retained import inspect_retained_execution
from pdos_next.domain.verification import rules
from pdos_next.domain.verification_front import service as front
from pdos_next.domain.verification_handoff import service as physical
from pdos_next.domain.verification_launch import service as launch
from pdos_next.domain.verification_launch.models import VerificationRunVersion
from pdos_next.domain.verification_results import service as results
from pdos_next.domain.verification_results.models import TestResultProjection
from pdos_next.errors import DomainError
from pdos_next.models import Outbox, Receipt
from pdos_next.schemas.verification.contracts import Measurement, SourceRef
from pdos_next.service import EVENTS, digest, source_for

RESULT_OPERATIONS = frozenset(results.PAYLOADS)


def _runtime_stamp(s):
    engine = s.get_bind()
    value = {
        "professional_enabled": getattr(engine, "_pdos_professional_synthetic", False),
        "security": id(getattr(engine, "_pdos_security_runtime", None)),
        "store": id(getattr(engine, "_pdos_results_store", None)),
        "bridge": id(getattr(engine, "_pdos_quality_result_bridge", None)),
        "refresh": id(getattr(engine, "_pdos_quality_result_refresh", None)),
    }
    for namespace in ("professional", "test_resource", "operational"):
        registry = getattr(engine, f"_pdos_{namespace}_issuers", {})
        value[namespace] = {
            "epochs": getattr(engine, f"_pdos_{namespace}_issuer_epochs", {}),
            "issuers": {key: [id(issuer), issuer.epoch] for key, issuer in registry.items()},
        }
    return digest(value)


def _event_run(s, ctx, product_id, run_id, event_id):
    event = s.scalar(select(Outbox).where(Outbox.tenant_id == ctx.tenant_id, Outbox.id == event_id))
    receipt = (
        s.scalar(
            select(Receipt).where(
                Receipt.tenant_id == ctx.tenant_id,
                Receipt.product_id == product_id,
                Receipt.id == event.receipt_id,
            )
        )
        if event
        else None
    )
    if (
        event is None
        or receipt is None
        or receipt.operation not in RESULT_OPERATIONS
        or event.type != EVENTS.get(receipt.operation)
        or event.subject_id != receipt.subject_id
        or event.subject_revision != receipt.subject_revision
        or event.actor_id != receipt.actor_id
        or event.correlation_id != receipt.command_id
        or event.schema_version != 1
    ):
        raise DomainError("FAILURE_EVENT_UNAVAILABLE", "必须选择同范围真实结果事件。", 403)
    projection = None
    if receipt.operation == "test.result.compute":
        if receipt.subject_type != "test_result_projection":
            raise DomainError("INTEGRITY_MISMATCH", "计算事件回执对象无法核对。")
        projection = results._row(s, ctx, product_id, TestResultProjection, receipt.subject_id)
        if projection.run_id != run_id or projection.revision != receipt.subject_revision:
            raise DomainError("FORBIDDEN_SCOPE", "结果事件不属于所选运行。", 403)
        row = launch._row(s, ctx, product_id, VerificationRunVersion, projection.run_version_id)
    else:
        if receipt.subject_type != "test_run":
            raise DomainError("INTEGRITY_MISMATCH", "结果事件回执对象无法核对。")
        row = launch._row(s, ctx, product_id, VerificationRunVersion, receipt.subject_id)
        if row.revision != receipt.subject_revision:
            raise DomainError("INTEGRITY_MISMATCH", "结果事件精确版本无法核对。")
    if row.run_id != run_id:
        raise DomainError("FORBIDDEN_SCOPE", "不能用其他运行事件建立失败身份。", 403)
    return row, projection


def _artifact_refs(s, ctx, product_id, references):
    mapped = {}
    for ref in references:
        source = source_for(s, ctx, product_id, UUID(ref["artifact_id"]), ref["expected_revision"])
        line = ref["line"]
        lines = source.content.splitlines()
        if (
            type(line) is not int
            or not 1 <= line <= len(lines)
            or ref["quote"] not in lines[line - 1]
        ):
            raise DomainError("SOURCE_STALE", "固定出处不能在原文逐字定位。")
        value = SourceRef(
            id=source.id,
            revision=source.revision,
            kind="artifact",
            position=(
                f"line:{line};quote_sha256:{hashlib.sha256(lines[line - 1].encode()).hexdigest()}"
            ),
        )
        mapped[digest(value.model_dump(mode="json"))] = value
    return mapped


def fixed_failure_result(
    s, ctx, product_id, *, run_id, measurement_id, event_id=None, run_revision=None, write=False
):
    """Return verified truth; the quality kernel separately enforces definite fail.

    New delivery pins its archived version through the actual Outbox/Receipt.
    Original Issue reading must give its precise FailureRef Run revision. Neither
    branch substitutes a current Run for the originally selected version.
    """
    launch._human(s, ctx, product_id, write=write)
    runtime_stamp = _runtime_stamp(s)
    if event_id is not None:
        row, projection = _event_run(s, ctx, product_id, run_id, event_id)
        if run_revision is not None and row.revision != run_revision:
            raise DomainError("FAILURE_EVENT_CHANGED", "事件必须绑定原精确运行版本。")
    else:
        if type(run_revision) is not int or run_revision < 3:
            raise DomainError("FAILURE_CONTEXT_MISSING", "回读失败须明确原结果运行版本。", 422)
        row, projection = launch._version(s, ctx, product_id, run_id, run_revision), None
    run, plan = launch._snapshot(row)
    request_row = front._version(s, ctx, product_id, row.request_id, row.request_revision)
    request = front._snapshot(request_row)
    if run.scope != request.scope or run.build != request.build:
        raise DomainError("INTEGRITY_MISMATCH", "原请求与运行范围不能核对。")
    if launch._read_evidence(s, ctx, product_id, row) != "current":
        raise DomainError("SOURCE_STALE", "原运行依据当前需重核。")
    retained = inspect_retained_execution(s, ctx, product_id, row, write=write)
    if not retained["current"]:
        raise DomainError("SOURCE_STALE", "原实际开测、资源与消费证明已变化。")
    records = results._measurement_records(s, ctx, product_id, run)
    if sum(record.id == measurement_id for record in records) != 1:
        raise DomainError("FAILURE_CONTEXT_MISSING", "事件结果没有所选精确测量。", 422)
    basis_sha = results._basis_sha(run, plan)
    if projection is None:
        identity = s.scalar(
            select(TestResultProjection.id).where(
                TestResultProjection.tenant_id == ctx.tenant_id,
                TestResultProjection.product_id == product_id,
                TestResultProjection.run_id == run.id,
                TestResultProjection.basis_sha256 == basis_sha,
            )
        )
        if identity is None:
            raise DomainError("FAILURE_CONTEXT_MISSING", "缺少固定判定投影。", 422)
        projection = results._row(s, ctx, product_id, TestResultProjection, identity)
    projected = launch._row(s, ctx, product_id, VerificationRunVersion, projection.run_version_id)
    projected_run, projected_plan = launch._snapshot(projected)
    calculated, aggregate = rules.compute_results(
        run, run.measurements, final=run.final_result is not None
    )
    if (
        projection.project_id != row.project_id
        or projection.run_id != run.id
        or projection.run_revision != projected.revision
        or projection.run_sha256 != projected.snapshot_sha256
        or projection.basis_sha256 != basis_sha
        or projection.input_snapshot != results._projection_basis(run, plan)
        or results._basis_sha(projected_run, projected_plan) != basis_sha
        or projection.rules_version != results.RULES_VERSION
        or projection.rules_sha256 != results.RULES_SHA256
        or projection.result != aggregate
        or run.result != aggregate
        or projection.computed_results != [value.model_dump(mode="json") for value in calculated]
        or tuple(calculated) != run.computed_results
    ):
        raise DomainError("RESULT_BASIS_CHANGED", "原测量、判据、规则与固定投影不能一致核对。")
    reads = results._union(
        row.required_source_read_set,
        request_row.required_source_read_set,
        projection.required_source_read_set,
        retained["required_source_read_set"],
    )
    refs = physical._merge_refs(row.sources, request_row.sources, projection.sources)
    captured_reports = {}
    for record in records:
        capture = results._measurement_capture(s, ctx, product_id, record)
        if capture.id not in captured_reports:
            captured_reports[capture.id] = results._report_for_capture(
                s, ctx, product_id, capture, run, plan
            )
        content, binding = captured_reports[capture.id]
        observation = verify_measurement(
            content, binding, Measurement.model_validate(record.measurement), run
        )
        if digest(observation.model_dump(mode="json")) != digest(record.verified_observation):
            raise DomainError("SOURCE_STALE", "原值及每字段位置证明已经变化。")
        reads = results._union(reads, record.required_source_read_set)
        refs = physical._merge_refs(refs, record.sources)
    source_basis, private = physical._basis(s, ctx, product_id, reads, refs)
    projected_basis, _ = physical._basis(
        s, ctx, product_id, projection.required_source_read_set, projection.sources
    )
    if projected_basis != projection.source_basis or (row.visibility == "product" and private):
        raise DomainError("SOURCE_STALE", "固定结果来源或受众已变化。")
    sources = _artifact_refs(s, ctx, product_id, refs)
    for measurement in run.measurements:
        for source in (measurement.source, measurement.method, measurement.equipment):
            if source is not None:
                sources[digest(source.model_dump(mode="json"))] = source
    for item in run.items:
        if item.criterion is not None:
            source = item.criterion.source
            sources[digest(source.model_dump(mode="json"))] = source
    fresh = inspect_retained_execution(s, ctx, product_id, row, write=write)
    refreshed_basis, _ = physical._basis(s, ctx, product_id, reads, refs)
    if (
        not fresh["current"]
        or results._retained_stamp(fresh) != results._retained_stamp(retained)
        or refreshed_basis != source_basis
        or _runtime_stamp(s) != runtime_stamp
    ):
        raise DomainError("SOURCE_STALE", "读取原件期间历史执行或来源已变化。")
    nature = fresh.get("source_nature")
    if nature not in {"real", "synthetic"}:
        raise DomainError("INTEGRATION_REQUIRED", "缺少服务器核定的执行性质。", 503)
    return FixedQualityResult(
        scope=run.scope,
        purpose=request.purpose,
        event_id=event_id,
        run_version_id=row.id,
        run_revision=row.revision,
        measurement_id=measurement_id,
        projection_id=projection.id,
        projection_revision=projection.revision,
        basis_sha256=basis_sha,
        rules_version=projection.rules_version,
        rules_sha256=projection.rules_sha256,
        verified=VerifiedRun(run=run, nature=nature),
        visibility=row.visibility,
        owner_id=row.owner_id,
        sources=tuple(sources[key] for key in sorted(sources)),
        required_source_read_set=reads,
        source_basis={
            "evidence": source_basis,
            "run_sha256": row.snapshot_sha256,
            "projection_sha256": digest(projection.input_snapshot),
            "rules_sha256": projection.rules_sha256,
            "event_id": str(event_id) if event_id else None,
            "runtime_stamp": runtime_stamp,
        },
        retained=fresh,
        current=True,
    )


def recheck_fixed_failure_result(s, ctx, product_id, value, *, write=False):
    """Refresh a previously byte-verified proof without further object-store I/O.

    The quality host calls this for every failure after ALL byte reads. The
    runtime fingerprint catches cross-failure issuer revocation even when the
    later retained reader changes a registry while checking a different failure.
    """
    value = FixedQualityResult.model_validate(value)
    launch._human(s, ctx, product_id, write=write)
    if value.scope.tenant_id != ctx.tenant_id or value.scope.product_id != product_id:
        raise DomainError("FORBIDDEN_SCOPE", "固定失败证明不在当前产品范围。", 403)
    row = launch._row(s, ctx, product_id, VerificationRunVersion, value.run_version_id)
    run, plan = launch._snapshot(row)
    projection = results._row(s, ctx, product_id, TestResultProjection, value.projection_id)
    if (
        run != value.verified.run
        or row.snapshot_sha256 != value.source_basis.get("run_sha256")
        or row.project_id != value.scope.project_id
        or row.revision != value.run_revision
        or row.owner_id != value.owner_id
        or row.visibility != value.visibility
        or projection.revision != value.projection_revision
        or projection.run_id != run.id
        or projection.basis_sha256 != value.basis_sha256
        or results._basis_sha(run, plan) != value.basis_sha256
        or digest(projection.input_snapshot) != value.source_basis.get("projection_sha256")
        or projection.rules_version != value.rules_version
        or projection.rules_sha256 != value.rules_sha256
    ):
        raise DomainError("RESULT_BASIS_CHANGED", "固定失败版本或判定投影已变化。")
    if value.event_id is not None:
        event_row, event_projection = _event_run(s, ctx, product_id, run.id, value.event_id)
        if event_row.id != row.id or (
            event_projection is not None and event_projection.id != projection.id
        ):
            raise DomainError("FAILURE_EVENT_CHANGED", "精确失败源事件归属已变化。")
    reads = [item.model_dump(mode="json") for item in value.required_source_read_set]
    request_row = front._version(s, ctx, product_id, row.request_id, row.request_revision)
    refs = physical._merge_refs(row.sources, request_row.sources, projection.sources)
    for record in results._measurement_records(s, ctx, product_id, run):
        refs = physical._merge_refs(refs, record.sources)
    basis, private = physical._basis(s, ctx, product_id, reads, refs)
    fresh = inspect_retained_execution(s, ctx, product_id, row, write=write)
    if (
        launch._read_evidence(s, ctx, product_id, row) != "current"
        or not fresh["current"]
        or results._retained_stamp(fresh) != results._retained_stamp(value.retained)
        or basis != value.source_basis.get("evidence")
        or (row.visibility == "product" and private)
        or _runtime_stamp(s) != value.source_basis.get("runtime_stamp")
    ):
        raise DomainError("SOURCE_STALE", "全部原件读取后失败来源、执行或签发入口已变化。")
    return value.model_copy(update={"retained": fresh})
