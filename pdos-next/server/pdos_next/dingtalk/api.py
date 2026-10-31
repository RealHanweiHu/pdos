"""Authenticated account/share controls plus signed one-message ingress; no business actions."""

from uuid import UUID

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from pdos_next.database import tenant_session
from pdos_next.errors import DomainError

from . import accounts, admission, settings
from .models import Binding, Delivery
from .runtime import ChannelService, configured
from .schemas import (
    AppSave,
    BindingBegin,
    BindingFinish,
    BindingRevoke,
    ChannelReference,
    ShareConfirm,
    SharePrepare,
)


def register_routes(app, engine, auth_engine, auth_dependency, bootstrap, metadata_engine=None):
    def transaction(ctx, *, read=False):
        if ctx.category_id is not None:
            raise DomainError("FORBIDDEN_SCOPE", "账号绑定须在本人入口办理。", 403)
        return tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            read_snapshot=read,
        )

    def service():
        return ChannelService(engine, metadata_engine or auth_engine)

    @app.get("/v1/personal/dingtalk/settings")
    def current_settings(ctx=auth_dependency):
        with transaction(ctx, read=True) as session:
            return settings.view(session, ctx, getattr(engine, "_pdos_dingtalk", None))

    @app.post("/v1/dingtalk/application")
    @app.put("/v1/dingtalk/application")
    def save(data: AppSave, ctx=auth_dependency):
        with transaction(ctx) as session:
            runtime = configured(engine) if data.active else getattr(engine, "_pdos_dingtalk", None)
            return accounts.save_application(session, ctx, data, runtime)

    @app.get("/v1/personal/dingtalk/bindings")
    def bindings(ctx=auth_dependency):
        with transaction(ctx, read=True) as session:
            accounts.human(session, ctx)
            rows = session.scalars(
                select(Binding)
                .where(Binding.owner_id == ctx.actor_id)
                .order_by(Binding.created_at.desc())
            )
            return {
                "items": [
                    {
                        "binding_id": str(row.id),
                        "application_id": str(row.application_id),
                        "active": row.active,
                        "epoch": row.epoch,
                    }
                    for row in rows
                ]
            }

    @app.post("/v1/personal/dingtalk/bindings/begin")
    def begin(data: BindingBegin, ctx=auth_dependency):
        with transaction(ctx) as session:
            return accounts.begin(session, ctx, data, configured(engine))

    @app.post("/v1/personal/dingtalk/bindings/finish")
    def finish(data: BindingFinish, ctx=auth_dependency):
        return accounts.finish(engine, ctx, data, configured(engine))

    @app.post("/v1/personal/dingtalk/bindings/revoke")
    def revoke(data: BindingRevoke, ctx=auth_dependency):
        with transaction(ctx) as session:
            return accounts.revoke(session, ctx, data)

    @app.post("/v1/dingtalk/applications/{application_id}/events", status_code=202)
    async def incoming(application_id: UUID, request: Request):
        runtime = configured(engine)
        official = getattr(runtime.adapter, "protocol", "") == "dingtalk-internal-http/v1"

        def response(value):
            # HTTP acknowledgement carries no business answer. Every actual reply
            # goes through the journalled P26 delivery path after admission.
            return JSONResponse({"msgtype": "empty"}, status_code=200) if official else value

        # No raw callback payload/credentials in event/Temporal/model context logs.
        body = await request.body()
        if len(body) > 32768:
            raise DomainError("VALIDATION_FAILED", "入站消息过长。", 422)
        service_ctx = admission.locate(auth_engine, application_id)
        event = admission.verify(
            engine,
            service_ctx,
            application_id,
            runtime,
            body,
            request.headers.get("sign" if official else "x-channel-signature", ""),
            request.headers.get("timestamp" if official else "x-channel-timestamp", ""),
        )
        if event.conversation_kind == "group" and not event.mentioned:
            return response({"accepted": False, "ignored": True})
        owner = admission.resolve_sender(engine, service_ctx, event)
        if owner is None:
            return response({
                "accepted": False,
                "binding_required": True,
                "message": "请先在 PDOS 本人入口绑定账号；未查询任何资料。",
            })
        with transaction(owner) as session:
            row = admission.admit(session, owner, event, bootstrap)
            return response(
                {"accepted": True, "run_id": str(row.run_id), "message_id": str(row.id)}
            )

    @app.post("/v1/personal/dingtalk/share/preview")
    def preview(data: SharePrepare, ctx=auth_dependency):
        with transaction(ctx, read=True) as session:
            return service().preview_share(session, ctx, data)

    @app.post("/v1/personal/dingtalk/share/confirm", status_code=202)
    def confirm(data: ShareConfirm, ctx=auth_dependency):
        with transaction(ctx) as session:
            return service().confirm_share(session, ctx, data)

    @app.get("/v1/personal/dingtalk/deliveries")
    def receipts(ctx=auth_dependency):
        with transaction(ctx, read=True) as session:
            accounts.human(session, ctx)
            rows = session.scalars(
                select(Delivery)
                .where(Delivery.owner_id == ctx.actor_id)
                .order_by(Delivery.created_at.desc())
                .limit(100)
            )
            return {
                "items": [
                    {
                        **ChannelService.status(row),
                        "p26": row.p26,
                        "provider_receipt": row.provider_receipt,
                    }
                    for row in rows
                ]
            }

    @app.post("/v1/personal/dingtalk/deliveries/{delivery_id}/reconcile")
    def reconcile(delivery_id: UUID, ctx=auth_dependency):
        with transaction(ctx, read=True) as session:
            accounts.human(session, ctx)
            row = session.get(Delivery, delivery_id)
            if not row or row.owner_id != ctx.actor_id:
                raise DomainError("FORBIDDEN_SCOPE", "此投递不属于本人。", 403)
            ref = ChannelReference(tenant_id=ctx.tenant_id, message_id=row.message_id)
        # lookup only; this endpoint never invokes send, create_run or a model.
        return service().reconcile(ref, delivery_id)
