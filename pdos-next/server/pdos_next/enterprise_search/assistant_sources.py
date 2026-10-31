"""Batch authoritative citation rechecks under the actual Human requester's RR/RLS."""

import hashlib
from functools import lru_cache
from uuid import UUID

from sqlalchemy import bindparam, func, select, tuple_

from pdos_next.agent_kernel.extract_read_ledger import ArtifactSeal
from pdos_next.agent_kernel.extract_sources import _manifest
from pdos_next.agent_kernel.models import PublicWebSnapshot
from pdos_next.database import tenant_session
from pdos_next.models import Claim, UploadedOriginal

from . import assistant_dependencies as dependencies
from .safety import safe_originals
from .sources import prepare_read, select_sources

FIXED_BUSINESS_RECORDS = frozenset(
    {
        "issue",
        "capa",
        "change",
        "external_wait",
        "supply",
        "build",
        "test_run",
        "field_feedback",
        "project_status",
        "manufacturing_document",
        "verification_handoff",
    }
)


def human_snapshot(engine, scope):
    # This is a read-only host projection for the stored requester. It never
    # changes the Run writer or creates a Human business command.
    return tenant_session(
        engine,
        scope.tenant_id,
        actor_id=scope.requester_id,
        requester_id=scope.requester_id,
        category_id=scope.category_id,
        read_snapshot=True,
    )



@lru_cache(maxsize=1024)
def _source_query(source_types, with_body):
    """Cache immutable SQL shape, never IDs, principals, rows or permission results."""
    sources = select_sources(include_body=True, source_types=source_types).subquery()
    fields = (
        list(sources.c)
        if with_body
        else [column for column in sources.c if column.key not in {"body", "structured"}]
        + [sources.c.structured["source_refs"].label("source_refs"),
           sources.c.structured["knowledge_review"].label("knowledge_review")]
    )
    return select(*fields, func.transaction_timestamp().label("as_of")).where(
        tuple_(sources.c.source_type, sources.c.source_id).in_(
            bindparam("enterprise_source_keys", expanding=True),
        ),
    )


