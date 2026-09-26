"""Project-bound external access credentials with named responsibility and revocation."""

import secrets
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import Connection, Engine, case, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Text
from app.db.schema import tables
from app.domain.customer_report_packages import customer
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.quality_operations import authorize
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

Scope = Literal["work.read", "customer_reports.read", "customer_receipts.write"]
CAPABILITIES = {
    "work.read": "项目任务与问题的明确字段读取",
    "customer_reports.read": "本客户当前获准报告内容和文件读取",
    "customer_receipts.write": "本客户获准文件的外部接收回执登记",
}


class CredentialDraft(Contract):
    label: str = Field(min_length=1, max_length=128)
    audience: Literal["internal", "customer"]
    customer_id: UUID | None = None
    scopes: tuple[Scope, ...] = Field(min_length=1, max_length=3)
    expires_at: AwareDatetime
    purpose: Text

    @model_validator(mode="after")
    def explicit(self) -> Self:
        if len(set(self.scopes)) != len(self.scopes):
            raise ValueError("用途不能重复")
        if self.audience == "internal":
            if self.customer_id is not None or self.scopes != ("work.read",):
                raise ValueError("内部工程凭据只授予工程读取")
        elif (
            self.customer_id is None
            or "work.read" in self.scopes
            or "customer_reports.read" not in self.scopes
        ):
            raise ValueError("客户凭据须明确客户并授予客户报告读取，不可混入内部工程资料")
        return self


class CredentialCreate(CredentialDraft):
    request_id: UUID


class CredentialRevoke(Contract):
    credential_id: UUID
    request_id: UUID
    reason: Text


class CredentialHistory(Contract):
    before_id: UUID | None = None


class CallHistory(Contract):
    credential_id: UUID
    before_id: UUID | None = None


def manage(c: Connection, context: AuthContext, project: UUID) -> None:
    authorize(c, context, project, Action.INTEGRATION_PROJECT_MANAGE)


def revocation(c: Connection, tenant: UUID, identity: UUID) -> Any:
    t = tables.open_api_revocations
    return (
        c.execute(select(t).where(t.c.tenant_id == tenant, t.c.credential_id == identity))
        .mappings()
        .one_or_none()
    )


def metadata(c: Connection, row: Any) -> dict[str, Any]:
    revoked = revocation(c, row["tenant_id"], row["id"])
    return {
        **_plain(
            {
                k: row[k]
                for k in (
                    "id",
                    "project_id",
                    "label",
                    "audience",
                    "customer_id",
                    "scopes",
                    "expires_at",
                    "purpose",
                    "principal_user_id",
                    "created_at",
                )
            }
        ),
        "revocation": _plain(revoked) if revoked else None,
        "expired": row["expires_at"] <= datetime.now(UTC),
    }


def event(c: Connection, context: AuthContext, project: UUID, identity: UUID, action: str) -> None:
    EventAuditWriter(
        c, tenant_id=context.tenant.id, project_id=project, actor_user_id=context.user.id
    ).record(
        EventDraft(
            event_id=f"open-api:{identity}:{action}",
            event_type="OPEN_API_ACCESS_CHANGED",
            source="open_api_service",
            entity_id=identity,
            payload={"record_id": str(identity), "action": action},
        ),
        AuditDraft(
            action=f"open_api.{action}",
            after_snapshot={"record_id": str(identity), "action": action},
        ),
    )


