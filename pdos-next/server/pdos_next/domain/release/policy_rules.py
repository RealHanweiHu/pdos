"""Finite policy projections over actual owner facts, without IO or grants.

Publication authority, registered original bytes, scope and Current pointers
belong to the host owner. This module does not turn a policy DTO into proof.
"""

from datetime import datetime
from typing import get_args

from pydantic import ValidationError

from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import RunState, Scope, SourceRef

from .policy_schemas import PolicyFact, PolicyMaterial
from .schemas import ObjectRef, PolicyBasis, ReleaseCheck, ReleaseScope, SubjectConfiguration

_KINDS = frozenset(get_args(ObjectRef.model_fields["kind"].annotation))
_RUN_STATES = frozenset(get_args(RunState))
_DOCUMENTS = frozenset({"artifact", "work_instruction", "control_plan"})
_DISCIPLINES = ("engineering", "manufacturing")


def _require(test, detail, code="INTEGRITY_MISMATCH", status=409):
    if not test:
        raise DomainError(code, detail, status)


def _disjoint(left, right):
    if left.site is not None and right.site is not None and left.site != right.site:
        return True
    for name in ("lots", "lines", "regions"):
        a, b = getattr(left, name), getattr(right, name)
        if a and b and not set(a) & set(b):
            return True
    return False


def _covers(bound, selected):
    # None/empty never grants all values. Two omitted dimensions stay omitted;
    # a selected value must have an actual, explicit covering policy value.
    for name in ("lots", "lines", "regions"):
        a, b = getattr(bound, name), getattr(selected, name)
        if b is None:
            if a is not None:
                return False
        elif a is None or not set(b) <= set(a):
            return False
    if selected.site != bound.site:
        return False
    if selected.quantity is None:
        return bound.quantity is None
    return (
        bound.quantity is not None
        and selected.unit == bound.unit
        and selected.quantity <= bound.quantity
    )


def _selected(expression, facts, *, default=None, allowed=None, extra=()):
    if set(expression) - {"op", "ref", "kind", *extra}:
        return None
    if "ref" in expression and "kind" in expression:
        return None
    if "ref" in expression:
        try:
            target = ObjectRef.model_validate(expression["ref"])
        except (ValidationError, TypeError):
            return None
        if allowed is not None and target.kind not in allowed:
            return None
        return tuple(value for value in facts if value.ref == target)
    kind = expression.get("kind", default)
    if kind is None:
        return tuple(value for value in facts if value.ref.kind in allowed) if allowed else None
    if (
        not isinstance(kind, str)
        or kind not in _KINDS
        or (allowed is not None and kind not in allowed)
    ):
        return None
    return tuple(value for value in facts if value.ref.kind == kind)


def _current(values):
    return bool(values) and all(
        isinstance(value.value, dict) and value.value.get("_release_current") is True
        for value in values
    )


def _condition(expression, facts, selected):
    if expression == {"op": "always"}:
        return True
    if expression.get("op") == "scope" and set(expression) == {"op", "release_scope"}:
        try:
            bound = ReleaseScope.model_validate(expression["release_scope"])
        except (ValidationError, TypeError):
            return None
        return False if _disjoint(bound, selected) else True if _covers(bound, selected) else None
    if expression.get("op") == "object_exists":
        values = _selected(expression, facts)
        # Missing/unreadable evidence does not establish non-applicability.
        return True if values is not None and _current(values) else None
    return None


def _evidence(rule, facts):
    values = []
    for target in rule.required_evidence:
        selected = (
            tuple(value for value in facts if value.ref == target)
            if isinstance(target, ObjectRef)
            else tuple(value for value in facts if value.ref.kind == target)
            if target in _KINDS
            else ()
        )
        if not _current(selected):
            return False
        values.extend(selected)
    return all(_current((value,)) for value in values)


def _predicate(expression, facts):
    op = expression.get("op")
    if op == "object_exists":
        values = _selected(expression, facts)
    elif op == "document_present":
        values = _selected(expression, facts, allowed=_DOCUMENTS)
    elif op == "manufacturing_publication_present":
        values = _selected(
            expression,
            facts,
            default="manufacturing_publication",
            allowed={"manufacturing_publication"},
        )
    elif op == "test_run_status":
        values = _selected(
            expression, facts, default="test_run", allowed={"test_run"}, extra=("status",)
        )
        wanted = expression.get("status")
        if not isinstance(wanted, str) or wanted not in _RUN_STATES or not _current(values or ()):
            return None
        states = []
        for value in values:
            snapshot = value.value.get("snapshot", value.value)
            status = snapshot.get("status") if isinstance(snapshot, dict) else None
            if not isinstance(status, str) or status not in _RUN_STATES:
                return None
            states.append(status)
        # This checks lifecycle only. result/computed_results are never inferred
        # from reviewed/disposed, nor is 'pass' accepted as a lifecycle state.
        return all(value == wanted for value in states)
    else:
        return None
    return True if values is not None and _current(values) else None


