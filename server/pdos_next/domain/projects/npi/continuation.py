"""Queue G0 planning using the same durable run journal as the 小Pai entry point."""

from types import SimpleNamespace
from uuid import UUID

from pydantic import Field
from sqlalchemy import select, text

from pdos_next.agent.kernel.api import reference
from pdos_next.agent.kernel.bootstrap import Bootstrap
from pdos_next.agent.kernel.models import AgentEvent, AgentRun
from pdos_next.agent.kernel.persistence import create_run
from pdos_next.agent.kernel.policy import skill_enabled
from pdos_next.core.contracts import SourceRead
from pdos_next.core.database import tenant_session
from pdos_next.core.dispatch.context import event_context
from pdos_next.core.models import Outbox, Receipt
from pdos_next.core.schema_base import StrictModel
from pdos_next.core.service import Context
from pdos_next.domain.categories.preproject.access import human
from pdos_next.domain.categories.preproject.models import ProposalDecision
from pdos_next.domain.projects.models import Project
from pdos_next.errors import DomainError

from .planning import current_definition

GOAL = (
    "按项目固定的 NPI 框架和后附的项目规划依据，为刚立项的项目准备首版计划。"
    "使用 work_management，一次生成完整任务与阶段成果映射，调用 work.plan.apply，填写 draft。"
    "按框架检查反馈最多修正一次。负责角色依据项目角色目录，存在歧义请明确列出，"
    "无工期依据保留未知。"
)


def key(project):
    return f"npi-g0:{project.g0_decision_id}:{project.id}"


class Retry(StrictModel):
    expected_project_revision: int = Field(ge=1, strict=True)
    previous_run_id: UUID | None = None


def _runs(s, ctx, project):
    return select(AgentRun).where(
        AgentRun.tenant_id == ctx.tenant_id,
        AgentRun.requester_id == ctx.requester_id,
        AgentRun.project_id == project.id,
        AgentRun.intent_key.startswith(key(project)),
    )


def _latest(s, ctx, project):
    return s.scalar(_runs(s, ctx, project).order_by(AgentRun.created_at.desc()).limit(1))


def _retryable(run, events):
    if run is None:
        return True
    if run.reverted_at or run.state not in {"failed", "partial", "completed", "cancelled"}:
        return False
    if run.held_tokens or run.error_code in {"TIMEOUT", "OUTCOME_UNKNOWN"}:
        return False
    candidate = any(event.body["type"] == "npi_plan_candidate" for event in events)
    return not candidate


def run_view(s, ctx, project, run=None):
    if ctx.requester_id != project.owner_id or not project.g0_decision_id:
        return None
    run = run if run is not None else _latest(s, ctx, project)
    if not run:
        return {
            "state": "not_queued",
            "run_id": None,
            "candidate": None,
            "failures": [],
            "retry_available": not project.current_plan_id,
        }
    from .candidate import events

    history = events(s, run.id)

    candidate, failures = None, []
    if not run.reverted_at and not project.current_plan_id and run.state != "cancelled":
        for event in history:
            value = event.body
            if value["type"] == "npi_plan_candidate":
                candidate = {key: value[key] for key in ("command", "role_exceptions")}
            else:
                failures.append(value["error"]["detail"])
    return {
        "run_id": str(run.id),
        "session_id": str(run.session_id),
        "state": run.state,
        "reason": run.error_code,
        "candidate": candidate,
        "failures": failures,
        "retry_available": not project.current_plan_id and _retryable(run, history),
    }


def queue(engine, event):
    """Consume only a committed native G0 event. A replay finds its original run."""
    origin = event_context(vars(event))
    with tenant_session(
        engine,
        origin.tenant_id,
        actor_id=origin.actor_id,
        requester_id=origin.requester_id,
        category_id=origin.category_id,
    ) as s:
        project = s.get(Project, UUID(event.subject_id))
        outbox = s.get(Outbox, UUID(event.event_id))
        decision = s.get(ProposalDecision, project.g0_decision_id) if project else None
        receipt = s.get(Receipt, outbox.receipt_id) if outbox else None
        if (
            not project
            or not project.framework_id
            or not decision
            or not receipt
            or not outbox
            or outbox.type != "project.created"
            or outbox.subject_id != project.id
            or outbox.receipt_id != decision.receipt_id
            or receipt.operation != "proposal.g0.decide"
            or outbox.category_id != origin.category_id
            or outbox.tenant_id != origin.tenant_id
            or decision.created_project_id != project.id
            or decision.created_product_id != project.product_id
            or decision.project_owner_id != project.owner_id
        ):
            return None
        project_id, owner_id = project.id, project.owner_id
    ctx = Context(origin.tenant_id, owner_id, owner_id, category_id=origin.category_id)
    with tenant_session(
        engine,
        ctx.tenant_id,
        actor_id=owner_id,
        requester_id=owner_id,
        category_id=ctx.category_id,
    ) as s:
        project = s.get(Project, project_id)
        if project is None or project.owner_id != ctx.requester_id:
            return None
        _lock(s, project)
        prior = _latest(s, ctx, project)
        if prior:
            return reference(prior, ctx)
        if project.current_plan_id:
            return None
        decision = s.get(ProposalDecision, project.g0_decision_id)
        if decision is None:
            return None
        run = _admit(s, ctx, project, decision, key(project))
        return reference(run, ctx) if run else None


