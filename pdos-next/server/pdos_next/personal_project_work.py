"""Personal current work heads under the caller's ordinary read-only RR/RLS scope."""

from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.orm import aliased

from pdos_next import models
from pdos_next.domain.projects.models import Project
from pdos_next.domain.work_fulfillment.models import WorkCommitmentReviewCurrent
from pdos_next.domain.work_management.models import (
    WorkCommitmentCurrent,
    WorkCommitmentVersion,
    WorkTaskCurrent,
    WorkTaskVersion,
)
from pdos_next.errors import DomainError
from pdos_next.personal_views import _personal

VERSION = "personal-project-work/v1"
QUEUES = frozenset({"receive", "verify", "tasks", "commitments"})
SCOPE = ("tenant_id", "category_id", "product_id", "project_id")
BINDING = (*SCOPE, "owner_id", "visibility")
TASK_STATES = {
    "receive": ("assigned",),
    "verify": ("submitted",),
    "tasks": ("accepted", "in_progress", "submitted"),
}


def _same(left, right, fields):
    return and_(*(getattr(left, key) == getattr(right, key) for key in fields))


def _records(ctx, queue):
    """Select current identity/configuration heads, never full frozen documents."""
    Category, Principal, Product = models.Category, models.Principal, models.Product
    task, pointer = WorkTaskVersion, WorkTaskCurrent
    commitment, commitment_pointer = WorkCommitmentVersion, WorkCommitmentCurrent
    assignee, recipient = aliased(Principal, name="assignee"), aliased(Principal, name="recipient")
    body_assignee = task.body["assignee_id"].astext
    recipient_id = (
        cast(commitment.recipient_id, String)
        if queue == "commitments"
        else task.body["recipient_id"].astext
    )
    heads = [
        ("task", task, ("id", *BINDING, "task_id", "revision", "state", "created_at")),
        ("pointer", pointer, ("id", *BINDING, "task_id", "version_id", "revision", "state")),
        ("category", Category, ("id", "tenant_id", "name")),
        ("product", Product, ("id", "tenant_id", "category_id", "name")),
        (
            "project",
            Project,
            ("id", "tenant_id", "category_id", "product_id", "owner_id", "visibility", "name"),
        ),
    ]
    if queue == "commitments":
        heads.extend(
            (
                (
                    "commitment",
                    commitment,
                    (
                        "id",
                        *BINDING,
                        "series_id",
                        "revision",
                        "task_id",
                        "task_revision",
                        "promisor_id",
                        "recipient_id",
                        "outcome_keys",
                        "promised_at",
                        "original_timezone",
                        "calendar_id",
                        "created_at",
                    ),
                ),
                (
                    "commitment_pointer",
                    commitment_pointer,
                    (
                        "id",
                        *BINDING,
                        "task_id",
                        "promisor_id",
                        "recipient_id",
                        "series_id",
                        "version_id",
                        "revision",
                    ),
                ),
            )
        )
    query = (
        select(
            *(
                getattr(model, key).label(f"{prefix}_{key}")
                for prefix, model, keys in heads
                for key in keys
            ),
            task.body["task_id"].astext.label("snapshot_task_id"),
            task.body["revision"].astext.label("snapshot_revision"),
            task.body["state"].astext.label("snapshot_state"),
            task.body["title"].astext.label("task_title"),
            body_assignee.label("assignee_id"),
            assignee.name.label("assignee_name"),
            recipient_id.label("recipient_id"),
            recipient.name.label("recipient_name"),
        )
        .select_from(pointer)
        .join(
            task,
            and_(
                _same(task, pointer, (*BINDING, "task_id", "revision", "state")),
                task.id == pointer.version_id,
            ),
        )
        .join(
            Product,
            and_(
                Product.tenant_id == task.tenant_id,
                Product.category_id == task.category_id,
                Product.id == task.product_id,
            ),
        )
        .join(Category, and_(Category.tenant_id == task.tenant_id, Category.id == task.category_id))
        .join(
            Project,
            and_(
                _same(
                    Project,
                    task,
                    ("tenant_id", "category_id", "product_id", "owner_id", "visibility"),
                ),
                Project.id == task.project_id,
            ),
        )
        .outerjoin(
            assignee,
            and_(assignee.tenant_id == task.tenant_id, cast(assignee.id, String) == body_assignee),
        )
    )
    if queue == "commitments":
        query = (
            query.join(
                commitment_pointer,
                and_(
                    _same(commitment_pointer, task, (*BINDING, "task_id")),
                    commitment_pointer.promisor_id == ctx.requester_id,
                ),
            )
            .join(
                commitment,
                and_(
                    _same(
                        commitment,
                        commitment_pointer,
                        (
                            *BINDING,
                            "task_id",
                            "promisor_id",
                            "recipient_id",
                            "series_id",
                            "revision",
                        ),
                    ),
                    commitment.id == commitment_pointer.version_id,
                ),
            )
            .where(
                commitment.promisor_id == ctx.requester_id,
                ~select(WorkCommitmentReviewCurrent.id)
                .where(
                    _same(WorkCommitmentReviewCurrent, commitment, BINDING),
                    WorkCommitmentReviewCurrent.commitment_id == commitment.id,
                    WorkCommitmentReviewCurrent.state == "fulfilled",
                )
                .exists(),
            )
        )
    else:
        query = query.where(task.state.in_(TASK_STATES[queue]))
        query = query.where(
            (task.body["recipient_id"].astext if queue == "verify" else body_assignee)
            == str(ctx.requester_id)
        )
    return query.outerjoin(
        recipient,
        and_(recipient.tenant_id == task.tenant_id, cast(recipient.id, String) == recipient_id),
    ).where(task.tenant_id == ctx.tenant_id)


