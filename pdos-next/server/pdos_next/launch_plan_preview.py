"""Isolated exact-Plan preview seam; never a write, replay or shared proof cache.

The common caller keeps its Product lock, actor/source gates and normal material
confirmation.  The existing owner preview already loads and validates the whole
Plan.  Calling its separate validate first repeats that entire traversal without
introducing a later guard.  This seam calls the unchanged owner preview once.
"""


from sqlalchemy import inspect
from sqlalchemy.orm import Session, SessionTransaction

from pdos_next.clock import now
from pdos_next.contracts import Command
from pdos_next.domain.professional_authority.service import authority_time_current
from pdos_next.domain.verification_launch import service as launch
from pdos_next.domain.verification_launch.schemas import PlanPayload
from pdos_next.errors import DomainError
from pdos_next.models import Product
from pdos_next.quality_result_bridge import _runtime_stamp
from pdos_next.service import Context, digest

OPERATION = "test.run.plan"


def _now():
    return now()


def _uow(s):
    if not isinstance(s, Session) or s.is_active is not True:
        raise DomainError("INTEGRATION_REQUIRED", "计划预览需要实际活动Session。", 503)
    root, current = s.get_transaction(), s.get_nested_transaction()
    if not isinstance(root, SessionTransaction):
        raise DomainError("INTEGRATION_REQUIRED", "计划预览需要当前事务。", 503)
    chain, seen = [], set()
    value = current or root
    while value is not None:
        if (
            not isinstance(value, SessionTransaction)
            or id(value) in seen
            or value.session is not s
            or value.is_active is not True
        ):
            raise DomainError("SOURCE_STALE", "计划预览事务链已变化。")
        seen.add(id(value))
        chain.append(value)
        value = value.parent
    if chain[-1] is not root or root.parent is not None:
        raise DomainError("SOURCE_STALE", "计划预览不在原主事务内。")
    if s.new or s.dirty or s.deleted:
        raise DomainError("INTEGRATION_REQUIRED", "只读计划预览不能复用待保存对象。", 503)
    return s.get_bind(), tuple(chain)


def _binding(s, ctx, command, product, payload):
    if type(ctx) is not Context or ctx.run_id is not None or ctx.actor_id != ctx.requester_id:
        raise DomainError("NAMED_PERSON_REQUIRED", "计划预览须由当前具名本人办理。", 403)
    if type(command) is not Command or type(payload) is not PlanPayload:
        raise DomainError("INVALID_REQUEST", "须传入完整已核对的计划命令。", 422)
    checked = Command.model_validate(command.model_dump(mode="json"))
    if checked.operation != OPERATION or PlanPayload.model_validate(checked.payload) != payload:
        raise DomainError("FORBIDDEN_OPERATION", "本入口仅核对精确的Run计划。", 403)
    if type(product) is not Product:
        raise DomainError("INTEGRATION_REQUIRED", "计划预览缺少实际型号对象。", 503)
    state = inspect(product)
    if state.session is not s or state.persistent is not True:
        raise DomainError("INTEGRATION_REQUIRED", "产品必须是本Session已保存对象。", 503)
    if product.tenant_id != ctx.tenant_id or product.id != checked.product_id:
        raise DomainError("FORBIDDEN_SCOPE", "计划预览不在原产品或租户范围。", 403)
    return digest(
        {
            "context": vars(ctx),
            "command": checked.model_dump(mode="json"),
            "payload": payload.model_dump(mode="json"),
            "product": {c.key: getattr(product, c.key) for c in Product.__table__.columns},
        }
    )


def _owner_stamp():
    # Detect a callback replacement during the current call, not just an issuer
    # epoch change.  Actual source/professional checks stay inside these owners.
    return tuple(
        getattr(launch, name)
        for name in ("preview_view", "_load", "_guards", "_new_write", "_kernel")
    )


def preview_once(s, ctx, command, product, payload):
    """Use the unchanged Plan owner once inside this common preview invocation.

    Nothing is returned for reuse by another call, and no negative is memoized.
    The caller must NOT add Plan to PHASED_MATERIAL_OPERATIONS, since that set
    also changes consume/execute.  This module has no prepare/apply/replay API.
    """
    uow = _uow(s)
    binding = _binding(s, ctx, command, product, payload)
    runtime, owners = _runtime_stamp(s), _owner_stamp()
    with s.no_autoflush:
        review = launch.preview_view(s, ctx, command, product, payload)
        # Check UOW before any final ORM property read.  No re-entry from another
        # Session, root or SAVEPOINT can carry the earlier successful proof.
        if _uow(s) != uow:
            raise DomainError("SOURCE_STALE", "计划预览已离开原事务。")
        if _binding(s, ctx, command, product, payload) != binding:
            raise DomainError("SOURCE_CHANGED", "计划命令、范围或产品材料已变化。")
        if _owner_stamp() != owners or _runtime_stamp(s) != runtime:
            raise DomainError("SOURCE_STALE", "计划核对期间宿主或签发配置已变化。")
        # Sample fresh time after all owner/source/professional/ORM I/O.  Do not
        # serialize a new event or shift the supplied plan window to make it pass.
        final_at = _now()
        if not authority_time_current(review["authority"], final_at):
            raise DomainError("SOURCE_STALE", "本人专业资格在计划核对期间已到期。")
        if payload.execution_plan.window.start < final_at:
            raise DomainError("INVALID_EVENT_TIME", "计划窗口在核对期间已开始，请重新读取。", 422)
    return review
