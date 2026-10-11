"""Actual read-only candidate material owner; unregistered and never a writer.

Phase identities attest only this module's completed reads in the current UOW.
They do not attest confirmation consumption, seven effectiveness gates or a
public preview-to-write handoff. That handoff needs the real saved proof anchor.
"""

from pdos_next.database import category_for_product


# Initialize actual registry before importing its domain children.
# ruff: noqa: I001
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from weakref import WeakKeyDictionary, ref
from uuid import UUID

from pdos_next.service import Context, digest

from . import anchor as anchors
from . import anchor_owner
from . import anchor_storage
from . import candidate_commands as commands
from . import candidate_storage
from . import candidate_anchor_restore as restoration
from . import fact_atom_storage as guards
from pdos_next.domain.capa_verification import service as followup
from pdos_next.domain.capa_verification.models import CapaVerificationEvidence
from pdos_next.domain.capa_verification.schemas import CandidateBinding, CandidateInspect
from pdos_next.domain.professional_authority import service as professional
from pdos_next.domain.professional_authority.models import ProfessionalFact
from pdos_next.domain.quality_execution import evidence, policy
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Principal, Product
from pdos_next.request_proof import batch_read, scope_is_held
from pdos_next.contracts import Command
from pdos_next.quality_result_bridge import _runtime_stamp
from sqlalchemy import select


@dataclass(frozen=True, eq=False, slots=True, weakref_slot=True)
class PreparedCandidate:
    payload_semantic: dict
    anchor: anchors.StableCapaAnchor
    binding: CandidateBinding
    inspection: CandidateInspect
    raw_source_basis: list
    required_source_read_set: tuple
    sources: tuple
    authority_snapshot: dict
    policy_snapshot: dict
    owner_id: UUID
    visibility: str
    current_issue_revision: int
    session: object
    uow: tuple
    runtime_binding: str
    checked_at: datetime
    valid_until: datetime | None
    caller_expires_at: datetime | None = None
    # Same-phase server metadata only; never a payload/review or saved fact.
    persistent_origin_ref: candidate_storage.FactRef | None = None


# This is an opaque identity registry, NOT a source/professional result cache.
# Every require performs independent actual owner IO. No Session.info state.
_PHASES = WeakKeyDictionary()
_WRITE_PHASES = WeakKeyDictionary()


@dataclass(frozen=True)
class _WritePreparation:
    command: Command
    proof: object
    restored: restoration.RestoredCandidateAnchor
    restore_host: restoration.CandidateAnchorRestoreHost
    proof_immutable_sha256: str
    reviewed_snapshot: dict
    caller_watermark: tuple
    project_snapshot: object
    current_snapshot: object


def _require(value, code="SOURCE_STALE", detail="候选材料在本次读取期间发生变化。", status=409):
    if not value:
        raise DomainError(code, detail, status)


def _clock():
    return datetime.now(UTC)


def _runtime(s):
    engine = s.get_bind()
    registry = getattr(engine, "_pdos_quality_policy_issuers", {})
    return digest(
        {
            "result": _runtime_stamp(s),
            "policy_epochs": getattr(engine, "_pdos_quality_policy_epochs", {}),
            "policy_issuers": {k: [id(v), v.epoch] for k, v in registry.items()},
            "operation_roles": sorted(professional.OPERATION_ROLES.get(commands.OPERATION, ())),
            "ports": [
                id(anchor_owner.read_anchor_from_actual_owner),
                id(followup.load_followup_basis),
                id(followup.inspect_candidate),
                id(professional.assess),
                id(policy.assess),
                id(evidence.source_basis),
                id(evidence.refs_from_exact),
                id(candidate_storage.read_candidate),
                id(commands.semantic_owner),
            ],
        }
    )


def _phase(s, ctx, uow, caller, stamp):
    guards._same_uow(s, uow, ctx, caller)
    _require(_runtime(s) == stamp, detail="候选读取期间宿主入口、issuer或运行epoch已变化。")


