"""Project discussions and object comments (`discussion.message.post` / `.retract`, P34-2).

Rules kept here and in the database:
- only a named human acting for themself posts, edits or retracts; 小Pai's identity
  has no privilege on these tables at all (DC-11; its own replies are W6 ⑥, P54);
- a thread inherits its subject's audience and is re-checked on every read;
- a comment records the object version it was written against (P41-6);
- editing keeps every version; retraction leaves "已撤回" and keeps the history;
- what is said here is never a decision, commitment or approval (P34-2).
"""

from uuid import UUID

from pydantic import Field, field_validator
from sqlalchemy import func, select, text

from pdos_next.core.clock import now
from pdos_next.core.database import require_context
from pdos_next.core.models import Artifact, Principal
from pdos_next.core.schema_base import StrictModel
from pdos_next.core.service import digest, require_access
from pdos_next.domain.categories.preproject.access import fail, human
from pdos_next.domain.my_work.notifications import service as notifications
from pdos_next.domain.projects.models import Project
from pdos_next.domain.projects.team import handover
from pdos_next.errors import DomainError

from . import mentions
from .models import DiscussionFollow, DiscussionMessage, DiscussionMessageVersion, DiscussionThread

OBJECT_TYPES = {"work_task": "任务", "artifact": "文档"}
RETRACTED = "已撤回"
NOT_A_DECISION = "讨论不是正式记录：这里的结论不构成决定、承诺或批准，需要时请转为任务或决定草稿。"


class NewMessage(StrictModel):
    body: str = Field(min_length=1, max_length=8000)
    request_key: UUID

    @field_validator("body")
    @classmethod
    def body_nonblank(cls, value):
        if not value.strip():
            raise ValueError("请输入内容")
        return value.strip()


class NewTopic(NewMessage):
    title: str = Field(min_length=1, max_length=160)

    @field_validator("title")
    @classmethod
    def title_nonblank(cls, value):
        if not value.strip():
            raise ValueError("请输入讨论标题")
        return value.strip()


class EditMessage(NewMessage):
    expected_revision: int = Field(ge=1)


class RetractMessage(StrictModel):
    expected_revision: int = Field(ge=1)
    request_key: UUID


class FollowChange(StrictModel):
    followed: bool


# Scope --------------------------------------------------------------------------


ANY_ITEM = (None, None)


def _project(s, ctx, product_id, project_id, *, write=False, lane=ANY_ITEM):
    """The project row under the caller's own RLS.

    For a removed member in handover the lane opens the project row in this
    transaction only; every thread still re-checks that its subject is one of
    their own open items, so project topics and other objects stay invisible.
    """
    require_context(s, ctx)
    human(s, ctx)
    if lane is not None:
        handover.open_lane(s, ctx, project_id, *lane)
    require_access(s, ctx, product_id, write=False, lock=write)
    row = s.scalar(
        select(Project).where(
            Project.tenant_id == ctx.tenant_id,
            Project.category_id == ctx.category_id,
            Project.product_id == product_id,
            Project.id == project_id,
        )
    )
    if row is None:
        raise DomainError("FORBIDDEN_SCOPE", "项目不存在或不在当前受众内。", 403)
    return row


def _full(s, ctx, project):
    """True when the requester sees the project itself, not only a handover item."""
    return bool(
        s.scalar(
            text("SELECT discussion_project_open(:t, :p)"),
            {"t": ctx.tenant_id, "p": project.id},
        )
    )


