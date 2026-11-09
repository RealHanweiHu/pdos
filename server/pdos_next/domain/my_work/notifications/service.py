"""In-app notifications: emitting, reading, state, settings and the live cursor.

Writes to other people's notifications only happen inside the SQL functions
(`notification_emit`, `notification_emit_followers`), which drop the operator,
re-check that the recipient can see the subject now, apply mute and level, and
merge a repeat within the window. A row stores no content; the text shown is
read from the subject under the reader's own access every time.
"""

from datetime import timedelta
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import func, or_, select, text

from pdos_next.core.clock import now
from pdos_next.core.database import require_context
from pdos_next.core.models import Category, Principal
from pdos_next.core.schema_base import StrictModel
from pdos_next.domain.categories.preproject.access import human
from pdos_next.domain.projects.models import Project
from pdos_next.errors import DomainError

from .models import Notification, NotificationPreference

# P41-9 tenant default: changes to the same subject within 10 minutes merge into one.
MERGE_WINDOW_SECONDS = 600
SNOOZE_MAX = timedelta(days=30)
CATEGORY_LABELS = {
    "mention": "提及我",
    "assigned": "分派给我",
    "decide": "要我确认或决定",
    "agent": "小Pai 需要我",
    "follow": "关注的变化",
}
REASON_LABELS = {
    "mention": "在讨论中提及了你",
    "comment": "发表了评论",
    "topic": "发起了讨论",
    "task.assigned": "把任务分派给你",
    "task.accepted": "承接了任务",
    "task.started": "开始了任务",
    "task.submitted": "提交了成果，等你验收",
    "task.reviewed": "验收了任务",
    "commitment.accepted": "作出了承诺",
    "project.status_updated": "发布了状态更新",
    "member.deactivated": "账号已停用，有待接事项",
}


def emit(
    s,
    ctx,
    recipient,
    category,
    reason,
    *,
    project_id,
    kind,
    subject_id,
    thread_id=None,
    latest=None,
    important=True,
):
    s.flush()
    return s.scalar(
        text(
            "SELECT notification_emit(:t, :recipient, :category, :reason, :important, :project, "
            ":kind, :subject, :thread, CAST(:latest AS jsonb), :window)"
        ),
        {
            "t": ctx.tenant_id,
            "recipient": recipient,
            "category": category,
            "reason": reason,
            "important": important,
            "project": project_id,
            "kind": kind,
            "subject": subject_id,
            "thread": thread_id,
            "latest": _json(latest or {}),
            "window": MERGE_WINDOW_SECONDS,
        },
    )


def emit_followers(
    s,
    ctx,
    targets,
    reason,
    *,
    project_id,
    kind,
    subject_id,
    thread_id=None,
    latest=None,
    important=True,
    exclude=(),
):
    """Notify everyone following any of `targets` [(kind, id)], each person once."""
    s.flush()
    return s.scalar(
        text(
            "SELECT notification_emit_followers(:t, CAST(:kinds AS text[]), "
            "CAST(:targets AS uuid[]), 'follow', :reason, :important, :project, :kind, "
            ":subject, :thread, "
            "CAST(:latest AS jsonb), :window, CAST(:exclude AS uuid[]))"
        ),
        {
            "t": ctx.tenant_id,
            "kinds": [value[0] for value in targets],
            "targets": [str(value[1]) for value in targets],
            "reason": reason,
            "important": important,
            "project": project_id,
            "kind": kind,
            "subject": subject_id,
            "thread": thread_id,
            "latest": _json(latest or {}),
            "window": MERGE_WINDOW_SECONDS,
            "exclude": [str(value) for value in exclude],
        },
    )


def follow(s, ctx, person, kind, target_id, project_id, reason):
    """Automatic follow (§8): never overrides the person's own unfollow."""
    s.flush()
    return s.scalar(
        text("SELECT discussion_follow_set(:t, :person, :kind, :target, :project, :reason, false)"),
        {
            "t": ctx.tenant_id,
            "person": person,
            "kind": kind,
            "target": target_id,
            "project": project_id,
            "reason": reason,
        },
    )


def set_follow(s, ctx, kind, target_id, project_id, followed):
    s.flush()
    s.execute(
        text("SELECT discussion_follow_set(:t, :person, :kind, :target, :project, :reason, true)"),
        {
            "t": ctx.tenant_id,
            "person": ctx.requester_id,
            "kind": kind,
            "target": target_id,
            "project": project_id,
            "reason": "follow" if followed else "unfollow",
        },
    )


