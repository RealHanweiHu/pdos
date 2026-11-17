from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import func, select, text

from pdos_next.core.models import Principal, Product
from pdos_next.core.request_proof import snapshot_get, snapshot_scalar
from pdos_next.domain.categories.products.definitions import definition_view
from pdos_next.domain.categories.products.models import DefinitionRevision
from pdos_next.domain.projects.planning.calendar import ScheduleError
from pdos_next.domain.projects.planning.scheduling import schedule
from pdos_next.errors import DomainError

from .models import (
    PlanProposal,
    PlanRevision,
    Project,
    ProjectProductLink,
    ProjectTask,
    ProjectWorkPackage,
    TaskDependency,
)
from .schemas import PlanApplyPayload, PlanProposePayload

category_lifecycle_fence = True


def _definition(s, ctx, product_id, definition_id, revision=None):
    row = snapshot_get(s, DefinitionRevision, definition_id, scope_id=product_id)
    if not row or row.product_id != product_id or row.tenant_id != ctx.tenant_id:
        raise DomainError("SOURCE_UNAVAILABLE", "型号定义不在当前授权范围。", 403)
    value = definition_view(s, ctx, row)
    if revision is not None and revision != row.revision:
        raise DomainError("VERSION_CONFLICT", "固定型号定义版本不匹配。")
    return row, value


def _project(s, ctx, product_id, project_id, *, write=False):
    if write:
        s.scalar(select(Product).where(Product.id == product_id).with_for_update())
    query = select(Project).where(
        Project.id == project_id,
        Project.product_id == product_id,
        Project.tenant_id == ctx.tenant_id,
    )
    row = snapshot_scalar(
        s, (Project, product_id, project_id), query, lock=write, scope_id=product_id
    )
    if not row or (write and row.owner_id != ctx.requester_id):
        raise DomainError("FORBIDDEN_SCOPE", "当前项目不可用，计划由项目负责人建立。", 403)
    link = snapshot_scalar(
        s,
        (ProjectProductLink, product_id, row.id),
        select(ProjectProductLink).where(ProjectProductLink.project_id == row.id),
        scope_id=product_id,
    )
    _, definition = _definition(s, ctx, product_id, link.definition_id, link.definition_revision)
    return row, link, definition


def _proposal(s, ctx, product_id, payload):
    row = s.get(PlanProposal, payload.proposal_id)
    if (
        not row
        or row.tenant_id != ctx.tenant_id
        or row.product_id != product_id
        or row.project_id != payload.project_id
    ):
        raise DomainError("FORBIDDEN_SCOPE", "计划候选不在当前授权范围。", 403)
    return row


def t0_initial_plan(s, project):
    from .governance.models import GovernanceEvent

    return bool(
        project
        and project.framework_id
        and project.current_plan_id is None
        and not s.scalar(
            select(GovernanceEvent.id)
            .where(
                GovernanceEvent.tenant_id == project.tenant_id,
                GovernanceEvent.project_id == project.id,
                GovernanceEvent.operation == "work.baseline.approve",
            )
            .limit(1)
        )
    )


@dataclass
class PlanWrite:
    draft_inputs: tuple | None
    confirmation_id: UUID | None = None


