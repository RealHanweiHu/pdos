"""Actual pure release consumption, not saved owner/current, authority or T2 proof."""

from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest

from pdos_next.domain.release import rules, schemas
from pdos_next.errors import DomainError
from tests.release.test_rules import AT
from tests.release.test_rules import case as release_case  # noqa: F401
from tests.release_exceptions.test_rules import case as exception_case  # noqa: F401


@pytest.fixture
def case(request):
    return request.getfixturevalue("exception_case")


def basis(case, **updates):
    """Explicit owner-input substitute from the separate exception candidate."""
    original = case.plan
    values = {
        name: getattr(original, name)
        for name in (
            "scope",
            "subject_config",
            "release_scope",
            "purpose",
            "policy_version",
            "discipline",
            "check_keys",
            "limits",
            "sources",
            "expiry",
        )
    }
    values.update(decision=case.ref, state="current")
    values.update(updates)
    return schemas.ExceptionBasis(**values)


def package(case, exceptions, *, checks=None, selected=None):
    selected = tuple(value.decision for value in exceptions) if selected is None else selected
    payload = case.package.declaration.model_copy(update={"exceptions": selected})
    material = case.base.material.model_copy(
        update={
            "checks": checks or case.package.checks,
            "exceptions": exceptions,
            "objects": (
                *case.base.material.objects,
                *(
                    schemas.FixedObject(
                        ref=schemas.ObjectRef(kind="exception", **value.model_dump()),
                        product_id=case.base.scope.product_id,
                        project_id=case.base.scope.project_id,
                        sha256="c" * 64,
                    )
                    for value in selected
                ),
            ),
        }
    )
    return rules.assemble(payload, material, owner_id=case.base.actor)


def candidate(case, plan, *, release_scope=None, at=AT):
    return rules.prepare_decision(
        schemas.MANUFACTURING_APPROVE,
        schemas.ManufacturingApprovePayload(
            package=case.base.package,
            release_scope=release_scope or case.payload.release_scope,
            purpose=case.payload.purpose,
            sources=(case.base.original,),
            reason="本人核对固定包及单独例外的实际适用范围",
        ),
        case.base.package,
        plan,
        ctx=case.base.ctx,
        at=at,
    )


def unknown_check(case, **updates):
    return case.check.model_copy(update={"state": "unknown", "exception": None, **updates})


def assert_not_decidable(value):
    with pytest.raises(DomainError) as error:
        rules.require_decidable(value)
    assert error.value.reason == "SOURCE_STALE"


def test_selected_waivable_unknown_is_conditional_without_rewriting_original_check(case):
    check, exception = unknown_check(case), basis(case)
    plan = package(case, (exception,), checks=(case.package.checks[0], check))
    before = deepcopy(plan.model_dump())
    decision = rules.require_decidable(candidate(case, plan))
    assert decision.assessment.state == "READY_WITH_CONDITIONS"
    assert decision.assessment.conditions == (exception.decision,)
    assert decision.assessment.unknown == decision.assessment.blocked == ()
    assert decision.assessment.checks == (check,) and check.state == "unknown"
    assert decision.limits == exception.limits
    assert plan.model_dump() == before
    assert rules.evaluate(plan, "engineering", case.payload.release_scope, at=AT).state == "READY"


@pytest.mark.parametrize("state", ["unknown", "blocked"])
def test_nonwaivable_original_never_borrows_an_otherwise_applicable_exception(case, state):
    check = unknown_check(case, state=state, non_waivable=True)
    plan = package(case, (basis(case),), checks=(case.package.checks[0], check))
    decision = candidate(case, plan)
    assert decision.assessment.state == state.upper()
    assert decision.assessment.conditions == ()
    assert decision.assessment.checks[0].non_waivable is True
    assert_not_decidable(decision)


@pytest.mark.parametrize("field", ["lots", "lines", "regions"])
@pytest.mark.parametrize("uncovered", [None, ()])
def test_omitted_or_empty_exception_bound_does_not_cover_real_selected_objects(
    case, field, uncovered
):
    check = unknown_check(case)
    bound = case.payload.release_scope.model_copy(update={field: uncovered})
    exception = basis(case, release_scope=bound)
    plan = package(case, (exception,), checks=(case.package.checks[0], check))
    decision = candidate(case, plan)
    assert decision.assessment.state == "UNKNOWN"
    assert decision.assessment.conditions == ()
    assert decision.assessment.unknown == (check.key,)
    assert plan.exceptions[0].release_scope == bound
    assert_not_decidable(decision)


