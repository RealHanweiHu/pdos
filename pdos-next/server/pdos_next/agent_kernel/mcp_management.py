"""Named connector admission and confirmed tool grants; no network or credential lookup."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator
from sqlalchemy import select, text

from pdos_next.errors import DomainError
from pdos_next.model_configuration.commands import CurrentAdministrator
from pdos_next.model_configuration.ports import ManagementContext
from pdos_next.models import Category, Grant, Principal, Receipt, RequestKey, now
from pdos_next.request_proof import command_inputs_once
from pdos_next.schema_base import StrictModel

from .mcp_binding import check_schema, connector_binding
from .models import McpConnector, McpControlRecord, McpToolGrant, TenantAdministrator
from .skills import SkillCatalog


class ToolRegistration(StrictModel):
    name: str = Field(pattern=r"^[A-Za-z0-9_][A-Za-z0-9_.:/-]{0,159}$")
    description: str = Field(min_length=1, max_length=2000)
    kind: Literal["read", "write"]
    input_schema: dict
    output_schema: dict | None = None

    @field_validator("input_schema", "output_schema")
    @classmethod
    def schema_local(cls, value):
        return check_schema(value) if value is not None else None


class AllowConnector(StrictModel):
    key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9:_.@/-]{0,159}$")
    expected_revision: int = Field(ge=0)
    endpoint: str | None = Field(default=None, min_length=1, max_length=1000)
    secret_ref: str | None = Field(default=None, min_length=1, max_length=200)
    tools: list[ToolRegistration] = Field(default_factory=list, max_length=50)
    remove_tools: list[str] = Field(default_factory=list, max_length=50)
    active: bool
    decision: Literal["批准"]
    reason: str = Field(min_length=1, max_length=4000)
    approval_token: str | None = Field(default=None, min_length=20, max_length=128)

    @field_validator("endpoint")
    @classmethod
    def endpoint_url(cls, value):
        if value is not None:
            try:
                parts = urlsplit(value)
                valid = (
                    parts.scheme in {"https", "http"}
                    and parts.hostname
                    and not parts.username
                    and not parts.password
                    and not parts.fragment
                )
                _ = parts.port
            except ValueError:
                valid = False
            if not valid or any(ord(char) <= 32 for char in value):
                raise ValueError("请填写不含账号、密钥或片段的 HTTP(S) 服务地址。")
        return value

    @model_validator(mode="after")
    def unique_patch(self):
        names = [tool.name for tool in self.tools]
        if (
            len(names) != len(set(names))
            or len(self.remove_tools) != len(set(self.remove_tools))
            or set(names) & set(self.remove_tools)
        ):
            raise ValueError("同一批工具新增/更新/移除不能重复。")
        if not self.reason.strip():
            raise ValueError("请填写本人准入决定理由。")
        return self


class GrantTool(StrictModel):
    connector_id: UUID
    grant_id: UUID
    expected_revision: int = Field(ge=0)
    connector_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    tool: str = Field(min_length=1, max_length=160)
    skill_key: str = Field(min_length=1, max_length=160)
    active: bool
    expires_at: datetime | None = None
    allow_external_write: bool = False
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)

    @model_validator(mode="after")
    def fields_for_action(self):
        if self.active and (self.expires_at is None or not self.connector_digest):
            raise ValueError("授权须绑定当前连接器，并填写明确到期时间。")
        return self


class ConnectorPage(StrictModel):
    cursor: UUID | None = None
    page_size: int = Field(default=20, ge=1, le=100)


class ToolPage(ConnectorPage):
    cursor_key: str | None = Field(default=None, min_length=1, max_length=160)


@dataclass
class Prepared:
    row: object | None
    review: dict
    values: dict
    confirmation_id: UUID | None = None


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"approval_token", "confirmation_token"})


def administrator(session, ctx):
    if not CurrentAdministrator(session, ctx).is_current_human_admin(
        ManagementContext(ctx.tenant_id, ctx.actor_id)
    ):
        raise DomainError(
            "NAMED_DECISION_REQUIRED", "请由当前租户管理员本人办理 MCP 准入与授权。", 403
        )


def scope_check(session, ctx, command, scope):
    if command.product_id is not None or command.source_read_set:
        raise DomainError("FORBIDDEN_SCOPE", "MCP 管理只办理当前租户的登记。", 403)
    if command.expected_revision != scope.revision:
        raise DomainError("VERSION_CONFLICT", "当前品类范围已变化，请刷新。")
    administrator(session, ctx)


def lock_key(session, tenant, key):
    from pdos_next.service import digest

    number = int(digest(["mcp-management", tenant, key])[:16], 16)
    session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": number if number < 2**63 else number - 2**64},
    )


@command_inputs_once
def prepared(session, ctx, command, scope, payload):
    scope_check(session, ctx, command, scope)
    if isinstance(payload, AllowConnector):
        lock_key(session, ctx.tenant_id, payload.key)
        row = session.scalar(
            select(McpConnector)
            .where(McpConnector.tenant_id == ctx.tenant_id, McpConnector.key == payload.key)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (row.revision if row else 0) != payload.expected_revision:
            raise DomainError("VERSION_CONFLICT", "连接器登记已变化，请核对当前版本。")
        endpoint = (
            payload.endpoint if payload.endpoint is not None else row.endpoint if row else None
        )
        secret = (
            payload.secret_ref
            if payload.secret_ref is not None
            else row.secret_ref
            if row
            else None
        )
        if not endpoint or not secret:
            raise DomainError("VALIDATION_FAILED", "首次登记须填写服务地址和服务器凭据引用。", 422)
        tools = dict(row.tools) if row else {}
        for key in payload.remove_tools:
            if key not in tools:
                raise DomainError("VERSION_CONFLICT", "要移除的工具不在当前登记中。")
            del tools[key]
        tools.update(
            {
                tool.name: tool.model_dump(exclude={"name"}, exclude_none=True)
                for tool in payload.tools
            }
        )
        values = dict(
            key=payload.key,
            endpoint=endpoint,
            secret_ref=secret,
            tools=tools,
            active=payload.active,
            admitted_by=ctx.actor_id,
            revision=payload.expected_revision + 1,
        )
        from types import SimpleNamespace

        binding = connector_binding(SimpleNamespace(**values))
        return Prepared(
            row,
            {
                "key": payload.key,
                "endpoint": endpoint,
                "credential_reference": "本次登记" if payload.secret_ref else "沿用已登记引用",
                "credential_availability": "unverified",
                "active": payload.active,
                "previous_revision": payload.expected_revision,
                "next_revision": payload.expected_revision + 1,
                "upsert_tools": [tool.model_dump(exclude_none=True) for tool in payload.tools],
                "remove_tools": payload.remove_tools,
                "tool_count": len(tools),
                "binding_changed": bool(
                    row and (connector_binding(row) != binding or row.tools != tools)
                ),
                "reason": payload.reason,
                "effect": (
                    "只登记允许的服务和工具，不发起连接或授予工具使用权。"
                    "目标变更影响此连接器授权；工具结构变更只影响对应工具授权。停用阻止后续调用。"
                ),
            },
            values,
        )
    connector = session.scalar(
        select(McpConnector)
        .where(McpConnector.tenant_id == ctx.tenant_id, McpConnector.id == payload.connector_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if connector is None:
        raise DomainError("SOURCE_UNAVAILABLE", "连接器登记当前不可用。")
    row = (
        session.scalar(
            select(McpToolGrant)
            .where(McpToolGrant.tenant_id == ctx.tenant_id, McpToolGrant.id == payload.grant_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if payload.grant_id
        else None
    )
    if (payload.expected_revision > 0 or not payload.active) and not row:
        raise DomainError("SOURCE_UNAVAILABLE", "原工具授权当前不可读。")
    if (row.revision if row else 0) != payload.expected_revision:
        raise DomainError("VERSION_CONFLICT", "工具授权已变化，请读取当前版本。")
    if row and (row.connector_id, row.tool, row.skill_key, row.automation_rule_id) != (
        connector.id,
        payload.tool,
        payload.skill_key,
        None,
    ):
        raise DomainError("FORBIDDEN_SCOPE", "原授权不能改换连接器、工具或技能范围。", 403)
    spec = connector.tools.get(payload.tool)
    binding = connector_binding(connector, payload.tool)
    if payload.active:
        if not connector.active or not isinstance(spec, dict):
            raise DomainError("SOURCE_UNAVAILABLE", "请先准入当前连接器与工具。")
        if binding != payload.connector_digest:
            raise DomainError("VERSION_CONFLICT", "连接器目标或工具结构已变化，请重新核对。")
        if SkillCatalog().configuration(payload.skill_key) is None:
            raise DomainError("SOURCE_UNAVAILABLE", "技能包未登记。")
        if not payload.expires_at.tzinfo or payload.expires_at <= now():
            raise DomainError("VALIDATION_FAILED", "授权到期时间须明确时区并晚于当前时间。", 422)
        if payload.allow_external_write and spec.get("kind") != "write":
            raise DomainError("VALIDATION_FAILED", "只读工具不需要外部写入授权。", 422)
    values = dict(
        connector_id=connector.id,
        tool=payload.tool,
        skill_key=payload.skill_key,
        automation_rule_id=None,
        active=payload.active,
        expires_at=payload.expires_at if payload.active else row.expires_at,
        explicit_external_write=payload.allow_external_write
        if payload.active
        else row.explicit_external_write,
        connector_binding_digest=binding if payload.active else row.connector_binding_digest,
        authorized_by=ctx.actor_id,
        revision=payload.expected_revision + 1,
    )
    return Prepared(
        row,
        {
            "connector_id": str(connector.id),
            "key": connector.key,
            "endpoint": connector.endpoint,
            "tool": payload.tool,
            "skill_key": payload.skill_key,
            "tool_kind": spec.get("kind") if spec else None,
            "active": payload.active,
            "allow_external_write": values["explicit_external_write"],
            "expires_at": values["expires_at"].isoformat(),
            "previous_revision": payload.expected_revision,
            "next_revision": payload.expected_revision + 1,
            "effect": "撤销此项授权，保留历史和已完成回执。"
            if not payload.active
            else "授权所选技能使用这一工具，仍核对实际技能加载与资料出站政策。"
            + (
                " 已明确允许该工具向登记的连接器写入或发送。"
                if payload.allow_external_write
                else " 未授权外部写入。"
            ),
        },
        values,
    )


def validate(session, ctx, command, scope, payload):
    return prepared(session, ctx, command, scope, payload)


def preview_view(session, ctx, command, scope, payload):
    return prepared(session, ctx, command, scope, payload).review


CONNECTOR_FIELDS = ("key", "endpoint", "secret_ref", "tools", "active", "admitted_by", "revision")
GRANT_FIELDS = (
    "connector_id",
    "tool",
    "skill_key",
    "automation_rule_id",
    "active",
    "expires_at",
    "explicit_external_write",
    "connector_binding_digest",
    "authorized_by",
    "revision",
)


def after_snapshot(row, fields):
    def wire(value):
        return (
            value.isoformat()
            if isinstance(value, datetime)
            else str(value)
            if isinstance(value, UUID)
            else value
        )

    return {key: wire(getattr(row, key)) for key in fields}


def apply_validated(session, ctx, command, scope, payload, plan):
    receipt, control_id = uuid4(), uuid4()
    is_connector = isinstance(payload, AllowConnector)
    cls = McpConnector if is_connector else McpToolGrant
    row = plan.row or cls(id=uuid4() if is_connector else payload.grant_id, tenant_id=ctx.tenant_id)
    for key, value in plan.values.items():
        setattr(row, key, value)
    row.receipt_id = row.prepared_receipt_id = receipt
    row.control_record_id = control_id
    row.confirmation_id = plan.confirmation_id
    row.status = (
        ("admitted" if row.active else "inactive")
        if is_connector
        else ("granted" if row.active else "revoked")
    )
    row.action_result = (
        {"key": row.key, "active": row.active, "tool_count": len(row.tools)}
        if is_connector
        else {
            "connector_id": str(row.connector_id),
            "tool": row.tool,
            "skill_key": row.skill_key,
            "active": row.active,
            "allow_external_write": row.explicit_external_write,
        }
    )
    control = McpControlRecord(
        id=control_id,
        tenant_id=ctx.tenant_id,
        operation=command.operation,
        subject_id=row.id,
        subject_revision=row.revision,
        decided_by=ctx.actor_id,
        after_snapshot=after_snapshot(row, CONNECTOR_FIELDS if is_connector else GRANT_FIELDS),
        reason=payload.reason
        if is_connector
        else "本人确认工具授权"
        if row.active
        else "本人撤销工具授权",
        receipt_id=receipt,
    )
    session.add(control)
    return row, "mcp_connector" if is_connector else "mcp_tool_grant", "private"


def can_manage(session, ctx):
    admin = session.scalar(
        select(TenantAdministrator.id).where(
            TenantAdministrator.tenant_id == ctx.tenant_id,
            TenantAdministrator.principal_id == ctx.actor_id,
            TenantAdministrator.active.is_(True),
        )
    )
    write = session.scalar(
        select(Grant.can_write).where(
            Grant.tenant_id == ctx.tenant_id,
            Grant.principal_id == ctx.actor_id,
            Grant.category_id == ctx.category_id,
        )
    )
    return bool(admin and write)


def connector_view(row, *, detail=False):
    value = {
        "id": str(row.id),
        "key": row.key,
        "revision": row.revision,
        "active": row.active,
        "tool_count": len(row.tools),
        "receipt_id": str(row.receipt_id) if row.receipt_id else None,
    }
    if detail:
        value.update(
            endpoint=row.endpoint,
            credential_reference_set=bool(row.secret_ref),
            binding_digest=connector_binding(row),
        )
    return value


def reading(session, ctx, page):
    edit = can_manage(session, ctx)
    query = select(McpConnector).where(McpConnector.tenant_id == ctx.tenant_id)
    if page.cursor:
        query = query.where(McpConnector.id > page.cursor)
    rows = list(session.scalars(query.order_by(McpConnector.id).limit(page.page_size + 1)))
    return {
        "items": [connector_view(row, detail=edit) for row in rows[: page.page_size]],
        "can_edit": edit,
        "category_revision": session.get(Category, ctx.category_id).revision,
        "next_cursor": str(rows[page.page_size - 1].id) if len(rows) > page.page_size else None,
    }


def detail(session, ctx, identity, tool_page, grant_page):
    administrator_read = can_manage(session, ctx)
    if not administrator_read:
        raise DomainError(
            "NAMED_DECISION_REQUIRED",
            "连接器工具与授权明细只供有当前品类写入权的租户管理员核对。",
            403,
        )
    row = session.get(McpConnector, identity)
    if not row or row.tenant_id != ctx.tenant_id:
        raise DomainError("SOURCE_UNAVAILABLE", "连接器登记不可读。", 404)
    names = sorted(
        name for name in row.tools if tool_page.cursor_key is None or name > tool_page.cursor_key
    )
    grants = select(McpToolGrant).where(
        McpToolGrant.tenant_id == ctx.tenant_id, McpToolGrant.connector_id == row.id
    )
    if grant_page.cursor:
        grants = grants.where(McpToolGrant.id > grant_page.cursor)
    rows = list(session.scalars(grants.order_by(McpToolGrant.id).limit(grant_page.page_size + 1)))
    people = (
        dict(
            session.execute(
                select(Principal.id, Principal.name).where(
                    Principal.tenant_id == ctx.tenant_id,
                    Principal.id.in_({row.authorized_by for row in rows}),
                )
            ).all()
        )
        if rows
        else {}
    )
    instant = now()
    return {
        "connector": connector_view(row, detail=True),
        "tools": [
            {"name": name, **row.tools[name], "binding_digest": connector_binding(row, name)}
            for name in names[: tool_page.page_size]
        ],
        "next_tool_cursor": names[tool_page.page_size - 1]
        if len(names) > tool_page.page_size
        else None,
        "grants": [
            {
                "id": str(grant.id),
                "tool": grant.tool,
                "skill_key": grant.skill_key,
                "automation_rule_id": str(grant.automation_rule_id)
                if grant.automation_rule_id
                else None,
                "revision": grant.revision,
                "active": grant.active,
                "expires_at": grant.expires_at.isoformat(),
                "allow_external_write": grant.explicit_external_write,
                "authorized_by_name": people.get(grant.authorized_by),
                "receipt_id": str(grant.receipt_id) if grant.receipt_id else None,
                "state": "revoked"
                if not grant.active
                else "expired"
                if grant.expires_at <= instant
                else "connector_inactive"
                if not row.active
                else "stale"
                if grant.connector_binding_digest != connector_binding(row, grant.tool)
                else "active",
            }
            for grant in rows[: grant_page.page_size]
        ],
        "next_grant_cursor": str(rows[grant_page.page_size - 1].id)
        if len(rows) > grant_page.page_size
        else None,
        "as_of": instant.isoformat(),
        "category_revision": session.get(Category, ctx.category_id).revision,
    }


def recover(session, ctx, command):
    from pdos_next.service import command_digest, receipt_view

    cls = {"mcp.connector.allow": AllowConnector, "mcp.tool.grant": GrantTool}.get(
        command.operation
    )
    if not cls or command.product_id is not None or command.source_read_set:
        raise DomainError("VALIDATION_FAILED", "这里只核对原 MCP 登记或授权请求。", 422)
    if command.category_id is not None and command.category_id != ctx.category_id:
        raise DomainError("FORBIDDEN_SCOPE", "原请求与当前品类不一致。", 403)
    cls.model_validate(command.payload)
    key = session.scalar(
        select(RequestKey).where(
            RequestKey.tenant_id == ctx.tenant_id,
            RequestKey.actor_id == ctx.actor_id,
            RequestKey.key == command.idempotency_key,
        )
    )
    if key is None:
        return None
    if key.digest != command_digest(command):
        raise DomainError("DUPLICATE_INTENT_CONFLICT", "原请求编号绑定不同内容。")
    row = session.get(Receipt, key.receipt_id)
    if not row or row.operation != command.operation or row.category_id != ctx.category_id:
        raise DomainError("FORBIDDEN_SCOPE", "原回执不在当前可读范围。", 403)
    return receipt_view(row)


class DetailPage(StrictModel):
    tool_cursor: str | None = Field(default=None, min_length=1, max_length=160)
    grant_cursor: UUID | None = None
    page_size: int = Field(default=20, ge=1, le=100)


def history(session, ctx, identity, page):
    if not can_manage(session, ctx):
        raise DomainError(
            "NAMED_DECISION_REQUIRED", "MCP 变更历史须由当前有权的租户管理员核对。", 403
        )
    connector = session.get(McpConnector, identity)
    if not connector or connector.tenant_id != ctx.tenant_id:
        raise DomainError("SOURCE_UNAVAILABLE", "连接器登记不可读。", 404)
    grants = select(McpToolGrant.id).where(
        McpToolGrant.tenant_id == ctx.tenant_id, McpToolGrant.connector_id == connector.id
    )
    query = select(
        McpControlRecord.id,
        McpControlRecord.operation,
        McpControlRecord.subject_id,
        McpControlRecord.subject_revision,
        McpControlRecord.decided_by,
        McpControlRecord.reason,
        McpControlRecord.receipt_id,
        McpControlRecord.created_at,
    ).where(
        McpControlRecord.tenant_id == ctx.tenant_id,
        (McpControlRecord.subject_id == connector.id) | McpControlRecord.subject_id.in_(grants),
    )
    if page.cursor:
        from sqlalchemy import tuple_

        cursor = session.get(McpControlRecord, page.cursor)
        if not cursor or (
            cursor.subject_id != connector.id
            and not session.scalar(
                select(McpToolGrant.id).where(
                    McpToolGrant.id == cursor.subject_id, McpToolGrant.connector_id == connector.id
                )
            )
        ):
            raise DomainError("VALIDATION_FAILED", "历史分页定位已失效，请刷新。", 422)
        query = query.where(
            tuple_(McpControlRecord.created_at, McpControlRecord.id)
            < (cursor.created_at, cursor.id)
        )
    rows = list(
        session.execute(
            query.order_by(McpControlRecord.created_at.desc(), McpControlRecord.id.desc()).limit(
                page.page_size + 1
            )
        )
    )
    people = (
        dict(
            session.execute(
                select(Principal.id, Principal.name).where(
                    Principal.tenant_id == ctx.tenant_id,
                    Principal.id.in_({row.decided_by for row in rows}),
                )
            ).all()
        )
        if rows
        else {}
    )
    return {
        "items": [
            {
                "id": str(row.id),
                "operation": row.operation,
                "subject_id": str(row.subject_id),
                "revision": row.subject_revision,
                "decided_by_name": people.get(row.decided_by),
                "reason": row.reason,
                "receipt_id": str(row.receipt_id),
                "created_at": row.created_at.isoformat(),
            }
            for row in rows[: page.page_size]
        ],
        "next_cursor": str(rows[page.page_size - 1].id) if len(rows) > page.page_size else None,
    }
