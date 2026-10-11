"""Common T1 hooks; LifecycleService remains the sole lifecycle state machine."""

from dataclasses import replace
from uuid import UUID

from pdos_next.errors import DomainError
from pdos_next.original_lifecycle.rules import digest, facts_digest
from pdos_next.original_lifecycle.service import LifecycleService
from pdos_next.original_lifecycle.types import (
    IntentState,
    LifecycleAction,
    LifecycleFailure,
    exact_reference,
)

from .codec import decode_intent, encode_state
from .runtime import LifecycleRuntime
from .schemas import (
    LifecycleCancelPayload,
    LifecycleCommandPayload,
    LifecycleProtectionPayload,
)
from .store import SqlLifecycleAuthority, SqlLifecycleStore

# The common command layer may alias a new candidate/key to this stored subject's
# original Receipt. It must still run validate before that dedup lookup.
deduplicate_subject = frozenset({"original_lifecycle_intent"})


def _domain(error):
    status = (
        403
        if error.code
        in {
            "FORBIDDEN_SCOPE",
            "SOURCE_UNAVAILABLE",
            "NAMED_CONFIRMATION_REQUIRED",
            "WORKER_AUTHORITY_REQUIRED",
        }
        else 409
    )
    raise DomainError(error.code, str(error), status) from None


def runtime_for(s, ctx, product_id, *, emit_transition=True) -> LifecycleService:
    runtime = getattr(s.get_bind(), "lifecycle_runtime", None)
    if not isinstance(runtime, LifecycleRuntime):
        raise DomainError("LIFECYCLE_UNAVAILABLE", "原件生命周期权威接线尚未配置。", 503)
    store = SqlLifecycleStore(s, ctx, product_id, runtime, emit_transition=emit_transition)
    references = runtime.references_factory(s, ctx, product_id)
    if not all(
        callable(getattr(references, name, None)) for name in ("read_current", "read_under_fence")
    ):
        raise DomainError("LIFECYCLE_UNAVAILABLE", "原件权威引用清单接线尚未配置。", 503)
    return LifecycleService(
        store=store,
        references=references,
        authority=SqlLifecycleAuthority(store),
        policy=runtime.policy,
        clock=runtime.clock,
    )


def _reference(service, object_id):
    store = service.store
    reference = store.runtime.resolve_reference(store.s, store.ctx, store.product_id, object_id)
    try:
        exact_reference(reference)
    except (ValueError, TypeError):
        raise LifecycleFailure("BINDING_MISMATCH", "权威原件引用不是精确服务器对象。") from None
    if reference.id != object_id:
        raise LifecycleFailure("BINDING_MISMATCH", "权威原件标识不一致。")
    return reference


def preview(s, ctx, product_id, object_id: UUID, action: LifecycleAction | str):
    service = runtime_for(s, ctx, product_id)
    try:
        action = LifecycleAction(action)
        candidate = service.preview(ctx, _reference(service, object_id), action=action)
        return candidate.as_dict()
    except ValueError:
        raise DomainError("INVALID_ACTION", "只开放可逆隔离与恢复预览。", 422) from None
    except LifecycleFailure as error:
        _domain(error)


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"confirmation_token"})


def replay_subject(s, ctx, command, product, payload):
    """Find the original same-facts intent before re-consuming a stale T1 snapshot.

    Current object ownership/authorization is mandatory even for a historical
    result. This only exposes an existing bound subject; the common layer must
    locate its original operation Receipt before aliasing a request key.
    """
    if not isinstance(payload, LifecycleCommandPayload):
        return None
    service = runtime_for(s, ctx, product.id, emit_transition=False)
    try:
        _target(service, ctx, command, payload)
        candidate = service._candidate(payload.candidate_id)
        intent_digest = digest(
            [
                candidate.action,
                candidate.original.scope,
                candidate.original.reference,
                candidate.policy_digest,
                facts_digest(candidate.original, candidate.references),
            ]
        )
        prior = service.store.find_intent(candidate.original.scope, intent_digest)
        if prior is None:
            return None
        service._prior_binding(
            prior, candidate.original, candidate.action, intent_digest=intent_digest
        )
        return service.store.intent_row(prior.id)
    except LifecycleFailure as error:
        _domain(error)