def _caller(s, ctx, pid):
    guards._acl(s, ctx, pid)
    product = guards._one(s, Product, Product.tenant_id == ctx.tenant_id, Product.id == pid)
    person = guards._one(
        s, Principal, Principal.tenant_id == ctx.tenant_id, Principal.id == ctx.actor_id
    )
    grant = guards._one(
        s,
        Grant,
        Grant.tenant_id == ctx.tenant_id,
        Grant.category_id == category_for_product(pid),
        Grant.principal_id == ctx.actor_id,
    )
    _require(grant.can_write is True, "FORBIDDEN_SCOPE", "当前本人没有产品办理权限。", 403)
    return (
        product.id,
        product.tenant_id,
        product.revision,
        getattr(product, "lifecycle_epoch", None),
        person.id,
        person.kind,
        person.active,
        person.access_epoch,
        grant.id,
        grant.access_epoch,
        grant.can_write,
        grant.expires_at,
    ), grant.expires_at


def _current(s, ctx, pid, actual, payload):
    origin = actual.anchor.origin
    desc = actual.origin_descriptor
    _require(
        (origin.issue_id, origin.scope.tenant_id, origin.scope.product_id)
        == (payload.issue_id, ctx.tenant_id, pid),
        "FORBIDDEN_SCOPE",
        "原完成锚不在本次Issue/租户/型号范围。",
        403,
    )
    _require(
        actual.needs_lineage_owner is False
        and desc.needs_lineage_owner is False
        and desc.current.ref == origin.ref,
        "CANDIDATE_LINEAGE_OWNER_REQUIRED",
        "v1仅接受Current与原完成版相同，有限谱系owner尚未接通。",
        503,
    )
    _require(
        payload.expected_issue_revision == desc.current.ref.revision,
        "VERSION_CONFLICT",
        "当前Issue版已变化。",
    )
    _require(
        payload.visibility == origin.visibility,
        "CANDIDATE_AUDIENCE_MISMATCH",
        "候选请求受众必须精确继承实际原系列。",
        403,
    )
    return desc.current.ref.revision


def _authority(s, ctx, pid, basis):
    if not professional.OPERATION_ROLES.get(commands.OPERATION):
        raise DomainError(
            "PROFESSIONAL_OPERATION_NOT_CONFIGURED", "候选T1当前专业职责矩阵尚未配置。", 503
        )
    evaluated_at = _clock()
    value = deepcopy(
        professional.assess(
            s,
            ctx,
            pid,
            basis.scope.project_id,
            commands.OPERATION,
            basis.purpose,
            evaluated_at,
            write=False,
        )
    )
    _require(
        value.get("scope") == basis.scope.model_dump(mode="json")
        and value.get("subject_id") == str(ctx.requester_id)
        and value.get("operation") == commands.OPERATION
        and value.get("purpose") == basis.purpose,
        "INTEGRATION_REQUIRED",
        "当前专业端口没有返回精确候选办理绑定。",
        503,
    )
    _require(
        value.get("authorized") is True and value.get("qualified") is True,
        "QUALIFICATION_REQUIRED",
        "当前具名候选职责与资格不足。",
        403,
    )
    _require(
        bool(value.get("facts_revision")) and bool(value.get("fact_refs")),
        "INTEGRATION_REQUIRED",
        "专业准入缺少完整事实。",
        503,
    )
    if basis.nature == "real" and value.get("synthetic") is not False:
        raise DomainError("NATURE_MISMATCH", "合成专业依据不能授真实候选资格。", 403)
    # The existing assessor does not delimit future activation. Read every
    # exact fact it actually selected, including inactive/negative scope facts.
    refs = value["fact_refs"]
    _require(
        isinstance(refs, list),
        "INTEGRATION_REQUIRED",
        "专业事实范围必须完整。",
        503,
    )
    exact_refs = []
    for item in refs:
        try:
            identity = UUID(item["id"])
            revision = item["revision"]
        except (KeyError, TypeError, ValueError):
            raise DomainError("INTEGRATION_REQUIRED", "专业事实引用缺少精确身份。", 503) from None
        _require(
            type(revision) is int and revision > 0,
            "INTEGRATION_REQUIRED",
            "专业事实版本不能猜测。",
            503,
        )
        exact_refs.append((identity, revision))
    if s.info.get("read_snapshot") and scope_is_held(s, pid):
        # Full RLS-loaded rows are held by this actual RR request. Check every
        # exact scope/version after one batch, including negative scope facts.
        rows = batch_read(s, ProfessionalFact, {identity for identity, _ in exact_refs})
        for identity, revision in exact_refs:
            row = rows[identity]
            _require(
                row is not None
                and (row.tenant_id, row.product_id, row.project_id, row.subject_id, row.revision)
                == (ctx.tenant_id, pid, basis.scope.project_id, ctx.requester_id, revision),
                "FACT_EXACT_GROUP_ROW_MISSING",
                "专业事实须逐条匹配当前租户、型号、项目、本人和固定版本。",
                503,
            )
    else:
        for identity, revision in exact_refs:
            guards._one(
                s,
                ProfessionalFact,
                ProfessionalFact.tenant_id == ctx.tenant_id,
                ProfessionalFact.product_id == pid,
                ProfessionalFact.project_id == basis.scope.project_id,
                ProfessionalFact.subject_id == ctx.requester_id,
                ProfessionalFact.id == identity,
                ProfessionalFact.revision == revision,
            )
    _require(
        professional.authority_time_current(value, _clock()),
        detail="专业来源或事实查询期间实际职责或资格已失效。",
    )
    return value


