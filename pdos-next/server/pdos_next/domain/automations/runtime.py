"""Actual Run binding, fixed skill selection and shared rule admission limits."""

from types import SimpleNamespace
from uuid import uuid4

from pdos_next.agent_kernel.models import AgentEvent, AgentRun, AgentToolCall
from pdos_next.agent_kernel.persistence import create_run
from pdos_next.domain.preproject.access import human
from pdos_next.errors import DomainError
from pdos_next.models import now
from pdos_next.service import digest, require_access
from sqlalchemy import case, func, select, text

from .models import AutomationRuleVersion as Version
from .models import AutomationTriggerOccurrence as Occurrence
from .rules import validate_admission
from .schemas import AutomationSpec
from .service import owned, spec_current

TRIGGER = "automation_manual"
TRIGGERS = frozenset({TRIGGER, "automation_service"})


def binding(s, run):
    """Read the immutable occurrence, never arbitrary model/configuration JSON as authority."""
    if run.trigger == "automation_service":
        from .service_runtime import run_binding

        return run_binding(s, run)
    if run.trigger != TRIGGER:
        return None
    occurrence = s.scalar(select(Occurrence).where(Occurrence.run_id == run.id))
    version = s.get(Version, occurrence.published_version_id) if occurrence else None
    if (
        not version
        or version.action != "activate"
        or version.state != "active"
        or version.rule_id != occurrence.rule_id
        or version.tenant_id != run.tenant_id
        or occurrence.tenant_id != run.tenant_id
        or occurrence.category_id != run.category_id
        or occurrence.owner_id != run.requester_id
        or version.owner_id != run.requester_id
        or occurrence.requester_id != run.requester_id
        or version.category_id != run.category_id
        or occurrence.request_digest != run.intent_digest
    ):
        raise DomainError("FORBIDDEN_SCOPE", "运行缺少实际规则受理证明。", 403)
    spec = AutomationSpec.model_validate(version.spec)
    if (
        run.product_id != spec.product_id
        or run.goal != spec.goal
        or run.validation_budget_id != spec.validation_budget_id
        or run.token_limit != spec.token_limit
        or run.proposal_id is not None
    ):
        raise DomainError("FORBIDDEN_SCOPE", "运行与已确认规则不一致。", 403)
    return occurrence, spec


def scope_binding(store, scope):
    if scope.trigger not in TRIGGERS:
        return None
    with store.transaction(scope) as (s, run):
        return binding(s, run)


def permitted_skill(store, scope, skill):
    value = scope_binding(store, scope)
    return value is None or any(
        (ref.key, ref.version, ref.digest) == (skill.key, skill.version, skill.digest)
        for ref in value[1].skill_keys
    )


def preload(store, scope, fallback=()):
    value = scope_binding(store, scope)
    return tuple(ref.key for ref in value[1].skill_keys) if value else tuple(fallback)


def guard_tool(store, scope, name=None, *, writing=False):
    value = scope_binding(store, scope)
    if value is not None and value[1].personal_summary is not None:
        raise DomainError(
            "FORBIDDEN_SCOPE", "确定性本人摘要不能调用模型、query embedding 或通用工具。", 403
        )
    if value is not None and (
        writing
        or name
        in {
            "research.fanout",
            "research.search",
            "research.read",
            "research.fetch",
            "mcp.tools.list",
            "mcp.read",
        }
        or (name and (name.startswith("mcp.") or name.startswith("web.")))
    ):
        raise DomainError(
            "FORBIDDEN_SCOPE", "此规则只运行已选方法的本地读取；联网、MCP 和业务写入未开放。", 403
        )


