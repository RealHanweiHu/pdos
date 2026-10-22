"""M3 admission ports over M2's actual model/tool ledger; no model-supplied authority."""

from pydantic import ValidationError
from sqlalchemy import select

from pdos_next.agent_kernel.execution import (
    verify_source,
)
from pdos_next.agent_kernel.models import AgentRun, AgentToolCall
from pdos_next.models import Principal
from pdos_next.service import digest

from .access import fail, human
from .models import PreparedCandidate

CONTENT_OPERATIONS = frozenset(
    {
        "platform.link.create",
        "proposal.create",
        "proposal.item.patch",
        "product.definition.item.patch",
        "proposal.question.create",
        "category.knowledge.add",
        "category.knowledge.withdraw",
        "category.knowledge.promote",
        "category.parameter.publish",
    }
)


def _scope_matches(payload, proposal_id):
    if hasattr(payload, "proposal_id") and payload.proposal_id != proposal_id:
        return False
    if hasattr(payload, "source_proposal_id") and payload.source_proposal_id != proposal_id:
        return False
    return True


def content(payload):
    from pdos_next.schemas.products.definition_items import DefinitionItemPatch

    data = (
        payload.model_dump(mode="json", exclude_unset=isinstance(payload, DefinitionItemPatch))
        if hasattr(payload, "model_dump")
        else dict(payload)
    )
    return {
        key: value
        for key, value in data.items()
        if key not in {"confirmation_token", "prepared_by_run_id", "candidate_digest"}
    }


def prepare_candidate(s, scope, operation, arguments, source, *, catalog, registry, route):
    """Trusted host port. The candidate must equal one actual completed model response."""
    from pdos_next.agent_kernel.execution import _check_session
    from pdos_next.contracts import PAYLOADS

    _check_session(s, scope)
    if operation not in CONTENT_OPERATIONS:
        fail("NAMED_DECISION_REQUIRED", "prepare_only", "此入口不能准备或执行 G0 决定。", 403)
    run = s.scalar(select(AgentRun).where(AgentRun.id == scope.run_id).with_for_update())
    actual_route = route(s, scope) if callable(route) else route
    model, _skill = verify_source(
        s,
        scope,
        run,
        registry.get(operation),
        arguments,
        source,
        catalog=catalog,
        registry=registry,
        route=actual_route,
        prepare_only=True,
    )
    payload = PAYLOADS[operation].model_validate(arguments)
    if payload.prepared_by_run_id or payload.candidate_digest or payload.confirmation_token:
        fail("FORBIDDEN_SCOPE", "server_candidate_binding", "候选身份与摘要由服务器绑定。", 403)
    product_patch = operation in {"product.definition.item.patch", "platform.link.create"}
    if operation == "platform.link.create" and payload.product_id != scope.product_id:
        fail("FORBIDDEN_SCOPE", "product_run_mismatch", "平台关联不属于运行绑定的型号。", 403)
    if (product_patch and (scope.product_id is None or scope.proposal_id is not None)) or (
        not product_patch
        and (scope.product_id is not None or not _scope_matches(payload, scope.proposal_id))
    ):
        fail("FORBIDDEN_SCOPE", "proposal_run_mismatch", "候选不属于运行绑定提案。", 403)
    body = content(payload)
    fingerprint = digest(
        [operation, scope.tenant_id, scope.category_id, scope.requester_id, scope.run_id, body]
    )
    row = s.scalar(
        select(PreparedCandidate).where(
            PreparedCandidate.tenant_id == scope.tenant_id,
            PreparedCandidate.run_id == run.id,
            PreparedCandidate.candidate_digest == fingerprint,
        )
    )
    if row is None:
        row = PreparedCandidate(
            tenant_id=scope.tenant_id,
            category_id=scope.category_id,
            requester_id=scope.requester_id,
            writer_id=scope.writer_id,
            run_id=run.id,
            operation=operation,
            candidate_digest=fingerprint,
            payload=body,
            execution_binding={
                **source.model_dump(mode="json"),
                "model": model.model_dump(mode="json"),
            },
        )
        s.add(row)
        s.flush()
    return {**body, "prepared_by_run_id": str(run.id), "candidate_digest": fingerprint}


