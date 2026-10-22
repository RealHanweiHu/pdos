"""Unregistered auxiliary T2 selection participant; shared tail alone owns Receipt/commit."""

import sys
from copy import deepcopy
from dataclasses import dataclass
from uuid import uuid4
from weakref import WeakKeyDictionary

from pdos_next import change_controlled_owner as owner
from pdos_next import change_controlled_store as models
from pdos_next import field_change_selection as field
from pdos_next.change_controlled_schemas import FieldIntentTarget, FieldSelectionMaterial
from pdos_next.change_order_service import _one, current_fixed, snapshot
from pdos_next.change_selection_consumption import ConsumptionHost
from pdos_next.clock import deadline_current, earliest_deadline
from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow, _uow
from pdos_next.domain.change_control.rules import digest
from pdos_next.domain.change_execution import service as old
from pdos_next.domain.change_execution.models import ChangeRequestVersion
from pdos_next.errors import DomainError
from pdos_next.models import Product
from pdos_next.schemas.verification.contracts import SourceRef
from pdos_next.service import confirmation_for
from pdos_next.service import digest as common_digest

OPERATION = models.SELECTION_OPERATION
EVENT = models.SELECTION_EVENT
FAMILY = models.SELECTION_FAMILY
Payload = models.SelectionPayload
deduplicate_subject = {FAMILY}
_PHASES = WeakKeyDictionary()


def semantic(payload):
    owner.require(type(payload) is Payload, "INVALID_PAYLOAD", 422)
    value = Payload.model_validate(payload.model_dump(mode="json")).model_dump(mode="json")
    value.pop("approval_token")
    return value


@dataclass(frozen=True)
class Runtime:
    module: object
    consumption: ConsumptionHost


def configure(engine):
    module = sys.modules[__name__]
    engine._pdos_change_selection_runtime = Runtime(module, ConsumptionHost({OPERATION: module}))
    return engine._pdos_change_selection_runtime


def runtime(s):
    value = getattr(s.get_bind(), "_pdos_change_selection_runtime", None)
    owner.require(
        type(value) is Runtime and value.module is sys.modules[__name__],
        "CONTROLLED_SELECTION_INTEGRATION_REQUIRED",
        503,
    )
    return value


@dataclass(frozen=True, eq=False)
class PreparedSelection:
    row: object
    pointer: object
    prior: object
    policy: object
    policy_snapshot: dict
    material: object
    basis: object
    units: tuple
    object_basis: dict
    sources: tuple[SourceRef, ...]
    reads: list
    source_basis: dict
    authority: dict
    current_revision: int
    next_revision: int
    next_epoch: int
    deadline: object
    payload_semantic: dict
    checked_at: object


