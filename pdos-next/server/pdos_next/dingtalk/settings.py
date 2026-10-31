"""Current self/admin metadata under ordinary Human RLS; no KMS/network on GET."""

from sqlalchemy import select

from pdos_next.agent_kernel.models import TenantAdministrator

from .accounts import human
from .models import Application, Binding


def view(session, ctx, runtime=None):
    human(session, ctx)
    admin = bool(
        session.scalar(
            select(TenantAdministrator.id).where(
                TenantAdministrator.tenant_id == ctx.tenant_id,
                TenantAdministrator.principal_id == ctx.actor_id,
                TenantAdministrator.active.is_(True),
            )
        )
    )
    app = session.scalar(select(Application).where(Application.tenant_id == ctx.tenant_id))
    query = select(Binding).where(Binding.tenant_id == ctx.tenant_id)
    if not admin:
        query = query.where(Binding.owner_id == ctx.actor_id)
    rows = list(session.scalars(query.order_by(Binding.created_at.desc(), Binding.id).limit(101)))
    application = None
    if app:
        application = {
            "application_id": str(app.id),
            "revision": app.revision,
            "active": app.active,
            **(
                {
                    "corp_id": app.corp_id,
                    "client_id": app.client_id,
                    "robot_code": app.robot_code,
                    "secret_arn": app.secret_arn,
                    "secret_version": app.secret_version,
                }
                if admin
                else {}
            ),
        }
    return {
        "principal_id": str(ctx.actor_id),
        "can_manage": admin,
        "configured": runtime is not None,
        "application": application,
        "group_citations_available": bool(
            runtime and getattr(runtime.adapter, "group_citations", False)
        ),
        "bindings": [
            {
                "binding_id": str(row.id),
                "application_id": str(row.application_id),
                "owner_id": str(row.owner_id),
                "active": row.active,
                "epoch": row.epoch,
                "verified_at": row.verified_at.isoformat(),
            }
            for row in rows[:100]
        ],
        "has_more_bindings": len(rows) > 100,
    }
