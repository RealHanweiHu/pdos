"""Named project webhook endpoints, explicit activation and durable notifications."""

import base64
import secrets
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import Engine, select, update

from app.auth.repository import AuthContext, AuthRepository
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.customer_report_packages import customer
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.quality_operations import authorize
from app.domain.webhook_sources import SOURCE_EVENTS, notification
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft
from app.integrations.webhook_protocol import PROTOCOL, body_bytes, destination, encrypt_key
from app.settings import get_settings

Topic = Literal[
    "work.updated", "customer_report.ready", "customer_file.ready", "customer_report.withdrawn"
]


class EndpointCreate(Contract):
    request_id: UUID
    label: str = Field(min_length=1, max_length=128)
    url: str = Field(min_length=1, max_length=2048)
    audience: Literal["internal", "customer"]
    customer_id: UUID | None = None
    topics: tuple[Topic, ...] = Field(min_length=1, max_length=3)
    expires_at: AwareDatetime
    purpose: Text

    @model_validator(mode="after")
    def scope(self) -> Self:
        if len(set(self.topics)) != len(self.topics):
            raise ValueError("通知类别不能重复")
        if self.audience == "internal":
            if self.customer_id or self.topics != ("work.updated",):
                raise ValueError("内部端点只接工程事件")
        elif not self.customer_id or "work.updated" in self.topics:
            raise ValueError("客户端点须明确客户且不能接内部工程事件")
        return self


class EndpointControl(Contract):
    endpoint_id: UUID
    request_id: UUID
    expected_version: int = Field(ge=0)
    status: Literal["active", "paused", "revoked"]
    receiver_contract_confirmed: bool = False
    delivery_authorized: bool = False
    reason: Text

    @model_validator(mode="after")
    def active(self) -> Self:
        if self.status == "active" and not (
            self.receiver_contract_confirmed and self.delivery_authorized
        ):
            raise ValueError("启用须明确接收方验签/时间窗/持久去重合同及实际外发授权")
        return self


class EndpointQuery(Contract):
    endpoint_id: UUID


class EndpointHistory(Contract):
    before_id: UUID | None = None


class ControlHistory(EndpointQuery):
    before_version: int | None = Field(default=None, ge=1)


class ScanHistory(EndpointQuery):
    before_event_id: int | None = Field(default=None, ge=1)


class SourceOptions(EndpointQuery):
    before_event_id: int | None = Field(default=None, ge=1)


class NoticePreview(EndpointQuery):
    source_event_id: int = Field(ge=1)


class NoticeSave(NoticePreview):
    request_id: UUID
    expected_digest: Digest
    reason: Text


class DeliveryHistory(EndpointQuery):
    before_id: UUID | None = None


class DeliveryAction(Contract):
    delivery_id: UUID
    request_id: UUID
    action: Literal["retry", "cancel"]
    reason: Text