def _json(value):
    import json

    return json.dumps(value, ensure_ascii=False, default=str)


def _personal(s, ctx):
    require_context(s, ctx)
    human(s, ctx)
    if ctx.category_id is not None:
        raise DomainError("FORBIDDEN_SCOPE", "请使用本人收件箱。", 403)


# Reading ---------------------------------------------------------------------

View = Literal["inbox", "snoozed", "archived", "digest"]


class Query(StrictModel):
    view: View = "inbox"
    category: Literal["mention", "assigned", "decide", "agent", "follow"] | None = None
    unread: bool = False
    before: int | None = Field(default=None, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)


def _names(s, ctx, ids):
    ids = {value for value in ids if value}
    if not ids:
        return {}
    return {
        row.id: row.name
        for row in s.scalars(
            select(Principal).where(Principal.tenant_id == ctx.tenant_id, Principal.id.in_(ids))
        )
    }


def _subject_text(s, ctx, row, names):
    """Title and snippet read now from the subject, under the reader's own access."""
    from pdos_next.domain.projects.discussions import service as discussions

    if row.subject_kind == "thread":
        return discussions.notification_text(s, ctx, row)
    if row.subject_kind == "work_task":
        from pdos_next.domain.projects.work.models import WorkTaskCurrent, WorkTaskVersion

        pointer = s.scalar(
            select(WorkTaskCurrent).where(
                WorkTaskCurrent.tenant_id == ctx.tenant_id,
                WorkTaskCurrent.task_id == row.subject_id,
            )
        )
        version = s.get(WorkTaskVersion, pointer.version_id) if pointer else None
        title = (version.body or {}).get("title") if version else None
        return {"title": title or "任务", "snippet": None, "target": {"view": "tasks"}}
    if row.subject_kind == "member_handover":
        latest = row.latest or {}
        parts = [
            f"{label} {latest.get(key, 0)}"
            for key, label in (
                ("tasks", "任务"),
                ("commitments", "承诺"),
                ("external_waits", "外部等待"),
            )
            if latest.get(key)
        ]
        person = names.get(row.subject_id, "成员")
        return {
            "title": f"{person} 的待接事项",
            "snippet": "、".join(parts) or None,
            "target": {"view": "team"},
        }
    return {"title": "项目动态", "snippet": None, "target": {"view": "now"}}


def item_view(s, ctx, row, names, projects):
    project = projects.get(row.project_id)
    body = _subject_text(s, ctx, row, names)
    actors = [names.get(identity, "成员") for identity in row.actor_ids]
    return {
        "id": str(row.id),
        "category": row.category,
        "category_label": CATEGORY_LABELS[row.category],
        "reason": row.reason,
        "reason_label": REASON_LABELS.get(row.reason, "有新变化"),
        "subject_kind": row.subject_kind,
        "subject_id": str(row.subject_id),
        "thread_id": str(row.thread_id) if row.thread_id else None,
        "project": {
            "id": str(row.project_id),
            "name": project.name if project else "项目",
            "category_id": str(row.category_id),
            "product_id": str(project.product_id) if project else None,
        },
        "actors": actors,
        "event_count": row.event_count,
        "first_at": row.first_at.isoformat(),
        "last_at": row.last_at.isoformat(),
        "read": row.read_at is not None,
        "snoozed_until": row.snoozed_until.isoformat() if row.snoozed_until else None,
        "archived": row.archived_at is not None,
        "delivery": row.delivery,
        "change_seq": row.change_seq,
        **body,
    }


