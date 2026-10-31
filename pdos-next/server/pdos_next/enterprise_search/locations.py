"""Character spans follow parser splitlines, including PDF form feeds."""

from bisect import bisect_left, bisect_right

from .indexing import _locator


def span(source, start, end):
    body = source["body"]
    cached = source.get("_located_line_offsets")
    if cached is None or cached[0] is not body:
        offsets = [0]
        for fragment in body.splitlines(keepends=True):
            offsets.append(offsets[-1] + len(fragment))
        cached = (body, offsets)
        # Per-request source projection, never a global private-text cache.
        source["_located_line_offsets"] = cached
    offsets = cached[1]
    first = bisect_right(offsets, start)
    last = max(first, bisect_left(offsets, end))
    return _locator(start, end, first, last, source.get("seal"))
