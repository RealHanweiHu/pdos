"""A subscriber chooses only their verified binding, in the existing rule T1."""

from sqlalchemy import select

from pdos_next.dingtalk.accounts import human
from pdos_next.dingtalk.models import Application, Binding
from pdos_next.errors import DomainError
from pdos_next.models import Principal


def selected(session, ctx, binding_id):
    human(session, ctx)
    binding = session.scalar(
        select(Binding).where(
            Binding.tenant_id == ctx.tenant_id,
            Binding.id == binding_id,
            Binding.owner_id == ctx.requester_id,
        )
    )
    app = session.get(Application, binding.application_id) if binding else None
    service = session.get(Principal, app.service_principal_id) if app else None
    if (
        not binding
        or not binding.active
        or not app
        or not app.active
        or not service
        or not service.active
        or service.kind != "agent"
    ):
        raise DomainError("SOURCE_UNAVAILABLE", "请先在本人钉钉设置完成当前账号绑定。", 409)
    return app, binding


def options(session, ctx, *, configured):
    human(session, ctx)
    rows = session.scalars(
        select(Binding).where(
            Binding.tenant_id == ctx.tenant_id,
            Binding.owner_id == ctx.requester_id,
            Binding.active.is_(True),
        )
    ).all()
    choices = []
    for row in rows:
        try:
            app, binding = selected(session, ctx, row.id)
        except DomainError:
            continue
        choices.append(
            {
                "binding_id": str(binding.id),
                "epoch": binding.epoch,
                "application_id": str(app.id),
                "application_revision": app.revision,
            }
        )
    return {
        "version": "personal-summary-channels/v1",
        "principal_id": str(ctx.requester_id),
        "configured": configured,
        "bindings": choices,
    }


def register_routes(app, engine, auth_dependency):
    from uuid import UUID

    from pdos_next.database import tenant_session
    from pdos_next.dingtalk.summary_delivery import SummaryDeliveryService
    from pdos_next.dingtalk.summary_models import SummaryDelivery

    def reading(ctx):
        return tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            read_snapshot=True,
        )

    @app.get("/v1/personal/inbox/summary-channels")
    def channels(ctx=auth_dependency):
        with reading(ctx) as session:
            return options(
                session, ctx, configured=getattr(engine, "_pdos_dingtalk", None) is not None
            )

    @app.get("/v1/personal/inbox/summary-deliveries")
    def receipts(ctx=auth_dependency):
        with reading(ctx) as session:
            human(session, ctx)
            rows = session.scalars(
                select(SummaryDelivery)
                .where(
                    SummaryDelivery.owner_id == ctx.requester_id,
                )
                .order_by(SummaryDelivery.created_at.desc(), SummaryDelivery.id.desc())
                .limit(100)
            )
            return {
                "principal_id": str(ctx.requester_id),
                "items": [
                    {
                        **SummaryDeliveryService.status(row),
                        "p26": row.p26,
                        "provider_receipt": row.provider_receipt,
                    }
                    for row in rows
                ],
            }

    @app.post("/v1/personal/inbox/summary-deliveries/{delivery_id}/reconcile")
    def reconcile(delivery_id: UUID, ctx=auth_dependency):
        with reading(ctx) as session:
            human(session, ctx)
            row = session.get(SummaryDelivery, delivery_id)
            if not row or row.owner_id != ctx.requester_id:
                raise DomainError("FORBIDDEN_SCOPE", "此摘要投递不属于本人。", 403)
            reference = {"tenant_id": str(ctx.tenant_id), "run_id": str(row.run_id)}
        service = SummaryDeliveryService(engine, engine)
        metadata = service.reference(reference, owner=ctx.requester_id)
        return service.reconcile(metadata, delivery_id)
