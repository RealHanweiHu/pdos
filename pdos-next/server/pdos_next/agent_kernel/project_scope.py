"""Explicit page context is checked against ordinary current Project visibility."""

from sqlalchemy import inspect, select

from pdos_next.domain.projects.models import Project
from pdos_next.errors import DomainError
from pdos_next.service import require_access


def require_project(session, ctx, project_id, product_id, *, lock=False):
    if project_id is None:
        return None
    if ctx.category_id is None or product_id is None:
        raise DomainError("FORBIDDEN_SCOPE", "项目运行须绑定实际品类与型号。", 403)
    # Reading project context does not require business write authority.
    require_access(session, ctx, product_id, write=False, lock=lock)
    query = select(Project).where(
        Project.tenant_id == ctx.tenant_id,
        Project.category_id == ctx.category_id,
        Project.product_id == product_id,
        Project.id == project_id,
    )
    row = session.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise DomainError("FORBIDDEN_SCOPE", "运行绑定项目不在当前实际受众内。", 403)
    return row


def require_run_project(session, ctx, run):
    """Metadata readers may intentionally defer every unrelated Run column."""
    state = inspect(run, raiseerr=False)
    if state is not None and "project_id" in state.unloaded:
        from .models import AgentRun

        binding = session.execute(
            select(AgentRun.project_id, AgentRun.product_id).where(
                AgentRun.tenant_id == ctx.tenant_id,
                AgentRun.id == run.id,
                AgentRun.requester_id == ctx.requester_id,
            )
        ).one_or_none()
        if binding is None:
            raise DomainError("FORBIDDEN_SCOPE", "运行绑定项目不在当前实际受众内。", 403)
        project_id, product_id = binding
    else:
        project_id = getattr(run, "project_id", None)
        product_id = run.product_id if project_id is not None else None
    return require_project(session, ctx, project_id, product_id)
