"""Deterministic identity checks. Overlap is a warning, never an automatic veto."""

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any


def strings(value: Any, *, include_keys=True):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, child in value.items():
            if include_keys:
                yield str(key)
            yield from strings(child, include_keys=include_keys)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from strings(child, include_keys=include_keys)


def normalized(value):
    return unicodedata.normalize("NFKC", value).casefold()


def check_content(content, *, identities=(), filenames=(), private_refs=(), originals=()):
    fragments = list(strings(content))
    flattened = "\n".join(fragments)
    searchable = normalized(flattened)
    hits = []
    for kind, values in (
        ("identity", identities),
        ("filename", filenames),
        ("private_ref", private_refs),
    ):
        for value in values:
            if value and normalized(str(value)) in searchable:
                hits.append({"kind": kind, "value": str(value)})
    for url in re.findall(
        r'(?i)(?:[a-z][a-z0-9+.-]*://|www\.|/(?:categories|proposals|originals|artifacts)/)[^\s<>"\]]+',
        flattened,
    ):
        hits.append({"kind": "url", "value": url})
    for path in source_links(content):
        hits.append({"kind": "private_ref", "value": path})
    overlaps = []
    for index, original in enumerate(originals):
        match = SequenceMatcher(None, flattened, original, autojunk=False).find_longest_match()
        if match.size:
            overlaps.append(
                {
                    "source_index": index,
                    "characters": match.size,
                    "quote": flattened[match.a : match.a + match.size],
                }
            )
    return {
        "refs_clean": not any(h["kind"] in {"url", "private_ref"} for h in hits),
        "filenames_clean": not any(h["kind"] == "filename" for h in hits),
        "identities_clean": not any(h["kind"] == "identity" for h in hits),
        "hits": hits,
        "overlap_warnings": overlaps,
    }


def source_links(value, path="content"):
    """Promotion content cannot carry structured source links or private backrefs."""
    if isinstance(value, dict):
        for key, child in value.items():
            location = f"{path}.{key}"
            if child and key in {
                "source_ref",
                "source_refs",
                "source_proposal_id",
                "source_item_refs",
                "proposal_id",
                "artifact_id",
                "original_id",
                "snapshot_id",
                "knowledge_entry_id",
                "source_url",
                "url",
                "href",
            }:
                yield location
            yield from source_links(child, location)
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            yield from source_links(child, f"{path}[{index}]")
