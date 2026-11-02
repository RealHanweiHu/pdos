"""Typed, metadata-only columns shared by personal attention source readers."""

from sqlalchemy import DateTime, Integer, String, cast, literal
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql.elements import ClauseElement

VERSION = "personal-attention/v1"
QUEUES = frozenset({"decide", "receive", "verify", "external"})


def columns(
    *,
    key,
    kind,
    queue,
    tenant_id,
    source_id,
    category_id,
    recorded_at,
    title,
    reason,
    state,
    responsible_id,
    responsibility,
    target,
    version_id=None,
    revision=None,
    epoch=None,
    product_id=None,
    project_id=None,
    owner_id=None,
    visibility=None,
    blocked_code=None,
    blocked_message=None,
    due_at=None,
    valid_until=None,
    details=None,
):
    """Normalize explicit leaf projections; this function never loads a document."""
    values = locals()
    types = {
        **{
            name: String()
            for name in (
                "key",
                "kind",
                "queue",
                "title",
                "reason",
                "state",
                "responsibility",
                "target",
                "visibility",
                "blocked_code",
                "blocked_message",
            )
        },
        **{
            name: UUID(as_uuid=True)
            for name in (
                "tenant_id",
                "source_id",
                "category_id",
                "responsible_id",
                "version_id",
                "product_id",
                "project_id",
                "owner_id",
            )
        },
        **{name: Integer() for name in ("revision", "epoch")},
        **{
            name: DateTime(timezone=True)
            for name in (
                "recorded_at",
                "due_at",
                "valid_until",
            )
        },
        "details": JSONB(),
    }
    return tuple(
        cast(
            value
            if isinstance(value, ClauseElement) or hasattr(value, "__clause_element__")
            else literal(value, type_=types[name]),
            types[name],
        ).label(name)
        for name in types
        for value in (values[name] if name != "details" or values[name] is not None else {},)
    )