def current(session, citations, *, with_body=False, allow_updated=frozenset()):
    if not citations:
        return {}, {}
    keys = {(item["source_type"], UUID(item["source_id"])) for item in citations.values()}
    relation_origins = {
        (item["relation"]["source_type"], UUID(item["relation"]["source_id"]))
        for item in citations.values() if item.get("relation")
    }
    keys |= relation_origins
    prepare_read(session, {key[0] for key in keys})
    rows = (
        session.execute(
            _source_query(tuple(sorted({key[0] for key in keys})), with_body),
            {"enterprise_source_keys": list(keys)},
        )
        .mappings()
        .all()
    )
    by_key = {(row["source_type"], row["source_id"]): dict(row) for row in rows}
    refs, roots = {}, {}
    for key, row in by_key.items():
        values = row.get("source_refs") or (
            row["structured"].get("source_refs", []) if row.get("structured") else []
        )
        # Knowledge references are a flat registered set: source creation already
        # rejects unsupported reference kinds. Recheck their current roots here.
        refs[key] = values
        for ref in values:
            if ref.get("type") in {"artifact", "original"}:
                roots[("artifact", UUID(ref["id"]))] = ref["version"]
    bases = {
        cid: dependencies.fixed(item, refs.get((item["source_type"], UUID(item["source_id"])), []))
        for cid, item in citations.items() if item["source_type"] == "knowledge"
    }
    fixed_roots = [dep.root for basis in bases.values() if basis for dep in basis.dependencies]
    for root in fixed_roots:
        if root.type == "artifact":
            roots[(root.type, root.id)] = root.version
    claim_refs = {
        UUID(ref["id"]): ref["version"]
        for values in refs.values()
        for ref in values
        if ref.get("type") == "claim"
    }
    claims = (
        {
            row.id: row
            for row in session.scalars(
                select(Claim).where(
                    Claim.id.in_(claim_refs),
                    Claim.status == "active",
                )
            )
        }
        if claim_refs
        else {}
    )
    for claim in claims.values():
        if claim.source_kind == "artifact" and claim.artifact_id:
            roots[("artifact", claim.artifact_id)] = claim.source_revision
    if roots:
        dep = select_sources(source_type="artifact").subquery()
        for row in session.execute(
            select(dep).where(tuple_(dep.c.source_type, dep.c.source_id).in_(roots))
        ).mappings():
            by_key.setdefault((row["source_type"], row["source_id"]), dict(row))
    snapshot_ids = {
        UUID(ref["id"])
        for values in refs.values()
        for ref in values
        if ref.get("type") == "snapshot"
    } | {claim.snapshot_id for claim in claims.values() if claim.snapshot_id}
    snapshot_ids |= {root.id for root in fixed_roots if root.type == "snapshot"}
    snapshots = (
        {
            row.id: row
            for row in session.scalars(
                select(PublicWebSnapshot).where(
                    PublicWebSnapshot.id.in_(snapshot_ids),
                    PublicWebSnapshot.status.in_(["ok", "partial"]),
                )
            )
        }
        if snapshot_ids
        else {}
    )
    original_ids = {row["original_id"] for row in by_key.values() if row["original_id"]}
    original_ids |= {
        identity for row in by_key.values() for identity in row.get("original_ids", [])
    }
    original_ids |= {root.original_id for root in fixed_roots if root.original_id}
    safe = safe_originals(session, original_ids)
    originals = (
        {
            row.id: row
            for row in session.scalars(
                select(UploadedOriginal).where(
                    UploadedOriginal.id.in_(safe),
                )
            )
        }
        if with_body and safe
        else {}
    )

    def artifact(identity, version, *, historical_record=False):
        row = by_key.get(("artifact", identity))
        return (
            row
            if row
            and (row["source_revision"] == version or historical_record)
            and (row["original_id"] is None or row["original_id"] in safe)
            else None
        )

    valid, missing = {}, {}
    for cid, item in citations.items():
        key = (item["source_type"], UUID(item["source_id"]))
        row = by_key.get(key)
        changed = bool(
            row
            and (
                row["source_revision"] != item["source_revision"]
                or row["content_hash"] != item["content_hash"]
            )
        )
        if (
            not row
            or str(row["category_id"]) != item["category_id"]
            or (row["original_id"] is not None and row["original_id"] not in safe)
            or set(row.get("original_ids", [])) - safe
        ):
            missing[cid] = "source_unavailable"
            continue
        if changed and (cid not in allow_updated or with_body):
            missing[cid] = "source_changed"
            continue
        row = dict(row)
        row["fixed_body_available"] = not changed
        basis = bases.get(cid)
        # The primary revision/hash above must still match before any body is
        # returned. A fixed KnowledgeEntry remains readable as historical data
        # when only its dependencies moved; no newer primary body is substituted.
        historical_dependencies = cid in allow_updated and bool(basis)
        if basis is False:
            missing[cid] = "source_dependency_unavailable"
            continue
        relation = item.get("relation")
        if relation:
            origin = by_key.get((relation["source_type"], UUID(relation["source_id"])))
            if (not origin or origin["category_id"] != row["category_id"]
                or origin["source_revision"] != relation["source_revision"]
                or origin["content_hash"] != relation["content_hash"]
                or set(origin["original_ids"]) - safe):
                missing[cid] = "relation_origin_unavailable"
                continue
            row["private"] |= origin["private"]
            row["customer_original"] |= origin["customer_original"]
        row["updated"] = (
            changed
            or row["is_current"] != item["is_current"]
            or row["read_basis_status"] != item.get("read_basis_status", "current")
        )
        if row["updated"]:
            row["private"] |= item["private"]
            row["customer_original"] |= item["customer_original"]
        bad = False
        dependency_changed = False
        for ref in refs.get(key, []):
            kind = ref.get("type")
            dependency = None
            if kind in {"artifact", "original"}:
                dependency = artifact(
                    UUID(ref["id"]),
                    ref["version"],
                    historical_record=key[0] in FIXED_BUSINESS_RECORDS or bool(basis),
                )
                bad |= dependency is None
            elif kind == "claim":
                claim = claims.get(UUID(ref["id"]))
                bad |= claim is None or claim.revision != ref["version"]
                if claim:
                    bad |= claim.category_id != row["category_id"]
                    row["private"] |= claim.privacy == "private" or claim.visibility != "category"
                    if claim.source_kind == "artifact":
                        dependency = artifact(claim.artifact_id, claim.source_revision,
                                              historical_record=bool(basis))
                        bad |= dependency is None
                    elif claim.source_kind == "snapshot":
                        snapshot = snapshots.get(claim.snapshot_id)
                        bad |= snapshot is None or claim.source_revision != 1
                        bad |= bool(snapshot and snapshot.category_id != row["category_id"])
                        row["private"] |= bool(snapshot and snapshot.visibility != "category")
                    else:
                        bad = True
            elif kind == "snapshot":
                snapshot = snapshots.get(UUID(ref["id"]))
                bad |= snapshot is None or ref["version"] != 1
                bad |= bool(snapshot and snapshot.category_id != row["category_id"])
                row["private"] |= bool(snapshot and snapshot.visibility != "category")
            elif kind not in {"human", "parameter"}:
                bad = True
            if dependency:
                bad |= dependency["category_id"] != row["category_id"]
                row["private"] |= dependency["private"]
                row["customer_original"] |= dependency["customer_original"]
        if with_body and hashlib.sha256(row["body"].encode()).hexdigest() != row["content_hash"]:
            bad = True
        if bad:
            missing[cid] = "source_dependency_unavailable"
            continue
        if basis:
            readable, moved = dependencies.recheck(basis, by_key, claims, snapshots, safe)
            if not readable:
                missing[cid] = "source_dependency_unavailable"
                continue
            for dep in basis.dependencies:
                if dep.root.type == "artifact":
                    old_root = by_key[(dep.root.type, dep.root.id)]
                    row["private"] |= old_root["private"]
                    row["customer_original"] |= old_root["customer_original"]
                else:
                    row["private"] |= snapshots[dep.root.id].visibility != "category"
            dependency_changed |= moved
            if dependency_changed and not historical_dependencies:
                missing[cid] = "source_dependency_changed"
                continue
        if key[0] == "knowledge" and dependencies.references(refs[key]):
            if basis is None:
                basis = dependencies.capture(refs[key], by_key, claims, snapshots)
            row["dependency_basis"] = basis.model_dump(mode="json")
        if dependency_changed:
            row["updated"], row["read_basis_status"] = True, "needs_recheck"
            row["private"] |= item["private"]
            row["customer_original"] |= item["customer_original"]
        if with_body and key[0] == "artifact":
            original = originals.get(row["original_id"])
            try:
                row["seal"] = ArtifactSeal.from_server(
                    artifact_id=row["source_id"],
                    revision=row["source_revision"],
                    content_hash=row["content_hash"],
                    text=row["body"],
                    total_lines=len(row["body"].splitlines()),
                    locator_map=original.locator_map if original else [],
                    parse_status=original.status if original else "parsed",
                    parse_code=original.parse_code if original else None,
                    parse_manifest=_manifest(original),
                )
            except (ValueError, TypeError, KeyError):
                missing[cid] = "source_parse_unavailable"
                continue
        valid[cid] = row
    return valid, missing