def _policy(s, ctx, pid, basis):
    value = deepcopy(policy.assess(s, ctx, pid, basis.scope.project_id, basis.purpose))
    _require(
        value.get("nature") == basis.nature
        and value.get("facts_revision")
        and value.get("id")
        and value.get("revision"),
        "INTEGRATION_REQUIRED",
        "当前政策缺少真实完整范围或事实性质不符。",
        503,
    )
    if basis.visibility == "category" and value.get("private") is not False:
        raise DomainError("CANDIDATE_AUDIENCE_MISMATCH", "私人政策不能进入共享候选。", 403)
    return value


def _anchor_material(value):
    # Only these three frozen per-result paths are observational. Do not delete
    # recursive keys or reconstruct a full-proof SHA from this stable material.
    return {
        "origin": value.origin.model_dump(mode="json"),
        "failures": [anchors.stable_failure_material(v) for v in value.failures],
        "sources": anchors.json_value(value.origin_sources),
        "reads": anchors.json_value(value.origin_required_source_read_set),
        "safety": anchors.json_value(value.origin_source_basis),
        "material_sha256": value.material_sha256,
        "stable_failure_material_sha256": value.stable_failure_material_sha256,
        "origin_source_basis_sha256": value.origin_source_basis_sha256,
    }


def _saved_origin_anchor(s, ctx, pid, payload, actual):
    """Read the same persisted root selected by the rule publisher.

    The stored full proof is historical material, never a live qualification.
    It is reusable only after the independently read actual original failure,
    Current, bytes and complete safety closure match the frozen stable material.
    """
    origin = actual.anchor.origin
    rows = list(
        s.scalars(
            select(CapaVerificationEvidence)
            .where(
                CapaVerificationEvidence.tenant_id == ctx.tenant_id,
                CapaVerificationEvidence.product_id == pid,
                CapaVerificationEvidence.issue_id == payload.issue_id,
                CapaVerificationEvidence.issue_version_id == origin.ref.id,
                CapaVerificationEvidence.issue_revision == origin.ref.revision,
            )
            .order_by(CapaVerificationEvidence.created_at, CapaVerificationEvidence.id)
            .limit(1)
            .execution_options(populate_existing=True, autoflush=False)
        )
    )
    if not rows:
        return None
    selected = candidate_storage.read_candidate(
        s, ctx, pid, rows[0].id, semantic_owner=commands.semantic_owner()
    )
    saved = selected.body.stable_anchor
    _require(
        saved.origin == origin and _anchor_material(saved) == _anchor_material(actual.anchor),
        detail="最早持久锚与当前真实原失败、来源安全或原完成版不一致。",
    )
    return selected