def _target(service, ctx, command, payload):
    if isinstance(payload, LifecycleCommandPayload):
        candidate = service.store.get_candidate(payload.candidate_id)
        expected_action = {
            "evidence.lifecycle.quarantine": LifecycleAction.QUARANTINE,
            "evidence.lifecycle.restore": LifecycleAction.RESTORE,
        }.get(command.operation)
        if candidate.action != expected_action or candidate.digest != payload.digest:
            raise LifecycleFailure("PREVIEW_MISMATCH", "共同确认与固定生命周期候选不一致。")
        reference, action = candidate.original.reference, candidate.action
    elif isinstance(payload, LifecycleCancelPayload):
        if command.operation != "evidence.lifecycle.cancel":
            raise LifecycleFailure("INVALID_ACTION", "取消载荷不能用于其他动作。")
        intent = service.store.get_intent(payload.intent_id)
        reference, action = intent.reference, intent.action
    elif isinstance(payload, LifecycleProtectionPayload):
        if command.operation != "evidence.lifecycle.protection.record":
            raise LifecycleFailure("INVALID_ACTION", "保护事实载荷不能用于其他动作。")
        reference, action = _reference(service, payload.object_id), LifecycleAction.PREVIEW
    else:
        raise LifecycleFailure("INVALID_PAYLOAD", "未知生命周期载荷。")
    original = service.store.read_current(reference)
    service._authorize(ctx, original, action, service.clock.now())
    return original


def validate(s, ctx, command, product, payload):
    if command.source_read_set:
        raise DomainError(
            "INVALID_PAYLOAD", "生命周期由权威引用清单决定，不接受额外引用输入。", 422
        )
    service = runtime_for(s, ctx, product.id, emit_transition=False)
    try:
        _target(service, ctx, command, payload)
    except LifecycleFailure as error:
        _domain(error)


def _new_write(command, product):
    if command.expected_revision != product.revision:
        raise DomainError("VERSION_CONFLICT", "型号范围已变化，请重新预览。")


def _candidate_current(service, ctx, payload):
    candidate = service._candidate(payload.candidate_id)
    if candidate.digest != payload.digest:
        raise LifecycleFailure("PREVIEW_MISMATCH", "候选摘要不一致。")
    fence = service.store.lock_current(candidate.original.reference)
    references = service.references.read_under_fence(fence)
    now = service.clock.now()
    if candidate.captured_at > now:
        raise LifecycleFailure("FACT_TIME_INVALID", "候选核对时点不能在未来。")
    if facts_digest(fence.original, references) != facts_digest(
        candidate.original, candidate.references
    ):
        raise LifecycleFailure("PREVIEW_STALE", "原件或引用保护事实已变化。")
    decision = service._decision(candidate.action, fence.original, references, now)
    if not candidate.decision.eligible or not decision.eligible:
        raise LifecycleFailure("RETENTION_PROTECTED", "当前事实不允许这个生命周期动作。")
    service._authorize(ctx, fence.original, candidate.action, now)
    return candidate


def _cancel_current(service, payload):
    intent = service.store.get_intent(payload.intent_id)
    if intent.revision != payload.expected_revision:
        raise LifecycleFailure("VERSION_CONFLICT", "生命周期意图版本已变化。")
    if intent.state != IntentState.PENDING or intent.permit is not None:
        raise LifecycleFailure(
            "EFFECT_ALREADY_ATTEMPTED", "已尝试的操作只能受控观察，不能取消或重发。"
        )
    return intent


def protection_view(row):
    return {
        "object_id": str(row.id),
        "revision": row.revision,
        "manual_hold": row.manual_hold,
        "retention_until": row.retention_until.isoformat() if row.retention_until else None,
        "protection_revision": row.protection_revision,
    }


def _protection_current(service, payload):
    reference = _reference(service, payload.object_id)
    fence = service.store.lock_current(reference)
    row = service.store._fenced(fence)
    if row.revision != payload.expected_revision:
        raise LifecycleFailure("VERSION_CONFLICT", "原件生命周期版本已变化。")
    if fence.original.pending_intent_id is not None:
        raise LifecycleFailure("EFFECT_PENDING", "待执行或未知操作期间不能改变保护事实。")
    return fence, row


