"""Actual read-only candidate material owner; unregistered and never a writer.

Phase identities attest only this module's completed reads in the current UOW.
They do not attest confirmation consumption, seven effectiveness gates or a
public preview-to-write handoff. That handoff needs the real saved proof anchor.
"""

# Initialize actual registry before importing its domain children.
# ruff: noqa: I001
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from weakref import WeakKeyDictionary, ref
from uuid import UUID

from pdos_next.service import Context, digest

import anchor as anchors
import anchor_owner
import anchor_storage
import candidate_commands as commands
import fact_atom_storage as guards
from pdos_next.domain.capa_verification import service as followup
from pdos_next.domain.capa_verification.schemas import CandidateBinding, CandidateInspect
from pdos_next.domain.professional_authority import service as professional
from pdos_next.domain.professional_authority.models import ProfessionalFact
from pdos_next.domain.quality_execution import evidence, policy
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Principal, Product
from pdos_next.quality_result_bridge import _runtime_stamp


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
    valid_until: datetime


# This is an opaque identity registry, NOT a source/professional result cache.
# Every require performs independent actual owner IO. No Session.info state.
_PHASES = WeakKeyDictionary()


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
        Grant.product_id == pid,
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
        "原完成锚不在本次Issue/租户/产品范围。",
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
        bool(value.get("facts_revision"))
        and bool(value.get("fact_refs"))
        and value.get("valid_until") is not None,
        "INTEGRATION_REQUIRED",
        "专业准入缺少完整事实/期限。",
        503,
    )
    if basis.nature == "real" and value.get("synthetic") is not False:
        raise DomainError("NATURE_MISMATCH", "合成专业依据不能授真实候选资格。", 403)
    # The existing assessor does not delimit future activation. Read every
    # exact fact it actually selected, including inactive/negative scope facts.
    refs = value["fact_refs"]
    _require(
        isinstance(refs, list) and len(refs) <= professional.MAX_FACTS,
        "INTEGRATION_REQUIRED",
        "专业事实范围必须完整有界。",
        503,
    )
    deadlines = [_deadline(value["valid_until"])]
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
        row = guards._one(
            s,
            ProfessionalFact,
            ProfessionalFact.tenant_id == ctx.tenant_id,
            ProfessionalFact.product_id == pid,
            ProfessionalFact.project_id == basis.scope.project_id,
            ProfessionalFact.subject_id == ctx.requester_id,
            ProfessionalFact.id == identity,
            ProfessionalFact.revision == revision,
        )
        if row.state == "active":
            deadlines.extend(v for v in (row.valid_from, row.valid_until) if v > evaluated_at)
    value["valid_until"] = min(deadlines).isoformat()
    _require(_clock() < min(deadlines), detail="专业来源或事实查询期间已越过资格期限/激活边界。")
    return value


def _policy(s, ctx, pid, basis):
    value = deepcopy(policy.assess(s, ctx, pid, basis.scope.project_id, basis.purpose))
    _require(
        value.get("nature") == basis.nature
        and value.get("valid_until") is not None
        and value.get("facts_revision")
        and value.get("id")
        and value.get("revision"),
        "INTEGRATION_REQUIRED",
        "当前政策缺少真实完整范围/期限或事实性质不符。",
        503,
    )
    if basis.visibility == "product" and value.get("private") is not False:
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


def _material(phase, *, stable=False):
    return {
        "payload_semantic": deepcopy(phase.payload_semantic),
        "stable_anchor": _anchor_material(phase.anchor)
        if stable
        else phase.anchor.model_dump(mode="json"),
        "binding": phase.binding.model_dump(mode="json"),
        "inspection": phase.inspection.model_dump(mode="json"),
        "raw_source_basis": deepcopy(phase.raw_source_basis),
        "required_source_read_set": anchors.json_value(phase.required_source_read_set),
        "sources": anchors.json_value(phase.sources),
        "authority_snapshot": deepcopy(phase.authority_snapshot),
        "policy_snapshot": deepcopy(phase.policy_snapshot),
        "owner_id": str(phase.owner_id),
        "visibility": phase.visibility,
        "current_issue_revision": phase.current_issue_revision,
    }


def _deadline(value):
    try:
        at = datetime.fromisoformat(value)
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError
        return at.astimezone(UTC)
    except (TypeError, ValueError):
        raise DomainError("INTEGRATION_REQUIRED", "专业或政策缺少明确真实有效期限。", 503) from None


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
        if private and basis.visibility == "product":
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
        # Independent post-all-owner/source IO proof refresh. Keep the FIRST
        # complete anchor/full proof unchanged, compare only frozen stable paths.
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
        final_inspection = followup.inspect_candidate(
            s, ctx, pid, binding, at=_clock(), write=False
        )
        # Compare the original bounded inspection before adding host closure.
        _require(
            final_inspection.model_dump(mode="json", exclude={"inspection_sha256"})
            == original_inspection,
            detail="末端候选输出、映射或缺项改变。",
        )
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
        valid_until = min(
            caller_until,
            after_until,
            _deadline(authority["valid_until"]),
            _deadline(published["valid_until"]),
        )
        _require(checked_at < valid_until, "SOURCE_STALE", "全部IO后当前授权/专业/政策已到期。")
        _require(checked_at >= final_anchor.checked_at, detail="末端真实时钟早于最后原锚读取。")
        return PreparedCandidate(
            commands.semantic(payload),
            actual.anchor,
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
            valid_until,
        )


def _seal(phase):
    return digest(
        {
            "material": _material(phase),
            "checked_at": phase.checked_at,
            "valid_until": phase.valid_until,
            "runtime": phase.runtime_binding,
        }
    )


def prepare_candidate(s, ctx, product_id, payload, *, origin_ref):
    phase = _read(s, ctx, product_id, payload, origin_ref)
    _PHASES[phase] = (
        ref(s),
        digest(vars(ctx)),
        _seal(phase),
        phase.uow,
        phase.runtime_binding,
    )
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
    fresh = _read(s, ctx, product_id, payload, phase.anchor.origin.ref)
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
    _require(
        _seal(phase) == _PHASES[phase][2],
        "CANDIDATE_PREPARED_BINDING_CHANGED",
        "准备材料或期限已改变。",
    )
    return _material(phase)  # checked_at is excluded; original proof clocks remain.


def invalidate_prepared_candidate(phase):
    _require(
        isinstance(phase, PreparedCandidate) and phase in _PHASES,
        "CANDIDATE_PREPARED_OWNER_REQUIRED",
        "准备阶段已失效或并非实际模块产生。",
        503,
    )
    del _PHASES[phase]


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
        phase.checked_at <= at <= _clock() and at < phase.valid_until,
        "SOURCE_STALE",
        "保存时点已越过当前授权/专业/政策边界。",
    )
    return phase