class OpenApiCredentialService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def options(self, context: AuthContext, project: UUID) -> dict[str, Any]:
        from app.domain.customer_report_packages import CustomerReportService, PackageOptions
        from app.settings import get_settings

        with self.engine.connect() as c:
            manage(c, context, project)
        return {
            "capabilities": CAPABILITIES,
            "enabled": get_settings().open_api_enabled,
            "customers": CustomerReportService(self.engine).options(
                context, project, PackageOptions()
            )["customers"],
            "limits": {"calls_per_minute": 60, "max_lifetime_days": 365},
            "contract_version": "open-api.v1",
        }

    def create(
        self, context: AuthContext, project: UUID, command: CredentialCreate
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            manage(c, context, project)
            if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project):
                raise ProductWorkError("项目不可用")
            t = tables.open_api_credentials
            signature = digest(
                {"project": str(project), "command": command.model_dump(mode="json")}
            )
            old = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.principal_user_id == context.user.id,
                        t.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if old:
                if old["request_digest"] != signature:
                    raise ProductWorkError("同一请求不能改变凭据范围")
                return {
                    "credential": metadata(c, old),
                    "access_token": None,
                    "message": "该凭据已创建，密钥不再展示；未收到原值时请撤销并重新创建。",
                }
            now = datetime.now(UTC)
            if not now < command.expires_at <= now + timedelta(days=365):
                raise ProductWorkError("有效期须晚于现在且不超过365天")
            if command.customer_id:
                customer(c, context, project, command.customer_id)
                authorize(c, context, project, Action.CHANGE_VIEW)
            else:
                authorize(c, context, project, Action.WORK_ITEM_VIEW)
            identity = uuid4()
            token = f"pdos_api_{identity.hex}.{secrets.token_urlsafe(32)}"
            row = (
                c.execute(
                    t.insert()
                    .values(
                        id=identity,
                        tenant_id=context.tenant.id,
                        project_id=project,
                        principal_user_id=context.user.id,
                        principal_auth_version=context.user.auth_version,
                        label=command.label,
                        audience=command.audience,
                        customer_id=command.customer_id,
                        scopes=list(command.scopes),
                        expires_at=command.expires_at,
                        purpose=command.purpose,
                        verifier=sha256(token.encode()).hexdigest(),
                        request_id=command.request_id,
                        request_digest=signature,
                        created_at=now,
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            event(c, context, project, identity, "credential_created")
            return {
                "credential": metadata(c, row),
                "access_token": token,
                "message": "密钥仅本次展示，请交由实际接入系统妥善保管。系统仅保留校验摘要。",
            }

    def revoke(
        self, context: AuthContext, project: UUID, command: CredentialRevoke
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            manage(c, context, project)
            k, t = tables.open_api_credentials, tables.open_api_revocations
            # Same credential lock used by the external call transaction.
            key = (
                c.execute(
                    select(k)
                    .where(
                        k.c.tenant_id == context.tenant.id,
                        k.c.project_id == project,
                        k.c.id == command.credential_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if key is None:
                raise ProductWorkError("接口凭据不存在或不属于此项目")
            signature = digest(
                {"project": str(project), "command": command.model_dump(mode="json")}
            )
            old = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.actor_user_id == context.user.id,
                        t.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if old:
                if old["request_digest"] != signature:
                    raise ProductWorkError("同一请求不能改变撤销对象或依据")
                return _plain(old)
            if revocation(c, context.tenant.id, command.credential_id):
                raise ProductWorkError("凭据已撤销，请刷新历史")
            identity = uuid4()
            row = (
                c.execute(
                    t.insert()
                    .values(
                        id=identity,
                        tenant_id=context.tenant.id,
                        project_id=project,
                        credential_id=command.credential_id,
                        actor_user_id=context.user.id,
                        reason=command.reason,
                        request_id=command.request_id,
                        request_digest=signature,
                        created_at=datetime.now(UTC),
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            event(c, context, project, identity, "credential_revoked")
            return _plain(row)

    def history(
        self, context: AuthContext, project: UUID, query: CredentialHistory
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            manage(c, context, project)
            t = tables.open_api_credentials
            q = select(t).where(t.c.tenant_id == context.tenant.id, t.c.project_id == project)
            if query.before_id:
                q = q.where(t.c.id < query.before_id)
            rows = c.execute(q.order_by(t.c.id.desc()).limit(21)).mappings().all()
            return {
                "items": [metadata(c, r) for r in rows[:20]],
                "next_before_id": str(rows[19]["id"]) if len(rows) > 20 else None,
            }

    def calls(self, context: AuthContext, project: UUID, query: CallHistory) -> dict[str, Any]:
        with self.engine.connect() as c:
            manage(c, context, project)
            t, k = tables.open_api_calls, tables.open_api_credentials
            if (
                c.execute(
                    select(k.c.id).where(
                        k.c.tenant_id == context.tenant.id,
                        k.c.project_id == project,
                        k.c.id == query.credential_id,
                    )
                ).first()
                is None
            ):
                raise ProductWorkError("接口凭据不存在")
            q = select(
                t.c.id,
                t.c.operation,
                t.c.request_id,
                t.c.status_code,
                t.c.response_digest,
                t.c.created_at,
                case(
                    (
                        (t.c.operation == "customer_receipts.record") & (t.c.status_code == 200),
                        t.c.response["result"],
                    ),
                    else_=None,
                ).label("receipt"),
            ).where(t.c.tenant_id == context.tenant.id, t.c.credential_id == query.credential_id)
            if query.before_id:
                q = q.where(t.c.id < query.before_id)
            rows = c.execute(q.order_by(t.c.id.desc()).limit(21)).mappings().all()
            return {
                "items": [_plain(v) for v in rows[:20]],
                "next_before_id": str(rows[19]["id"]) if len(rows) > 20 else None,
            }