def _invalid():
    raise DomainError("INTEGRITY_MISMATCH", "本人工作事项的当前版本或范围无法核对，请刷新。")


def _aware(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        _invalid()
    return value.astimezone(UTC)


def _uuid(value):
    try:
        return value if isinstance(value, UUID) else UUID(value)
    except (TypeError, ValueError, AttributeError):
        _invalid()


def _matches(row, prefix, values):
    if any(row[f"{prefix}_{key}"] != value for key, value in values.items()):
        _invalid()


def _person(identity, name):
    if identity is None:
        return None
    if name is not None and not isinstance(name, str):
        _invalid()
    return {"id": str(_uuid(identity)), "name": name}


def _entry(row, ctx, queue, as_of):
    binding = {key: row[f"task_{key}"] for key in BINDING}
    if binding["tenant_id"] != ctx.tenant_id or row["task_revision"] < 1:
        _invalid()
    _matches(
        row,
        "pointer",
        {
            **binding,
            "task_id": row["task_task_id"],
            "version_id": row["task_id"],
            "revision": row["task_revision"],
            "state": row["task_state"],
        },
    )
    _matches(row, "category", {"id": binding["category_id"], "tenant_id": ctx.tenant_id})
    _matches(
        row,
        "product",
        {
            "id": binding["product_id"],
            "tenant_id": ctx.tenant_id,
            "category_id": binding["category_id"],
        },
    )
    _matches(
        row,
        "project",
        {
            "id": binding["project_id"],
            **{
                key: binding[key]
                for key in ("tenant_id", "category_id", "product_id", "owner_id", "visibility")
            },
        },
    )
    if (
        _uuid(row["snapshot_task_id"]) != row["task_task_id"]
        or row["snapshot_revision"] != str(row["task_revision"])
        or row["snapshot_state"] != row["task_state"]
        or not isinstance(row["task_title"], str)
        or not row["task_title"].strip()
    ):
        _invalid()
    assignee, recipient = (
        _person(row["assignee_id"], row["assignee_name"]),
        _person(row["recipient_id"], row["recipient_name"]),
    )
    commitment, timing = None, None
    recorded = row["task_created_at"]
    identity = row["task_task_id"]
    if queue == "commitments":
        _matches(
            row,
            "commitment",
            {**binding, "task_id": row["task_task_id"], "promisor_id": ctx.requester_id},
        )
        _matches(
            row,
            "commitment_pointer",
            {
                **binding,
                "task_id": row["task_task_id"],
                "promisor_id": ctx.requester_id,
                "recipient_id": row["commitment_recipient_id"],
                "series_id": row["commitment_series_id"],
                "version_id": row["commitment_id"],
                "revision": row["commitment_revision"],
            },
        )
        if (
            row["task_state"]
            not in {"proposed", "assigned", "accepted", "in_progress", "submitted", "completed"}
            or not 1 <= row["commitment_task_revision"] <= row["task_revision"]
            or row["commitment_revision"] < 1
            or recipient is None
            or recipient["id"] != str(row["commitment_recipient_id"])
        ):
            _invalid()
        keys = row["commitment_outcome_keys"]
        if (
            not isinstance(keys, list)
            or not keys
            or any(not isinstance(key, str) or not key.strip() for key in keys)
            or len(keys) != len(set(keys))
        ):
            _invalid()
        try:
            ZoneInfo(row["commitment_original_timezone"])
        except (TypeError, ValueError, ZoneInfoNotFoundError):
            _invalid()
        promised = row["commitment_promised_at"]
        promised = _aware(promised) if promised is not None else None
        commitment = {
            "id": str(row["commitment_id"]),
            "revision": row["commitment_revision"],
            "task_revision": row["commitment_task_revision"],
            "promisor_id": str(row["commitment_promisor_id"]),
            "recipient_id": str(row["commitment_recipient_id"]),
            "outcome_keys": list(keys),
            "promised_at": promised.isoformat() if promised is not None else None,
            "original_timezone": row["commitment_original_timezone"],
            "calendar_id": str(row["commitment_calendar_id"])
            if row["commitment_calendar_id"] is not None
            else None,
        }
        # Date status alone cannot establish fulfillment, even after task completion.
        timing = "unknown" if promised is None else "overdue" if promised < as_of else "pending"
        identity, recorded = row["commitment_id"], row["commitment_created_at"]
    elif (
        row["task_state"] not in TASK_STATES[queue]
        or (recipient if queue == "verify" else assignee) is None
        or (recipient if queue == "verify" else assignee)["id"] != str(ctx.requester_id)
    ):
        _invalid()
    return {
        "id": str(identity),
        **{
            prefix: {"id": str(binding[f"{prefix}_id"]), "name": row[f"{prefix}_name"]}
            for prefix in ("category", "product", "project")
        },
        "task": {
            "id": str(row["task_task_id"]),
            "version_id": str(row["task_id"]),
            "revision": row["task_revision"],
            "state": row["task_state"],
            "title": row["task_title"],
        },
        "assignee": assignee,
        "recipient": recipient,
        "recorded_at": _aware(recorded).isoformat(),
        "commitment": commitment,
        "timing": timing,
    }


def read(s, ctx, queue, cursor=None, page_size=20):
    """Use one existing personal RR/RLS transaction; never open or mutate it."""
    _personal(s, ctx)
    if s.info.get("read_snapshot") is not True or s.info.get("scope") != (
        ctx.tenant_id,
        ctx.actor_id,
        ctx.requester_id,
        None,
    ):
        raise DomainError("FORBIDDEN_SCOPE", "本人工作队列须使用个人只读快照事务。", 403)
    if not isinstance(queue, str) or queue not in QUEUES:
        raise DomainError("VALIDATION_FAILED", "本人工作队列类型无效。", 422)
    if type(page_size) is not int or not 1 <= page_size <= 100:
        raise DomainError("VALIDATION_FAILED", "每页数量须为 1–100 的整数。", 422)
    if cursor is not None:
        try:
            cursor = cursor if isinstance(cursor, UUID) else UUID(cursor)
        except (TypeError, ValueError, AttributeError):
            raise DomainError("VALIDATION_FAILED", "分页位置须为此队列事项 UUID。", 422) from None
    as_of = _aware(s.scalar(select(func.transaction_timestamp())))
    records = _records(ctx, queue)
    identity, created = (
        (WorkCommitmentVersion.id, WorkCommitmentVersion.created_at)
        if queue == "commitments"
        else (WorkTaskVersion.task_id, WorkTaskVersion.created_at)
    )
    page = records
    if cursor is not None:
        anchor = s.execute(records.where(identity == cursor)).mappings().first()
        if anchor is None:
            raise DomainError("FORBIDDEN_SCOPE", "分页位置已不属于当前可读队列，请刷新。", 403)
        _entry(anchor, ctx, queue, as_of)
        anchor_created = anchor[
            "commitment_created_at" if queue == "commitments" else "task_created_at"
        ]
        page = page.where(
            or_(created < anchor_created, and_(created == anchor_created, identity < cursor))
        )
    total = s.scalar(select(func.count()).select_from(records.subquery()))
    rows = (
        s.execute(page.order_by(created.desc(), identity.desc()).limit(page_size + 1))
        .mappings()
        .all()
    )
    entries = [_entry(row, ctx, queue, as_of) for row in rows]
    visible = entries[:page_size]
    return {
        "version": VERSION,
        "principal_id": str(ctx.requester_id),
        "as_of": as_of.isoformat(),
        "queue": queue,
        "total_records": total,
        "items": visible,
        "next_cursor": visible[-1]["id"] if len(entries) > page_size else None,
    }
