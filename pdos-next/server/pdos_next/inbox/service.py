"""All message writes are authored by a named human; no AI execution path."""

from dataclasses import replace
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator
from sqlalchemy import func, select, text

from pdos_next.agent_kernel.models import AgentRun
from pdos_next.category_scope import category_scope
from pdos_next.database import require_context
from pdos_next.domain.preproject.access import human, member
from pdos_next.errors import DomainError
from pdos_next.models import Category, Principal, Project, ProjectStatusUpdate
from pdos_next.personal_views import _page
from pdos_next.schema_base import StrictModel
from pdos_next.service import digest

from .models import Conversation, InboxState, Message


class NewMessage(StrictModel):
    body: str = Field(min_length=1, max_length=8000)
    request_key: UUID

    @field_validator("body")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("请输入消息")
        return value.strip()


class NewConversation(NewMessage):
    category_id: UUID
    title: str = Field(min_length=1, max_length=160)
    recipients: list[UUID] = Field(min_length=1, max_length=19)

    @field_validator("title")
    @classmethod
    def title_nonblank(cls, value):
        if not value.strip():
            raise ValueError("请输入会话标题")
        return value.strip()


class SaveState(StrictModel):
    kind: Literal["conversation", "run", "project"]
    target_id: UUID
    expected_revision: int = Field(ge=0)
    observed_token: str = Field(max_length=64)
    mark_read: bool
    archived: bool
    followed: bool
    request_key: UUID


def _personal(s, ctx):
    require_context(s, ctx)
    human(s, ctx)
    if ctx.category_id is not None:
        raise DomainError("FORBIDDEN_SCOPE", "请使用本人收件箱。", 403)


def _lock(s, value):
    s.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"), {"key": value})


def _request(s, ctx, model, data, owner_column):
    fingerprint = digest(data.model_dump(mode="json"))
    _lock(s, f"inbox-request:{ctx.tenant_id}:{ctx.actor_id}:{data.request_key}")
    prior = s.scalar(
        select(model).where(
            model.tenant_id == ctx.tenant_id,
            owner_column == ctx.actor_id,
            model.request_key == data.request_key,
        )
    )
    if prior and prior.request_sha256 != fingerprint:
        raise DomainError("DUPLICATE_INTENT_CONFLICT", "请求已绑定另一份内容。")
    return prior, fingerprint


def conversation(s, ctx, identity):
    row = s.get(Conversation, identity)
    if row is None or row.tenant_id != ctx.tenant_id or ctx.actor_id not in row.member_ids:
        raise DomainError("FORBIDDEN_SCOPE", "会话不可读或权限已变化。", 403)
    category_scope(
        s, replace(ctx, category_id=row.category_id), lock=not s.info.get("read_snapshot")
    )
    return row


def message_view(s, row):
    person = s.get(Principal, row.sender_id)
    return {
        "id": str(row.id),
        "sequence": row.sequence,
        "sender_id": str(row.sender_id),
        "sender_name": person.name if person else "成员",
        "body": row.body,
        "created_at": row.created_at.isoformat(),
    }


def _append_message(s, ctx, target, data):
    # Lock before idempotency lookup: concurrent retries return exactly the same message.
    _lock(s, f"inbox-message:{ctx.tenant_id}:{target.id}")
    prior, fingerprint = _request(s, ctx, Message, data, Message.sender_id)
    if prior:
        if prior.conversation_id != target.id:
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "请求属于另一会话。")
        return message_view(s, prior)
    sequence = (
        s.scalar(
            select(func.coalesce(func.max(Message.sequence), 0)).where(
                Message.tenant_id == ctx.tenant_id, Message.conversation_id == target.id
            )
        )
        + 1
    )
    row = Message(
        tenant_id=ctx.tenant_id,
        conversation_id=target.id,
        sender_id=ctx.actor_id,
        sequence=sequence,
        body=data.body,
        request_key=data.request_key,
        request_sha256=fingerprint,
    )
    s.add(row)
    s.flush()
    return message_view(s, row)


def create(s, ctx, data):
    _personal(s, ctx)
    scoped = replace(ctx, category_id=data.category_id)
    category_scope(s, scoped, lock=True)
    people = sorted({*data.recipients, ctx.actor_id}, key=str)
    if len(people) != len(data.recipients) + 1:
        raise DomainError("VALIDATION_FAILED", "请选择不重复的其他成员。", 422)
    for identity in people:
        member(s, scoped, identity)
    prior, fingerprint = _request(s, ctx, Conversation, data, Conversation.owner_id)
    if prior:
        return {
            "conversation_id": str(prior.id),
            "message": _append_message(
                s, ctx, prior, NewMessage(body=data.body, request_key=data.request_key)
            ),
        }
    row = Conversation(
        tenant_id=ctx.tenant_id,
        category_id=data.category_id,
        owner_id=ctx.actor_id,
        member_ids=people,
        title=data.title,
        request_key=data.request_key,
        request_sha256=fingerprint,
    )
    s.add(row)
    s.flush()
    return {
        "conversation_id": str(row.id),
        "message": _append_message(
            s, ctx, row, NewMessage(body=data.body, request_key=data.request_key)
        ),
    }


