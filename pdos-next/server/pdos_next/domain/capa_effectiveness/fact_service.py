"""Public Observation/Review adapter for the existing common transaction.

Only trusted startup supplies the actual material owner. Rule imports have a
separate host-only entry; they never enter this public command registry.
"""

# ruff: noqa: I001
from pdos_next.service import Context, confirmation_for, digest

import sys
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from weakref import WeakKeyDictionary

from pdos_next.contracts import Command
from pdos_next.errors import DomainError

from . import anchor, fact_atom_storage as guards, fact_commands as commands, fact_write as writer
from .fact_consumption import ConsumptionHost

semantic = commands.semantic
OPERATIONS = frozenset({commands.OBSERVATION_OPERATION, commands.REVIEW_OPERATION})


@dataclass(frozen=True)
class FactRuntime:
    module: object
    host: writer.FactWriteHost
    consumption_host: ConsumptionHost


@dataclass(frozen=True, eq=False, slots=True, weakref_slot=True)
class Phase:
    prepared: writer.PreparedFact
    proof: object | None


_PHASES = WeakKeyDictionary()


def _require(value, code="FACT_COMMON_PHASE_REQUIRED", status=503):
    if not value:
        raise DomainError(code, "事实办理缺少当前真实宿主或共同确认绑定。", status)


def _module():
    module = sys.modules[__name__]
    _require(module.semantic is commands.semantic)
    return module


def configure(engine, owner):
    """Startup only. A missing owner is never replaced with an approving stub."""
    module = _module()
    runtime = FactRuntime(
        module, writer.FactWriteHost(owner), ConsumptionHost({op: module for op in OPERATIONS})
    )
    engine._pdos_capa_fact_runtime = runtime
    return runtime


def _runtime(s):
    value = getattr(s.get_bind(), "_pdos_capa_fact_runtime", None)
    _require(
        type(value) is FactRuntime
        and value.module is _module()
        and type(value.host) is writer.FactWriteHost
        and type(value.consumption_host) is ConsumptionHost
        and all(value.consumption_host.modules.get(op) is value.module for op in OPERATIONS),
        "INTEGRATION_REQUIRED",
    )
    return value


def _payload(ctx, command, payload):
    _require(
        isinstance(ctx, Context) and ctx.actor_id == ctx.requester_id and ctx.run_id is None,
        "FORBIDDEN_SCOPE",
        403,
    )
    _require(
        isinstance(command, Command) and command.operation in OPERATIONS, "FORBIDDEN_SCOPE", 403
    )
    kind = "observation" if command.operation == commands.OBSERVATION_OPERATION else "review"
    value = commands.payload_for(kind, payload)
    _require(value == commands.payload_for(kind, command.payload))
    return value


def _review(runtime, prepared):
    return writer.reviewed_fact(prepared, host=runtime.host)


def _reads(command, prepared):
    _require(
        bool(command.source_read_set)
        and anchor.canonical_reads(command.source_read_set)
        == anchor.canonical_reads(prepared.required_source_read_set),
        "MISSING_REQUIRED_EVIDENCE",
        409,
    )


def _discard(runtime, prepared):
    if prepared in runtime.host._phases:
        runtime.host.invalidate(prepared)


def validate(s, ctx, command, product, payload, replay=None):
    runtime, value = _runtime(s), _payload(ctx, command, payload)
    with s.no_autoflush:
        prepared = writer.prepare_fact(s, ctx, product.id, value, host=runtime.host)
        try:
            _reads(command, prepared)
            writer.require_prepared_fact_clock(
                s, ctx, product.id, value, prepared, datetime.now(UTC), host=runtime.host
            )
        finally:
            _discard(runtime, prepared)


def _register(s, ctx, command, product, payload, prepared, proof, runtime):
    writer._product(s, ctx, command, product)
    _reads(command, prepared)
    phase = Phase(prepared, proof)
    _PHASES[phase] = (
        s,
        guards._uow(s),
        digest(vars(ctx)),
        digest(command.model_dump(mode="json")),
        runtime,
        digest(_review(runtime, prepared)),
    )
    return phase