def _subject(s, ctx, project, subject_type, subject_id):
    """Current title and revision of a comment subject, read under the caller's RLS."""
    if subject_type == "work_task":
        from pdos_next.domain.projects.work.models import WorkTaskCurrent, WorkTaskVersion

        pointer = s.scalar(
            select(WorkTaskCurrent).where(
                WorkTaskCurrent.tenant_id == ctx.tenant_id,
                WorkTaskCurrent.project_id == project.id,
                WorkTaskCurrent.task_id == subject_id,
            )
        )
        if pointer is None:
            raise DomainError("FORBIDDEN_SCOPE", "任务不存在或不可读。", 403)
        version = s.get(WorkTaskVersion, pointer.version_id)
        return {"title": (version.body or {}).get("title", "任务"), "revision": pointer.revision}
    if subject_type == "artifact":
        row = s.scalar(
            select(Artifact).where(
                Artifact.tenant_id == ctx.tenant_id,
                Artifact.category_id == project.category_id,
                Artifact.id == subject_id,
                Artifact.status == "active",
            )
        )
        if row is None or (row.product_id is not None and row.product_id != project.product_id):
            raise DomainError("FORBIDDEN_SCOPE", "文档不存在或不在当前受众内。", 403)
        return {"title": row.title, "revision": row.revision, "visibility": row.visibility}
    raise DomainError("VALIDATION_FAILED", "不支持在此类对象下评论。", 422)


def _lane(subject_type, subject_id):
    return ("work_task", subject_id) if subject_type == "work_task" else None


def _thread(s, ctx, project, thread_id):
    row = s.scalar(
        select(DiscussionThread).where(
            DiscussionThread.tenant_id == ctx.tenant_id,
            DiscussionThread.project_id == project.id,
            DiscussionThread.id == thread_id,
        )
    )
    if row is None:
        raise DomainError("FORBIDDEN_SCOPE", "讨论不存在或权限已变化。", 403)
    return row


def _object_thread(s, ctx, project, subject_type, subject_id):
    return s.scalar(
        select(DiscussionThread).where(
            DiscussionThread.tenant_id == ctx.tenant_id,
            DiscussionThread.project_id == project.id,
            DiscussionThread.subject_type == subject_type,
            DiscussionThread.subject_id == subject_id,
        )
    )


def _follow_target(thread):
    """Commenting follows the object (a task's changes and comments); topics follow the thread."""
    if thread.subject_type == "work_task":
        return "work_task", thread.subject_id
    return "thread", thread.id


def _targets(thread):
    values = [("thread", thread.id)]
    if thread.subject_type == "work_task":
        values.append(("work_task", thread.subject_id))
    return values


# Views ---------------------------------------------------------------------------


def _people(s, ctx, ids):
    ids = {value for value in ids if value}
    if not ids:
        return {}
    return {
        row.id: row.name
        for row in s.scalars(
            select(Principal).where(Principal.tenant_id == ctx.tenant_id, Principal.id.in_(ids))
        )
    }


def message_view(row, names, me):
    retracted = row.state == "retracted"
    return {
        "id": str(row.id),
        "sequence": row.sequence,
        "author_id": str(row.author_id),
        "author_name": names.get(row.author_id, "成员"),
        "state": row.state,
        "retracted": retracted,
        "body": "" if retracted else row.body,
        "placeholder": RETRACTED if retracted else None,
        "mentions": [] if retracted else row.mentions,
        "revision": row.revision,
        "edited": row.state == "edited",
        "subject_revision": row.subject_revision,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "change_seq": row.change_seq,
        "own": row.author_id == me,
        "can_edit": row.author_id == me and not retracted,
    }


def _following(s, ctx, thread):
    kind, target = _follow_target(thread)
    rows = {
        (row.target_kind, row.target_id): row.followed
        for row in s.scalars(
            select(DiscussionFollow).where(
                DiscussionFollow.tenant_id == ctx.tenant_id,
                DiscussionFollow.principal_id == ctx.requester_id,
                DiscussionFollow.target_id.in_([thread.id, thread.subject_id]),
            )
        )
    }
    return bool(rows.get(("thread", thread.id)) or rows.get((kind, target)))


