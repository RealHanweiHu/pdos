"""Fixed release preparation and separate decisions through the common owner.

An assembled package preserves unknowns; its existence grants no release.
The real policy owner is deliberately required for a later T2 decision.
"""

import sys
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID, uuid4

from pydantic_core import to_jsonable_python
from sqlalchemy import inspect, select

from pdos_next.contracts import Command, SourceRead
from pdos_next.database import require_context
from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow, _uow
from pdos_next.domain.change_execution import service as evidence
from pdos_next.domain.manufacturing_baseline.consumption import ConsumptionHost
from pdos_next.domain.professional_authority import service as professional
from pdos_next.domain.professional_authority.signature_watermarks import signature_current
from pdos_next.errors import DomainError
from pdos_next.models import Product, now
from pdos_next.request_proof import snapshot_get, snapshot_scalar
from pdos_next.schemas.verification.contracts import SourceRef
from pdos_next.service import command_digest, digest, require_access

from . import rules
from .material_owner import ActualReleaseMaterialOwner
from .models import ReleaseDecision as Decision
from .models import ReleasePackage as Package
from .models import ReleasePackageCurrent as Current
from .schemas import (
    ASSEMBLE,
    ENGINEERING_APPROVE,
    MANUFACTURING_APPROVE,
    PAYLOADS,
    PackagePlan,
    ReleaseMaterial,
)

semantic = rules.semantic
category_lifecycle_fence = True
_CAPABILITY = object()
_T2 = {ENGINEERING_APPROVE, MANUFACTURING_APPROVE}


def _require(test, detail, code="SOURCE_STALE", status=409):
    if not test:
        raise DomainError(code, detail, status)


@dataclass(frozen=True)
class Runtime:
    owner: ActualReleaseMaterialOwner
    consumption: ConsumptionHost


def configure(engine):
    engine._pdos_release = Runtime(
        ActualReleaseMaterialOwner(engine),
        ConsumptionHost({operation: sys.modules[__name__] for operation in _T2}),
    )


def _runtime(s):
    value = getattr(s.get_bind(), "_pdos_release", None)
    _require(type(value) is Runtime, "发布包实际读取端尚未接通。", "INTEGRATION_REQUIRED", 503)
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
            "工程与制造决定须由当前具名本人分别办理。",
            "NAMED_DECISION_REQUIRED",
            403,
        )


def _row(s, ctx, pid, identity, revision=None):
    require_access(s, ctx, pid)
    row = snapshot_get(s, Package, identity, scope_id=pid)
    _require(
        row is not None
        and (row.tenant_id, row.category_id, row.product_id)
        == (ctx.tenant_id, ctx.category_id, pid)
        and (row.visibility != "private" or row.owner_id == ctx.requester_id),
        "所选固定发布包不可读取。",
        "FORBIDDEN_SCOPE",
        403,
    )
    _require(revision is None or row.revision == revision, "发布包版本不匹配。", "VERSION_CONFLICT")
    plan = PackagePlan.model_validate(row.body)
    _require(
        rules.digest(row.body) == row.body_sha256
        and plan.scope.tenant_id == row.tenant_id
        and plan.scope.product_id == row.product_id
        and plan.scope.project_id == row.project_id
        and plan.category_id == row.category_id
        and plan.owner_id == row.owner_id
        and plan.declaration.visibility == row.visibility,
        "固定发布包内容绑定不完整。",
        "INTEGRITY_MISMATCH",
        503,
    )
    return row, plan


def _pointer(s, ctx, pid, series_id, *, lock=False):
    query = select(Current).where(
        Current.tenant_id == ctx.tenant_id,
        Current.category_id == ctx.category_id,
        Current.product_id == pid,
        Current.series_id == series_id,
    )
    if lock:
        return s.scalar(query.with_for_update().execution_options(populate_existing=True))
    return snapshot_scalar(s, (Current, series_id), query, scope_id=pid)


