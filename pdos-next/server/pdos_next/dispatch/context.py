"""Execution scope carried by the committed server Outbox envelope."""

from uuid import UUID

from pdos_next.errors import DomainError
from pdos_next.service import Context


def event_context(reference):
    try:
        tenant, category, actor, requester = (
            UUID(reference[key]) for key in ("tenant_id", "category_id", "actor_id", "requester_id")
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        raise DomainError("INVALID_PAYLOAD", "后台工作缺少服务器范围信封。", 422) from None
    return Context(tenant, actor, requester, category_id=category)
