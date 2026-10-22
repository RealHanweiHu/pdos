"""Fixed competitor/segment associations through existing knowledge versions."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import select

from pdos_next.category_scope import category_scope
from pdos_next.clock import now
from pdos_next.errors import DomainError

from . import category_reads, root_sources
from .access import fail, human
from .category_models import KnowledgeCurrent, KnowledgeEntry
from .category_schemas import CompetitorContent, SegmentRef
from .schemas import Reference

VERSION = "competitor-segment-assignment/v1"
SEGMENT_FIELDS = ("entry_id", "version", "lineage_id", "label", "status", "source_refs")


def _checked_sources(s, ctx, refs):
    # Local import: spec_compare itself imports category_service for the existing
    # recursive source guard. A segment association is never a provenance edge.
    from .spec_compare import _check_reference

    result = []
    for raw in refs:
        fields = {
            key: deepcopy(value) for key, value in raw.items() if key in Reference.model_fields
        }
        ref = Reference.model_validate(fields)
        if isinstance(fields.get("quote"), str):
            ref = ref.model_copy(update={"quote": fields["quote"]})
        _check_reference(s, ctx, ref)
        result.append(fields)
    return result


def _safe_knowledge(s, ctx, entry):
    from .spec_compare import _check_reference

    _check_reference(s, ctx, Reference(type="knowledge", id=entry.id, version=entry.version))
    projected = root_sources.project_knowledge(s, ctx, [category_reads._row(entry)])[0]
    if projected.get("source_changes"):
        raise DomainError("SOURCE_UNAVAILABLE", "知识来源当前不可用。")
    _checked_sources(s, ctx, projected["source_refs"])
    direct = projected.get("direct_source_refs", projected["source_refs"])
    return projected, _checked_sources(s, ctx, direct)


def _explicit_sources(content, direct):
    from .category_service import _references

    nested = [
        ref.model_dump(mode="json")
        for ref in _references(SimpleNamespace(kind="competitor", content=content, source_refs=[]))
    ]
    # Add stores explicit refs followed by metrics/features/prices refs. Promote
    # intentionally stores []; it never supplies an inferred explicit prefix.
    if not direct or not nested:
        return direct
    if len(direct) < len(nested) or direct[-len(nested) :] != nested:
        raise DomainError("SOURCE_UNAVAILABLE", "竞品保存的来源顺序无法核对。")
    return direct[: -len(nested)]


def _typed_refs(refs):
    result = [
        ref if isinstance(ref, SegmentRef) else SegmentRef.model_validate(ref) for ref in refs
    ]
    keys = [(ref.entry_id, ref.version) for ref in result]
    if len(keys) != len(set(keys)):
        fail("VALIDATION_FAILED", "competitor_segment_duplicate", "固定细分引用不能重复。", 422)
    return result


def resolve_fixed(s, ctx, refs):
    """Only explicit IDs/versions; Current supplies withdrawal, never replacement."""
    refs = _typed_refs(refs)
    if not refs:
        return []
    rows = s.execute(
        select(KnowledgeEntry, KnowledgeCurrent.status)
        .outerjoin(
            KnowledgeCurrent,
            (KnowledgeCurrent.tenant_id == KnowledgeEntry.tenant_id)
            & (KnowledgeCurrent.category_id == KnowledgeEntry.category_id)
            & (KnowledgeCurrent.lineage_id == KnowledgeEntry.lineage_id),
        )
        .where(
            KnowledgeEntry.tenant_id == ctx.tenant_id,
            KnowledgeEntry.category_id == ctx.category_id,
            KnowledgeEntry.id.in_({ref.entry_id for ref in refs}),
        )
    ).all()
    by_id = {entry.id: (entry, status) for entry, status in rows}
    result = []
    for ref in refs:
        value = {
            "entry_id": str(ref.entry_id),
            "version": ref.version,
            "lineage_id": None,
            "label": None,
            "status": "unavailable",
            "source_refs": [],
            "reasons": ["segment_unavailable"],
        }
        entry, status = by_id.get(ref.entry_id, (None, None))
        if (
            entry is None
            or entry.tenant_id != ctx.tenant_id
            or entry.category_id != ctx.category_id
            or entry.kind != "segment"
            or entry.version != ref.version
            or status is None
        ):
            result.append(value)
            continue
        if entry.action == "withdraw" or status != "active":
            value["reasons"] = ["segment_withdrawn"]
            result.append(value)
            continue
        try:
            projected, sources = _safe_knowledge(s, ctx, entry)
            label = projected["content"].get("segment")
            if not isinstance(label, str) or not label.strip():
                raise ValueError
        except (DomainError, ValueError):
            result.append(value)
            continue
        result.append(
            {
                **value,
                "lineage_id": str(entry.lineage_id),
                "label": label,
                "status": "available",
                "source_refs": sources,
                "reasons": [],
            }
        )
    return result


def validate_refs(s, ctx, refs):
    """The command already holds its category/actor fence; keep target state stable."""
    refs = _typed_refs(refs)
    if not refs:
        return
    lineages = list(
        s.scalars(
            select(KnowledgeEntry.lineage_id).where(
                KnowledgeEntry.tenant_id == ctx.tenant_id,
                KnowledgeEntry.category_id == ctx.category_id,
                KnowledgeEntry.id.in_({ref.entry_id for ref in refs}),
            )
        )
    )
    if lineages:
        # Withdrawal/supersede uses the same Current row FOR UPDATE. Readers of
        # historical versions keep the old version while serializing withdrawal.
        list(
            s.scalars(
                select(KnowledgeCurrent)
                .where(
                    KnowledgeCurrent.tenant_id == ctx.tenant_id,
                    KnowledgeCurrent.category_id == ctx.category_id,
                    KnowledgeCurrent.lineage_id.in_(lineages),
                )
                .order_by(KnowledgeCurrent.lineage_id)
                .with_for_update(read=True)
            )
        )
    if any(value["status"] != "available" for value in resolve_fixed(s, ctx, refs)):
        fail(
            "SOURCE_UNAVAILABLE",
            "competitor_segment_unavailable",
            "所选固定细分或其来源当前不可用，请重新选择。",
        )


def read(s, ctx, entry_id):
    category_scope(s, ctx)
    human(s, ctx)
    entry_id = entry_id if isinstance(entry_id, UUID) else UUID(entry_id)
    pair = s.execute(
        select(KnowledgeEntry, KnowledgeCurrent)
        .outerjoin(
            KnowledgeCurrent,
            (KnowledgeCurrent.tenant_id == KnowledgeEntry.tenant_id)
            & (KnowledgeCurrent.category_id == KnowledgeEntry.category_id)
            & (KnowledgeCurrent.lineage_id == KnowledgeEntry.lineage_id),
        )
        .where(
            KnowledgeEntry.tenant_id == ctx.tenant_id,
            KnowledgeEntry.category_id == ctx.category_id,
            KnowledgeEntry.id == entry_id,
            KnowledgeEntry.kind == "competitor",
        )
    ).first()
    if pair is None:
        fail("NOT_FOUND", "competitor_not_found", "竞品当前记录不存在或不可读。", 404)
    entry, current = pair
    if (
        entry.tenant_id != ctx.tenant_id
        or entry.category_id != ctx.category_id
        or entry.kind != "competitor"
    ):
        fail("NOT_FOUND", "competitor_not_found", "竞品当前记录不存在或不可读。", 404)
    if (
        not current
        or current.tenant_id != ctx.tenant_id
        or current.category_id != ctx.category_id
        or current.lineage_id != entry.lineage_id
        or current.kind != "competitor"
        or current.status != "active"
        or current.current_entry_id != entry.id
        or current.current_version != entry.version
        or entry.action == "withdraw"
    ):
        fail("VERSION_CONFLICT", "competitor_version_moved", "竞品版本已变化或撤回，请刷新。")
    blockers = []
    try:
        category_scope(s, ctx, write=True)
    except DomainError as error:
        if error.code != "FORBIDDEN_SCOPE":
            raise
        blockers.append({"code": "category_write_required", "message": "当前没有品类写入权限。"})
    content, sources, regions = None, [], []
    try:
        projected, sources = _safe_knowledge(s, ctx, entry)
        content = CompetitorContent.model_validate(projected["content"]).model_dump(mode="json")
        sources = _explicit_sources(content, sources)
        regions = deepcopy(projected["regions"])
    except (DomainError, ValueError):
        blockers.append(
            {
                "code": "competitor_source_unavailable",
                "message": "竞品来源当前不可读，请先恢复来源读取。",
            }
        )
        content, sources, regions = None, [], []
    selected = resolve_fixed(s, ctx, entry.content.get("segment_refs", []))
    if content is None:
        selected = [
            {**value, "lineage_id": None, "label": None, "status": "unavailable", "source_refs": []}
            for value in selected
        ]
    rows = s.execute(
        select(KnowledgeEntry.id, KnowledgeEntry.version)
        .join(
            KnowledgeCurrent,
            (KnowledgeCurrent.tenant_id == KnowledgeEntry.tenant_id)
            & (KnowledgeCurrent.category_id == KnowledgeEntry.category_id)
            & (KnowledgeCurrent.lineage_id == KnowledgeEntry.lineage_id)
            & (KnowledgeCurrent.current_entry_id == KnowledgeEntry.id)
            & (KnowledgeCurrent.current_version == KnowledgeEntry.version),
        )
        .where(
            KnowledgeEntry.tenant_id == ctx.tenant_id,
            KnowledgeEntry.category_id == ctx.category_id,
            KnowledgeEntry.kind == "segment",
            KnowledgeEntry.action != "withdraw",
            KnowledgeCurrent.status == "active",
        )
        .order_by(KnowledgeEntry.lineage_id)
    ).all()
    options = resolve_fixed(
        s, ctx, [{"entry_id": identity, "version": version} for identity, version in rows]
    )
    return {
        "version": VERSION,
        "category_id": str(ctx.category_id),
        "principal_id": str(ctx.requester_id),
        "as_of": now().isoformat(),
        "competitor": {
            "id": str(entry.id),
            "lineage_id": str(entry.lineage_id),
            "version": entry.version,
            "origin": entry.origin,
            "writer_id": str(entry.writer_id),
            "run_id": str(entry.run_id) if entry.run_id else None,
            "confirmed_by": str(entry.confirmed_by) if entry.confirmed_by else None,
            "content": content,
            "regions": regions,
            "source_refs": sources,
        },
        "can_edit": not blockers,
        "blockers": blockers,
        "selected_segments": [
            {field: value[field] for field in SEGMENT_FIELDS} for value in selected
        ],
        "segments": [
            {field: value[field] for field in SEGMENT_FIELDS if field != "status"}
            for value in options
            if value["status"] == "available"
        ],
        "unavailable_segment_count": len(
            {
                (value["entry_id"], value["version"])
                for value in [*selected, *options]
                if value["status"] != "available"
            }
        ),
    }
