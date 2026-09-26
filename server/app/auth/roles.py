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
    MY_WORK_VIEW = "my_work.view"
    ISSUE_ASSIGN = "issue.assign"
    ISSUE_EXECUTE = "issue.execute"
    ISSUE_VERIFY = "issue.verify"
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
    TEST_RUN_RECORD = "test_run.record"
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
    COST_APPROVE = "cost.approve"
    HANDOFF_VIEW = "handoff.view"
    HANDOFF_PREPARE = "handoff.prepare"
    HANDOFF_EXECUTE = "handoff.execute"
    HANDOFF_RECONCILE = "handoff.reconcile"
    INTEGRATION_VIEW = "integration.view"
    INTEGRATION_BIND_SELF = "integration.bind_self"
    INTEGRATION_MANAGE = "integration.manage"
    INTEGRATION_PROJECT_MANAGE = "integration.project_manage"
    INTEGRATION_PROJECT_SEND = "integration.project_send"
    EXTERNAL_RESPOND = "external.respond"
    MEETING_VIEW = "meeting.view"
    MEETING_MANAGE = "meeting.manage"
    MEETING_TRANSCRIPT_UPLOAD = "meeting.transcript_upload"
    MEETING_LINK_MANAGE = "meeting.link_manage"
    EVIDENCE_VIEW = "evidence.view"
    EVIDENCE_CAPTURE = "evidence.capture"
    RESEARCH_SOURCE_MANAGE = "research_source.manage"
    PRODUCT_WORK_VIEW = "product_work.view"
    PRODUCT_WORK_CONTRIBUTE = "product_work.contribute"
    PRODUCT_WORK_MANAGE = "product_work.manage"


_ALL_ACTIONS = frozenset(Action)
_ROLE_ACTIONS = MappingProxyType(
    {
        Role.OWNER: _ALL_ACTIONS,
        Role.ADMIN: _ALL_ACTIONS - {Action.TENANT_MANAGE},
        Role.PROJECT_MANAGER: frozenset(
            {
                Action.PRODUCT_WORK_VIEW,
                Action.PRODUCT_WORK_CONTRIBUTE,
                Action.PRODUCT_WORK_MANAGE,
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
                Action.MY_WORK_VIEW,
                Action.ISSUE_ASSIGN,
                Action.ISSUE_EXECUTE,
                Action.ISSUE_VERIFY,
                Action.QUALITY_MANAGE,
                Action.TEST_RUN_RECORD,
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
                Action.COST_APPROVE,
                Action.HANDOFF_VIEW,
                Action.HANDOFF_PREPARE,
                Action.HANDOFF_EXECUTE,
                Action.INTEGRATION_VIEW,
                Action.INTEGRATION_BIND_SELF,
                Action.INTEGRATION_PROJECT_MANAGE,
                Action.INTEGRATION_PROJECT_SEND,
                Action.MEETING_VIEW,
                Action.MEETING_MANAGE,
                Action.MEETING_TRANSCRIPT_UPLOAD,
                Action.MEETING_LINK_MANAGE,
                Action.EVIDENCE_VIEW,
                Action.EVIDENCE_CAPTURE,
                Action.RESEARCH_SOURCE_MANAGE,
            }
        ),
        Role.ENGINEER: frozenset(
            {
                Action.PRODUCT_WORK_VIEW,
                Action.PRODUCT_WORK_CONTRIBUTE,
                Action.TEST_RUN_RECORD,
                Action.PROJECT_VIEW,
                Action.REQUIREMENT_VIEW,
                Action.DEVELOPMENT_CASE_VIEW,
                Action.WORK_ITEM_VIEW,
                Action.WORK_ITEM_EDIT,
                Action.MY_WORK_VIEW,
                Action.ISSUE_EXECUTE,
                Action.ISSUE_VERIFY,
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
                Action.INTEGRATION_VIEW,
                Action.INTEGRATION_BIND_SELF,
                Action.MEETING_VIEW,
                Action.MEETING_TRANSCRIPT_UPLOAD,
                Action.EVIDENCE_VIEW,
                Action.EVIDENCE_CAPTURE,
            }
        ),
        Role.QUALITY: frozenset(
            {
                Action.PRODUCT_WORK_VIEW,
                Action.PRODUCT_WORK_CONTRIBUTE,
                Action.TEST_RUN_RECORD,
                Action.PROJECT_VIEW,
                Action.REQUIREMENT_VIEW,
                Action.DEVELOPMENT_CASE_VIEW,
                Action.WORK_ITEM_VIEW,
                Action.WORK_ITEM_EDIT,
                Action.MY_WORK_VIEW,
                Action.ISSUE_ASSIGN,
                Action.ISSUE_EXECUTE,
                Action.ISSUE_VERIFY,
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
                Action.INTEGRATION_VIEW,
                Action.INTEGRATION_BIND_SELF,
                Action.MEETING_VIEW,
                Action.MEETING_TRANSCRIPT_UPLOAD,
                Action.EVIDENCE_VIEW,
                Action.EVIDENCE_CAPTURE,
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
