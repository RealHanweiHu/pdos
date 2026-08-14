import pytest

from app.auth.roles import Role
from app.domain.gates import (
    NPD_GATE_POLICY_VERSION,
    NPD_GATE_REQUIREMENTS,
    OBT_GATE_POLICY_VERSION,
    OBT_GATE_REQUIREMENTS,
    GateInvalidStateError,
    gate_policy_for_workflow,
    gate_signoffs_ready,
    may_sign_gate_slot,
    promote_requirement,
)


def test_npd_v1_policy_is_explicit_and_versioned_for_all_seven_stages() -> None:
    assert NPD_GATE_POLICY_VERSION == "npd-gate-v1"
    assert tuple(NPD_GATE_REQUIREMENTS) == (
        "concept",
        "planning",
        "design",
        "evt",
        "dvt",
        "pvt",
        "mp",
    )
    assert NPD_GATE_REQUIREMENTS["concept"] == {
        "product": "required",
        "engineering": "required",
        "quality": "conditional",
    }
    assert NPD_GATE_REQUIREMENTS["mp"] == {
        "product": "required",
        "engineering": "conditional",
        "quality": "required",
    }


def test_obt_v1_policy_is_explicit_and_selected_by_workflow() -> None:
    assert OBT_GATE_POLICY_VERSION == "obt-gate-v1"
    assert tuple(OBT_GATE_REQUIREMENTS) == ("intake", "sample", "pvt", "mp")
    assert gate_policy_for_workflow("obt-cehub-project", "intake") == (
        OBT_GATE_POLICY_VERSION,
        OBT_GATE_REQUIREMENTS["intake"],
    )
    assert gate_policy_for_workflow("npd-project", "concept") == (
        NPD_GATE_POLICY_VERSION,
        NPD_GATE_REQUIREMENTS["concept"],
    )
    with pytest.raises(GateInvalidStateError):
        gate_policy_for_workflow("unknown-project", "concept")


def test_readiness_treats_required_conditional_and_rejected_deterministically() -> None:
    requirements = NPD_GATE_REQUIREMENTS["concept"]

    missing = gate_signoffs_ready(requirements, {})
    assert not missing.ready
    assert missing.blockers == (
        "signoff:product",
        "signoff:engineering",
        "signoff:quality",
    )

    ready = gate_signoffs_ready(
        requirements,
        {
            "product": "approved",
            "engineering": "approved",
            "quality": "conditional",
        },
    )
    assert ready.ready
    assert ready.blockers == ()

    rejected = gate_signoffs_ready(
        requirements,
        {
            "product": "approved",
            "engineering": "rejected",
            "quality": "approved",
        },
    )
    assert not rejected.ready
    assert rejected.blockers == ("signoff:engineering",)


def test_slot_signing_is_role_bound_with_auditable_governance_override() -> None:
    assert may_sign_gate_slot(Role.OWNER, "quality")
    assert may_sign_gate_slot(Role.ADMIN, "engineering")
    assert may_sign_gate_slot(Role.PROJECT_MANAGER, "product")
    assert not may_sign_gate_slot(Role.PROJECT_MANAGER, "engineering")
    assert may_sign_gate_slot(Role.ENGINEER, "engineering")
    assert not may_sign_gate_slot(Role.ENGINEER, "quality")
    assert may_sign_gate_slot(Role.QUALITY, "quality")
    assert not may_sign_gate_slot(Role.SUPPLIER, "product")
    assert not may_sign_gate_slot(Role.CUSTOMER, "product")


def test_project_additions_can_only_promote_a_requirement() -> None:
    assert promote_requirement("not_applicable", "conditional") == "conditional"
    assert promote_requirement("conditional", "required") == "required"
    assert promote_requirement("required", "conditional") is None
    assert promote_requirement("required", "required") is None