def send(s, ctx, identity, data):
    _personal(s, ctx)
    return _append_message(s, ctx, conversation(s, ctx, identity), data)


def list_conversations(s, ctx, cursor=None, page_size=50):
    _personal(s, ctx)
    rows, following = _page(s, ctx, Conversation, cursor=cursor, page_size=page_size)
    items = []
    for row in rows:
        latest = s.scalar(
            select(Message)
            .where(Message.tenant_id == ctx.tenant_id, Message.conversation_id == row.id)
            .order_by(Message.sequence.desc())
            .limit(1)
        )
        category = s.get(Category, row.category_id)
        people = list(
            s.scalars(
                select(Principal).where(
                    Principal.tenant_id == ctx.tenant_id, Principal.id.in_(row.member_ids)
                )
            )
        )
        items.append(
            {
                "id": str(row.id),
                "title": row.title,
                "category_id": str(row.category_id),
                "category_name": category.name if category else "品类",
                "members": [{"id": str(p.id), "name": p.name} for p in people],
                "created_at": row.created_at.isoformat(),
                "latest": message_view(s, latest) if latest else None,
            }
        )
    return {"items": items, "next_cursor": following}


def messages(s, ctx, identity, before=None, page_size=50):
    _personal(s, ctx)
    target = conversation(s, ctx, identity)
    query = select(Message).where(
        Message.tenant_id == ctx.tenant_id, Message.conversation_id == target.id
    )
    if before is not None:
        query = query.where(Message.sequence < before)
    rows = list(s.scalars(query.order_by(Message.sequence.desc()).limit(page_size + 1)))
    return {
        "conversation_id": str(target.id),
        "items": [message_view(s, row) for row in reversed(rows[:page_size])],
        "next_before": rows[page_size - 1].sequence if len(rows) > page_size else None,
    }


def state_view(row):
    return {
        "kind": row.kind,
        "target_id": str(row.target_id),
        "revision": row.revision,
        "read_through": row.read_through,
        "archived": row.archived,
        "followed": row.followed,
    }


def states(s, ctx):
    _personal(s, ctx)
    rows = s.scalars(
        select(InboxState)
        .where(InboxState.tenant_id == ctx.tenant_id, InboxState.owner_id == ctx.actor_id)
        .distinct(InboxState.kind, InboxState.target_id)
        .order_by(InboxState.kind, InboxState.target_id, InboxState.revision.desc())
    )
    return {"items": [state_view(row) for row in rows]}


def save_state(s, ctx, data):
    _personal(s, ctx)
    if data.kind == "conversation":
        target = conversation(s, ctx, data.target_id)
        _lock(s, f"inbox-message:{ctx.tenant_id}:{target.id}")
        current_token = str(
            s.scalar(
                select(func.coalesce(func.max(Message.sequence), 0)).where(
                    Message.tenant_id == ctx.tenant_id, Message.conversation_id == target.id
                )
            )
        )
    elif data.kind == "project":
        if not s.scalar(
            select(Project.id).where(
                Project.tenant_id == ctx.tenant_id, Project.id == data.target_id
            )
        ):
            raise DomainError("FORBIDDEN_SCOPE", "项目权限已变化，请刷新。", 403)
        latest = s.scalar(
            select(ProjectStatusUpdate.id)
            .where(
                ProjectStatusUpdate.tenant_id == ctx.tenant_id,
                ProjectStatusUpdate.project_id == data.target_id,
            )
            .order_by(ProjectStatusUpdate.created_at.desc(), ProjectStatusUpdate.id.desc())
            .limit(1)
        )
        current_token = str(latest) if latest else "none"
    else:
        run = s.scalar(
            select(AgentRun)
            .where(
                AgentRun.tenant_id == ctx.tenant_id,
                AgentRun.id == data.target_id,
                AgentRun.requester_id == ctx.actor_id,
            )
            .with_for_update(read=True)
        )
        if run is None:
            raise DomainError("FORBIDDEN_SCOPE", "这条动态已不可读。", 403)
        current_token = f"{run.state}:{run.cancel_epoch}"
    prior, fingerprint = _request(s, ctx, InboxState, data, InboxState.owner_id)
    if prior:
        return state_view(prior)
    _lock(s, f"inbox-state:{ctx.tenant_id}:{ctx.actor_id}:{data.kind}:{data.target_id}")
    current = s.scalar(
        select(InboxState)
        .where(
            InboxState.tenant_id == ctx.tenant_id,
            InboxState.owner_id == ctx.actor_id,
            InboxState.kind == data.kind,
            InboxState.target_id == data.target_id,
        )
        .order_by(InboxState.revision.desc())
        .limit(1)
    )
    revision = current.revision if current else 0
    if revision != data.expected_revision or data.observed_token != current_token:
        raise DomainError("VERSION_CONFLICT", "有新消息或阅读状态变化，请刷新后重试。")
    row = InboxState(
        tenant_id=ctx.tenant_id,
        owner_id=ctx.actor_id,
        kind=data.kind,
        target_id=data.target_id,
        revision=revision + 1,
        read_through=current_token if data.mark_read else "",
        archived=data.archived,
        followed=data.followed,
        request_key=data.request_key,
        request_sha256=fingerprint,
    )
    s.add(row)
    s.flush()
    return state_view(row)
