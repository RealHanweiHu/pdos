"""Use a checked plan task as native provenance for its execution facts."""

from uuid import UUID

from pdos_next.core.service import source_for
from pdos_next.domain.categories.preproject.baseline import validate_sources
from pdos_next.domain.categories.preproject.schemas import Reference
from pdos_next.domain.projects.models import PlanProposal, PlanRevision, ProjectTask

from .rules import require


def resolve(s, ctx, pid, project_id, task):
    row = s.get(ProjectTask, UUID(str(task["id"])))
    plan = s.get(PlanRevision, row.plan_id) if row else None
    proposal = s.get(PlanProposal, plan.proposal_id) if plan else None
    checked = (proposal.input_snapshot.get("npi") or {}).get("checked") if proposal else None
    require(
        checked
        and row.tenant_id == ctx.tenant_id
        and row.product_id == pid
        and str(row.project_id) == str(project_id)
        and plan.revision == task["revision"]
        and row.forecast.get("role")
        and row.forecast.get("sources"),
        "需要当前项目中通过框架检查的固定计划任务。",
        "SOURCE_UNAVAILABLE",
    )
    return {
        "project_id": str(row.project_id),
        "task": task,
        "plan_id": str(plan.id),
        "key": row.key,
        "framework": checked["framework"],
        "sources": row.forecast["sources"],
    }


def sources_current(s, ctx, pid, basis):
    from pdos_next.domain.categories.products.definitions import definition_view
    from pdos_next.domain.categories.products.models import DefinitionRevision

    # The work receipt retains the checked plan reference. Its SQL guard verifies
    # the immutable plan, including when an assignee cannot read the plan proposal.
    refs, definitions = [], []
    for source in basis["sources"]:
        kind, identity, revision = source["kind"], UUID(source["id"]), source["revision"]
        if kind == "artifact":
            source_for(s, ctx, pid, identity, revision)
        elif kind in {"category_knowledge", "parameter"}:
            refs.append(
                Reference(
                    type="knowledge" if kind == "category_knowledge" else "parameter",
                    id=identity,
                    version=revision,
                )
            )
        elif kind == "definition":
            definition = s.get(DefinitionRevision, identity)
            require(
                definition and definition.product_id == pid and definition.revision == revision,
                "任务引用的固定型号定义不可读。",
                "SOURCE_UNAVAILABLE",
            )
            definitions.append(definition_view(s, ctx, definition))
    validate_sources(s, ctx, None, extra_refs=refs)
    for item in definitions:
        validate_sources(s, ctx, item)
