"""One read snapshot of real waiting facts and the calendars actually available."""

from sqlalchemy import select

from pdos_next.errors import DomainError
from pdos_next.models import Grant, Principal, now
from pdos_next.service import require_access

from . import calendar_owner, owner, rules
from .models import ExternalWaitCurrent, ExternalWaitVersion


def workspace(s, ctx, pid, project_id):
    product = require_access(s, ctx, pid)
    project = owner.project(s, ctx, pid, project_id)
    at = now()
    waits = []
    for pointer in s.scalars(
        select(ExternalWaitCurrent)
        .where(
            ExternalWaitCurrent.tenant_id == ctx.tenant_id,
            ExternalWaitCurrent.category_id == ctx.category_id,
            ExternalWaitCurrent.product_id == pid,
            ExternalWaitCurrent.project_id == project_id,
        )
        .order_by(ExternalWaitCurrent.created_at, ExternalWaitCurrent.id)
    ):
        row = s.get(ExternalWaitVersion, pointer.version_id)
        snapshot = owner.retained(s, ctx, pid, row)
        calendar, label, unavailable = None, None, False
        if snapshot.calendar:
            try:
                owner.sources_current(s, ctx, pid, project_id, row.source_basis)
                resolved = calendar_owner.resolve(s, ctx, pid, project_id, snapshot.calendar)
                calendar = resolved["calendar"]
                label = snapshot.calendar.calendar_key + " · " + snapshot.calendar.calendar_version
            except DomainError as error:
                if error.code not in {
                    "SOURCE_UNAVAILABLE",
                    "SOURCE_STALE",
                    "VERSION_CONFLICT",
                    "FORBIDDEN_SCOPE",
                    "INTEGRATION_REQUIRED",
                }:
                    raise
                unavailable = True
        history = list(
            s.scalars(
                select(ExternalWaitVersion)
                .where(
                    ExternalWaitVersion.tenant_id == ctx.tenant_id,
                    ExternalWaitVersion.product_id == pid,
                    ExternalWaitVersion.wait_id == row.wait_id,
                )
                .order_by(ExternalWaitVersion.revision)
            )
        )
        waits.append(
            {
                **snapshot.model_dump(mode="json"),
                "id": str(row.wait_id),
                "version_id": str(row.id),
                "history": [
                    {
                        "id": str(v.id),
                        "revision": v.revision,
                        "action": v.action,
                        "state": v.state,
                        "actor_id": str(v.actor_id),
                        "created_at": v.created_at.isoformat(),
                        "receipt_id": str(v.receipt_id),
                    }
                    for v in history
                ],
                "clock": rules.clock(
                    snapshot,
                    at=at,
                    calendar=calendar,
                    calendar_label=label,
                    unavailable=unavailable,
                ),
            }
        )
    members = [
        {"id": str(person.id), "name": person.name, "can_write": grant.can_write}
        for person, grant in s.execute(
            select(Principal, Grant)
            .join(
                Grant,
                (Grant.tenant_id == Principal.tenant_id) & (Grant.principal_id == Principal.id),
            )
            .where(
                Principal.tenant_id == ctx.tenant_id,
                Principal.kind == "human",
                Principal.active.is_(True),
                Grant.category_id == ctx.category_id,
                Grant.expires_at.is_(None) | (Grant.expires_at > at),
            )
            .order_by(Principal.name, Principal.id)
        )
    ]
    return {
        "project": {
            "id": str(project.id),
            "revision": project.revision,
            "name": project.name,
            "owner_id": str(project.owner_id),
            "visibility": project.visibility,
        },
        "product_revision": product.revision,
        "members": members,
        "waits": waits,
        "available_calendars": calendar_owner.available(s, ctx, pid, project_id),
        "as_of": at.isoformat(),
    }
