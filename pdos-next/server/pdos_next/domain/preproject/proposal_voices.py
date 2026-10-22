"""Fixed user-voice knowledge explicitly referenced by this visible proposal.

No category-wide search, inferred association, Claim consumption or privilege
switch is used. A failed source/reference never returns the voice's body.
"""

from copy import deepcopy

from sqlalchemy import select

from pdos_next.clock import now
from pdos_next.errors import DomainError
from pdos_next.service import digest

from . import category_reads, proposal_views, root_sources, spec_compare
from .category_models import KnowledgeCurrent, KnowledgeEntry
from .schemas import Reference

VERSION = "proposal-voices/v1"
IDENTITY_FIELDS = ("proposal_id", "revision", "document_digest", "submission_id", "document_mode")
CHANGE_FIELDS = ("type", "id", "version", "current_version", "status")


def _reference(raw):
    """Keep only the already-visible, non-body identity for an unavailable edge."""
    return {
        key: raw[key]
        for key in ("type", "id", "version")
        if key in raw and (isinstance(raw[key], str) or type(raw[key]) is int)
    }


def _related_item(item):
    content = item.get("content", {})
    label = next(
        (
            content[key]
            for key in ("title", "parameter", "question", "name", "text", "key")
            if isinstance(content.get(key), str) and content[key].strip()
        ),
        item["kind"],
    )
    return {
        "item_id": item["item_id"],
        "version": item["version"],
        "kind": item["kind"],
        "label": label[:200],
    }


def _references(document):
    selected, invalid = {}, []

    def add(raw, *, item=None, context=False, reasons=()):
        if not isinstance(raw, dict) or raw.get("type") != "knowledge":
            return
        fields = {key: value for key, value in raw.items() if key in Reference.model_fields}
        try:
            reference = Reference.model_validate(fields)
        except ValueError:
            invalid.append(
                {"reference": _reference(raw), "reasons": ["knowledge_reference_invalid"]}
            )
            return
        key = (reference.id, reference.version)
        entry = selected.setdefault(
            key,
            {
                "reference": {
                    "type": "knowledge",
                    "id": str(reference.id),
                    "version": reference.version,
                },
                "related_items": {},
                "used_in_context": False,
                "valid": False,
                "reasons": set(),
            },
        )
        if reasons:
            entry["reasons"].update(reasons)
            return
        entry["valid"] = True
        entry["used_in_context"] |= context
        if item is not None:
            entry["related_items"][(item["item_id"], item["version"])] = _related_item(item)

    for raw in document.get("source_refs", []):
        add(raw)
    for raw in document.get("context_refs", []):
        add(raw, context=True)
    for item in document.get("items", []):
        if item.get("removed") is True:
            continue
        for raw in item.get("source_refs", []):
            add(raw, item=item)
        if item["kind"] == "commercial_target":
            for field in ("target_price", "cost", "volume"):
                value = item.get("content", {}).get(field)
                if isinstance(value, dict):
                    add(value.get("source"), item=item)
        for link in item.get("evidence_links", []):
            target = link.get("target", {})
            reasons = []
            if link.get("status") != "active":
                reasons.append("evidence_link_inactive")
            if (
                target.get("type") != "proposal_item"
                or target.get("id") != item["item_id"]
                or target.get("version") != item["version"]
            ):
                reasons.append("evidence_link_target_mismatch")
            add(link.get("evidence"), item=item, reasons=reasons)
    return selected, invalid


def _checked_sources(s, ctx, raw_refs):
    sources, reasons = spec_compare._sources(s, ctx, raw_refs)
    # Reference normalizes strings. If a stored quote was trimmed during model
    # validation, recheck its exact original spelling before returning it.
    if not reasons:
        for raw in raw_refs:
            quote = raw.get("quote")
            if isinstance(quote, str) and quote != quote.strip():
                fields = {key: value for key, value in raw.items() if key in Reference.model_fields}
                ref = Reference.model_validate(fields).model_copy(update={"quote": quote})
                try:
                    spec_compare._check_reference(s, ctx, ref)
                except (DomainError, ValueError):
                    reasons.append("source_unavailable")
    return sources, sorted(set(reasons))


def _changes(changes):
    return [{key: change[key] for key in CHANGE_FIELDS if key in change} for change in changes]


