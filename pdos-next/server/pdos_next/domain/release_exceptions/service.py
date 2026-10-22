"""Named bounded exceptions and withdrawals through one common T2 atom."""

import sys
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID, uuid4

from pydantic_core import to_jsonable_python
from sqlalchemy import inspect, select

from pdos_next.contracts import Command
from pdos_next.database import require_context
from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow, _uow
from pdos_next.domain.change_execution import service as evidence
from pdos_next.domain.manufacturing_baseline.consumption import ConsumptionHost
from pdos_next.domain.professional_authority import service as professional
from pdos_next.domain.professional_authority.signature_watermarks import signature_current
from pdos_next.domain.release import policy_owner
from pdos_next.domain.release import service as releases
from pdos_next.domain.release.policy_models import ReleasePolicyFact
from pdos_next.domain.release.policy_schemas import PolicyMaterial
from pdos_next.domain.release.rules import _canonical_reads, _sources
from pdos_next.domain.release.rules import digest as body_digest
from pdos_next.domain.release.schemas import ReleaseMaterial
from pdos_next.errors import DomainError
from pdos_next.models import Product, now
from pdos_next.request_proof import snapshot_get
from pdos_next.service import command_digest, digest, require_access

from . import owner, rules
from .constants import DECIDE, WITHDRAW
from .models import ReleaseExceptionCurrent as Current
from .models import ReleaseExceptionDecision as Decision
from .schemas import PAYLOADS, ActualData, ExceptionPlan, WithdrawActualData

semantic = rules.semantic
category_lifecycle_fence = True
_CAPABILITY = object()
_T2 = {DECIDE, WITHDRAW}


def _require(test, detail, code="SOURCE_STALE", status=409):
    if not test:
        raise DomainError(code, detail, status)


@dataclass(frozen=True)
class Runtime:
    owner: owner.ActualReleaseExceptionOwner
    consumption: ConsumptionHost


def configure(engine):
    engine._pdos_release_exceptions = Runtime(
        owner.ActualReleaseExceptionOwner(engine),
        ConsumptionHost({operation: sys.modules[__name__] for operation in _T2}),
    )


def _runtime(s):
    value = getattr(s.get_bind(), "_pdos_release_exceptions", None)
    _require(type(value) is Runtime, "例外实际领域端尚未接通。", "INTEGRATION_REQUIRED", 503)
    return value


def _command(s, ctx, command, product, payload):
    require_context(s, ctx)
    _require(
        isinstance(command, Command)
        and command.operation in PAYLOADS
        and type(payload) is PAYLOADS[command.operation]
        and PAYLOADS[command.operation].model_validate(command.payload) == payload
        and command.category_id == ctx.category_id,
        "操作、完整载荷或实际品类不匹配。",
        "COMMAND_PAYLOAD_MISMATCH",
        422,
    )
    state = inspect(product, raiseerr=False)
    _require(
        isinstance(product, Product)
        and state is not None
        and state.persistent
        and state.session is s
        and (product.tenant_id, product.category_id, product.id)
        == (ctx.tenant_id, ctx.category_id, command.product_id),
        "须使用本次真实型号。",
        "FORBIDDEN_SCOPE",
        403,
    )
    _require(
        command.expected_revision == product.revision, "型号范围版本已变化。", "VERSION_CONFLICT"
    )
    if command.operation in _T2:
        _require(
            ctx.actor_id == ctx.requester_id and ctx.run_id is None and ctx.agent_run_id is None,
            "例外决定和撤回须由当前具名本人办理。",
            "NAMED_DECISION_REQUIRED",
            403,
        )


@dataclass(frozen=True)
class Bound:
    material: object
    basis: dict
    plan: ExceptionPlan
    candidate: ExceptionPlan
    reads: tuple
    authority: dict
    diagnostics: tuple = ()
    previous: object = None
    package: object = None
    pointer: dict | None = None


