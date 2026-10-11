"""One committed lifecycle attempt followed by observation; never implicit effect retry."""

import os
from contextlib import contextmanager
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import select

from pdos_next.contracts import Command
from pdos_next.database import category_for_product, tenant_session
from pdos_next.dispatch.context import event_context
from pdos_next.domain.original_lifecycle_execution.codec import decode_intent
from pdos_next.domain.original_lifecycle_execution.runtime import LifecycleRuntime
from pdos_next.domain.original_lifecycle_execution.service import runtime_for
from pdos_next.errors import DomainError
from pdos_next.lifecycle_access import References, product_gate, read_facts, resolve_reference
from pdos_next.models import Grant, LifecycleIntentRecord, Principal, now
from pdos_next.original_lifecycle.rules import digest
from pdos_next.original_lifecycle.types import (
    ActorKind,
    CurrentAuthorization,
    EffectOutcome,
    EffectReceipt,
    IntentState,
    LifecycleFailure,
    LifecycleScope,
    RetentionPolicy,
)
from pdos_next.service import Context, append_receipt

_WORKER = object()


def authorize_service(s, ctx, product_id, reference, action, timestamp, decision):
    if s.info.get("lifecycle_worker") is not _WORKER:
        raise LifecycleFailure("WORKER_AUTHORITY_REQUIRED", "需要当前受控工作器。")
    product_gate(s, ctx, product_id)
    if decision.named_decider_id != ctx.requester_id:
        raise LifecycleFailure("FORBIDDEN_SCOPE", "具名决定身份不符。")
    principal = s.get(Principal, ctx.requester_id)
    grant = s.scalar(
        select(Grant).where(
            Grant.category_id == ctx.category_id,
            Grant.principal_id == ctx.requester_id,
        )
    )
    revision = digest(
        [
            principal.id,
            principal.access_epoch,
            grant.id,
            grant.access_epoch,
            grant.can_write,
            grant.expires_at,
        ]
    )
    return CurrentAuthorization(
        reference,
        LifecycleScope(ctx.tenant_id, product_id, ctx.category_id if product_id is None else None),
        ctx.actor_id,
        ActorKind.SERVICE,
        action,
        revision,
        min(grant.expires_at, timestamp + timedelta(minutes=5))
        if grant.expires_at
        else timestamp + timedelta(minutes=5),
        decision.named_decider_id,
        decision.id,
    )


def transition(s, ctx, before, after, original):
    row = s.get(LifecycleIntentRecord, after.id)
    row.status = after.state.value
    row.action_result = {
        "action": after.action.value,
        "state": after.state.value,
        "object_id": str(original.reference.id),
        "disposition": original.disposition.value,
        "recovery_required": after.recovery_required,
        "writer_kind": "controlled_lifecycle_worker",
    }
    command = Command(
        category_id=ctx.category_id,
        command_id=uuid4(),
        idempotency_key=f"lifecycle:{after.id}:{after.revision}",
        operation="evidence.lifecycle.effect",
        product_id=after.scope.product_id,
        expected_revision=before.revision,
        payload={
            "intent_id": str(after.id),
            "revision": after.revision,
            "state": after.state.value,
        },
    )
    append_receipt(
        s,
        ctx,
        command,
        "original_lifecycle_intent",
        row,
        digest(command.payload),
        digest([command.operation, after.id, after.revision]),
        "private",
    )


