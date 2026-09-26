"""Route project event stops through the existing user-visible control surface."""

from uuid import UUID

from sqlalchemy import Engine, select, text
from sqlalchemy.exc import DBAPIError

from app.ai.application_control import ApplicationCancelReceipt, cancel_application_run
from app.auth.errors import ObjectPermissionDeniedError
from app.auth.project_access import ProjectAccessService, SqlProjectAccessRepository
from app.auth.repository import AuthContext, AuthRepository
from app.auth.roles import Action
from app.db.schema import tables


def cancel_visible_run(
    engine: Engine, *, context: AuthContext, run_id: UUID
) -> ApplicationCancelReceipt:
    with engine.connect() as c:
        row = (
            c.execute(
                select(tables.agent_runs).where(
                    tables.agent_runs.c.tenant_id == context.tenant.id,
                    tables.agent_runs.c.id == run_id,
                )
            )
            .mappings()
            .one_or_none()
        )
    if row is None:
        raise ObjectPermissionDeniedError
    if (
        row["request_id"] is not None
        or row["requested_by_user_id"] is not None
        or row["subscription_id"] is None
    ):
        return cancel_application_run(engine, context=context, run_id=run_id)
    current = AuthRepository(engine).find_user_context(context.user.id)
    if (
        current is None
        or current.tenant.id != context.tenant.id
        or current.tenant.status != "active"
        or not current.user.is_active
        or current.user.auth_version != context.user.auth_version
    ):
        raise ObjectPermissionDeniedError
    ProjectAccessService(SqlProjectAccessRepository(engine)).authorize(
        context=current, project_id=row["project_id"], action=Action.PROJECT_EDIT
    )
    try:
        with engine.begin() as c:
            body = c.execute(
                text("SELECT cehub_ai.cancel_event_run(:tenant,:run,:actor,:version)"),
                {
                    "tenant": context.tenant.id,
                    "run": run_id,
                    "actor": context.user.id,
                    "version": context.user.auth_version,
                },
            ).scalar_one()
    except DBAPIError as error:
        if getattr(error.orig, "sqlstate", None) == "42501":
            raise ObjectPermissionDeniedError from error
        raise
    return ApplicationCancelReceipt.model_validate(body)


class EventPauseError(ValueError):
    pass


def control_pause(
    engine: Engine, *, context: AuthContext, run_id: UUID, resume: bool
) -> dict[str, object]:
    with engine.connect() as c:
        row = c.execute(
            select(tables.agent_runs.c.project_id).where(
                tables.agent_runs.c.tenant_id == context.tenant.id,
                tables.agent_runs.c.id == run_id,
                tables.agent_runs.c.request_id.is_(None),
                tables.agent_runs.c.requested_by_user_id.is_(None),
                tables.agent_runs.c.subscription_id.is_not(None),
            )
        ).one_or_none()
    current = AuthRepository(engine).find_user_context(context.user.id)
    if (
        row is None
        or current is None
        or current.tenant.id != context.tenant.id
        or current.tenant.status != "active"
        or not current.user.is_active
        or current.user.auth_version != context.user.auth_version
    ):
        raise ObjectPermissionDeniedError
    ProjectAccessService(SqlProjectAccessRepository(engine)).authorize(
        context=current, project_id=row.project_id, action=Action.PROJECT_EDIT
    )
    try:
        with engine.begin() as c:
            body = c.execute(
                text("SELECT cehub_ai.control_event_pause(:t,:r,:a,:v,:resume)"),
                dict(
                    t=context.tenant.id,
                    r=run_id,
                    a=context.user.id,
                    v=context.user.auth_version,
                    resume=resume,
                ),
            ).scalar_one()
    except DBAPIError as error:
        if getattr(error.orig, "sqlstate", None) == "42501":
            raise ObjectPermissionDeniedError from error
        if getattr(error.orig, "sqlstate", None) == "22023":
            code = getattr(
                getattr(error.orig, "diag", None), "message_primary", "EVENT_PAUSE_UNAVAILABLE"
            )
            raise EventPauseError(code) from error
        raise
    return dict(body)
