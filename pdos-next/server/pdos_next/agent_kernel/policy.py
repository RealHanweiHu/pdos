"""Actual provider agreements, skill qualification and MCP admission; no prompt authority."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from pdos_next.clock import now
from pdos_next.errors import DomainError

from .models import McpConnector, McpToolGrant, ProviderDataAgreement, TenantSkillEnablement

PUBLIC = frozenset({"public", "synthetic"})


@dataclass(frozen=True)
class EgressDecision:
    provider: str
    data_categories: tuple[str, ...]
    agreement_id: str | None
    agreement_revision: int | None
    checked_at: datetime


def egress(session, scope, provider, *, data_categories=None):
    # data_categories is supplied by the host from projected fields, not by a tool payload.
    categories = frozenset(data_categories or scope.data_categories)
    if not categories:
        raise DomainError("FORBIDDEN_SCOPE", "出站资料性质未登记。")
    agreement = session.scalar(
        select(ProviderDataAgreement)
        .where(
            ProviderDataAgreement.tenant_id == scope.tenant_id,
            ProviderDataAgreement.provider == provider,
        )
        .order_by(ProviderDataAgreement.revision.desc())
        .limit(1)
    )
    current = bool(
        agreement
        and agreement.active
        and agreement.signed_on <= now()
        and agreement.expires_at > now()
    )
    # P26: a registered current agreement restricts categories; its absence never blocks.
    if current and not categories <= set(agreement.data_categories):
        raise DomainError(
            "FORBIDDEN_SCOPE",
            "资料类别超出该服务商已登记协议的许可范围。",
            detail={"reason_key": "provider_agreement_category"},
        )
    return EgressDecision(
        provider,
        tuple(sorted(categories)),
        str(agreement.id) if current else None,
        agreement.revision if current else None,
        now(),
    )


def skill_enabled(session, scope, skill):
    row = session.scalar(
        select(TenantSkillEnablement).where(
            TenantSkillEnablement.tenant_id == scope.tenant_id,
            TenantSkillEnablement.skill_key == skill.key,
        )
    )
    return bool(row and row.enabled)


def qualified(
    session, scope, skill, model_version, *, model_digest=None, tool_digest=None, lock=False
):
    from .skill_qualification import is_pilot

    query = select(TenantSkillEnablement).where(
        TenantSkillEnablement.tenant_id == scope.tenant_id,
        TenantSkillEnablement.skill_key == skill.key,
    )
    query = query.execution_options(populate_existing=True)
    row = session.scalar(query.with_for_update() if lock else query)
    # A case list is evidence of the user's review, never automatically created by the Agent.
    return bool(
        row
        and row.enabled
        and is_pilot(session, scope.tenant_id, lock=lock)
        and row.pilot
        and not row.quality_paused
        and row.qualified_skill_digest == skill.digest
        and model_digest is not None
        and row.qualified_model_digest == model_digest
        and tool_digest is not None
        and row.qualified_tool_digest == tool_digest
        and not row.qualification_revoked
        and row.qualified_skill_version == skill.version
        and row.qualified_model_version == model_version
        and row.reviewed_by
        and row.reviewed_at
        and len(set(row.review_case_refs)) >= 10
    )


def mcp_admission(
    session,
    scope,
    connector_id,
    tool,
    *,
    loaded_skills,
    automation_rule_id=None,
    external_write=False,
):
    connector = session.get(McpConnector, connector_id)
    if not connector or connector.tenant_id != scope.tenant_id or not connector.active:
        raise DomainError("FORBIDDEN_SCOPE", "MCP 服务未被当前租户管理员准入。")
    registered = connector.tools.get(tool)
    if not isinstance(registered, dict):
        raise DomainError("FORBIDDEN_SCOPE", "MCP 工具未登记。")
    from .mcp_binding import connector_binding

    grants = session.scalars(
        select(McpToolGrant).where(
            McpToolGrant.tenant_id == scope.tenant_id,
            McpToolGrant.connector_id == connector.id,
            McpToolGrant.tool == tool,
            McpToolGrant.expires_at > now(),
            McpToolGrant.active.is_(True),
            McpToolGrant.connector_binding_digest == connector_binding(connector, tool),
        )
    ).all()
    valid = [
        g
        for g in grants
        if (g.skill_key is not None and g.skill_key in loaded_skills)
        or (automation_rule_id is not None and g.automation_rule_id == automation_rule_id)
    ]
    if not valid:
        raise DomainError("FORBIDDEN_SCOPE", "MCP 工具尚无当前技能或规则的逐项授权。")
    write = registered.get("kind") != "read"
    if write and (not external_write or not any(g.explicit_external_write for g in valid)):
        raise DomainError("NAMED_DECISION_REQUIRED", "外部写入须具名决定或该连接器的明确授权。")
    if scope.isolation == "main" and not write:
        raise DomainError("FORBIDDEN_SCOPE", "MCP 原文须交给只读隔离子任务。")
    return connector, registered, valid
