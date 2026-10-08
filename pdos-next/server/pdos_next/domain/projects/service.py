from uuid import UUID, uuid4

from sqlalchemy import func, select

from pdos_next.domain.planning.calendar import ScheduleError
from pdos_next.domain.planning.scheduling import schedule
from pdos_next.domain.products.definitions import definition_view
from pdos_next.domain.products.models import DefinitionRevision
from pdos_next.errors import DomainError
from pdos_next.models import Principal, Product

from .models import (
    PlanProposal,
    PlanRevision,
    Project,
    ProjectProductLink,
    ProjectTask,
    ProjectWorkPackage,
    TaskDependency,
)
from .schemas import PlanApplyPayload, PlanProposePayload, ProjectCreatePayload


def _definition(s, ctx, product_id, definition_id, revision=None):
    row = s.get(DefinitionRevision, definition_id)
    if (
        not row
        or row.product_id != product_id
        or row.tenant_id != ctx.tenant_id
        or (row.visibility == "private" and row.owner_id != ctx.requester_id)
    ):
        raise DomainError("SOURCE_UNAVAILABLE", "产品定义不在当前授权范围。", 403)
    value = definition_view(s, ctx, row)
    if revision is not None and revision != row.revision:
        raise DomainError("VERSION_CONFLICT", "固定产品定义版本不匹配。")
    return row, value


def _project(s, ctx, product_id, project_id, *, write=False):
    # Source validation later locks the product. Acquire it before the project,
    # matching commands and concurrent Build/supply/professional readers.
    s.scalar(
        select(Product)
        .where(Product.id == product_id, Product.tenant_id == ctx.tenant_id)
        .with_for_update()
    )
    row = s.scalar(
        select(Project)
        .where(
            Project.id == project_id,
            Project.product_id == product_id,
            Project.tenant_id == ctx.tenant_id,
        )
        .with_for_update()
    )
    if (
        not row
        or (row.visibility == "private" and row.owner_id != ctx.requester_id)
        or (write and row.owner_id != ctx.requester_id)
    ):
        raise DomainError("FORBIDDEN_SCOPE", "当前项目不可用，首版计划由项目负责人建立。", 403)
    link = s.scalar(select(ProjectProductLink).where(ProjectProductLink.project_id == row.id))
    _, definition = _definition(s, ctx, product_id, link.definition_id, link.definition_revision)
    return row, link, definition


def _proposal(s, ctx, product_id, payload):
    row = s.get(PlanProposal, payload.proposal_id)
    if (
        not row
        or row.tenant_id != ctx.tenant_id
        or row.product_id != product_id
        or row.project_id != payload.project_id
        or (row.visibility == "private" and row.owner_id != ctx.requester_id)
    ):
        raise DomainError("FORBIDDEN_SCOPE", "计划候选不在当前授权范围。", 403)
    return row


def validate(s, ctx, command, product, payload):
    from pdos_next.service import source_for

    actor = s.get(Principal, ctx.actor_id)
    if ctx.run_id or ctx.actor_id != ctx.requester_id or actor.kind != "human":
        raise DomainError("NAMED_DECISION_REQUIRED", "当前项目与首版计划由本人手工建立。", 403)
    if command.expected_revision != product.revision:
        raise DomainError("VERSION_CONFLICT", "产品范围版本已变化。")
    if isinstance(payload, ProjectCreatePayload):
        _, definition = _definition(
            s, ctx, product.id, payload.definition_id, payload.expected_definition_revision
        )
        if payload.visibility == "product" and definition["visibility"] != "product":
            raise DomainError("FORBIDDEN_SCOPE", "私人定义不能扩大到共享项目。", 403)
    else:
        _, _, definition = _project(s, ctx, product.id, payload.project_id, write=True)
        if isinstance(payload, PlanApplyPayload):
            _proposal(s, ctx, product.id, payload)
        else:
            calculate(payload)
    reads = {str(read.artifact_id): read.expected_revision for read in command.source_read_set}
    for reference in definition["sources"]:
        if reads.get(reference["artifact_id"]) != reference["expected_revision"]:
            raise DomainError("MISSING_REQUIRED_EVIDENCE", "项目和计划需要固定定义的全部来源版本。")
        source = source_for(
            s, ctx, product.id, UUID(reference["artifact_id"]), reference["expected_revision"]
        )
        if (
            isinstance(payload, ProjectCreatePayload)
            and payload.visibility == "product"
            and source.visibility == "private"
        ):
            raise DomainError("FORBIDDEN_SCOPE", "私人来源不能扩大到共享项目。", 403)


def calculate(payload):
    try:
        return schedule(payload.schedule).model_dump(mode="json")
    except ScheduleError as error:
        raise DomainError(error.code, "日历、估计或依赖无法计算，请核对计划输入。", 422) from None