def validate(s, ctx, command, product, payload):
    from pdos_next.core.service import source_for
    from pdos_next.domain.categories.preproject.baseline import validate_sources

    actor = s.get(Principal, ctx.actor_id)
    automated = bool(ctx.agent_run_id and ctx.agent_call_id and actor.kind == "agent")
    if not automated and (
        ctx.run_id or ctx.agent_run_id or ctx.actor_id != ctx.requester_id or actor.kind != "human"
    ):
        raise DomainError("NAMED_DECISION_REQUIRED", "此计划由项目负责人本人确认。", 403)
    if command.expected_revision != product.revision:
        raise DomainError("VERSION_CONFLICT", "型号范围版本已变化。")
    project, link, definition = _project(s, ctx, product.id, payload.project_id, write=True)
    if project.revision != payload.expected_project_revision:
        raise DomainError("VERSION_CONFLICT", "项目版本已变化，请重新核对候选。")
    if project.framework_id and s.info.get("read_snapshot") is not True:
        s.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"project-role-catalog:{ctx.tenant_id}"},
        )
    validate_sources(s, ctx, definition)
    if automated:
        from pdos_next.agent.kernel.models import AgentRun

        run = s.get(AgentRun, ctx.agent_run_id)
        if (
            not isinstance(payload, PlanApplyPayload)
            or payload.draft is None
            or not t0_initial_plan(s, project)
            or run is None
            or run.project_id != project.id
            or not run.versions.get("npi_g0")
        ):
            raise DomainError("CONFIRMATION_REQUIRED", "此计划须由项目负责人一次确认。")
    from pdos_next.schemas.planning import ScheduleInput

    from .npi.planning import scheduling_calendar, validate_plan
    from .npi.rules import PlanBasis

    draft = payload.draft if isinstance(payload, PlanApplyPayload) else payload
    if draft is None:
        proposal = _proposal(s, ctx, product.id, payload)
        if (
            proposal.project_revision != project.revision
            or proposal.base_plan_id != project.current_plan_id
        ):
            raise DomainError("VERSION_CONFLICT", "候选已过期，请从当前计划准备新候选。")
        raw = proposal.input_snapshot.get("npi")
        if raw or project.framework_id:
            fixed_schedule = ScheduleInput.model_validate(
                {key: proposal.input_snapshot[key] for key in ("start", "calendar", "tasks")}
            )
            metadata = validate_plan(
                s,
                ctx,
                project,
                link,
                PlanBasis.model_validate(raw["basis"]) if raw else None,
                fixed_schedule,
                command.source_read_set,
                allow_upgrade=not automated,
            )
            _, basis = scheduling_calendar(s, ctx, fixed_schedule)
            if metadata != raw["checked"] or basis != proposal.input_snapshot["calendar_basis"]:
                raise DomainError(
                    "VERSION_CONFLICT", "定义、团队或日历已变化，请重新准备并核对计划。"
                )
    else:
        from .resources import validate_demands

        if draft.base_plan_id != project.current_plan_id:
            raise DomainError("VERSION_CONFLICT", "请基于当前计划版本准备候选。")
        metadata = validate_plan(
            s,
            ctx,
            project,
            link,
            draft.npi,
            draft.schedule,
            command.source_read_set,
            allow_upgrade=not automated,
        )
        plan_input, basis = (
            scheduling_calendar(s, ctx, draft.schedule) if metadata else (draft.schedule, None)
        )
        forecast = calculate(plan_input)
        validate_demands(s, ctx, product.id, draft.project_id, draft.resource_demands)
    reads = {str(read.artifact_id): read.expected_revision for read in command.source_read_set}
    for reference in definition["sources"]:
        if reads.get(reference["artifact_id"]) != reference["expected_revision"]:
            raise DomainError("MISSING_REQUIRED_EVIDENCE", "项目和计划需要固定定义的全部来源版本。")
        source_for(
            s, ctx, product.id, UUID(reference["artifact_id"]), reference["expected_revision"]
        )
    return PlanWrite((plan_input, forecast, metadata, basis) if draft else None)


def confirmation_subject(s, ctx, command, product, payload):
    if isinstance(payload, PlanApplyPayload) and payload.proposal_id:
        return "proposal", _proposal(s, ctx, product.id, payload)
    return "product", product


def calculate(schedule_input):
    try:
        return schedule(schedule_input).model_dump(mode="json")
    except ScheduleError as error:
        raise DomainError(
            error.code, "日历、估计或依赖无法计算，请核对计划输入。", 422, detail=error.as_dict()
        ) from None


def semantic(payload):
    value = payload.model_dump(mode="json")
    value.pop("confirmation_token", None)
    if value.get("npi") is None:
        value.pop("npi", None)
    if "schedule" in value:
        value["schedule"]["tasks"] = sorted(
            value["schedule"]["tasks"], key=lambda task: task["key"]
        )
        for task in value["schedule"]["tasks"]:
            task["depends_on"] = sorted(task["depends_on"])
    return value