def _load(s, ctx, command, product, payload, *, require_reads=True):
    _command(s, ctx, command, product, payload)
    _runtime(s)
    previous = pointer = package = None
    at = now()
    if command.operation == DECIDE:
        package, package_plan = releases._row(
            s, ctx, product.id, payload.basis_package.id, payload.basis_package.revision
        )
        package_pointer = releases._pointer(s, ctx, product.id, package.series_id, lock=True)
        current = package_pointer is not None and package_pointer.version_id == package.id
        try:
            current = current and releases._current_material(
                s,
                ctx,
                product.id,
                ReleaseMaterial.model_validate(package.material_snapshot),
                package.source_basis,
            )
        except DomainError as error:
            if error.status in {401, 403} or error.code not in {
                "SOURCE_STALE",
                "RECHECK_REQUIRED",
                "VERSION_CONFLICT",
                "SOURCE_UNAVAILABLE",
            }:
                raise
            current = False
        policy_basis = package.source_basis["material_owner"].get("policy")
        fact_value = policy_basis.get("fact") if policy_basis else None
        fact = (
            snapshot_get(s, ReleasePolicyFact, UUID(fact_value["id"]), scope_id=product.id)
            if fact_value
            else None
        )
        if fact is not None:
            policy_owner._common(s, ctx, product.id, fact)
            _require(
                fact.material_sha256 == digest(fact.material),
                "固定政策内容摘要不匹配。",
                "INTEGRITY_MISMATCH",
                503,
            )
        policy_current = bool(
            policy_basis
            and releases._runtime(s).owner.policy_owner.current(s, ctx, product.id, policy_basis)
        )
        basis = {
            "package_material": deepcopy(package.material_snapshot),
            "package_source_basis": deepcopy(package.source_basis),
            "package_binding": {
                "id": str(package.id),
                "revision": package.revision,
                "series_id": str(package.series_id),
                "sha256": package.body_sha256,
            },
            "policy_basis": deepcopy(policy_basis),
        }
        project_id, purpose = package.project_id, payload.purpose
        visibility = package.visibility
        upstream_sources = package_plan.sources
        upstream_reads = package_plan.required_source_read_set
    else:
        previous, old_plan = owner.retained(
            s, ctx, product.id, payload.exception.id, payload.exception.revision
        )
        pointer = owner.pointer(s, ctx, product.id, previous.series_id, lock=True)
        _require(previous.action == "approved", "只能撤回实际独立批准决定。", "SOURCE_STALE")
        basis = {"previous_current": owner.pointer_value(pointer)}
        project_id, purpose = previous.project_id, old_plan.purpose
        visibility = previous.visibility
        upstream_sources, upstream_reads = (), ()
    authority = professional.assess(
        s, ctx, product.id, project_id, command.operation, purpose, at, write=True
    )
    sources = tuple(dict.fromkeys((*upstream_sources, *_sources(payload))))
    reads = _canonical_reads(
        (
            *upstream_reads,
            *authority.get("required_source_read_set", ()),
            *[
                {"artifact_id": str(v.id), "expected_revision": v.revision}
                for v in sources
                if v.kind == "artifact"
            ],
        )
    )
    raw, private, verified = {}, False, set()
    direct_ids = {v.id for v in _sources(payload)}
    for io in (True, False):
        selected = [v.model_dump(mode="json") for v in reads if (v.artifact_id in direct_ids) == io]
        refs = tuple(v for v in sources if (v.id in direct_ids) == io)
        if selected:
            values, is_private, checked = evidence._evidence(
                s, ctx, product.id, selected, refs, io=io
            )
            raw.update(values)
            private |= is_private
            verified.update(checked)
    _require(
        not private or visibility == "private",
        "私有例外原件不能扩大为共享记录。",
        "FORBIDDEN_SCOPE",
        403,
    )
    _require(
        {evidence.digest(v) for v in sources} <= verified,
        "例外原件未覆盖完整引用。",
        "MISSING_REQUIRED_EVIDENCE",
        422,
    )
    basis["artifact_sources"] = to_jsonable_python(raw)
    if command.operation == DECIDE:
        material = ActualData(
            package_ref=payload.basis_package,
            package=package_plan,
            package_current=current,
            policy_fact={"id": fact.id, "revision": fact.revision} if fact else None,
            policy=PolicyMaterial.model_validate(fact.material) if fact else None,
            policy_current=policy_current,
            sources_current=True,
            sources=sources,
            required_source_read_set=reads,
        )
        candidate = rules.prepare_decide(payload, material, ctx=ctx, at=at)
    else:
        material = WithdrawActualData(
            exception=payload.exception,
            previous=old_plan,
            current=pointer is not None
            and pointer.decision_id == previous.id
            and pointer.action == "approved",
            sources_current=True,
            sources=sources,
            required_source_read_set=reads,
        )
        candidate = rules.prepare_withdraw(payload, material, ctx=ctx, at=at)
    if require_reads:
        _require(
            _canonical_reads(command.source_read_set) == reads,
            "须使用本次实际例外原件完整读集。",
            "SOURCE_STALE",
        )
    return Bound(
        material,
        basis,
        candidate,
        candidate,
        reads,
        authority,
        (),
        previous,
        package,
        owner.pointer_value(pointer),
    )


