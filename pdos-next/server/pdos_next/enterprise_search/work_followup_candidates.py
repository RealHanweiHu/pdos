"""Narrow work.task.create adapter for the existing durable domain_candidate feed.

AgentEvents retain actual model provenance. The original work owner validates,
creates, assigns and owns business receipts; no candidate table or command is added.
"""

from copy import deepcopy
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import ValidationError
from sqlalchemy import func, select

from pdos_next.agent_kernel.bindings import ModelBinding, WriteSource, execution_key
from pdos_next.agent_kernel.execution import (
    check_run_binding,
    scope_for_run,
    validate_skill_load,
    verify_source,
)
from pdos_next.agent_kernel.models import AgentEvent, AgentRun, AgentToolCall
from pdos_next.contracts import Command, SourceRead
from pdos_next.database import require_context, tenant_session
from pdos_next.domain.work_management import owner as work_owner
from pdos_next.domain.work_management import service as work_service
from pdos_next.domain.work_management.schemas import TaskCreatePayload
from pdos_next.errors import DomainError
from pdos_next.models import Receipt, RequestKey
from pdos_next.service import Context, digest, receipt_view, require_access

from .action_sources import capture_work, recheck_work
from .work_followup_actions import KEY, OPERATION, SKILL, check_action

KIND = "work_followup"


def _deny():
    raise DomainError("FORBIDDEN_SCOPE", "资料跟进候选与真实运行、模型或原件无法核对。", 403)


def _source(session, run, intent_key):
    try:
        prefix, rid, label, identity, index = intent_key.split(":")
        identity, index = UUID(identity), int(index)
        if (
            prefix != "agent"
            or rid != str(run.id)
            or label != "model"
            or index < 0
            or intent_key != execution_key(run.id, identity, index)
        ):
            _deny()
        call = session.get(AgentToolCall, identity)
        binding = ModelBinding.model_validate(call.execution_binding)
        skill = next(value for value in binding.loaded_skills if value.key == SKILL)
        return WriteSource(skill=skill, model_call_id=identity, response_index=index)
    except (ValueError, AttributeError, StopIteration, ValidationError):
        _deny()


def _model(session, run, source, arguments):
    call = session.get(AgentToolCall, source.model_call_id)
    if (
        call is None
        or call.tenant_id != run.tenant_id
        or call.run_id != run.id
        or call.tool != "model"
        or call.state != "completed"
        or call.error_code is not None
    ):
        _deny()
    binding = ModelBinding.model_validate(call.execution_binding)
    if (
        binding.isolation != "main"
        or binding.cancel_epoch != run.cancel_epoch
        or source.skill.key != SKILL
        or source.skill not in binding.loaded_skills
    ):
        _deny()
    try:
        actual = call.result["calls"][source.response_index]
        if actual["name"] != OPERATION or digest(actual["arguments"]) != digest(arguments):
            _deny()
    except (KeyError, TypeError, IndexError):
        _deny()
    return digest(call.execution_binding)


def _run(session, ctx, run, *, creating=False):
    require_context(session, ctx)
    if (
        ctx.actor_id != ctx.requester_id
        or ctx.agent_run_id
        or ctx.run_id
        or run.tenant_id != ctx.tenant_id
        or run.requester_id != ctx.requester_id
        or run.category_id != ctx.category_id
        or run.product_id is None
        or run.project_id is None
        or run.trigger != "conversation"
    ):
        _deny()
    check_run_binding(run, scope_for_run(run), for_write=creating)
    return run


