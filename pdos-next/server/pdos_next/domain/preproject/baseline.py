"""Read fixed baselines and verify publication receipts; never publish a definition."""

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from pdos_next.domain.products.definitions import definition_view
from pdos_next.domain.products.models import DefinitionRevision
from pdos_next.domain.products.variant_models import Variant
from pdos_next.errors import DomainError
from pdos_next.models import Principal, Product, Receipt
from pdos_next.schemas.products.derivation import ObjectReference, SourceReference, SpecSnapshot

from .access import fail
from .baseline_blocks import read_blocks

# Status, sealing and the publication-receipt pointer are checked separately.
# They are not hashed: publication binds already-fixed content, without a cycle
# through the digest-bearing receipt. Source titles/status are read projections.
HEAD_FIELDS = (
    "id",
    "category_id",
    "product_id",
    "variant_id",
    "revision",
    "owner_id",
    "title",
    "purpose",
    "visibility",
    "parent_definition_id",
    "derived_from_definition_id",
    "derived_from_definition_revision",
    "use_cases",
    "requirements",
    "constraints",
    "unknowns",
    "exclusions",
    "change_reason",
    "source_proposal_id",
    "source_submission_id",
    "source_proposal_revision",
    "g0_decision_id",
    "created_at",
)
UUID_FIELDS = frozenset(field for field in HEAD_FIELDS if field == "id" or field.endswith("_id"))
SET_FIELDS = frozenset({"sources", "source_refs", "specs", "spec_keys", "test_conditions"})


def _canonical(value, field=""):
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Publication content requires finite exact decimals")
        number = format(value, "f")
        number = number.rstrip("0").rstrip(".") if "." in number else number
        return "0" if value == 0 else number
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _canonical(item, key) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        result = [_canonical(item) for item in value]
        if field in SET_FIELDS:
            result.sort(key=_json)
        return result
    if isinstance(value, float):
        raise ValueError("Publication content must not use inexact floats")
    return value


