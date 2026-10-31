"""Run-bound owner reads for the deterministic branch of the one 小Pai graph.

No public owner/reference endpoint, role switch, model, outbound call or business
write lives here. The caller supplies an actual KernelStore scope, not a Human ID.
"""

from contextlib import contextmanager
from copy import deepcopy

from sqlalchemy import literal, or_, select

from pdos_next import personal_summary
from pdos_next.agent_kernel.models import AgentRun
from pdos_next.agent_kernel.types import AgentOutput
from pdos_next.database import require_context, tenant_session
from pdos_next.domain.automations import service_runtime
from pdos_next.domain.automations.service_models import AutomationServiceAttempt as Attempt
from pdos_next.errors import DomainError
from pdos_next.models import Principal
from pdos_next.personal_summary_schemas import Baseline, Summary
from pdos_next.service import Context, require_access

KIND = "personal_summary"
TERMINAL = frozenset({"completed", "partial", "failed", "cancelled"})


def _deny(message="摘要缺少实际本人自动化运行授权。"):
    raise DomainError("FORBIDDEN_SCOPE", message, 403)


def selected(spec):
    return spec.personal_summary is not None


def _bound(s, run, *, historical=False):
    """Recheck stored Run/Attempt/Grant/version/T1 receipt, including on replay."""
    _, spec = service_runtime.summary_binding(s, run, historical=historical)
    owner = s.get(Principal, run.requester_id)
    if not owner or owner.tenant_id != run.tenant_id or not owner.active or owner.kind != "human":
        _deny("摘要订阅者已不是当前有效本人身份。")
    choice = spec.personal_summary
    # A category on a selection only narrows the actual single-category grant.
    groups = choice.groups
    if choice.category_ids and run.category_id not in choice.category_ids:
        groups = ()
    choice = choice.model_copy(update={"category_ids": (run.category_id,), "groups": groups})
    return spec, choice


def _same_run(run, scope):
    if not run or any(
        getattr(run, key) != getattr(scope, target)
        for key, target in (
            ("id", "run_id"), ("tenant_id", "tenant_id"),
            ("requester_id", "requester_id"), ("writer_id", "writer_id"),
            ("category_id", "category_id"), ("product_id", "product_id"),
            ("session_id", "session_id"), ("trigger", "trigger"),
        )
    ):
        _deny()
    if run.reverted_at or run.state == "cancelled" or run.cancel_epoch != scope.cancel_epoch:
        raise DomainError("CANCELLED_RUN", "摘要运行已取消，不能追加结果。")


@contextmanager
def _owner_snapshot(store, scope):
    # This first ordinary writer/requester transaction proves the server scope.
    # It never gains the owner's private business reading authority.
    if scope.trigger != "automation_service" or scope.isolation != "main":
        _deny()
    with store.transaction(scope) as (s, run):
        _bound(s, run)
        tenant, owner = run.tenant_id, run.requester_id
    with tenant_session(
        store.engine, tenant, actor_id=owner, requester_id=owner, read_snapshot=True,
    ) as s:
        # Derive again from the actual Run under current owner RLS; no arbitrary
        # owner id or caller-supplied grant can enter this personal read adapter.
        run = s.get(AgentRun, scope.run_id)
        _same_run(run, scope)
        spec, choice = _bound(s, run)
        scoped = Context(tenant, owner, owner, category_id=run.category_id)
        require_access(s, scoped, spec.product_id)
        yield s, Context(tenant, owner, owner), run, spec, choice


def _previous(s, run, choice):
    # Only hashes from the same immutable publication and earlier actual admission
    # enter comparison. No prior source text is replayed or read for this purpose.
    attempt = s.scalar(select(Attempt).where(Attempt.run_id == run.id))
    value = s.scalar(
        select(AgentRun.result["result"][KIND]["baseline"])
        .join(Attempt, (Attempt.run_id == AgentRun.id) & (Attempt.tenant_id == AgentRun.tenant_id))
        .where(
            AgentRun.tenant_id == run.tenant_id,
            AgentRun.requester_id == run.requester_id,
            AgentRun.category_id == run.category_id,
            AgentRun.product_id.is_not_distinct_from(run.product_id),
            AgentRun.trigger == "automation_service",
            AgentRun.state.in_(("completed", "partial")),
            AgentRun.reverted_at.is_(None),
            Attempt.published_version_id == attempt.published_version_id,
            Attempt.rule_id == attempt.rule_id,
            Attempt.state == "admitted",
            or_(
                AgentRun.created_at < run.created_at,
                (AgentRun.created_at == run.created_at) & (AgentRun.id < run.id),
            ),
            AgentRun.result["result"][KIND]["version"].astext == "personal-summary/v1",
        )
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc()).limit(1)
    )
    if value is None:
        return None
    baseline = Baseline.model_validate(value)
    if (
        baseline.tenant_id != run.tenant_id or baseline.principal_id != run.requester_id
        or baseline.selection_digest != personal_summary._selection_digest(choice)
    ):
        raise DomainError("INTEGRITY_MISMATCH", "原摘要基线与固定订阅选择不一致。")
    return baseline


