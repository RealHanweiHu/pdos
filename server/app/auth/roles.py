"""Frozen RBAC role and action catalogs with a fail-closed policy matrix."""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    PROJECT_MANAGER = "project_manager"
    ENGINEER = "engineer"
    QUALITY = "quality"
    SUPPLIER = "supplier"
    CUSTOMER = "customer"


class Action(StrEnum):
    TENANT_MANAGE = "tenant.manage"
    USER_MANAGE = "user.manage"
    PROJECT_CREATE = "project.create"
    PROJECT_VIEW = "project.view"
    PROJECT_EDIT = "project.edit"
    PROJECT_MEMBERS_MANAGE = "project.members.manage"
    REQUIREMENT_VIEW = "requirement.view"
    REQUIREMENT_CREATE = "requirement.create"
    REQUIREMENT_EDIT = "requirement.edit"
    WORK_ITEM_VIEW = "work_item.view"
    WORK_ITEM_EDIT = "work_item.edit"
    QUALITY_MANAGE = "quality.manage"
    EXTERNAL_RESPOND = "external.respond"


_ALL_ACTIONS = frozenset(Action)
_ROLE_ACTIONS = MappingProxyType(
    {
        Role.OWNER: _ALL_ACTIONS,
        Role.ADMIN: _ALL_ACTIONS - {Action.TENANT_MANAGE},
        Role.PROJECT_MANAGER: frozenset(
            {
                Action.PROJECT_CREATE,
                Action.PROJECT_VIEW,
                Action.PROJECT_EDIT,
                Action.PROJECT_MEMBERS_MANAGE,
                Action.REQUIREMENT_VIEW,
                Action.REQUIREMENT_CREATE,
                Action.REQUIREMENT_EDIT,
                Action.WORK_ITEM_VIEW,
                Action.WORK_ITEM_EDIT,
                Action.QUALITY_MANAGE,
            }
        ),
        Role.ENGINEER: frozenset(
            {
                Action.PROJECT_VIEW,
                Action.REQUIREMENT_VIEW,
                Action.WORK_ITEM_VIEW,
                Action.WORK_ITEM_EDIT,
            }
        ),
        Role.QUALITY: frozenset(
            {
                Action.PROJECT_VIEW,
                Action.REQUIREMENT_VIEW,
                Action.WORK_ITEM_VIEW,
                Action.WORK_ITEM_EDIT,
                Action.QUALITY_MANAGE,
            }
        ),
        Role.SUPPLIER: frozenset(
            {
                Action.PROJECT_VIEW,
                Action.EXTERNAL_RESPOND,
            }
        ),
        Role.CUSTOMER: frozenset(
            {
                Action.PROJECT_VIEW,
                Action.EXTERNAL_RESPOND,
            }
        ),
    }
)


def parse_role(value: Role | str) -> Role | None:
    try:
        return Role(value)
    except ValueError:
        return None


def parse_action(value: Action | str) -> Action | None:
    try:
        return Action(value)
    except ValueError:
        return None


def allowed_actions(role: Role | str) -> frozenset[Action]:
    parsed_role = parse_role(role)
    return _ROLE_ACTIONS.get(parsed_role, frozenset()) if parsed_role is not None else frozenset()


def is_allowed(role: Role | str, action: Action | str) -> bool:
    parsed_action = parse_action(action)
    return parsed_action is not None and parsed_action in allowed_actions(role)