def _same_saved_origin_anchor(before, after):
    _require(
        (before is None and after is None)
        or (
            before is not None
            and after is not None
            and before.ref == after.ref
            and before.body.stable_anchor == after.body.stable_anchor
        ),
        detail="全部owner读取后最早持久锚或其完整共同保存组改变。",
    )


def _material(phase, *, stable=False):
    return {
        "payload_semantic": deepcopy(phase.payload_semantic),
        "stable_anchor": _anchor_material(phase.anchor)
        if stable
        else phase.anchor.model_dump(mode="json"),
        "binding": phase.binding.model_dump(mode="json"),
        "inspection": phase.inspection.model_dump(mode="json"),
        "raw_source_basis": deepcopy(phase.raw_source_basis),
        "required_source_read_set": [anchors.json_value(v) for v in phase.required_source_read_set],
        "sources": [anchors.json_value(v) for v in phase.sources],
        "authority_snapshot": deepcopy(phase.authority_snapshot),
        "policy_snapshot": deepcopy(phase.policy_snapshot),
        "owner_id": str(phase.owner_id),
        "visibility": phase.visibility,
        "current_issue_revision": phase.current_issue_revision,
    }


def _read(s, ctx, pid, payload, origin_ref):
    payload = commands._payload(payload)
    origin_ref = anchors.VersionRef.model_validate(commands._attributes(origin_ref))
    _require(
        isinstance(ctx, Context) and isinstance(pid, UUID),
        "FORBIDDEN_SCOPE",
        "需实际当前Context与产品。",
        403,
    )
    uow, caller = guards._uow(s), digest(vars(ctx))
    stamp = _runtime(s)
    readonly_snapshot = bool(s.info.get("read_snapshot")) and scope_is_held(s, pid)
    with s.no_autoflush:
        before_caller, caller_until = _caller(s, ctx, pid)
        actual = anchor_owner.read_anchor_from_actual_owner(
            s, ctx, pid, payload.issue_id, origin_ref
        )
        revision = _current(s, ctx, pid, actual, payload)
        _phase(s, ctx, uow, caller, stamp)
        basis = followup.load_followup_basis(s, ctx, pid, payload.issue_id, revision, write=False)
        _require(
            (
                basis.scope,
                basis.issue_id,
                basis.issue_version_id,
                basis.issue_revision,
                basis.capa_id,
                basis.owner_id,
                basis.visibility,
                basis.purpose,
            )
            == (
                actual.anchor.origin.scope,
                payload.issue_id,
                origin_ref.id,
                revision,
                payload.capa_id,
                actual.anchor.origin.owner_id,
                payload.visibility,
                actual.anchor.origin.purpose,
            ),
            "CANDIDATE_REQUEST_BINDING_MISMATCH",
            "实际CAPA依据与原完成锚不一致。",
        )
        saved_origin = _saved_origin_anchor(s, ctx, pid, payload, actual)
        fixed_anchor = actual.anchor if saved_origin is None else saved_origin.body.stable_anchor
        _phase(s, ctx, uow, caller, stamp)
        binding = CandidateBinding(
            basis=basis,
            remediation_link_refs=payload.remediation_link_refs,
            mappings=payload.mappings,
        )
        commands.check_candidate_request(payload, binding, current_issue_revision=revision)
        inspection = followup.inspect_candidate(s, ctx, pid, binding, at=_clock(), write=False)
        inspection = CandidateInspect.model_validate(commands._attributes(inspection))
        original_inspection = inspection.model_dump(mode="json", exclude={"inspection_sha256"})
        _require(
            inspection.inspection_sha256
            == digest(
                inspection.model_dump(mode="json", exclude={"inspection_sha256", "candidate_ref"})
            ),
            "INTEGRITY_MISMATCH",
            "实际inspection完整材料摘要不能核对。",
        )
        _require(inspection.binding == binding, "SOURCE_STALE", "候选核对不得偷偷换入新CAPA依据。")
        user_sources = evidence.refs_from_exact(s, ctx, pid, payload.sources)
        mapping_sources = evidence.refs_from_exact(
            s, ctx, pid, tuple(v for m in payload.mappings for v in m.applicability_sources)
        )
        authority, published = _authority(s, ctx, pid, basis), _policy(s, ctx, pid, basis)
        reads = evidence.merge_reads(
            basis.required_source_read_set,
            actual.anchor.origin_required_source_read_set,
            inspection.required_source_read_set,
            authority["required_source_read_set"],
            published["required_source_read_set"],
            [{"artifact_id": str(v.id), "expected_revision": v.revision} for v in user_sources],
        )
        sources = evidence.union_sources(
            actual.anchor.origin_sources,
            basis.sources,
            user_sources,
            mapping_sources,
            published["sources"],
        )
        raw, private = evidence.source_basis(s, ctx, pid, reads)
        raw = deepcopy(raw)  # Preserve sparse actual original/registration keysets.
        selected_ids = {
            str(r.artifact_id): r.expected_revision for r in inspection.required_source_read_set
        }
        subset = [v for v in raw if selected_ids.get(v["id"]) == v["revision"]]
        _require(
            len(subset) == len(selected_ids) and digest(subset) == inspection.source_basis_sha256,
            detail="原inspection来源闭包摘要不能漂白。",
        )
        if private and basis.visibility == "category":
            raise DomainError(
                "CANDIDATE_AUDIENCE_MISMATCH", "任何私人来源都不能进入共享候选。", 403
            )
        # Preserve original basis/source digest; only inspection expands to the
        # COMPLETE current professional/policy/user/output/anchor closure.
        raw_basis, _ = evidence.source_basis(s, ctx, pid, basis.required_source_read_set)
        _require(digest(raw_basis) == basis.source_basis_sha256, detail="固定Basis安全摘要已漂移。")
        inspection_raw = inspection.model_dump(mode="json")
        inspection_raw.update(
            required_source_read_set=reads,
            source_basis_sha256=digest(raw),
            inspection_sha256="0" * 64,
        )
        inspection_raw["inspection_sha256"] = digest(
            {
                k: v
                for k, v in inspection_raw.items()
                if k not in {"inspection_sha256", "candidate_ref"}
            }
        )
        inspection = CandidateInspect.model_validate(inspection_raw)
        _phase(s, ctx, uow, caller, stamp)
        # RR/READ ONLY holds the same actual rows throughout this request. Keep
        # the first owner proof; later IO still precedes scope/runtime and real
        # deadline checks below. Command/write preparation keeps its refresh.
        final_anchor = actual
        if readonly_snapshot:
            _require(s.info.get("read_snapshot") and scope_is_held(s, pid))
        else:
            final_anchor = anchor_owner.read_anchor_from_actual_owner(
                s, ctx, pid, payload.issue_id, origin_ref
            )
            _require(
                _anchor_material(final_anchor.anchor) == _anchor_material(actual.anchor),
                detail="末端原完成锚或固定失败依据改变。",
            )
            _require(
                final_anchor.origin_descriptor == actual.origin_descriptor,
                detail="末端Current/Project/共同保存组改变。",
            )
        _current(s, ctx, pid, final_anchor, payload)
        if not readonly_snapshot:
            final_inspection = followup.inspect_candidate(
                s, ctx, pid, binding, at=_clock(), write=False
            )
            # Compare the original inspection before adding host closure.
            _require(
                final_inspection.model_dump(mode="json", exclude={"inspection_sha256"})
                == original_inspection,
                detail="末端候选输出、映射或缺项改变。",
            )
        # Re-read the persisted root/group after original/output owner IO.
        # Source, professional/policy, Current, caller and real clock checks
        # remain AFTER this additional IO; the stored proof grants no gate.
        final_saved_origin = _saved_origin_anchor(s, ctx, pid, payload, final_anchor)
        _same_saved_origin_anchor(saved_origin, final_saved_origin)
        _require(
            _authority(s, ctx, pid, basis) == authority
            and _policy(s, ctx, pid, basis) == published,
            detail="全部读取后专业或政策依据改变。",
        )
        after, private = evidence.source_basis(s, ctx, pid, reads)
        _require(after == raw, detail="末端完整来源/安全epoch改变。")
        _require(
            not private or basis.visibility == "private",
            "CANDIDATE_AUDIENCE_MISMATCH",
            "末端私有来源不能扩围。",
            403,
        )
        # Last source IO may outlive earlier scope reads. Actual exact row,
        # Current, Project and caller are read once more, then real clock last.
        row, issue = anchor_storage._version(
            s, ctx, pid, payload.issue_id, origin_ref, basis.scope.project_id
        )
        _require(issue == actual.anchor.origin.issue, detail="最后来源IO后原Issue改变。")
        _require(
            anchor_storage._current(s, ctx, pid, row) == actual.origin_descriptor.current
            and anchor_storage._project(s, ctx, pid, basis.scope.project_id)
            == actual.origin_descriptor.project,
            detail="最后来源IO后Current或Project改变。",
        )
        after_caller, after_until = _caller(s, ctx, pid)
        _require(after_caller == before_caller, detail="本人/Grant访问epoch或产品已经改变。")
        _phase(s, ctx, uow, caller, stamp)
        checked_at = _clock()
        _require(
            all(value is None or checked_at < value for value in (caller_until, after_until))
            and professional.authority_time_current(authority, checked_at)
            and policy.policy_time_current(published, checked_at),
            "SOURCE_STALE",
            "全部IO后当前授权或实际专业/政策条件已失效。",
        )
        _require(checked_at >= final_anchor.checked_at, detail="末端真实时钟早于最后原锚读取。")
        return PreparedCandidate(
            commands.semantic(payload),
            fixed_anchor,
            binding,
            inspection,
            raw,
            tuple(anchors.SourceRead.model_validate(r) for r in reads),
            sources,
            authority,
            published,
            basis.owner_id,
            basis.visibility,
            revision,
            s,
            uow,
            stamp,
            checked_at,
            None,
            after_until,
            saved_origin.ref if saved_origin is not None else None,
        )


