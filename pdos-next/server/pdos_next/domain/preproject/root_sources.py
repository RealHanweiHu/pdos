"""Current source roots and immutable evidence-link projections for M3 documents."""

from collections import defaultdict
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import select, text

from pdos_next.errors import DomainError
from pdos_next.models import Claim, Consumption
from pdos_next.service import digest

from .access import fail
from .schemas import Reference


def lock_claim_refs(s, ctx, refs, *, approved=False):
    """All Claim dependencies use one UUID order before source revalidation."""
    from .claim_access import lock_references, resolve

    keys = sorted(
        {(ref.id, ref.version) for ref in refs if ref.type == "claim"},
        key=lambda key: (str(key[0]), key[1]),
    )
    lock_references(s, ctx, [identity for identity, _ in keys])
    return {
        identity: resolve(s, ctx, identity, version, approved=approved, source_lock=True)
        for identity, version in keys
    }


def roots(s, ctx, refs, reference_privacy):
    """Expand Claims to actual original/snapshot roots, retaining multiplicity.

    Withdrawn Claim references remain in immutable item history, but the trusted
    withdrawal projection has already removed their source-counter contribution.
    """
    from .claim_access import source_privacy, source_reference

    result, privacy = [], dict(reference_privacy)
    identities = {ref.id for ref in refs if ref.type == "claim"}
    states = claim_states(s, ctx, [ref.model_dump(mode="json") for ref in refs])
    claims = (
        {
            row.id: row
            for row in s.scalars(
                select(Claim)
                .where(
                    Claim.tenant_id == ctx.tenant_id,
                    Claim.category_id == ctx.category_id,
                    Claim.id.in_(identities),
                )
                .execution_options(populate_existing=True)
            )
        }
        if identities
        else {}
    )
    for ref in refs:
        if ref.type != "claim":
            result.append(ref)
            continue
        row = claims.get(ref.id)
        if not row:
            if states.get(str(ref.id), (None, None))[1] in {"withdrawn", "reverted"}:
                continue
            fail("SOURCE_UNAVAILABLE", "claim_unreadable", "事实不在当前可读范围。")
        if row.status != "active":
            continue
        if row.revision != ref.version:
            fail("SOURCE_STALE", "claim_version_moved", "事实版本已变化。")
        bottom = source_reference(row)
        result.append(bottom)
        privacy[digest(bottom.model_dump(mode="json"))] = source_privacy(s, ctx, row)
    return result, privacy


def claim_states(s, ctx, refs):
    """Read only identity/status/version columns, never withdrawn Claim bodies."""
    ids = {UUID(str(ref["id"])) for ref in refs if ref["type"] == "claim"}
    if not ids:
        return {}
    return {
        str(identity): (version, status)
        for identity, version, status in s.execute(
            text(
                "SELECT id,revision,status FROM "
                "m3_claim_reference_states(:tenant,:category,CAST(:ids AS uuid[]))"
            ),
            {"tenant": ctx.tenant_id, "category": ctx.category_id, "ids": sorted(ids, key=str)},
        )
    }


def source_changes(refs, states):
    changes = {}
    for ref in refs:
        if ref["type"] != "claim":
            continue
        version, status = states.get(str(ref["id"]), (None, "unavailable"))
        if status != "active" or version != ref["version"]:
            changes[(str(ref["id"]), ref["version"])] = {
                "type": "claim",
                "id": str(ref["id"]),
                "version": ref["version"],
                "current_version": version,
                "status": status,
            }
    return [changes[key] for key in sorted(changes)]


def redact_references(value, states):
    """Only Claim reference metadata survives when its current body is unavailable."""
    if isinstance(value, dict):
        if value.get("type") == "claim" and "id" in value and "version" in value:
            if states.get(str(value["id"]), (None, "unavailable"))[1] != "active":
                return {
                    key: child
                    for key, child in value.items()
                    if key in {"type", "id", "version", "current_version", "status", "locator"}
                }
        return {key: redact_references(child, states) for key, child in value.items()}
    if isinstance(value, list):
        return [redact_references(child, states) for child in value]
    return deepcopy(value)


def nested_claim_refs(value):
    if isinstance(value, dict):
        if value.get("type") == "claim" and "id" in value and "version" in value:
            yield value
        for child in value.values():
            yield from nested_claim_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from nested_claim_refs(child)


def _canonical_citation(body, locator):
    """Choose one actual nonblank line fragment inside the entire validated locator."""
    validate_locator(locator, body)
    start, end, first, last = 0, len(body), 1, len(body.splitlines())
    if locator is not None:
        parts = locator.split(":")
        if parts[0] == "chars":
            start, end = int(parts[1]), int(parts[2])
        else:
            first = int(parts[1])
            last = int(parts[-1])
    offset = 0
    for number, (raw, line) in enumerate(
        zip(body.splitlines(keepends=True), body.splitlines(), strict=True), start=1
    ):
        left, right = max(start, offset), min(end, offset + len(line))
        if first <= number <= last and left < right:
            quote = line[left - offset : right - offset].strip()[:4000].rstrip()
            if quote:
                return {"line": number, "quote": quote}
        offset += len(raw)
    fail("SOURCE_UNAVAILABLE", "source_locator_empty", "证据定位内没有可核对的非空原文。")