def listing(s, ctx, query: Query):
    _personal(s, ctx)
    at = now()
    rows = select(Notification).where(
        Notification.tenant_id == ctx.tenant_id, Notification.recipient_id == ctx.requester_id
    )
    if query.view == "archived":
        rows = rows.where(Notification.archived_at.is_not(None))
    else:
        rows = rows.where(Notification.archived_at.is_(None))
        if query.view == "snoozed":
            rows = rows.where(Notification.snoozed_until > at)
        else:
            rows = rows.where(
                or_(Notification.snoozed_until.is_(None), Notification.snoozed_until <= at),
                Notification.delivery == ("digest" if query.view == "digest" else "instant"),
            )
            if query.view == "digest":
                # The daily digest holds unread follow changes only (§8).
                rows = rows.where(Notification.read_at.is_(None))
    if query.category:
        rows = rows.where(Notification.category == query.category)
    if query.unread:
        rows = rows.where(Notification.read_at.is_(None))
    if query.before is not None:
        rows = rows.where(Notification.change_seq < query.before)
    found = list(
        s.scalars(rows.order_by(Notification.change_seq.desc()).limit(query.page_size + 1))
    )
    page = found[: query.page_size]
    names = _names(
        s,
        ctx,
        {identity for row in page for identity in row.actor_ids}
        | {row.subject_id for row in page if row.subject_kind == "member_handover"},
    )
    projects = {
        row.id: row
        for row in s.scalars(
            select(Project).where(
                Project.tenant_id == ctx.tenant_id,
                Project.id.in_({row.project_id for row in page} or {UUID(int=0)}),
            )
        )
    }
    counts = dict(
        s.execute(
            select(Notification.category, func.count())
            .where(
                Notification.tenant_id == ctx.tenant_id,
                Notification.recipient_id == ctx.requester_id,
                Notification.read_at.is_(None),
                Notification.archived_at.is_(None),
                Notification.delivery == "instant",
                or_(Notification.snoozed_until.is_(None), Notification.snoozed_until <= at),
            )
            .group_by(Notification.category)
        ).all()
    )
    return {
        "items": [item_view(s, ctx, row, names, projects) for row in page],
        "next_before": page[-1].change_seq if len(found) > query.page_size else None,
        "unread": {key: counts.get(key, 0) for key in CATEGORY_LABELS},
        "cursor": cursor(s, ctx)["cursor"],
        "merge_window_minutes": MERGE_WINDOW_SECONDS // 60,
    }


# State -------------------------------------------------------------------------


class StateChange(StrictModel):
    notification_ids: list[UUID] = Field(default_factory=list, max_length=100)
    action: Literal["read", "unread", "archive", "restore", "snooze", "unsnooze", "read_all"]
    snooze_until: str | None = None
    category: Literal["mention", "assigned", "decide", "agent", "follow"] | None = None

    @model_validator(mode="after")
    def shape(self):
        if self.action == "read_all":
            if self.notification_ids:
                raise ValueError("全部已读不指定单条通知")
        elif not self.notification_ids:
            raise ValueError("请选择通知")
        if (self.action == "snooze") != (self.snooze_until is not None):
            raise ValueError("稍后提醒需要提醒时间")
        return self


def _until(value):
    from datetime import UTC, datetime

    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise DomainError("VALIDATION_FAILED", "提醒时间无效。", 422) from error
    if moment.tzinfo is None:
        raise DomainError("VALIDATION_FAILED", "提醒时间须带时区。", 422)
    moment = moment.astimezone(UTC)
    at = now()
    if moment <= at or moment - at > SNOOZE_MAX:
        raise DomainError("VALIDATION_FAILED", "提醒时间须在现在之后、30 天之内。", 422)
    return moment


def change_state(s, ctx, data: StateChange):
    _personal(s, ctx)
    at = now()
    query = select(Notification).where(
        Notification.tenant_id == ctx.tenant_id, Notification.recipient_id == ctx.requester_id
    )
    if data.action == "read_all":
        query = query.where(
            Notification.read_at.is_(None),
            Notification.archived_at.is_(None),
            or_(Notification.snoozed_until.is_(None), Notification.snoozed_until <= at),
        )
        if data.category:
            query = query.where(Notification.category == data.category)
    else:
        query = query.where(Notification.id.in_(data.notification_ids))
    rows = list(s.scalars(query.with_for_update()))
    if data.action != "read_all" and len(rows) != len(set(data.notification_ids)):
        raise DomainError("FORBIDDEN_SCOPE", "通知不可读或权限已变化，请刷新。", 403)
    until = _until(data.snooze_until) if data.action == "snooze" else None
    for row in rows:
        if data.action in {"read", "read_all"}:
            row.read_at = row.read_at or at
        elif data.action == "unread":
            row.read_at = None
        elif data.action == "archive":
            row.archived_at = row.archived_at or at
            row.read_at = row.read_at or at
        elif data.action == "restore":
            row.archived_at = None
        elif data.action == "snooze":
            # D73: hidden until then, and back as unread at that time.
            row.snoozed_until = until
            row.read_at = None
        elif data.action == "unsnooze":
            row.snoozed_until = None
    s.flush()
    return {"updated": len(rows), "cursor": cursor(s, ctx)["cursor"]}


