from __future__ import annotations

import pytest

from app.auth.roles import Action, Role, allowed_actions, is_allowed

EXPECTED_ACTIONS = {
    "tenant.manage",
    "user.manage",
    "project.create",
    "project.view",
    "project.edit",
    "project.members.manage",
    "requirement.view",
    "requirement.create",
    "requirement.edit",
    "development_case.view",
    "development_case.create",
    "development_case.edit",
    "development_case.transition",
    "work_item.view",
    "work_item.edit",
    "event_debug.view",
    "model_governance.view",
    "model_governance.manage",
    "finding.view",
    "finding.review",
    "finding.apply",
    "ai_chat.use",
    "document.analyze",
    "risk_suggestion.create",
    "event.ingest",
    "product_engineering.view",
    "product_engineering.edit",
    "gate.view",
    "gate.manage",
    "gate.sign",
    "quality.manage",
    "external.respond",
}

EXPECTED_MATRIX = {
    Role.OWNER: EXPECTED_ACTIONS,
    Role.ADMIN: EXPECTED_ACTIONS - {"tenant.manage"},
    Role.PROJECT_MANAGER: {
        "project.create",
        "project.view",
        "project.edit",
        "project.members.manage",
        "requirement.view",
        "requirement.create",
        "requirement.edit",
        "development_case.view",
        "development_case.create",
        "development_case.edit",
        "development_case.transition",
        "work_item.view",
        "work_item.edit",
        "quality.manage",
        "finding.view",
        "finding.review",
        "finding.apply",
        "ai_chat.use",
        "document.analyze",
        "risk_suggestion.create",
        "event.ingest",
        "product_engineering.view",
        "product_engineering.edit",
        "gate.view",
        "gate.manage",
        "gate.sign",
    },
    Role.ENGINEER: {
        "project.view",
        "requirement.view",
        "development_case.view",
        "work_item.view",
        "work_item.edit",
        "finding.view",
        "finding.review",
        "finding.apply",
        "ai_chat.use",
        "document.analyze",
        "risk_suggestion.create",
        "product_engineering.view",
        "product_engineering.edit",
        "gate.view",
        "gate.sign",
    },
    Role.QUALITY: {
        "project.view",
        "requirement.view",
        "development_case.view",
        "work_item.view",
        "work_item.edit",
        "quality.manage",
        "finding.view",
        "finding.review",
        "finding.apply",
        "ai_chat.use",
        "document.analyze",
        "risk_suggestion.create",
        "product_engineering.view",
        "gate.view",
        "gate.sign",
    },
    Role.SUPPLIER: {"project.view", "external.respond"},
    Role.CUSTOMER: {"project.view", "external.respond"},
}


def test_role_and_action_catalogs_are_frozen() -> None:
    assert {role.value for role in Role} == {
        "owner",
        "admin",
        "project_manager",
        "engineer",
        "quality",
        "supplier",
        "customer",
    }
    assert {action.value for action in Action} == EXPECTED_ACTIONS


@pytest.mark.parametrize(("role", "expected"), EXPECTED_MATRIX.items())
def test_every_role_has_an_explicit_allow_deny_matrix(
    role: Role,
    expected: set[str],
) -> None:
    actual = {action.value for action in allowed_actions(role)}

    assert actual == expected
    for action in Action:
        assert is_allowed(role, action) is (action.value in expected)


def test_unknown_roles_and_actions_fail_closed() -> None:
    assert not is_allowed("not-a-role", Action.PROJECT_VIEW)
    assert not is_allowed(Role.OWNER, "not-an-action")
    assert not is_allowed("not-a-role", "not-an-action")
    assert allowed_actions("not-a-role") == frozenset()


def test_external_roles_have_only_the_minimum_surface() -> None:
    external_minimum = frozenset({Action.PROJECT_VIEW, Action.EXTERNAL_RESPOND})

    assert allowed_actions(Role.SUPPLIER) == external_minimum
    assert allowed_actions(Role.CUSTOMER) == external_minimum