def prepare(owner, scope, spec, arguments, intent_key):
    if spec.name != OPERATION or spec.tier != "T0" or scope.isolation != "main":
        _deny()
    with tenant_session(
        owner.engine,
        scope.tenant_id,
        actor_id=scope.requester_id,
        requester_id=scope.requester_id,
        category_id=scope.category_id,
    ) as session:
        run = session.get(AgentRun, scope.run_id, with_for_update=True)
        check_run_binding(run, scope)
        action = run.versions.get(KEY)
        if action is None:
            return None
        ctx = Context(
            scope.tenant_id, scope.requester_id, scope.requester_id, category_id=scope.category_id
        )
        _run(session, ctx, run, creating=True)
        check_action(session, ctx, run, action)
        source = _source(session, run, intent_key)
        verify_source(
            session,
            scope,
            run,
            spec,
            arguments,
            source,
            catalog=owner.catalog,
            registry=owner.registry,
            route=owner.route(session, scope),
            prepare_only=True,
        )
        binding_digest = _model(session, run, source, arguments)
        try:
            payload = TaskCreatePayload.model_validate(arguments)
        except ValidationError:
            raise DomainError(
                "INVALID_PAYLOAD", "任务草稿缺少原生必填字段，请保留缺项并向本人询问。", 422,
            ) from None
        if (
            payload.project_id != run.project_id
            or payload.g0_open_item is not None
            or payload.plan_task is not None
            or payload.npi_template is not None
        ):
            _deny()
        proof = capture_work(
            session, ctx, run, action["citation_ids"], execution_references=payload.sources
        )
        product = require_access(session, ctx, run.product_id, write=True)
        command = Command(
            command_id=uuid5(NAMESPACE_URL, intent_key),
            idempotency_key=str(uuid5(NAMESPACE_URL, "pdos:work-followup:" + intent_key)),
            operation=OPERATION,
            category_id=run.category_id,
            product_id=run.product_id,
            expected_revision=product.revision,
            source_read_set=[SourceRead.model_validate(value) for value in proof["read_set"]],
            payload=payload.model_dump(mode="json"),
        )
        # Use the same native Human inputs contract as the project work screen.
        work_service.inputs(session, ctx, run.product_id, command)
        previous = session.scalar(
            select(AgentEvent).where(
                AgentEvent.run_id == run.id,
                AgentEvent.body["type"].astext == "domain_candidate",
                AgentEvent.body["intent_key"].astext == intent_key,
            )
        )
        if previous is not None:
            if previous.body.get("arguments") != arguments:
                raise DomainError("DUPLICATE_INTENT_CONFLICT", "原任务候选内容已变化。")
            value = read(session, ctx, run, previous)
        else:
            body = {
                "type": "domain_candidate",
                "kind": KIND,
                "version": 1,
                "intent_key": intent_key,
                "cancel_epoch": run.cancel_epoch,
                "command": command.model_dump(mode="json"),
                "arguments": deepcopy(arguments),
                "source": source.model_dump(mode="json"),
                "model_binding_digest": binding_digest,
                "source_proof": proof,
            }
            event = AgentEvent(
                id=uuid4(),
                tenant_id=run.tenant_id,
                run_id=run.id,
                sequence=session.scalar(
                    select(func.coalesce(func.max(AgentEvent.sequence), 0)).where(
                        AgentEvent.run_id == run.id
                    )
                )
                + 1,
                body={**body, "digest": digest(body)},
            )
            session.add(event)
            session.flush()
            value = read(session, ctx, run, event)
        return {
            "event_id": value["event_id"],
            "command": value["command"],
            "requires_human": True,
            "write_tier": "T1",
            "operation_tier": "T0",
            "state": "candidate",
            "next_action": "confirm_human_command",
        }


