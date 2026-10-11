"""Actual AI Claim candidate, one Human T1 confirmation, retained AI writer and Run."""

from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import func, select

from pdos_next.errors import DomainError
from pdos_next.models import Claim, Principal
from pdos_next.request_proof import command_inputs_once
from pdos_next.service import digest, source_for

from .bindings import ModelBinding, WriteSource, execution_key
from .execution import verify_source
from .models import AgentEvent, AgentRun, AgentToolCall


def content(payload):
    return payload.model_dump(mode="json", exclude={"confirmation_token", "prepared_event_id"})


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"confirmation_token"})


def supports_confirmation(command):
    return command.payload.get("prepared_event_id") is not None


def needs_confirmation(payload):
    return payload.prepared_event_id is not None


def prepare(session, scope, spec, arguments, intent_key, bootstrap):
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
        model_call = session.get(AgentToolCall, model_id)
        binding = ModelBinding.model_validate(model_call.execution_binding)
    except (ValueError, AttributeError, ValidationError):
        raise DomainError("FORBIDDEN_SCOPE", "候选须绑定实际模型回复。", 403) from None
    run = session.scalar(select(AgentRun).where(AgentRun.id == scope.run_id).with_for_update())
    matching = [
        skill
        for skill in binding.loaded_skills
        if spec.name in bootstrap.catalog._skills[skill.key].operations
    ]
    if not matching:
        raise DomainError("FORBIDDEN_SCOPE", "原模型回复没有加载对应技能。", 403)
    source = WriteSource(skill=matching[0], model_call_id=model_id, response_index=index)
    verify_source(
        session,
        scope,
        run,
        spec,
        arguments,
        source,
        catalog=bootstrap.catalog,
        registry=bootstrap.registry,
        route=bootstrap.route(session, scope),
        prepare_only=True,
    )
    command = bootstrap.commands.command(session, scope, spec.name, arguments, intent_key)
    if command.payload.get("prepared_event_id") or command.payload.get("confirmation_token"):
        raise DomainError("FORBIDDEN_SCOPE", "候选身份和确认由服务器办理。", 403)
    events = session.scalars(select(AgentEvent).where(AgentEvent.run_id == run.id)).all()
    previous = next(
        (
            event
            for event in events
            if event.body.get("type") == "claim_candidate"
            and event.body.get("intent_key") == intent_key
        ),
        None,
    )
    if previous is None:
        identity = uuid4()
        command.payload["prepared_event_id"] = identity
        body = {
            "type": "claim_candidate",
            "intent_key": intent_key,
            "command": command.model_dump(mode="json"),
            "cancel_epoch": run.cancel_epoch,
            "source": source.model_dump(mode="json"),
            "model_binding": binding.model_dump(mode="json"),
        }
        previous = AgentEvent(
            id=identity,
            tenant_id=scope.tenant_id,
            run_id=run.id,
            sequence=session.scalar(
                select(func.coalesce(func.max(AgentEvent.sequence), 0)).where(
                    AgentEvent.run_id == run.id
                )
            )
            + 1,
            body=body,
        )
        session.add(previous)
        session.flush()
    return {
        "command": previous.body["command"],
        "requires_human": True,
        "write_tier": "T1",
        "state": "candidate",
        "event_id": str(previous.id),
    }


@command_inputs_once
def prepared(session, ctx, command, scope, payload):
    from pdos_next.contracts import ClaimPayload

    if command.expected_revision != scope.revision:
        raise DomainError("VERSION_CONFLICT", "当前型号版本已变化。")
    source = source_for(session, ctx, scope.id, payload.artifact_id)
    reads = {read.artifact_id: read.expected_revision for read in command.source_read_set}
    if reads.get(source.id) != source.revision:
        raise DomainError("MISSING_REQUIRED_EVIDENCE", "须引用当前原文的明确版本。")
    lines = source.content.splitlines()
    if payload.line > len(lines) or payload.quote not in lines[payload.line - 1]:
        raise DomainError("MISSING_REQUIRED_EVIDENCE", "引用须定位到原文行。")
    if source.visibility != "category" and payload.visibility == "category":
        raise DomainError("FORBIDDEN_SCOPE", "不能扩大来源受众。", 403)
    if payload.prepared_event_id is None:
        return source, None
    actor = session.get(Principal, ctx.actor_id)
    event = session.get(AgentEvent, payload.prepared_event_id)
    run = session.scalar(
        select(AgentRun)
        .where(AgentRun.id == event.run_id if event else AgentRun.id.is_(None))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        actor.kind != "human"
        or ctx.actor_id != ctx.requester_id
        or ctx.run_id
        or ctx.agent_run_id
        or not event
        or not run
        or event.body.get("type") != "claim_candidate"
        or run.tenant_id != ctx.tenant_id
        or run.category_id != ctx.category_id
        or run.product_id != scope.id
        or run.requester_id != ctx.requester_id
        or run.cancel_epoch != event.body.get("cancel_epoch")
        or run.reverted_at
        or run.state == "cancelled"
    ):
        raise DomainError("FORBIDDEN_SCOPE", "候选不属于本人、当前范围或有效运行。", 403)
    actual = event.body["command"]
    original = ClaimPayload.model_validate(actual["payload"])
    if (
        actual["operation"] != command.operation
        or content(original) != content(payload)
        or digest(actual["source_read_set"])
        != digest([read.model_dump(mode="json") for read in command.source_read_set])
    ):
        raise DomainError("DUPLICATE_INTENT_CONFLICT", "原候选已绑定不同的内容或来源。")
    writer = session.get(Principal, run.writer_id)
    if not writer or not writer.active or writer.kind != "agent" or payload.nature == "observed":
        raise DomainError("FORBIDDEN_SCOPE", "原 AI 署名不可用，或试图冒充亲历事实。", 403)
    return source, run


def validate(session, ctx, command, scope, payload):
    prepared(session, ctx, command, scope, payload)


def preview_view(session, ctx, command, scope, payload):
    _, run = prepared(session, ctx, command, scope, payload)
    return {
        "claim": content(payload),
        "origin": "ai_draft" if run else "human",
        "prepared_by_run_id": str(run.id) if run else None,
        "effect": "确认登记此来源事实，保留原 AI 署名、运行与依据。",
    }


def apply(session, ctx, command, scope, payload):
    source, run = prepared(session, ctx, command, scope, payload)
    row = Claim(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        product_id=scope.id,
        **content(payload),
        source_revision=source.revision,
        human_owner_id=ctx.requester_id,
        writer_id=run.writer_id if run else ctx.actor_id,
    )
    if run:
        row.prepared_by_run_id = run.id
        row.action_result = {
            "origin": "ai_draft",
            "writer_id": str(run.writer_id),
            "confirmed_by": str(ctx.actor_id),
            "prepared_event_id": str(payload.prepared_event_id),
        }
    return row, "claim", payload.visibility


def finalize_receipt(session, ctx, command, scope, payload, subject, receipt):
    if payload.prepared_event_id is None:
        return
    run_id = subject.prepared_by_run_id
    sequence = (
        session.scalar(
            select(func.coalesce(func.max(AgentEvent.sequence), 0)).where(
                AgentEvent.run_id == run_id
            )
        )
        + 1
    )
    session.add(
        AgentEvent(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            run_id=run_id,
            sequence=sequence,
            body={
                "type": "claim_candidate_adopted",
                "prepared_event_id": str(payload.prepared_event_id),
                "receipt_id": str(receipt.id),
            },
        )
    )
    session.flush()
