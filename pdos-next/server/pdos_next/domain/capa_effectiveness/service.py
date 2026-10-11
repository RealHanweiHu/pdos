"""Common candidate adapter, with opaque local preview/new-write phases.

No confirmation assignment, Receipt, flush, commit or Issue pointer mutation.
The common consumer must bind before its real False -> True assignment and
capture immediately afterwards. A stored candidate remains indeterminate.
"""

import sys
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from weakref import WeakKeyDictionary

from sqlalchemy import inspect

from pdos_next.contracts import Command
from pdos_next.domain.quality_execution.models import QualityIssueCurrent, QualityIssueVersion
from pdos_next.errors import DomainError
from pdos_next.models import Product
from pdos_next.service import Context, confirmation_for, digest

from . import anchor, candidate_commands, candidate_prepare, candidate_write, fact_atom_storage
from .candidate_anchor_restore import CandidateAnchorRestoreHost
from .fact_consumption import ConsumptionHost

OPERATION = candidate_commands.OPERATION
TIER = candidate_commands.TIER
SUBJECT = candidate_commands.SUBJECT
EVENT = candidate_commands.EVENT
CandidateRecordPayload = candidate_commands.CandidateRecordPayload
semantic = candidate_commands.semantic  # Startup hosts pin this exact function identity.


@dataclass(frozen=True)
class CandidateRuntime:
    module: object
    restore_host: CandidateAnchorRestoreHost
    consumption_host: ConsumptionHost


@dataclass(frozen=True, eq=False, slots=True, weakref_slot=True)
class PreviewPhase:
    prepared: object


@dataclass(frozen=True, eq=False, slots=True, weakref_slot=True)
class WritePhase:
    prepared: object
    proof: object


# Identity registration protects a local call-stack phase, never an authority
# cache. Actual all-owner prepare/refresh and real ConsumptionHost still run.
_PHASES = WeakKeyDictionary()


def _require(value, code="CANDIDATE_COMMON_PHASE_REQUIRED", status=503):
    if not value:
        raise DomainError(code, "缺本次实际候选阶段、共同证明或精确调用绑定。", status)


def _module():
    module = sys.modules[__name__]
    _require(
        module.semantic is candidate_commands.semantic
        and module.CandidateRecordPayload is candidate_commands.CandidateRecordPayload,
        "CANDIDATE_ACTUAL_MODULE_REQUIRED",
    )
    return module


def configure(engine):
    """Trusted startup only; no client callbacks or permission facts accepted."""
    module = _module()
    runtime = CandidateRuntime(
        module, CandidateAnchorRestoreHost(module), ConsumptionHost({OPERATION: module})
    )
    engine._pdos_capa_candidate_runtime = runtime
    return runtime


def _runtime(s):
    runtime = getattr(s.get_bind(), "_pdos_capa_candidate_runtime", None)
    _require(
        type(runtime) is CandidateRuntime
        and runtime.module is _module()
        and type(runtime.restore_host) is CandidateAnchorRestoreHost
        and runtime.restore_host.module is runtime.module
        and type(runtime.consumption_host) is ConsumptionHost
        and runtime.consumption_host.modules.get(OPERATION) is runtime.module,
        "INTEGRATION_REQUIRED",
    )
    return runtime


def _product(s, ctx, product, *, expected=None):
    _require(isinstance(product, Product), "CANDIDATE_ACTUAL_PRODUCT_REQUIRED")
    state = inspect(product)
    _require(
        state.persistent is True
        and state.session is s
        and not state.deleted
        and product not in s.deleted
        and not {"id", "tenant_id", "revision"} & state.unloaded,
        "CANDIDATE_LOADED_PRODUCT_REQUIRED",
    )
    _require(product.tenant_id == ctx.tenant_id, "FORBIDDEN_SCOPE", 403)
    _require(type(product.revision) is int and product.revision > 0)
    if expected is not None:
        _require(product.revision == expected, "VERSION_CONFLICT", 409)
    return (product.id, product.tenant_id, product.revision)


def _command(ctx, command, payload, product_id):
    _require(
        isinstance(ctx, Context)
        and ctx.actor_id == ctx.requester_id
        and ctx.run_id is None
        and isinstance(command, Command)
        and command.operation == OPERATION
        and command.product_id == product_id,
        "FORBIDDEN_SCOPE",
        403,
    )
    checked = candidate_commands._payload(payload)
    _require(candidate_commands._payload(command.payload) == checked)
    return checked