def _lock(s, project):
    s.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"), {"key": key(project)})


def _admit(s, ctx, project, decision, intent):
    product_id, project_id = project.product_id, project.id
    variant_id = decision.created_variant_id
    _, definition = current_definition(s, ctx, product_id, variant_id)
    sources = {}
    for source in definition["sources"]:
        artifact_id, revision = UUID(source["artifact_id"]), source["expected_revision"]
        sources[artifact_id] = SourceRead(artifact_id=artifact_id, expected_revision=revision)
    engine = s.get_bind()
    bootstrap = getattr(engine, "_pdos_category_candidate_owner", None) or Bootstrap(engine)
    skill = bootstrap.catalog.configuration("work_management")
    if skill is None or not skill_enabled(s, ctx, skill):
        return None
    data = SimpleNamespace(
        product_id=product_id,
        project_id=project_id,
        proposal_id=None,
        sources=list(sources.values()),
    )
    binding = bootstrap.binding_for(s, ctx, data)
    s.refresh(project)
    if project.current_plan_id:
        raise DomainError("VERSION_CONFLICT", "项目已有已应用的计划。")
    run = create_run(
        s,
        ctx,
        goal=GOAL,
        writer_id=bootstrap.writer_for(s, ctx),
        intent_key=intent,
        product_id=product_id,
        project_id=project_id,
        private_context=binding.private_context,
        data_categories=binding.data_categories,
        customer_identities=binding.customer_identities,
        read_sources=binding.read_sources,
        token_limit=binding.token_limit,
        validation_budget_id=binding.validation_budget_id,
    )
    run.versions = {**run.versions, "npi_g0": True}
    s.add(
        AgentEvent(
            tenant_id=ctx.tenant_id,
            run_id=run.id,
            sequence=1,
            body={
                "type": "accepted",
                "status": "queued",
                "requested_skills": [
                    {"key": skill.key, "version": skill.version, "digest": skill.digest}
                ],
            },
        )
    )
    return run


def retry(s, ctx, product_id, project_id, data):
    from pdos_next.core.service import require_access
    from pdos_next.domain.projects.service import _project

    from .candidate import events

    human(s, ctx)
    require_access(s, ctx, product_id, write=True)
    project, _, _ = _project(s, ctx, product_id, project_id)
    if project.owner_id != ctx.requester_id or not project.framework_id:
        raise DomainError("FORBIDDEN_SCOPE", "首版计划由项目负责人重新受理。", 403)
    _lock(s, project)
    s.refresh(project)
    if project.current_plan_id or project.revision != data.expected_project_revision:
        raise DomainError("VERSION_CONFLICT", "项目已有计划或版本已改变，请刷新。")
    intent = (
        f"{key(project)}:retry:{data.previous_run_id}" if data.previous_run_id else key(project)
    )
    prior = s.scalar(_runs(s, ctx, project).where(AgentRun.intent_key == intent))
    if prior:
        return run_view(s, ctx, project, prior)
    latest = _latest(s, ctx, project)
    if (latest.id if latest else None) != data.previous_run_id or not _retryable(
        latest,
        events(s, latest.id) if latest else (),
    ):
        raise DomainError("VERSION_CONFLICT", "原运行仍在处理或已有待核对结果，请刷新。")
    decision = s.get(ProposalDecision, project.g0_decision_id)
    if (
        decision is None
        or decision.outcome != "approved"
        or decision.created_project_id != project.id
    ):
        raise DomainError("SOURCE_UNAVAILABLE", "缺少当前项目的固定 G0 决定。")
    run = _admit(s, ctx, project, decision, intent)
    if run is None:
        raise DomainError("SOURCE_UNAVAILABLE", "请先启用当前租户的项目工作技能。")
    s.flush()
    return run_view(s, ctx, project)
