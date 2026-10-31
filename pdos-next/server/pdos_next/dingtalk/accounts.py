"""Self binding from verified external identity; metadata never grants business READ."""

import secrets
from datetime import timedelta
from uuid import uuid4

from pydantic import SecretStr
from sqlalchemy import select, text

from pdos_next.agent_kernel.models import TenantAdministrator
from pdos_next.clock import now
from pdos_next.database import require_context, tenant_session
from pdos_next.errors import DomainError
from pdos_next.models import Principal
from pdos_next.service import digest

from .models import Application, Binding, BindingNonce
from .ports import ExternalIdentity


def human(session, ctx):
    require_context(session, ctx)
    person = session.get(Principal, ctx.actor_id)
    if (
        ctx.actor_id != ctx.requester_id
        or ctx.run_id
        or ctx.agent_run_id
        or not person
        or person.kind != "human"
        or not person.active
    ):
        raise DomainError("FORBIDDEN_SCOPE", "此操作须由已登录的本人办理。", 403)
    return person


def administrator(session, ctx):
    human(session, ctx)
    if not session.scalar(
        select(TenantAdministrator.id).where(
            TenantAdministrator.tenant_id == ctx.tenant_id,
            TenantAdministrator.principal_id == ctx.actor_id,
            TenantAdministrator.active.is_(True),
        )
    ):
        raise DomainError("FORBIDDEN_SCOPE", "当前本人没有租户管理员职责。", 403)


def credential(runtime, app):
    if not app or not app.active:
        raise DomainError("SOURCE_UNAVAILABLE", "钉钉应用尚未启用。")
    if runtime.kms.current_version(app.secret_arn) != app.secret_version:
        raise DomainError("SOURCE_UNAVAILABLE", "钉钉凭据版本已变化，请管理员核对登记。")
    value = runtime.kms.value(app.secret_arn, app.secret_version)
    if not isinstance(value, SecretStr):
        raise DomainError("SOURCE_UNAVAILABLE", "钉钉凭据须由当前安全凭据端口解析。")
    # Recheck after resolution, just like native model configuration binding.
    if runtime.kms.current_version(app.secret_arn) != app.secret_version:
        raise DomainError("SOURCE_UNAVAILABLE", "钉钉凭据已轮换。")
    return value


def save_application(session, ctx, data, runtime):
    administrator(session, ctx)
    from pdos_next.agent_kernel.bootstrap import Bootstrap

    service_id = Bootstrap.writer_for(session, ctx)
    row = session.scalar(
        select(Application).where(Application.tenant_id == ctx.tenant_id).with_for_update()
    )
    if (row.revision if row else 0) != data.expected_revision:
        raise DomainError("VERSION_CONFLICT", "钉钉应用登记已变化。")
    # Check KMS refs without accepting or returning a credential value.
    if data.active and runtime.kms.current_version(data.secret_arn) != data.secret_version:
        raise DomainError("SOURCE_UNAVAILABLE", "凭据引用没有当前登记版本。")
    if row is not None and (row.corp_id, row.client_id) != (data.corp_id, data.client_id):
        if session.scalar(
            select(Binding.id)
            .where(Binding.application_id == row.id, Binding.active.is_(True))
            .limit(1)
        ):
            raise DomainError("VERSION_CONFLICT", "更换企业身份前请先撤销现有账号绑定。")
    if row is None:
        row = Application(
            id=uuid4(), tenant_id=ctx.tenant_id, revision=0, service_principal_id=service_id
        )
        session.add(row)
    for name, value in data.model_dump(exclude={"expected_revision"}).items():
        setattr(row, name, value)
    row.revision += 1
    row.administrator_id = ctx.actor_id
    session.flush()
    return {"application_id": str(row.id), "revision": row.revision, "active": row.active}


def begin(session, ctx, data, runtime):
    human(session, ctx)
    app = session.get(Application, data.application_id)
    credential(runtime, app)
    state = secrets.token_urlsafe(32)
    nonce = BindingNonce(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        application_id=app.id,
        owner_id=ctx.actor_id,
        app_revision=app.revision,
        state_sha256=digest(state),
        expires_at=now() + timedelta(minutes=5),
    )
    session.add(nonce)
    session.flush()
    return {
        "authorization_url": runtime.adapter.authorization_url(app, state),
        "expires_at": nonce.expires_at.isoformat(),
    }


