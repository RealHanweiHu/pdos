"""Pure candidates only: no live owners, current authority or common T2 proof."""

from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.domain.release import rules as release
from pdos_next.domain.release.policy_schemas import PolicyMaterial, PolicyRule
from pdos_next.domain.release_exceptions import rules, schemas
from pdos_next.domain.release_exceptions.constants import DECIDE, OPERATIONS, WITHDRAW
from pdos_next.errors import DomainError
from pdos_next.service import Context
from tests.release.test_rules import AT
from tests.release.test_rules import case as release_case  # noqa: F401


@pytest.fixture
def case(request):
    base = request.getfixturevalue("release_case")
    package_payload = base.payload.model_copy(update={"visibility": "category"})
    check = base.material.checks[1].model_copy(
        update={
            "state": "blocked",
            "non_waivable": False,
            "release_scope": base.payload.release_scope,
        }
    )
    package = release.assemble(
        package_payload,
        base.material.model_copy(update={"checks": (base.material.checks[0], check)}),
        owner_id=base.actor,
    )
    policy = PolicyMaterial(
        schema_version="pdos-release-policy-v1",
        scope=base.scope,
        category_id=base.ctx.category_id,
        subject_config=base.payload.subject_config,
        release_scope=base.payload.release_scope,
        purpose=base.payload.purpose,
        policy_version=base.material.policy.version,
        publisher_id=base.actor,
        owner_id=base.actor,
        visibility="category",
        nature="synthetic",
        status="active",
        valid_from=None,
        valid_until=None,
        rules=(
            PolicyRule(
                id=check.key,
                version="1",
                scope=base.payload.release_scope,
                discipline="manufacturing",
                applicable_if={"op": "always"},
                predicate={"op": "object_exists", "kind": "artifact"},
                required_evidence=("artifact",),
                freshness="current",
                severity="required",
                responsible_role="manufacturing",
                waivable=True,
                allowed_purpose=(base.payload.purpose,),
            ),
        ),
    )
    sourced = schemas.SourcedText(text="仅按原件载明的本轮限量范围办理", sources=(base.original,))
    payload = schemas.DecidePayload(
        basis_package=base.package,
        discipline="manufacturing",
        release_scope=base.payload.release_scope,
        purpose=base.payload.purpose,
        check_keys=(check.key,),
        limits=(sourced,),
        risk_controls=(
            schemas.SourcedText(
                text="保留隔离和逐件追溯，超范围立即停止", sources=(base.original,)
            ),
        ),
        sources=(base.original,),
        reason="依据受控政策作限定例外决定候选",
    )
    data = schemas.ActualData(
        package_ref=base.package,
        package=package,
        package_current=True,
        policy_fact=schemas.VersionRef(id=uuid4(), revision=1),
        policy=policy,
        policy_current=True,
        sources_current=True,
        sources=(schemas.OriginalRef.model_validate(base.original),),
        required_source_read_set=base.material.required_source_read_set,
    )
    plan = rules.prepare_decide(payload, data, ctx=base.ctx, at=AT)
    ref = schemas.VersionRef(id=uuid4(), revision=1)
    withdraw = schemas.WithdrawPayload(
        exception=ref, sources=(base.original,), reason="撤回本轮例外，保留原批准内容"
    )
    withdrawal_data = schemas.WithdrawActualData(
        exception=ref,
        previous=plan,
        current=True,
        sources_current=True,
        sources=data.sources,
        required_source_read_set=data.required_source_read_set,
    )
    return SimpleNamespace(**locals())


def test_ready_candidate_preserves_scope_checks_controls_and_is_not_a_signed_fact(case):
    before = deepcopy(case.package.model_dump())
    plan = rules.require_decidable(case.plan)
    assert plan.operation == DECIDE and OPERATIONS[DECIDE][0] == "T2"
    assert plan.action == "approved" and plan.structural_only
    assert plan.status == "unexecuted_candidate" and plan.previous is None
    assert plan.owner_id == case.package.owner_id and plan.visibility == "category"
    assert plan.expiry is None and plan.signers == (case.base.ctx.requester_id,)
    assert plan.policy_fact == case.data.policy_fact
    assert plan.selected_checks == (case.check,) and plan.selected_checks[0].state == "blocked"
    assert plan.limits == case.payload.limits and plan.risk_controls == case.payload.risk_controls
    assert plan.declaration == rules.semantic(case.payload)
    assert "approval_token" not in plan.declaration
    assert case.package.model_dump() == before