def _reads(command, prepared):
    _require(bool(command.source_read_set), "MISSING_REQUIRED_EVIDENCE", 409)
    _require(
        bool(prepared.required_source_read_set)
        and anchor.canonical_reads(command.source_read_set)
        == anchor.canonical_reads(prepared.required_source_read_set),
        "MISSING_REQUIRED_EVIDENCE",
        409,
    )


def _origin(s, ctx, product_id, payload):
    # This is only a selector. Actual origin/completion/Project/source/failure
    # proof is independently verified by candidate_prepare and anchor_owner.
    pointer = fact_atom_storage._one(
        s,
        QualityIssueCurrent,
        QualityIssueCurrent.tenant_id == ctx.tenant_id,
        QualityIssueCurrent.product_id == product_id,
        QualityIssueCurrent.issue_id == payload.issue_id,
    )
    row = fact_atom_storage._one(
        s,
        QualityIssueVersion,
        QualityIssueVersion.tenant_id == ctx.tenant_id,
        QualityIssueVersion.product_id == product_id,
        QualityIssueVersion.project_id == pointer.project_id,
        QualityIssueVersion.issue_id == payload.issue_id,
        QualityIssueVersion.id == pointer.issue_version_id,
        QualityIssueVersion.revision == pointer.issue_revision,
    )
    _require(
        row.visibility in {"private", "category", "audience"}
        and (row.visibility != "private" or row.owner_id == ctx.requester_id),
        "FORBIDDEN_SCOPE",
        403,
    )
    return anchor.VersionRef(id=row.id, revision=row.revision, snapshot_sha256=row.snapshot_sha256)


def _review(prepared):
    return candidate_write.reviewed_prepared_candidate(prepared)


def _discard(prepared):
    try:
        candidate_prepare.invalidate_prepared_candidate(prepared)
    except DomainError:
        pass


def review(s, ctx, product_id, payload):
    """Actual read-only 13-key review; never a client-provided snapshot."""
    checked = candidate_commands._payload(payload)
    with s.no_autoflush:
        prepared = candidate_prepare.prepare_candidate(
            s, ctx, product_id, checked, origin_ref=_origin(s, ctx, product_id, checked)
        )
        try:
            result = _review(prepared)
            candidate_prepare.require_prepared_candidate_clock(
                s, ctx, product_id, checked, prepared, datetime.now(UTC)
            )
            return result
        finally:
            _discard(prepared)


def validate(s, ctx, command, product, payload, replay=None):
    # Current authorization precedes common replay. Product revision CAS belongs
    # only to preview/new write, so a retained Receipt can remain replayable.
    checked = _command(ctx, command, payload, _product(s, ctx, product)[0])
    with s.no_autoflush:
        prepared = candidate_prepare.prepare_candidate(
            s, ctx, product.id, checked, origin_ref=_origin(s, ctx, product.id, checked)
        )
        try:
            _reads(command, prepared)
            _review(prepared)
            candidate_prepare.require_prepared_candidate_clock(
                s, ctx, product.id, checked, prepared, datetime.now(UTC)
            )
        finally:
            _discard(prepared)


def _binding(s, ctx, command, product, payload, prepared):
    _command(ctx, command, payload, product.id)
    _reads(command, prepared)
    return (
        digest(vars(ctx)),
        digest(command.model_dump(mode="json")),
        _product(s, ctx, product, expected=command.expected_revision),
        digest(_review(prepared)),
        candidate_prepare._runtime(s),
    )


def _register(s, ctx, command, product, payload, phase, runtime=None):
    _PHASES[phase] = (
        s,
        fact_atom_storage._uow(s),
        _binding(s, ctx, command, product, payload, phase.prepared),
        runtime,
    )
    return phase


def _phase(s, ctx, command, product, payload, phase, kind):
    saved = _PHASES.get(phase) if type(phase) is kind else None
    _require(saved is not None and saved[0] is s)
    fact_atom_storage._same_uow(s, saved[1], ctx, saved[2][0])
    _require(_binding(s, ctx, command, product, payload, phase.prepared) == saved[2])
    if saved[3] is not None:
        _require(_runtime(s) is saved[3], "CANDIDATE_ACTUAL_MODULE_REQUIRED")
    return saved


def prepare_preview(s, ctx, command, product, payload):
    checked = _command(ctx, command, payload, _product(s, ctx, product)[0])
    with s.no_autoflush:
        prepared = candidate_prepare.prepare_candidate(
            s, ctx, product.id, checked, origin_ref=_origin(s, ctx, product.id, checked)
        )
        try:
            return _register(s, ctx, command, product, checked, PreviewPhase(prepared))
        except BaseException:
            _discard(prepared)
            raise