def consume(session, ctx, data):
    """Commit this consumed nonce BEFORE calling the external identity adapter."""
    human(session, ctx)
    nonce = session.scalar(
        select(BindingNonce)
        .where(
            BindingNonce.application_id == data.application_id,
            BindingNonce.owner_id == ctx.actor_id,
            BindingNonce.state_sha256 == digest(data.state.get_secret_value()),
        )
        .with_for_update()
    )
    app = session.get(Application, data.application_id)
    if (
        not nonce
        or nonce.consumed_at
        or nonce.expires_at <= now()
        or not app
        or not app.active
        or app.revision != nonce.app_revision
    ):
        raise DomainError("FORBIDDEN_SCOPE", "一次性绑定状态已过期、已用或不属于本人。", 403)
    nonce.consumed_at = now()
    session.flush()
    return nonce.id, app


def bind_verified(session, ctx, nonce_id, identity):
    human(session, ctx)
    if not isinstance(identity, ExternalIdentity):
        raise DomainError("FORBIDDEN_SCOPE", "外部账号身份未经已配置适配器验证。", 403)
    nonce = session.scalar(
        select(BindingNonce).where(BindingNonce.id == nonce_id).with_for_update()
    )
    app = session.get(Application, identity.application_id)
    if (
        not nonce
        or nonce.owner_id != ctx.actor_id
        or not nonce.consumed_at
        or nonce.expires_at <= now()
        or not app
        or not app.active
        or nonce.app_revision != app.revision
        or nonce.application_id != app.id
        or identity.corp_id != app.corp_id
        or identity.state_sha256 != nonce.state_sha256
    ):
        raise DomainError("FORBIDDEN_SCOPE", "验证身份与实际一次性绑定请求不一致。", 403)
    # Serialize the two one-to-one keys; DB partial unique indexes remain final guards.
    for key in sorted(
        (
            f"dingtalk-owner:{ctx.tenant_id}:{ctx.actor_id}",
            f"dingtalk-user:{app.id}:{identity.external_user_id}",
        )
    ):
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"), {"key": key}
        )
    if session.scalar(select(Binding.id).where(Binding.verified_nonce_id == nonce.id)):
        raise DomainError("VERSION_CONFLICT", "该次身份验证已经完成绑定。")
    row = Binding(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        application_id=app.id,
        owner_id=ctx.actor_id,
        external_user_id=identity.external_user_id,
        verified_nonce_id=nonce.id,
        active=True,
        epoch=1,
        verified_at=now(),
    )
    session.add(row)
    session.flush()
    return {"binding_id": str(row.id), "epoch": row.epoch, "active": row.active}


def finish(engine, ctx, data, runtime):
    def transaction():
        return tenant_session(
            engine, ctx.tenant_id, actor_id=ctx.actor_id, requester_id=ctx.requester_id
        )

    with transaction() as session:
        nonce_id, app = consume(session, ctx, data)
        # Snapshot only registered adapter metadata; SQL transaction commits before exchange.
        session.expunge(app)
    verified = runtime.adapter.exchange_identity(
        app,
        credential(runtime, app),
        data.auth_code,
        digest(data.state.get_secret_value()),
    )
    with transaction() as session:
        return bind_verified(session, ctx, nonce_id, verified)


def revoke(session, ctx, data):
    human(session, ctx)
    row = session.scalar(select(Binding).where(Binding.id == data.binding_id).with_for_update())
    if not row:
        raise DomainError("FORBIDDEN_SCOPE", "账号绑定不在当前可办理范围。", 403)
    if row.owner_id != ctx.actor_id:
        administrator(session, ctx)
    if not row.active and row.revoke_key == data.request_key:
        return {"binding_id": str(row.id), "epoch": row.epoch, "active": False}
    if not row.active or row.epoch != data.expected_epoch:
        raise DomainError("VERSION_CONFLICT", "绑定状态已变化。")
    row.active, row.epoch = False, row.epoch + 1
    row.revoked_by, row.revoke_key, row.revoke_reason = ctx.actor_id, data.request_key, data.reason
    session.flush()
    # Existing binding/app locks fence sends; dispatcher cancels this binding’s pending metadata.
    return {"binding_id": str(row.id), "epoch": row.epoch, "active": False}