def test_bounded_permission_leaves_the_selected_unknown_evidence_unknown(case):
    check = case.check.model_copy(update={"state": "unknown"})
    package = case.package.model_copy(update={"checks": (case.package.checks[0], check)})
    plan = rules.prepare_decide(
        case.payload, case.data.model_copy(update={"package": package}), ctx=case.base.ctx, at=AT
    )
    assert rules.require_decidable(plan).selected_checks[0].state == "unknown"
    assert package.checks[1].state == "unknown"
    # The ordinary release projection remains unknown without its separate,
    # actual exception owner. The candidate grants no engineering/manufacturing release.
    assert release.evaluate(package, "manufacturing", plan.release_scope, at=AT).state == "UNKNOWN"


@pytest.mark.parametrize("where", ["check", "policy"])
def test_either_actual_nonwaivable_marker_blocks_the_candidate(case, where):
    data = case.data
    if where == "check":
        package = case.package.model_copy(
            update={
                "checks": (
                    case.package.checks[0],
                    case.check.model_copy(update={"non_waivable": True}),
                )
            }
        )
        data = data.model_copy(update={"package": package})
    else:
        policy = case.policy.model_copy(
            update={"rules": (case.policy.rules[0].model_copy(update={"waivable": False}),)}
        )
        data = data.model_copy(update={"policy": policy})
    plan = rules.prepare_decide(case.payload, data, ctx=case.base.ctx, at=AT)
    assert plan.state == "BLOCKED" and any("NON_WAIVABLE" in value for value in plan.blocked)
    with pytest.raises(DomainError):
        rules.require_decidable(plan)


@pytest.mark.parametrize("fault", ["missing", "not_applicable", "other_discipline"])
def test_selected_check_must_exist_and_belong_to_this_applicable_discipline(case, fault):
    payload, data = case.payload, case.data
    if fault == "missing":
        payload = payload.model_copy(update={"check_keys": ("not-the-selected-policy-rule",)})
    else:
        check = case.check.model_copy(
            update={"applicable": False}
            if fault == "not_applicable"
            else {"discipline": "engineering"}
        )
        data = data.model_copy(
            update={"package": case.package.model_copy(update={"checks": (check,)})}
        )
    plan = rules.prepare_decide(payload, data, ctx=case.base.ctx, at=AT)
    assert plan.state == ("UNKNOWN" if fault == "missing" else "BLOCKED")


@pytest.mark.parametrize(
    "fault",
    [
        "package_current",
        "policy_current",
        "policy",
        "policy_fact",
        "package_policy",
        "policy_expired",
    ],
)
def test_unavailable_policy_or_current_binding_stays_unknown(case, fault):
    if fault in {"package_current", "policy_current"}:
        data = case.data.model_copy(update={fault: False})
    elif fault == "package_policy":
        data = case.data.model_copy(
            update={"package": case.package.model_copy(update={"policy": None})}
        )
    elif fault == "policy_expired":
        data = case.data.model_copy(
            update={"policy": case.policy.model_copy(update={"valid_until": AT})}
        )
    else:
        data = case.data.model_copy(update={fault: None})
    plan = rules.prepare_decide(case.payload, data, ctx=case.base.ctx, at=AT)
    assert plan.state == "UNKNOWN" and plan.unknown
    with pytest.raises(DomainError):
        rules.require_decidable(plan)


@pytest.mark.parametrize(
    "fault", ["package_quantity", "policy_configuration", "policy_regions", "null_widen"]
)
def test_package_policy_and_selected_scope_cannot_be_widened_or_rebound(case, fault):
    payload, data = case.payload, case.data
    if fault == "package_quantity":
        payload = payload.model_copy(
            update={
                "release_scope": payload.release_scope.model_copy(
                    update={"quantity": Decimal("99")}
                )
            }
        )
    elif fault == "null_widen":
        payload = payload.model_copy(
            update={"release_scope": payload.release_scope.model_copy(update={"lots": None})}
        )
    elif fault == "policy_regions":
        policy = case.policy.model_copy(
            update={
                "release_scope": case.policy.release_scope.model_copy(update={"regions": ("CN",)})
            }
        )
        data = data.model_copy(update={"policy": policy})
    else:
        config = case.policy.subject_config.model_copy(
            update={"engineering_configuration": schemas.VersionRef(id=uuid4(), revision=1)}
        )
        data = data.model_copy(
            update={"policy": case.policy.model_copy(update={"subject_config": config})}
        )
    plan = rules.prepare_decide(payload, data, ctx=case.base.ctx, at=AT)
    assert plan.state == "UNKNOWN"
    assert any("SCOPE_NOT_COVERED" in value for value in plan.unknown)