def preview_view(s, ctx, command, product, payload):
    prepared = validate(s, ctx, command, product, payload)
    project, link, _ = _project(s, ctx, product.id, payload.project_id, write=True)
    if payload.draft:
        plan_input, forecast, metadata, basis = prepared.draft_inputs
        input_snapshot = plan_input.model_dump(mode="json")
        input_snapshot.update(
            npi={"basis": payload.draft.npi.model_dump(mode="json"), "checked": metadata},
            calendar_basis=basis,
        )
        forecast["calendar_basis"] = basis
        proposal = PlanProposal(
            base_plan_id=payload.draft.base_plan_id,
            reason=payload.draft.reason,
            resource_demands=[
                item.model_dump(mode="json") for item in payload.draft.resource_demands
            ],
            forecast=forecast,
            input_snapshot=input_snapshot,
            revision=0,
        )
    else:
        proposal = _proposal(s, ctx, product.id, payload)
    from .resources import analyze, compare

    current = s.get(PlanRevision, project.current_plan_id) if project.current_plan_id else None
    return {
        "comparison": compare(current.forecast if current else None, proposal.forecast),
        "resources": analyze(
            s, ctx, product.id, project, proposal.forecast, proposal.resource_demands
        ),
        "base_plan_id": str(proposal.base_plan_id) if proposal.base_plan_id else None,
        "operation": command.operation,
        "project_id": str(project.id),
        "name": project.name,
        "project_revision": project.revision,
        "current_plan_id": str(project.current_plan_id) if project.current_plan_id else None,
        "proposal_id": str(proposal.id) if proposal.id else None,
        "proposal_revision": proposal.revision,
        "definition_id": str(link.definition_id),
        "input_snapshot": proposal.input_snapshot,
        "framework_upgrade": (proposal.input_snapshot.get("npi") or {})
        .get("checked", {})
        .get("framework_upgrade"),
        "reason": proposal.reason,
        "forecast": proposal.forecast,
        "effect": (
            "生成新的计划版本与工作包、任务及依赖；"
            "保留历史计划、已执行任务、基线、承诺与实绩，"
            "不改动实际预约。"
        ),
    }


def create_project(
    s,
    ctx,
    product,
    *,
    owner_id,
    name,
    purpose,
    scope,
    visibility,
    definition_id,
    definition_revision,
    project_id,
    decision,
    variant_id=None,
):
    from pdos_next.domain.categories.preproject.models import (
        Proposal,
        ProposalDecision,
        ProposalSubmission,
    )
    from pdos_next.domain.categories.products.service import require_creation
    from pdos_next.domain.categories.products.variant_models import Variant

    if decision is None or not project_id or not getattr(decision, "id", None):
        raise DomainError("NAMED_DECISION_REQUIRED", "项目只随实际 G0 批准建立。", 403)
    decision = s.get(ProposalDecision, decision.id, populate_existing=True)
    if decision is None:
        raise DomainError("NAMED_DECISION_REQUIRED", "实际 G0 决定不可用。", 403)
    require_creation(s, ctx, product_id=product.id, decision=decision)
    product = s.get(Product, product.id, populate_existing=True)
    proposal = s.get(Proposal, decision.proposal_id, populate_existing=True)
    submission = s.get(ProposalSubmission, decision.submission_id, populate_existing=True)
    if (
        not product
        or product.tenant_id != ctx.tenant_id
        or product.category_id != ctx.category_id
        or not proposal
        or proposal.tenant_id != ctx.tenant_id
        or proposal.category_id != ctx.category_id
        or proposal.owner_id != decision.owner_id
        or not submission
        or submission.tenant_id != ctx.tenant_id
        or submission.category_id != ctx.category_id
        or submission.proposal_id != proposal.id
        or proposal.current_submission_id != submission.id
        or submission.owner_id != decision.owner_id
        or submission.reviewer_id != decision.decided_by
        or decision.review_digest != submission.document_digest
        or project_id != decision.created_project_id
        or definition_id != decision.created_definition_id
        or owner_id != decision.project_owner_id
        or variant_id != decision.created_variant_id
        or name != decision.creation["project_name"]
        or purpose != proposal.brief
        or scope != proposal.brief
        or visibility != proposal.effective_visibility
    ):
        raise DomainError("FORBIDDEN_SCOPE", "项目须准确对应本次 G0 决定及固定提案。", 403)
    # G0 seals with SQL after assembling children; refresh the identity-map row
    # so checks use the actual stored seal and provenance, not its prior draft.
    definition = s.get(DefinitionRevision, definition_id, populate_existing=True)
    if (
        not definition
        or definition.tenant_id != ctx.tenant_id
        or definition.category_id != ctx.category_id
        or definition.product_id != product.id
        or definition_revision != 1
        or definition.revision != 1
        or not definition.sealed
        or definition.status != "draft"
        or definition.variant_id != variant_id
        or definition.g0_decision_id != decision.id
        or definition.source_proposal_id != proposal.id
        or definition.source_submission_id != submission.id
        or definition.source_proposal_revision != submission.revision
        or definition.owner_id != proposal.owner_id
        or definition.visibility != visibility
    ):
        raise DomainError("SOURCE_UNAVAILABLE", "项目须固定本次 G0 封存的型号定义 v1。")
    if variant_id is not None:
        variant = s.get(Variant, variant_id, populate_existing=True)
        if (
            not variant
            or variant.tenant_id != ctx.tenant_id
            or variant.category_id != ctx.category_id
            or variant.product_id != product.id
            or variant.g0_decision_id != decision.id
        ):
            raise DomainError("SOURCE_UNAVAILABLE", "项目变体须属于本次 G0 结果。")
    trigger_type = (
        "parent_product"
        if proposal.baseline_product_id is not None
        else "customer_request"
        if proposal.entry_kind == "customer_request"
        else "proposal"
    )
    from .npi.catalog import effective

    kind = "derivative" if trigger_type == "parent_product" else "new_product"
    framework = effective(s, ctx, kind)
    trigger_id = proposal.baseline_product_id or proposal.id
    project = Project(
        id=project_id,
        tenant_id=ctx.tenant_id,
        product_id=product.id,
        owner_id=owner_id,
        name=name,
        purpose=purpose,
        scope=scope,
        visibility=visibility,
        g0_decision_id=decision.id,
        trigger_type=trigger_type,
        trigger_id=trigger_id,
        framework_id=framework.id if framework else None,
    )
    s.add(project)
    s.flush([project])
    s.add(
        ProjectProductLink(
            tenant_id=ctx.tenant_id,
            product_id=product.id,
            variant_id=variant_id,
            project_id=project.id,
            definition_id=definition_id,
            definition_revision=definition_revision,
            scope=scope,
        )
    )
    s.flush()
    return project


