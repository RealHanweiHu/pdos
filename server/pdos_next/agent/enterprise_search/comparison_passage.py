"""Human source viewing follows an actual verified difference, never arbitrary offsets."""

from . import assistant_ledger as ledger
from .locations import span


def read(adapter, scope, cid, change_id, cursor, page_chars):
    with adapter.store.transaction(scope) as (session, _run):
        citations = ledger.select_issued(session, scope, [cid])
        sides = [
            side
            for call, _args in ledger.completed(session, scope, {"assistant.compare"})
            for row in call.result["rows"]
            if row["change_id"] == change_id
            for side in (row["old"], row["new"])
            if side and side["citation_id"] == str(cid)
        ]
    if not sides:
        ledger.deny("comparison_location_not_issued")
    actual, missing = adapter._current(scope, citations, body=True)
    if missing:
        ledger.deny("comparison_source_unavailable")
    source, fixed = actual[str(cid)], sides[0]
    first, last = fixed["locator"]["char_start"], fixed["locator"]["char_end"]
    location = span(source, first, last)
    if source["body"][first:last] != fixed["quote"] or location != fixed["locator"]:
        ledger.deny("comparison_location_changed")
    start, end = max(0, first - 300), min(len(source["body"]), last + 300)
    offset = start + cursor
    if not start <= offset < end:
        ledger.deny("comparison_cursor_invalid")
    stop = min(offset + page_chars, end)
    return {
        "citation_id": str(cid),
        "source_revision": source["source_revision"],
        "content_hash": source["content_hash"],
        "text": source["body"][offset:stop],
        "locator": span(source, offset, stop),
        "range_chars": end - start,
        "next_cursor": stop - start if stop < end else None,
    }
