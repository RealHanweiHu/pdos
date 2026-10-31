"""T0 ledger ports for the domain owner's existing Session; no commits or business DML.

The owner acquires its normal scope/object locks BEFORE calling prepare_domain_call.
It then supplies Context.agent_call_id to the common command and finishes in that
same UOW. Public Context/check_run/qualification integration remains a B7 owner task.
"""

from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import select

from pdos_next.database import require_context
from pdos_next.errors import DomainError
from pdos_next.models import Principal, Receipt
from pdos_next.service import Context, digest, receipt_view

from . import policy
from .bindings import DomainBinding, ModelBinding, SkillBinding, WriteSource, execution_key
from .disclosure import binding_operations, disclosed_in_run, disclosure
from .models import AgentEvent, AgentRun, AgentToolCall
from .qualification_binding import model_identity, tool_identity
from .types import RunScope


def scope_for_run(run):
    return RunScope(
        run.tenant_id,
        run.requester_id,
        run.writer_id,
        run.session_id,
        run.id,
        run.category_id,
        run.product_id,
        run.proposal_id,
        run.cancel_epoch,
        run.private_context,
        frozenset(run.data_categories),
        tuple(run.customer_identities),
        trigger=run.trigger,
        project_id=getattr(run, "project_id", None),
    )


