"""Exact readable Run/event/measurement proof for the quality host.

This bridge reads archived result truth and retained execution. It does not
reserve, consume, grant a role, choose a policy, mutate a Run or create an Issue.
"""

import hashlib
import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select

from pdos_next.database import require_context
from pdos_next.domain.measurement_evidence.verifier import verify_measurement
from pdos_next.domain.quality_execution.ports import FixedQualityResult, FixedQualityScope
from pdos_next.domain.quality_issues.ports import VerifiedRun
from pdos_next.domain.test_resources.retained import _caller as retained_caller
from pdos_next.domain.test_resources.retained import inspect_retained_execution
from pdos_next.domain.verification_front import service as front
from pdos_next.domain.verification_handoff import service as physical
from pdos_next.domain.verification_launch import service as launch
from pdos_next.domain.verification_launch.models import VerificationRunVersion
from pdos_next.domain.verification_results import service as results
from pdos_next.domain.verification_results.models import TestResultProjection
from pdos_next.errors import DomainError
from pdos_next.models import Outbox, Receipt
from pdos_next.request_proof import request_proof, snapshot_scalar
from pdos_next.schemas.verification.contracts import Measurement, SourceRef
from pdos_next.service import EVENTS, digest, source_for

RESULT_OPERATIONS = frozenset(results.PAYLOADS)
_READ_BATCH = "quality_failure_read_batch"


def _row_seal(row):
    mapper = getattr(type(row), "__mapper__", None)
    values = (
        {attribute.key: getattr(row, attribute.key) for attribute in mapper.column_attrs}
        if mapper is not None
        else vars(row)
    )
    return digest(values)


@dataclass(frozen=True)
class _BatchExecution:
    # An owner-bound execution description, never a saved current flag or result.
    retained_json: str
    expected_stamp: str
    row_seal: str
    request_seal: str
    projection_seal: str
    row_id: UUID
    projection_id: UUID
    caller: str
    runtime: str
    read_set_json: str
    references_json: str
    source_basis_json: str


@dataclass
class _ReadFailureBatch:
    proof: object
    owner_key: tuple
    preparation: bool = False
    entries: dict = field(default_factory=dict)
    snapshots: dict = field(default_factory=dict)
    terminal_access: list = field(default_factory=list)
    closing: bool = False


def _writer_preparation_session(s, ctx, product_id):
    # A held Product gate alone is insufficient after any command mutation or
    # confirmation consumption. This phase only prepares pristine inputs.
    return (
        not getattr(s, "info", {}).get("read_snapshot")
        and results._held_read_session(s, ctx, product_id)
        and request_proof(s).mutation_epoch == 0
    )


def _batch_owner_key(s, ctx, product_id, *, preparation=False):
    eligible = (
        _writer_preparation_session(s, ctx, product_id)
        if preparation
        else results._rr_read_session(s)
    )
    if not eligible:
        raise DomainError("SOURCE_STALE", "品质读取批次的只读事务已变化。")
    require_context(s, ctx)
    proof = request_proof(s)
    return (
        id(s),
        id(s.get_transaction()),
        proof.mutation_epoch,
        digest(vars(ctx)),
        digest(s.info.get("scope")),
        product_id,
        _runtime_stamp(s),
        preparation,
    )


def _active_batch(s, ctx, product_id, *, write=False):
    batch = getattr(s, "info", {}).get(_READ_BATCH)
    if batch is None or (write and not batch.preparation):
        return None
    if batch.owner_key != _batch_owner_key(s, ctx, product_id, preparation=batch.preparation):
        raise DomainError("SOURCE_STALE", "品质读取批次的范围、事务或签发入口已变化。")
    if batch.proof is not request_proof(s):
        raise DomainError("SOURCE_STALE", "品质读取批次不能跨事务复用。")
    return batch


def _batch_run_snapshot(batch, row):
    if batch is None:
        return launch._snapshot(row)
    key = ("run", row.id, _row_seal(row))
    saved = batch.snapshots.get(key)
    if saved is not None:
        run, plan, seal = saved
        if seal == digest([run.model_dump(mode="json"), plan.model_dump(mode="json")]):
            return run, plan
    run, plan = launch._snapshot(row)
    batch.snapshots[key] = (
        run,
        plan,
        digest([run.model_dump(mode="json"), plan.model_dump(mode="json")]),
    )
    return run, plan