def _thread_view(s, ctx, project, thread, *, before=None, page_size=50, full=True):
    query = select(DiscussionMessage).where(
        DiscussionMessage.tenant_id == ctx.tenant_id, DiscussionMessage.thread_id == thread.id
    )
    if before is not None:
        query = query.where(DiscussionMessage.sequence < before)
    rows = list(s.scalars(query.order_by(DiscussionMessage.sequence.desc()).limit(page_size + 1)))
    page = list(reversed(rows[:page_size]))
    ids = {row.author_id for row in page} | {thread.author_id}
    for row in page:
        for item in row.mentions or ():
            if item.get("kind") == "person":
                ids.add(UUID(item["id"]))
    names = _people(s, ctx, ids)
    subject = None
    if thread.subject_type != "project":
        subject = {
            "type": thread.subject_type,
            "type_label": OBJECT_TYPES[thread.subject_type],
            "id": str(thread.subject_id),
            **_subject(s, ctx, project, thread.subject_type, thread.subject_id),
        }
    return {
        "thread": {
            "id": str(thread.id),
            "project_id": str(project.id),
            "subject_type": thread.subject_type,
            "subject_id": str(thread.subject_id),
            "title": thread.title,
            "author_id": str(thread.author_id),
            "author_name": names.get(thread.author_id, "成员"),
            "created_at": thread.created_at.isoformat(),
            "following": _following(s, ctx, thread),
            "token": thread_tokens(s, ctx, [thread.id]).get(str(thread.id)),
        },
        "subject": subject,
        "messages": [message_view(row, names, ctx.requester_id) for row in page],
        "people": {str(key): value for key, value in names.items()},
        "next_before": page[0].sequence if len(rows) > page_size else None,
        "can_post": True,
        "full_project": full,
        "note": NOT_A_DECISION,
    }


def thread_tokens(s, ctx, thread_ids):
    """Live-delivery token per visible thread: its latest message change (D74)."""
    ids = []
    for value in thread_ids:
        try:
            ids.append(UUID(str(value)))
        except ValueError:
            continue
    if not ids:
        return {}
    rows = s.execute(
        select(DiscussionThread.id, func.coalesce(func.max(DiscussionMessage.change_seq), 0))
        .outerjoin(
            DiscussionMessage,
            (DiscussionMessage.tenant_id == DiscussionThread.tenant_id)
            & (DiscussionMessage.thread_id == DiscussionThread.id),
        )
        .where(DiscussionThread.tenant_id == ctx.tenant_id, DiscussionThread.id.in_(ids[:20]))
        .group_by(DiscussionThread.id)
    ).all()
    return {str(identity): str(token) for identity, token in rows}


def topics(s, ctx, product_id, project_id):
    project = _project(s, ctx, product_id, project_id, lane=None)
    if not _full(s, ctx, project):
        raise DomainError("FORBIDDEN_SCOPE", "项目讨论只对项目受众可见。", 403)
    rows = list(
        s.scalars(
            select(DiscussionThread).where(
                DiscussionThread.tenant_id == ctx.tenant_id,
                DiscussionThread.project_id == project.id,
                DiscussionThread.subject_type == "project",
            )
        )
    )
    stats = {
        thread: (count, latest_seq)
        for thread, count, latest_seq in s.execute(
            select(
                DiscussionMessage.thread_id,
                func.count(),
                func.max(DiscussionMessage.change_seq),
            )
            .where(
                DiscussionMessage.tenant_id == ctx.tenant_id,
                DiscussionMessage.thread_id.in_([row.id for row in rows] or [UUID(int=0)]),
            )
            .group_by(DiscussionMessage.thread_id)
        ).all()
    }
    latest = {}
    for row in s.scalars(
        select(DiscussionMessage)
        .where(
            DiscussionMessage.tenant_id == ctx.tenant_id,
            DiscussionMessage.thread_id.in_([row.id for row in rows] or [UUID(int=0)]),
        )
        .distinct(DiscussionMessage.thread_id)
        .order_by(DiscussionMessage.thread_id, DiscussionMessage.sequence.desc())
    ):
        latest[row.thread_id] = row
    names = _people(
        s, ctx, {row.author_id for row in rows} | {row.author_id for row in latest.values()}
    )
    items = [
        {
            "id": str(row.id),
            "title": row.title,
            "author_name": names.get(row.author_id, "成员"),
            "created_at": row.created_at.isoformat(),
            "messages": stats.get(row.id, (0, 0))[0],
            "token": str(stats.get(row.id, (0, 0))[1] or 0),
            "latest": message_view(latest[row.id], names, ctx.requester_id)
            if row.id in latest
            else None,
            "following": _following(s, ctx, row),
        }
        for row in rows
    ]
    items.sort(key=lambda item: int(item["token"]), reverse=True)
    return {"project_id": str(project.id), "items": items, "note": NOT_A_DECISION}


