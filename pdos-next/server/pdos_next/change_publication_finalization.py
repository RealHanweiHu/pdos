"""One command's opaque coverage fence after its entire common flush.

No registry, persisted token, replay cache, new authority or confirmation lives
here. Only the actual returning ORM subject carries this one-use material.
"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime

from pdos_next.clock import deadline_current, earliest_deadline

_TOKEN = object()
_ATTRIBUTE = "_pdos_change_publication_finalization"
_OPERATIONS = frozenset(
    {
        "change.impact.compute",
        "change.order.prepare",
        "change.order.approve",
        "change.implementation.record",
        "change.effectivity.record",
        "change.verification.record",
        "change.close",
    }
)


def _require(ok):
    from pdos_next.errors import DomainError

    if not ok:
        raise DomainError("RECHECK_REQUIRED", "共同发布尾部的当前覆盖或同事务依据须重新核对。", 409)


def _digest(value):
    from pdos_next.service import digest

    return digest(value)


def _row_pin(subject):
    return _digest(
        {
            column.key: getattr(subject, column.key)
            for column in subject.__table__.columns
            if column.key != "audience_dependencies"
        }
    )


@dataclass(frozen=True, eq=False)
class _Publication:
    token: object
    session: object
    context: object
    uow: object
    caller_hash: str
    command: object
    command_hash: str
    subject: object
    subject_hash: str
    coverage: object
    request: object
    request_hash: str
    purpose: str
    runtime_kind: str
    runtime_stamp: object
    closure: object
    valid_until: datetime
    consumer: object = None
    module: object = None
    proof: object = None
    binding: object = None
    marker: object = None
    consumer_runtime: object = None
    used: bool = False


def _attach(
    s,
    ctx,
    command,
    subject,
    *,
    coverage,
    request,
    purpose,
    runtime_kind,
    runtime_stamp,
    closure,
    valid_until,
    consumer=None,
    module=None,
    proof=None,
    binding=None,
    marker=None,
):
    from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow, _uow
    from pdos_next.domain.change_coverage_owner import owner
    from pdos_next.domain.change_execution.models import ChangeRequestVersion

    # A missing opaque read never turns saved JSON into a permission token.
    if coverage is None:
        _require("coverage" not in subject.source_basis)
        return
    _require(type(subject) is ChangeRequestVersion and not hasattr(subject, _ATTRIBUTE))
    retained = command.operation in {
        "change.implementation.record",
        "change.effectivity.record",
        "change.verification.record",
        "change.close",
    }
    _require(
        type(coverage) is (owner.RetainedCoverageRead if retained else owner.CoverageRead)
        and coverage._token is (owner._RETAINED_TOKEN if retained else owner._READ_TOKEN)
    )
    _require(coverage._session is s and coverage._proof_sha256 == _digest(coverage.source_basis))
    caller = _digest(vars(ctx))
    _same_uow(s, coverage._uow, ctx, coverage._caller_hash)
    _require(subject.source_basis.get("coverage") == coverage.source_basis)
    _require(
        command.operation in _OPERATIONS
        and subject.operation == command.operation
        and (subject.tenant_id, subject.product_id, subject.project_id, subject.change_id)
        == (ctx.tenant_id, command.product_id, request.scope.project_id, request.id)
        and (request.scope.tenant_id, request.scope.product_id)
        == (ctx.tenant_id, command.product_id)
        and isinstance(closure, dict)
        and closure == subject.source_basis.get("closure")
        and (
            valid_until is None
            or (isinstance(valid_until, datetime) and valid_until.tzinfo is not None)
        )
    )
    _require(
        (runtime_kind == "impact" and command.operation == "change.impact.compute")
        or (
            runtime_kind == "formal"
            and command.operation in _OPERATIONS - {"change.impact.compute"}
        )
    )
    state = _Publication(
        _TOKEN,
        s,
        ctx,
        _uow(s),
        caller,
        command,
        _digest(command.model_dump(mode="json")),
        subject,
        _row_pin(subject),
        coverage,
        request,
        _digest(request.model_dump(mode="json")),
        purpose,
        runtime_kind,
        deepcopy(runtime_stamp),
        deepcopy(closure),
        earliest_deadline(valid_until, coverage.valid_until),
        consumer,
        module,
        proof,
        binding,
        marker,
        getattr(s.get_bind(), "_pdos_change_order_consumer", None)
        if runtime_kind == "formal"
        else None,
    )
    if runtime_kind == "formal":
        from pdos_next import change_order_integration as integration

        _require(
            module is integration
            and type(state.consumer_runtime) is integration.Runtime
            and state.consumer_runtime.module is module
            and state.consumer_runtime.consumption is consumer
            and all(value is not None for value in (proof, binding, marker))
        )
    setattr(subject, _ATTRIBUTE, state)


def attach_impact(s, ctx, command, subject, bound):
    deadlines = [bound.graph.expires_at]
    if bound.authority.get("valid_until"):
        deadlines.append(
            datetime.fromisoformat(bound.authority["valid_until"].replace("Z", "+00:00"))
        )
    _attach(
        s,
        ctx,
        command,
        subject,
        coverage=bound.coverage,
        request=bound.request,
        purpose=bound.purpose,
        runtime_kind="impact",
        runtime_stamp=bound.runtime_stamp,
        closure=bound.source_basis.get("closure"),
        valid_until=earliest_deadline(*deadlines),
    )


def attach_formal(s, ctx, command, subject, phase, *, consumer, module, proof, binding, marker):
    _attach(
        s,
        ctx,
        command,
        subject,
        coverage=phase.coverage,
        request=phase.request,
        purpose=phase.purpose,
        runtime_kind="formal",
        runtime_stamp=phase.runtime_stamp,
        closure=phase.source_basis.get("closure"),
        valid_until=earliest_deadline(phase.valid_until, marker.expires_at),
        consumer=consumer,
        module=module,
        proof=proof,
        binding=binding,
        marker=marker,
    )


def discard(subject):
    if subject is not None and hasattr(subject, _ATTRIBUTE):
        state = getattr(subject, _ATTRIBUTE)
        if type(state) is _Publication and state.token is _TOKEN:
            object.__setattr__(state, "used", True)
        delattr(subject, _ATTRIBUTE)


def _same_material(s, ctx, command, subject, state):
    from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow

    _require(
        type(state) is _Publication
        and state.token is _TOKEN
        and state.session is s
        and state.context is ctx
        and state.command is command
        and state.subject is subject
        and getattr(subject, _ATTRIBUTE, None) is state
        and _digest(vars(ctx)) == state.caller_hash
        and _digest(command.model_dump(mode="json")) == state.command_hash
        and _row_pin(subject) == state.subject_hash
        and _digest(state.request.model_dump(mode="json")) == state.request_hash
        and subject.source_basis.get("coverage") == state.coverage.source_basis
        and subject.source_basis.get("closure") == state.closure
    )
    _same_uow(s, state.uow, ctx, state.caller_hash)


def finalize(s, ctx, command, subject):
    """Fixed common seam: after append_receipt/fullflush, before receipt return.

    A rejection escapes to the existing caller's whole-transaction rollback.
    This is the final application check, not a claimed COMMIT-clock guarantee.
    """
    if command.operation not in _OPERATIONS:
        return
    state = getattr(subject, _ATTRIBUTE, None)
    if state is None:
        _require("coverage" not in subject.source_basis)
        return
    try:
        _require(type(state) is _Publication and state.token is _TOKEN and not state.used)
        # A private one-use lifecycle flag; never persisted or supplied by a client.
        object.__setattr__(state, "used", True)
        _same_material(s, ctx, command, subject, state)
        from pdos_next.change_graph_closure import closure_stamp
        from pdos_next.domain.change_coverage_owner.owner import recheck_access

        # Fixed Product/business scope and monotonic DB epoch stay exact.
        # Finish this SQL before the last current publisher/caller access fence.
        _require(
            closure_stamp(s, ctx, scope=state.request.scope, audience=state.request.audience)
            == state.closure
        )
        access_until = recheck_access(
            s,
            ctx,
            command.product_id,
            state.coverage,
            request=state.request,
            purpose=state.purpose,
        )
        if state.runtime_kind == "impact":
            from pdos_next.domain.change_execution.service import _runtime_stamp

            _require(_runtime_stamp(s) == state.runtime_stamp)
        else:
            from pdos_next import change_order_integration as integration
            from pdos_next.change_order_service import runtime

            _require(
                runtime(s)[0] == state.runtime_stamp
                and getattr(s.get_bind(), "_pdos_change_order_consumer", None)
                is state.consumer_runtime
                and integration._runtime(s) is state.consumer_runtime
            )
            # Existing concrete host check has no IO and consumes no second proof.
            payload = integration.owner.PAYLOADS[command.operation].model_validate(command.payload)
            state.consumer.require_live(
                s,
                ctx,
                command,
                payload,
                state.module,
                state.proof,
                binding=state.binding,
                marker=state.marker,
            )
        _same_material(s, ctx, command, subject, state)
        _require(
            deadline_current(earliest_deadline(state.valid_until, access_until), datetime.now(UTC))
        )
    finally:
        discard(subject)