def _batch_request_snapshot(batch, row):
    if batch is None:
        return front._snapshot(row)
    key = ("request", row.id, _row_seal(row))
    saved = batch.snapshots.get(key)
    if saved is not None and saved[1] == digest(saved[0].model_dump(mode="json")):
        return saved[0]
    request = front._snapshot(row)
    batch.snapshots[key] = request, digest(request.model_dump(mode="json"))
    return request


def _batch_execution(batch, context, row, request_row, projection):
    if batch is None or context is None or projection is None:
        return None
    entry = batch.entries.get(_prepared_key(context[1], projection))
    if entry is not None and (
        entry.row_seal != _row_seal(row)
        or entry.request_seal != _row_seal(request_row)
        or entry.projection_seal != _row_seal(projection)
    ):
        raise DomainError("SOURCE_STALE", "品质读取批次的固定材料已变化。")
    return entry


def _borrow_execution(entry):
    # Only a matching live batch owner can call this. Its outer successful exit
    # performs the actual complete retained refresh before any view can escape.
    return {**json.loads(entry.retained_json), "current": True}


def _terminal_batch_execution(s, ctx, product_id, entry):
    launch._human(s, ctx, product_id)
    caller, _ = retained_caller(s, ctx, product_id, write=False)
    row = launch._row(s, ctx, product_id, VerificationRunVersion, entry.row_id)
    run, _ = launch._snapshot(row)
    request_row = front._version(s, ctx, product_id, row.request_id, row.request_revision)
    request = front._snapshot(request_row)
    projection = results._row(s, ctx, product_id, TestResultProjection, entry.projection_id)
    if (
        caller != entry.caller
        or _row_seal(row) != entry.row_seal
        or _row_seal(request_row) != entry.request_seal
        or _row_seal(projection) != entry.projection_seal
        or run.scope != request.scope
        or run.build != request.build
    ):
        raise DomainError("SOURCE_STALE", "品质读取返回前固定材料或当前消费者已变化。")
    reads, refs = json.loads(entry.read_set_json), json.loads(entry.references_json)
    basis, private = physical._basis(s, ctx, product_id, reads, refs)
    projected_basis, _ = physical._basis(
        s, ctx, product_id, projection.required_source_read_set, projection.sources
    )
    # This deliberately calls the real retained owner, never the deferred bridge
    # refresh. It checks original start, every resource/effect, source and issuer.
    fresh = inspect_retained_execution(s, ctx, product_id, row, write=False)
    refreshed_basis, refreshed_private = physical._basis(s, ctx, product_id, reads, refs)
    if (
        launch._read_evidence(s, ctx, product_id, row) != "current"
        or not fresh["current"]
        or results._retained_stamp(fresh) != entry.expected_stamp
        or basis != json.loads(entry.source_basis_json)
        or refreshed_basis != basis
        or projected_basis != projection.source_basis
        or (row.visibility == "category" and (private or refreshed_private))
        or _runtime_stamp(s) != entry.runtime
    ):
        raise DomainError("SOURCE_STALE", "全部失败原件读取后执行、来源或签发入口已变化。")