def thread(s, ctx, product_id, project_id, thread_id, before=None):
    project = _project(s, ctx, product_id, project_id)
    row = _thread(s, ctx, project, thread_id)
    return _thread_view(s, ctx, project, row, before=before, full=_full(s, ctx, project))


def comments(s, ctx, product_id, project_id, subject_type, subject_id, before=None):
    if subject_type not in OBJECT_TYPES:
        raise DomainError("VALIDATION_FAILED", "不支持在此类对象下评论。", 422)
    project = _project(s, ctx, product_id, project_id, lane=_lane(subject_type, subject_id))
    full = _full(s, ctx, project)
    if subject_type == "artifact" and not full:
        raise DomainError("FORBIDDEN_SCOPE", "文档不在当前受众内。", 403)
    found = _object_thread(s, ctx, project, subject_type, subject_id)
    if found is None:
        subject = _subject(s, ctx, project, subject_type, subject_id)
        return {
            "thread": None,
            "subject": {
                "type": subject_type,
                "type_label": OBJECT_TYPES[subject_type],
                "id": str(subject_id),
                **subject,
            },
            "messages": [],
            "people": {},
            "next_before": None,
            "can_post": True,
            "full_project": full,
            "note": NOT_A_DECISION,
        }
    return _thread_view(s, ctx, project, found, before=before, full=full)


# Writes --------------------------------------------------------------------------


def _lock(s, key):
    s.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"), {"key": key})


def _prior(s, ctx, model, column, key, fingerprint):
    row = s.scalar(
        select(model).where(
            model.tenant_id == ctx.tenant_id, column == ctx.actor_id, model.request_key == key
        )
    )
    if row is not None and row.request_sha256 != fingerprint:
        fail("DUPLICATE_INTENT_CONFLICT", "request_rebound", "原请求已绑定其他内容。")
    return row


def _anchor(s, ctx, project, thread):
    if thread.subject_type == "project":
        return None
    return _subject(s, ctx, project, thread.subject_type, thread.subject_id)["revision"]


def _append(s, ctx, project, thread, data, fingerprint):
    """Insert one message and its first version; notify mentions and followers."""
    resolved = mentions.resolve(s, ctx, thread, project, data.body)
    _lock(s, f"discussion-thread:{thread.id}")
    sequence = (
        s.scalar(
            select(func.coalesce(func.max(DiscussionMessage.sequence), 0)).where(
                DiscussionMessage.tenant_id == ctx.tenant_id,
                DiscussionMessage.thread_id == thread.id,
            )
        )
        + 1
    )
    revision = _anchor(s, ctx, project, thread)
    at = now()
    row = DiscussionMessage(
        tenant_id=ctx.tenant_id,
        thread_id=thread.id,
        sequence=sequence,
        author_id=ctx.actor_id,
        revision=1,
        state="posted",
        body=data.body,
        mentions=resolved.stored,
        subject_revision=revision,
        updated_at=at,
        change_seq=0,
        request_key=data.request_key,
        request_sha256=fingerprint,
    )
    s.add(row)
    s.flush()
    s.add(
        DiscussionMessageVersion(
            tenant_id=ctx.tenant_id,
            message_id=row.id,
            thread_id=thread.id,
            revision=1,
            state="posted",
            body=data.body,
            mentions=resolved.stored,
            subject_revision=revision,
            editor_id=ctx.actor_id,
            request_key=data.request_key,
            request_sha256=fingerprint,
        )
    )
    s.flush()
    kind, target = _follow_target(thread)
    notifications.follow(
        s,
        ctx,
        ctx.actor_id,
        kind,
        target,
        project.id,
        "created" if sequence == 1 and thread.author_id == ctx.actor_id else "commented",
    )
    _notify(s, ctx, project, thread, row, resolved.recipients, first=sequence == 1)
    s.refresh(row)
    return row