def _voice(s, ctx, row, pointer, requested_version):
    if row.version != requested_version:
        return None, ["knowledge_version_mismatch"]
    if row.action == "withdraw" or (pointer is not None and pointer.status == "withdrawn"):
        return None, ["knowledge_withdrawn"]
    if pointer is None or pointer.status != "active":
        return None, ["knowledge_current_unavailable"]
    # Re-resolve the fixed record and its complete stored source tree, then add
    # only current, ordinary-reader evidence-link/source-state projections.
    _, reasons = spec_compare._sources(
        s,
        ctx,
        [
            {
                "type": "knowledge",
                "id": str(row.id),
                "version": requested_version,
            }
        ],
    )
    if reasons:
        return None, reasons
    projected = root_sources.project_knowledge(
        s,
        ctx,
        [
            {
                **category_reads._row(row),
                "status": "active",
            }
        ],
    )[0]
    if projected.get("source_changes") or any(
        link.get("status") != "active" for link in projected.get("evidence_links", [])
    ):
        return None, ["source_unavailable"]
    content = projected["content"]
    sources, reasons = _checked_sources(s, ctx, projected.get("source_refs", []))
    representatives, representative_reasons = _checked_sources(
        s,
        ctx,
        content.get("representative_refs", []),
    )
    reasons = sorted(set(reasons) | set(representative_reasons))
    if reasons:
        return None, reasons
    sample_size = content.get("sample_size")
    changes = _changes(projected.get("source_changes", []))
    if pointer.current_version != requested_version:
        changes.append(
            {
                "type": "knowledge",
                "id": str(row.id),
                "version": requested_version,
                "current_version": pointer.current_version,
                "status": pointer.status,
            }
        )
    return {
        "knowledge_id": str(row.id),
        "lineage_id": str(row.lineage_id),
        "version": row.version,
        "label": content["label"],
        "source_platform": content["source_platform"],
        "origin": row.origin,
        "status": "active",
        "current_version": pointer.current_version,
        "sample_size": sample_size if type(sample_size) is int and sample_size >= 0 else None,
        "source_refs": sources,
        "representative_refs": representatives,
        "source_changes": changes,
    }, []


def read(s, ctx, proposal_id):
    record = proposal_views.read_document(s, ctx, proposal_id)
    selected, unavailable = _references(record["display_document"])
    readable_keys = {
        identity
        for (identity, _), item in selected.items()
        if item["valid"] and not item["reasons"]
    }
    rows = (
        s.execute(
            select(KnowledgeEntry, KnowledgeCurrent)
            .outerjoin(
                KnowledgeCurrent,
                (
                    (KnowledgeCurrent.tenant_id == KnowledgeEntry.tenant_id)
                    & (KnowledgeCurrent.category_id == KnowledgeEntry.category_id)
                    & (KnowledgeCurrent.lineage_id == KnowledgeEntry.lineage_id)
                ),
            )
            .where(
                KnowledgeEntry.tenant_id == ctx.tenant_id,
                KnowledgeEntry.category_id == ctx.category_id,
                KnowledgeEntry.id.in_(readable_keys),
            )
        ).all()
        if readable_keys
        else []
    )
    indexed = {entry.id: (entry, current) for entry, current in rows}
    entries = []
    for (identity, version), reference in sorted(
        selected.items(), key=lambda item: (str(item[0][0]), item[0][1])
    ):
        if not reference["valid"] or reference["reasons"]:
            unavailable.append(
                {"reference": reference["reference"], "reasons": sorted(reference["reasons"])}
            )
            continue
        entry, pointer = indexed.get(identity, (None, None))
        if entry is None:
            unavailable.append(
                {"reference": reference["reference"], "reasons": ["knowledge_unavailable"]}
            )
            continue
        if entry.kind != "voice":
            continue
        try:
            voice, reasons = _voice(s, ctx, entry, pointer, version)
        except (DomainError, ValueError):
            voice, reasons = None, ["source_unavailable"]
        if voice is None:
            unavailable.append({"reference": reference["reference"], "reasons": reasons})
        else:
            entries.append(
                {
                    **voice,
                    "related_items": list(reference["related_items"].values()),
                    "used_in_context": reference["used_in_context"],
                }
            )
    unavailable = list({digest(row): row for row in unavailable}.values())
    return {
        "version": VERSION,
        "category_id": str(ctx.category_id),
        "document": {
            field: deepcopy(record["document_identity"][field]) for field in IDENTITY_FIELDS
        },
        "as_of": now().isoformat(),
        "entries": entries,
        "unavailable": unavailable,
        "counts": {"entries": len(entries), "unavailable_entries": len(unavailable)},
    }