def control(c: Any, tenant: UUID, endpoint: UUID) -> Any:
    t = tables.webhook_controls
    return (
        c.execute(
            select(t)
            .where(t.c.tenant_id == tenant, t.c.endpoint_id == endpoint)
            .order_by(t.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )


def endpoint(
    c: Any, context: AuthContext, project: UUID, identity: UUID, *, lock: bool = False
) -> Any:
    authorize(c, context, project, Action.INTEGRATION_PROJECT_MANAGE)
    t = tables.webhook_endpoints
    q = select(t).where(
        t.c.tenant_id == context.tenant.id, t.c.project_id == project, t.c.id == identity
    )
    row = c.execute(q.with_for_update() if lock else q).mappings().one_or_none()
    if row is None:
        raise ProductWorkError("Webhook端点不存在或不属于此项目")
    return row


def principal(engine: Engine, row: Any) -> AuthContext:
    context = AuthRepository(engine).find_user_context(row["principal_user_id"])
    if (
        context is None
        or not context.user.is_active
        or context.tenant.status != "active"
        or context.tenant.id != row["tenant_id"]
        or context.user.auth_version != row["principal_auth_version"]
    ):
        raise ProductWorkError("端点具名负责人的原身份已失效")
    return context


def endpoint_meta(c: Any, row: Any) -> dict[str, Any]:
    state = control(c, row["tenant_id"], row["id"])
    return {
        **_plain(
            {
                k: row[k]
                for k in (
                    "id",
                    "label",
                    "url",
                    "audience",
                    "customer_id",
                    "topics",
                    "principal_user_id",
                    "expires_at",
                    "purpose",
                    "created_at",
                    "auto_start_at",
                    "last_scanned_at",
                    "dispatch_error",
                )
            }
        ),
        "control": _plain(state) if state else None,
        "status": state["status"] if state else "paused",
        "version": state["version"] if state else 0,
        "expired": row["expires_at"] <= datetime.now(UTC),
    }


def record(
    c: Any,
    context: AuthContext,
    project: UUID,
    identity: UUID,
    action: str,
    detail: dict[str, Any] | None = None,
    *,
    automated: bool = False,
) -> None:
    EventAuditWriter(
        c, tenant_id=context.tenant.id, project_id=project, actor_user_id=context.user.id
    ).record(
        EventDraft(
            event_id=f"webhook:{identity}:{action}",
            event_type="WEBHOOK_RECORDED",
            source="webhook_service",
            entity_id=identity,
            payload={"record_id": str(identity), "action": action},
        ),
        AuditDraft(
            action=f"webhook.{action}",
            after_snapshot={"record_id": str(identity), **(detail or {})},
        ),
    )


def preview(c: Any, context: AuthContext, row: Any, source_event: int) -> dict[str, Any]:
    state = control(c, context.tenant.id, row["id"])
    if row["expires_at"] <= datetime.now(UTC) or (state and state["status"] == "revoked"):
        raise ProductWorkError("端点已过期或撤销")
    basis = notification(c, context, row, source_event)
    return {
        "endpoint_id": str(row["id"]),
        "url": row["url"],
        "basis": basis,
        "digest": digest({"endpoint": str(row["id"]), "url": row["url"], "basis": basis}),
    }


def insert_delivery(
    c: Any,
    context: AuthContext,
    row: Any,
    basis: dict[str, Any],
    request_id: UUID,
    request_digest: str,
    reason: str,
    *,
    automated: bool = False,
) -> Any:
    t = tables.webhook_deliveries
    existing = (
        c.execute(
            select(t).where(
                t.c.tenant_id == context.tenant.id,
                t.c.endpoint_id == row["id"],
                t.c.source_event_id == basis["source_event_id"],
            )
        )
        .mappings()
        .one_or_none()
    )
    if existing:
        return existing
    identity = uuid4()
    payload = {
        "protocol": PROTOCOL,
        "delivery_id": str(identity),
        "event_id": basis["source_event_reference"],
        "event_type": basis["topic"],
        "source_event_at": basis["source_event_at"],
        "data": basis["data"],
    }
    body_bytes(payload)
    value = (
        c.execute(
            t.insert()
            .values(
                id=identity,
                tenant_id=context.tenant.id,
                project_id=row["project_id"],
                endpoint_id=row["id"],
                source_event_id=basis["source_event_id"],
                topic=basis["topic"],
                payload=payload,
                basis_digest=basis["digest"],
                payload_digest=sha256(body_bytes(payload)).hexdigest(),
                requested_by_user_id=context.user.id,
                request_id=request_id,
                request_digest=request_digest,
                reason=reason,
                status="queued",
                attempt_count=0,
                attempt_limit=8,
                next_attempt_at=datetime.now(UTC),
                created_at=datetime.now(UTC),
            )
            .returning(t)
        )
        .mappings()
        .one()
    )
    record(
        c,
        context,
        row["project_id"],
        identity,
        "queued",
        {"principal_user_id": str(row["principal_user_id"]), "automated": automated},
        automated=automated,
    )
    return value


def readable_delivery(c: Any, context: AuthContext, ep: Any, row: Any) -> dict[str, Any]:
    value = delivery_meta(row)
    try:
        notification(c, context, ep, row["source_event_id"])
    except (ProductWorkError, PermissionError):
        value["payload"] = None
        value["payload_unavailable"] = True
    return value


def close_attempt(c: Any, row: Any, reason: str) -> None:
    if row["lease_id"]:
        a = tables.webhook_attempts
        c.execute(
            update(a)
            .where(a.c.id == row["lease_id"], a.c.outcome == "started")
            .values(outcome="unknown", error_code=reason, finished_at=datetime.now(UTC))
        )


def delivery_meta(row: Any) -> dict[str, Any]:
    return _plain(
        {
            k: row[k]
            for k in (
                "id",
                "endpoint_id",
                "source_event_id",
                "topic",
                "status",
                "payload",
                "payload_digest",
                "attempt_count",
                "attempt_limit",
                "next_attempt_at",
                "last_error",
                "reason",
                "created_at",
            )
        }
    )


class ProjectWebhookService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def options(self, context: AuthContext, project: UUID) -> dict[str, Any]:
        from app.domain.customer_report_packages import CustomerReportService, PackageOptions

        with self.engine.connect() as c:
            authorize(c, context, project, Action.INTEGRATION_PROJECT_MANAGE)
        settings = get_settings()
        return {
            "delivery_enabled": settings.webhook_delivery_enabled,
            "encryption_configured": settings.webhook_encryption_key is not None,
            "protocol": PROTOCOL,
            "customers": CustomerReportService(self.engine).options(
                context, project, PackageOptions()
            )["customers"],
        }

    def create(
        self, context: AuthContext, project: UUID, command: EndpointCreate
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            authorize(c, context, project, Action.INTEGRATION_PROJECT_MANAGE)
            t = tables.webhook_endpoints
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
                    raise ProductWorkError("原请求不能改变端点")
                return {"endpoint": endpoint_meta(c, old), "signing_key": None}
            now = datetime.now(UTC)
            if not now < command.expires_at <= now + timedelta(days=365):
                raise ProductWorkError("端点有效期须在未来365天内")
            if command.customer_id:
                customer(c, context, project, command.customer_id)
            url = destination(command.url)
            identity, secret = uuid4(), secrets.token_bytes(32)
            nonce, envelope = encrypt_key(context.tenant.id, project, identity, secret)
            row = (
                c.execute(
                    t.insert()
                    .values(
                        id=identity,
                        tenant_id=context.tenant.id,
                        project_id=project,
                        label=command.label,
                        url=url,
                        audience=command.audience,
                        customer_id=command.customer_id,
                        topics=list(command.topics),
                        expires_at=command.expires_at,
                        purpose=command.purpose,
                        principal_user_id=context.user.id,
                        principal_auth_version=context.user.auth_version,
                        key_nonce=nonce,
                        key_envelope=envelope,
                        request_id=command.request_id,
                        request_digest=signature,
                        created_at=now,
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            record(c, context, project, identity, "endpoint_created")
            return {
                "endpoint": endpoint_meta(c, row),
                "signing_key": base64.urlsafe_b64encode(secret).decode(),
            }

    def set_control(
        self, context: AuthContext, project: UUID, command: EndpointControl
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            row = endpoint(c, context, project, command.endpoint_id, lock=True)
            t = tables.webhook_controls
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
                    raise ProductWorkError("原请求不能改变端点状态")
                return _plain(old)
            latest = control(c, context.tenant.id, row["id"])
            version = latest["version"] if latest else 0
            if command.expected_version != version or (latest and latest["status"] == "revoked"):
                raise ProductWorkError("端点已有新状态或已终止，请刷新")
            if command.status == "active":
                authorize(c, context, project, Action.INTEGRATION_PROJECT_SEND)
                owner = principal(self.engine, row)
                authorize(c, owner, project, Action.INTEGRATION_PROJECT_SEND)
                if row["expires_at"] <= datetime.now(UTC):
                    raise ProductWorkError("端点已到期")
                from app.integrations.webhook_protocol import decrypt_key

                decrypt_key(row)
                if row["auto_start_at"] is None:
                    c.execute(
                        update(tables.webhook_endpoints)
                        .where(tables.webhook_endpoints.c.id == row["id"])
                        .values(auto_start_at=datetime.now(UTC))
                    )
            identity = uuid4()
            saved = (
                c.execute(
                    t.insert()
                    .values(
                        id=identity,
                        tenant_id=context.tenant.id,
                        project_id=project,
                        endpoint_id=row["id"],
                        version=version + 1,
                        status=command.status,
                        receiver_contract_confirmed=command.receiver_contract_confirmed,
                        delivery_authorized=command.delivery_authorized,
                        reason=command.reason,
                        actor_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=signature,
                        created_at=datetime.now(UTC),
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            if command.status == "revoked":
                q = tables.webhook_deliveries
                for pending in (
                    c.execute(
                        select(q).where(q.c.endpoint_id == row["id"], q.c.status == "sending")
                    )
                    .mappings()
                    .all()
                ):
                    close_attempt(c, pending, "revoked_result_unknown")
                c.execute(
                    update(q)
                    .where(
                        q.c.endpoint_id == row["id"],
                        q.c.status.in_(["queued", "retry_wait", "sending"]),
                    )
                    .values(
                        status="cancelled",
                        last_error="endpoint_revoked",
                        lease_id=None,
                        lease_until=None,
                    )
                )
            record(c, context, project, identity, command.status)
            return _plain(saved)

    def history(
        self, context: AuthContext, project: UUID, query: EndpointHistory
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            authorize(c, context, project, Action.INTEGRATION_PROJECT_MANAGE)
            t = tables.webhook_endpoints
            q = select(t).where(t.c.tenant_id == context.tenant.id, t.c.project_id == project)
            if query.before_id:
                q = q.where(t.c.id < query.before_id)
            rows = c.execute(q.order_by(t.c.id.desc()).limit(21)).mappings().all()
            return {
                "items": [endpoint_meta(c, v) for v in rows[:20]],
                "next_before_id": str(rows[19]["id"]) if len(rows) > 20 else None,
            }

    def sources(self, context: AuthContext, project: UUID, query: SourceOptions) -> dict[str, Any]:
        with self.engine.connect() as c:
            row = endpoint(c, context, project, query.endpoint_id)
            t = tables.events
            q = select(t.c.id, t.c.event_type, t.c.timestamp).where(
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == project,
                t.c.event_type.in_(SOURCE_EVENTS),
            )
            if query.before_event_id:
                q = q.where(t.c.id < query.before_event_id)
            candidates = c.execute(q.order_by(t.c.id.desc()).limit(51)).mappings().all()
            values = []
            for candidate in candidates[:50]:
                try:
                    basis = notification(c, context, row, candidate["id"])
                except (ProductWorkError, PermissionError):
                    continue
                values.append({**_plain(candidate), "topic": basis["topic"]})
            return {
                "items": values,
                "next_before_event_id": candidates[49]["id"] if len(candidates) > 50 else None,
            }

    def preview(self, context: AuthContext, project: UUID, query: NoticePreview) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            return preview(
                c, context, endpoint(c, context, project, query.endpoint_id), query.source_event_id
            )

    def enqueue(self, context: AuthContext, project: UUID, command: NoticeSave) -> dict[str, Any]:
        with self.engine.begin() as c:
            row = endpoint(c, context, project, command.endpoint_id, lock=True)
            authorize(c, context, project, Action.INTEGRATION_PROJECT_SEND)
            signature = digest(
                {"project": str(project), "command": command.model_dump(mode="json")}
            )
            t = tables.webhook_deliveries
            old = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.requested_by_user_id == context.user.id,
                        t.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if old:
                if old["request_digest"] != signature:
                    raise ProductWorkError("原请求不能改变通知")
                return readable_delivery(c, context, row, old)
            prepared = preview(c, context, row, command.source_event_id)
            if prepared["digest"] != command.expected_digest:
                raise ProductWorkError("通知范围或原来源变化，请重新预览")
            return readable_delivery(
                c,
                context,
                row,
                insert_delivery(
                    c,
                    context,
                    row,
                    prepared["basis"],
                    command.request_id,
                    signature,
                    command.reason,
                ),
            )

    def deliveries(
        self, context: AuthContext, project: UUID, query: DeliveryHistory
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            ep = endpoint(c, context, project, query.endpoint_id)
            t = tables.webhook_deliveries
            q = select(t).where(
                t.c.tenant_id == context.tenant.id, t.c.endpoint_id == query.endpoint_id
            )
            if query.before_id:
                q = q.where(t.c.id < query.before_id)
            rows = c.execute(q.order_by(t.c.id.desc()).limit(21)).mappings().all()
            a = tables.webhook_attempts
            actions = tables.webhook_delivery_actions
            return {
                "items": [
                    {
                        **readable_delivery(c, context, ep, v),
                        "actions": [
                            _plain(r)
                            for r in c.execute(
                                select(actions)
                                .where(actions.c.delivery_id == v["id"])
                                .order_by(actions.c.created_at)
                            )
                            .mappings()
                            .all()
                        ],
                        "attempts": [
                            _plain(r)
                            for r in c.execute(
                                select(a)
                                .where(
                                    a.c.tenant_id == context.tenant.id, a.c.delivery_id == v["id"]
                                )
                                .order_by(a.c.number)
                            )
                            .mappings()
                            .all()
                        ],
                    }
                    for v in rows[:20]
                ],
                "next_before_id": str(rows[19]["id"]) if len(rows) > 20 else None,
            }

    def delivery_action(
        self, context: AuthContext, project: UUID, command: DeliveryAction
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            t = tables.webhook_deliveries
            original = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.project_id == project,
                        t.c.id == command.delivery_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if original is None:
                raise ProductWorkError("原通知不存在")
            ep = endpoint(c, context, project, original["endpoint_id"], lock=True)
            row = (
                c.execute(select(t).where(t.c.id == original["id"]).with_for_update())
                .mappings()
                .one()
            )
            a = tables.webhook_delivery_actions
            sig = digest({"project": str(project), "command": command.model_dump(mode="json")})
            old = (
                c.execute(
                    select(a).where(
                        a.c.tenant_id == context.tenant.id,
                        a.c.actor_user_id == context.user.id,
                        a.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if old:
                if old["request_digest"] != sig:
                    raise ProductWorkError("原请求不能改变重试或取消")
                return _plain(old)
            if row["status"] == "delivered" or (
                row["status"] == "sending" and row["lease_until"] > datetime.now(UTC)
            ):
                raise ProductWorkError("通知已接收或正在投递，请刷新回执")
            values: dict[str, Any] = {"lease_id": None, "lease_until": None}
            if command.action == "retry":
                authorize(c, context, project, Action.INTEGRATION_PROJECT_SEND)
                current = preview(c, context, ep, row["source_event_id"])
                if current["basis"]["digest"] != row["basis_digest"]:
                    raise ProductWorkError("原通知依据已变化，不能用重试改写原载荷")
                if row["attempt_count"] >= 1000:
                    raise ProductWorkError("已达到该通知的保留重试上限")
                values.update(
                    status="queued",
                    attempt_limit=min(1000, row["attempt_count"] + 8),
                    next_attempt_at=datetime.now(UTC),
                    last_error=None,
                )
            else:
                values.update(status="cancelled", last_error="cancelled_by_user")
            close_attempt(c, row, "manual_action_result_unknown")
            c.execute(update(t).where(t.c.id == row["id"]).values(**values))
            identity = uuid4()
            saved = (
                c.execute(
                    a.insert()
                    .values(
                        id=identity,
                        tenant_id=context.tenant.id,
                        project_id=project,
                        delivery_id=row["id"],
                        action=command.action,
                        reason=command.reason,
                        actor_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=sig,
                        created_at=datetime.now(UTC),
                    )
                    .returning(a)
                )
                .mappings()
                .one()
            )
            record(c, context, project, identity, command.action)
            return _plain(saved)

    def controls(
        self, context: AuthContext, project: UUID, query: ControlHistory
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            endpoint(c, context, project, query.endpoint_id)
            t = tables.webhook_controls
            q = select(t).where(
                t.c.tenant_id == context.tenant.id, t.c.endpoint_id == query.endpoint_id
            )
            if query.before_version:
                q = q.where(t.c.version < query.before_version)
            rows = c.execute(q.order_by(t.c.version.desc()).limit(21)).mappings().all()
            return {
                "items": [_plain(v) for v in rows[:20]],
                "next_before_version": rows[19]["version"] if len(rows) > 20 else None,
            }

    def scans(self, context: AuthContext, project: UUID, query: ScanHistory) -> dict[str, Any]:
        with self.engine.connect() as c:
            endpoint(c, context, project, query.endpoint_id)
            t = tables.webhook_scans
            q = select(t).where(
                t.c.tenant_id == context.tenant.id, t.c.endpoint_id == query.endpoint_id
            )
            if query.before_event_id:
                q = q.where(t.c.source_event_id < query.before_event_id)
            rows = c.execute(q.order_by(t.c.source_event_id.desc()).limit(51)).mappings().all()
            return {
                "items": [_plain(v) for v in rows[:50]],
                "next_before_event_id": rows[49]["source_event_id"] if len(rows) > 50 else None,
            }