def read(session, ctx, run, event):
    _run(session, ctx, run)
    body = event.body
    if (
        event.tenant_id != run.tenant_id
        or event.run_id != run.id
        or body.get("type") != "domain_candidate"
        or body.get("kind") != KIND
        or body.get("version") != 1
        or body.get("cancel_epoch") != run.cancel_epoch
        or body.get("digest") != digest({k: v for k, v in body.items() if k != "digest"})
    ):
        _deny()
    command = Command.model_validate(body["command"])
    payload = TaskCreatePayload.model_validate(command.payload)
    source = WriteSource.model_validate(body["source"])
    validate_skill_load(session, scope_for_run(run), source.skill)
    if (
        command.operation != OPERATION
        or command.category_id != run.category_id
        or command.product_id != run.product_id
        or payload.project_id != run.project_id
        or body["intent_key"]
        != execution_key(
            run.id,
            source.model_call_id,
            source.response_index,
        )
        or command.command_id != uuid5(NAMESPACE_URL, body["intent_key"])
        or command.idempotency_key
        != str(
            uuid5(
                NAMESPACE_URL,
                "pdos:work-followup:" + body["intent_key"],
            )
        )
        or payload.model_dump(mode="json")
        != TaskCreatePayload.model_validate(body["arguments"]).model_dump(mode="json")
        or body["model_binding_digest"] != _model(session, run, source, body["arguments"])
    ):
        _deny()
    check_action(session, ctx, run, run.versions.get(KEY))
    proof = recheck_work(session, ctx, run, body["source_proof"])
    if command.source_read_set != [SourceRead.model_validate(value) for value in proof["read_set"]]:
        _deny()
    return {
        "event_id": str(event.id),
        "command": command.model_dump(mode="json"),
        "source_proof": proof,
    }


def item(session, ctx, run, event):
    result = {
        "event_id": str(event.id),
        "sequence": event.sequence,
        "kind": KIND,
        "operation": OPERATION,
        "command_id": None,
        "idempotency_key": None,
        "state": "unavailable",
        "command": None,
        "receipt": None,
        "task": None,
        "assignment": None,
    }
    if (
        run.reverted_at
        or run.state == "cancelled"
        or event.body.get("cancel_epoch") != run.cancel_epoch
    ):
        return {**result, "state": "cancelled"}
    try:
        value = read(session, ctx, run, event)
        command = Command.model_validate(value["command"])
        key = session.scalar(
            select(RequestKey).where(
                RequestKey.tenant_id == ctx.tenant_id,
                RequestKey.actor_id == ctx.requester_id,
                RequestKey.key == command.idempotency_key,
            )
        )
        receipt = session.get(Receipt, key.receipt_id) if key else None
        task = None
        if key is not None:
            if (
                receipt is None
                or receipt.command_id != command.command_id
                or receipt.requester_id != ctx.requester_id
                or receipt.actor_id != ctx.requester_id
                or receipt.operation != OPERATION
                or receipt.category_id != run.category_id
                or receipt.product_id != run.product_id
                or receipt.subject_type != "work_task"
            ):
                return result
            row, snapshot, _pointer = work_owner.task(
                session,
                ctx,
                run.product_id,
                receipt.subject_id,
            )
            task = {
                "id": str(row.task_id),
                "revision": row.revision,
                "title": snapshot.title,
                "state": snapshot.state,
            }
        result.update(
            command_id=str(command.command_id),
            idempotency_key=command.idempotency_key,
            command=value["command"],
            state="adopted" if receipt else "pending",
            receipt=receipt_view(receipt) if receipt else None,
            task=task,
            assignment=deepcopy(run.versions[KEY].get("assignment")),
        )
    except (DomainError, KeyError, TypeError, ValueError, ValidationError):
        pass
    return result


def check_command(session, ctx, command):
    """Recheck this adapter's frozen command inside the original native owner UOW.

    Ordinary Human work commands have no AgentEvent and keep their own contract.
    An existing server candidate cannot be replayed after cancel/source loss.
    """
    event = session.scalar(
        select(AgentEvent).where(
            AgentEvent.tenant_id == ctx.tenant_id,
            AgentEvent.body["type"].astext == "domain_candidate",
            AgentEvent.body["kind"].astext == KIND,
            AgentEvent.body["command"]["command_id"].astext == str(command.command_id),
        )
    )
    if event is None:
        return
    run = session.get(AgentRun, event.run_id, with_for_update=True)
    value = read(session, ctx, run, event)
    if Command.model_validate(value["command"]) != command:
        _deny()