def _link_citation(s, row, link):
    """Read only through this transaction's actual actor, RLS and source lifecycle."""
    from sqlalchemy.orm import load_only

    from pdos_next.agent_kernel.models import PublicWebSnapshot
    from pdos_next.models import Artifact
    from pdos_next.service import Context, source_for

    scope = getattr(s, "info", {}).get("scope")
    if (
        not scope
        or len(scope) != 4
        or scope[0] != row.tenant_id
        or scope[3] != row.category_id
        or not scope[1]
        or not scope[2]
    ):
        fail("SOURCE_UNAVAILABLE", "source_unreadable", "证据正文缺少当前事务读取身份。")
    ctx = Context(scope[0], scope[1], scope[2], category_id=scope[3])
    model = Artifact if link.evidence_type == "artifact" else PublicWebSnapshot
    columns = [model.id, model.tenant_id, model.category_id]
    columns.append(model.product_id if model is Artifact else model.status)
    source = s.scalar(
        select(model)
        .where(
            model.id == link.evidence_id,
            model.tenant_id == ctx.tenant_id,
            model.category_id == ctx.category_id,
        )
        .options(load_only(*columns))
        .execution_options(populate_existing=True)
    )
    if not source or source.tenant_id != ctx.tenant_id or source.category_id != ctx.category_id:
        fail("SOURCE_UNAVAILABLE", "source_unreadable", "证据正文不在当前读取范围。")
    if link.evidence_type == "artifact":
        # The RLS-loaded source supplies its product; neither the linked item nor
        # the caller can substitute a product scope. source_for checks Originals.
        source = source_for(s, ctx, source.product_id, source.id, link.evidence_version)
        body = source.content
    else:
        if link.evidence_version != 1 or source.status not in {"ok", "partial"}:
            fail("SOURCE_STALE", "snapshot_unavailable", "网页快照不可用。")
        body = source.markdown
    return _canonical_citation(body, link.evidence_locator)


def project_items(s, row, items, *, target_type="proposal_item"):
    """Merge independent associations without changing stored item versions."""
    from .evidence_models import EvidenceLink

    if not items:
        return items
    ctx = SimpleNamespace(tenant_id=row.tenant_id, category_id=row.category_id)
    pairs = {(UUID(item["item_id"]), item["version"]) for item in items}
    links = list(
        s.scalars(
            select(EvidenceLink)
            .where(
                EvidenceLink.tenant_id == row.tenant_id,
                EvidenceLink.category_id == row.category_id,
                EvidenceLink.target_type == target_type,
                EvidenceLink.target_id.in_({pair[0] for pair in pairs}),
            )
            .order_by(EvidenceLink.id)
        )
    )
    relevant = [link for link in links if (link.target_id, link.target_version) in pairs]
    all_refs = [
        *(ref for item in items for ref in item["source_refs"]),
        *(
            {
                "type": link.evidence_type,
                "id": str(link.evidence_id),
                "version": link.evidence_version,
            }
            for link in relevant
        ),
    ]
    states = claim_states(s, ctx, all_refs)
    grouped = defaultdict(list)
    for link in relevant:
        grouped[(str(link.target_id), link.target_version)].append(link)
    result = []
    for item in items:
        item = dict(item)
        direct = list(item["source_refs"])
        refs, views = list(direct), []
        for link in grouped[(item["item_id"], item["version"])]:
            reference = {
                "type": link.evidence_type,
                "id": str(link.evidence_id),
                "version": link.evidence_version,
            }
            changes = source_changes([reference], states)
            status = (
                "reverted"
                if link.reverted_by_receipt_id
                else (
                    ("stale" if changes[0]["status"] == "active" else changes[0]["status"])
                    if changes
                    else "active"
                )
            )
            citation = {}
            if status == "active" and link.evidence_type in {"artifact", "snapshot"}:
                try:
                    citation = _link_citation(s, row, link)
                except DomainError:
                    # History remains readable; an unavailable body never gains
                    # a synthetic quote or an active reference in the document.
                    status = "stale"
            views.append(
                {
                    "id": str(link.id),
                    "evidence": {**reference, "locator": link.evidence_locator},
                    "target": {
                        "type": target_type,
                        "id": item["item_id"],
                        "version": item["version"],
                    },
                    "relation": link.relation,
                    "status": status,
                }
            )
            if status == "active":
                refs.append({**reference, **citation})
        if views:
            item.update(direct_source_refs=direct, source_refs=refs, evidence_links=views)
        changed = source_changes([*direct, *(view["evidence"] for view in views)], states)
        if changed:
            item["source_changes"] = changed
        result.append(item)
    return result