# Settings ----------------------------------------------------------------------


class Preference(StrictModel):
    project_id: UUID
    level: Literal["all", "important", "mentions"]
    muted: bool
    digest: bool
    expected_revision: int = Field(ge=0)


def _preference_view(row, project):
    return {
        "project_id": str(project.id),
        "project_name": project.name,
        "level": row.level if row else "all",
        "muted": row.muted if row else False,
        "digest": row.digest if row else False,
        "revision": row.revision if row else 0,
    }


def preferences(s, ctx, project_id):
    _personal(s, ctx)
    project = s.scalar(
        select(Project).where(Project.tenant_id == ctx.tenant_id, Project.id == project_id)
    )
    if project is None:
        raise DomainError("FORBIDDEN_SCOPE", "项目不可读或权限已变化。", 403)
    row = s.scalar(
        select(NotificationPreference).where(
            NotificationPreference.tenant_id == ctx.tenant_id,
            NotificationPreference.principal_id == ctx.requester_id,
            NotificationPreference.project_id == project_id,
        )
    )
    return {
        **_preference_view(row, project),
        "levels": {
            "all": "全部",
            "important": "重要变化（状态、负责人、日期和评论）",
            "mentions": "只看提及",
        },
        # P98: mute stops follow changes and the digest; mentions, assignments, decisions arrive.
        "mute_scope": "follow_only",
    }


def save_preference(s, ctx, data: Preference):
    _personal(s, ctx)
    project = s.scalar(
        select(Project).where(Project.tenant_id == ctx.tenant_id, Project.id == data.project_id)
    )
    if project is None:
        raise DomainError("FORBIDDEN_SCOPE", "项目不可读或权限已变化。", 403)
    s.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": f"notification-preference:{ctx.tenant_id}:{ctx.requester_id}:{project.id}"},
    )
    row = s.scalar(
        select(NotificationPreference)
        .where(
            NotificationPreference.tenant_id == ctx.tenant_id,
            NotificationPreference.principal_id == ctx.requester_id,
            NotificationPreference.project_id == project.id,
        )
        .with_for_update()
    )
    if (row.revision if row else 0) != data.expected_revision:
        raise DomainError("VERSION_CONFLICT", "通知设置已变化，请刷新后重试。")
    if row is None:
        row = NotificationPreference(
            tenant_id=ctx.tenant_id,
            principal_id=ctx.requester_id,
            project_id=project.id,
            level=data.level,
            muted=data.muted,
            digest=data.digest,
            revision=1,
            updated_at=now(),
        )
        s.add(row)
    else:
        row.level, row.muted, row.digest = data.level, data.muted, data.digest
        row.revision += 1
    s.flush()
    return preferences(s, ctx, project.id)


# Live cursor (D74) -------------------------------------------------------------


def cursor(s, ctx, threads=()):
    """One token per stream: notifications changed, a snooze came due, or a thread moved."""
    at = now()
    latest = s.scalar(
        select(func.coalesce(func.max(Notification.change_seq), 0)).where(
            Notification.tenant_id == ctx.tenant_id,
            Notification.recipient_id == ctx.requester_id,
        )
    )
    due = s.scalar(
        select(func.count()).where(
            Notification.tenant_id == ctx.tenant_id,
            Notification.recipient_id == ctx.requester_id,
            Notification.snoozed_until.is_not(None),
            Notification.snoozed_until <= at,
            Notification.archived_at.is_(None),
        )
    )
    tokens = {}
    if threads:
        from pdos_next.domain.projects.discussions import service as discussions

        tokens = discussions.thread_tokens(s, ctx, threads)
    return {"cursor": f"{latest}.{due}", "threads": tokens}


def changes(s, ctx, since, threads):
    _personal(s, ctx)
    current = cursor(s, ctx, threads)
    return {**current, "changed": since != current["cursor"], "poll_seconds": 30}


def category_name(s, ctx, category_id):
    row = s.get(Category, category_id)
    return row.name if row else "品类"