def _read(s, ctx, command, payload, *, new_write, require_reads=True):
    owner.require(
        type(payload) is Payload
        and command.operation == OPERATION
        and Payload.model_validate(command.payload) == payload,
        "INVALID_PAYLOAD",
        422,
    )
    uow, configured, stamp = _uow(s), runtime(s), old._runtime_stamp(s)
    product = _one(
        s,
        Product,
        Product.tenant_id == ctx.tenant_id,
        Product.id == command.product_id,
        lock=new_write,
    )
    product_revision = product.revision
    if new_write:
        owner.require(product_revision == command.expected_revision, "VERSION_CONFLICT")
    caller, caller_until = owner._caller(s, ctx, command.product_id, write=True)
    selected = _one(
        s,
        ChangeRequestVersion,
        ChangeRequestVersion.tenant_id == ctx.tenant_id,
        ChangeRequestVersion.product_id == command.product_id,
        ChangeRequestVersion.change_id == payload.change_id,
        ChangeRequestVersion.revision == payload.expected_change_revision,
    )
    owner.require(
        selected.visibility == payload.visibility
        and (selected.visibility == "category" or selected.owner_id == ctx.requester_id),
        "CHANGE_AUDIENCE_MISMATCH",
        403,
    )
    request = snapshot(selected)
    pointer, current = current_fixed(s, ctx, command.product_id, payload.change_id, lock=new_write)
    if new_write:
        owner.require(current.id == selected.id, "VERSION_CONFLICT")
        owner.require(request.status in {"analysis", "review"}, "INVALID_STATE")
    owner.require(
        (current.project_id, current.owner_id, current.visibility)
        == (selected.project_id, selected.owner_id, selected.visibility),
        "FORBIDDEN_SCOPE",
        403,
    )
    # Current and captured parent may differ after legitimate Order appends only;
    # scope, fixed root/reference material and Action binding remain exact.
    active_request = snapshot(current)
    owner.require(
        (active_request.roots, active_request.references, active_request.scope)
        == (request.roots, request.references, request.scope),
        "RECHECK_REQUIRED",
    )
    scope, purpose = old._seed(s, ctx, command.product_id, (*request.roots, *request.references))
    owner.require(scope == request.scope, "FORBIDDEN_SCOPE", 403)
    _, project = owner._project(s, ctx, scope)
    policy = owner.policy_callback(
        s, ctx, command.product_id, scope=scope, purpose=purpose, request=request
    )
    _, policy_row = owner.policy_pointer(s, ctx, command.product_id, scope, purpose)
    is_field = isinstance(payload.action, FieldIntentTarget)
    action_target = (
        payload.action
        if new_write or is_field
        else payload.action.model_copy(
            update={
                "expected_issue_revision": owner._current_issue_revision(
                    s, ctx, command.product_id, scope, payload.action.issue_id
                )
            }
        )
    )

    def action_read():
        if is_field:
            return field.load_basis(
                s,
                ctx,
                command.product_id,
                action_target,
                payload.item,
                request,
                scope,
                purpose,
                policy.nature,
            )
        return owner.action_basis(s, ctx, command.product_id, action_target, scope, purpose)

    basis, action = action_read()
    if not is_field:
        owner.require(
            (selected.owner_id, selected.visibility) == (basis.owner_id, basis.visibility),
            "AUDIENCE_USE_FORBIDDEN",
            403,
        )
    material, _ = owner.original(
        s, ctx, command.product_id, payload.source, field.SelectionMaterialReader
    )
    expected = (
        field.material_for(
            ctx,
            request,
            payload.item,
            action_target,
            basis,
            status=payload.status,
            valid_until=payload.valid_until,
            reason=payload.reason,
        )
        if is_field
        else models.SelectionMaterial(
            schema_version="pdos-controlled-change-selection-v1",
            scope=scope,
            purpose=purpose,
            change_id=request.id,
            item=payload.item,
            issue_id=basis.issue_id,
            capa_id=basis.capa_id,
            action_id=action.action_id,
            action_sha256=action.action_sha256,
            executor_id=action.executor_id,
            decider_id=ctx.actor_id,
            status=payload.status,
            valid_until=payload.valid_until,
            reason=payload.reason,
            nature=basis.nature,
        )
    )
    owner.require(material == expected, "ACTION_INTENT_SOURCE_MISMATCH")
    owner.require(policy.nature == basis.nature, "NATURE_MISMATCH", 403)
    fixed, object_reads, object_sources = owner.objects(
        s, ctx, command.product_id, request, payload.item
    )
    units = owner.exact_units(payload.item)
    auth, auth_until = owner.authority(s, ctx, command.product_id, scope, OPERATION, purpose)
    owner.require(
        payload.item.discipline in auth["roles"]
        and (basis.nature != "real" or auth.get("synthetic") is False),
        "FORBIDDEN_DISCIPLINE",
        403,
    )
    selection_pointer, prior = owner.selection_pointer(
        s, ctx, command.product_id, scope, request.id, payload.item.id, lock=new_write
    )
    if new_write:
        revision, epoch = owner.previous(
            selection_pointer,
            prior,
            payload.expected_previous_id,
            payload.expected_previous_revision,
        )
        owner.require(
            prior is None
            or getattr(prior, "basis_kind", "capa_action")
            == ("field_intent" if is_field else "capa_action"),
            "SELECTION_SERIES_SCOPE_CHANGED",
        )
        if is_field:
            owner.require(
                prior is None
                or (
                    prior.owner_id,
                    prior.visibility,
                    prior.purpose,
                    prior.intent_id,
                    prior.feedback_id,
                    prior.feedback_version_id,
                    prior.feedback_revision,
                    prior.feedback_sha256,
                )
                == (
                    selected.owner_id,
                    selected.visibility,
                    purpose,
                    payload.item.intent.id,
                    basis.feedback_id,
                    basis.feedback_version_id,
                    basis.feedback_revision,
                    basis.feedback_sha256,
                ),
                "SELECTION_SERIES_SCOPE_CHANGED",
            )
        else:
            owner.require(
                prior is None
                or (
                    prior.owner_id,
                    prior.visibility,
                    prior.purpose,
                    prior.intent_id,
                    prior.action_id,
                    prior.capa_id,
                    prior.issue_id,
                )
                == (
                    selected.owner_id,
                    selected.visibility,
                    purpose,
                    payload.item.intent.id,
                    action.action_id,
                    basis.capa_id,
                    basis.issue_id,
                ),
                "SELECTION_SERIES_SCOPE_CHANGED",
            )
    else:
        revision, epoch = (prior.revision, prior.epoch) if prior else (1, 1)
    sources = tuple(
        dict.fromkeys(
            (payload.source, *request.sources, policy.source, *object_sources, *basis.sources)
        )
    )
    reads = owner._reads(
        selected.required_source_read_set,
        current.required_source_read_set,
        owner.old._source_reads(sources),
        policy.required_source_read_set,
        object_reads,
        basis.required_source_read_set,
        auth["required_source_read_set"],
        prior.required_source_read_set if prior else (),
    )
    actual_basis = owner._source_guard(
        s, ctx, command.product_id, selected.visibility, selected.owner_id, reads, sources
    )
    wanted_reads = owner._reads(command.source_read_set)
    if require_reads:
        owner.require(all(v in wanted_reads for v in reads), "MISSING_REQUIRED_EVIDENCE")
    # Final closure after ALL bytes: fresh actual policy/action/objects/qualification,
    # then source metadata/Current/Project/caller/runtime/UOW and a real clock.
    owner.policy_callback(
        s, ctx, command.product_id, scope=scope, purpose=purpose, request=request, previous=policy
    )
    final_basis, final_action = action_read()
    owner.require(
        final_basis == basis
        and final_action == action
        and owner.same(owner.objects(s, ctx, command.product_id, request, payload.item)[0], fixed),
        "SOURCE_STALE",
    )
    last_auth, last_auth_until = owner.authority(
        s, ctx, command.product_id, scope, OPERATION, purpose
    )
    owner.require(
        last_auth == auth
        and owner.same(
            owner._source_guard(
                s,
                ctx,
                command.product_id,
                selected.visibility,
                selected.owner_id,
                reads,
                sources,
                io=False,
            ),
            actual_basis,
        ),
        "SOURCE_STALE",
    )
    final_pointer, final_current = current_fixed(s, ctx, command.product_id, request.id)
    owner.require(
        (final_pointer.id, final_current.id, final_current.request_sha256)
        == (pointer.id, current.id, current.request_sha256),
        "SOURCE_STALE",
    )
    last_pointer, last_prior = owner.selection_pointer(
        s, ctx, command.product_id, scope, request.id, payload.item.id
    )
    owner.require(
        (last_pointer.id if last_pointer else None, last_prior.id if last_prior else None)
        == (selection_pointer.id if selection_pointer else None, prior.id if prior else None),
        "SOURCE_STALE",
    )
    owner.require(
        _one(
            s,
            Product,
            Product.tenant_id == ctx.tenant_id,
            Product.id == command.product_id,
        ).revision
        == product_revision,
        "SOURCE_STALE",
    )
    owner.require(
        owner._project(s, ctx, scope)[1] == project
        and owner._caller(s, ctx, command.product_id, write=True)[0] == caller
        and old._runtime_stamp(s) == stamp
        and runtime(s) is configured,
        "SOURCE_STALE",
    )
    _same_uow(s, uow, ctx, common_digest(vars(ctx)))
    at = owner.clock()
    end = earliest_deadline(
        caller_until, auth_until, last_auth_until, material.valid_until, policy.valid_until
    )
    owner.require(at < end, "SOURCE_STALE")
    phase = PreparedSelection(
        selected,
        selection_pointer,
        prior,
        policy_row,
        policy.model_dump(mode="json"),
        material,
        basis,
        units,
        fixed,
        sources,
        reads,
        actual_basis,
        auth,
        current.revision,
        revision,
        epoch,
        end,
        semantic(payload),
        at,
    )
    return phase, configured