def _review(command, bound):
    candidate = bound.candidate.model_dump(mode="json")
    candidate["prepared_at"] = None
    return {
        "operation": command.operation,
        "before": deepcopy(bound.pointer),
        "after": candidate,
        "authority": deepcopy(bound.authority),
        "required_source_read_set": [v.model_dump(mode="json") for v in bound.reads],
        "read_basis": deepcopy(bound.basis),
        "diagnostics": list(bound.diagnostics),
    }


class Prepared:
    def __init__(self, token, s, ctx, command, product, payload, bound):
        _require(token is _CAPABILITY, "缺本次实际准备。", "INVALID_PHASE", 503)
        self.session, self.product, self.uow = s, product, _uow(s)
        self.ctx_sha, self.command_sha = digest(vars(ctx)), digest(command)
        self.payload_sha, self.bound = digest(semantic(payload)), bound
        self.review = _review(command, bound)
        self.review_sha, self.runtime, self.used = digest(self.review), _runtime(s), False
        self.bound_sha = _bound_digest(bound)

    def __reduce__(self):
        raise TypeError("Release preparation stays in its actual transaction")


def _phase(s, ctx, command, product, payload, phase):
    _require(
        type(phase) is Prepared
        and phase.session is s
        and phase.product is product
        and phase.runtime is _runtime(s)
        and not phase.used
        and phase.command_sha == digest(command)
        and phase.payload_sha == digest(semantic(payload))
        and phase.review_sha == digest(phase.review)
        and phase.bound_sha == _bound_digest(phase.bound),
        "本次命令、材料或准备事务已改变。",
        "INVALID_PHASE",
        503,
    )
    _same_uow(s, phase.uow, ctx, phase.ctx_sha)


def _bound_digest(bound):
    return digest(
        {
            "material": bound.material,
            "basis": bound.basis,
            "plan": bound.plan,
            "candidate": bound.candidate,
            "reads": bound.reads,
            "authority": bound.authority,
            "diagnostics": bound.diagnostics,
            "pointer": bound.pointer,
            "previous": str(bound.previous.id) if bound.previous is not None else None,
            "package": str(bound.package.id) if bound.package is not None else None,
        }
    )


def validate(s, ctx, command, product, payload):
    return Prepared(
        _CAPABILITY, s, ctx, command, product, payload, _load(s, ctx, command, product, payload)
    )


prepare_preview = validate


def preview_prepared(s, ctx, command, product, payload, phase):
    _phase(s, ctx, command, product, payload, phase)
    phase.used = True
    return deepcopy(phase.review)


def preview_view(s, ctx, command, product, payload):
    return preview_prepared(
        s, ctx, command, product, payload, prepare_preview(s, ctx, command, product, payload)
    )


def prepare_write_review(s, ctx, command, product, payload, proof=None):
    # Full current material is collected once for this T2 transaction. Later
    # application/finalization use this bound phase and direct watermarks only.
    phase = validate(s, ctx, command, product, payload)
    rules.require_decidable(phase.bound.candidate)
    authority = phase.bound.authority
    _require(
        authority.get("authorized") is True and authority.get("qualified") is True,
        "当前本人、专业职责或本用途资格尚未满足。",
        "QUALIFICATION_REQUIRED",
        403,
    )
    return phase, deepcopy(phase.review)


def bind_consumption(s, ctx, command, product, payload, phase, proof):
    _phase(s, ctx, command, product, payload, phase)
    return _runtime(s).consumption.bind_before_transition(
        s, ctx, command, payload, sys.modules[__name__], proof, reviewed_snapshot=phase.review
    )


def record_consumption(s, ctx, command, product, payload, phase, proof, binding):
    marker = _runtime(s).consumption.capture_after_transition(
        s, ctx, command, payload, sys.modules[__name__], proof, binding=binding
    )
    _phase(s, ctx, command, product, payload, phase)
    return marker


def _saved_input(command, payload, phase):
    saved = command.model_dump(mode="json")
    saved.pop("idempotency_key")
    saved["payload"] = semantic(payload)
    return {
        "command": saved,
        "semantic": semantic(payload),
        "original_key_sha256": sha256(command.idempotency_key.encode()).hexdigest(),
        "review": deepcopy(phase.review),
    }


