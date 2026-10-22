"""Replay isolated public reads, without granting registered business evidence status."""

import re
from dataclasses import asdict
from uuid import UUID

from pdos_next.errors import DomainError
from pdos_next.research.types import ReadPage, ReadTrace, SearchHit, SearchTrace
from pdos_next.research.web import canonical_url
from pdos_next.service import digest


def page_result(page):
    return {
        "snapshot_id": str(page.snapshot.id),
        "snapshot_digest": digest(asdict(page.snapshot)),
        "content_hash": page.snapshot.content_hash,
        "locator": page.locator,
        "markdown": page.markdown,
        "next_cursor": page.next_cursor,
    }


def restore_page(child, arguments, previous, *, artifacts, current):
    """Only immutable host artifacts and the actual read receipt restore quote authority."""
    current(child._scope)
    if artifacts is None:
        raise DomainError("SOURCE_UNAVAILABLE", "研究读取重放需要原运行快照文件。")
    try:
        identity = UUID(previous["snapshot_id"])
        snapshot = artifacts.snapshot(child._scope, identity)
        location = re.fullmatch(r"chars:(0|[1-9][0-9]*):(0|[1-9][0-9]*)", previous["locator"])
        if location is None:
            raise ValueError("Invalid page location")
        start, end = map(int, location.groups())
        if (
            snapshot.id != identity or snapshot.url != canonical_url(arguments.url)
            or start != arguments.cursor or not start <= end <= len(snapshot.markdown)
            or (end == start and end < len(snapshot.markdown))
        ):
            raise ValueError("Page does not match the original read")
        page = ReadPage(
            snapshot, previous["locator"], snapshot.markdown[start:end],
            end if end < len(snapshot.markdown) else None,
        )
        # Full snapshot digest includes unread text and metadata, not just the returned page.
        if page_result(page) != previous:
            raise ValueError("Snapshot or page changed")
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise DomainError("SOURCE_UNAVAILABLE", "原研究快照或读取回执无法核对。") from exc
    current(child._scope)
    child.pages[(identity, page.locator)] = page
    trace = ReadTrace(snapshot.url, identity, page.locator)
    if trace not in child.reads:
        child.reads.append(trace)
    # Later pages must continue this same immutable document after worker recovery.
    service = child._service
    scope = child._scope
    key = scope.tenant_id, scope.requester_id, scope.session_id, scope.run_id
    with service._lock:
        service._allowlists.setdefault(key, set()).add(snapshot.url)
        service._snapshots[(key, snapshot.url)] = snapshot
    return previous


def restore_search(child, query, previous, *, current):
    current(child._scope)
    try:
        hits = tuple(SearchHit(**raw) for raw in previous["hits"])
        provider = previous["provider"]
        if (
            set(previous) != {"hits", "provider"} or not isinstance(provider, str)
            or not provider or any(
                not all(isinstance(value, str) for value in asdict(hit).values())
                or canonical_url(hit.url) != hit.url or hit.provider != provider
                for hit in hits
            )
        ):
            raise ValueError("Invalid search receipt")
    except (KeyError, TypeError, ValueError) as exc:
        raise DomainError("SOURCE_UNAVAILABLE", "原搜索回执无法核对。") from exc
    # The stored, model-bound search response is the original source of these URL grants.
    child._service.register_user_message(child._scope, "\n".join(hit.url for hit in hits))
    trace = SearchTrace(query, provider, tuple(hit.url for hit in hits))
    if trace not in child.searches:
        child.searches.append(trace)
    return previous