def review(phase):
    """Stable 13 keys; no prospective UUID or evaluated clock enters material."""
    is_field = isinstance(phase.material, FieldSelectionMaterial)
    return {
        "operation": OPERATION,
        "payload_semantic": deepcopy(phase.payload_semantic),
        "before": {
            "change_id": str(phase.row.change_id),
            "change_revision": phase.current_revision,
            "selection": str(phase.prior.id) if phase.prior else None,
            "revision": phase.prior.revision if phase.prior else 0,
        },
        "after": {
            "selection_revision": phase.next_revision,
            "material": phase.material.model_dump(mode="json"),
            **(
                {
                    "feedback_version_id": str(phase.basis.feedback_version_id),
                    "feedback_sha256": phase.basis.feedback_sha256,
                }
                if is_field
                else {"issue_version_id": str(phase.basis.issue_version_id)}
            ),
        },
        "read_set": deepcopy(phase.reads),
        "sources": [v.model_dump(mode="json") for v in phase.sources],
        "authority": deepcopy(phase.authority),
        "policy": deepcopy(phase.policy_snapshot),
        "source_basis": deepcopy(phase.source_basis),
        "selection": {
            "item_sha256": digest(phase.material.item),
            "units": [v.model_dump(mode="json") for v in phase.units],
            "objects": deepcopy(phase.object_basis),
            **(
                {"intent_sha256": digest(phase.material.item.intent)}
                if is_field
                else {"action_sha256": phase.material.action_sha256}
            ),
        },
        "effect": (
            "保存现场反馈的明确未来实施意图与逐项适用；不代表执行人已承诺、已实施或复验。"
            if is_field
            else "保存逐项适用与真实CAPA措施关联；未批准变更令、未实施、未授资格或完整影响覆盖。"
        ),
        "unknown": ["八维影响完整性、实际实施和生效由原独立owner办理。"]
        if phase.material.status == "applicable"
        else ["该项不适用/未知，不能批准或实施。"],
        "proof_tier": "T2",
    }


