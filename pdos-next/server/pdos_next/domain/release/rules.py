"""Deterministic structural candidates; actual owners and common T2 remain required.

No IO, authority grant, token minting or saved approval lives here. Policy
applicability and separate exception decisions must come from the real owner.
An omitted category never becomes a global release gate or an all-scope grant.
"""

import json
from datetime import datetime
from hashlib import sha256
from uuid import UUID

from pydantic import BaseModel

from pdos_next.contracts import SourceRead
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import SourceRef
from pdos_next.service import Context

from .schemas import (
    ENGINEERING_APPROVE,
    MANUFACTURING_APPROVE,
    PAYLOADS,
    Assessment,
    DecisionPlan,
    ObjectRef,
    PackageAssemblePayload,
    PackagePlan,
    ReleaseMaterial,
    ReleaseScope,
)


def _require(test, detail, code="SOURCE_STALE", status=409):
    if not test:
        raise DomainError(code, detail, status)


def digest(value):
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def semantic(payload):
    value = payload.model_dump(mode="json")
    value.pop("approval_token", None)
    return value


def _sources(value):
    if isinstance(value, SourceRef):
        return (SourceRef.model_validate(value.model_dump(mode="json")),)
    if isinstance(value, BaseModel):
        return tuple(
            dict.fromkeys(
                source
                for key in type(value).model_fields
                for source in _sources(getattr(value, key))
            )
        )
    if isinstance(value, tuple):
        return tuple(dict.fromkeys(source for child in value for source in _sources(child)))
    return ()


def selected_objects(payload):
    config = payload.subject_config
    values = [
        ObjectRef(kind=kind, **ref.model_dump())
        for kind, ref in (
            ("definition", config.definition),
            ("engineering_configuration", config.engineering_configuration),
            ("process_revision", config.manufacturing_configuration),
        )
    ]
    for kind, refs in (
        (
            "manufacturing_publication",
            (payload.manufacturing_publication,)
            if payload.manufacturing_publication is not None
            else (),
        ),
        ("test_run", payload.verifications),
        ("pilot_run", payload.pilots),
        ("exception", payload.exceptions),
        ("build_lot", payload.release_scope.lots or ()),
        ("line", payload.release_scope.lines or ()),
    ):
        values.extend(ObjectRef(kind=kind, **ref.model_dump()) for ref in refs)
    return tuple(dict.fromkeys((*values, *payload.residuals, *payload.documents)))


def _canonical_reads(values):
    by_id = {}
    for value in values:
        read = SourceRead.model_validate(
            value.model_dump() if isinstance(value, BaseModel) else value
        )
        _require(
            read.artifact_id not in by_id or by_id[read.artifact_id] == read.expected_revision,
            "同一原件不能固定两个版本。",
        )
        by_id[read.artifact_id] = read.expected_revision
    return tuple(
        SourceRead(artifact_id=key, expected_revision=by_id[key]) for key in sorted(by_id, key=str)
    )


def assemble(payload, material, *, owner_id: UUID):
    payload, material = (
        PackageAssemblePayload.model_validate(payload),
        ReleaseMaterial.model_validate(material),
    )
    _require(
        payload.project_id == material.scope.project_id
        and payload.subject_config == material.subject_config
        and payload.release_scope == material.release_scope
        and payload.purpose == material.purpose,
        "发布包须固定实际项目、定义、双配置与用途。",
        "FORBIDDEN_SCOPE",
        403,
    )
    objects = {value.ref: value for value in material.objects}
    _require(
        len(objects) == len(material.objects)
        and set(selected_objects(payload)) == set(objects)
        and all(
            value.product_id == material.scope.product_id
            and value.project_id in (None, material.scope.project_id)
            for value in material.objects
        ),
        "实际owner须提供全部所选固定对象，不能替换或隐去遗留项。",
        "MISSING_REQUIRED_EVIDENCE",
        422,
    )
    sources = tuple(dict.fromkeys((*material.sources, *_sources(material))))
    _require(
        set(_sources(payload)) <= set(sources),
        "发布声明原文尚未由实际owner读取。",
        "MISSING_REQUIRED_EVIDENCE",
        422,
    )
    reads = _canonical_reads(material.required_source_read_set)
    expected = {(source.id, source.revision) for source in sources if source.kind == "artifact"}
    _require(
        expected <= {(read.artifact_id, read.expected_revision) for read in reads},
        "发布包须保留实际直接原件完整读集。",
        "MISSING_REQUIRED_EVIDENCE",
        422,
    )
    checks = material.checks
    _require(len({check.key for check in checks}) == len(checks), "政策检查身份不能重复。")
    _require(
        len({value.decision for value in material.exceptions}) == len(material.exceptions),
        "实际例外决定不能重复。",
    )
    evidence_digest = digest(
        {
            "objects": [value.model_dump(mode="json") for value in material.objects],
            "sources": [value.model_dump(mode="json") for value in sources],
            "reads": [value.model_dump(mode="json") for value in reads],
        }
    )
    body = {
        "declaration": semantic(payload),
        "material": material.model_dump(mode="json"),
        "owner_id": str(owner_id),
        "evidence_digest": evidence_digest,
    }
    return PackagePlan(
        scope=material.scope,
        category_id=material.category_id,
        product_revision=material.product_revision,
        owner_id=owner_id,
        declaration=payload,
        objects=material.objects,
        policy=material.policy,
        checks=checks,
        exceptions=material.exceptions,
        sources=sources,
        required_source_read_set=reads,
        evidence_digest=evidence_digest,
        body_sha256=digest(body),
    )


