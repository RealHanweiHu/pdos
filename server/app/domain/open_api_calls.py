"""Explicit external API operations; credentials never enter ordinary human-action routes."""

import hmac
import re
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field
from sqlalchemy import Engine, func, select

from app.auth.repository import AuthContext, AuthRepository
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.customer_report_packages import (
    CustomerReportService,
    approved,
    customer,
    last_decision,
)
from app.domain.open_api_credentials import revocation
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.quality_operations import authorize
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft
from app.settings import get_settings


class ApiCall(Contract):
    request_id: UUID


class WorkQuery(ApiCall):
    kind: Literal["task", "issue"]
    before_id: UUID | None = None
    limit: int = Field(default=20, ge=1, le=100)


class ReportQuery(ApiCall):
    before_id: UUID | None = None


class ReportRead(ApiCall):
    package_id: UUID


class FileRead(ApiCall):
    file_id: UUID


class FileReceipt(FileRead):
    content_digest: Digest
    result: Literal["received", "unable_to_open"]
    received_at: AwareDatetime
    recipient_reference: str = Field(min_length=1, max_length=128)
    note: Text


class OpenApiError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


OPERATIONS = {
    "work.query": "work.read",
    "customer_reports.query": "customer_reports.read",
    "customer_reports.read": "customer_reports.read",
    "customer_files.read": "customer_reports.read",
    "customer_receipts.record": "customer_receipts.write",
}


def permission(c: Any, context: AuthContext, key: Any, project: UUID, operation: str) -> None:
    if key["project_id"] != project or OPERATIONS[operation] not in key["scopes"]:
        raise PermissionError("接口授权范围不匹配")
    authorize(c, context, project, Action.INTEGRATION_PROJECT_MANAGE)
    if operation == "work.query":
        authorize(c, context, project, Action.WORK_ITEM_VIEW)
    else:
        if key["customer_id"] is None or key["audience"] != "customer":
            raise PermissionError("客户范围不匹配")
        customer(c, context, project, key["customer_id"])
        authorize(c, context, project, Action.CHANGE_VIEW)


def customer_package(
    c: Any,
    context: AuthContext,
    project: UUID,
    key: Any,
    identity: UUID,
    expected_decision: UUID | None = None,
) -> tuple[Any, Any]:
    t = tables.customer_report_packages
    match = c.execute(
        select(t.c.id).where(
            t.c.tenant_id == context.tenant.id,
            t.c.project_id == project,
            t.c.customer_id == key["customer_id"],
            t.c.id == identity,
        )
    ).first()
    if match is None:
        raise PermissionError("报告不在客户授权范围")
    decision = last_decision(c, context.tenant.id, identity)
    if decision is None:
        raise ProductWorkError("报告当前不可提供")
    if expected_decision and decision["id"] != expected_decision:
        raise ProductWorkError("原披露批准已变化，请使用新调用编号")
    return approved(c, context, project, identity, decision["id"])