def _phase(s, ctx, command, product, payload, phase):
    saved = _PHASES.get(phase) if type(phase) is Phase else None
    _require(saved is not None and saved[0] is s and _runtime(s) is saved[4])
    guards._same_uow(s, saved[1], ctx, saved[2])
    _payload(ctx, command, payload)
    writer._product(s, ctx, command, product)
    _reads(command, phase.prepared)
    _require(
        digest(command.model_dump(mode="json")) == saved[3]
        and digest(_review(saved[4], phase.prepared)) == saved[5]
    )
    return saved


def prepare_preview(s, ctx, command, product, payload):
    runtime, value = _runtime(s), _payload(ctx, command, payload)
    with s.no_autoflush:
        prepared = writer.prepare_fact(s, ctx, product.id, value, host=runtime.host, new_write=True)
        try:
            return _register(s, ctx, command, product, value, prepared, None, runtime)
        except BaseException:
            _discard(runtime, prepared)
            raise


def preview_prepared(s, ctx, command, product, payload, phase):
    saved = _phase(s, ctx, command, product, payload, phase)
    try:
        _require(phase.proof is None)
        value = deepcopy(_review(saved[4], phase.prepared))
        writer.require_prepared_fact_clock(
            s, ctx, product.id, payload, phase.prepared, datetime.now(UTC), host=saved[4].host
        )
        return value
    finally:
        _PHASES.pop(phase, None)
        _discard(saved[4], phase.prepared)


def preview_view(s, ctx, command, product, payload):
    return preview_prepared(
        s, ctx, command, product, payload, prepare_preview(s, ctx, command, product, payload)
    )


def prepare_write_review(s, ctx, command, product, payload, proof=None):
    runtime, value = _runtime(s), _payload(ctx, command, payload)
    if proof is None:
        token = (
            value.confirmation_token
            if command.operation == commands.OBSERVATION_OPERATION
            else value.approval_token
        )
        proof = confirmation_for(
            s, ctx, product.id, command.operation, product.id, product.revision, token
        )
    with s.no_autoflush:
        prepared = writer.prepare_fact(s, ctx, product.id, value, host=runtime.host, new_write=True)
        try:
            view = deepcopy(_review(runtime, prepared))
            _require(proof.snapshot == view, "CONFIRMATION_SCOPE_CHANGED", 409)
            phase = _register(s, ctx, command, product, value, prepared, proof, runtime)
            return phase, view
        except BaseException:
            _discard(runtime, prepared)
            raise


def bind_consumption(s, ctx, command, product, payload, phase, proof):
    saved = _phase(s, ctx, command, product, payload, phase)
    _require(phase.proof is proof)
    return saved[4].consumption_host.bind_before_transition(
        s,
        ctx,
        command,
        payload,
        _module(),
        proof,
        reviewed_snapshot=_review(saved[4], phase.prepared),
    )


def record_consumption(s, ctx, command, product, payload, phase, proof, binding):
    # Capture is the first action after common False -> True; no SQL first.
    saved = _PHASES.get(phase) if type(phase) is Phase else None
    _require(saved is not None)
    marker = saved[4].consumption_host.capture_after_transition(
        s, ctx, command, payload, _module(), proof, binding=binding
    )
    _phase(s, ctx, command, product, payload, phase)
    _require(phase.proof is proof)
    return marker


def apply_prepared_write(s, ctx, command, product, payload, phase, *, consumption):
    saved = _phase(s, ctx, command, product, payload, phase)
    try:
        _require(type(consumption) is tuple and len(consumption) == 2 and phase.proof is not None)
        row = writer.apply_prepared_fact(
            s,
            ctx,
            command,
            product,
            payload,
            phase.prepared,
            host=saved[4].host,
            consumption_host=saved[4].consumption_host,
            module=_module(),
            proof=phase.proof,
            consumption_binding=consumption[0],
            consumption_marker=consumption[1],
        )
        guards._same_uow(s, saved[1], ctx, saved[2])
        _require(_runtime(s) is saved[4] and digest(command.model_dump(mode="json")) == saved[3])
        return row, commands.SPECS[phase.prepared.kind][2], row.visibility
    finally:
        _PHASES.pop(phase, None)
        _discard(saved[4], phase.prepared)


def apply(*args, **kwargs):
    raise DomainError(
        "FACT_COMMON_PHASE_REQUIRED", "事实保存须使用本次共同确认和原子写入阶段。", 503
    )