def generate(store, scope):
    with _owner_snapshot(store, scope) as (s, ctx, run, spec, choice):
        return personal_summary.read(
            s, ctx, choice, previous=_previous(s, run, choice), product_id=spec.product_id,
        ).model_dump(mode="json")


def _source_models():
    from pdos_next.domain.external_handoff.models import ExternalReceipt
    from pdos_next.domain.external_wait.models import ExternalWaitVersion
    from pdos_next.domain.preproject.models import ProjectOpenItem, ProposalSubmission
    from pdos_next.domain.project_governance.models import GovernanceEvent
    from pdos_next.domain.project_risk.models import ProjectRiskFollowup
    from pdos_next.domain.projects.models import Project
    from pdos_next.domain.quality_execution.models import QualityIssueVersion
    from pdos_next.domain.verification_front.models import FormalVerificationRequest
    from pdos_next.domain.verification_launch.models import VerificationRunVersion
    from pdos_next.domain.work_management.models import (
        ProjectStatusUpdate,
        WorkCommitmentVersion,
        WorkTaskVersion,
    )

    return {
        "task": (WorkTaskVersion,), "work_task": (WorkTaskVersion,),
        "promise_review": (WorkCommitmentVersion,), "work_commitment": (WorkCommitmentVersion,),
        "external_wait": (ExternalWaitVersion,), "external_wait_transfer": (ExternalWaitVersion,),
        "g0_review": (ProposalSubmission,), "external_handoff": (ExternalReceipt,),
        "project_risk": (ProjectOpenItem, ProjectRiskFollowup),
        "verification_handoff_return": (FormalVerificationRequest,),
        "verification_result_return": (VerificationRunVersion,),
        "project_status_update": (ProjectStatusUpdate,), "project": (Project,),
        "quality_issue": (QualityIssueVersion,),
        "project_governance": (GovernanceEvent,),
    }


def _source_key(model):
    keys = {
        "WorkTaskVersion": "task_id", "WorkCommitmentVersion": "series_id",
        "ExternalWaitVersion": "wait_id", "ProposalSubmission": "proposal_id",
        "ExternalReceipt": "handoff_id", "ProjectOpenItem": "id",
        "ProjectRiskFollowup": "risk_id", "FormalVerificationRequest": "request_id",
        "VerificationRunVersion": "run_id", "ProjectStatusUpdate": "project_id", "Project": "id",
        "QualityIssueVersion": "issue_id", "GovernanceEvent": "project_id",
    }
    return getattr(model, keys[model.__name__])