def customer_file(c: Any, context: AuthContext, project: UUID, key: Any, identity: UUID) -> Any:
    t = tables.customer_report_files
    row = (
        c.execute(
            select(*(col for col in t.c if col.name != "content")).where(
                t.c.tenant_id == context.tenant.id, t.c.project_id == project, t.c.id == identity
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkError("客户文件不可提供")
    customer_package(c, context, project, key, row["package_id"], row["decision_id"])
    return row


def file_projection(row: Any) -> dict[str, Any]:
    return _plain(
        {
            k: row[k]
            for k in (
                "id",
                "format",
                "filename",
                "mime_type",
                "byte_size",
                "content_digest",
                "created_at",
            )
        }
    )


class OpenApiCallService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def invoke(
        self, token: str, project: UUID, operation: str, command: ApiCall
    ) -> tuple[int, dict[str, Any], tuple[bytes, str, str] | None]:
        if not get_settings().open_api_enabled:
            raise OpenApiError(503, "受控接口尚未启用")
        match = re.fullmatch(r"pdos_api_([0-9a-f]{32})\.([A-Za-z0-9_-]{43})", token)
        if match is None:
            raise OpenApiError(401, "接口凭据无效")
        identity = UUID(hex=match.group(1))
        binary = None
        with self.engine.begin() as c:
            k, t = tables.open_api_credentials, tables.open_api_calls
            key = (
                c.execute(select(k).where(k.c.id == identity).with_for_update())
                .mappings()
                .one_or_none()
            )
            if key is None or not hmac.compare_digest(
                key["verifier"], sha256(token.encode()).hexdigest()
            ):
                raise OpenApiError(401, "接口凭据无效")
            now = datetime.now(UTC)
            context = AuthRepository(self.engine).find_user_context(key["principal_user_id"])
            if (
                context is None
                or not context.user.is_active
                or context.tenant.status != "active"
                or context.tenant.id != key["tenant_id"]
                or context.user.auth_version != key["principal_auth_version"]
                or key["expires_at"] <= now
                or revocation(c, key["tenant_id"], identity)
            ):
                raise OpenApiError(401, "接口凭据已失效")
            signature = digest(
                {
                    "project": str(project),
                    "operation": operation,
                    "command": command.model_dump(mode="json"),
                }
            )
            old = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == key["tenant_id"],
                        t.c.credential_id == identity,
                        t.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if old:
                if old["request_digest"] != signature:
                    raise OpenApiError(409, "调用编号已用于不同请求")
                try:
                    permission(c, context, key, project, operation)
                    for ref in old["resource_refs"]:
                        customer_package(
                            c,
                            context,
                            project,
                            key,
                            UUID(ref["package_id"]),
                            UUID(ref["decision_id"]),
                        )
                    if old["file_id"]:
                        customer_file(c, context, project, key, old["file_id"])
                    if operation == "customer_files.read" and old["status_code"] == 200:
                        binary = CustomerReportService(self.engine).download(
                            context, project, old["file_id"]
                        )
                except PermissionError as error:
                    raise OpenApiError(403, "当前已无调用或原资料读取权限") from error
                except ProductWorkError as error:
                    raise OpenApiError(409, "原批准或来源已变化，不能重放该资料") from error
                return old["status_code"], {**old["response"], "replayed": True}, binary
            count = c.execute(
                select(func.count())
                .select_from(t)
                .where(t.c.credential_id == identity, t.c.created_at > now - timedelta(minutes=1))
            ).scalar_one()
            if count >= 60:
                raise OpenApiError(429, "一分钟内新调用编号超过60个，请稍后重试")
            references: list[dict[str, str]] = []
            file_id = None
            status = 200
            try:
                permission(c, context, key, project, operation)
                body, references, file_id = self.dispatch(
                    c, context, key, project, operation, command
                )
                if operation == "customer_files.read":
                    assert file_id is not None
                    binary = CustomerReportService(self.engine).download(context, project, file_id)
            except PermissionError:
                status, body = 403, {"error": "调用或客户资料不在当前授权范围"}
                references, file_id = [], None
            except ProductWorkError:
                status, body = (
                    409,
                    {"error": "原记录、批准或请求条件当前不满足，请在原业务核对后使用新调用编号"},
                )
                references, file_id = [], None
            call_id = uuid4()
            response = {
                "call_id": str(call_id),
                "request_id": str(command.request_id),
                "as_of": now.isoformat(),
                "contract_version": "open-api.v1",
                "result": body,
            }
            c.execute(
                t.insert().values(
                    id=call_id,
                    tenant_id=key["tenant_id"],
                    project_id=key["project_id"],
                    credential_id=identity,
                    request_id=command.request_id,
                    operation=operation,
                    request_digest=signature,
                    status_code=status,
                    response=response,
                    response_digest=digest(response),
                    resource_refs=references,
                    file_id=file_id,
                    created_at=now,
                )
            )
            EventAuditWriter(
                c,
                tenant_id=key["tenant_id"],
                project_id=key["project_id"],
                actor_user_id=context.user.id,
            ).record(
                EventDraft(
                    event_id=f"open-api-call:{call_id}",
                    event_type="OPEN_API_CALLED",
                    source="open_api_service",
                    entity_id=call_id,
                    payload={
                        "record_id": str(call_id),
                        "operation": operation,
                        "status_code": status,
                    },
                ),
                AuditDraft(
                    action="open_api.called",
                    after_snapshot={
                        "record_id": str(call_id),
                        "operation": operation,
                        "status_code": status,
                    },
                    context={
                        "authentication_method": "scoped_external_api",
                        "credential_id": str(identity),
                        "responsible_user_id": str(context.user.id),
                    },
                ),
            )
            return status, {**response, "replayed": False}, binary

    def dispatch(
        self,
        c: Any,
        context: AuthContext,
        key: Any,
        project: UUID,
        operation: str,
        command: ApiCall,
    ) -> tuple[dict[str, Any], list[dict[str, str]], UUID | None]:
        if isinstance(command, WorkQuery):
            t = tables.tasks if command.kind == "task" else tables.issues
            columns = (
                ("id", "title", "status", "assignee_user_id", "due_date", "updated_at")
                if command.kind == "task"
                else ("id", "title", "status", "severity", "owner_user_id", "updated_at")
            )
            q = select(*(t.c[k] for k in columns)).where(
                t.c.tenant_id == context.tenant.id, t.c.project_id == project
            )
            if command.before_id:
                q = q.where(t.c.id < command.before_id)
            values = c.execute(q.order_by(t.c.id.desc()).limit(command.limit + 1)).mappings().all()
            return (
                {
                    "items": [_plain(v) for v in values[: command.limit]],
                    "next_before_id": str(values[command.limit - 1]["id"])
                    if len(values) > command.limit
                    else None,
                },
                [],
                None,
            )
        if isinstance(command, ReportQuery):
            t = tables.customer_report_packages
            q = select(t.c.id).where(
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == project,
                t.c.customer_id == key["customer_id"],
            )
            if command.before_id:
                q = q.where(t.c.id < command.before_id)
            values = list(c.execute(q.order_by(t.c.id.desc()).limit(21)).scalars())
            items, refs = [], []
            for identity in values[:20]:
                try:
                    package, decision = customer_package(c, context, project, key, identity)
                except (ProductWorkError, PermissionError):
                    continue
                items.append(
                    {
                        "id": str(identity),
                        "title": package["snapshot"]["projection"]["title"],
                        "approved_at": decision["created_at"].isoformat(),
                    }
                )
                refs.append({"package_id": str(identity), "decision_id": str(decision["id"])})
            return (
                {"items": items, "next_before_id": str(values[19]) if len(values) > 20 else None},
                refs,
                None,
            )
        if isinstance(command, ReportRead):
            row, decision = customer_package(c, context, project, key, command.package_id)
            t = tables.customer_report_files
            files = (
                c.execute(
                    select(*(col for col in t.c if col.name != "content")).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.project_id == project,
                        t.c.package_id == row["id"],
                        t.c.decision_id == decision["id"],
                    )
                )
                .mappings()
                .all()
            )
            return (
                {
                    "projection": row["snapshot"]["projection"],
                    "files": [file_projection(v) for v in files],
                },
                [{"package_id": str(row["id"]), "decision_id": str(decision["id"])}],
                None,
            )
        if isinstance(command, FileRead):
            row = customer_file(c, context, project, key, command.file_id)
            refs = [{"package_id": str(row["package_id"]), "decision_id": str(row["decision_id"])}]
            if isinstance(command, FileReceipt):
                if (
                    command.content_digest != row["content_digest"]
                    or command.received_at < row["created_at"]
                    or command.received_at > datetime.now(UTC) + timedelta(minutes=5)
                ):
                    raise ProductWorkError("接收回执须对应原获准文件及实际时间")
                return (
                    {
                        "file_id": str(command.file_id),
                        "content_digest": command.content_digest,
                        "declared_result": command.result,
                        "received_at": command.received_at.isoformat(),
                        "recipient_reference": command.recipient_reference,
                        "note": command.note,
                        "interpretation": (
                            "外部系统接收声明，不代表客户业务接受、质量签核或认证通过。"
                        ),
                    },
                    refs,
                    command.file_id,
                )
            return {"file": file_projection(row)}, refs, command.file_id
        raise ProductWorkError("接口操作与请求合同不匹配")