def reserve(s, run, *, reservation, cost_lease):
    value = binding(s, run)
    if value is not None and value[1].personal_summary is not None:
        raise DomainError(
            "FORBIDDEN_SCOPE", "确定性本人摘要不领取任何通用工具或模型调用。", 403
        )
    if value is None or cost_lease is None:
        return
    occurrence, spec = value
    if run.trigger == "automation_service":
        # SQL checks the stored chain and serializes its shared envelope before
        # the per-rule lock, including descendants owned by other delegators.
        allowed = s.scalar(
            text("SELECT automation_chain_reserve(:run,:cost,:inp,:outp)"),
            {"run": run.id, "cost": cost_lease[0], "inp": cost_lease[1], "outp": cost_lease[2]},
        )
        if allowed is not True:
            raise DomainError("RATE_LIMITED", "本因果链的累计预算已达上限。")
    # All runs of this rule serialize new reservations; no AI DML privilege on rule facts.
    s.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": f"automation-budget:{run.tenant_id}:{occurrence.rule_id}"},
    )
    from .service_models import AutomationServiceAttempt as ServiceAttempt

    admitted_runs = (
        select(Occurrence.run_id)
        .where(Occurrence.rule_id == occurrence.rule_id)
        .union(
            select(ServiceAttempt.run_id).where(
                ServiceAttempt.rule_id == occurrence.rule_id, ServiceAttempt.state == "admitted"
            )
        )
    )
    used = s.execute(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (
                            AgentToolCall.cost_state == "reserved",
                            AgentToolCall.cost_reserved_micro_usd,
                        ),
                        else_=AgentToolCall.cost_charged_micro_usd,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            AgentToolCall.cost_state == "reserved",
                            AgentToolCall.input_token_reservation,
                        ),
                        else_=AgentToolCall.actual_input_tokens,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            AgentToolCall.cost_state == "reserved",
                            AgentToolCall.output_token_reservation,
                        ),
                        else_=AgentToolCall.actual_output_tokens,
                    )
                ),
                0,
            ),
            func.count(AgentToolCall.id),
        ).where(
            AgentToolCall.run_id.in_(admitted_runs),
            AgentToolCall.cost_state != "unmetered",
        )
    ).one()
    cost, inp, outp, _ = cost_lease
    if any(
        actual + extra > limit
        for actual, extra, limit in zip(
            used,
            (cost, inp, outp, 1),
            (
                spec.budget.limit_micro_usd,
                spec.budget.input_token_limit,
                spec.budget.output_token_limit,
                spec.budget.call_limit,
            ),
            strict=True,
        )
    ):
        raise DomainError("RATE_LIMITED", "本规则的累计费用、用量或调用次数已达上限。")


def admit(s, ctx, rule_id, data, ports):
    human(s, ctx)
    require_access(s, ctx, None, lock=True)
    s.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": f"automation-trigger:{ctx.tenant_id}:{ctx.requester_id}:{data.idempotency_key}"},
    )
    fingerprint = digest(
        {
            "category_id": ctx.category_id,
            "rule_id": rule_id,
            "request": data.model_dump(mode="json", exclude={"idempotency_key"}),
        }
    )
    prior = s.scalar(
        select(Occurrence).where(
            Occurrence.owner_id == ctx.requester_id, Occurrence.intent_key == data.idempotency_key
        )
    )
    pointer = owned(s, ctx, rule_id, lock=True)
    if prior:
        if prior.request_digest != fingerprint or prior.rule_id != rule_id:
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "原触发编号对应另一请求。")
        run = s.get(AgentRun, prior.run_id)
        if run is None:
            raise DomainError("FORBIDDEN_SCOPE", "原工作已不在当前可读范围。", 403)
        require_access(s, ctx, run.product_id)
        binding(s, run)
        return run, prior
    version = s.get(Version, pointer.published_version_id) if pointer.published_version_id else None
    if version is None:
        raise DomainError("VERSION_CONFLICT", "请先确认启用规则。")
    spec = AutomationSpec.model_validate(version.spec)
    if spec.trigger_kind != "manual":
        raise DomainError("FORBIDDEN_SCOPE", "自动规则由已授权服务受理，不能借用人工触发。", 403)
    at = now()
    validate_admission(
        {
            "state": pointer.state,
            "revision": pointer.revision,
            "published_version_id": pointer.published_version_id,
            "admitted_count": pointer.admitted_count,
            "last_admitted_at": pointer.last_admitted_at,
        },
        data,
        spec=spec,
        at=at,
    )
    spec_current(s, ctx, spec, enabled=True)
    taint = ports.binding_for(
        s, ctx, SimpleNamespace(product_id=spec.product_id, proposal_id=None, sources=[])
    )
    run = create_run(
        s,
        ctx,
        goal=spec.goal,
        writer_id=ports.writer_for(s, ctx),
        intent_key="automation:" + data.idempotency_key,
        product_id=spec.product_id,
        trigger=TRIGGER,
        private_context=taint.private_context,
        data_categories=taint.data_categories,
        customer_identities=taint.customer_identities,
        read_sources=taint.read_sources,
        outbound_context=getattr(taint, "outbound_context", None),
        validation_budget_id=spec.validation_budget_id,
        token_limit=spec.token_limit,
        request_digest=fingerprint,
    )
    at = now()
    occurrence = Occurrence(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        owner_id=ctx.requester_id,
        requester_id=ctx.requester_id,
        rule_id=rule_id,
        published_version_id=version.id,
        run_id=run.id,
        intent_key=data.idempotency_key,
        request_digest=fingerprint,
        created_at=at,
    )
    pointer.admitted_count += 1
    pointer.last_admitted_at = at
    s.add(occurrence)
    s.add(
        AgentEvent(
            tenant_id=ctx.tenant_id,
            run_id=run.id,
            sequence=1,
            body={"type": "accepted", "status": "queued"},
        )
    )
    s.flush()
    return run, occurrence
