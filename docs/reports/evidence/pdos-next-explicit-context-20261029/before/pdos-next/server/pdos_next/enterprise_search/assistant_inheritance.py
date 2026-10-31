"""Fixed-source citation continuation within the actual server-linked Run lineage."""

from copy import deepcopy
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import defer

from pdos_next.agent_kernel.conversation import lineage
from pdos_next.agent_kernel.execution import scope_for_run
from pdos_next.agent_kernel.models import AgentRun
from pdos_next.errors import DomainError
from pdos_next.service import digest

from . import assistant_ledger as ledger
from .assistant_sources import current

TOOL = "assistant.citations.read"
PREVIEW_SIZE = 3


def registry(session, run, *, include_self=False):
    parents = lineage(session, run)
    identities = [row.id for row in parents]
    rows = (
        session.scalars(
            select(AgentRun).options(defer(AgentRun.result)).where(AgentRun.id.in_(identities))
        ).all()
        if identities
        else []
    )
    by_id = {row.id: row for row in rows}
    if set(by_id) != set(identities):
        ledger.deny("lineage_unreadable")
    ordered = ([run] if include_self else []) + [by_id[identity] for identity in identities]
    roots = {}
    for origin in ordered:
        for cid, item in ledger.search_issued(
            session, scope_for_run(origin), archive=True
        ).items():
            roots[cid] = (str(origin.id), item)
    return roots, ordered


def fixed(run_id, root):
    origin_id, item = root
    value = {
        **deepcopy(item),
        "origin_run_id": origin_id,
        "origin_citation_id": item["citation_id"],
    }
    value["citation_id"] = ledger.citation_id(run_id, origin_id, value)
    return value


def preview(run_id, root, source):
    origin_id, item = root
    return {
        "citation_id": fixed(run_id, root)["citation_id"],
        "origin_run_id": origin_id,
        "origin_citation_id": item["citation_id"],
        "title": item["title"][:96],
        "source_type": item["source_type"],
        "source_revision": item["source_revision"],
        "currentness": "history" if source["updated"] or not source["is_current"] else "current",
        "read_basis_status": source["read_basis_status"],
    }


def expand(session, run, refs, *, roots=None):
    if roots is None:
        roots, _rows = registry(session, run)
    result = {}
    for ref in refs:
        root = roots.get(ref.get("origin_citation_id"))
        if root is None or ref.get("origin_run_id") != root[0]:
            ledger.deny("citation_origin_invalid")
        value = fixed(run.id, root)
        expected = {
            "citation_id": value["citation_id"],
            "origin_run_id": root[0],
            "origin_citation_id": root[1]["citation_id"],
            "title": root[1]["title"][:96],
            "source_type": root[1]["source_type"],
            "source_revision": root[1]["source_revision"],
        }
        if (
            set(ref) != set(expected) | {"currentness", "read_basis_status"}
            or any(ref.get(key) != val for key, val in expected.items())
            or ref["currentness"] not in {"current", "history"}
            or ref["read_basis_status"] not in {"current", "needs_recheck"}
        ):
            ledger.deny("inherited_citation_invalid")
        result[value["citation_id"]] = value
    return result


def _aliases(session, rows, roots):
    """Only original search CIDs and refs actually delivered to an ancestor resolve."""
    aliases = {cid: cid for cid in roots}
    older = {}
    for row in reversed(rows):
        frozen = row.versions.get("work_state", {})
        refs = list(frozen.get("citations", []))
        if refs and digest(frozen) != row.versions.get("work_state_digest"):
            ledger.deny("work_state_changed")
        for call, _args in ledger.completed(session, scope_for_run(row), {TOOL}, archive=True):
            refs.extend(call.result["items"])
        for cid, item in expand(session, row, refs, roots=older).items():
            aliases[cid] = item["origin_citation_id"]
        older.update((cid, root) for cid, root in roots.items() if root[0] == str(row.id))
    return aliases


def page(session, run, data, *, excluded=()):
    roots, rows = registry(session, run)
    keys = list(roots)
    if data.reference_id is not None:
        cid = _aliases(session, rows, roots).get(str(data.reference_id))
        if cid is None:
            ledger.deny("citation_not_in_lineage")
        keys = [cid]
    elif data.cursor is not None:
        cursor = str(data.cursor)
        if cursor not in roots:
            ledger.deny("citation_cursor_invalid")
        keys = keys[keys.index(cursor) + 1 :]
    excluded_sources = {
        (item["source_type"], item["source_id"])
        for cid, (_origin, item) in roots.items()
        if cid in excluded
    }
    selected = {
        cid: roots[cid][1]
        for cid in keys
        if roots[cid][1]["source_id"] not in excluded
        and (roots[cid][1]["source_type"], roots[cid][1]["source_id"]) not in excluded_sources
    }
    # Updated metadata establishes ongoing ACL only. fixed() keeps the original
    # revision/hash/locator; extract must still read that exact body or fail closed.
    actual, _missing = current(session, selected, allow_updated=set(selected))
    readable = [cid for cid in keys if cid in actual]
    visible = readable[: data.page_size]
    more = len(readable) > len(visible)
    return {
        "items": [preview(run.id, roots[cid], actual[cid]) for cid in visible],
        "returned": len(visible),
        "next_cursor": visible[-1] if more else None,
        "has_more": more,
    }


def saved(session, run, refs):
    """Public work-state metadata is reauthorized, without minting a phantom child CID."""
    roots, _rows = registry(session, run, include_self=True)
    selected = {}
    for ref in refs:
        root = roots.get(ref["citation_id"])
        if root is None or root[0] != ref["run_id"]:
            ledger.deny("work_state_citation_invalid")
        selected[ref["citation_id"]] = root[1]
    actual, missing = current(session, selected, allow_updated=set(selected))
    visible = list(actual)
    result = []
    for cid in visible[:PREVIEW_SIZE]:
        origin, _item = roots[cid]
        ref = preview(UUID(origin), roots[cid], actual[cid])
        ref["citation_id"] = cid
        result.append(ref)
    return (
        result,
        bool(missing),
        {
            "tool": TOOL,
            "has_more": len(visible) > PREVIEW_SIZE,
            "next_cursor": visible[PREVIEW_SIZE - 1] if len(visible) > PREVIEW_SIZE else None,
        },
        set(visible),
    )


def recheck(session, run, refs):
    values = expand(session, run, refs)
    _actual, missing = current(session, values, allow_updated=set(values))
    if missing:
        raise DomainError("CONVERSATION_HISTORY_REVOKED", "续接引用已无权读取或已撤回。")