def prepare_from_intent(s, scope, operation, arguments, intent_key, *, catalog, registry, route):
    """The registered host receives the graph's server key, never a model identity."""
    from uuid import UUID

    from pdos_next.agent_kernel import policy
    from pdos_next.agent_kernel.bindings import ModelBinding, WriteSource, execution_key

    try:
        prefix, run_id, kind, model_id, index = intent_key.split(":")
        model_id, index = UUID(model_id), int(index)
        if (
            prefix != "agent"
            or kind != "model"
            or run_id != str(scope.run_id)
            or index < 0
            or intent_key != execution_key(scope.run_id, model_id, index)
        ):
            raise ValueError
    except (ValueError, AttributeError):
        fail("FORBIDDEN_SCOPE", "server_candidate_binding", "候选须绑定服务器实际模型调用。", 403)
    call = s.get(AgentToolCall, model_id)
    if not call or call.tenant_id != scope.tenant_id or call.run_id != scope.run_id:
        fail("FORBIDDEN_SCOPE", "server_candidate_binding", "候选没有实际模型调用。", 403)
    try:
        binding = ModelBinding.model_validate(call.execution_binding)
    except ValidationError:
        fail("SOURCE_UNAVAILABLE", "model_source_invalid", "原模型调用没有可信来源绑定。")
    for skill_binding in binding.loaded_skills:
        skill = catalog.load(
            skill_binding.key, scope, lambda _, value: policy.skill_enabled(s, scope, value)
        )
        if operation in skill.operations:
            return prepare_candidate(
                s,
                scope,
                operation,
                arguments,
                WriteSource(skill=skill_binding, model_call_id=model_id, response_index=index),
                catalog=catalog,
                registry=registry,
                route=route,
            )
    fail("FORBIDDEN_SCOPE", "server_candidate_binding", "原模型输出没有加载对应技能。", 403)


def _t0(s, ctx, command, payload):
    # The one common command path has already checked the current model, actual
    # call, qualification and command digest. Resolve provenance from that ledger.
    from pdos_next.agent_kernel.execution import command_call, command_run

    run = command_run(s, ctx, None)
    command_call(s, ctx, command.operation)
    if command.operation not in {
        "proposal.item.patch",
        "category.knowledge.add",
    } or not _scope_matches(payload, run.proposal_id):
        fail("FORBIDDEN_SCOPE", "proposal_run_mismatch", "写入不属于运行绑定的提案。", 403)
    return {
        "origin": "ai_draft",
        "writer_id": run.writer_id,
        "run_id": run.id,
        "confirmed_by": None,
        "prepared_candidate_id": None,
    }


def writing_path(s, ctx, command, payload):
    if ctx.agent_run_id:
        return _t0(s, ctx, command, payload)
    human(s, ctx)
    if not getattr(payload, "prepared_by_run_id", None):
        return {
            "origin": "human",
            "writer_id": ctx.actor_id,
            "run_id": None,
            "confirmed_by": None,
            "prepared_candidate_id": None,
        }
    run = s.scalar(
        select(AgentRun).where(AgentRun.id == payload.prepared_by_run_id).with_for_update()
    )
    candidate = s.scalar(
        select(PreparedCandidate).where(
            PreparedCandidate.tenant_id == ctx.tenant_id,
            PreparedCandidate.run_id == payload.prepared_by_run_id,
            PreparedCandidate.candidate_digest == payload.candidate_digest,
        )
    )
    if (
        not run
        or not candidate
        or run.category_id != ctx.category_id
        or run.requester_id != ctx.requester_id
        or run.product_id
        != (command.product_id if command.operation == "platform.link.create" else None)
        or (command.operation == "platform.link.create" and run.proposal_id is not None)
        or run.reverted_at
        or run.state == "cancelled"
        or candidate.execution_binding["model"]["cancel_epoch"] != run.cancel_epoch
        or candidate.operation != command.operation
        or candidate.payload != content(payload)
        or not _scope_matches(payload, run.proposal_id)
    ):
        fail(
            "FORBIDDEN_SCOPE", "candidate_binding_invalid", "候选不属于本人、本品类或原运行。", 403
        )
    writer = s.get(Principal, run.writer_id)
    if not writer or not writer.active or writer.kind != "agent":
        fail("FORBIDDEN_SCOPE", "candidate_writer_invalid", "原候选署名不可用。", 403)
    return {
        "origin": "ai_draft",
        "writer_id": run.writer_id,
        "run_id": run.id,
        "confirmed_by": ctx.requester_id,
        "prepared_candidate_id": candidate.id,
    }
