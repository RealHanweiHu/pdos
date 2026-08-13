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
    DEVELOPMENT_CASE_VIEW = "development_case.view"
    DEVELOPMENT_CASE_CREATE = "development_case.create"
    DEVELOPMENT_CASE_EDIT = "development_case.edit"
    DEVELOPMENT_CASE_TRANSITION = "development_case.transition"
    WORK_ITEM_VIEW = "work_item.view"
    WORK_ITEM_EDIT = "work_item.edit"
    EVENT_DEBUG_VIEW = "event_debug.view"
    MODEL_GOVERNANCE_VIEW = "model_governance.view"
    MODEL_GOVERNANCE_MANAGE = "model_governance.manage"
    FINDING_VIEW = "finding.view"
    FINDING_REVIEW = "finding.review"
    FINDING_APPLY = "finding.apply"
    AI_CHAT_USE = "ai_chat.use"
    DOCUMENT_ANALYZE = "document.analyze"
    RISK_SUGGESTION_CREATE = "risk_suggestion.create"
    EVENT_INGEST = "event.ingest"
    PRODUCT_ENGINEERING_VIEW = "product_engineering.view"
    PRODUCT_ENGINEERING_EDIT = "product_engineering.edit"
    GATE_VIEW = "gate.view"
    GATE_MANAGE = "gate.manage"
    GATE_SIGN = "gate.sign"
    QUALITY_MANAGE = "quality.manage"
    QUALITY_VIEW = "quality.view"
    COMPLAINT_CREATE = "complaint.create"
    CAPA_MANAGE = "capa.manage"
    CAPA_EXECUTE = "capa.execute"
    CAPA_VERIFY = "capa.verify"
    MEMORY_VIEW = "memory.view"
    MEMORY_DRAFT = "memory.draft"
    MEMORY_VERIFY = "memory.verify"
    MEMORY_ARCHIVE = "memory.archive"
    CHANGE_VIEW = "change.view"
    CHANGE_EDIT = "change.edit"
    CHANGE_APPROVE = "change.approve"
    HANDOFF_VIEW = "handoff.view"
    HANDOFF_PREPARE = "handoff.prepare"
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
                Action.DEVELOPMENT_CASE_VIEW,
                Action.DEVELOPMENT_CASE_CREATE,
                Action.DEVELOPMENT_CASE_EDIT,
                Action.DEVELOPMENT_CASE_TRANSITION,
                Action.WORK_ITEM_VIEW,
                Action.WORK_ITEM_EDIT,
                Action.QUALITY_MANAGE,
                Action.QUALITY_VIEW,
                Action.COMPLAINT_CREATE,
                Action.CAPA_EXECUTE,
                Action.MEMORY_VIEW,
                Action.MEMORY_DRAFT,
                Action.MEMORY_VERIFY,
                Action.MEMORY_ARCHIVE,
                Action.FINDING_VIEW,
                Action.FINDING_REVIEW,
                Action.FINDING_APPLY,
                Action.AI_CHAT_USE,
                Action.DOCUMENT_ANALYZE,
                Action.RISK_SUGGESTION_CREATE,
                Action.EVENT_INGEST,
                Action.PRODUCT_ENGINEERING_VIEW,
                Action.PRODUCT_ENGINEERING_EDIT,
                Action.GATE_VIEW,
                Action.GATE_MANAGE,
                Action.GATE_SIGN,
                Action.CHANGE_VIEW,
                Action.CHANGE_EDIT,
                Action.CHANGE_APPROVE,
                Action.HANDOFF_VIEW,
                Action.HANDOFF_PREPARE,
            }
        ),
        Role.ENGINEER: frozenset(
            {
                Action.PROJECT_VIEW,
                Action.REQUIREMENT_VIEW,
                Action.DEVELOPMENT_CASE_VIEW,
                Action.WORK_ITEM_VIEW,
                Action.WORK_ITEM_EDIT,
                Action.QUALITY_VIEW,
                Action.COMPLAINT_CREATE,
                Action.CAPA_EXECUTE,
                Action.MEMORY_VIEW,
                Action.MEMORY_DRAFT,
                Action.FINDING_VIEW,
                Action.FINDING_REVIEW,
                Action.FINDING_APPLY,
                Action.AI_CHAT_USE,
                Action.DOCUMENT_ANALYZE,
                Action.RISK_SUGGESTION_CREATE,
                Action.PRODUCT_ENGINEERING_VIEW,
                Action.PRODUCT_ENGINEERING_EDIT,
                Action.GATE_VIEW,
                Action.GATE_SIGN,
                Action.CHANGE_VIEW,
                Action.CHANGE_EDIT,
                Action.HANDOFF_VIEW,
            }
        ),
        Role.QUALITY: frozenset(
            {
                Action.PROJECT_VIEW,
                Action.REQUIREMENT_VIEW,
                Action.DEVELOPMENT_CASE_VIEW,
                Action.WORK_ITEM_VIEW,
                Action.WORK_ITEM_EDIT,
                Action.QUALITY_MANAGE,
                Action.QUALITY_VIEW,
                Action.COMPLAINT_CREATE,
                Action.CAPA_MANAGE,
                Action.CAPA_EXECUTE,
                Action.CAPA_VERIFY,
                Action.MEMORY_VIEW,
                Action.MEMORY_DRAFT,
                Action.MEMORY_VERIFY,
                Action.MEMORY_ARCHIVE,
                Action.FINDING_VIEW,
                Action.FINDING_REVIEW,
                Action.FINDING_APPLY,
                Action.AI_CHAT_USE,
                Action.DOCUMENT_ANALYZE,
                Action.RISK_SUGGESTION_CREATE,
                Action.PRODUCT_ENGINEERING_VIEW,
                Action.GATE_VIEW,
                Action.GATE_SIGN,
                Action.CHANGE_VIEW,
                Action.HANDOFF_VIEW,
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