def prepare_write_review(s, ctx, command, product, payload, proof=None):
    owner.require(
        command.product_id == product.id and command.expected_revision == product.revision,
        "VERSION_CONFLICT",
    )
    if proof is None:
        proof = confirmation_for(
            s, ctx, product.id, OPERATION, product.id, product.revision, payload.approval_token
        )
    phase, configured = _read(s, ctx, command, payload, new_write=True)
    viewed = review(phase)
    owner.require(owner.same(proof.snapshot, viewed), "CONFIRMATION_SCOPE_CHANGED")
    _PHASES[phase] = (
        s,
        _uow(s),
        common_digest(vars(ctx)),
        common_digest(command.model_dump(mode="json")),
        configured,
        proof,
        common_digest(viewed),
    )
    return phase, viewed


def _phase(s, ctx, command, payload, phase):
    saved = _PHASES.get(phase)
    owner.require(
        saved is not None
        and saved[0] is s
        and saved[2] == common_digest(vars(ctx))
        and saved[3] == common_digest(command.model_dump(mode="json"))
        and saved[4] is runtime(s)
        and semantic(payload) == phase.payload_semantic
        and saved[6] == common_digest(review(phase)),
        "CONTROLLED_SELECTION_PHASE_REQUIRED",
        503,
    )
    _same_uow(s, saved[1], ctx, saved[2])
    return saved