def _seal_material(phase, material):
    return digest(
        {
            "material": material,
            "checked_at": phase.checked_at,
            "valid_until": phase.valid_until,
            "caller_expires_at": phase.caller_expires_at,
            "runtime": phase.runtime_binding,
            "persistent_origin_ref": None
            if phase.persistent_origin_ref is None
            else phase.persistent_origin_ref.model_dump(mode="json"),
        }
    )


def _seal(phase):
    return _seal_material(phase, _material(phase))


def prepare_candidate(s, ctx, product_id, payload, *, origin_ref):
    phase = _read(s, ctx, product_id, payload, origin_ref)
    return _register(s, ctx, phase)


def _register(s, ctx, phase):
    _PHASES[phase] = (
        ref(s),
        digest(vars(ctx)),
        _seal(phase),
        phase.uow,
        phase.runtime_binding,
    )
    return phase


def _immutable_proof(s, ctx, command, payload, proof):
    """Whole persisted material; consumed is exclusively the common host's gate.

    After the true common transition the ORM may hold consumed=True while SQL
    still holds False before its first flush. Neither value attests consumption
    here. The writer separately requires the actual LiveConsumption marker.
    """
    state = restoration.consumption._proof_state(s, proof)
    columns = set(restoration.PROOF_COLUMNS) - {"consumed"}
    _require(
        not columns & state.unloaded
        and not any(state.attrs[k].history.has_changes() for k in columns),
        "CANDIDATE_PERSISTED_PROOF_CHANGED",
        "原确认的完整非消费材料须已加载且未修改。",
    )
    loaded = {k: deepcopy(getattr(proof, k)) for k in columns}
    saved = restoration._db_proof(s, ctx, command.product_id, proof.id)
    _require(type(proof.consumed) is bool and type(saved["consumed"]) is bool)
    del saved["consumed"]
    _require(loaded == saved, "CANDIDATE_PERSISTED_PROOF_CHANGED")
    _require(
        commands._payload(command.payload) == commands._payload(payload)
        and proof.token_hash == digest(payload.confirmation_token)
        and proof.payload_digest
        == restoration.material_digest(ctx, command, payload, restoration.commands),
        "CANDIDATE_PROOF_BINDING_MISMATCH",
    )
    return digest(saved)


