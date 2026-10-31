"""Admin-entered credentials go straight to KMS; only public metadata is persisted here."""

import fcntl
import hashlib
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, SecretStr, field_validator

from pdos_next.clock import now
from pdos_next.errors import DomainError
from pdos_next.model_configuration.host import ManagedConnection, Pricing, SecretSlot, TenantRuntime
from pdos_next.schemas.model_configuration import ModelMetadata
from pdos_next.schemas.model_configuration.dto import ClosedDTO


class AddConnection(ClosedDTO):
    request_id: UUID = Field(strict=False)
    name: str = Field(min_length=1, max_length=120)
    metadata: ModelMetadata
    api_key: SecretStr = Field(min_length=1, max_length=8192, exclude=True, repr=False)
    pricing: Pricing | None = None

    @field_validator("pricing", mode="before")
    @classmethod
    def json_pricing(cls, value):
        # Decimal/date values use the same strict JSON contract as server-owned price cards.
        return Pricing.model_validate_json(json.dumps(value)) if isinstance(value, dict) else value

    @field_validator("api_key")
    @classmethod
    def bearer_key(cls, value):
        key = value.get_secret_value().strip()
        if not key or any(not 33 <= ord(char) <= 126 for char in key):
            raise ValueError("A valid API key is required")
        return SecretStr(key)


def public_connection(row):
    return {"id": str(row.id), "name": row.name,
        "metadata": row.metadata.model_dump(mode="json"),
        "credential_display": "已保存 ••••", "provider": row.provider,
        "pricing_configured": row.pricing is not None}


def readings(host, tenant_id):
    config = host.configuration()
    result = [public_connection(row) for row in config.connections if row.tenant_id == tenant_id]
    for row in config.models:
        if row.tenant_id == tenant_id:
            metadata = ModelMetadata(protocol=row.protocol, base_url=row.base_url,
                model=row.model, model_version=row.model_version,
                context_window_tokens=row.context_window_tokens)
            result.append({"id": None, "name": row.model,
                "metadata": metadata.model_dump(mode="json"), "provider": row.provider,
                "credential_display": "服务器已绑定 ••••", "pricing_configured": True})
    return {"connections": result}


def add(host: TenantRuntime, tenant_id: UUID, actor_id: UUID, data: AddConnection):
    if data.metadata.connection_id is not None:
        raise DomainError("VALIDATION_FAILED", "添加服务商须使用新的连接配置。", 422)
    identity = uuid5(NAMESPACE_URL, f"pdos-next:connection:{tenant_id}:{data.request_id}")
    metadata = data.metadata.model_copy(update={"connection_id": identity})
    # This digest stays in private server metadata; neither the key nor its hash is returned.
    value = {**data.model_dump(mode="json"), "tenant": str(tenant_id),
        "actor": str(actor_id), "key": data.api_key.get_secret_value()}
    if data.metadata.context_window_tokens is None:
        value["metadata"].pop("context_window_tokens")
    fingerprint = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
    lock_path = Path(str(host.path) + ".connections.lock")
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            config = host.configuration()
            existing = next((row for row in config.connections
                if row.tenant_id == tenant_id and row.id == identity), None)
            if existing is not None:
                if existing.request_digest != fingerprint:
                    raise DomainError("DUPLICATE_INTENT_CONFLICT", "原保存请求内容已变化。", 409)
                return public_connection(existing)
            if sum(row.tenant_id == tenant_id for row in config.connections) >= 100:
                raise DomainError("VALIDATION_FAILED", "当前租户最多保存 100 个模型连接。", 422)
            kms = host.kms(config)
            if not callable(getattr(kms, "create", None)):
                raise DomainError("SOURCE_UNAVAILABLE", "服务器尚未接通安全凭据写入。")
            name = f"pdos-next-ui-{tenant_id.hex}-{identity.hex}"
            arn = kms.create(name, str(identity), data.api_key)
            provider = urlsplit(metadata.base_url).hostname
            if provider == "::1":
                provider = "localhost-ipv6"
            registered = next((row for row in config.models if row.tenant_id == tenant_id
                and row.protocol == metadata.protocol
                and row.base_url.rstrip("/") == metadata.base_url.rstrip("/")), None)
            pricing = data.pricing
            if registered is not None:
                provider = registered.provider
                if (registered.model, registered.model_version) == (
                    metadata.model, metadata.model_version
                ) and pricing is None:
                    pricing = registered.pricing
            connection = ManagedConnection(id=identity, tenant_id=tenant_id,
                name=data.name.strip() or metadata.model, metadata=metadata, provider=provider,
                secret=SecretSlot(tenant_id=tenant_id, protocol=metadata.protocol,
                    reference=identity, secret_arn=arn), pricing=pricing,
                request_digest=fingerprint, created_by=actor_id, created_at=now())
            updated = config.model_copy(update={"connections": [*config.connections, connection]})
            content = updated.model_dump_json(indent=2) + "\n"
            if len(content.encode()) > 2_097_152:
                raise DomainError("SOURCE_UNAVAILABLE", "配置容量不足，请保留原保存请求。", 503)
            temporary = None
            try:
                descriptor, temporary = tempfile.mkstemp(prefix=".model-connections-",
                    dir=host.path.parent)
                with os.fdopen(descriptor, "w") as output:
                    os.fchmod(output.fileno(), 0o600)
                    output.write(content)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, host.path)
            finally:
                if temporary is not None:
                    Path(temporary).unlink(missing_ok=True)
            return public_connection(connection)
    except DomainError:
        raise
    except Exception:
        raise DomainError(
            "SOURCE_UNAVAILABLE", "安全保存尚未确认，请保留原请求核对。", 503) from None


def authorize(session, ctx, host):
    from pdos_next.model_configuration.commands import CurrentAdministrator
    from pdos_next.model_configuration.ports import ManagementContext
    from pdos_next.service import require_access

    require_access(session, ctx, None, write=True)
    if not CurrentAdministrator(session, ctx).is_current_human_admin(
        ManagementContext(ctx.tenant_id, ctx.actor_id)
    ):
        raise DomainError("FORBIDDEN_SCOPE", "仅当前授权管理员可以管理模型服务商。", 403)
    if not isinstance(host, TenantRuntime):
        raise DomainError("SOURCE_UNAVAILABLE", "服务器尚未配置 KMS 或本机安全凭据存储。")


def register_routes(app, engine, auth_dependency, bootstrap):
    from pdos_next.database import tenant_session
    from pdos_next.service import Context

    @app.get("/v1/categories/{category_id}/model-connections")
    def model_connections(ctx: Context = auth_dependency):
        with tenant_session(engine, ctx.tenant_id, actor_id=ctx.actor_id,
            requester_id=ctx.requester_id, category_id=ctx.category_id) as session:
            host = bootstrap.ports.secrets
            authorize(session, ctx, host)
            return readings(host, ctx.tenant_id)

    @app.post("/v1/categories/{category_id}/model-connections")
    def add_model_connection(data: AddConnection, ctx: Context = auth_dependency):
        with tenant_session(engine, ctx.tenant_id, actor_id=ctx.actor_id,
            requester_id=ctx.requester_id, category_id=ctx.category_id) as session:
            host = bootstrap.ports.secrets
            authorize(session, ctx, host)
            return add(host, ctx.tenant_id, ctx.actor_id, data)