def bind_consumption(s, ctx, command, product, payload, phase, proof):
    saved = _phase(s, ctx, command, payload, phase)
    owner.require(saved[5] is proof, "CONTROLLED_SELECTION_PHASE_REQUIRED", 503)
    return saved[4].consumption.bind_before_transition(
        s, ctx, command, payload, saved[4].module, proof, reviewed_snapshot=review(phase)
    )


def record_consumption(s, ctx, command, product, payload, phase, proof, binding):
    # First actual clock capture. Python registry only: no SQL/flush/owner IO.
    saved = _PHASES.get(phase)
    if saved is None:
        raise DomainError("CONTROLLED_SELECTION_PHASE_REQUIRED", "缺本次共同消费绑定。", 503)
    marker = saved[4].consumption.capture_after_transition(
        s, ctx, command, payload, saved[4].module, proof, binding=binding
    )
    _phase(s, ctx, command, payload, phase)
    return marker


def _stage_without_io(s, ctx, command, phase, marker, saved_at):
    """No owner IO/flush/Receipt: common tail must flush Fact BEFORE Current."""
    owner.require(
        deadline_current(earliest_deadline(phase.deadline, marker.expires_at), saved_at),
        "SOURCE_STALE",
    )
    material, prior = phase.material, phase.prior
    is_field = isinstance(material, FieldSelectionMaterial)
    atom = models.ChangeSelectionFact(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        product_id=command.product_id,
        project_id=material.scope.project_id,
        owner_id=phase.row.owner_id,
        visibility=phase.row.visibility,
        revision=phase.next_revision,
        epoch=phase.next_epoch,
        purpose=material.purpose,
        purpose_sha256=digest(material.purpose),
        previous_id=prior.id if prior else None,
        previous_revision=prior.revision if prior else None,
        actor_id=ctx.actor_id,
        command_id=command.command_id,
        operation=OPERATION,
        status=material.status,
        nature=material.nature,
        material=material.model_dump(mode="json"),
        material_sha256=digest(material),
        source=phase.payload_semantic["source"],
        sources=[v.model_dump(mode="json") for v in phase.sources],
        required_source_read_set=phase.reads,
        source_basis=phase.source_basis,
        authority_snapshot=phase.authority,
        input_snapshot={
            "review": review(phase),
            "semantic": phase.payload_semantic,
            "shared_proof": {"id": str(marker.proof_id), "tier": marker.tier},
        },
        valid_until=material.valid_until,
        change_id=material.change_id,
        change_version_id=phase.row.id,
        change_revision=phase.row.revision,
        item_id=material.item.id,
        item_sha256=digest(material.item),
        intent_id=material.item.intent.id,
        basis_kind="field_intent" if is_field else "capa_action",
        issue_id=None if is_field else material.issue_id,
        issue_version_id=None if is_field else phase.basis.issue_version_id,
        issue_revision=None if is_field else phase.basis.issue_revision,
        capa_id=None if is_field else material.capa_id,
        action_id=None if is_field else material.action_id,
        action_sha256=None if is_field else material.action_sha256,
        **(
            {
                "category_id": phase.basis.category_id,
                "feedback_id": phase.basis.feedback_id,
                "feedback_version_id": phase.basis.feedback_version_id,
                "feedback_revision": phase.basis.feedback_revision,
                "feedback_sha256": phase.basis.feedback_sha256,
                "executor_id": material.executor_id,
            }
            if is_field
            else {}
        ),
        policy_id=phase.policy.id,
        policy_revision=phase.policy.revision,
        policy_snapshot=phase.policy_snapshot,
        units_snapshot=[v.model_dump(mode="json") for v in phase.units],
        object_basis=phase.object_basis,
        created_at=saved_at,
        **{
            ("confirmation_material_sha256" if key == "material_sha256" else key): value
            for key, value in marker.storage_columns().items()
        },
    )
    atom.action_result = {
        "item_id": str(atom.item_id),
        **(
            {"intent_id": str(atom.intent_id), "feedback_id": str(atom.feedback_id)}
            if is_field
            else {"action_id": str(atom.action_id)}
        ),
        "material_sha256": atom.material_sha256,
    }
    s.add(atom)
    if phase.pointer is None:
        s.add(
            models.ChangeSelectionCurrent(
                tenant_id=ctx.tenant_id,
                product_id=command.product_id,
                project_id=material.scope.project_id,
                owner_id=atom.owner_id,
                visibility=atom.visibility,
                purpose_sha256=atom.purpose_sha256,
                change_id=atom.change_id,
                item_id=atom.item_id,
                fact_id=atom.id,
                revision=atom.revision,
                epoch=atom.epoch,
            )
        )
    else:
        phase.pointer.fact_id, phase.pointer.revision, phase.pointer.epoch = (
            atom.id,
            atom.revision,
            atom.epoch,
        )
    return atom