def _write_review(phase, original_anchor):
    review = _material(phase)
    # ONLY the full original anchor is restored. Every other current material
    # comes from this independently read phase and must equal the true review.
    review["stable_anchor"] = original_anchor.model_dump(mode="json")
    return {"operation": commands.OPERATION, **review}


def _finish_write(s, ctx, command, payload, fresh, binding):
    _require(
        _write_review(fresh, binding.restored.anchor) == binding.reviewed_snapshot,
        "CANDIDATE_REVIEW_MATERIAL_CHANGED",
        "当前专业/政策/输出/来源须精确匹配原完整确认材料。",
    )
    _require(
        _anchor_material(fresh.anchor) == _anchor_material(binding.restored.anchor),
        detail="原失败/完成材料仅允许三条固定评估路径差异。",
    )
    _require(
        fresh.persistent_origin_ref is None or fresh.anchor == binding.restored.anchor,
        detail="原确认首锚与已经存在的最早持久根不一致，须重新预览而不能覆盖固定根。",
    )
    _require(
        _immutable_proof(s, ctx, command, payload, binding.proof) == binding.proof_immutable_sha256,
        "CANDIDATE_PERSISTED_PROOF_CHANGED",
    )
    # The last raw proof query is still IO: Current/Project/caller follow it.
    origin = binding.restored.anchor.origin
    row, issue = anchor_storage._version(
        s, ctx, command.product_id, payload.issue_id, origin.ref, origin.scope.project_id
    )
    current = anchor_storage._current(s, ctx, command.product_id, row)
    project = anchor_storage._project(s, ctx, command.product_id, origin.scope.project_id)
    _require(
        issue == origin.issue
        and current.ref == origin.ref
        and current.ref.revision == payload.expected_issue_revision
        and current == binding.current_snapshot
        and project.scope == origin.scope
        and project == binding.project_snapshot,
        detail="全部owner读取后原Issue/Current/Project已变化。",
    )
    caller, caller_until = _caller(s, ctx, command.product_id)
    _require(
        caller == binding.caller_watermark and caller[2] == command.expected_revision,
        detail="原共同产品水位或本人当前访问epoch已变化。",
    )
    _phase(s, ctx, fresh.uow, digest(vars(ctx)), fresh.runtime_binding)
    at = _clock()
    until = binding.restored.expires_at
    _require(
        fresh.checked_at <= at < until
        and (caller_until is None or at < caller_until)
        and professional.authority_time_current(fresh.authority_snapshot, at)
        and policy.policy_time_current(fresh.policy_snapshot, at),
        detail="全部读取后实际专业/政策条件、本人授权或T1确认已失效。",
    )
    return replace(
        fresh,
        anchor=binding.restored.anchor,
        checked_at=at,
        valid_until=until,
        caller_expires_at=caller_until,
    )