def _notify(s, ctx, project, thread, row, mentioned, *, first):
    latest = {"message_id": str(row.id), "sequence": row.sequence}
    for person in sorted(mentioned, key=str):
        # A mention follows only this thread, not the whole object (§7.2, Linear).
        notifications.follow(s, ctx, person, "thread", thread.id, project.id, "mentioned")
        notifications.emit(
            s,
            ctx,
            person,
            "mention",
            "mention",
            project_id=project.id,
            kind="thread",
            subject_id=thread.id,
            thread_id=thread.id,
            latest=latest,
        )
    notifications.emit_followers(
        s,
        ctx,
        _targets(thread),
        "topic" if first and thread.subject_type == "project" else "comment",
        project_id=project.id,
        kind="thread",
        subject_id=thread.id,
        thread_id=thread.id,
        latest=latest,
        important=not (first and thread.subject_type == "project"),
        exclude=[ctx.actor_id, *mentioned],
    )


def start_topic(s, ctx, product_id, project_id, data: NewTopic):
    project = _project(s, ctx, product_id, project_id, write=True, lane=None)
    if not _full(s, ctx, project):
        raise DomainError("FORBIDDEN_SCOPE", "项目讨论只对项目受众可见。", 403)
    fingerprint = digest({"project_id": str(project.id), **data.model_dump(mode="json")})
    _lock(s, f"discussion-request:{ctx.tenant_id}:{ctx.actor_id}:{data.request_key}")
    prior = _prior(
        s, ctx, DiscussionThread, DiscussionThread.author_id, data.request_key, fingerprint
    )
    if prior is not None:
        return _thread_view(s, ctx, project, prior)
    row = DiscussionThread(
        tenant_id=ctx.tenant_id,
        category_id=project.category_id,
        product_id=project.product_id,
        project_id=project.id,
        subject_type="project",
        subject_id=project.id,
        title=data.title,
        author_id=ctx.actor_id,
        request_key=data.request_key,
        request_sha256=fingerprint,
    )
    s.add(row)
    s.flush()
    _append(
        s, ctx, project, row, NewMessage(body=data.body, request_key=data.request_key), fingerprint
    )
    return _thread_view(s, ctx, project, row)


def _reply(s, ctx, project, thread, data):
    fingerprint = digest({"thread_id": str(thread.id), **data.model_dump(mode="json")})
    _lock(s, f"discussion-request:{ctx.tenant_id}:{ctx.actor_id}:{data.request_key}")
    prior = _prior(
        s, ctx, DiscussionMessage, DiscussionMessage.author_id, data.request_key, fingerprint
    )
    if prior is None:
        _append(s, ctx, project, thread, data, fingerprint)
    elif prior.thread_id != thread.id:
        fail("DUPLICATE_INTENT_CONFLICT", "request_rebound", "原请求属于另一个讨论。")
    return _thread_view(s, ctx, project, thread, full=_full(s, ctx, project))


def post(s, ctx, product_id, project_id, thread_id, data: NewMessage):
    project = _project(s, ctx, product_id, project_id, write=True)
    row = _thread(s, ctx, project, thread_id)
    return _reply(s, ctx, project, row, data)