@pytest.mark.parametrize("fault", ["borrowed_actor", "ai_run", "foreign_category"])
def test_only_actual_named_context_prepares_the_candidate(case, fault):
    ctx = case.base.ctx
    values = vars(ctx).copy()
    values.update(
        {"actor_id": uuid4()}
        if fault == "borrowed_actor"
        else {"agent_run_id": uuid4()}
        if fault == "ai_run"
        else {"category_id": uuid4()}
    )
    with pytest.raises(DomainError) as error:
        rules.prepare_decide(case.payload, case.data, ctx=Context(**values), at=AT)
    assert error.value.reason == "FORBIDDEN_SCOPE"


def test_new_explicit_expiry_must_be_future_but_no_ttl_is_invented(case):
    assert case.plan.expiry is None
    payload = case.payload.model_copy(update={"expiry": AT})
    with pytest.raises(DomainError) as error:
        rules.prepare_decide(payload, case.data, ctx=case.base.ctx, at=AT)
    assert error.value.reason == "SOURCE_STALE"


@pytest.mark.parametrize("fault", ["duplicate_keys", "no_controls", "client_ready"])
def test_closed_payload_keeps_real_controls_and_rejects_client_policy_facts(case, fault):
    raw = case.payload.model_dump(mode="json")
    raw.update(
        {"check_keys": [case.check.key, case.check.key]}
        if fault == "duplicate_keys"
        else {"risk_controls": []}
        if fault == "no_controls"
        else {"ready": True}
    )
    with pytest.raises(ValidationError):
        schemas.DecidePayload.model_validate(raw)


@pytest.mark.parametrize("fault", ["position", "revision"])
def test_sources_need_exact_verified_reference_and_readset_not_just_identity(case, fault):
    source = case.data.sources[0].model_copy(
        update={"position": "line:2;quote_sha256:" + "f" * 64}
        if fault == "position"
        else {"revision": 2}
    )
    data = case.data.model_copy(update={"sources": (source,)})
    plan = rules.prepare_decide(case.payload, data, ctx=case.base.ctx, at=AT)
    assert plan.state == "UNKNOWN" and "EXCEPTION_ORIGINAL_NOT_VERIFIED" in plan.unknown


def test_withdrawal_retains_expired_original_and_uses_only_new_direct_originals(case):
    previous = case.plan.model_copy(update={"expiry": AT - timedelta(seconds=1)})
    new_source = schemas.OriginalRef(
        id=uuid4(), revision=1, position="line:1;quote_sha256:" + "d" * 64
    )
    payload = case.withdraw.model_copy(update={"sources": (new_source,)})
    data = case.withdrawal_data.model_copy(
        update={
            "previous": previous,
            "sources": (new_source,),
            "required_source_read_set": (
                schemas.SourceRead(artifact_id=new_source.id, expected_revision=1),
            ),
        }
    )
    before = deepcopy(previous.model_dump())
    plan = rules.require_decidable(rules.prepare_withdraw(payload, data, ctx=case.base.ctx, at=AT))
    assert plan.operation == WITHDRAW and OPERATIONS[WITHDRAW][0] == "T2"
    assert plan.action == "withdrawn" and plan.previous == case.ref
    for name in (
        "basis_package",
        "policy_fact",
        "policy_version",
        "subject_config",
        "release_scope",
        "purpose",
        "check_keys",
        "selected_checks",
        "limits",
        "risk_controls",
        "expiry",
        "owner_id",
        "visibility",
        "discipline",
    ):
        assert getattr(plan, name) == getattr(previous, name)
    assert plan.sources == (schemas.SourceRef.model_validate(new_source.model_dump()),)
    assert plan.required_source_read_set == data.required_source_read_set
    assert plan.declaration == rules.semantic(payload) and plan.reason == payload.reason
    assert previous.model_dump() == before


def test_withdrawal_current_drift_stays_unknown_instead_of_overwriting_history(case):
    plan = rules.prepare_withdraw(
        case.withdraw,
        case.withdrawal_data.model_copy(update={"current": False}),
        ctx=case.base.ctx,
        at=AT,
    )
    assert plan.state == "UNKNOWN" and plan.unknown == ("EXCEPTION_NOT_CURRENT",)
    with pytest.raises(DomainError):
        rules.require_decidable(plan)


def test_withdrawal_requires_exact_original_reference(case):
    payload = case.withdraw.model_copy(
        update={"exception": case.ref.model_copy(update={"revision": 2})}
    )
    with pytest.raises(DomainError) as error:
        rules.prepare_withdraw(payload, case.withdrawal_data, ctx=case.base.ctx, at=AT)
    assert error.value.reason == "VERSION_CONFLICT"