def _pointer_value(row):
    return (
        {
            "id": str(row.series_id),
            "version": {"id": str(row.version_id), "revision": row.revision},
            "epoch": row.epoch,
        }
        if row is not None
        else None
    )


def _intent(ctx, command, payload):
    return digest(
        {
            "operation": command.operation,
            "category": command.category_id,
            "product": command.product_id,
            "payload": semantic(payload),
            "named_actor": ctx.requester_id,
            "source_revision": None,
            "private_owner": ctx.requester_id
            if getattr(payload, "visibility", "private") == "private"
            else None,
        }
    )


def _current_material(s, ctx, pid, material, basis):
    result = _runtime(s).owner.current(s, ctx, pid, material, source_basis=basis["material_owner"])
    extra = basis.get("decision_originals")
    if extra is not None:
        raw, _, _ = evidence._evidence(
            s,
            ctx,
            pid,
            extra["reads"],
            [SourceRef.model_validate(value) for value in extra["sources"]],
            io=False,
        )
        result = result is True and to_jsonable_python(raw) == extra["basis"]
    return result


def _assessments(plan):
    return {
        discipline: rules.evaluate(
            plan, discipline, plan.declaration.release_scope, at=now()
        ).model_dump(mode="json")
        for discipline in ("engineering", "manufacturing")
    }


@dataclass(frozen=True)
class Bound:
    material: ReleaseMaterial
    basis: dict
    plan: PackagePlan
    candidate: object
    reads: tuple
    authority: dict
    diagnostics: tuple
    previous: object = None
    package: object = None
    pointer: object = None


def _load(s, ctx, command, product, payload, *, require_reads=True):
    _command(s, ctx, command, product, payload)
    runtime = _runtime(s)
    previous, package, pointer, authority = None, None, None, {}
    if command.operation == ASSEMBLE:
        declaration = payload
        if payload.previous is not None:
            previous, _ = _row(s, ctx, product.id, payload.previous.id, payload.previous.revision)
            _require(
                previous.project_id == payload.project_id
                and previous.owner_id == ctx.requester_id
                and previous.visibility == payload.visibility,
                "续版须保留实际项目、原属主和受众。",
                "FORBIDDEN_SCOPE",
                403,
            )
            pointer = _pointer(s, ctx, product.id, previous.series_id, lock=True)
            _require(
                pointer is not None
                and pointer.version_id == previous.id
                and pointer.revision == previous.revision,
                "须基于当前固定包显式续版。",
                "VERSION_CONFLICT",
            )
    else:
        package, saved = _row(s, ctx, product.id, payload.package.id, payload.package.revision)
        declaration = saved.declaration
        pointer = _pointer(s, ctx, product.id, package.series_id, lock=True)
        _require(
            pointer is not None and pointer.version_id == package.id,
            "放行须明确选择当前固定包。",
            "VERSION_CONFLICT",
        )
    read = runtime.owner.read(s, ctx, product.id, declaration)
    plan = rules.assemble(
        declaration,
        read.material,
        owner_id=previous.owner_id
        if previous
        else package.owner_id
        if package
        else ctx.requester_id,
    )
    if package is not None:
        _require(
            plan == saved, "固定包的直接材料或政策水位已变化，请明确续版。", "RECHECK_REQUIRED"
        )
        candidate = rules.prepare_decision(
            command.operation, payload, payload.package, saved, ctx=ctx, at=now()
        )
        authority = professional.assess(
            s,
            ctx,
            product.id,
            package.project_id,
            command.operation,
            payload.purpose,
            now(),
            write=True,
        )
    else:
        candidate = plan
    basis = {"material_owner": deepcopy(read.source_basis)}
    reads_by_id = {value.artifact_id: value for value in read.required_source_read_set}
    if package is not None:
        sources = rules._sources(payload)
        for value in (
            *authority.get("required_source_read_set", ()),
            *(
                {"artifact_id": source.id, "expected_revision": source.revision}
                for source in sources
            ),
        ):
            value = SourceRead.model_validate(value)
            existing = reads_by_id.get(value.artifact_id)
            _require(existing is None or existing == value, "同一原件不能选择两个版本。")
            reads_by_id[value.artifact_id] = value
        original_reads = {value.artifact_id for value in read.required_source_read_set}
        extra_reads = [value.model_dump(mode="json") for value in reads_by_id.values()]
        original_sources = [source.model_dump(mode="json") for source in sources]
        raw, private = {}, False
        for already_read in (True, False):
            selected_reads = [
                value
                for identity, value in reads_by_id.items()
                if (identity in original_reads) == already_read
            ]
            if not selected_reads:
                continue
            selected_ids = {value.artifact_id for value in selected_reads}
            values, is_private, _ = evidence._evidence(
                s,
                ctx,
                product.id,
                [value.model_dump(mode="json") for value in selected_reads],
                [source for source in sources if source.id in selected_ids],
                io=not already_read,
            )
            raw.update(values)
            private |= is_private
        _require(
            not private or package.visibility == "private",
            "私人决定依据不能扩大为共享放行。",
            "FORBIDDEN_SCOPE",
            403,
        )
        basis["decision_originals"] = {
            "reads": extra_reads,
            "sources": original_sources,
            "basis": to_jsonable_python(raw),
        }
    reads = tuple(sorted(reads_by_id.values(), key=lambda value: str(value.artifact_id)))
    if require_reads:
        _require(
            {(value.artifact_id, value.expected_revision) for value in command.source_read_set}
            == {(value.artifact_id, value.expected_revision) for value in reads},
            "须提交本轮实际最小来源读集。",
            "RECHECK_REQUIRED",
        )
    return Bound(
        read.material,
        basis,
        plan,
        candidate,
        reads,
        authority,
        tuple(read.gaps),
        previous,
        package,
        _pointer_value(pointer),
    )