def _still_current(s, ctx, pid, bound, *, written=None):
    raw, _, _ = evidence._evidence(
        s, ctx, pid, [v.model_dump(mode="json") for v in bound.reads], (), io=False
    )
    _require(
        to_jsonable_python(raw) == bound.basis["artifact_sources"],
        "例外直接原件水位已变化。",
        "RECHECK_REQUIRED",
    )
    if bound.package is not None:
        package = bound.package
        pointer = releases._pointer(s, ctx, pid, package.series_id, lock=True)
        _require(
            pointer is not None and pointer.version_id == package.id,
            "例外所据固定包已续版。",
            "VERSION_CONFLICT",
        )
        _require(
            releases._current_material(
                s,
                ctx,
                pid,
                ReleaseMaterial.model_validate(bound.basis["package_material"]),
                bound.basis["package_source_basis"],
            ),
            "固定包直接依据已变化。",
            "RECHECK_REQUIRED",
        )
    else:
        pointer = owner.pointer(s, ctx, pid, bound.previous.series_id, lock=True)
        expected = (
            {"decision": {"id": str(written.id), "revision": 1}, "epoch": 2, "action": "withdrawn"}
            if written is not None
            else bound.pointer
        )
        _require(
            owner.pointer_value(pointer) == expected,
            "例外已被撤回或当前水位变化。",
            "VERSION_CONFLICT",
        )
    _require(
        signature_current(s, ctx, pid, bound.plan.scope.project_id, bound.authority)
        and professional.authority_time_current(bound.authority, now()),
        "本次专业职责水位已变化。",
        "QUALIFICATION_REQUIRED",
        403,
    )


def apply_validated(*args, **kwargs):
    raise DomainError("NAMED_DECISION_REQUIRED", "例外须由本人消费共同T2。", 403)


def apply_prepared_write(s, ctx, command, product, payload, phase, *, consumption):
    _phase(s, ctx, command, product, payload, phase)
    bound = phase.bound
    _still_current(s, ctx, product.id, bound)
    rules.require_decidable(bound.candidate)
    binding, marker = consumption
    live = _runtime(s).consumption.require_live(
        s,
        ctx,
        command,
        payload,
        sys.modules[__name__],
        binding.proof,
        binding=binding,
        marker=marker,
    )
    phase.used = True
    plan = bound.plan
    identity, receipt_id = uuid4(), uuid4()
    previous = bound.previous
    row = Decision(
        id=identity,
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        product_id=product.id,
        project_id=plan.scope.project_id,
        revision=1,
        series_id=previous.series_id if previous else identity,
        previous_id=previous.id if previous else None,
        previous_revision=previous.revision if previous else None,
        owner_id=plan.owner_id,
        writer_id=ctx.actor_id,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        visibility=plan.visibility,
        basis_package_id=plan.basis_package.id,
        basis_package_revision=plan.basis_package.revision,
        policy_fact_id=plan.policy_fact.id,
        policy_fact_revision=plan.policy_fact.revision,
        discipline=plan.discipline,
        purpose=plan.purpose,
        action=plan.action,
        expiry=plan.expiry,
        operation=command.operation,
        write_tier="T2",
        body=plan.model_dump(mode="json"),
        body_sha256=body_digest(plan),
        material_snapshot=bound.material.model_dump(mode="json"),
        input_snapshot=_saved_input(command, payload, phase),
        source_basis=deepcopy(bound.basis),
        sources=[v.model_dump(mode="json") for v in plan.sources],
        required_source_read_set=[v.model_dump(mode="json") for v in bound.reads],
        authority_snapshot=deepcopy(bound.authority),
        command_id=command.command_id,
        receipt_id=receipt_id,
        request_digest=command_digest(command),
        created_at=now(),
        **live.storage_columns(),
    )
    row.prepared_receipt_id, row.confirmation_id, row._release_exception_phase = (
        receipt_id,
        live.proof_id,
        phase,
    )
    s.add(row)
    s.flush([row])
    if previous is None:
        s.add(
            Current(
                id=uuid4(),
                tenant_id=row.tenant_id,
                category_id=row.category_id,
                product_id=row.product_id,
                project_id=row.project_id,
                series_id=row.series_id,
                owner_id=row.owner_id,
                visibility=row.visibility,
                basis_package_id=row.basis_package_id,
                basis_package_revision=row.basis_package_revision,
                policy_fact_id=row.policy_fact_id,
                policy_fact_revision=row.policy_fact_revision,
                discipline=row.discipline,
                purpose=row.purpose,
                decision_id=row.id,
                decision_revision=1,
                action=row.action,
                epoch=1,
            )
        )
    else:
        current = owner.pointer(s, ctx, product.id, previous.series_id, lock=True)
        current.decision_id, current.decision_revision, current.action, current.epoch = (
            row.id,
            1,
            "withdrawn",
            2,
        )
    return row, "release_exception", row.visibility