def semantic(payload):
    value = payload.model_dump(mode="json")
    value.pop("confirmation_token", None)
    if "schedule" in value:
        value["schedule"]["tasks"] = sorted(
            value["schedule"]["tasks"], key=lambda task: task["key"]
        )
        for task in value["schedule"]["tasks"]:
            task["depends_on"] = sorted(task["depends_on"])
    return value


def preview_view(s, ctx, command, product, payload):
    validate(s, ctx, command, product, payload)
    if isinstance(payload, ProjectCreatePayload):
        _, definition = _definition(s, ctx, product.id, payload.definition_id)
        return {
            "operation": command.operation,
            "name": payload.name,
            "purpose": payload.purpose,
            "scope": payload.scope,
            "visibility": payload.visibility,
            "definition": {key: definition[key] for key in ("id", "revision", "title", "status")},
            "owner_id": str(ctx.requester_id),
            "effect": "建立真实研发项目并固定产品定义及范围；草稿定义尚未正式发布。",
        }
    project, link, _ = _project(s, ctx, product.id, payload.project_id, write=True)
    proposal = _proposal(s, ctx, product.id, payload)
    return {
        "operation": command.operation,
        "project_id": str(project.id),
        "name": project.name,
        "project_revision": project.revision,
        "current_plan_id": str(project.current_plan_id) if project.current_plan_id else None,
        "proposal_id": str(proposal.id),
        "proposal_revision": proposal.revision,
        "definition_id": str(link.definition_id),
        "input_snapshot": proposal.input_snapshot,
        "reason": proposal.reason,
        "forecast": proposal.forecast,
        "effect": "一次建立工程/NPI工作包、全部任务和依赖；预测不构成批准基线、个人承诺或实绩。",
    }


def apply(s, ctx, command, product, payload):
    if isinstance(payload, ProjectCreatePayload):
        project = Project(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            product_id=product.id,
            owner_id=ctx.requester_id,
            name=payload.name,
            purpose=payload.purpose,
            scope=payload.scope,
            visibility=payload.visibility,
        )
        s.add(project)
        s.flush()
        s.add(
            ProjectProductLink(
                tenant_id=ctx.tenant_id,
                product_id=product.id,
                project_id=project.id,
                definition_id=payload.definition_id,
                definition_revision=payload.expected_definition_revision,
                scope=payload.scope,
            )
        )
        return project, "project", project.visibility
    project, _, _ = _project(s, ctx, product.id, payload.project_id, write=True)
    if project.revision != payload.expected_project_revision:
        raise DomainError("VERSION_CONFLICT", "项目已变化，请重新查看实际范围。")
    if project.current_plan_id:
        raise DomainError("VERSION_CONFLICT", "首版计划已应用；后续修订须走独立变更路径。")
    if isinstance(payload, PlanProposePayload):
        forecast = calculate(payload)
        fixed_input = payload.schedule.model_dump(mode="json")
        calendar = fixed_input["calendar"]
        calendar["timezone_rules_sha256"] = forecast["calendar_ref"]["timezone_rules_sha256"]
        calendar["working_weekdays"] = sorted(calendar["working_weekdays"])
        calendar["holidays"] = sorted(calendar["holidays"])
        calendar["intervals"] = sorted(calendar["intervals"], key=lambda item: item["start_minute"])
        for previous in s.scalars(
            select(PlanProposal).where(PlanProposal.project_id == project.id)
        ):
            old = previous.input_snapshot["calendar"]
            if (old["key"], old["version"]) == (calendar["key"], calendar["version"]):
                if old != calendar:
                    raise DomainError(
                        "VERSION_CONFLICT", "这个日历版本已固定；修改工作日或时段须使用新版本。"
                    )
        revision = (
            s.scalar(
                select(func.max(PlanProposal.revision)).where(
                    PlanProposal.project_id == project.id,
                )
            )
            or 0
        )
        proposal = PlanProposal(
            tenant_id=ctx.tenant_id,
            product_id=product.id,
            project_id=project.id,
            project_revision=project.revision,
            revision=revision + 1,
            owner_id=ctx.requester_id,
            visibility=project.visibility,
            input_snapshot=fixed_input,
            forecast=forecast,
            reason=payload.reason,
        )
        return proposal, "plan_proposal", project.visibility
    proposal = _proposal(s, ctx, product.id, payload)
    if proposal.project_revision != project.revision:
        raise DomainError("VERSION_CONFLICT", "计划候选针对的项目版本已经过期。")
    plan = PlanRevision(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        product_id=product.id,
        project_id=project.id,
        proposal_id=proposal.id,
        owner_id=ctx.requester_id,
        revision=1,
        visibility=project.visibility,
        forecast=proposal.forecast,
    )
    s.add(plan)
    s.flush()
    packages = {
        discipline: ProjectWorkPackage(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            product_id=product.id,
            project_id=project.id,
            plan_id=plan.id,
            discipline=discipline,
        )
        for discipline in ("engineering", "npi")
    }
    s.add_all(packages.values())
    s.flush()
    tasks = {
        item["key"]: ProjectTask(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            product_id=product.id,
            project_id=project.id,
            plan_id=plan.id,
            work_package_id=packages[item["discipline"]].id,
            key=item["key"],
            title=item["title"],
            forecast=item,
        )
        for item in proposal.forecast["tasks"]
    }
    s.add_all(tasks.values())
    s.flush()
    s.add_all(
        [
            TaskDependency(
                tenant_id=ctx.tenant_id,
                product_id=product.id,
                project_id=project.id,
                plan_id=plan.id,
                task_id=tasks[item["key"]].id,
                predecessor_id=tasks[predecessor].id,
            )
            for item in proposal.forecast["tasks"]
            for predecessor in item["depends_on"]
        ]
    )
    project.current_plan_id = plan.id
    project.revision += 1
    plan.action_result = {
        "project_id": str(project.id),
        "proposal_id": str(proposal.id),
        "work_package_ids": [str(package.id) for package in packages.values()],
        "task_ids": [str(task.id) for task in tasks.values()],
    }
    return plan, "plan_revision", project.visibility