def scope_contains(bound: ReleaseScope, selected: ReleaseScope):
    """Only explicit covered values can contain a later constrained action."""
    for key in ("lots", "lines", "regions"):
        values, chosen = getattr(bound, key), getattr(selected, key)
        if chosen is not None and chosen and (values is None or not set(chosen) <= set(values)):
            return False
    if selected.site is not None and selected.site != bound.site:
        return False
    if selected.quantity is not None and (
        bound.quantity is None or selected.unit != bound.unit or selected.quantity > bound.quantity
    ):
        return False
    return True


def _overlap(left, right):
    if left.site is not None and right.site is not None and left.site != right.site:
        return False
    for key in ("lots", "lines", "regions"):
        a, b = getattr(left, key), getattr(right, key)
        if a is not None and b is not None and (a or b) and not set(a) & set(b):
            return False
    return True


def evaluate(package, discipline, release_scope, *, at: datetime):
    package = PackagePlan.model_validate(package)
    selected = ReleaseScope.model_validate(release_scope)
    _require(discipline in {"engineering", "manufacturing"}, "放行专业不明确。")
    _require(at.utcoffset() is not None, "须使用服务器aware时钟。")
    _require(
        scope_contains(package.declaration.release_scope, selected), "专业决定不能扩大固定包范围。"
    )
    checks = tuple(
        check
        for check in package.checks
        if check.discipline in {discipline, "both"}
        and check.applicable
        and check.required
        and (check.release_scope is None or _overlap(check.release_scope, selected))
    )
    blocked, unknown, conditions = [], [], []
    if package.policy is None:
        unknown.append("RELEASE_POLICY_MISSING")
    for check in checks:
        if check.state == "satisfied":
            continue
        candidates = tuple(
            value
            for value in package.exceptions
            if (check.exception is None or value.decision == check.exception)
            and check.key in value.check_keys
        )
        from .policy_rules import _covers

        permitted = tuple(
            value
            for value in candidates
            if (
                not check.non_waivable
                and value.decision in package.declaration.exceptions
                and value.state == "current"
                and value.discipline == discipline
                and value.scope == package.scope
                and value.subject_config == package.declaration.subject_config
                and value.purpose == package.declaration.purpose
                and package.policy is not None
                and value.policy_version == package.policy.version
                and _covers(value.release_scope, selected)
                and (value.expiry is None or at < value.expiry)
            )
        )
        if permitted:
            conditions.extend(value.decision for value in permitted)
        elif check.state == "unknown":
            unknown.append(check.key)
        else:
            blocked.append(check.key)
            if check.exception is not None and (
                not candidates or any(value.state == "unknown" for value in candidates)
            ):
                unknown.append(check.key + ":exception_unknown")
    state = (
        "BLOCKED"
        if blocked
        else "UNKNOWN"
        if unknown
        else "READY_WITH_CONDITIONS"
        if conditions
        else "READY"
    )
    return Assessment(
        discipline=discipline,
        state=state,
        checks=checks,
        blocked=tuple(blocked),
        unknown=tuple(unknown),
        conditions=tuple(dict.fromkeys(conditions)),
    )


def prepare_decision(operation, payload, package_ref, package, *, ctx: Context, at: datetime):
    _require(
        operation in {ENGINEERING_APPROVE, MANUFACTURING_APPROVE}, "只允许独立工程或制造决定。"
    )
    payload, package = (
        PAYLOADS[operation].model_validate(payload),
        PackagePlan.model_validate(package),
    )
    _require(
        type(ctx) is Context
        and ctx.actor_id == ctx.requester_id
        and ctx.run_id is None
        and ctx.tenant_id == package.scope.tenant_id
        and ctx.category_id == package.category_id,
        "候选签署人须绑定当前具名调用本人及实际品类。",
        "NAMED_DECISION_REQUIRED",
        403,
    )
    _require(
        payload.package == package_ref and payload.purpose == package.declaration.purpose,
        "决定须保留固定发布包版本与用途。",
    )
    _require(
        at.utcoffset() is not None and (payload.expiry is None or at < payload.expiry),
        "新决定的明确适用期限已过期。",
    )
    discipline = "engineering" if operation == ENGINEERING_APPROVE else "manufacturing"
    assessment = evaluate(package, discipline, payload.release_scope, at=at)
    exception_limits = tuple(
        limit
        for exception in package.exceptions
        if exception.decision in assessment.conditions
        for limit in exception.limits
    )
    # Limits are retained exact declarations; they never turn an unknown or hard
    # blocker into satisfied evidence. Authority and T2 consumption are separate.
    return DecisionPlan(
        operation=operation,
        discipline=discipline,
        package=payload.package,
        package_sha256=package.body_sha256,
        scope=package.scope,
        category_id=package.category_id,
        subject_config=package.declaration.subject_config,
        release_scope=payload.release_scope,
        purpose=payload.purpose,
        limits=(*package.declaration.limits, *payload.limits, *exception_limits),
        evidence_digest=package.evidence_digest,
        policy_version=package.policy.version if package.policy else None,
        input_snapshot=semantic(payload),
        signers=(ctx.actor_id,),
        expiry=payload.expiry,
        assessment=assessment,
        prepared_at=at,
    )


def require_decidable(candidate):
    """Necessary content guard only; never sufficient authority/common T2 proof."""
    candidate = DecisionPlan.model_validate(candidate)
    _require(
        candidate.assessment.state in {"READY", "READY_WITH_CONDITIONS"},
        "实际适用的必需政策检查仍有阻塞或未知，不能执行放行。",
    )
    return candidate