def preview_view(s, ctx, command, product, payload):
    _new_write(command, product)
    service = runtime_for(s, ctx, product.id, emit_transition=False)
    try:
        _target(service, ctx, command, payload)
        if isinstance(payload, LifecycleCommandPayload):
            candidate = _candidate_current(service, ctx, payload)
            original = candidate.original
            before = {
                **candidate.as_dict(),
                "product_id": str(original.scope.product_id) if original.scope.product_id else None,
                "owner_id": str(ctx.requester_id),
                "registered": original.registered,
                "manual_hold": original.manual_hold,
                "retention_until": original.retention_until.isoformat()
                if original.retention_until
                else None,
                "upload_state": original.upload_state.value,
                "upload_terminal_at": original.upload_terminal_at.isoformat()
                if original.upload_terminal_at
                else None,
                "parse_state": original.parse_state.value,
                "disposition": original.disposition.value,
                "reference_count": candidate.references.reference_count,
                "formal_history": candidate.references.formal_history,
            }
            return {
                "before": before,
                "after": {
                    "action": candidate.action.value,
                    "status": "pending",
                    "reason": payload.reason,
                    "physical_effect_applied": False,
                },
                "effect": (
                    "只记录具名可逆操作意图。工作器仍须检查当前保护与权限；"
                    "不删除字节，不授予安全资格。"
                ),
            }
        if isinstance(payload, LifecycleCancelPayload):
            intent = _cancel_current(service, payload)
            return {
                "before": {
                    "intent_id": str(intent.id),
                    "revision": intent.revision,
                    "action": intent.action.value,
                    "state": intent.state.value,
                    "object_id": str(intent.reference.id),
                    "attempted": intent.permit is not None,
                },
                "after": {
                    "state": "cancelled",
                    "reason": payload.reason,
                    "physical_effect_applied": False,
                },
                "effect": "只取消未尝试的待执行意图；已尝试或未知操作只能观察，不重发。",
            }
        _, row = _protection_current(service, payload)
        return {
            "before": protection_view(row),
            "after": {
                "object_id": str(row.id),
                "revision": row.revision + 1,
                "manual_hold": payload.manual_hold,
                "retention_until": payload.retention_until.isoformat(),
                "protection_revision": row.protection_revision + 1,
                "reason": payload.reason,
            },
            "effect": (
                "记录具名保留与人工保护事实；仍受配置的最小等待期及引用历史保护，不执行物理操作。"
            ),
        }
    except LifecycleFailure as error:
        _domain(error)


def apply(s, ctx, command, product, payload):
    _new_write(command, product)
    service = runtime_for(s, ctx, product.id, emit_transition=False)
    try:
        _target(service, ctx, command, payload)
        if isinstance(payload, LifecycleCommandPayload):
            service.store.request_reason = payload.reason
            intent = service.confirm(
                ctx, payload.candidate_id, payload.digest, command.idempotency_key
            )
            row = service.store.intent_row(intent.id)
        elif isinstance(payload, LifecycleCancelPayload):
            _cancel_current(service, payload)
            intent = service.cancel_pending(ctx, payload.intent_id)
            row = service.store.intent_row(intent.id)
        else:
            fence, row = _protection_current(service, payload)
            state = replace(
                fence.original,
                revision=fence.original.revision + 1,
                manual_hold=payload.manual_hold,
                retention_until=payload.retention_until,
            )
            row.revision, row.state = state.revision, encode_state(state)
            row.manual_hold, row.retention_until = payload.manual_hold, payload.retention_until
            row.protection_revision += 1
            row.status = state.disposition.value
            row.action_result = {
                **protection_view(row),
                "reason": payload.reason,
                "physical_effect_applied": False,
            }
            s.flush()
            return row, "original_lifecycle_object", "private"
        s.flush()
        row.status = intent.state.value
        row.action_result = {
            "intent_id": str(intent.id),
            "object_id": str(intent.reference.id),
            "action": intent.action.value,
            "state": intent.state.value,
            "physical_effect_applied": False,
        }
        return row, "original_lifecycle_intent", "private"
    except LifecycleFailure as error:
        _domain(error)


def intent_view(row):
    """Authorized read projection: no exact storage key, token, authority claims or scan claim."""
    intent = decode_intent(row.document)
    return {
        "id": str(intent.id),
        "object_id": str(intent.reference.id),
        "revision": intent.revision,
        "action": intent.action.value,
        "state": intent.state.value,
        "created_at": intent.created_at.isoformat(),
        "updated_at": intent.updated_at.isoformat(),
        "reason": row.reason,
        "attempted": intent.permit is not None,
        "outcome": intent.receipt.outcome.value if intent.receipt else None,
        "recovery_required": intent.recovery_required,
        "protection_reasons": [reason.value for reason in intent.protection_reasons],
    }