def configure_lifecycle(engine, store, *, policy=None, allow_local_profile=False):
    """No production default. Explicit local profile is a synthetic development policy."""
    if store is None:
        return
    store.read_engine = engine
    if policy is None:
        if (
            not allow_local_profile
            or os.environ.get("PDOS_OBJECT_LIFECYCLE_PROFILE") != "local-synthetic-v1"
        ):
            return
        policy = RetentionPolicy(
            "local-synthetic-retention-v1",
            timedelta(seconds=60),
            timedelta(days=1),
            timedelta(seconds=30),
        )
    engine.lifecycle_runtime = LifecycleRuntime(
        policy=policy,
        resolve_reference=lambda s, ctx, pid, oid: resolve_reference(s, ctx, pid, oid, store),
        read_facts=lambda s, ctx, pid, ref, prev: read_facts(s, ctx, pid, ref, prev, store),
        references_factory=lambda s, ctx, pid: References(s, ctx, pid, store),
        transition_hook=transition,
        service_authorize=authorize_service,
    )

    @contextmanager
    def gate(permit, observation=False):
        with tenant_session(
            engine,
            permit.scope.tenant_id,
            actor_id=permit.named_decider_id,
            requester_id=permit.named_decider_id,
        ) as s:
            s.info["lifecycle_worker"] = _WORKER
            ctx = Context(
                permit.scope.tenant_id,
                permit.named_decider_id,
                permit.named_decider_id,
                category_id=permit.scope.category_id
                or s.scalar(select(category_for_product(permit.scope.product_id))),
            )
            service = runtime_for(s, ctx, permit.scope.product_id)
            if observation:
                fence, intent = service._locked_operation(permit.operation_id)
                if intent.permit != permit:
                    raise LifecycleFailure("BINDING_MISMATCH", "观察对象不匹配原尝试。")
                service._effect_authority(ctx, fence, intent, now(), reconcile=True)
            else:
                service.validate_effect(ctx, permit)
            yield

    from pdos_next.object_lifecycle_runtime import LocalReversibleLifecycleAdapter

    transport = LocalReversibleLifecycleAdapter(store, gate)
    engine.lifecycle_transport = transport
    store.lifecycle_transport = transport


def process(engine, reference, *, observe_only=False):
    ctx = event_context(reference)
    tenant, intent_id = UUID(reference["tenant_id"]), UUID(reference["subject_id"])
    product_id = UUID(reference["product_id"]) if reference.get("product_id") else None
    transport = getattr(engine, "lifecycle_transport", None)
    if transport is None:
        raise DomainError("LIFECYCLE_UNAVAILABLE", "原件生命周期尚未配置。", 503)
    with tenant_session(
        engine,
        tenant,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        category_id=ctx.category_id,
    ) as s:
        s.info["lifecycle_worker"] = _WORKER
        record = s.get(LifecycleIntentRecord, intent_id)
        if not record or record.product_id != product_id:
            raise DomainError("SOURCE_UNAVAILABLE", "生命周期意图不可用。", 403)
        intent = decode_intent(record.document)
        if intent.named_decider_id != ctx.requester_id:
            raise DomainError("FORBIDDEN_SCOPE", "生命周期范围信封与具名决定不符。", 403)
        service = runtime_for(s, ctx, product_id)
        product_gate(s, ctx, product_id)
        if intent.state in {IntentState.APPLIED, IntentState.NOT_APPLIED, IntentState.CANCELLED}:
            return {"status": intent.state.value, "intent_id": str(intent.id)}
        apply = intent.state == IntentState.PENDING and not observe_only
        if apply:
            permit = service.begin_effect(ctx, intent.id)
        elif intent.permit:
            permit = intent.permit
        else:
            return {"status": intent.state.value, "intent_id": str(intent.id)}
    # The permit is committed. Adapter opens the current shared gate around bounded I/O.
    try:
        outcome = transport.apply_once(permit) if apply else transport.observe(permit)
    except (LifecycleFailure, DomainError):
        outcome = EffectReceipt(
            permit.operation_id,
            permit.reference,
            permit.scope,
            permit.lease_token,
            EffectOutcome.UNKNOWN,
            None,
            False,
            now(),
            "local-lifecycle-unconfirmed",
            "AUTHORITY_CHANGED",
        )
    with tenant_session(
        engine,
        tenant,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        category_id=ctx.category_id,
    ) as s:
        s.info["lifecycle_worker"] = _WORKER
        service = runtime_for(s, ctx, product_id)
        result = service.record_effect(ctx, intent_id, outcome)
        return {"status": result.state.value, "intent_id": str(intent_id)}
