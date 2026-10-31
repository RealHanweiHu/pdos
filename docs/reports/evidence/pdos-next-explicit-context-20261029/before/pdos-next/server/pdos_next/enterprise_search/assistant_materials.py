"""Sign only server-pinned material versions, without waiting for a derived index."""

from uuid import UUID

from sqlalchemy import func, select

from pdos_next.agent_kernel.models import AgentRun

from . import assistant_ledger as ledger
from .assistant_sources import current
from .indexing import _locator
from .sources import select_sources


def read(session, scope, data, call_id):
    run = session.get(AgentRun, scope.run_id)
    pinned = {ref["artifact_id"]: ref["expected_revision"] for ref in run.read_sources}
    ids = list(dict.fromkeys(str(identity) for identity in data.artifact_ids))
    if set(ids) - set(pinned):
        ledger.deny("material_not_pinned")
    source = select_sources(source_type="artifact", include_body=True).subquery()
    fields = [column for column in source.c if column.key not in {"body", "structured"}]
    rows = (
        session.execute(
            select(
                *fields,
                func.length(source.c.body).label("body_chars"),
                func.transaction_timestamp().label("as_of"),
            ).where(
                source.c.tenant_id == scope.tenant_id,
                source.c.source_id.in_([UUID(identity) for identity in ids]),
            )
        )
        .mappings()
        .all()
    )
    candidates = {}
    for row in rows:
        identity = str(row["source_id"])
        if row["source_revision"] != pinned[identity]:
            continue
        item = {
            key: str(value) if isinstance(value, UUID) else value
            for key, value in row.items()
            if key
            not in {"as_of", "created_at", "original_ids", "original_id", "owner_id", "body_chars"}
        }
        item["locator"] = _locator(0, row["body_chars"], 1, 1, None)
        candidates[identity] = item
    actual, missing = current(session, candidates)
    items = []
    for identity in ids:
        if identity not in actual:
            continue
        item = candidates[identity]
        item.update(
            private=actual[identity]["private"],
            customer_original=actual[identity]["customer_original"],
        )
        item["citation_id"] = ledger.citation_id(scope.run_id, call_id, item)
        items.append(item)
    return {
        "items": items,
        "returned": len(items),
        "as_of": rows[0]["as_of"].isoformat() if rows else None,
        "coverage": {"status": "current" if len(items) == len(ids) and not missing else "partial"},
    }
