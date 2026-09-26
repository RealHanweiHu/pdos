"""User-facing control of application runs, without a model gateway dependency."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine, func, select, text

from app.auth.errors import ObjectPermissionDeniedError
from app.auth.project_access import ProjectAccessService, SqlProjectAccessRepository
from app.auth.repository import AuthContext, AuthRepository
from app.auth.roles import Action
from app.db.schema import tables


class ApplicationCancelReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)
    run_id: UUID
    cancellation_id: UUID | None
    lineage_id: UUID | None
    cancelled_run_ids: list[UUID]
    changed: bool


def cancel_application_run(
    engine: Engine, *, context: AuthContext, run_id: UUID
) -> ApplicationCancelReceipt:
    with engine.connect() as c:
        row = c.execute(
            select(
                tables.agent_runs.c.project_id,
                tables.agent_runs.c.scope_kind,
                tables.agent_runs.c.market_space_id,
            )
            .outerjoin(
                tables.application_authorizations,
                (tables.application_authorizations.c.tenant_id == tables.agent_runs.c.tenant_id)
                & (tables.application_authorizations.c.run_id == tables.agent_runs.c.id),
            )
            .where(
                tables.agent_runs.c.tenant_id == context.tenant.id,
                func.coalesce(
                    tables.agent_runs.c.requested_by_user_id,
                    tables.application_authorizations.c.principal_id,
                )
                == context.user.id,
                tables.agent_runs.c.id == run_id,
            )
        ).one_or_none()
    if row is None:
        raise ObjectPermissionDeniedError
    current = AuthRepository(engine).find_user_context(context.user.id)
    if (
        current is None
        or current.tenant.id != context.tenant.id
        or current.tenant.status != "active"
        or not current.user.is_active
        or current.user.auth_version != context.user.auth_version
    ):
        raise ObjectPermissionDeniedError
    if row.scope_kind == "market_space":
        from app.ai.product_matrix_runs import run_row

        with engine.connect() as c:
            run_row(c, current, row.market_space_id, run_id)
    elif row.scope_kind == "tenant":
        from app.domain.process_templates import authorize

        with engine.connect() as c:
            authorize(c, current)
    else:
        ProjectAccessService(SqlProjectAccessRepository(engine)).authorize(
            context=current, project_id=row.project_id, action=Action.PROJECT_VIEW
        )
    with engine.begin() as c:
        body = c.execute(
            text("SELECT cehub_ai.cancel_application_request(:tenant,:run,:actor)"),
            {"tenant": context.tenant.id, "run": run_id, "actor": context.user.id},
        ).scalar_one()
    return ApplicationCancelReceipt.model_validate(body)