@pytest.mark.parametrize("field", ["lots", "lines", "regions", "quantity"])
def test_selected_none_cannot_remove_an_explicit_exception_limit(case, field):
    check = unknown_check(case)
    plan = package(case, (basis(case),), checks=(case.package.checks[0], check))
    updates = {field: None, **({"unit": None} if field == "quantity" else {})}
    selected = case.payload.release_scope.model_copy(update=updates)
    decision = candidate(case, plan, release_scope=selected)
    assert decision.assessment.state == "UNKNOWN"
    assert decision.assessment.conditions == ()
    assert_not_decidable(decision)


def test_separate_partial_exceptions_do_not_combine_into_whole_scope_permission(case):
    check = unknown_check(case)
    exceptions = tuple(
        basis(
            case,
            decision=schemas.VersionRef(id=uuid4(), revision=1),
            release_scope=case.payload.release_scope.model_copy(update={"regions": (region,)}),
        )
        for region in case.payload.release_scope.regions
    )
    plan = package(case, exceptions, checks=(case.package.checks[0], check))
    full = candidate(case, plan)
    assert full.assessment.state == "UNKNOWN" and full.assessment.conditions == ()
    assert_not_decidable(full)
    # Each bounded decision remains usable for its own explicit selected scope.
    for exception in exceptions:
        narrow = rules.require_decidable(
            candidate(case, plan, release_scope=exception.release_scope)
        )
        assert narrow.assessment.state == "READY_WITH_CONDITIONS"
        assert narrow.assessment.conditions == (exception.decision,)


def test_multiple_explicit_exceptions_can_cover_distinct_checks_without_hiding_either(case):
    first = unknown_check(case)
    second = first.model_copy(update={"key": "separate-waivable-check", "state": "blocked"})
    first_exception = basis(case)
    second_exception = basis(
        case,
        decision=schemas.VersionRef(id=uuid4(), revision=1),
        check_keys=(second.key,),
        limits=(schemas.SourcedText(text="第二检查的独立限定措施", sources=(case.base.original,)),),
    )
    plan = package(
        case,
        (first_exception, second_exception),
        checks=(case.package.checks[0], first, second),
    )
    decision = rules.require_decidable(candidate(case, plan))
    assert decision.assessment.state == "READY_WITH_CONDITIONS"
    assert decision.assessment.conditions == (first_exception.decision, second_exception.decision)
    assert decision.assessment.checks == (first, second)
    assert decision.limits == (*first_exception.limits, *second_exception.limits)


def test_unselected_actual_exception_is_retained_as_material_but_grants_no_condition(case):
    check = unknown_check(case)
    exception = basis(case)
    plan = package(case, (exception,), checks=(case.package.checks[0], check), selected=())
    assert plan.exceptions == (exception,)
    assert plan.declaration.exceptions == ()
    decision = candidate(case, plan)
    assert decision.assessment.state == "UNKNOWN" and decision.assessment.conditions == ()
    assert_not_decidable(decision)


@pytest.mark.parametrize("fault", ["withdrawn", "expiry"])
def test_withdrawal_or_expiry_keeps_history_but_cannot_support_a_new_release_decision(case, fault):
    check = unknown_check(case)
    exception = basis(case, expiry=AT + timedelta(seconds=1))
    plan = package(case, (exception,), checks=(case.package.checks[0], check))
    retained = rules.require_decidable(candidate(case, plan))
    history = deepcopy(retained.model_dump())
    if fault == "withdrawn":
        unavailable = exception.model_copy(update={"state": "withdrawn"})
        later = package(case, (unavailable,), checks=(case.package.checks[0], check))
        new_decision = candidate(case, later)
        assert later.exceptions[0].decision == exception.decision
        assert later.exceptions[0].state == "withdrawn"
    else:
        new_decision = candidate(case, plan, at=exception.expiry)
        assert plan.exceptions[0].expiry == exception.expiry
    assert new_decision.assessment.state == "UNKNOWN"
    assert new_decision.assessment.conditions == ()
    assert_not_decidable(new_decision)
    assert retained.model_dump() == history
    assert retained.assessment.state == "READY_WITH_CONDITIONS"
