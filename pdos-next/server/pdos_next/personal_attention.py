"""Read-only attention derived from current business facts in one personal RR scope."""

import base64
import binascii
import json
from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select, union_all

from pdos_next import models as registered_models  # noqa: F401 -- registry before domain children
from pdos_next.domain.projects.models import Project
from pdos_next.errors import DomainError
from pdos_next.models import Category, Principal, Product
from pdos_next.personal_attention_common import QUEUES, VERSION
from pdos_next.personal_views import _personal


def records(ctx, queue):
    from pdos_next import (
        personal_attention_decisions,
        personal_attention_external_wait,
        personal_attention_project_risk,
        personal_attention_verification,
        personal_attention_work,
    )

    sources = union_all(
        *(
            query
            for adapter in (
                personal_attention_work,
                personal_attention_external_wait,
                personal_attention_project_risk,
                personal_attention_decisions,
                personal_attention_verification,
            )
            for query in adapter.queries(ctx, queue)
        )
    ).subquery("attention_sources")
    c = sources.c
    return (
        select(
            *c,
            Category.name.label("category_name"),
            Product.name.label("product_name"),
            Project.name.label("project_name"),
            Principal.name.label("responsible_name"),
        )
        .select_from(sources)
        .join(
            Category,
            and_(
                Category.tenant_id == c.tenant_id,
                Category.id == c.category_id,
            ),
        )
        .outerjoin(
            Product,
            and_(
                Product.tenant_id == c.tenant_id,
                Product.category_id == c.category_id,
                Product.id == c.product_id,
            ),
        )
        .outerjoin(
            Project,
            and_(
                Project.tenant_id == c.tenant_id,
                Project.category_id == c.category_id,
                Project.product_id == c.product_id,
                Project.id == c.project_id,
                or_(c.owner_id.is_(None), Project.owner_id == c.owner_id),
                or_(c.visibility.is_(None), Project.visibility == c.visibility),
            ),
        )
        .join(
            Principal,
            and_(
                Principal.tenant_id == c.tenant_id,
                Principal.id == c.responsible_id,
            ),
        )
        .where(
            c.tenant_id == ctx.tenant_id,
            c.responsible_id == ctx.requester_id,
            c.queue == queue,
            or_(c.product_id.is_(None), Product.id.is_not(None)),
            or_(c.project_id.is_(None), Project.id.is_not(None)),
        )
    )


def _invalid():
    raise DomainError("VERSION_CONFLICT", "注意项的来源或当前责任无法核对，请刷新。")


def _time(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        _invalid()
    return value.astimezone(UTC).isoformat()


def entry(row, ctx, queue):
    if (
        row["tenant_id"] != ctx.tenant_id
        or row["responsible_id"] != ctx.requester_id
        or row["queue"] != queue
        or row["target"] not in {"proposal", "project"}
    ):
        _invalid()
    for field in ("key", "kind", "title", "reason", "state", "responsibility"):
        if not isinstance(row[field], str) or not row[field].strip():
            _invalid()
    if row["target"] == "project" and row["project_id"] is None:
        _invalid()
    for field in ("revision", "epoch"):
        if row[field] is not None and (type(row[field]) is not int or row[field] < 1):
            _invalid()
    if bool(row["blocked_code"]) != bool(row["blocked_message"]):
        _invalid()
    result = {
        "id": row["key"],
        "kind": row["kind"],
        "queue": queue,
        "source": {
            "id": str(row["source_id"]),
            "version_id": str(row["version_id"]) if row["version_id"] else None,
            "revision": row["revision"],
            "epoch": row["epoch"],
        },
        "responsible": {"id": str(row["responsible_id"]), "name": row["responsible_name"]},
        **{
            key: row[key]
            for key in ("title", "reason", "state", "responsibility", "target", "details")
        },
        **{key: _time(row[key]) if row[key] else None for key in ("due_at", "valid_until")},
        "recorded_at": _time(row["recorded_at"]),
        "blocked": {"code": row["blocked_code"], "message": row["blocked_message"]}
        if row["blocked_code"]
        else None,
    }
    for kind in ("category", "product", "project"):
        result[kind] = (
            {"id": str(row[kind + "_id"]), "name": row[kind + "_name"]}
            if row[kind + "_id"]
            else None
        )
    return result


def _watermark(row):
    return [
        str(row["version_id"]) if row["version_id"] else None,
        row["revision"],
        row["epoch"],
        _time(row["recorded_at"]),
    ]


def _cursor(ctx, queue, row):
    data = [VERSION, str(ctx.tenant_id), str(ctx.requester_id), queue, row["key"], _watermark(row)]
    return (
        base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode())
        .decode()
        .rstrip("=")
    )


def _decode(cursor, ctx, queue):
    try:
        if not isinstance(cursor, str) or not 1 <= len(cursor) <= 2048:
            raise ValueError()
        data = json.loads(
            base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        )
        if (
            not isinstance(data, list)
            or len(data) != 6
            or data[:4] != [VERSION, str(ctx.tenant_id), str(ctx.requester_id), queue]
            or not isinstance(data[4], str)
            or not isinstance(data[5], list)
            or len(data[5]) != 4
        ):
            raise ValueError()
        return data[4], data[5]
    except (ValueError, TypeError, binascii.Error, UnicodeDecodeError, RecursionError):
        raise DomainError(
            "VALIDATION_FAILED", "分页位置不属于当前本人队列，请刷新。", 422
        ) from None


def read(s, ctx, queue, cursor=None, page_size=20):
    _personal(s, ctx)
    if (
        s.info.get("read_snapshot") is not True
        or s.info.get("scope") != (ctx.tenant_id, ctx.actor_id, ctx.requester_id, None)
        or ctx.agent_run_id is not None
        or ctx.run_id is not None
    ):
        raise DomainError("FORBIDDEN_SCOPE", "注意项须使用本人只读快照事务。", 403)
    if queue not in QUEUES or type(page_size) is not int or not 1 <= page_size <= 100:
        raise DomainError("VALIDATION_FAILED", "注意项分组或每页数量无效。", 422)
    page = records(ctx, queue).subquery("current_attention")
    query = select(page)
    if cursor is not None:
        key, watermark = _decode(cursor, ctx, queue)
        anchor = s.execute(query.where(page.c.key == key)).mappings().one_or_none()
        if anchor is None or _watermark(anchor) != watermark:
            raise DomainError("FORBIDDEN_SCOPE", "分页来源已变化或不可读，请刷新队列。", 403)
        query = query.where(
            or_(
                page.c.recorded_at < anchor["recorded_at"],
                and_(page.c.recorded_at == anchor["recorded_at"], page.c.key < key),
            )
        )
    total = s.scalar(select(func.count()).select_from(page))
    rows = list(
        s.execute(
            query.order_by(page.c.recorded_at.desc(), page.c.key.desc()).limit(page_size + 1)
        ).mappings()
    )
    selected = rows[:page_size]
    return {
        "version": VERSION,
        "principal_id": str(ctx.requester_id),
        "queue": queue,
        "items": [entry(row, ctx, queue) for row in selected],
        "total_records": total,
        "next_cursor": _cursor(ctx, queue, selected[-1]) if len(rows) > page_size else None,
        "as_of": _time(s.scalar(select(func.transaction_timestamp()))),
    }