@contextmanager
def _failure_batch(s, ctx, product_id, *, preparation, terminal_access=None):
    if terminal_access is not None and (not preparation or not callable(terminal_access)):
        raise TypeError("Quality preparation terminal access must be callable")
    existing = _active_batch(s, ctx, product_id, write=preparation)
    if existing is not None:
        if existing.preparation != preparation:
            raise DomainError("SOURCE_STALE", "品质准备和只读批次不能互借材料。")
        if existing.closing:
            raise DomainError("SOURCE_STALE", "品质批次终核期间不能追加准备或回调。")
        yield
        _active_batch(s, ctx, product_id, write=preparation)
        if terminal_access is not None:
            # The actual outer owner runs all nested access IO before its global
            # issuer/consumer and pure-clock seals. No inner proof can finish it.
            existing.terminal_access.append(terminal_access)
        return
    eligible = (
        _writer_preparation_session(s, ctx, product_id)
        if preparation
        else results._rr_read_session(s)
    )
    if not eligible:
        yield
        if terminal_access is not None:
            clock = terminal_access()
            if clock is not None:
                if not callable(clock):
                    raise TypeError("Quality preparation terminal clock must be callable")
                clock()
        return
    batch = _ReadFailureBatch(
        request_proof(s),
        _batch_owner_key(s, ctx, product_id, preparation=preparation),
        preparation=preparation,
    )
    s.info[_READ_BATCH] = batch
    try:
        yield
        _active_batch(s, ctx, product_id)
        if terminal_access is not None:
            batch.terminal_access.append(terminal_access)
        batch.closing = True
        for entry in batch.entries.values():
            _terminal_batch_execution(s, ctx, product_id, entry)
        clocks = []
        for access in batch.terminal_access:
            clock = access()
            if clock is not None:
                if not callable(clock):
                    raise TypeError("Quality preparation terminal clock must be callable")
                clocks.append(clock)
        # Checking a later Run may revoke an earlier issuer or cross its consumer
        # deadline. No external source IO follows these final global boundaries.
        _active_batch(s, ctx, product_id)
        for entry in batch.entries.values():
            caller, _ = retained_caller(s, ctx, product_id, write=False)
            if caller != entry.caller or _runtime_stamp(s) != entry.runtime:
                raise DomainError("SOURCE_STALE", "品质读取返回前消费者或签发入口已变化。")
        # A later access callback may cross an earlier actor/policy deadline.
        # These host-owned clock checks do no IO and cannot defer another owner.
        for clock in clocks:
            clock()
        _active_batch(s, ctx, product_id)
    finally:
        s.info.pop(_READ_BATCH, None)


@contextmanager
def read_failure_batch(s, ctx, product_id):
    """Prove a whole RR quality read before its constructed view can be returned.

    Selections still inspect actual events, measurements, every original byte
    and source ACL. Only owner-bound immutable execution material is shared;
    distinct precise executions receive one complete terminal retained refresh.
    """
    with _failure_batch(s, ctx, product_id, preparation=False):
        yield


@contextmanager
def prepare_failure_batch(s, ctx, product_id, *, terminal_access=None):
    """Share exact immutable inputs only before a held writer's first mutation.

    The preparation's actual terminal owner uses write=False in a non-RR
    Session, so retained execution still performs all fresh terminal SQL. The
    quality host's terminal_access seals policy/qualification after that final
    IO; returned pure clock checks run after all nested callbacks and callers.
    No preparation state survives into confirmation consumption or _record.
    """
    with _failure_batch(s, ctx, product_id, preparation=True, terminal_access=terminal_access):
        yield


# The configured trusted read port explicitly exposes its separate preparation
# boundary. A plain/custom read context never silently opts writers into reuse.
read_failure_batch.prepare = prepare_failure_batch


def _read_scalar(s, ctx, product_id, query):
    if results._held_read_session(s, ctx, product_id):
        return snapshot_scalar(
            s,
            ("quality-result-row", results._read_query_key(s, ctx, query)),
            query,
            scope_id=product_id,
        )
    return s.scalar(query)


def _projection_for_basis(s, ctx, product_id, run, basis_sha):
    identity = _read_scalar(
        s,
        ctx,
        product_id,
        select(TestResultProjection.id).where(
            TestResultProjection.tenant_id == ctx.tenant_id,
            TestResultProjection.product_id == product_id,
            TestResultProjection.run_id == run.id,
            TestResultProjection.basis_sha256 == basis_sha,
        ),
    )
    if identity is None:
        return None
    return results._row(s, ctx, product_id, TestResultProjection, identity)


@dataclass(frozen=True)
class _PreparedRetained:
    expected_stamp: str
    read_set_json: str