def finalize_receipt(s, ctx, command, product, payload, subject, receipt):
    phase = getattr(subject, "_release_exception_phase", None)
    _require(
        type(phase) is Prepared
        and phase.used
        and phase.session is s
        and phase.runtime is _runtime(s)
        and phase.command_sha == digest(command)
        and phase.payload_sha == digest(semantic(payload))
        and phase.bound_sha == _bound_digest(phase.bound)
        and phase.review_sha == digest(phase.review)
        and subject.receipt_id == receipt.id,
        "缺原事务的发布回执绑定。",
        "INVALID_PHASE",
        503,
    )
    _same_uow(s, phase.uow, ctx, phase.ctx_sha)
    _still_current(s, ctx, product.id, phase.bound, written=subject)
    del subject._release_exception_phase


def _header(row, pointer, applicability="not_checked"):
    current = owner.pointer_value(pointer)
    return {
        "id": str(row.id),
        "revision": row.revision,
        "project_id": str(row.project_id),
        "purpose": row.purpose,
        "discipline": row.discipline,
        "action": row.action,
        "basis_package": {"id": str(row.basis_package_id), "revision": row.basis_package_revision},
        "series_id": str(row.series_id),
        "visibility": row.visibility,
        "expiry": row.expiry.isoformat() if row.expiry else None,
        "created_at": row.created_at.isoformat(),
        "receipt_id": str(row.receipt_id),
        "as_of": current,
        "current": current,
        "applicability": applicability,
    }


def get_exception(s, ctx, pid, identity):
    row, plan = owner.retained(s, ctx, pid, identity)
    pointer = owner.pointer(s, ctx, pid, row.series_id)
    current = (
        pointer is not None
        and pointer.decision_id == row.id
        and signature_current(s, ctx, pid, row.project_id, row.authority_snapshot)
    )
    if row.action == "approved":
        try:
            from pdos_next.domain.manufacturing_trials import native_material_owner as direct

            direct._watermarks_current(
                s,
                ctx,
                pid,
                direct._source_watermarks(s, ctx, pid, row.source_basis["artifact_sources"]),
            )
            current = current and releases._runtime(s).owner.policy_owner.current(
                s, ctx, pid, row.source_basis["policy_basis"]
            )
        except DomainError as error:
            if error.status in {401, 403} or error.code not in {
                "SOURCE_STALE",
                "RECHECK_REQUIRED",
                "SOURCE_UNAVAILABLE",
                "VERSION_CONFLICT",
            }:
                raise
            current = False
        current = current and (row.expiry is None or now() < row.expiry)
    return row, {
        **_header(row, pointer, "current" if current else "needs_recheck"),
        "decision": plan.model_dump(mode="json"),
        "authority": deepcopy(row.authority_snapshot),
    }


def list_exceptions(s, ctx, pid, *, project_id, history_cursor=None):
    from pdos_next.domain.projects.models import Project

    require_access(s, ctx, pid)
    project = snapshot_get(s, Project, project_id, scope_id=pid)
    _require(
        project is not None
        and (project.tenant_id, project.category_id, project.product_id)
        == (ctx.tenant_id, ctx.category_id, pid)
        and (project.visibility != "private" or project.owner_id == ctx.requester_id),
        "项目当前不可读取。",
        "FORBIDDEN_SCOPE",
        403,
    )
    query = select(Decision).where(
        Decision.tenant_id == ctx.tenant_id,
        Decision.category_id == ctx.category_id,
        Decision.product_id == pid,
        Decision.project_id == project_id,
    )
    if history_cursor is not None:
        try:
            query = query.where(Decision.id < UUID(history_cursor))
        except ValueError as error:
            raise DomainError("SOURCE_STALE", "例外分页位置无效。", 422) from error
    rows = list(s.scalars(query.order_by(Decision.id.desc()).limit(21)))
    return {
        "items": [_header(row, owner.pointer(s, ctx, pid, row.series_id)) for row in rows[:20]],
        "next_cursor": str(rows[19].id) if len(rows) > 20 else None,
    }


def inputs(s, ctx, pid, command):
    require_access(s, ctx, pid, write=True, lock=True)
    product = s.get(Product, pid)
    _require(
        command.product_id == pid and command.operation in PAYLOADS,
        "请选择当前型号的例外操作。",
        "FORBIDDEN_SCOPE",
        403,
    )
    payload = PAYLOADS[command.operation].model_validate(command.payload)
    bound = _load(s, ctx, command, product, payload, require_reads=False)
    return to_jsonable_python(
        {
            "operation": command.operation,
            "payload": payload,
            "candidate": bound.candidate,
            "authority": bound.authority,
            "required_source_read_set": bound.reads,
            "diagnostics": bound.diagnostics,
        }
    )
