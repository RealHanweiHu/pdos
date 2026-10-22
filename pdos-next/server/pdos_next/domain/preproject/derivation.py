"""Prepare derivative proposals from fixed readable baselines; calculate, never publish."""

from copy import deepcopy
from uuid import UUID

from pydantic import BaseModel

from pdos_next.domain.products import variants
from pdos_next.schemas.products.derivation import (
    ApplicabilityScope,
    DerivationRequest,
    ObjectReference,
    Override,
    SpecSnapshot,
)

from .access import fail
from .baseline import published_baseline
from .schemas import ItemInput, Reference, SpecItem

PROVENANCE_FIELDS = frozenset({"origin", "writer_id", "run_id", "confirmed_by", "receipt_id"})
BASELINE_FIELDS = ("baseline_product_id", "baseline_definition_id", "baseline_definition_revision")


def _get(value, key, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def _derivative(value):
    return _get(value, "entry_kind") == "derivative" or _get(value, "target_kind") == "new_variant"


def _dict(value):
    return value.model_dump(mode="json") if isinstance(value, BaseModel) else deepcopy(value)


def _fixed_reference(parent, key):
    return Reference(
        type="definition",
        id=parent["id"],
        version=parent["revision"],
        statement=variants._spec_path(key),
    )


def _key(item_ref, parent_specs):
    """Resolve exact keys, escaped paths or exact dictionary parameter versions."""
    if isinstance(item_ref, dict):
        if "key" in item_ref or "path" in item_ref:
            return _key(item_ref.get("key", item_ref.get("path")), parent_specs)
        parameter = item_ref.get("parameter_id")
        version = item_ref.get("parameter_version", item_ref.get("version"))
        matches = [
            spec["key"]
            for spec in parent_specs
            if (
                parameter is not None
                and str(spec.get("parameter_id")) == str(parameter)
                and spec.get("parameter_version") == version
            )
        ]
        return matches[0] if len(matches) == 1 else None
    if not isinstance(item_ref, str) or not item_ref:
        return None
    # Literal keys take precedence over paths, including keys that contain '/'.
    if any(spec["key"] == item_ref for spec in parent_specs):
        return item_ref
    if item_ref.startswith("specs/") and variants._valid_path(item_ref):
        return variants._spec_key(item_ref)
    if "@" in item_ref:
        parameter, version = item_ref.rsplit("@", 1)
        try:
            return _key({"parameter_id": UUID(parameter), "version": int(version)}, parent_specs)
        except (ValueError, TypeError):
            return None
    return item_ref


def _difference_sources(item):
    """Expose explicitly supplied difference references to normal item authorization."""
    refs = list(item.source_refs)
    for raw in item.content.get("sources", ()):
        ref = Reference.model_validate(raw)
        if ref not in refs:
            refs.append(ref)
    return item.model_copy(update={"source_refs": refs}, deep=True)


def _inherited_spec(parent, raw):
    source = SpecSnapshot.model_validate(raw)
    values = source.model_dump(mode="json")
    data = {key: deepcopy(values[key]) for key in SpecItem.model_fields if key in values}
    data.update(
        text_value=source.text,
        verification_method=source.method,
        owner_id=None,
        item_status="ai_draft" if source.origin == "ai_draft" else "unknown",
    )
    # No writer, confirmation or receipt is borrowed. The real command supplies
    # current provenance; this exact definition reference preserves original trace.
    return ItemInput(kind="spec", content=data, source_refs=[_fixed_reference(parent, source.key)])


def prepare_create(s, ctx, payload):
    """Return a verified parent and the server-expanded initial item set."""
    given = [item.model_copy(deep=True) for item in payload.groups.items]
    for item in given:
        if PROVENANCE_FIELDS.intersection(item.content):
            fail(
                "VALIDATION_FAILED", "derivation_provenance_supplied", "条目署名须由当前命令记录。"
            )
    if not _derivative(payload):
        return None, given
    given = [_difference_sources(item) if item.kind == "difference" else item for item in given]
    parent = published_baseline(
        s,
        ctx,
        payload.baseline_product_id,
        payload.baseline_definition_revision,
        definition_id=payload.baseline_definition_id,
        extra_refs=[
            *payload.source_refs,
            *payload.context_refs,
            *(ref for item in given for ref in item.source_refs),
        ],
    )
    parent_specs = parent.get("specs", [])
    specified = [item.content["key"] for item in given if item.kind == "spec"]
    if len(set(specified)) != len(specified):
        fail("VALIDATION_FAILED", "duplicate_spec_key", "一个提案不能同时给出同一规格的两个值。")
    removed, prepared = set(), []
    for item in given:
        if item.kind == "difference":
            if (
                item.content.get("area") == "specification"
                and item.content.get("change") == "removed"
            ):
                key = _key(item.content.get("item_ref"), parent_specs)
                if key not in {spec["key"] for spec in parent_specs}:
                    fail(
                        "VALIDATION_FAILED",
                        "derivation_item_reference_invalid",
                        "待移除规格须引用固定父版的真实条目。",
                    )
                if key in specified:
                    fail(
                        "VALIDATION_FAILED",
                        "derivation_conflicting_override",
                        "同一规格不能同时替换和移除。",
                    )
                removed.add(key)
        prepared.append(item)
    inherited = [
        _inherited_spec(parent, spec)
        for spec in parent_specs
        if spec["key"] not in set(specified) | removed
    ]
    return parent, [*inherited, *prepared]


def validate_baseline(s, ctx, row_or_document, document=None):
    """Re-read the exact parent at submit/decision time, retaining all read guards."""
    data = (
        document
        if document is not None
        else _get(row_or_document, "frozen_document", row_or_document)
    )
    if not _derivative(data):
        return None
    if document is not None:
        for field in BASELINE_FIELDS:
            if str(_get(row_or_document, field)) != str(_get(document, field)):
                fail(
                    "VERSION_CONFLICT",
                    "baseline_version_changed",
                    "在审提案的固定父版与当前记录不一致。",
                )
    product, identity, revision = (_get(data, field) for field in BASELINE_FIELDS)
    if product is None or identity is None or type(revision) is not int or revision < 1:
        fail("SOURCE_UNAVAILABLE", "baseline_not_published", "派生提案缺少完整的固定父版引用。")
    try:
        product, identity = UUID(str(product)), UUID(str(identity))
    except (ValueError, TypeError, AttributeError):
        fail("SOURCE_UNAVAILABLE", "baseline_not_published", "派生提案的固定父版引用无效。")
    from .service import _all_refs_from_document

    return published_baseline(
        s, ctx, product, revision, definition_id=identity, extra_refs=_all_refs_from_document(data)
    )


def _child_spec(item):
    content = SpecItem.model_validate(item["content"]).model_dump(mode="json")
    content["text"] = content.pop("text_value")
    content["method"] = content.pop("verification_method")
    content.update(
        sources=[],
        source_refs=deepcopy(item.get("source_refs", [])),
        state="proposed",
        **{field: item[field] for field in PROVENANCE_FIELDS if field in item},
    )
    return content


def _calculation_overrides(parent, child, document):
    """Use explicit difference trace only; missing rationale/scope stays a diagnostic."""
    traces, overrides, missing = [], [], []
    child_keys = {spec.key for spec in child.content.specs}
    parent_keys = {spec.key for spec in parent.content.specs}
    by_path = {}
    for item in document.get("items", []):
        if item["kind"] != "difference":
            continue
        trace = deepcopy(item)
        traces.append(trace)
        content = item["content"]
        if content.get("area") != "specification":
            continue
        key = _key(content.get("item_ref"), [spec.model_dump() for spec in parent.content.specs])
        if key is None:
            missing.append(
                {
                    "path": "",
                    "code": "difference_reference_unknown",
                    "detail": "Specification path remains unknown",
                }
            )
            continue
        path = variants._spec_path(key)
        if key not in child_keys | parent_keys:
            missing.append(
                {
                    "path": path,
                    "code": "difference_reference_unknown",
                    "detail": "Specification is absent from both fixed snapshots",
                }
            )
            continue
        change = content.get("change")
        if change not in {"added", "removed", "changed"}:
            missing.append(
                {
                    "path": path,
                    "code": "difference_change_unknown",
                    "detail": "Explicit change remains unknown",
                }
            )
            continue
        operation = "delete" if change == "removed" else "set"
        if (operation == "delete") != (key not in child_keys):
            missing.append(
                {
                    "path": path,
                    "code": "difference_value_mismatch",
                    "detail": "Difference does not describe the current proposal",
                }
            )
            continue
        reason, applicability = content.get("reason"), content.get("applicability")
        if not isinstance(reason, str) or not reason.strip():
            missing.append(
                {
                    "path": path,
                    "code": "difference_reason_missing",
                    "detail": "Explicit reason remains incomplete",
                }
            )
            continue
        if not isinstance(applicability, str) or not applicability.strip():
            missing.append(
                {
                    "path": path,
                    "code": "difference_applicability_missing",
                    "detail": "Explicit applicability remains incomplete",
                }
            )
            continue
        refs = [
            ObjectReference.model_validate(ref)
            for ref in (*item.get("source_refs", []), *content.get("sources", []))
        ]
        unique_refs = tuple(dict.fromkeys(refs))
        candidate = Override(
            path=path,
            operation=operation,
            reason=reason,
            sources=unique_refs,
            scope=ApplicabilityScope(
                category_id=child.ref.category_id,
                product_id=child.ref.product_id,
                variant_id=child.ref.variant_id,
                description=applicability,
            ),
        )
        if path in by_path:
            missing.append(
                {
                    "path": path,
                    "code": "duplicate_difference_trace",
                    "detail": "Multiple explicit traces describe this path",
                }
            )
            by_path[path] = None
        else:
            by_path[path] = candidate
    overrides.extend(candidate for candidate in by_path.values() if candidate is not None)
    return tuple(overrides), traces, missing


def calculation(baseline_view, doc, *, proposal_id=None, revision=None):
    """Compare a real proposal revision to its fixed parent with the unique engine."""
    from pdos_next.service import digest

    document = _dict(doc)
    document["items"] = [_dict(item) for item in document.get("items", [])]
    identity = proposal_id or document.get("proposal_id", document.get("id"))
    proposal_revision = revision if revision is not None else document.get("revision")
    if identity is None or type(proposal_revision) is not int or proposal_revision < 1:
        fail("VERSION_CONFLICT", "proposal_revision_required", "比较须绑定真实提案及其固定版本。")
    try:
        identity = UUID(str(identity))
    except (ValueError, TypeError, AttributeError):
        fail("VERSION_CONFLICT", "proposal_revision_required", "比较须绑定有效的提案标识。")
    for field, expected in zip(
        BASELINE_FIELDS,
        (baseline_view["product_id"], baseline_view["id"], baseline_view["revision"]),
        strict=True,
    ):
        if field in document and str(document[field]) != str(expected):
            fail("VERSION_CONFLICT", "baseline_version_changed", "比较基线与提案固定的父版不一致。")
    parent = variants.snapshot_from_definition(
        baseline_view, variant_id=baseline_view.get("variant_id")
    )
    child_view = {
        "id": identity,
        "revision": proposal_revision,
        "category_id": parent.ref.category_id,
        "product_id": parent.ref.product_id,
        "title": document.get("title", ""),
        "status": document.get("status", "draft"),
        "purpose": document.get("brief", ""),
        "sources": [],
        "source_refs": document.get("source_refs", []),
        "specs": [_child_spec(item) for item in document["items"] if item["kind"] == "spec"],
    }
    # The comparison DTO uses definition_id as a snapshot identity. Here that
    # identity is the actual proposal, explicitly labeled below; no product or
    # definition identity is allocated and no parent revision is fabricated.
    child = variants.snapshot_from_definition(child_view)
    overrides, traces, extra_missing = _calculation_overrides(parent, child, document)
    request = DerivationRequest(
        old_parent=parent,
        new_parent=parent,
        child=child,
        pinned_parent=parent.ref,
        overrides=overrides,
    )
    result = variants.compare_snapshots(request, allow_same_parent=True).model_dump(mode="json")
    proposal_ref = {"id": str(identity), "revision": proposal_revision, "kind": "proposal"}
    document_digest = digest({"proposal": proposal_ref, "document": document})
    return {
        **result,
        "engine_request_digest": result["request_digest"],
        "request_digest": digest(
            {"comparison": result["request_digest"], "document": document_digest}
        ),
        "document_digest": document_digest,
        "baseline": parent.ref.model_dump(mode="json"),
        "proposal": proposal_ref,
        "difference_traces": traces,
        "missing": [*result["missing"], *extra_missing],
    }
