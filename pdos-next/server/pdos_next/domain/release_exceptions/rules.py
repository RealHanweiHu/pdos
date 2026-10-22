"""Finite scoped candidates, without IO, policy grants or replacement T2."""

from datetime import datetime

from pdos_next.domain.release import rules as release
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import SourceRef
from pdos_next.service import Context

from .constants import DECIDE, WITHDRAW
from .schemas import ActualData, DecidePayload, ExceptionPlan, WithdrawActualData, WithdrawPayload


def _require(test, detail, code="INTEGRITY_MISMATCH", status=409):
    if not test:
        raise DomainError(code, detail, status)


def semantic(payload):
    value = payload.model_dump(mode="json")
    value.pop("approval_token", None)
    return value


def scope_covers(bound, selected):
    """Contain explicit selected values without turning omitted limits into all."""
    if not release.scope_contains(bound, selected):
        return False
    for name in ("lots", "lines", "regions", "site", "quantity", "unit"):
        allowed, chosen = getattr(bound, name), getattr(selected, name)
        if chosen is None and allowed is not None:
            return False
        if isinstance(chosen, tuple) and not chosen and allowed != ():
            return False
    return True


def _caller(ctx, scope, category_id, at):
    _require(at.utcoffset() is not None, "须使用服务器aware时钟。", "VALIDATION_FAILED", 422)
    _require(
        type(ctx) is Context
        and ctx.actor_id == ctx.requester_id
        and ctx.run_id is None
        and ctx.agent_run_id is None
        and ctx.agent_call_id is None
        and ctx.tenant_id == scope.tenant_id
        and ctx.category_id == category_id,
        "例外决定须由当前真实范围内的具名本人办理。",
        "FORBIDDEN_SCOPE",
        403,
    )


def _sources(actual, payload):
    # Normalize exact reference fields; a subtype adds no owner attestation.
    verified = tuple(
        SourceRef.model_validate({name: getattr(value, name) for name in SourceRef.model_fields})
        for value in actual.sources
    )
    required = release._sources(payload)
    sources = tuple(dict.fromkeys((*verified, *required)))
    reads = release._canonical_reads(actual.required_source_read_set)
    read_set = {(value.artifact_id, value.expected_revision) for value in reads}
    current = (
        actual.sources_current is True
        and set(required) <= set(verified)
        and all(
            (value.id, value.revision) in read_set for value in sources if value.kind == "artifact"
        )
    )
    return sources, reads, current