def prepare_candidate_write(s, ctx, command, payload, proof, restore_host):
    """Real unconsumed proof anchor -> independent full current write materials.

    No consumption, SQL write, flush, commit or Receipt is performed here.
    """
    _require(
        type(restore_host) is restoration.CandidateAnchorRestoreHost
        and isinstance(command, Command)
        and command.operation == commands.OPERATION,
        "CANDIDATE_ANCHOR_RESTORE_REQUIRED",
        "需服务器实际配置的原确认恢复host和候选Command。",
        503,
    )
    payload = commands._payload(payload)
    uow, caller, stamp = guards._uow(s), digest(vars(ctx)), _runtime(s)
    restored = restore_host.restore(s, ctx, command, payload, proof)
    restore_host.require_restored(s, ctx, command, payload, proof, restored)
    fresh = _read(s, ctx, command.product_id, payload, restored.anchor.origin.ref)
    _phase(s, ctx, uow, caller, stamp)
    watermark, _ = _caller(s, ctx, command.product_id)
    binding = _WritePreparation(
        command.model_copy(deep=True),
        proof,
        restored,
        restore_host,
        _immutable_proof(s, ctx, command, payload, proof),
        deepcopy(restored.reviewed_snapshot),
        watermark,
        anchor_storage._project(s, ctx, command.product_id, fresh.binding.basis.scope.project_id),
        anchor_storage._current(
            s,
            ctx,
            command.product_id,
            anchor_storage._version(
                s,
                ctx,
                command.product_id,
                payload.issue_id,
                fresh.anchor.origin.ref,
                fresh.binding.basis.scope.project_id,
            )[0],
        ),
    )
    phase = _finish_write(s, ctx, command, payload, fresh, binding)
    _phase(s, ctx, uow, caller, stamp)
    _register(s, ctx, phase)
    _WRITE_PHASES[phase] = binding
    return phase