def comment(s, ctx, product_id, project_id, subject_type, subject_id, data: NewMessage):
    if subject_type not in OBJECT_TYPES:
        raise DomainError("VALIDATION_FAILED", "不支持在此类对象下评论。", 422)
    project = _project(
        s, ctx, product_id, project_id, write=True, lane=_lane(subject_type, subject_id)
    )
    if subject_type == "artifact" and not _full(s, ctx, project):
        raise DomainError("FORBIDDEN_SCOPE", "文档不在当前受众内。", 403)
    _subject(s, ctx, project, subject_type, subject_id)
    _lock(s, f"discussion-object:{ctx.tenant_id}:{project.id}:{subject_type}:{subject_id}")
    row = _object_thread(s, ctx, project, subject_type, subject_id)
    if row is None:
        row = DiscussionThread(
            tenant_id=ctx.tenant_id,
            category_id=project.category_id,
            product_id=project.product_id,
            project_id=project.id,
            subject_type=subject_type,
            subject_id=subject_id,
            title=None,
            author_id=ctx.actor_id,
            request_key=data.request_key,
            request_sha256=digest(
                {
                    "subject_type": subject_type,
                    "subject_id": str(subject_id),
                    "request_key": str(data.request_key),
                }
            ),
        )
        s.add(row)
        s.flush()
    return _reply(s, ctx, project, row, data)


def _message(s, ctx, thread, message_id):
    query = select(DiscussionMessage).where(
        DiscussionMessage.tenant_id == ctx.tenant_id,
        DiscussionMessage.thread_id == thread.id,
        DiscussionMessage.id == message_id,
    )
    row = s.scalar(query)
    if row is None:
        raise DomainError("FORBIDDEN_SCOPE", "消息不存在或权限已变化。", 403)
    if row.author_id != ctx.actor_id:
        fail("FORBIDDEN_SCOPE", "author_only", "只有作者本人可以编辑或撤回。", 403)
    # Only the author's own row passes the update policy, so the lock comes second.
    return s.scalar(query.with_for_update().execution_options(populate_existing=True))


def _revise(s, ctx, project, thread, message_id, data, *, retract):
    fingerprint = digest(
        {"message_id": str(message_id), "retract": retract, **data.model_dump(mode="json")}
    )
    _lock(s, f"discussion-request:{ctx.tenant_id}:{ctx.actor_id}:{data.request_key}")
    prior = _prior(
        s,
        ctx,
        DiscussionMessageVersion,
        DiscussionMessageVersion.editor_id,
        data.request_key,
        fingerprint,
    )
    if prior is not None:
        return _thread_view(s, ctx, project, thread, full=_full(s, ctx, project))
    row = _message(s, ctx, thread, message_id)
    if row.state == "retracted":
        fail("INVALID_STATE", "retracted", "消息已撤回，不能再编辑或撤回。")
    if row.revision != data.expected_revision:
        fail("VERSION_CONFLICT", "message_changed", "消息已被修改，请刷新后重试。")
    previous_people = {
        UUID(item["id"]) for item in row.mentions or () if item.get("kind") == "person"
    } | {UUID(value) for item in row.mentions or () for value in item.get("member_ids", ())}
    if retract:
        body, stored, recipients, revision = "", [], set(), row.subject_revision
    else:
        resolved = mentions.resolve(s, ctx, thread, project, data.body)
        body, stored, revision = data.body, resolved.stored, _anchor(s, ctx, project, thread)
        recipients = resolved.recipients - previous_people
    row.revision += 1
    row.state = "retracted" if retract else "edited"
    row.body = body
    row.mentions = stored
    row.subject_revision = revision
    row.updated_at = now()
    s.flush()
    s.refresh(row)
    s.add(
        DiscussionMessageVersion(
            tenant_id=ctx.tenant_id,
            message_id=row.id,
            thread_id=thread.id,
            revision=row.revision,
            state=row.state,
            body=body,
            mentions=stored,
            subject_revision=revision,
            editor_id=ctx.actor_id,
            request_key=data.request_key,
            request_sha256=fingerprint,
        )
    )
    s.flush()
    if recipients:
        # Only people newly mentioned by the edit hear about it; edits are not broadcast.
        latest = {"message_id": str(row.id), "sequence": row.sequence}
        for person in sorted(recipients, key=str):
            notifications.follow(s, ctx, person, "thread", thread.id, project.id, "mentioned")
            notifications.emit(
                s,
                ctx,
                person,
                "mention",
                "mention",
                project_id=project.id,
                kind="thread",
                subject_id=thread.id,
                thread_id=thread.id,
                latest=latest,
            )
    return _thread_view(s, ctx, project, thread, full=_full(s, ctx, project))