def evaluate(
    material,
    *,
    scope,
    category_id,
    subject_config,
    release_scope,
    purpose,
    facts,
    sources,
    at: datetime,
):
    """Return internal policy/check candidates; no IO, signer or authorization.

    Facts/sources must come from the same actual owner collection. Unknown
    applicability is an applicable UNKNOWN check so it cannot disappear from
    required readiness. Unsupported policy expressions are preserved on input.
    """
    policy = PolicyMaterial.model_validate(material)
    scope = Scope.model_validate(scope)
    config = SubjectConfiguration.model_validate(subject_config)
    selected = ReleaseScope.model_validate(release_scope)
    originals = tuple(dict.fromkeys(SourceRef.model_validate(value) for value in sources))
    _require(bool(originals), "发布政策须固定实际原件来源。")
    _require(at.utcoffset() is not None, "政策求值须使用服务器aware时钟。")
    _require(
        policy.scope == scope and policy.category_id == category_id and policy.purpose == purpose,
        "发布政策不在实际品类、项目或用途范围。",
        "FORBIDDEN_SCOPE",
        403,
    )
    values = tuple(PolicyFact.model_validate(value) for value in facts)
    _require(
        len({(value.ref.kind, value.ref.id) for value in values}) == len(values),
        "同一政策对象只能提供一个实际固定版本。",
    )
    basis = PolicyBasis(version=policy.policy_version, sources=originals)
    checks = []
    used = {rule.id for rule in policy.rules}

    def missing(discipline, detail, suffix):
        key = f"policy:{discipline}:{suffix}"
        while key in used:
            key += ":unknown"
        used.add(key)
        checks.append(
            ReleaseCheck(
                key=key,
                discipline=discipline,
                applicable=True,
                required=True,
                state="unknown",
                non_waivable=True,
                detail=detail,
                sources=originals,
                release_scope=selected,
            )
        )

    unavailable = (
        "政策已撤回。"
        if policy.status != "active"
        else "政策尚未生效或已经到期。"
        if not (
            (policy.valid_from is None or policy.valid_from <= at)
            and (policy.valid_until is None or at < policy.valid_until)
        )
        else "政策未覆盖实际定义、双配置或本轮数量/批次/场地/产线/地区范围。"
        if policy.subject_config != config or not _covers(policy.release_scope, selected)
        else None
    )
    if unavailable:
        for discipline in _DISCIPLINES:
            missing(discipline, unavailable, "not_covered")
        return basis, tuple(checks)

    for rule in policy.rules:
        if purpose not in rule.allowed_purpose and rule.allowed_purpose:
            applicable = False
        elif _disjoint(rule.scope, selected):
            applicable = False
        elif not _covers(rule.scope, selected):
            applicable = None
        elif not rule.allowed_purpose:
            applicable = None
        else:
            applicable = _condition(rule.applicable_if, values, selected)
        detail = f"规则 {rule.id}@{rule.version}；责任角色：{rule.responsible_role}。"
        if applicable is False:
            state, detail = "satisfied", detail + "已明确不适用于本轮用途或范围。"
        elif applicable is None:
            state, detail = "unknown", detail + "规则适用条件未知，不能略过。"
        elif rule.freshness != "current" or not _evidence(rule, values):
            state, detail = "unknown", detail + "必要实际证据或当前水位尚未核实。"
        else:
            result = _predicate(rule.predicate, values)
            state = "satisfied" if result is True else "blocked" if result is False else "unknown"
            detail += (
                "实际具名谓词满足。"
                if result is True
                else "实际具名谓词不满足。"
                if result is False
                else "谓词不支持或实际输入不充分。"
            )
        checks.append(
            ReleaseCheck(
                key=rule.id,
                discipline=rule.discipline,
                applicable=applicable is not False,
                required=rule.severity in {"hard", "required"},
                state=state,
                non_waivable=not rule.waivable,
                detail=detail,
                sources=originals,
                release_scope=rule.scope,
            )
        )
    for discipline in _DISCIPLINES:
        if not any(rule.discipline in {discipline, "both"} for rule in policy.rules):
            missing(discipline, "当前受控政策未提供本专业规则。", "rules_missing")
    return basis, tuple(checks)
