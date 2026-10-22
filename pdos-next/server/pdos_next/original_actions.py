"""Named withdrawal invalidates current use while retaining original bytes/history."""

from sqlalchemy import select

from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Principal
from pdos_next.original_security import security_row
from pdos_next.originals import require_original


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"confirmation_token"})


def validate(s, ctx, command, product, payload):
    if (
        ctx.run_id
        or ctx.actor_id != ctx.requester_id
        or s.get(Principal, ctx.actor_id).kind != "human"
    ):
        raise DomainError("NAMED_DECISION_REQUIRED", "撤回来源需要具名本人确认。", 403)
    original = require_original(s, ctx, product.id, payload.original_id, lock=True)
    state = security_row(s, original)
    # Permit exact successful dedup to pass the current authorization check.
    if state.epoch != payload.expected_epoch and not (
        state.source_state == "withdrawn" and state.epoch == payload.expected_epoch + 1
    ):
        raise DomainError("VERSION_CONFLICT", "原件安全状态已变化，请重新预览。")
    if command.source_read_set:
        raise DomainError("INVALID_PAYLOAD", "撤回原件不接受额外来源输入。", 422)


def preview_view(s, ctx, command, product, payload):
    if command.expected_revision != product.revision:
        raise DomainError("VERSION_CONFLICT", "型号范围已变化，请刷新后重新预览。")
    original = require_original(s, ctx, product.id, payload.original_id, lock=True)
    state = security_row(s, original)
    if state.source_state != "active" or state.epoch != payload.expected_epoch:
        raise DomainError("VERSION_CONFLICT", "来源已撤回或状态已变化。")
    return {
        "before": {
            "id": str(original.id),
            "title": original.title,
            "source_state": state.source_state,
            "epoch": state.epoch,
        },
        "after": {"source_state": "withdrawn", "reason": payload.reason},
        "effect": (
            "停止下载、解析和新的业务引用；依赖结果需重新核对。"
            "原件字节与历史决定保留，不执行物理删除。"
        ),
    }


def apply(s, ctx, command, product, payload):
    if command.expected_revision != product.revision:
        raise DomainError("VERSION_CONFLICT", "型号范围已变化，请刷新后重新预览。")
    original = require_original(s, ctx, product.id, payload.original_id, lock=True)
    state = security_row(s, original)
    if state.epoch != payload.expected_epoch or state.source_state != "active":
        raise DomainError("VERSION_CONFLICT", "原件状态已变化。")
    state.epoch += 1
    state.source_state = "withdrawn"
    original.revision += 1
    source = s.scalar(select(Artifact).where(Artifact.original_id == original.id).with_for_update())
    if source and source.status == "active":
        source.status = "withdrawn"
        source.revision += 1
    original.action_result = {
        "source_state": "withdrawn",
        "security_epoch": state.epoch,
        "reason": payload.reason,
    }
    return original, "uploaded_original", original.visibility