def _thread_for(s, ctx, product_id, project_id, thread_id):
    """Resolve a thread for a write; the lane reaches only an own task's thread."""
    project = _project(s, ctx, product_id, project_id, write=True)
    row = s.scalar(
        select(DiscussionThread).where(
            DiscussionThread.tenant_id == ctx.tenant_id,
            DiscussionThread.project_id == project.id,
            DiscussionThread.id == thread_id,
        )
    )
    if row is None:
        raise DomainError("FORBIDDEN_SCOPE", "讨论不存在或权限已变化。", 403)
    return project, row


def edit(s, ctx, product_id, project_id, thread_id, message_id, data: EditMessage):
    project, row = _thread_for(s, ctx, product_id, project_id, thread_id)
    return _revise(s, ctx, project, row, message_id, data, retract=False)


def retract(s, ctx, product_id, project_id, thread_id, message_id, data: RetractMessage):
    project, row = _thread_for(s, ctx, product_id, project_id, thread_id)
    return _revise(s, ctx, project, row, message_id, data, retract=True)


def set_follow(s, ctx, product_id, project_id, thread_id, data: FollowChange):
    project = _project(s, ctx, product_id, project_id, write=True)
    row = _thread(s, ctx, project, thread_id)
    kind, target = _follow_target(row)
    notifications.set_follow(s, ctx, "thread", row.id, project.id, data.followed)
    if kind != "thread":
        notifications.set_follow(s, ctx, kind, target, project.id, data.followed)
    return {"thread_id": str(row.id), "following": data.followed}


def mentionable(s, ctx, product_id, project_id, subject_type, subject_id):
    """Who can be @-mentioned here; people who cannot see the subject come back greyed."""
    from pdos_next.core.models import Grant
    from pdos_next.domain.projects.team import roles as catalog

    if subject_type != "project" and subject_type not in OBJECT_TYPES:
        raise DomainError("VALIDATION_FAILED", "不支持在此类对象下评论。", 422)
    project = _project(s, ctx, product_id, project_id, lane=None)
    if not _full(s, ctx, project):
        raise DomainError("FORBIDDEN_SCOPE", "项目讨论只对项目受众可见。", 403)
    probe = DiscussionThread(
        tenant_id=ctx.tenant_id,
        category_id=project.category_id,
        product_id=project.product_id,
        project_id=project.id,
        subject_type=subject_type,
        subject_id=project.id if subject_type == "project" else subject_id,
    )
    at = now()
    people = list(
        s.scalars(
            select(Principal)
            .join(
                Grant,
                (Grant.tenant_id == Principal.tenant_id) & (Grant.principal_id == Principal.id),
            )
            .where(
                Principal.tenant_id == ctx.tenant_id,
                Principal.kind == "human",
                Principal.active.is_(True),
                Grant.category_id == project.category_id,
                (Grant.expires_at.is_(None)) | (Grant.expires_at > at),
            )
            .order_by(Principal.name)
        )
    )
    members = mentions._current_members(s, ctx, project.id)
    names = catalog.names(s, ctx.tenant_id)
    held = {}
    for person, keys in members.items():
        for key in keys:
            held.setdefault(key, []).append(person)
    return {
        "people": [
            {
                "principal_id": str(row.id),
                "name": row.name,
                "is_member": row.id in members,
                "roles": sorted(names.get(key, key) for key in members.get(row.id, ())),
                "can_see": mentions.can_see(s, ctx, probe, row.id),
                "is_self": row.id == ctx.requester_id,
            }
            for row in people
        ],
        "roles": [
            {"key": key, "name": names.get(key, key), "members": len(values)}
            for key, values in sorted(held.items())
        ],
        "can_mention_all": ctx.requester_id == project.owner_id,
        "can_invite": ctx.requester_id == project.owner_id,
        "agent": {"available": False, "note": "在讨论中 @小Pai 将随 W6 ⑥ 开放。"},
    }


