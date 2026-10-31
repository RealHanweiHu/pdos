"""Verified one-message admission to the original 小Pai Run and native pending dispatcher."""

from uuid import uuid4

from sqlalchemy import select, text

from pdos_next.agent_kernel.api import StartInput, reference
from pdos_next.agent_kernel.models import AgentEvent
from pdos_next.agent_kernel.persistence import create_run
from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.models import Principal
from pdos_next.service import Context, digest

from .accounts import credential
from .models import Application, Binding, Message
from .ports import SingleMessage


def locate(auth_engine, application_id):
    # Dedicated auth role sees only exact active application service/tenant UUIDs.
    with auth_engine.connect() as connection:
        row = (
            connection.execute(
                text("SELECT * FROM dingtalk_callback_application(:app)"), {"app": application_id}
            )
            .mappings()
            .one_or_none()
        )
    if not row:
        raise DomainError("SOURCE_UNAVAILABLE", "钉钉应用不可用。")
    return Context(row["tenant_id"], row["service_principal_id"], row["service_principal_id"])


def verify(engine, service_ctx, application_id, runtime, body, signature, timestamp):
    with tenant_session(
        engine,
        service_ctx.tenant_id,
        actor_id=service_ctx.actor_id,
        requester_id=service_ctx.requester_id,
        read_snapshot=True,
    ) as session:
        app = session.get(Application, application_id)
        if not app or app.service_principal_id != service_ctx.actor_id:
            raise DomainError("FORBIDDEN_SCOPE", "应用验证身份不匹配。", 403)
        return runtime.adapter.verify_message(
            app, credential(runtime, app), body, signature=signature, timestamp=timestamp
        )


def resolve_sender(engine, service_ctx, event):
    if not isinstance(event, SingleMessage):
        raise DomainError("FORBIDDEN_SCOPE", "入站事件未经适配器验证。", 403)
    if event.conversation_kind == "group" and not event.mentioned:
        return None
    with tenant_session(
        engine,
        service_ctx.tenant_id,
        actor_id=service_ctx.actor_id,
        requester_id=service_ctx.requester_id,
        read_snapshot=True,
    ) as session:
        app = session.get(Application, event.application_id)
        if (
            not app
            or not app.active
            or app.service_principal_id != service_ctx.actor_id
            or app.corp_id != event.corp_id
        ):
            raise DomainError("FORBIDDEN_SCOPE", "入站消息不属于当前应用。", 403)
        binding = session.scalar(
            select(Binding).where(
                Binding.application_id == app.id,
                Binding.external_user_id == event.external_user_id,
                Binding.active.is_(True),
            )
        )
        if not binding:
            return None  # No Run, content reply, model, source access or synthetic PDOS account.
        person = session.get(Principal, binding.owner_id)
        if not person or not person.active or person.kind != "human":
            return None
        return Context(service_ctx.tenant_id, person.id, person.id)


def admit(session, ctx, event, bootstrap):
    if not isinstance(event, SingleMessage):
        raise DomainError("FORBIDDEN_SCOPE", "消息身份未经验证。", 403)
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": f"dingtalk-message:{event.application_id}:{event.message_id}"},
    )
    old = session.scalar(
        select(Message).where(
            Message.application_id == event.application_id,
            Message.external_message_id == event.message_id,
        )
    )
    if old:
        if old.envelope_sha256 != event.envelope_sha256 or old.owner_id != ctx.actor_id:
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "重复入站编号对应不同消息。")
        return old
    app = session.get(Application, event.application_id)
    binding = session.scalar(
        select(Binding)
        .where(
            Binding.application_id == event.application_id,
            Binding.owner_id == ctx.actor_id,
            Binding.external_user_id == event.external_user_id,
            Binding.active.is_(True),
        )
        .with_for_update()
    )
    if (
        not app
        or not app.active
        or not binding
        or app.corp_id != event.corp_id
        or ctx.actor_id != ctx.requester_id
        or ctx.category_id is not None
        or event.conversation_kind == "group"
        and not event.mentioned
    ):
        raise DomainError("FORBIDDEN_SCOPE", "入站本人绑定已失效。", 403)
    key = "dingtalk:" + digest([app.id, event.message_id])
    data = StartInput(goal=event.text, idempotency_key=key)
    bound = bootstrap.binding_for(session, ctx, data)
    row = create_run(
        session,
        ctx,
        goal=data.goal,
        writer_id=bootstrap.writer_for(session, ctx),
        intent_key=key,
        private_context=True,
        data_categories=bound.data_categories,
        customer_identities=bound.customer_identities,
        read_sources=bound.read_sources,
        token_limit=bound.token_limit,
        validation_budget_id=bound.validation_budget_id,
        request_digest=digest([app.id, event.message_id, event.envelope_sha256]),
    )
    from pdos_next.agent_kernel.search_preferences import configure_start
    from pdos_next.enterprise_search.assistant_depth import starting_profile

    row.versions = {
        **row.versions,
        "assistant_depth": starting_profile(None, None),
        "dingtalk": {"version": 1},
    }
    configure_start(session, ctx, row, None)
    from pdos_next.agent_kernel.context_corrections import configure_start as configure_context

    configure_context(session, ctx, row, data, data, None)
    session.add(
        AgentEvent(
            tenant_id=ctx.tenant_id,
            run_id=row.id,
            sequence=1,
            body={"type": "accepted", "status": "queued", "channel": "dingtalk"},
        )
    )
    message = Message(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        application_id=app.id,
        binding_id=binding.id,
        binding_epoch=binding.epoch,
        owner_id=ctx.actor_id,
        external_message_id=event.message_id,
        envelope_sha256=event.envelope_sha256,
        conversation_kind=event.conversation_kind,
        conversation_id=event.conversation_id,
        run_id=row.id,
        state="pending",
    )
    session.add(message)
    session.flush()
    # Commit is the outbox boundary. Existing kernel_pending_run_references recovers
    # this exact Run if starting the original XiaopaiWork loses its response.
    return message


def native_reference(run):
    return reference(run, Context(run.tenant_id, run.requester_id, run.requester_id))