def command_run(session, ctx, product_id):
    """The common command resolves its internal execution identity from stored rows."""
    run = session.scalar(
        select(AgentRun)
        .where(AgentRun.id == ctx.agent_run_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    actor = session.get(Principal, ctx.actor_id)
    if (
        not run
        or run.tenant_id != ctx.tenant_id
        or run.category_id != ctx.category_id
        or run.product_id != product_id
        or run.writer_id != ctx.actor_id
        or run.requester_id != ctx.requester_id
        or ctx.cancel_epoch != run.cancel_epoch
        or not ctx.agent_call_id
        or not actor
        or actor.kind != "agent"
    ):
        raise DomainError("FORBIDDEN_SCOPE", "命令未绑定实际小 Pai 运行和调用。", 403)
    check_run_binding(run, scope_for_run(run))
    from pdos_next.dingtalk.guards import read_only

    read_only(session, run)
    if run.trigger in {"automation_manual", "automation_service"}:
        raise DomainError("FORBIDDEN_SCOPE", "当前只读规则没有业务写入权限。", 403)
    if run.used_tokens > run.token_limit:
        raise DomainError("MODEL_BUDGET_EXCEEDED", "原运行用量已超出预算。")
    return run


def command_call(session, ctx, operation):
    call = session.scalar(
        select(AgentToolCall)
        .where(
            AgentToolCall.id == ctx.agent_call_id,
            AgentToolCall.run_id == ctx.agent_run_id,
        )
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    try:
        binding = DomainBinding.model_validate(call.execution_binding if call else None)
    except ValidationError:
        raise DomainError("FORBIDDEN_SCOPE", "命令缺少实际领域执行绑定。", 403) from None
    if (
        call.tenant_id != ctx.tenant_id
        or call.state != "started"
        or call.receipt_id is not None
        or binding.operation != operation
        or binding.cancel_epoch != ctx.cancel_epoch
    ):
        raise DomainError("FORBIDDEN_SCOPE", "命令不属于当前待执行的领域调用。", 403)
    return call, binding


def qualify_command(session, ctx, operation, run):
    call, binding = command_call(session, ctx, operation)
    owner = session.info.get("domain_command_owner")
    if owner is None:
        raise DomainError("SOURCE_UNAVAILABLE", "小 Pai 领域执行端口尚未配置。")
    scope = scope_for_run(run)
    model_call = session.get(AgentToolCall, binding.model_call_id)
    calls = model_call.result.get("calls", []) if model_call and model_call.result else []
    if binding.response_index >= len(calls):
        raise DomainError("FORBIDDEN_SCOPE", "执行索引不属于实际模型回复。", 403)
    original = calls[binding.response_index]
    spec = owner.registry.get(call.tool)
    source = WriteSource(
        skill=binding.skill,
        model_call_id=binding.model_call_id,
        response_index=binding.response_index,
    )
    actual_route = owner.route(session, scope)
    model, skill = verify_source(
        session,
        scope,
        run,
        spec,
        original.get("arguments"),
        source,
        catalog=owner.catalog,
        registry=owner.registry,
        route=actual_route,
    )
    if (
        spec.operation_key != operation
        or call.input_digest != digest([spec.name, original.get("arguments")])
        or binding.model_version != model.model_version
        or binding.model_route_digest != model.model_route_digest
        or binding.tool_definitions_digest != model.tool_definitions_digest
        or not policy.qualified(
            session,
            scope,
            skill,
            model.model_version,
            model_digest=model_identity(actual_route),
            tool_digest=tool_identity(skill, owner.registry),
            lock=True,
        )
    ):
        raise DomainError("QUALIFICATION_REQUIRED", "此技能与实际模型没有当前自动执行资格。", 403)


def check_command_digest(session, ctx, operation, actual_digest):
    _, binding = command_call(session, ctx, operation)
    if binding.command_digest != actual_digest:
        raise DomainError("DUPLICATE_INTENT_CONFLICT", "实际命令与领域执行绑定不同。")


def check_run_binding(run, scope, *, for_write=True):
    fields = (
        "tenant_id",
        "requester_id",
        "writer_id",
        "category_id",
        "product_id",
        "proposal_id",
        "session_id",
        "private_context",
    )
    if (
        not run
        or run.id != scope.run_id
        or any(getattr(run, key) != getattr(scope, key) for key in fields)
        or getattr(run, "project_id", None) != getattr(scope, "project_id", None)
    ):
        raise DomainError("FORBIDDEN_SCOPE", "调用不属于服务器实际运行。")
    if (
        frozenset(run.data_categories) != scope.data_categories
        or tuple(run.customer_identities) != scope.customer_identities
    ):
        raise DomainError("FORBIDDEN_SCOPE", "调用资料范围不属于实际运行。")
    if run.reverted_at or run.cancel_epoch != scope.cancel_epoch or run.state == "cancelled":
        raise DomainError("CANCELLED_RUN", "原运行已取消或撤回。")
    allowed = {"queued", "running", "waiting_input"}
    if not for_write:
        allowed |= {"completed", "partial", "failed"}
    if run.state not in allowed:
        raise DomainError("CANCELLED_RUN", "已结束运行不能开始新调用。")


def validate_skill_load(session, scope, binding):
    if not isinstance(binding, SkillBinding):
        raise DomainError("FORBIDDEN_SCOPE", "技能加载引用须来自服务器。")
    event = session.get(AgentEvent, binding.load_event_id)
    expected = {
        "type": "skill_loaded",
        "key": binding.key,
        "version": binding.version,
        "digest": binding.digest,
        "isolation": scope.isolation,
    }
    if (
        not event
        or event.tenant_id != scope.tenant_id
        or event.run_id != scope.run_id
        or event.body != expected
    ):
        raise DomainError("FORBIDDEN_SCOPE", "技能加载事实不属于实际运行。")


def validate_model_source(
    run, model_call, scope, source, spec, arguments, *, route, prepare_only=False
):
    """Pure comparison over actual rows supplied by the Session owner."""
    check_run_binding(run, scope)
    if not isinstance(source, WriteSource):
        raise DomainError("FORBIDDEN_SCOPE", "T0 来源须来自服务器执行账本。")
    if (
        spec.tier not in ({"T0", "T1"} if prepare_only else {"T0"})
        or spec.kind != "write"
        or not spec.operation_key
    ):
        raise DomainError("NAMED_DECISION_REQUIRED", "该工具没有 T0 执行权。")
    if scope.isolation != "main":
        raise DomainError("FORBIDDEN_SCOPE", "隔离子任务没有 T0 执行权。")
    if (
        not model_call
        or model_call.id != source.model_call_id
        or model_call.tenant_id != scope.tenant_id
        or model_call.run_id != run.id
        or model_call.tool != "model"
        or model_call.state != "completed"
    ):
        raise DomainError("FORBIDDEN_SCOPE", "模型结果不属于实际完成调用。")
    try:
        binding = ModelBinding.model_validate(model_call.execution_binding)
    except ValidationError:
        raise DomainError("SOURCE_UNAVAILABLE", "原模型调用没有可信来源绑定。") from None
    if binding.cancel_epoch != scope.cancel_epoch or binding.isolation != "main":
        raise DomainError("CANCELLED_RUN", "原模型调用 epoch 或隔离范围已失效。")
    if source.skill not in binding.loaded_skills:
        raise DomainError("FORBIDDEN_SCOPE", "模型输出未使用该版本技能上下文。")
    if (
        not route
        or binding.model_version != run.versions.get("model_version")
        or binding.model_route_digest != run.versions.get("model_route_digest")
        or binding.model_version != route.version
        or binding.model_route_digest != route.digest
        or not disclosed_in_run(run.versions, "main", binding.tool_definitions_digest)
        or binding.prompt_digest != run.versions.get("prompt_prefixes", {}).get("main")
    ):
        raise DomainError("VERSION_CONFLICT", "实际模型、工具或提示绑定已变化。")
    calls = model_call.result.get("calls", []) if isinstance(model_call.result, dict) else []
    if source.response_index >= len(calls):
        raise DomainError("FORBIDDEN_SCOPE", "模型结果索引不属于实际回复。")
    original = calls[source.response_index]
    if (
        not isinstance(original, dict)
        or original.get("name") != spec.name
        or digest([spec.name, original.get("arguments")]) != digest([spec.name, arguments])
    ):
        raise DomainError("DUPLICATE_INTENT_CONFLICT", "调用不等于实际模型结果索引。")
    return binding


def verify_source(
    session, scope, run, spec, arguments, source, *, catalog, registry, route, prepare_only=False
):
    if not isinstance(source, WriteSource):
        raise DomainError("FORBIDDEN_SCOPE", "T0 来源须来自服务器执行账本。")
    model_call = session.get(AgentToolCall, source.model_call_id)
    model = validate_model_source(
        run, model_call, scope, source, spec, arguments, route=route, prepare_only=prepare_only
    )
    validate_skill_load(session, scope, source.skill)
    skill = catalog.load(
        source.skill.key, scope, lambda _, s: policy.skill_enabled(session, scope, s)
    )
    if skill.version != source.skill.version or skill.digest != source.skill.digest:
        raise DomainError("VERSION_CONFLICT", "实际技能版本或内容已变化。")
    current = registry.get(spec.name)
    # The binding must match the disclosure its own loaded skills imply, so a write
    # is provably bound to a call that could actually see that command.
    disclosed = disclosure(
        registry, model.isolation, binding_operations(catalog, model.loaded_skills)
    )
    if (
        current != spec
        or current.tier not in ({"T0", "T1"} if prepare_only else {"T0"})
        or current.operation_key != spec.operation_key
        or spec.name not in skill.operations
        or digest(disclosed) != model.tool_definitions_digest
        or not any(item["name"] == spec.name for item in disclosed)
    ):
        raise DomainError("VERSION_CONFLICT", "实际登记工具或技能允许操作已变化。")
    return model, skill


def _check_session(session, scope):
    require_context(
        session,
        Context(
            scope.tenant_id,
            scope.writer_id,
            scope.requester_id,
            category_id=scope.category_id,
            agent_run_id=scope.run_id,
            cancel_epoch=scope.cancel_epoch,
        ),
    )
    if session.info.get("scope") != (
        scope.tenant_id,
        scope.writer_id,
        scope.requester_id,
        scope.category_id,
    ):
        raise DomainError("FORBIDDEN_SCOPE", "调用须使用实际服务器身份事务。")


def _locked_call(session, scope, source):
    _check_session(session, scope)
    run = session.scalar(
        select(AgentRun)
        .where(AgentRun.id == scope.run_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    check_run_binding(run, scope, for_write=False)
    if not isinstance(source, WriteSource):
        raise DomainError("FORBIDDEN_SCOPE", "执行来源须来自服务器账本。")
    key = execution_key(run.id, source.model_call_id, source.response_index)
    call = session.scalar(
        select(AgentToolCall)
        .where(
            AgentToolCall.tenant_id == scope.tenant_id,
            AgentToolCall.run_id == run.id,
            AgentToolCall.call_key == key,
        )
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    return run, call, key


def _check_completed_intent(call, scope, spec, arguments, source, command_digest):
    try:
        binding = DomainBinding.model_validate(call.execution_binding)
    except ValidationError:
        raise DomainError("SOURCE_UNAVAILABLE", "原执行没有可信绑定。") from None
    if (
        call.tenant_id != scope.tenant_id
        or call.run_id != scope.run_id
        or call.tool != spec.name
        or call.input_digest != digest([spec.name, arguments])
        or binding.skill != source.skill
        or binding.model_call_id != source.model_call_id
        or binding.response_index != source.response_index
        or binding.operation != spec.operation_key
        or binding.command_digest != command_digest
    ):
        raise DomainError("DUPLICATE_INTENT_CONFLICT", "原执行已绑定其他实质或版本。")


def recover_domain_call(session, scope, spec, arguments, source, *, command_digest, read_receipt):
    """Read an already completed intent; current read authority belongs to the owner.

    Returns (actual_call, prior_result), or None when no completed Call exists.
    No route, skill enablement, qualification, budget or business mutation is required.
    The owner ends a missed recovery UOW before taking new-write scope/object locks.
    """
    _, call, _ = _locked_call(session, scope, source)
    if not call or call.state != "completed":
        return None
    _check_completed_intent(call, scope, spec, arguments, source, command_digest)
    return call, finish_domain_call(
        session, scope, call.id, call.receipt_id, replay=True, read_receipt=read_receipt
    )


def prepare_domain_call(
    session,
    scope,
    spec,
    arguments,
    source,
    *,
    catalog,
    registry,
    route,
    command_digest,
    read_receipt=None,
):
    """Acquire a Call in the existing domain UOW; caller locks scope/object first.

    Returns (actual_call, prior_result). No source fields are deserialized from a
    model payload, and an unfinished local Call is never treated as an external send.
    """
    run, call, key = _locked_call(session, scope, source)
    if call and call.state == "completed":
        _check_completed_intent(call, scope, spec, arguments, source, command_digest)
        result = finish_domain_call(
            session, scope, call.id, call.receipt_id, replay=True, read_receipt=read_receipt
        )
        return call, result
    check_run_binding(run, scope)
    # Root supplies a Session callback which locks the actual configuration head here.
    # A route object is supported only when the caller already owns that configuration lock.
    actual_route = route(session, scope) if callable(route) else route
    model, skill = verify_source(
        session,
        scope,
        run,
        spec,
        arguments,
        source,
        catalog=catalog,
        registry=registry,
        route=actual_route,
    )
    binding = DomainBinding(
        **source.model_dump(),
        operation=spec.operation_key,
        model_version=model.model_version,
        model_route_digest=model.model_route_digest,
        tool_definitions_digest=model.tool_definitions_digest,
        cancel_epoch=scope.cancel_epoch,
        command_digest=command_digest,
    ).model_dump(mode="json")
    fingerprint = digest([spec.name, arguments])
    if call:
        if (
            call.tool != spec.name
            or call.input_digest != fingerprint
            or call.execution_binding != binding
        ):
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "原执行已绑定其他实质或版本。")
    if not policy.qualified(
        session,
        scope,
        skill,
        model.model_version,
        model_digest=model_identity(actual_route),
        tool_digest=tool_identity(skill, registry),
        lock=True,
    ):
        raise DomainError("QUALIFICATION_REQUIRED", "所选技能与实际模型尚无当前资格。")
    if call:
        # This path has no network side effect. Caller can retry the rolled-back UOW.
        if call.state != "started" or call.receipt_id is not None:
            raise DomainError("VERSION_CONFLICT", "原执行状态不能重新办理。")
    if call is None:
        call = AgentToolCall(
            id=uuid4(),
            tenant_id=scope.tenant_id,
            run_id=run.id,
            call_key=key,
            tool=spec.name,
            input_digest=fingerprint,
            execution_binding=binding,
        )
        session.add(call)
        session.flush()
    return call, None


def finish_domain_call(session, scope, call_id, receipt_id, *, replay=False, read_receipt=None):
    """Bind an actual newly authored Receipt and finish in the caller's same UOW."""
    _check_session(session, scope)
    run = session.scalar(
        select(AgentRun)
        .where(AgentRun.id == scope.run_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    check_run_binding(run, scope, for_write=not replay)
    call = session.scalar(
        select(AgentToolCall)
        .where(
            AgentToolCall.id == call_id,
            AgentToolCall.run_id == scope.run_id,
        )
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    receipt = session.get(Receipt, receipt_id) if receipt_id else None
    if not call or call.tenant_id != scope.tenant_id or call.run_id != scope.run_id:
        raise DomainError("FORBIDDEN_SCOPE", "调用不属于实际运行。")
    try:
        binding = DomainBinding.model_validate(call.execution_binding)
    except ValidationError:
        raise DomainError("FORBIDDEN_SCOPE", "调用缺少 T0 实际执行绑定。") from None
    if binding.cancel_epoch != scope.cancel_epoch:
        raise DomainError("CANCELLED_RUN", "执行 epoch 已失效。")
    if (
        not receipt
        or receipt.tenant_id != scope.tenant_id
        or receipt.category_id != scope.category_id
        or (scope.product_id is not None and receipt.product_id != scope.product_id)
        or receipt.actor_id != scope.writer_id
        or receipt.requester_id != scope.requester_id
        or receipt.agent_run_id != scope.run_id
        or receipt.run_id is not None
        or receipt.operation != binding.operation
        or receipt.request_digest != binding.command_digest
    ):
        raise DomainError("FORBIDDEN_SCOPE", "回执不属于该执行；不能重新挂接其他运行回执。")
    result = {**receipt_view(receipt), "agent_call_id": str(call.id)}
    if replay:
        if call.state != "completed" or call.receipt_id != receipt.id or call.result != result:
            raise DomainError("VERSION_CONFLICT", "原执行完成事实无法核对。")
        if not callable(read_receipt):
            raise DomainError("SOURCE_UNAVAILABLE", "原回执恢复尚未接入当前读取核对。")
        read_receipt(session, scope, receipt)
        return result
    if call.state != "started" or call.receipt_id is not None:
        raise DomainError("VERSION_CONFLICT", "原执行已经结束，不能改写。")
    call.receipt_id, call.result, call.state = receipt.id, result, "completed"
    session.flush()
    return result