def _review(command, bound):
    candidate = bound.candidate.model_dump(mode="json")
    if "prepared_at" in candidate:
        candidate["prepared_at"] = None
    return {
        "operation": command.operation,
        "before": deepcopy(bound.pointer),
        "after": candidate,
        "assessments": _assessments(bound.plan),
        "authority": deepcopy(bound.authority),
        "required_source_read_set": [value.model_dump(mode="json") for value in bound.reads],
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
    _require(
        _current_material(s, ctx, pid, bound.material, bound.basis) is True,
        "直接来源或材料水位已变化。",
        "RECHECK_REQUIRED",
    )
    if bound.previous is not None or bound.package is not None:
        previous = bound.previous or bound.package
        pointer = _pointer(s, ctx, pid, previous.series_id, lock=True)
        expected_id = (
            written.id if written is not None and isinstance(written, Package) else previous.id
        )
        _require(
            pointer is not None and pointer.version_id == expected_id,
            "固定包当前版本已变化。",
            "VERSION_CONFLICT",
        )
    if bound.authority:
        _require(
            signature_current(s, ctx, pid, bound.plan.scope.project_id, bound.authority)
            and professional.authority_time_current(bound.authority, now()),
            "本次具名职责的适用水位已变化。",
            "QUALIFICATION_REQUIRED",
            403,
        )


def apply_validated(s, ctx, command, product, payload, phase):
    _phase(s, ctx, command, product, payload, phase)
    _require(
        command.operation == ASSEMBLE, "独立专业决定须消费共同 T2。", "NAMED_DECISION_REQUIRED", 403
    )
    bound = phase.bound
    _still_current(s, ctx, product.id, bound)
    phase.used = True
    identity, receipt_id = uuid4(), uuid4()
    previous = bound.previous
    row = Package(
        id=identity,
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        product_id=product.id,
        project_id=payload.project_id,
        series_id=previous.series_id if previous else identity,
        revision=previous.revision + 1 if previous else 1,
        previous_id=previous.id if previous else None,
        previous_revision=previous.revision if previous else None,
        owner_id=bound.plan.owner_id,
        writer_id=ctx.actor_id,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        visibility=payload.visibility,
        purpose=payload.purpose,
        status="assembled",
        operation=ASSEMBLE,
        body=bound.plan.model_dump(mode="json"),
        body_sha256=rules.digest(bound.plan),
        material_snapshot=bound.material.model_dump(mode="json"),
        input_snapshot=_saved_input(command, payload, phase),
        source_basis=deepcopy(bound.basis),
        sources=[value.model_dump(mode="json") for value in bound.plan.sources],
        required_source_read_set=[value.model_dump(mode="json") for value in bound.reads],
        command_id=command.command_id,
        receipt_id=receipt_id,
        intent_digest=_intent(ctx, command, payload),
        request_digest=command_digest(command),
        created_at=now(),
    )
    row.prepared_receipt_id, row._release_phase = receipt_id, phase
    s.add(row)
    s.flush([row])
    if previous is None:
        s.add(
            Current(
                id=uuid4(),
                tenant_id=ctx.tenant_id,
                category_id=ctx.category_id,
                product_id=product.id,
                project_id=payload.project_id,
                series_id=identity,
                owner_id=row.owner_id,
                visibility=row.visibility,
                version_id=identity,
                revision=1,
                epoch=1,
            )
        )
    else:
        pointer = _pointer(s, ctx, product.id, previous.series_id, lock=True)
        pointer.version_id, pointer.revision = identity, row.revision
        pointer.epoch += 1
    return row, "release_package", row.visibility


def apply_prepared_write(s, ctx, command, product, payload, phase, *, consumption):
    _phase(s, ctx, command, product, payload, phase)
    _require(command.operation in _T2, "只允许分别办理工程或制造决定。")
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
    receipt_id, package = uuid4(), bound.package
    row = Decision(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        product_id=product.id,
        project_id=package.project_id,
        package_id=package.id,
        package_revision=package.revision,
        revision=1,
        discipline=bound.candidate.discipline,
        owner_id=ctx.requester_id,
        writer_id=ctx.actor_id,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        visibility=package.visibility,
        purpose=payload.purpose,
        operation=command.operation,
        status="approved",
        write_tier="T2",
        body=bound.candidate.model_dump(mode="json"),
        body_sha256=rules.digest(bound.candidate),
        input_snapshot=_saved_input(command, payload, phase),
        material_snapshot=bound.material.model_dump(mode="json"),
        authority_snapshot=deepcopy(bound.authority),
        source_basis=deepcopy(bound.basis),
        sources=[
            v.model_dump(mode="json")
            for v in dict.fromkeys((*bound.plan.sources, *rules._sources(payload)))
        ],
        required_source_read_set=[v.model_dump(mode="json") for v in bound.reads],
        command_id=command.command_id,
        receipt_id=receipt_id,
        request_digest=command_digest(command),
        created_at=now(),
        **live.storage_columns(),
    )
    row.prepared_receipt_id, row.confirmation_id, row._release_phase = (
        receipt_id,
        live.proof_id,
        phase,
    )
    s.add(row)
    return row, "release_decision", row.visibility


def finalize_receipt(s, ctx, command, product, payload, subject, receipt):
    phase = getattr(subject, "_release_phase", None)
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
    del subject._release_phase


def _header(row, pointer, status):
    return {
        "id": str(row.id),
        "revision": row.revision,
        "project_id": str(row.project_id),
        "purpose": row.purpose,
        "status": row.status,
        "receipt_id": str(row.receipt_id),
        "current": _pointer_value(pointer),
        "applicability": status,
    }


def get_package(s, ctx, pid, identity):
    row, plan = _row(s, ctx, pid, identity)
    current = _pointer(s, ctx, pid, row.series_id)
    status = "current"
    try:
        if not _current_material(
            s, ctx, pid, ReleaseMaterial.model_validate(row.material_snapshot), row.source_basis
        ):
            status = "needs_recheck"
    except DomainError as error:
        if error.status in {401, 403}:
            raise
        if error.code not in {
            "SOURCE_STALE",
            "RECHECK_REQUIRED",
            "SOURCE_UNAVAILABLE",
            "VERSION_CONFLICT",
        }:
            raise
        status = "needs_recheck"
    decisions = []
    for decision in s.scalars(
        select(Decision)
        .where(
            Decision.tenant_id == ctx.tenant_id,
            Decision.product_id == pid,
            Decision.package_id == row.id,
        )
        .order_by(Decision.created_at, Decision.id)
    ):
        applicable = status == "current" and signature_current(
            s, ctx, pid, row.project_id, decision.authority_snapshot
        )
        decisions.append(
            {
                "id": str(decision.id),
                "revision": decision.revision,
                "discipline": decision.discipline,
                "package": {"id": str(row.id), "revision": row.revision},
                "decision": deepcopy(decision.body),
                "authority": deepcopy(decision.authority_snapshot),
                "receipt_id": str(decision.receipt_id),
                "applicability": "current" if applicable else "needs_recheck",
            }
        )
    return row, {
        **_header(row, current, status),
        "package": plan.model_dump(mode="json"),
        "assessments": _assessments(plan),
        "decisions": decisions,
    }


def list_packages(s, ctx, pid, *, project_id, history_cursor=None):
    require_access(s, ctx, pid)
    from pdos_next.domain.projects.models import Project

    project = snapshot_get(s, Project, project_id, scope_id=pid)
    _require(
        project is not None
        and (project.tenant_id, project.category_id, project.product_id)
        == (ctx.tenant_id, ctx.category_id, pid)
        and (project.visibility != "private" or project.owner_id == ctx.requester_id),
        "所选项目不可读取。",
        "FORBIDDEN_SCOPE",
        403,
    )
    query = select(Package).where(
        Package.tenant_id == ctx.tenant_id,
        Package.category_id == ctx.category_id,
        Package.product_id == pid,
        Package.project_id == project_id,
    )
    if history_cursor is not None:
        try:
            query = query.where(Package.id < UUID(history_cursor))
        except ValueError as error:
            raise DomainError("SOURCE_STALE", "发布包分页位置无效。", 422) from error
    rows = list(s.scalars(query.order_by(Package.id.desc()).limit(21)))
    pointers = {
        row.series_id: row
        for row in s.scalars(
            select(Current).where(
                Current.tenant_id == ctx.tenant_id,
                Current.category_id == ctx.category_id,
                Current.product_id == pid,
                Current.project_id == project_id,
                Current.series_id.in_({row.series_id for row in rows[:20]}),
            )
        )
    }
    return {
        "items": [_header(row, pointers.get(row.series_id), "not_checked") for row in rows[:20]],
        "next_cursor": str(rows[19].id) if len(rows) > 20 else None,
    }


def inputs(s, ctx, pid, command):
    require_access(s, ctx, pid, write=True, lock=True)
    product = s.get(Product, pid)
    _require(
        command.product_id == pid and command.operation in PAYLOADS,
        "请选择当前型号的发布包操作。",
        "FORBIDDEN_SCOPE",
        403,
    )
    payload = PAYLOADS[command.operation].model_validate(command.payload)
    bound = _load(s, ctx, command, product, payload, require_reads=False)
    return to_jsonable_python(
        {
            "operation": command.operation,
            "payload": payload.model_dump(mode="json"),
            "required_source_read_set": bound.reads,
            "candidate": bound.candidate,
            "assessments": _assessments(bound.plan),
            "authority": bound.authority,
            "diagnostics": bound.diagnostics,
        }
    )
