"""Candidate standard common hooks. Registration/migration/app startup remain unapplied."""

import sys
from dataclasses import dataclass
from weakref import WeakKeyDictionary

from pdos_next import change_order_service as owner
from pdos_next.change_order_consumption import ConsumptionHost
from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow, _uow
from pdos_next.errors import DomainError
from pdos_next.service import confirmation_for, digest

semantic = owner.semantic
validate = owner.validate
preview_view = owner.preview_view
replay_subject = owner.replay_subject
replay_subject_type = owner.replay_subject_type
inputs = owner.inputs
deduplicate_subject = owner.deduplicate_subject
_PHASES = WeakKeyDictionary()


@dataclass(frozen=True, eq=False)
class WritePhase:
    prepared: owner.PreparedChange
    proof: object


@dataclass(frozen=True)
class Runtime:
    module: object
    consumption: ConsumptionHost


def configure_integration(engine, **callbacks):
    owner.configure(engine, **callbacks)
    module = sys.modules[__name__]
    engine._pdos_change_order_consumer = Runtime(
        module, ConsumptionHost({op: module for op in owner.PAYLOADS})
    )
    return engine._pdos_change_order_consumer


def _runtime(s):
    value = getattr(s.get_bind(), "_pdos_change_order_consumer", None)
    owner.require(
        type(value) is Runtime and value.module is sys.modules[__name__],
        "CHANGE_COMMON_INTEGRATION_REQUIRED",
        503,
    )
    return value


def _phase(s, ctx, command, payload, phase):
    value = _PHASES.get(phase)
    owner.require(
        value is not None and value[0] is s and value[2] is _runtime(s),
        "CHANGE_COMMON_PHASE_REQUIRED",
        503,
    )
    _same_uow(s, value[1], ctx, digest(vars(ctx)))
    owner._require_phase(s, ctx, command, payload, phase.prepared)
    return value[2]


def prepare_write_review(s, ctx, command, product, payload, proof=None):
    owner.require(
        command.product_id == product.id and command.expected_revision == product.revision,
        "VERSION_CONFLICT",
    )
    token = getattr(payload, "approval_token", None) or getattr(payload, "confirmation_token", None)
    if proof is None:
        proof = confirmation_for(
            s, ctx, product.id, command.operation, product.id, product.revision, token
        )
    prepared, review = owner.prepare_write_review(s, ctx, command, product, payload, proof)
    phase = WritePhase(prepared, proof)
    _PHASES[phase] = (s, _uow(s), _runtime(s))
    return phase, review


def bind_consumption(s, ctx, command, product, payload, phase, proof):
    runtime = _phase(s, ctx, command, payload, phase)
    owner.require(phase.proof is proof, "CHANGE_COMMON_PHASE_REQUIRED", 503)
    return runtime.consumption.bind_before_transition(
        s,
        ctx,
        command,
        payload,
        runtime.module,
        proof,
        reviewed_snapshot=owner._review(ctx, command, payload, phase.prepared),
    )


def record_consumption(s, ctx, command, product, payload, phase, proof, binding):
    # Python-only registry lookup then the actual first-capture clock. No SQL,
    # ORM load, source owner call or flush occurs between assignment and capture.
    saved = _PHASES.get(phase)
    if saved is None:
        raise DomainError("CHANGE_COMMON_PHASE_REQUIRED", "缺本事务消费绑定。", 503)
    marker = saved[2].consumption.capture_after_transition(
        s, ctx, command, payload, saved[2].module, proof, binding=binding
    )
    _phase(s, ctx, command, payload, phase)
    return marker


def apply_prepared_write(s, ctx, command, product, payload, phase, *, consumption):
    runtime = _phase(s, ctx, command, payload, phase)
    owner.require(
        type(consumption) is tuple and len(consumption) == 2, "CHANGE_COMMON_PHASE_REQUIRED", 503
    )
    try:
        return owner.apply_prepared(
            s,
            ctx,
            command,
            product,
            payload,
            phase.prepared,
            phase.proof,
            runtime.consumption,
            runtime.module,
            consumption[0],
            consumption[1],
        )
    finally:
        _PHASES.pop(phase, None)
        owner._PHASES.get(s, {}).pop(id(phase.prepared), None)


def apply(*args, **kwargs):
    raise DomainError(
        "CHANGE_COMMON_PHASE_REQUIRED", "须本次实际共同T1/T2消费和共同原子尾部。", 503
    )


def prepare_preview(s, ctx, command, product, payload):
    return owner.prepare_preview(s, ctx, command, product, payload)


def preview_prepared(s, ctx, command, product, payload, phase):
    return owner.preview_prepared(s, ctx, command, product, payload, phase)
