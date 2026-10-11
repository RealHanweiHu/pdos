"""Bounded history pages; cursors select rows, never authorize their scope."""

import base64
import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import literal, tuple_

from pdos_next.errors import DomainError

PAGE_SIZE = 50
KINDS = {"candidate", "rule", "observation", "review"}


def page_query(query, created_at, identity, kind, cursor=None, *, kinds=KINDS):
    kind_column = literal(kind) if isinstance(kind, str) else kind
    if cursor is not None:
        try:
            raw = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
            if not isinstance(raw, list) or len(raw) != 3:
                raise ValueError
            at, key, selected = datetime.fromisoformat(raw[0]), UUID(raw[1]), raw[2]
            if at.tzinfo is None or selected not in kinds:
                raise ValueError
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise DomainError(
                "INVALID_REQUEST", "历史分页游标无法核对，请重新读取。", 422
            ) from None
        query = query.where(tuple_(created_at, identity, kind_column) < tuple_(at, key, selected))
    return query.order_by(created_at.desc(), identity.desc(), kind_column.desc()).limit(
        PAGE_SIZE + 1
    )


def page_rows(rows, kind, *, kinds=KINDS):
    values = list(rows)
    page = values[:PAGE_SIZE]
    next_cursor = None
    if len(values) > PAGE_SIZE:
        last = page[-1]
        label = kind if kind in kinds else getattr(last, kind)
        raw = json.dumps([last.created_at.isoformat(), str(last.id), label], separators=(",", ":"))
        next_cursor = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
    return page, {"next_cursor": next_cursor}