def list_projects(s, ctx, product_id):
    from pdos_next.service import require_access

    require_access(s, ctx, product_id)
    rows = s.scalars(
        select(Project)
        .where(
            Project.product_id == product_id,
            (Project.visibility == "product") | (Project.owner_id == ctx.requester_id),
        )
        .order_by(Project.created_at.desc())
        .limit(101)
    ).all()
    items, unavailable = [], 0
    for row in rows[:100]:
        try:
            _, link, definition = _project(s, ctx, product_id, row.id)
        except DomainError as error:
            if error.code != "SOURCE_UNAVAILABLE":
                raise
            unavailable += 1
            continue
        proposals = s.scalars(
            select(PlanProposal)
            .where(
                PlanProposal.project_id == row.id,
                (PlanProposal.visibility == "product")
                | (PlanProposal.owner_id == ctx.requester_id),
            )
            .order_by(PlanProposal.revision.desc())
            .limit(100)
        ).all()
        plan = s.get(PlanRevision, row.current_plan_id) if row.current_plan_id else None
        items.append(
            {
                "id": str(row.id),
                "name": row.name,
                "purpose": row.purpose,
                "scope": row.scope,
                "owner_id": str(row.owner_id),
                "visibility": row.visibility,
                "revision": row.revision,
                "status": row.status,
                "definition": {
                    key: definition[key]
                    for key in ("id", "title", "revision", "status", "source_status")
                },
                "required_source_read_set": list(
                    {
                        ref["artifact_id"]: {
                            "artifact_id": ref["artifact_id"],
                            "expected_revision": ref["expected_revision"],
                        }
                        for ref in definition["sources"]
                    }.values()
                ),
                "proposals": [
                    {
                        "id": str(p.id),
                        "revision": p.revision,
                        "reason": p.reason,
                        "forecast": p.forecast,
                        "input_snapshot": p.input_snapshot,
                        "project_revision": p.project_revision,
                    }
                    for p in proposals
                ],
                "plan": {
                    "id": str(plan.id),
                    "revision": plan.revision,
                    "status": plan.status,
                    "proposal_id": str(plan.proposal_id),
                    "input_snapshot": s.get(PlanProposal, plan.proposal_id).input_snapshot,
                    "forecast": plan.forecast,
                }
                if plan
                else None,
                "timeline": {
                    "baseline": None,
                    "forecast": plan.forecast if plan else None,
                    "commitment": None,
                    "actual": None,
                },
                "work_packages": [
                    {"id": str(package.id), "discipline": package.discipline}
                    for package in s.scalars(
                        select(ProjectWorkPackage).where(ProjectWorkPackage.plan_id == plan.id)
                    )
                ]
                if plan
                else [],
                "tasks": [
                    {
                        "id": str(task.id),
                        "key": task.key,
                        "work_package_id": str(task.work_package_id),
                        "forecast": task.forecast,
                    }
                    for task in s.scalars(select(ProjectTask).where(ProjectTask.plan_id == plan.id))
                ]
                if plan
                else [],
                "source_status": definition["source_status"],
                "created_at": row.created_at.isoformat(),
            }
        )
    return {"items": items, "has_more": len(rows) > 100, "unavailable_count": unavailable}