def _prepare_context(s, ctx, product_id, row, run, plan, request_row, runtime, *, write):
    batch = _active_batch(s, ctx, product_id, write=write)
    if batch is None and (write or not results._rr_read_session(s)):
        return None
    # This checks the live consumer's own natural deadline on every selection.
    # The final complete retained owner also checks it after all original-byte IO.
    caller, _ = retained_caller(s, ctx, product_id, write=write)
    proof = request_proof(s)
    key = (
        "quality-prepared-run",
        id(s),
        id(s.get_transaction()),
        proof.mutation_epoch,
        digest(vars(ctx)),
        digest(s.info.get("scope")),
        product_id,
        row.id,
        row.revision,
        row.snapshot_sha256,
        digest(run.model_dump(mode="json")),
        digest(plan.model_dump(mode="json")),
        request_row.id,
        request_row.revision,
        request_row.snapshot_sha256,
        caller,
        runtime,
    )
    return proof, key


def _prepared_key(key, projection):
    # Seal every mapped business field by its ORM property name. The unmapped
    # audience_dependencies column is DB-derived RLS data; every selection still
    # checks its actual RLS scope, source ACL and complete retained owner.
    return (
        *key,
        projection.id,
        projection.revision,
        digest(
            {
                attribute.key: getattr(projection, attribute.key)
                for attribute in TestResultProjection.__mapper__.column_attrs
            }
        ),
    )


def _prepared_retained(s, ctx, product_id, run, basis_sha, projection, context):
    if context is None:
        return None, projection
    proof, key = context
    if ("quality-prepared-index", key) not in proof.scalar_rows:
        return None, projection
    if projection is None:
        try:
            projection = _projection_for_basis(s, ctx, product_id, run, basis_sha)
        except DomainError:
            # Preserve the original full path's ordering of retained/selection errors.
            return None, None
    if projection is None:
        return None, None
    return proof.scalar_rows.get(_prepared_key(key, projection)), projection


def _save_prepared_retained(context, projection, retained):
    if context is None:
        return
    proof, key = context
    proof.scalar_rows[_prepared_key(key, projection)] = _PreparedRetained(
        results._retained_stamp(retained),
        json.dumps(retained["required_source_read_set"], sort_keys=True),
    )
    # This index is not a positive proof: a hit still resolves the actual projection
    # and checks the complete key, all bytes, source basis and final retained owner.
    proof.scalar_rows[("quality-prepared-index", key)] = True


def _runtime_stamp(s):
    engine = s.get_bind()
    value = {
        "professional_enabled": getattr(engine, "_pdos_professional_synthetic", False),
        "security": id(getattr(engine, "_pdos_security_runtime", None)),
        "store": id(getattr(engine, "_pdos_results_store", None)),
        "bridge": id(getattr(engine, "_pdos_quality_result_bridge", None)),
        "refresh": id(getattr(engine, "_pdos_quality_result_refresh", None)),
        "scope": id(getattr(engine, "_pdos_quality_result_scope", None)),
        "read_batch": id(getattr(engine, "_pdos_quality_result_read_batch", None)),
        "prepare_batch": id(getattr(engine, "_pdos_quality_result_prepare_batch", None)),
    }
    for namespace in ("professional", "test_resource", "operational"):
        registry = getattr(engine, f"_pdos_{namespace}_issuers", {})
        value[namespace] = {
            "epochs": getattr(engine, f"_pdos_{namespace}_issuer_epochs", {}),
            "issuers": {key: [id(issuer), issuer.epoch] for key, issuer in registry.items()},
        }
    return digest(value)