def _save_proposal(s, ctx, product, project, payload, value):
    schedule_input, forecast, metadata, basis = value
    fixed_input = schedule_input.model_dump(mode="json")
    if metadata:
        fixed_input.update(
            npi={"basis": payload.npi.model_dump(mode="json"), "checked": metadata},
            calendar_basis=basis,
        )
        forecast["calendar_basis"] = basis
    calendar = fixed_input["calendar"]
    calendar["timezone_rules_sha256"] = forecast["calendar_ref"]["timezone_rules_sha256"]
    calendar["working_weekdays"] = sorted(calendar["working_weekdays"])
    calendar["holidays"] = sorted(calendar["holidays"])
    if "makeup_workdays" in calendar:
        calendar["makeup_workdays"] = sorted(calendar["makeup_workdays"])
    calendar["intervals"] = sorted(calendar["intervals"], key=lambda item: item["start_minute"])
    for previous in s.scalars(select(PlanProposal).where(PlanProposal.project_id == project.id)):
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
        base_plan_id=payload.base_plan_id,
        resource_demands=[d.model_dump(mode="json") for d in payload.resource_demands],
        forecast=forecast,
        reason=payload.reason,
    )
    return proposal


def apply_validated(s, ctx, command, product, payload, value):
    project, _, _ = _project(s, ctx, product.id, payload.project_id, write=True)
    if project.revision != payload.expected_project_revision:
        raise DomainError("VERSION_CONFLICT", "项目已变化，请重新查看实际范围。")
    if isinstance(payload, PlanProposePayload):
        proposal = _save_proposal(s, ctx, product, project, payload, value.draft_inputs)
        return proposal, "plan_proposal", project.visibility
    if payload.draft:
        proposal = _save_proposal(s, ctx, product, project, payload.draft, value.draft_inputs)
        s.add(proposal)
        s.flush([proposal])
    else:
        proposal = _proposal(s, ctx, product.id, payload)
    if (
        proposal.project_revision != project.revision
        or proposal.base_plan_id != project.current_plan_id
    ):
        raise DomainError("VERSION_CONFLICT", "计划候选针对的项目版本已经过期。")
    from .resources import validate_demands
    from .schemas import ResourceDemand

    validate_demands(
        s,
        ctx,
        product.id,
        project.id,
        [ResourceDemand.model_validate(d) for d in proposal.resource_demands],
    )
    previous = s.get(PlanRevision, project.current_plan_id) if project.current_plan_id else None
    plan = PlanRevision(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        product_id=product.id,
        project_id=project.id,
        proposal_id=proposal.id,
        owner_id=ctx.requester_id,
        revision=previous.revision + 1 if previous else 1,
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
    npi = proposal.input_snapshot.get("npi")
    task_details = {}
    if npi:
        stage_for = {outcome["key"]: outcome["stage"] for outcome in npi["checked"]["outcomes"]}
        checked_tasks = npi["basis"]["tasks"]
        roles = npi["checked"]["assignments"]
        stage_sets = {
            key: {stage_for[outcome] for outcome in detail["outcome_keys"]}
            for key, detail in checked_tasks.items()
        }
        for item in reversed(proposal.forecast["tasks"]):
            for parent in item["depends_on"]:
                stage_sets[parent].update(stage_sets[item["key"]])
        task_details = {
            key: detail
            | {"stage_keys": sorted(stage_sets[key]), "resolved_assignee_id": roles[key]}
            for key, detail in checked_tasks.items()
        }
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
            forecast=item | task_details.get(item["key"], {}),
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
    plan.confirmation_id = value.confirmation_id
    upgrade = npi["checked"].get("framework_upgrade") if npi else None
    if upgrade:
        if value.confirmation_id is None or ctx.agent_run_id:
            raise DomainError("CONFIRMATION_REQUIRED", "框架升级须由项目负责人确认。")
        project.framework_id = UUID(upgrade["to"]["id"])
    if ctx.agent_run_id:
        plan.action_result = {"npi_write_tier": "T0"}
    plan.action_result = {
        **getattr(plan, "action_result", {}),
        "project_id": str(project.id),
        "proposal_id": str(proposal.id),
        **({"framework_upgrade": upgrade} if upgrade else {}),
        **(
            {"calendar_basis": proposal.input_snapshot["calendar_basis"]}
            if "calendar_basis" in proposal.input_snapshot
            else {}
        ),
        "work_package_ids": [str(package.id) for package in packages.values()],
        "task_ids": [str(task.id) for task in tasks.values()],
    }
    return plan, "plan_revision", project.visibility


def list_projects(s, ctx, product_id, *, project_id=None):
    from pdos_next.core.service import require_access

    require_access(s, ctx, product_id)
    query = select(Project).where(Project.product_id == product_id)
    if project_id is not None:
        query = query.where(Project.id == project_id)
    rows = s.scalars(query.order_by(Project.created_at.desc()).limit(101)).all()
    if project_id is not None and not rows:
        raise DomainError("NOT_FOUND", "当前项目不可读，请核对范围和权限。", 404)
    items, unavailable = [], 0
    for row in rows[:100]:
        try:
            _, link, definition = _project(s, ctx, product_id, row.id)
        except DomainError as error:
            if project_id is not None or error.code != "SOURCE_UNAVAILABLE":
                raise
            unavailable += 1
            continue
        proposals = s.scalars(
            select(PlanProposal)
            .where(
                PlanProposal.project_id == row.id,
            )
            .order_by(PlanProposal.revision.desc())
            .limit(100)
        ).all()
        plan = s.get(PlanRevision, row.current_plan_id) if row.current_plan_id else None
        if project_id is not None and row.current_plan_id and plan is None:
            raise DomainError("SOURCE_UNAVAILABLE", "当前计划暂不可读，请核对权限后刷新。", 403)
        from pdos_next.domain.projects.governance.projection import summary as governance_summary

        from .resources import lineage

        current_tasks = (
            list(s.scalars(select(ProjectTask).where(ProjectTask.plan_id == plan.id)))
            if plan
            else []
        )
        task_lineage = lineage(s, row.id, current_tasks)
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
                "governance": governance_summary(s, ctx, row),
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
                        "base_plan_id": str(p.base_plan_id) if p.base_plan_id else None,
                        "resource_demands": p.resource_demands,
                    }
                    for p in proposals
                ],
                "plan": {
                    "id": str(plan.id),
                    "revision": plan.revision,
                    "status": plan.status,
                    "proposal_id": str(plan.proposal_id),
                    "input_snapshot": s.get(PlanProposal, plan.proposal_id).input_snapshot,
                    "resource_demands": s.get(PlanProposal, plan.proposal_id).resource_demands,
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
                        "lineage_ids": task_lineage[task.key],
                        "work_package_id": str(task.work_package_id),
                        "forecast": task.forecast,
                    }
                    for task in current_tasks
                ]
                if plan
                else [],
                "source_status": definition["source_status"],
                "created_at": row.created_at.isoformat(),
            }
        )
    return {"items": items, "has_more": len(rows) > 100, "unavailable_count": unavailable}
