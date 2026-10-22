"""Pure structure/policy projections, not owner truth, T2 or production release."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.contracts import SourceRead
from pdos_next.domain.release import rules
from pdos_next.domain.release import schemas as dto
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import Scope, SourceRef
from pdos_next.service import Context

AT = datetime(2026, 10, 17, 18, tzinfo=UTC)


def ref():
    return dto.VersionRef(id=uuid4(), revision=1)


@pytest.fixture
def case():
    scope = Scope(tenant_id=uuid4(), product_id=uuid4(), project_id=uuid4())
    actor, category = uuid4(), uuid4()
    original = {
        "kind": "artifact",
        "id": str(uuid4()),
        "revision": 1,
        "position": "line:1;quote_sha256:" + "a" * 64,
    }
    source = SourceRef.model_validate(original)
    subject = dto.SubjectConfiguration(
        definition=ref(), engineering_configuration=ref(), manufacturing_configuration=ref()
    )
    release_scope = dto.ReleaseScope(
        quantity="12", unit="台", lots=(ref(),), site="上海", lines=(ref(),), regions=("CN", "EU")
    )
    issue = dto.ObjectRef(kind="issue", **ref().model_dump())
    payload = dto.PackageAssemblePayload(
        project_id=scope.project_id,
        subject_config=subject,
        release_scope=release_scope,
        purpose="本型号固定交付用途",
        verifications=(ref(),),
        pilots=(ref(),),
        manufacturing_publication=ref(),
        residuals=(issue,),
        sources=(original,),
        reason="固定实际版本及尚待处理的遗留项",
    )
    checks = tuple(
        dto.ReleaseCheck(
            key=discipline + "-applicable-evidence",
            discipline=discipline,
            applicable=True,
            required=True,
            state="satisfied",
            non_waivable=True,
            detail="服务器实际政策的本专业适用证据检查",
            sources=(source,),
        )
        for discipline in ("engineering", "manufacturing")
    )
    material = dto.ReleaseMaterial(
        scope=scope,
        category_id=category,
        product_revision=3,
        purpose=payload.purpose,
        subject_config=subject,
        release_scope=release_scope,
        objects=tuple(
            dto.FixedObject(
                ref=value, product_id=scope.product_id, project_id=scope.project_id, sha256="b" * 64
            )
            for value in rules.selected_objects(payload)
        ),
        policy=dto.PolicyBasis(version="controlled-release-policy-v1", sources=(source,)),
        checks=checks,
        sources=(source,),
        required_source_read_set=(
            SourceRead(artifact_id=source.id, expected_revision=source.revision),
        ),
    )
    plan = rules.assemble(payload, material, owner_id=actor)
    ctx = Context(scope.tenant_id, actor, actor, category_id=category)
    value = SimpleNamespace(
        scope=scope,
        ctx=ctx,
        actor=actor,
        source=source,
        original=original,
        payload=payload,
        material=material,
        plan=plan,
        package=ref(),
    )
    value.candidate = lambda operation=dto.MANUFACTURING_APPROVE, plan=None, **updates: (
        rules.prepare_decision(
            operation,
            dto.PAYLOADS[operation](
                package=value.package,
                release_scope=value.payload.release_scope,
                purpose=value.payload.purpose,
                sources=(original,),
                reason="本人拟作本专业范围决定",
                **updates,
            ),
            value.package,
            plan or value.plan,
            ctx=value.ctx,
            at=AT,
        )
    )
    return value


def rebuilt(case, **updates):
    return rules.assemble(
        case.payload, case.material.model_copy(update=updates), owner_id=case.actor
    )


@pytest.mark.parametrize(
    ("check_state", "expected"),
    [("satisfied", "READY"), ("unknown", "UNKNOWN"), ("blocked", "BLOCKED")],
)
def test_explicit_empty_lots_and_lines_keep_the_actual_professional_checks(
    case, check_state, expected
):
    empty = case.payload.release_scope.model_copy(update={"lots": (), "lines": ()})
    payload = case.payload.model_copy(update={"release_scope": empty})
    checks = tuple(
        check.model_copy(update={"release_scope": empty, "state": check_state})
        for check in case.material.checks
    )
    selected = set(rules.selected_objects(payload))
    material = case.material.model_copy(
        update={
            "release_scope": empty,
            "checks": checks,
            "objects": tuple(v for v in case.material.objects if v.ref in selected),
        }
    )
    plan = rules.assemble(payload, material, owner_id=case.actor)
    for discipline in ("engineering", "manufacturing"):
        assessment = rules.evaluate(plan, discipline, empty, at=AT)
        assert assessment.state == expected
        assert len(assessment.checks) == 1
        assert assessment.checks[0].state == check_state


def assert_reason(call, code="SOURCE_STALE"):
    with pytest.raises(DomainError) as error:
        call()
    assert error.value.reason == code


def test_package_freezes_actual_objects_and_keeps_open_issue_reference(case):
    assert set(rules.selected_objects(case.payload)) == {v.ref for v in case.plan.objects}
    assert case.plan.declaration.residuals == case.payload.residuals
    assert case.plan.declaration.pilots == case.payload.pilots
    assert case.plan.evidence_digest and case.plan.required_source_read_set
    # Issue lifecycle and short-term yield are not invented global prerequisites.
    for operation in (dto.ENGINEERING_APPROVE, dto.MANUFACTURING_APPROVE):
        candidate = rules.require_decidable(case.candidate(operation))
        assert candidate.status == "unexecuted_candidate" and candidate.structural_only
        assert candidate.expiry is None and candidate.signers == (case.ctx.actor_id,)
        assert candidate.customer_acceptance is None
        assert candidate.external_received is candidate.external_effective is False


@pytest.mark.parametrize("field", ("ready", "qualified", "authorized", "signers", "policy_version"))
def test_public_input_cannot_assert_authority_or_policy(case, field):
    raw = case.payload.model_dump(mode="json")
    raw[field] = True
    with pytest.raises(ValidationError):
        dto.PackageAssemblePayload.model_validate(raw)
    raw = {
        "package": case.package.model_dump(mode="json"),
        "release_scope": case.payload.release_scope.model_dump(mode="json"),
        "purpose": case.payload.purpose,
        "sources": [case.original],
        "reason": "本人决定",
        field: True,
    }
    with pytest.raises(ValidationError):
        dto.ManufacturingApprovePayload.model_validate(raw)


def test_required_unknown_is_retained_and_cannot_be_signed_by_text_limits(case):
    checks = (
        case.material.checks[0],
        case.material.checks[1].model_copy(update={"state": "unknown"}),
    )
    candidate = case.candidate(
        plan=rebuilt(case, checks=checks),
        limits=(dto.SourcedText(text=" 人工写的条件 不能宣称已核对 ", sources=(case.original,)),),
    )
    assert candidate.assessment.state == "UNKNOWN"
    assert candidate.assessment.unknown == (checks[1].key,)
    assert candidate.limits[0].text == " 人工写的条件 不能宣称已核对 "
    assert_reason(lambda: rules.require_decidable(candidate))


def test_hard_block_wins_without_hiding_unknown_and_other_professional_stays_separate(case):
    check = case.material.checks[1].model_copy(update={"state": "blocked"})
    unknown = check.model_copy(update={"key": "required-method-unknown", "state": "unknown"})
    plan = rebuilt(case, checks=(case.material.checks[0], check, unknown))
    assessment = case.candidate(plan=plan).assessment
    assert assessment.state == "BLOCKED" and assessment.blocked == (check.key,)
    assert assessment.unknown == (unknown.key,)
    assert_reason(lambda: rules.require_decidable(case.candidate(plan=plan)))
    assert case.candidate(dto.ENGINEERING_APPROVE, plan=plan).assessment.state == "READY"


def test_unapplied_or_nonrequired_unknown_is_visible_material_not_global_gate(case):
    unknown = case.material.checks[1].model_copy(
        update={"key": "not-applicable-tooling", "applicable": False, "state": "unknown"}
    )
    optional = unknown.model_copy(
        update={"key": "optional-maturity", "applicable": True, "required": False}
    )
    plan = rebuilt(case, checks=(*case.material.checks, unknown, optional))
    assert len(plan.checks) == 4
    assert case.candidate(plan=plan).assessment.state == "READY"
    assert rebuilt(case, policy=None).policy is None
    assert case.candidate(plan=rebuilt(case, policy=None)).assessment.unknown == (
        "RELEASE_POLICY_MISSING",
    )


def with_exception(case, *, non_waivable=False, state="current", expiry=None):
    decision = ref()
    case.payload = case.payload.model_copy(update={"exceptions": (decision,)})
    original_check = case.material.checks[1]
    check = original_check.model_copy(
        update={"state": "blocked", "non_waivable": non_waivable, "exception": decision}
    )
    exception = dto.ExceptionBasis(
        decision=decision,
        scope=case.scope,
        subject_config=case.payload.subject_config,
        release_scope=case.payload.release_scope,
        purpose=case.payload.purpose,
        policy_version=case.material.policy.version,
        discipline="manufacturing",
        check_keys=(check.key,),
        state=state,
        limits=(dto.SourcedText(text="真实独立权威决定的限定条件", sources=(case.original,)),),
        sources=(case.source,),
        expiry=expiry,
    )
    material = case.material.model_copy(
        update={
            "checks": (case.material.checks[0], check),
            "objects": (
                *case.material.objects,
                dto.FixedObject(
                    ref=dto.ObjectRef(kind="exception", **decision.model_dump()),
                    product_id=case.scope.product_id,
                    project_id=case.scope.project_id,
                    sha256="c" * 64,
                ),
            ),
            "exceptions": (exception,),
        }
    )
    return rules.assemble(case.payload, material, owner_id=case.actor)


def test_only_separate_actual_applicable_exception_yields_conditions(case):
    plan = with_exception(case)
    candidate = case.candidate(plan=plan)
    assert candidate.assessment.state == "READY_WITH_CONDITIONS"
    assert candidate.assessment.conditions == case.payload.exceptions
    assert candidate.limits == plan.exceptions[0].limits
    rules.require_decidable(candidate)
    # The same reference is powerless when its actual owner has no usable proof.
    unknown = plan.model_copy(
        update={"exceptions": (plan.exceptions[0].model_copy(update={"state": "unknown"}),)}
    )
    assert case.candidate(plan=unknown).assessment.state == "BLOCKED"
    assert case.candidate(plan=unknown).assessment.unknown


@pytest.mark.parametrize(
    "fault", ("hard", "expired", "wrong_discipline", "changed_config", "unknown")
)
def test_exception_cannot_cover_hard_unknown_or_another_scope(case, fault):
    plan = with_exception(
        case,
        non_waivable=fault in {"hard", "unknown"},
        expiry=AT - timedelta(seconds=1) if fault == "expired" else None,
    )
    if fault == "wrong_discipline":
        plan = plan.model_copy(
            update={
                "exceptions": (plan.exceptions[0].model_copy(update={"discipline": "engineering"}),)
            }
        )
    elif fault == "changed_config":
        changed = case.payload.subject_config.model_copy(
            update={"manufacturing_configuration": ref()}
        )
        plan = plan.model_copy(
            update={
                "exceptions": (plan.exceptions[0].model_copy(update={"subject_config": changed}),)
            }
        )
    elif fault == "unknown":
        plan = plan.model_copy(
            update={
                "checks": (plan.checks[0], plan.checks[1].model_copy(update={"state": "unknown"}))
            }
        )
    candidate = case.candidate(plan=plan)
    assert candidate.assessment.state == ("UNKNOWN" if fault == "unknown" else "BLOCKED")
    assert_reason(lambda: rules.require_decidable(candidate))


def test_professional_scopes_can_narrow_independently_without_expansion_or_all_scope(case):
    narrow = case.payload.release_scope.model_copy(
        update={"quantity": Decimal("2"), "regions": ("CN",)}
    )
    raw = dict(
        package=case.package,
        release_scope=narrow,
        purpose=case.payload.purpose,
        sources=(case.original,),
        reason="本专业仅本批两台",
    )
    engineering = rules.prepare_decision(
        dto.ENGINEERING_APPROVE,
        dto.EngineeringApprovePayload(**raw),
        case.package,
        case.plan,
        ctx=case.ctx,
        at=AT,
    )
    manufacturing = case.candidate()
    assert engineering.release_scope != manufacturing.release_scope
    assert engineering.discipline != manufacturing.discipline
    assert not rules.scope_contains(dto.ReleaseScope(lines=()), dto.ReleaseScope(lines=(ref(),)))
    expanded = narrow.model_copy(update={"regions": ("US",)})
    assert_reason(lambda: rules.evaluate(case.plan, "engineering", expanded, at=AT))


def test_narrow_actual_scope_does_not_import_disjoint_policy_blocker(case):
    check = case.material.checks[1].model_copy(
        update={
            "key": "EU-specific-blocker",
            "state": "blocked",
            "release_scope": dto.ReleaseScope(regions=("EU",)),
        }
    )
    plan = rebuilt(case, checks=(*case.material.checks, check))
    selected = case.payload.release_scope.model_copy(update={"regions": ("CN",)})
    assert rules.evaluate(plan, "manufacturing", selected, at=AT).state == "READY"
    assert (
        rules.evaluate(plan, "manufacturing", case.payload.release_scope, at=AT).state == "BLOCKED"
    )


def test_fixed_selection_or_missing_original_cannot_be_silently_replaced(case):
    assert_reason(
        lambda: rebuilt(case, objects=case.material.objects[:-1]), "MISSING_REQUIRED_EVIDENCE"
    )
    assert_reason(lambda: rebuilt(case, purpose="另一用途"), "FORBIDDEN_SCOPE")
    assert_reason(
        lambda: rebuilt(
            case, release_scope=case.material.release_scope.model_copy(update={"site": "另一场地"})
        ),
        "FORBIDDEN_SCOPE",
    )
    missing = case.payload.model_copy(
        update={"sources": (dto.OriginalRef(**{**case.original, "id": uuid4()}),)}
    )
    assert_reason(
        lambda: rules.assemble(missing, case.material, owner_id=case.actor),
        "MISSING_REQUIRED_EVIDENCE",
    )


def test_signer_is_real_caller_bound_and_no_arbitrary_expiry_is_added(case):
    candidate = case.candidate(expiry=AT + timedelta(days=30))
    assert candidate.expiry == AT + timedelta(days=30)
    assert_reason(lambda: case.candidate(expiry=AT), "SOURCE_STALE")
    case.ctx = Context(case.scope.tenant_id, uuid4(), case.actor, category_id=case.ctx.category_id)
    assert_reason(case.candidate, "NAMED_DECISION_REQUIRED")