def prepare_decide(payload, data, *, ctx: Context, at: datetime):
    payload, data = DecidePayload.model_validate(payload), ActualData.model_validate(data)
    package, policy = data.package, data.policy
    _caller(ctx, package.scope, package.category_id, at)
    _require(
        payload.basis_package == data.package_ref, "须引用实际固定包版本。", "VERSION_CONFLICT"
    )
    _require(
        payload.purpose == package.declaration.purpose,
        "例外用途须精确等于固定包用途。",
        "FORBIDDEN_SCOPE",
        403,
    )
    _require(
        payload.expiry is None or at < payload.expiry,
        "新例外决定的明确有效期已经结束。",
        "SOURCE_STALE",
    )
    unknown, blocked = [], []
    if data.package_current is not True:
        unknown.append("BASIS_PACKAGE_NOT_CURRENT")
    if not scope_covers(package.declaration.release_scope, payload.release_scope):
        unknown.append("PACKAGE_SCOPE_NOT_COVERED")
    if policy is None or data.policy_fact is None or package.policy is None:
        unknown.append("RELEASE_POLICY_MISSING")
    else:
        _require(
            policy.scope == package.scope
            and policy.category_id == package.category_id
            and policy.purpose == payload.purpose,
            "政策须属于实际同品类、项目和用途。",
            "FORBIDDEN_SCOPE",
            403,
        )
        if (
            data.policy_current is not True
            or policy.status != "active"
            or package.policy.version != policy.policy_version
            or (policy.valid_from is not None and at < policy.valid_from)
            or (policy.valid_until is not None and at >= policy.valid_until)
        ):
            unknown.append("RELEASE_POLICY_NOT_CURRENT")
        if policy.subject_config != package.declaration.subject_config or not scope_covers(
            policy.release_scope, payload.release_scope
        ):
            unknown.append("POLICY_SCOPE_NOT_COVERED")
    checks = {value.key: value for value in package.checks}
    _require(len(checks) == len(package.checks), "实际包检查身份不能重复。")
    policy_rules = {rule.id: rule for rule in policy.rules} if policy is not None else {}
    for key in payload.check_keys:
        check, rule = checks.get(key), policy_rules.get(key)
        if check is None:
            unknown.append(key + ":CHECK_MISSING")
            continue
        if not check.applicable or check.discipline not in {payload.discipline, "both"}:
            blocked.append(key + ":CHECK_OUTSIDE_DISCIPLINE_OR_APPLICABILITY")
        if check.non_waivable or (rule is not None and not rule.waivable):
            blocked.append(key + ":NON_WAIVABLE")
        if check.release_scope is not None and not scope_covers(
            check.release_scope, payload.release_scope
        ):
            unknown.append(key + ":CHECK_SCOPE_NOT_COVERED")
        if rule is None:
            unknown.append(key + ":POLICY_RULE_MISSING")
        elif (
            rule.discipline not in {payload.discipline, "both"}
            or payload.purpose not in rule.allowed_purpose
            or not scope_covers(rule.scope, payload.release_scope)
        ):
            unknown.append(key + ":POLICY_RULE_NOT_COVERED")
        # A check may remain unknown: this is permission for the stated bounded
        # controls, never an assertion that its missing evidence now satisfies it.
    sources, reads, verified = _sources(data, payload)
    if not verified:
        unknown.append("EXCEPTION_ORIGINAL_NOT_VERIFIED")
    return ExceptionPlan(
        operation=DECIDE,
        action="approved",
        declaration=semantic(payload),
        scope=package.scope,
        category_id=package.category_id,
        owner_id=package.owner_id,
        visibility=package.declaration.visibility,
        discipline=payload.discipline,
        basis_package=data.package_ref,
        policy_fact=data.policy_fact,
        policy_version=policy.policy_version if policy is not None else None,
        subject_config=package.declaration.subject_config,
        release_scope=payload.release_scope,
        purpose=payload.purpose,
        check_keys=payload.check_keys,
        selected_checks=tuple(checks[key] for key in payload.check_keys if key in checks),
        limits=payload.limits,
        risk_controls=payload.risk_controls,
        expiry=payload.expiry,
        sources=sources,
        required_source_read_set=reads,
        signers=(ctx.actor_id,),
        prepared_at=at,
        reason=payload.reason,
        state="BLOCKED" if blocked else "UNKNOWN" if unknown else "READY",
        unknown=tuple(dict.fromkeys(unknown)),
        blocked=tuple(dict.fromkeys(blocked)),
    )


def prepare_withdraw(payload, data, *, ctx: Context, at: datetime):
    payload, data = WithdrawPayload.model_validate(payload), WithdrawActualData.model_validate(data)
    previous = data.previous
    _caller(ctx, previous.scope, previous.category_id, at)
    _require(payload.exception == data.exception, "须引用原例外准确版本。", "VERSION_CONFLICT")
    _require(
        previous.operation == DECIDE
        and previous.action == "approved"
        and previous.state == "READY"
        and not previous.unknown
        and not previous.blocked
        and previous.policy_fact is not None
        and previous.policy_version is not None,
        "撤回须绑定实际原批准内容，候选DTO本身不能代替保存证明。",
    )
    sources, reads, verified = _sources(data, payload)
    unknown = []
    if data.current is not True:
        unknown.append("EXCEPTION_NOT_CURRENT")
    if not verified:
        unknown.append("WITHDRAWAL_ORIGINAL_NOT_VERIFIED")
    # The retained atom proves old material. Only this withdrawal's direct
    # originals enter its new read set; old expiry does not prevent withdrawal.
    return previous.model_copy(
        update={
            "operation": WITHDRAW,
            "action": "withdrawn",
            "declaration": semantic(payload),
            "previous": data.exception,
            "sources": sources,
            "required_source_read_set": reads,
            "signers": (ctx.actor_id,),
            "prepared_at": at,
            "reason": payload.reason,
            "state": "UNKNOWN" if unknown else "READY",
            "unknown": tuple(unknown),
            "blocked": (),
        }
    )


def require_decidable(plan):
    plan = ExceptionPlan.model_validate(plan)
    _require(
        plan.state == "READY" and not plan.unknown and not plan.blocked,
        "例外依据、可豁免范围或直接原件仍有阻塞或未知。",
        "MISSING_REQUIRED_EVIDENCE",
    )
    return plan