def preview_prepared(s, ctx, command, product, payload, phase):
    # Local one-use render. prepare already completed actual all-owner post-IO
    # refresh; no IO or assertion of a cached authority is added in this render.
    try:
        _phase(s, ctx, command, product, payload, phase, PreviewPhase)
        result = deepcopy(_review(phase.prepared))
        candidate_prepare.require_prepared_candidate_clock(
            s, ctx, product.id, payload, phase.prepared, datetime.now(UTC)
        )
        _phase(s, ctx, command, product, payload, phase, PreviewPhase)
        return result
    finally:
        if type(phase) is PreviewPhase and phase in _PHASES:
            del _PHASES[phase]
            _discard(phase.prepared)


def preview_view(s, ctx, command, product, payload):
    return preview_prepared(
        s, ctx, command, product, payload, prepare_preview(s, ctx, command, product, payload)
    )


def prepare_write_review(s, ctx, command, product, payload, proof=None):
    runtime = _runtime(s)
    checked = _command(ctx, command, payload, _product(s, ctx, product)[0])
    if proof is None:
        proof = confirmation_for(
            s, ctx, product.id, OPERATION, product.id, product.revision, checked.confirmation_token
        )
    prepare_write = getattr(candidate_prepare, "prepare_candidate_write", None)
    _require(callable(prepare_write), "INTEGRATION_REQUIRED")
    with s.no_autoflush:
        prepared = prepare_write(s, ctx, command, checked, proof, runtime.restore_host)
        try:
            phase = _register(
                s, ctx, command, product, checked, WritePhase(prepared, proof), runtime
            )
            result = deepcopy(_review(prepared))
            _require(proof.snapshot == result, "CONFIRMATION_SCOPE_CHANGED", 409)
            return phase, result
        except BaseException:
            _discard(prepared)
            raise


def bind_consumption(s, ctx, command, product, payload, phase, proof):
    saved = _phase(s, ctx, command, product, payload, phase, WritePhase)
    _require(phase.proof is proof)
    return saved[3].consumption_host.bind_before_transition(
        s, ctx, command, payload, _module(), proof, reviewed_snapshot=_review(phase.prepared)
    )


def record_consumption(s, ctx, command, product, payload, phase, proof, binding):
    # No SQL and no owner IO before the actual host captures the first clock.
    saved = _PHASES.get(phase) if type(phase) is WritePhase else None
    _require(saved is not None and saved[3] is not None)
    marker = saved[3].consumption_host.capture_after_transition(
        s, ctx, command, payload, _module(), proof, binding=binding
    )
    _phase(s, ctx, command, product, payload, phase, WritePhase)
    _require(phase.proof is proof)
    return marker


def apply_prepared_write(s, ctx, command, product, payload, phase, *, consumption):
    try:
        saved = _phase(s, ctx, command, product, payload, phase, WritePhase)
        _require(type(consumption) is tuple and len(consumption) == 2)
        binding, marker = consumption
        result = candidate_write.apply_prepared_candidate(
            s,
            ctx,
            command,
            product,
            payload,
            phase.prepared,
            consumption_host=saved[3].consumption_host,
            module=_module(),
            proof=phase.proof,
            consumption_binding=binding,
            consumption_marker=marker,
        )
        # No IO follows the actual writer's final owner/proof checks and add.
        # Still reject startup-host/context/UOW replacement during that IO;
        # common owns rollback of a failed pending append.
        fact_atom_storage._same_uow(s, saved[1], ctx, saved[2][0])
        _require(
            _runtime(s) is saved[3]
            and digest(command.model_dump(mode="json")) == saved[2][1]
            and _product(s, ctx, product, expected=command.expected_revision) == saved[2][2]
            and candidate_prepare._runtime(s) == saved[2][4],
            "CANDIDATE_COMMON_PHASE_CHANGED",
            409,
        )
        return result
    finally:
        if type(phase) is WritePhase and phase in _PHASES:
            del _PHASES[phase]
            _discard(phase.prepared)


def apply(s, ctx, command, product, payload):
    raise DomainError("INTEGRATION_REQUIRED", "候选须经实际原锚恢复与共同消费局部协议保存。", 503)


def inputs(s, ctx, product_id, command):
    _require(command.product_id == product_id, "FORBIDDEN_SCOPE", 403)
    product = fact_atom_storage._one(
        s, Product, Product.tenant_id == ctx.tenant_id, Product.id == product_id
    )
    checked = _command(ctx, command, command.payload, product_id)
    _product(s, ctx, product, expected=command.expected_revision)
    result = review(s, ctx, product_id, checked)
    return {
        "operation": OPERATION,
        "allowed": True,
        "required_source_read_set": result["required_source_read_set"],
        "authority": result["authority_snapshot"],
        "review": result,
    }
