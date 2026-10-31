"""Scoped, read-only comparison of actual stored plan candidates."""

from uuid import UUID

from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.service import Context, require_access

from .models import PlanProposal, PlanRevision
from .resources import analyze, catalog, compare
from .service import _project


def register_routes(app, engine, auth_dependency):
    @app.get(
        "/v1/categories/{category_id}/products/{product_id}/projects/{project_id}/plan-comparison"
    )
    def planning_comparison(
        product_id: UUID,
        project_id: UUID,
        proposal_id: UUID | None = None,
        ctx: Context = auth_dependency,
    ):
        with tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
            read_snapshot=True,
        ) as s:
            require_access(s, ctx, product_id)
            project, _, _ = _project(s, ctx, product_id, project_id)
            current = (
                s.get(PlanRevision, project.current_plan_id) if project.current_plan_id else None
            )
            proposal = (
                s.get(PlanProposal, proposal_id or (current.proposal_id if current else None))
                if proposal_id or current
                else None
            )
            if proposal_id and (
                proposal is None
                or proposal.project_id != project.id
                or proposal.product_id != product_id
                or proposal.tenant_id != ctx.tenant_id
            ):
                raise DomainError("FORBIDDEN_SCOPE", "计划候选不在当前项目范围。", 403)
            from pdos_next.domain.project_governance.service import promise_facts

            from .models import ProjectTask

            promises = promise_facts(s, ctx, product_id, project_id)
            for promise in promises:
                original_task = (
                    s.get(ProjectTask, UUID(promise["plan_task"]["id"]))
                    if promise["plan_task"]
                    else None
                )
                predicted = (
                    next(
                        (
                            t
                            for t in proposal.forecast["tasks"]
                            if original_task and t["key"] == original_task.key
                        ),
                        None,
                    )
                    if proposal
                    else None
                )
                promise["forecast"] = predicted["latest_finish"] if predicted else None
                promise["task_title"] = original_task.title if original_task else "未关联计划任务"
                from .resources import instant

                promise["impact"] = (
                    "unknown"
                    if not promise["forecast"] or not promise["promised_at"]
                    else "later"
                    if instant(promise["forecast"]) > instant(promise["promised_at"])
                    else "within"
                )
            return {
                "commitments": promises,
                "project_id": str(project.id),
                "project_revision": project.revision,
                "catalog": catalog(s, ctx, product_id, project_id),
                "current_plan": {
                    "id": str(current.id),
                    "revision": current.revision,
                    "forecast": current.forecast,
                }
                if current
                else None,
                "proposal_id": str(proposal.id) if proposal else None,
                "comparison": compare(current.forecast if current else None, proposal.forecast)
                if proposal
                else [],
                "resources": analyze(
                    s, ctx, product_id, project, proposal.forecast, proposal.resource_demands
                )
                if proposal
                else None,
            }