def notification_text(s, ctx, row):
    """Title and snippet for a thread notification, read now under the reader's access."""
    thread = s.scalar(
        select(DiscussionThread).where(
            DiscussionThread.tenant_id == ctx.tenant_id, DiscussionThread.id == row.subject_id
        )
    )
    if thread is None:
        return {"title": "讨论", "snippet": None, "target": None}
    if thread.subject_type == "project":
        title = thread.title
    else:
        title = f"{OBJECT_TYPES[thread.subject_type]}评论"
        try:
            project = s.get(Project, thread.project_id)
            title = f"{OBJECT_TYPES[thread.subject_type]}「"
            title += _subject(s, ctx, project, thread.subject_type, thread.subject_id)["title"]
            title += "」的评论"
        except DomainError:
            pass
    snippet = None
    message_id = (row.latest or {}).get("message_id")
    if message_id:
        message = s.scalar(
            select(DiscussionMessage).where(
                DiscussionMessage.tenant_id == ctx.tenant_id,
                DiscussionMessage.id == UUID(message_id),
            )
        )
        if message is not None:
            snippet = RETRACTED if message.state == "retracted" else message.body[:140]
    return {
        "title": title,
        "snippet": snippet,
        "target": {
            "view": "tasks" if thread.subject_type == "work_task" else "now",
            "thread_id": str(thread.id),
            "subject_type": thread.subject_type,
            "subject_id": str(thread.subject_id),
            "message_id": message_id,
        },
    }


def export_rows(s, ctx, project_id):
    """Every thread and message the reader can see now, for the project export (D279)."""
    threads = list(
        s.scalars(
            select(DiscussionThread)
            .where(
                DiscussionThread.tenant_id == ctx.tenant_id,
                DiscussionThread.project_id == project_id,
            )
            .order_by(DiscussionThread.created_at, DiscussionThread.id)
        )
    )
    if not threads:
        return []
    messages = list(
        s.scalars(
            select(DiscussionMessage)
            .where(
                DiscussionMessage.tenant_id == ctx.tenant_id,
                DiscussionMessage.thread_id.in_([row.id for row in threads]),
            )
            .order_by(DiscussionMessage.thread_id, DiscussionMessage.sequence)
        )
    )
    names = _people(s, ctx, {row.author_id for row in messages})
    by_thread = {}
    for message in messages:
        by_thread.setdefault(message.thread_id, []).append(message)
    project = s.get(Project, project_id)
    rows = []
    for thread in threads:
        if thread.subject_type == "project":
            where = f"项目讨论：{thread.title}"
        else:
            try:
                title = _subject(s, ctx, project, thread.subject_type, thread.subject_id)["title"]
            except DomainError:
                continue
            where = f"{OBJECT_TYPES[thread.subject_type]}：{title}"
        for message in by_thread.get(thread.id, ()):
            rows.append(
                {
                    "thread": where,
                    "sequence": message.sequence,
                    "author": names.get(message.author_id, "成员"),
                    "body": RETRACTED if message.state == "retracted" else message.body,
                    "state": {"posted": "已发表", "edited": "已编辑", "retracted": RETRACTED}[
                        message.state
                    ],
                    "subject_revision": message.subject_revision,
                    "created_at": message.created_at.isoformat(),
                    "updated_at": message.updated_at.isoformat(),
                }
            )
    return rows