def _registered(s, ctx, pid, payload, phase):
    saved = _PHASES.get(phase) if isinstance(phase, PreparedCandidate) else None
    _require(
        saved is not None and saved[0]() is s and phase.session is s,
        "CANDIDATE_PREPARED_OWNER_REQUIRED",
        "需本模块在本次Session实际产生的未失效阶段。",
        503,
    )
    _require(
        saved[1] == digest(vars(ctx))
        and phase.payload_semantic == commands.semantic(payload)
        and phase.binding.basis.scope.product_id == pid
        and _seal(phase) == saved[2]
        and phase.runtime_binding == saved[4]
        and phase.uow[1] is saved[3][1]
        and len(phase.uow[0]) == len(saved[3][0])
        and all(a is b for a, b in zip(phase.uow[0], saved[3][0], strict=True)),
        "CANDIDATE_PREPARED_BINDING_CHANGED",
        "候选阶段/调用者/原请求材料已改变。",
    )
    _phase(s, ctx, saved[3], saved[1], saved[4])
    return saved


def require_prepared_candidate(s, ctx, product_id, payload, phase):
    _registered(s, ctx, product_id, payload, phase)
    payload = commands._payload(payload)
    fresh = _read(s, ctx, product_id, payload, phase.anchor.origin.ref)
    _require(
        fresh.persistent_origin_ref == phase.persistent_origin_ref,
        detail="本次phase读取期间最早持久根或完整保存组改变。",
    )
    binding = _WRITE_PHASES.get(phase)
    if binding is not None:
        fresh = _finish_write(s, ctx, binding.command, payload, fresh, binding)
    _require(
        _material(fresh, stable=True) == _material(phase, stable=True),
        detail="本phase最终独立重核的候选材料已经改变。",
    )
    _registered(s, ctx, product_id, payload, phase)
    return phase  # Never re-seal the FIRST actual full proof/anchor.


def reviewed_candidate(phase):
    _require(
        isinstance(phase, PreparedCandidate) and phase in _PHASES,
        "CANDIDATE_PREPARED_OWNER_REQUIRED",
        "需真实准备阶段。",
        503,
    )
    material = _material(phase)
    _require(
        _seal_material(phase, material) == _PHASES[phase][2],
        "CANDIDATE_PREPARED_BINDING_CHANGED",
        "准备材料或期限已改变。",
    )
    return material  # Fresh independent JSON; original proof clocks remain.


def invalidate_prepared_candidate(phase):
    _require(
        isinstance(phase, PreparedCandidate) and phase in _PHASES,
        "CANDIDATE_PREPARED_OWNER_REQUIRED",
        "准备阶段已失效或并非实际模块产生。",
        503,
    )
    del _PHASES[phase]
    _WRITE_PHASES.pop(phase, None)


def require_prepared_candidate_clock(s, ctx, product_id, payload, phase, at):
    """No-IO final host clock/epoch guard; never replaces independent refresh."""
    _registered(s, ctx, product_id, payload, phase)
    _require(
        isinstance(at, datetime) and at.tzinfo is not None and at.utcoffset() is not None,
        "INVALID_TIME",
        "需宿主真实保存UTC时点。",
        422,
    )
    _require(
        phase.checked_at <= at <= _clock()
        and (phase.valid_until is None or at < phase.valid_until)
        and (phase.caller_expires_at is None or at < phase.caller_expires_at)
        and professional.authority_time_current(phase.authority_snapshot, at)
        and policy.policy_time_current(phase.policy_snapshot, at),
        "SOURCE_STALE",
        "保存时点已越过当前授权/专业/政策边界。",
    )
    return phase