def apply_prepared_write(s, ctx, command, product, payload, phase, *, consumption):
    saved = _phase(s, ctx, command, payload, phase)
    owner.require(
        type(consumption) is tuple and len(consumption) == 2,
        "CONTROLLED_SELECTION_PHASE_REQUIRED",
        503,
    )
    binding, marker = consumption
    consumer = saved[4].consumption
    try:
        consumer.require_live(
            s, ctx, command, payload, saved[4].module, saved[5], binding=binding, marker=marker
        )
        fresh, _ = _read(s, ctx, command, payload, new_write=True)
        owner.require(owner.same(review(fresh), review(phase)), "CONFIRMATION_SCOPE_CHANGED")
        consumer.require_live(
            s, ctx, command, payload, saved[4].module, saved[5], binding=binding, marker=marker
        )
        at = owner.clock()
        _same_uow(s, saved[1], ctx, saved[2])
        owner.require(
            deadline_current(earliest_deadline(fresh.deadline, marker.expires_at), at),
            "SOURCE_STALE",
        )
        return _stage_without_io(s, ctx, command, fresh, marker, at)
    finally:
        _PHASES.pop(phase, None)


def validate(s, ctx, command, product, payload):
    _read(s, ctx, command, payload, new_write=False)


def preview_view(s, ctx, command, payload):
    phase, _ = _read(s, ctx, command, payload, new_write=True)
    return review(phase)


def inputs(s, ctx, pid, command):
    owner.require(command.product_id == pid, "FORBIDDEN_SCOPE", 403)
    payload = Payload.model_validate(command.payload)
    # Caller first obtains exact registered/owner reads via the actual owner port.
    # Missing reads raises; this endpoint never manufactures a positive decision.
    phase, _ = _read(s, ctx, command, payload, new_write=True, require_reads=False)
    returned = command.model_dump(mode="json")
    returned["source_read_set"] = owner._reads(command.source_read_set, phase.reads)
    from pdos_next.contracts import Command

    returned = Command.model_validate(returned).model_dump(mode="json")
    return {
        "command": returned,
        "allowed": True,
        "required_source_read_set": phase.reads,
        "review": review(phase),
    }


def replay_subject(s, ctx, command, payload):
    from sqlalchemy import select

    rows = list(
        s.scalars(
            select(models.ChangeSelectionFact)
            .where(
                models.ChangeSelectionFact.tenant_id == ctx.tenant_id,
                models.ChangeSelectionFact.product_id == command.product_id,
                models.ChangeSelectionFact.change_id == payload.change_id,
                models.ChangeSelectionFact.item_id == payload.item.id,
                models.ChangeSelectionFact.actor_id == ctx.actor_id,
                models.ChangeSelectionFact.input_snapshot["semantic"] == semantic(payload),
            )
            .limit(2)
            .execution_options(populate_existing=True, autoflush=False)
        )
    )
    matches = [row for row in rows if row.input_snapshot["semantic"] == semantic(payload)]
    owner.require(len(matches) <= 1, "INTEGRITY_MISMATCH")
    return matches[0].id if matches else None


def replay_subject_type(command, payload):
    return FAMILY


def apply(*args, **kwargs):
    raise DomainError(
        "CONTROLLED_SELECTION_PHASE_REQUIRED", "须真实共同具名T2消费与原子保存尾部。", 503
    )