def _event_run(s, ctx, product_id, run_id, event_id):
    event = _read_scalar(
        s,
        ctx,
        product_id,
        select(Outbox).where(Outbox.tenant_id == ctx.tenant_id, Outbox.id == event_id),
    )
    receipt = (
        _read_scalar(
            s,
            ctx,
            product_id,
            select(Receipt).where(
                Receipt.tenant_id == ctx.tenant_id,
                Receipt.product_id == product_id,
                Receipt.id == event.receipt_id,
            ),
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


def fixed_failure_scope(s, ctx, product_id, *, run_id, event_id):
    """Select actual event/run/request scope under the caller's RLS identity."""
    launch._human(s, ctx, product_id)
    row, _ = _event_run(s, ctx, product_id, run_id, event_id)
    run, _ = launch._snapshot(row)
    request_row = front._version(s, ctx, product_id, row.request_id, row.request_revision)
    request = front._snapshot(request_row)
    if run.scope != request.scope or run.build != request.build:
        raise DomainError("INTEGRITY_MISMATCH", "原请求与运行范围不能核对。")
    return FixedQualityScope(
        scope=run.scope,
        purpose=request.purpose,
        run_id=run.id,
        run_version_id=row.id,
        run_revision=row.revision,
        event_id=event_id,
    )


def fixed_failure_result(
    s, ctx, product_id, *, run_id, measurement_id, event_id=None, run_revision=None, write=False
):
    """Return verified truth; the quality kernel separately enforces definite fail.

    New delivery pins its archived version through the actual Outbox/Receipt.
    Original Issue reading must give its precise FailureRef Run revision. Neither
    branch substitutes a current Run for the originally selected version.
    """
    launch._human(s, ctx, product_id, write=write)
    batch = _active_batch(s, ctx, product_id, write=write)
    if batch is not None and batch.closing:
        raise DomainError("SOURCE_STALE", "品质批次终核期间不能追加失败材料。")
    runtime_stamp = _runtime_stamp(s)
    if event_id is not None:
        row, projection = _event_run(s, ctx, product_id, run_id, event_id)
        if run_revision is not None and row.revision != run_revision:
            raise DomainError("FAILURE_EVENT_CHANGED", "事件必须绑定原精确运行版本。")
    else:
        if type(run_revision) is not int or run_revision < 3:
            raise DomainError("FAILURE_CONTEXT_MISSING", "回读失败须明确原结果运行版本。", 422)
        row, projection = launch._version(s, ctx, product_id, run_id, run_revision), None
    run, plan = _batch_run_snapshot(batch, row)
    request_row = front._version(s, ctx, product_id, row.request_id, row.request_revision)
    request = _batch_request_snapshot(batch, request_row)
    if run.scope != request.scope or run.build != request.build:
        raise DomainError("INTEGRITY_MISMATCH", "原请求与运行范围不能核对。")
    if launch._read_evidence(s, ctx, product_id, row) != "current":
        raise DomainError("SOURCE_STALE", "原运行依据当前需重核。")
    basis_sha = results._basis_sha(run, plan)
    prepare_context = _prepare_context(
        s, ctx, product_id, row, run, plan, request_row, runtime_stamp, write=write
    )
    if batch is not None:
        # Resolve an archived selection early only after this exact Run already
        # succeeded in the batch. Initial retained/selection error ordering stays
        # unchanged for first selections and unavailable projections.
        if projection is None and any(entry.row_id == row.id for entry in batch.entries.values()):
            try:
                projection = _projection_for_basis(s, ctx, product_id, run, basis_sha)
            except DomainError:
                projection = None
        prepared = _batch_execution(batch, prepare_context, row, request_row, projection)
    else:
        prepared, projection = _prepared_retained(
            s, ctx, product_id, run, basis_sha, projection, prepare_context
        )
    if prepared is None:
        retained = inspect_retained_execution(s, ctx, product_id, row, write=write)
        if not retained["current"]:
            if "FORBIDDEN_SCOPE" in retained["reason_codes"]:
                raise DomainError("FORBIDDEN_SCOPE", "原执行证明不在当前可读范围。", 403)
            raise DomainError(
                "SOURCE_STALE",
                "原实际开测、资源与消费证明已变化。",
                detail={"retained_reasons": retained["reason_codes"]},
            )
        expected_retained_stamp = results._retained_stamp(retained)
        retained_reads = retained["required_source_read_set"]
    else:
        expected_retained_stamp = prepared.expected_stamp
        retained_reads = json.loads(prepared.read_set_json)
        if batch is not None:
            retained = _borrow_execution(prepared)
    records = results._measurement_records(s, ctx, product_id, run)
    if sum(record.id == measurement_id for record in records) != 1:
        raise DomainError("FAILURE_CONTEXT_MISSING", "事件结果没有所选精确测量。", 422)
    if projection is None:
        projection = _projection_for_basis(s, ctx, product_id, run, basis_sha)
        if projection is None:
            raise DomainError("FAILURE_CONTEXT_MISSING", "缺少固定判定投影。", 422)
    projected = launch._row(s, ctx, product_id, VerificationRunVersion, projection.run_version_id)
    projected_run, projected_plan = _batch_run_snapshot(batch, projected)
    # launch._snapshot already recomputes and verifies every deterministic
    # measurement result. Reuse that typed output, rather than compute it again.
    calculated, aggregate = run.computed_results, run.result
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
        retained_reads,
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
    if projected_basis != projection.source_basis or (row.visibility == "category" and private):
        raise DomainError("SOURCE_STALE", "固定结果来源或受众已变化。")
    if (
        batch is not None
        and prepared is not None
        and (
            source_basis != json.loads(prepared.source_basis_json)
            or reads != json.loads(prepared.read_set_json)
            or refs != json.loads(prepared.references_json)
        )
    ):
        raise DomainError("SOURCE_STALE", "同一执行材料的完整来源在批次内已变化。")
    sources = _artifact_refs(s, ctx, product_id, refs)
    for measurement in run.measurements:
        for source in (measurement.source, measurement.method, measurement.equipment):
            if source is not None:
                sources[digest(source.model_dump(mode="json"))] = source
    for item in run.items:
        if item.criterion is not None:
            source = item.criterion.source
            sources[digest(source.model_dump(mode="json"))] = source
    if batch is None:
        fresh = inspect_retained_execution(s, ctx, product_id, row, write=write)
    else:
        _active_batch(s, ctx, product_id)
        caller, _ = retained_caller(s, ctx, product_id, write=False)
        if caller != prepare_context[1][-2]:
            raise DomainError("SOURCE_STALE", "读取原件期间当前消费者已变化。")
        fresh = retained
    refreshed_basis, _ = physical._basis(s, ctx, product_id, reads, refs)
    if (
        not fresh["current"]
        or results._retained_stamp(fresh) != expected_retained_stamp
        or refreshed_basis != source_basis
        or _runtime_stamp(s) != runtime_stamp
    ):
        raise DomainError("SOURCE_STALE", "读取原件期间历史执行或来源已变化。")
    nature = fresh.get("source_nature")
    if nature not in {"real", "synthetic"}:
        raise DomainError("INTEGRATION_REQUIRED", "缺少服务器核定的执行性质。", 503)
    value = FixedQualityResult(
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
    if batch is None:
        _save_prepared_retained(prepare_context, projection, fresh)
    else:
        # No current flag, FixedQualityResult or original bytes are stored. The
        # enclosing owner makes every provisional selection terminally safe.
        material = {key: item for key, item in fresh.items() if key != "current"}
        entry = _BatchExecution(
            retained_json=json.dumps(material, sort_keys=True),
            expected_stamp=expected_retained_stamp,
            row_seal=_row_seal(row),
            request_seal=_row_seal(request_row),
            projection_seal=_row_seal(projection),
            row_id=row.id,
            projection_id=projection.id,
            caller=prepare_context[1][-2],
            runtime=runtime_stamp,
            read_set_json=json.dumps(reads, sort_keys=True),
            references_json=json.dumps(refs, sort_keys=True),
            source_basis_json=json.dumps(source_basis, sort_keys=True),
        )
        batch.entries.setdefault(_prepared_key(prepare_context[1], projection), entry)
    return value


def recheck_fixed_failure_result(s, ctx, product_id, value, *, write=False):
    """Refresh a previously byte-verified proof without further object-store I/O.

    The quality host calls this for every failure after ALL byte reads. The
    runtime fingerprint catches cross-failure issuer revocation even when the
    later retained reader changes a registry while checking a different failure.
    """
    value = FixedQualityResult.model_validate(value)
    launch._human(s, ctx, product_id, write=write)
    batch = _active_batch(s, ctx, product_id, write=write)
    if batch is not None and batch.closing:
        raise DomainError("SOURCE_STALE", "品质批次终核期间不能延后执行复核。")
    if value.scope.tenant_id != ctx.tenant_id or value.scope.product_id != product_id:
        raise DomainError("FORBIDDEN_SCOPE", "固定失败证明不在当前型号范围。", 403)
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
    entry = None
    if batch is not None:
        prepare_context = _prepare_context(
            s,
            ctx,
            product_id,
            row,
            run,
            plan,
            request_row,
            _runtime_stamp(s),
            write=False,
        )
        entry = _batch_execution(batch, prepare_context, row, request_row, projection)
        if entry is not None and entry.expected_stamp != results._retained_stamp(value.retained):
            raise DomainError("SOURCE_STALE", "失败证明不属于本批次已核对的执行材料。")
    fresh = (
        inspect_retained_execution(s, ctx, product_id, row, write=write)
        if entry is None
        else _borrow_execution(entry)
    )
    if (
        launch._read_evidence(s, ctx, product_id, row) != "current"
        or not fresh["current"]
        or results._retained_stamp(fresh) != results._retained_stamp(value.retained)
        or basis != value.source_basis.get("evidence")
        or (row.visibility == "category" and private)
        or _runtime_stamp(s) != value.source_basis.get("runtime_stamp")
    ):
        raise DomainError("SOURCE_STALE", "全部原件读取后失败来源、执行或签发入口已变化。")
    if entry is not None:
        # Source checks may consume time or change an issuer. The real retained
        # expansion is deferred only to the enclosing batch's mandatory exit.
        _active_batch(s, ctx, product_id)
        caller, _ = retained_caller(s, ctx, product_id, write=False)
        if caller != entry.caller:
            raise DomainError("SOURCE_STALE", "失败证明复核期间当前消费者已变化。")
    return value.model_copy(update={"retained": fresh})


@dataclass(frozen=True)
class DirectQualityFailure:
    """Stored failure identity and its immediate Current/result watermarks."""

    scope: object
    purpose: str
    failure: object
    measurement: dict
    projection_id: UUID
    basis_sha256: str
    sources: tuple
    required_source_read_set: tuple
    watermark: dict
    event_ids: tuple
    current: bool = True
    reasons: tuple = ()


def direct_issue_failure(s, ctx, product_id, issue, failure, *, purpose):
    """Read immutable result rows, never re-prove the upstream execution chain."""
    from pdos_next.domain.quality_execution.models import QualityEventFailureLink
    from pdos_next.domain.verification_launch.models import VerificationRunCurrent
    from pdos_next.domain.verification_results.models import MeasurementRecord
    from pdos_next.request_proof import snapshot_get, snapshot_rows

    links = snapshot_rows(
        s,
        ("quality-direct-failure", product_id, issue.scope.project_id, failure.identity),
        select(QualityEventFailureLink)
        .where(
            QualityEventFailureLink.tenant_id == ctx.tenant_id,
            QualityEventFailureLink.product_id == product_id,
            QualityEventFailureLink.project_id == issue.scope.project_id,
            QualityEventFailureLink.failure_identity == failure.identity,
            QualityEventFailureLink.run_revision == failure.run.revision,
            QualityEventFailureLink.measurement_id == failure.measurement_id,
        )
        .order_by(QualityEventFailureLink.id),
        scope_id=product_id,
    )
    if not links or any(
        link.failure != failure.model_dump(mode="json")
        or link.run_id != failure.run.id
        or link.run_revision != failure.run.revision
        or link.measurement_id != failure.measurement_id
        for link in links
    ):
        raise DomainError("INTEGRITY_MISMATCH", "问题未绑定已保存的精确失败来源。")
    link = links[0]
    run = snapshot_get(s, VerificationRunVersion, link.run_version_id, scope_id=product_id)
    measurement = snapshot_get(s, MeasurementRecord, link.measurement_id, scope_id=product_id)
    projection = snapshot_get(s, TestResultProjection, link.projection_id, scope_id=product_id)
    pointer = snapshot_scalar(
        s,
        ("quality-direct-run-current", product_id, failure.run.id),
        select(VerificationRunCurrent).where(
            VerificationRunCurrent.tenant_id == ctx.tenant_id,
            VerificationRunCurrent.product_id == product_id,
            VerificationRunCurrent.run_id == failure.run.id,
        ),
        scope_id=product_id,
    )
    current = (
        snapshot_get(s, VerificationRunVersion, pointer.run_version_id, scope_id=product_id)
        if pointer
        else None
    )
    projected = (
        snapshot_get(s, VerificationRunVersion, projection.run_version_id, scope_id=product_id)
        if projection
        else None
    )
    for row in (run, measurement, projection, current, projected):
        if row is None or (
            row.tenant_id,
            row.product_id,
            row.project_id,
            row.run_id,
            row.request_id,
        ) != (ctx.tenant_id, product_id, issue.scope.project_id, failure.run.id, link.request_id):
            raise DomainError("FORBIDDEN_SCOPE", "失败直接来源不在当前问题范围。", 403)
        if row.visibility == "private" and row.owner_id != ctx.requester_id:
            raise DomainError("FORBIDDEN_SCOPE", "失败直接来源不在当前可读受众。", 403)
    for row in (run, current, projected):
        if row.snapshot_sha256 != digest(row.run_snapshot) or row.plan_sha256 != digest(
            row.execution_plan
        ):
            raise DomainError("INTEGRITY_MISMATCH", "运行不可变材料摘要不一致。")
        raw = row.run_snapshot
        if (
            raw.get("scope") != issue.scope.model_dump(mode="json")
            or raw.get("id") != str(failure.run.id)
            or raw.get("revision") != row.revision
            or raw.get("request_id") != str(link.request_id)
            or raw.get("build") != failure.build.model_dump(mode="json")
        ):
            raise DomainError("INTEGRITY_MISMATCH", "运行直接材料与固定失败范围不一致。")
    if (
        run.revision != failure.run.revision
        or current.revision != pointer.run_revision
        or current.plan_sha256 != run.plan_sha256
        or projection.revision != link.projection_revision
        or projection.basis_sha256 != link.basis_sha256
        or projection.run_sha256 != projected.snapshot_sha256
        or projection.run_revision != projected.revision
        or measurement.revision != link.measurement_revision
        or measurement.measurement_sha256 != digest(measurement.measurement)
        or measurement.sample_id != failure.sample.id
        or measurement.item_id != failure.coverage.item_id
    ):
        raise DomainError("SOURCE_STALE", "问题的直接运行或结果版本已改变。")
    actual = Measurement.model_validate(measurement.measurement)
    if (
        actual.id != failure.measurement_id
        or actual.source != failure.source
        or actual.method != failure.method
        or actual.coverage != failure.coverage
    ):
        raise DomainError("INTEGRITY_MISMATCH", "固定失败与测量直接依据不一致。")
    expected_measurements = [
        m for m in run.run_snapshot["measurements"] if m["id"] == str(actual.id)
    ]
    current_measurements = [
        m for m in current.run_snapshot["measurements"] if m["id"] == str(actual.id)
    ]
    failed = [r for r in projection.computed_results if r.get("measurement_id") == str(actual.id)]
    current_failed = [
        r
        for r in current.run_snapshot.get("computed_results", [])
        if r.get("measurement_id") == str(actual.id)
    ]
    if (
        expected_measurements != [actual.model_dump(mode="json")]
        or current_measurements != expected_measurements
        or len(failed) != 1
        or failed[0].get("result") != "fail"
        or current_failed != failed
    ):
        raise DomainError("SOURCE_STALE", "直接结果摘要已失效，需重核原失败。")
    sources = (failure.criterion, failure.method, failure.source)
    reads = tuple({"artifact_id": str(r.id), "expected_revision": r.revision} for r in sources)
    return DirectQualityFailure(
        scope=issue.scope,
        purpose=purpose,
        failure=failure,
        measurement=actual.model_dump(mode="json"),
        projection_id=projection.id,
        basis_sha256=projection.basis_sha256,
        sources=sources,
        required_source_read_set=reads,
        watermark={
            "failure_identity": failure.identity,
            "links": [
                {"id": str(v.id), "event_id": str(v.event_id), "sha256": _row_seal(v)}
                for v in links
            ],
            "run": {"id": str(run.id), "revision": run.revision, "sha256": run.snapshot_sha256},
            "current_run": {
                "id": str(current.id),
                "revision": current.revision,
                "sha256": current.snapshot_sha256,
            },
            "measurement": {
                "id": str(measurement.id),
                "revision": measurement.revision,
                "sha256": measurement.measurement_sha256,
            },
            "projection": {
                "id": str(projection.id),
                "revision": projection.revision,
                "basis_sha256": projection.basis_sha256,
                "sha256": _row_seal(projection),
            },
        },
        event_ids=tuple(v.event_id for v in links),
    )