def project_knowledge(s, ctx, entries):
    shape = [
        {"item_id": row["id"], "version": row["version"], "source_refs": row["source_refs"]}
        for row in entries
    ]
    projected = project_items(s, ctx, shape, target_type="knowledge_entry")
    result = [
        {
            **row,
            **{
                key: value for key, value in projection.items() if key not in {"item_id", "version"}
            },
        }
        for row, projection in zip(entries, projected, strict=True)
    ]
    refs = list(nested_claim_refs(result))
    states = claim_states(s, ctx, refs)
    for row in result:
        changes = source_changes(list(nested_claim_refs(row)), states)
        if changes:
            row["source_changes"] = changes
    return redact_references(result, states)


def ordinary_refs(doc):
    """Return actual direct input refs, excluding separately verified Link refs."""
    refs = [
        *doc.get("direct_source_refs", doc.get("source_refs", [])),
        *doc.get("context_refs", []),
        *(
            ref
            for item in doc["items"]
            for ref in item.get("direct_source_refs", item["source_refs"])
        ),
    ]
    typed = [Reference.model_validate(ref) for ref in refs]
    return list({digest(ref.model_dump(mode="json")): ref for ref in typed}.values())


def validate_locator(locator, body):
    """Check a persisted locator against the actual source text without inventing quotes."""
    if locator is None:
        return
    parts = locator.split(":")
    try:
        if len(parts) == 3 and parts[0] == "chars":
            start, end = int(parts[1]), int(parts[2])
            if start < 0 or end <= start or end > len(body):
                raise ValueError
            return
        if len(parts) == 2 and parts[0] == "line":
            start = end = int(parts[1])
        elif len(parts) == 3 and parts[0] == "lines":
            start, end = int(parts[1]), int(parts[2])
        else:
            raise ValueError
        if start < 1 or end < start or end > len(body.splitlines()):
            raise ValueError
    except (TypeError, ValueError):
        fail("VALIDATION_FAILED", "source_locator_invalid", "证据定位不在实际来源正文范围内。")


def validate_document_links(s, ctx, doc, *, approved=False):
    from .evidence_models import EvidenceLink
    from .evidence_service import _source

    candidates = [
        (item, value)
        for item in doc["items"]
        for value in item.get("evidence_links", [])
        if value["status"] == "active"
    ]
    # Freeze and lock Claim versions before touching source roots, across all
    # associations rather than in target iteration order.
    refs = [
        Reference.model_validate({k: v for k, v in value["evidence"].items() if k != "locator"})
        for _, value in candidates
    ]
    lock_claim_refs(s, ctx, refs, approved=approved)
    ids = {UUID(value["id"]) for _, value in candidates}
    current = (
        {
            str(link.id): link
            for link in s.scalars(
                select(EvidenceLink)
                .where(
                    EvidenceLink.tenant_id == ctx.tenant_id,
                    EvidenceLink.category_id == ctx.category_id,
                    EvidenceLink.id.in_(ids),
                )
                .order_by(EvidenceLink.id)
                .with_for_update(read=True)
            )
        }
        if ids
        else {}
    )
    for item, frozen in candidates:
        link = current.get(frozen["id"])
        evidence = frozen["evidence"]
        if not link or link.reverted_by_receipt_id:
            fail("SOURCE_STALE", "evidence_link_reverted", "提交的证据关联已撤回。")
        actual = (
            link.target_type,
            str(link.target_id),
            link.target_version,
            link.evidence_type,
            str(link.evidence_id),
            link.evidence_version,
            link.evidence_locator,
            link.relation,
        )
        expected = (
            "proposal_item",
            item["item_id"],
            item["version"],
            evidence["type"],
            evidence["id"],
            evidence["version"],
            evidence["locator"],
            frozen["relation"],
        )
        if actual != expected:
            fail("SOURCE_STALE", "evidence_link_changed", "证据关联与固定副本不一致。")
        _, _, source = _source(
            s,
            ctx,
            SimpleNamespace(
                type=link.evidence_type, id=link.evidence_id, version=link.evidence_version
            ),
        )
        if link.evidence_type != "claim":
            body = source.content if link.evidence_type == "artifact" else source.markdown
            validate_locator(link.evidence_locator, body)
    return refs


def consume_claims(s, ctx, refs, decision):
    """Only an actual approved Decision + fixed Definition consumes Claim facts."""
    claims = lock_claim_refs(s, ctx, refs, approved=True)
    if decision.outcome != "approved" or not decision.created_definition_id:
        fail("VALIDATION_FAILED", "unsigned_consumption", "只有已批准的固定定义可登记消费。")
    for identity in sorted(claims, key=str):
        row = claims[identity]
        s.add(
            Consumption(
                tenant_id=ctx.tenant_id,
                category_id=ctx.category_id,
                product_id=decision.created_product_id,
                claim_id=row.id,
                claim_version=row.revision,
                decision_id=decision.id,
                definition_id=decision.created_definition_id,
                receipt_id=decision.receipt_id,
                consumer_type="proposal_decision",
                consumer_id=decision.id,
            )
        )