def _readable_sources(s, run, sources):
    """Batch metadata reads by native model under ordinary current owner RLS."""
    readable = set()
    if any(source.category_id != run.category_id or (
        run.product_id is not None and source.product_id != run.product_id
    ) for source in sources):
        return readable
    by_model, supply = {}, set()
    for source in sources:
        if source.kind == "supply":
            supply.add(source)
        for model in _source_models().get(source.kind, ()):
            by_model.setdefault(model, set()).add(source)
    for model, refs in by_model.items():
        product = getattr(model, "product_id", literal(None))
        project = getattr(model, "project_id", literal(None))
        query = select(
            model.id, model.category_id, product.label("product_id"),
            project.label("project_id"), _source_key(model).label("source_id"),
            getattr(model, "revision", literal(None)).label("revision"),
        ).where(
            model.tenant_id == run.tenant_id, model.category_id == run.category_id,
            model.id.in_({source.version_id or source.id for source in refs}),
        )
        if model.__name__ == "QualityIssueVersion":
            # Match native quality _row: private Issue reads remain owner-only.
            query = query.where(or_(model.visibility != "private",
                                    model.owner_id == run.requester_id))
        if run.product_id is not None:
            query = query.where(product == run.product_id)
        rows = s.execute(query).mappings().all()
        for source in refs:
            for row in rows:
                if (
                    row["id"] == (source.version_id or source.id)
                    and source.id in {row["id"], row["source_id"]}
                    and row["category_id"] == source.category_id
                    and row["product_id"] == source.product_id
                    and row["project_id"] == source.project_id
                    and (source.revision is None or model.__name__ == "Project"
                         or row["revision"] == source.revision)
                ):
                    readable.add(source)
    if supply:
        from pdos_next.enterprise_search.sources import prepare_read, select_sources

        prepare_read(s, ("supply",))
        query = select_sources(source_type="supply")
        c = query.selected_columns
        query = query.where(
            c.tenant_id == run.tenant_id, c.category_id == run.category_id,
            c.source_id.in_({source.version_id or source.id for source in supply}),
        ).with_only_columns(c.source_id, c.category_id, c.product_id, c.project_id)
        if run.product_id is not None:
            query = query.where(c.product_id == run.product_id)
        rows = s.execute(query).mappings().all()
        readable.update(source for source in supply if any(
            row["source_id"] == source.id == source.version_id
            and row["category_id"] == source.category_id
            and row["product_id"] == source.product_id
            and row["project_id"] == source.project_id
            for row in rows
        ))
    return readable


def _check_sources(s, run, summary):
    if summary.tenant_id != run.tenant_id or summary.principal_id != run.requester_id:
        _deny()
    sources = {
        item.object for group in summary.groups
        for item in (*group.items, *group.unchanged_items)
    }
    if sources - _readable_sources(s, run, sources):
        _deny("摘要依赖的原固定资料已不可读取，原内容已隐藏。")


def persist(store, scope, value):
    summary = Summary.model_validate(value)
    # Recheck the original snapshot's source ACLs in a fresh ordinary owner RR
    # snapshot after checkpoint recovery. Never replace it with current facts.
    with _owner_snapshot(store, scope) as (s, _ctx, run, _spec, _choice):
        _check_sources(s, run, summary)
    result = AgentOutput(
        status="completed" if summary.complete else "partial",
        summary=(
            "本人结构摘要已生成。" if summary.complete
            else "本人结构摘要已生成，部分来源仍待核对。"
        ),
        result={KIND: value, "delivery": {"state": "available_in_inbox", "destination": "owner"}},
        unfinished=(
            [] if summary.complete
            else ["部分来源超出本次范围或当前不可读取；请在原事项核对。"]
        ),
    ).model_dump(mode="json")
    # Serialize terminal persistence with cancellation and repeated Activity delivery.
    with store.transaction(scope, lock=True) as (s, run):
        _bound(s, run)
        if run.state in TERMINAL:
            if run.state not in {"completed", "partial"} or not isinstance(run.result, dict):
                raise DomainError("CANCELLED_RUN", "原运行已结束，不能覆盖结果。")
            return run.result
        from pdos_next.agent_kernel.process_view import record_state
        from pdos_next.agent_kernel.work_state import record_finish

        run.result = record_finish(s, run, result)
        run.state, run.error_code = result["status"], None
        record_state(s, run)
        return run.result


def checked_result(s, ctx, run):
    """Required HTTP stored-result hook; never expose raw persisted summary JSON.

    The existing endpoint must supply its ordinary Human read_snapshot transaction.
    This is a current READ check, not a new grant and not a model citation proof.
    """
    value = run.result
    if not isinstance(value, dict) or KIND not in value.get("result", {}):
        return None
    require_context(s, ctx)
    if (
        s.info.get("read_snapshot") is not True or ctx.actor_id != ctx.requester_id
        or ctx.requester_id != run.requester_id or ctx.tenant_id != run.tenant_id
        or ctx.category_id != run.category_id
        or ctx.agent_run_id is not None or ctx.run_id is not None
    ):
        _deny()
    spec, _choice = _bound(s, run, historical=True)
    require_access(s, ctx, spec.product_id)
    _check_sources(s, run, Summary.model_validate(value["result"][KIND]))
    return deepcopy(value)