def _json(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


def _reference(raw, *, include_spec_keys=False):
    model = ObjectReference if "type" in raw else SourceReference
    value = model.model_validate({key: raw[key] for key in model.model_fields if key in raw})
    result = value.model_dump()
    if include_spec_keys and "spec_keys" in raw:
        result["spec_keys"] = raw["spec_keys"]
    return result


def publication_document(view):
    """Canonical immutable content, excluding every mutable source/UI projection."""
    document = {field: view.get(field) for field in HEAD_FIELDS}
    for field in UUID_FIELDS:
        if document[field] is not None:
            document[field] = UUID(str(document[field]))
    document["sources"] = [
        _reference(ref, include_spec_keys=True) for ref in view.get("sources", ())
    ]
    document["source_refs"] = [_reference(ref) for ref in view.get("source_refs", ())]
    document["specs"] = []
    for raw in view.get("specs", ()):
        spec = dict(raw)
        for field in ("sources", "source_refs"):
            if field in spec:
                spec[field] = [_reference(ref) for ref in spec[field]]
        # Keep every M3 business field. Unknown fields fail rather than silently
        # escaping the publication digest; aliases and decimals are normalized.
        document["specs"].append(SpecSnapshot.model_validate(spec).model_dump())
    return _canonical(document)


def publication_digest(view):
    return hashlib.sha256(_json(publication_document(view)).encode("utf-8")).hexdigest()


# Short alias for callers that already name the publication context.
digest = publication_digest


def _unavailable(message="所选基线没有可核对的具名发布事实。", **detail):
    fail("SOURCE_UNAVAILABLE", "baseline_not_published", message, **detail)


def _scope(s, ctx, product_id, variant_id):
    from pdos_next.service import require_access

    require_access(s, ctx, product_id)
    product = s.scalar(
        select(Product).where(
            Product.id == product_id,
            Product.tenant_id == ctx.tenant_id,
            Product.category_id == ctx.category_id,
        )
    )
    if not product or (
        product.id != product_id
        or product.tenant_id != ctx.tenant_id
        or product.category_id != ctx.category_id
    ):
        _unavailable("型号不在当前可读品类范围。")
    if variant_id is not None:
        variant = s.scalar(
            select(Variant).where(
                Variant.id == variant_id,
                Variant.tenant_id == ctx.tenant_id,
                Variant.category_id == ctx.category_id,
                Variant.product_id == product_id,
            )
        )
        if not variant or (
            variant.id != variant_id
            or variant.tenant_id != ctx.tenant_id
            or variant.category_id != ctx.category_id
            or variant.product_id != product_id
        ):
            _unavailable("变体不在当前可读型号范围。")


def _query(ctx, product_id, variant_id):
    variant_column = DefinitionRevision.variant_id
    return select(DefinitionRevision).where(
        DefinitionRevision.tenant_id == ctx.tenant_id,
        DefinitionRevision.category_id == ctx.category_id,
        DefinitionRevision.product_id == product_id,
        variant_column == variant_id if variant_id is not None else variant_column.is_(None),
    )


def _row_scope(row, ctx, product_id, variant_id):
    if not row or (
        row.tenant_id != ctx.tenant_id
        or row.category_id != ctx.category_id
        or row.product_id != product_id
        or row.variant_id != variant_id
    ):
        _unavailable("固定定义不在当前可读范围。")


def _published_view(s, ctx, row, *, before_definition_read=None):
    if row.status != "published" or row.sealed is not True or not row.publication_receipt_id:
        _unavailable()
    receipt_query = select(Receipt).where(
        Receipt.id == row.publication_receipt_id,
        Receipt.tenant_id == ctx.tenant_id,
        Receipt.category_id == ctx.category_id,
        Receipt.product_id == row.product_id,
    )
    if before_definition_read is not None:
        from sqlalchemy.orm import load_only

        receipt_query = receipt_query.options(
            load_only(
                Receipt.id,
                Receipt.tenant_id,
                Receipt.category_id,
                Receipt.product_id,
                Receipt.operation,
                Receipt.subject_type,
                Receipt.subject_id,
                Receipt.subject_revision,
                Receipt.actor_id,
                Receipt.requester_id,
                Receipt.run_id,
                Receipt.agent_run_id,
                Receipt.result,
            )
        )
    receipt = s.scalar(receipt_query)
    if not receipt or (
        receipt.id != row.publication_receipt_id
        or receipt.tenant_id != ctx.tenant_id
        or receipt.category_id != ctx.category_id
        or receipt.product_id != row.product_id
        or receipt.operation != "product.definition.publish"
        or receipt.subject_type != "definition_revision"
        or receipt.subject_id != row.id
        or receipt.subject_revision != row.revision
        or receipt.actor_id != receipt.requester_id
        or receipt.run_id is not None
        or receipt.agent_run_id is not None
        or not isinstance(receipt.result, dict)
    ):
        _unavailable()
    signer_query = select(Principal).where(
        Principal.id == receipt.actor_id,
        Principal.tenant_id == ctx.tenant_id,
    )
    if before_definition_read is not None:
        signer_query = signer_query.options(
            load_only(Principal.id, Principal.tenant_id, Principal.kind)
        )
    signer = s.scalar(signer_query)
    # Current membership/activity is not re-interpreted as signing-time authority.
    if not signer or (
        signer.id != receipt.actor_id or signer.tenant_id != ctx.tenant_id or signer.kind != "human"
    ):
        _unavailable()
    if before_definition_read is not None:
        before_definition_read(row)
    view = definition_view(s, ctx, row)  # Preserves the existing source-read guard.
    if (
        str(view["id"]) != str(row.id)
        or view["revision"] != row.revision
        or str(view["category_id"]) != str(row.category_id)
        or str(view["product_id"]) != str(row.product_id)
        or view.get("variant_id") != (str(row.variant_id) if row.variant_id else None)
    ):
        fail("VERSION_CONFLICT", "baseline_version_changed", "固定定义读取结果已变化。")
    try:
        content_digest = publication_digest(view)
    except (TypeError, ValueError):
        _unavailable("发布定义的固定内容无法核对。")
    if receipt.result.get("definition_digest") != content_digest:
        _unavailable("发布回执与固定定义内容不一致。")
    synthetic = receipt.result.get("synthetic", False)
    if type(synthetic) is not bool:
        _unavailable("发布回执的合成标记无效。")
    return {
        **view,
        "baseline_kind": "published",
        "publication": {
            "receipt_id": str(receipt.id),
            "definition_digest": content_digest,
            "synthetic": synthetic,
        },
    }


def _source_references(view):
    """Read every persisted source edge, including dictionary columns on specs."""
    from .schemas import Reference

    for node in (view, *view.get("specs", ())):
        for raw in (*node.get("sources", ()), *node.get("source_refs", ())):
            if "type" in raw:
                yield Reference.model_validate(raw)
            else:
                yield Reference(
                    type="artifact",
                    id=raw["artifact_id"],
                    version=raw["expected_revision"],
                    line=raw["line"],
                    quote=raw["quote"],
                )
        if node.get("parameter_id") is not None:
            yield Reference(
                type="parameter", id=node["parameter_id"], version=node["parameter_version"]
            )


def _historical_source_access(s, ctx, product_id, ref):
    """Prove body access independently of active status; never use metadata helpers."""
    from sqlalchemy.orm import load_only

    from pdos_next.agent_kernel.models import PublicWebSnapshot
    from pdos_next.models import Artifact
    from pdos_next.originals import require_original
    from pdos_next.service import require_access

    model = PublicWebSnapshot if ref.type == "snapshot" else Artifact
    columns = [model.id, model.tenant_id, model.category_id]
    if model is Artifact:
        columns.extend([Artifact.product_id, Artifact.original_id])
    row = s.scalar(
        select(model)
        .where(
            model.id == ref.id,
            model.tenant_id == ctx.tenant_id,
            model.category_id == ctx.category_id,
        )
        .options(load_only(*columns))
        .execution_options(populate_existing=True)
    )
    if not row or row.tenant_id != ctx.tenant_id or row.category_id != ctx.category_id:
        fail("SOURCE_UNAVAILABLE", "source_unreadable", "来源正文不在当前可读范围。", 403)
    if model is Artifact:
        if row.product_id is not None:
            require_access(s, ctx, row.product_id)
        if product_id is not None:
            require_access(s, ctx, product_id)
        if row.original_id:
            require_original(s, ctx, row.product_id, row.original_id)


def _redact_source_metadata(document):
    from copy import deepcopy

    result = deepcopy(document)

    def walk(value):
        if isinstance(value, dict):
            if "artifact_id" in value or ("type" in value and "id" in value and "version" in value):
                for key in ("quote", "line", "statement", "title", "url", "final_url", "locator"):
                    value.pop(key, None)
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    walk(result)
    result["source_status"] = "stale"
    return result


def validate_sources(
    s, ctx, view, *, extra_refs=(), history_permissions=False, resolved_references=None
):
    """Revalidate the entire readable fixed tree before allowing new consumption.

    Traversal acquires no Claim locks. All Claims are then locked together in the
    shared UUID order before resolving source bodies under ordinary caller RLS.
    """
    from .category_models import KnowledgeEntry
    from .category_service import _references as knowledge_references
    from .claim_access import load_source
    from .root_sources import lock_claim_refs
    from .schemas import Reference
    from .service import _references

    pending, done, active = [], set(), set()

    def enter(kind, identity, version):
        key = (kind, UUID(str(identity)), version)
        if key in active:
            fail("SOURCE_UNAVAILABLE", "baseline_source_cycle", "固定来源存在循环。")
        if key in done:
            return None
        active.add(key)
        return key

    def finish(key):
        active.remove(key)
        done.add(key)

    def definition(identity, version=None):
        row = s.scalar(
            select(DefinitionRevision)
            .where(
                DefinitionRevision.id == identity,
                DefinitionRevision.tenant_id == ctx.tenant_id,
                DefinitionRevision.category_id == ctx.category_id,
            )
            .execution_options(populate_existing=True)
        )
        if (
            not row
            or row.tenant_id != ctx.tenant_id
            or row.category_id != ctx.category_id
            or (version is not None and row.revision != version)
        ):
            fail("SOURCE_UNAVAILABLE", "baseline_unreadable", "固定来源定义不可读或版本不符。")
        return row

    def edge(product_id, ref):
        pending.append((product_id, ref))
        if ref.type == "definition":
            visit(definition_view(s, ctx, definition(ref.id, ref.version)))
        elif ref.type == "knowledge":
            key = enter("knowledge", ref.id, ref.version)
            if key is None:
                return
            row = s.scalar(
                select(KnowledgeEntry)
                .where(
                    KnowledgeEntry.id == ref.id,
                    KnowledgeEntry.tenant_id == ctx.tenant_id,
                    KnowledgeEntry.category_id == ctx.category_id,
                )
                .execution_options(populate_existing=True)
            )
            if (
                not row
                or row.tenant_id != ctx.tenant_id
                or row.category_id != ctx.category_id
                or row.version != ref.version
                or row.action == "withdraw"
            ):
                fail("SOURCE_UNAVAILABLE", "knowledge_unreadable", "所选知识固定版本不可读。")
            # Knowledge is category material; it does not borrow a product scope.
            from types import SimpleNamespace

            for reference in knowledge_references(
                SimpleNamespace(
                    kind=row.kind,
                    content=row.content,
                    source_refs=[Reference.model_validate(raw) for raw in row.source_refs],
                )
            ):
                edge(None, reference)
            finish(key)

    def visit(document):
        key = enter("definition", document["id"], document["revision"])
        if key is None:
            return
        product_id = UUID(str(document["product_id"]))
        for ref in _source_references(document):
            edge(product_id, ref)
        if document.get("derived_from_definition_id") is not None:
            edge(
                product_id,
                Reference(
                    type="definition",
                    id=document["derived_from_definition_id"],
                    version=document["derived_from_definition_revision"],
                ),
            )
        if document.get("parent_definition_id") is not None:
            identity = UUID(str(document["parent_definition_id"]))
            parent = definition(identity)
            pending.append(
                (
                    product_id,
                    Reference(
                        type="definition",
                        id=identity,
                        version=parent.revision,
                    ),
                )
            )
            visit(definition_view(s, ctx, parent))
        finish(key)

    if view is not None:
        visit(view)
    for reference in extra_refs:
        edge(UUID(str(view["product_id"])) if view is not None else None, reference)
    all_refs = [ref for _, ref in pending]
    read_snapshot = bool(getattr(s, "info", {}).get("read_snapshot", False))
    if read_snapshot or history_permissions:
        from .claim_access import resolve

        claims = {
            identity: resolve(
                s,
                ctx,
                identity,
                version,
                **({"allow_withdrawn": True} if history_permissions else {"approved": True}),
            )
            for identity, version in sorted(
                {(ref.id, ref.version) for ref in all_refs if ref.type == "claim"},
                key=lambda pair: (str(pair[0]), pair[1]),
            )
        }
    else:
        claims = lock_claim_refs(s, ctx, all_refs, approved=True)
    for product_id, ref in pending:
        if ref.type == "definition":
            continue  # Already traversed through ordinary scoped definition reads.
        if ref.type == "claim":
            claim = claims[ref.id]
            if history_permissions:
                from .claim_access import source_reference

                _historical_source_access(s, ctx, claim.product_id, source_reference(claim))
                continue
            if (ref.quote is not None and ref.quote not in claim.quote) or (
                ref.line is not None and ref.line != claim.line
            ):
                fail("VALIDATION_FAILED", "quote_not_in_source", "引用不在事实的固定来源定位处。")
        elif history_permissions and ref.type in {"artifact", "original", "snapshot"}:
            _historical_source_access(s, ctx, product_id, ref)
        elif ref.type in {"artifact", "original"}:
            from sqlalchemy.orm import load_only

            from pdos_next.models import Artifact

            # Typed fixed references may originate in a different readable
            # Product, through Knowledge or an actual signed EvidenceLink.
            # Scope comes from the RLS-visible source header, never the payload.
            source = s.scalar(
                select(Artifact)
                .where(
                    Artifact.id == ref.id,
                    Artifact.tenant_id == ctx.tenant_id,
                    Artifact.category_id == ctx.category_id,
                )
                .options(load_only(Artifact.id, Artifact.product_id))
            )
            if source is None:
                fail("SOURCE_UNAVAILABLE", "source_unreadable", "固定来源不可读取。", 403)
            load_source(
                s,
                ctx,
                ref.model_copy(update={"type": "artifact"}),
                product_id=source.product_id,
                lock=not read_snapshot,
            )
        else:
            # AT53 preserves fixed historic knowledge entries and parameter versions.
            _references(s, ctx, [ref], approved=True)
    if resolved_references is not None:
        from .claim_access import source_reference

        resolved_references.extend(ref for _, ref in pending)
        resolved_references.extend(source_reference(claim) for claim in claims.values())
    return tuple(
        Reference(type="claim", id=identity, version=claims[identity].revision)
        for identity in sorted({ref.id for _, ref in pending if ref.type == "claim"}, key=str)
    )


def validate_references(s, ctx, refs):
    """Resolve an actual proposal's complete reference tree without inventing a definition."""
    return validate_sources(s, ctx, None, extra_refs=refs)


def published_baseline(
    s, ctx, product_id, revision, definition_id=None, variant_id=None, *, extra_refs=()
):
    """Read one exact published baseline through ordinary caller RLS."""
    _scope(s, ctx, product_id, variant_id)
    if type(revision) is not int or revision < 1:
        fail("VERSION_CONFLICT", "baseline_version_changed", "请选择明确的固定定义版本。")
    query = _query(ctx, product_id, variant_id)
    query = query.where(
        DefinitionRevision.id == definition_id
        if definition_id is not None
        else DefinitionRevision.revision == revision
    )
    row = s.scalar(query)
    _row_scope(row, ctx, product_id, variant_id)
    if row.revision != revision or (definition_id is not None and row.id != definition_id):
        fail("VERSION_CONFLICT", "baseline_version_changed", "固定父定义版本不匹配。")
    view = _published_view(s, ctx, row)
    claim_refs = validate_sources(s, ctx, view, extra_refs=extra_refs)
    if claim_refs:
        view["baseline_claim_refs"] = [ref.model_dump(mode="json") for ref in claim_refs]
    return view


def read_baseline(
    s,
    ctx,
    product_id,
    variant_id=None,
    definition_revision=None,
    *,
    before_definition_read=None,
    sources_current=None,
    include_blocks=True,
    block_areas=None,
):
    """Present an honest fallback; only a verified publication is derivation eligible."""
    _scope(s, ctx, product_id, variant_id)
    query = _query(ctx, product_id, variant_id).order_by(DefinitionRevision.revision.desc())
    if definition_revision is not None:
        if type(definition_revision) is not int or definition_revision < 1:
            fail("VERSION_CONFLICT", "baseline_version_changed", "请选择明确的固定定义版本。")
        query = query.where(DefinitionRevision.revision == definition_revision)
    if before_definition_read is not None:
        from sqlalchemy.orm import load_only

        query = query.options(
            load_only(
                DefinitionRevision.id,
                DefinitionRevision.tenant_id,
                DefinitionRevision.category_id,
                DefinitionRevision.product_id,
                DefinitionRevision.variant_id,
                DefinitionRevision.revision,
                DefinitionRevision.status,
                DefinitionRevision.sealed,
                DefinitionRevision.g0_decision_id,
                DefinitionRevision.publication_receipt_id,
            )
        )
    rows = list(s.scalars(query))
    for row in rows:
        _row_scope(row, ctx, product_id, variant_id)
    chosen, kind, unavailable = None, "unavailable", 0
    groups = (
        ("published", [row for row in rows if row.status == "published"]),
        (
            "g0",
            [
                row
                for row in rows
                if (
                    row.status == "draft"
                    and row.sealed is True
                    and row.revision == 1
                    and row.g0_decision_id is not None
                )
            ],
        ),
        ("draft", [row for row in rows if row.status == "draft"]),
    )
    visited = set()
    source_issues = []
    hidden_errors = {
        "SOURCE_UNAVAILABLE",
        "FORBIDDEN_SCOPE",
        "VERSION_CONFLICT",
        "NOT_FOUND",
        "SOURCE_STALE",
        "VALIDATION_FAILED",
    }
    callback_failed = False

    def authorize(row):
        nonlocal callback_failed
        if before_definition_read is not None:
            try:
                before_definition_read(row)
            except DomainError:
                callback_failed = True
                raise

    for candidate_kind, candidates in groups:
        for row in candidates:
            if row.id in visited:
                continue
            visited.add(row.id)
            try:
                if candidate_kind == "published":
                    candidate = (
                        _published_view(s, ctx, row, before_definition_read=authorize)
                        if before_definition_read is not None
                        else _published_view(s, ctx, row)
                    )
                else:
                    authorize(row)
                    candidate = definition_view(s, ctx, row)
                issues = []
                # A trusted Run reader can reuse its initial source closure and
                # this RR transaction's current watermarks. Other readers retain
                # the ordinary full proof, including historical body access.
                if sources_current is None or not sources_current(candidate):
                    validate_sources(s, ctx, candidate, history_permissions=True)
                    try:
                        validate_sources(s, ctx, candidate)
                    except DomainError as error:
                        if error.code != "SOURCE_STALE":
                            raise
                        issues.append(
                            {
                                "code": error.code,
                                "reason": (error.detail or {}).get("reason", "source_stale"),
                            }
                        )
                        candidate = _redact_source_metadata(candidate)
            except DomainError as error:
                if callback_failed or error.code not in hidden_errors:
                    raise
                unavailable += 1
                continue
            chosen, kind, source_issues = candidate, candidate_kind, issues
            break
        if chosen is not None:
            break
    blocks = {
        "bom": {"status": "unknown", "items": [], "reason": "definition_binding_unavailable"},
        **{
            name: {"status": "unknown", "items": [], "reason": "baseline_block_not_available"}
            for name in ("certification", "tooling", "platform")
        },
    }
    if include_blocks and (block_areas is None or "bom" in block_areas):
        blocks.update(read_blocks(s, ctx, chosen))
    if include_blocks and (block_areas is None or "platform" in block_areas):
        from pdos_next.domain.products.platforms import read as read_platforms

        linked = read_platforms(
            s,
            ctx,
            {
                "product_id": product_id,
                "variant_id": variant_id,
                "page_size": 200,
            },
        )
        references = [
            {**platform, "links": [link for link in platform["links"] if link["attached"]]}
            for platform in linked["items"]
            if any(link["attached"] for link in platform["links"])
        ]
        blocks["platform"] = {
            "status": "available" if references else "unknown",
            "items": references,
            "basis": "current_product_links",
            "next_cursor": linked["next_cursor"],
            "reason": None if references else "no_current_platform_links",
        }
    return {
        "definition": chosen,
        "baseline_kind": kind,
        "derivation_eligible": kind == "published" and not source_issues,
        "source_issues": source_issues,
        "blocks": blocks,
        "unavailable_blocks": [
            name for name, block in blocks.items() if block["status"] == "unknown"
        ],
        "unavailable_definition_count": unavailable,
    }
