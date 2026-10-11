import hashlib
import json
import re
from copy import deepcopy
from decimal import Decimal, localcontext
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import select

from pdos_next.errors import DomainError
from pdos_next.models import Principal
from pdos_next.schemas.products.definitions import DefinitionDraftPayload, DefinitionReference
from pdos_next.schemas.products.derivation import (
    CONTENT_FIELDS,
    AdoptionCandidate,
    AdoptionSelection,
    AdoptionTrace,
    DefinitionContent,
    DefinitionSnapshot,
    DerivationRequest,
    DerivationResult,
    Diagnostic,
    Difference,
    Override,
    PathValue,
    ReuseCheck,
    ReuseValidationPort,
    SourceReference,
    SpecSnapshot,
)
from pdos_next.schemas.products.variants import VariantDerivePayload

from .definitions import definition_view
from .definitions import validate as validate_definition
from .models import DefinitionRevision
from .variant_models import Variant, VariantRevision


def _classify(base, incoming, local, override=False):
    if base == incoming:
        return "child_only" if base != local else "unchanged"
    if local == incoming:
        return "same_change"
    return "conflict" if base != local or override else "parent_only"


SPEC_LOCAL_FIELDS = {"owner_id", "state"}
SPEC_PATH = re.compile(r"specs/[a-zA-Z0-9_-]{1,80}\Z")


class DerivationError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(f"{code}: {detail}")


def _valid_path(path: str) -> bool:
    return path in {f"field/{name}" for name in CONTENT_FIELDS} or bool(SPEC_PATH.fullmatch(path))


def _canonical(value: Any, name: str = "") -> Any:
    if isinstance(value, BaseModel):
        value = value.model_dump(exclude_unset=True)
    if isinstance(value, Decimal):
        # Decimal.normalize() can round to the active precision; formatting cannot.
        result = format(value, "f")
        result = result.rstrip("0").rstrip(".") if "." in result else result
        return "0" if value == 0 else result
    if isinstance(value, dict):
        return {key: _canonical(item, key) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        result = [_canonical(item) for item in value]
        if name in {"specs", "sources", "test_conditions", "overrides", "deleted_fields"}:
            result.sort(key=lambda item: json.dumps(item, sort_keys=True, default=str))
        return result
    return value


def _signature(cell: PathValue) -> str:
    value = cell.value
    if isinstance(value, SpecSnapshot):
        value = value.model_dump(exclude=SPEC_LOCAL_FIELDS)
    name = (
        "sources"
        if isinstance(value, tuple) and all(isinstance(item, SourceReference) for item in value)
        else ""
    )
    return json.dumps(
        {"state": cell.state, "value": _canonical(value, name)}, sort_keys=True, default=str
    )


def merge_paths(snapshot: DefinitionSnapshot) -> dict[str, PathValue]:
    """Stable specs/key and allowlisted sections; no identity or decisions are inheritable."""
    content = snapshot.content
    result = {}
    for name in CONTENT_FIELDS:
        path = f"field/{name}"
        if name in content.deleted_fields:
            result[path] = PathValue(state="deleted")
        elif name in content.model_fields_set:
            value = getattr(content, name)
            result[path] = PathValue(state="null" if value is None else "value", value=value)
        else:
            result[path] = PathValue(state="missing")
    for spec in content.specs:
        result[f"specs/{spec.key}"] = PathValue(
            state="unknown" if spec.availability == "unknown" else "value", value=spec
        )
    return result


def _cell(paths: dict[str, PathValue], path: str, base: dict[str, PathValue]) -> PathValue:
    if path in paths:
        return paths[path]
    # specs is complete: removing a previously present key is an explicit deletion.
    return PathValue(state="deleted" if path in base else "missing")


def _validate(request: DerivationRequest) -> dict[str, Any]:
    old, new, child = request.old_parent.ref, request.new_parent.ref, request.child.ref
    if request.pinned_parent != old:
        raise DerivationError(
            "PINNED_VERSION_MISMATCH", "Child must reference the exact old parent"
        )
    if (old.category_id, old.product_id, old.variant_id) != (
        new.category_id,
        new.product_id,
        new.variant_id,
    ):
        raise DerivationError("PARENT_SCOPE_MISMATCH", "Incoming parent belongs to another scope")
    if new.revision <= old.revision or new.definition_id == old.definition_id:
        raise DerivationError(
            "PARENT_VERSION_MISMATCH", "Incoming parent must be a distinct newer revision"
        )
    if child.definition_id in {old.definition_id, new.definition_id}:
        raise DerivationError(
            "CHILD_IDENTITY_MISMATCH", "Child must have its own definition identity"
        )
    overrides = {}
    old_paths, child_paths = merge_paths(request.old_parent), merge_paths(request.child)
    for override in request.overrides:
        if not _valid_path(override.path) or override.path in overrides:
            raise DerivationError(
                "INVALID_OVERRIDE_PATH", "Override paths must be legal and unique"
            )
        if (override.scope.category_id, override.scope.product_id, override.scope.variant_id) != (
            child.category_id,
            child.product_id,
            child.variant_id,
        ):
            raise DerivationError(
                "OVERRIDE_SCOPE_MISMATCH", "Override scope must describe this child"
            )
        cell = _cell(child_paths, override.path, old_paths)
        if cell.state == "missing" or (override.operation == "delete") != (cell.state == "deleted"):
            raise DerivationError(
                "OVERRIDE_VALUE_MISMATCH", "Override must describe the effective child value"
            )
        overrides[override.path] = override
    return overrides


def _changed_fields(old: PathValue, new: PathValue) -> tuple[str, ...]:
    if not isinstance(old.value, SpecSnapshot) or not isinstance(new.value, SpecSnapshot):
        return ("presence",) if _signature(old) != _signature(new) else ()
    before = old.value.model_dump(exclude=SPEC_LOCAL_FIELDS)
    after = new.value.model_dump(exclude=SPEC_LOCAL_FIELDS)
    return tuple(
        name
        for name in sorted(before)
        if _canonical(before[name], name) != _canonical(after[name], name)
    )


def _spec_gaps(path: str, spec: SpecSnapshot, role: str) -> list[Diagnostic]:
    gaps = []
    for condition, code, detail in (
        (spec.availability == "unknown", "unknown_specification", "Target remains unknown"),
        (
            spec.availability == "conflicted",
            "conflicted_specification",
            "Target remains conflicted",
        ),
        (spec.value_type != "text" and spec.unit is None, "missing_unit", "Unit remains absent"),
        (not spec.test_conditions, "missing_test_conditions", "Test conditions remain absent"),
    ):
        if condition:
            gaps.append(Diagnostic(path=path, code=code, detail=f"{role}: {detail}"))
    return gaps


def compare_snapshots(request: DerivationRequest) -> DerivationResult:
    overrides = _validate(request)
    old, new, child = (
        merge_paths(s) for s in (request.old_parent, request.new_parent, request.child)
    )
    differences, missing = [], []
    for path in sorted(old.keys() | new.keys() | child.keys()):
        base = _cell(old, path, {})
        incoming, local = _cell(new, path, old), _cell(child, path, old)
        parent_changed = _signature(base) != _signature(incoming)
        child_changed = _signature(base) != _signature(local)
        classification = _classify(
            _signature(base), _signature(incoming), _signature(local), path in overrides
        )
        if child_changed and path not in overrides:
            missing.append(
                Diagnostic(
                    path=path,
                    code="missing_override",
                    detail="Child difference needs reason, source and scope",
                )
            )
        reconfirmation = []
        changed_fields = _changed_fields(local, incoming)
        if any(
            isinstance(cell.value, SpecSnapshot) and cell.value.availability == "unknown"
            for cell in (incoming, local)
        ):
            reconfirmation.append("unknown_requires_confirmation")
        if path.startswith("specs/") and parent_changed:
            reconfirmation.append("adopted_spec_requires_confirmation")
            reconfirmation.extend(
                f"{name}_changed"
                for name in changed_fields
                if name in {"unit", "test_conditions", "value_type", "availability", "method"}
            )
        for role, cell in (("old_parent", base), ("new_parent", incoming), ("child", local)):
            if cell.state == "missing" and path.startswith("field/"):
                missing.append(Diagnostic(path=path, code="missing_snapshot_field", detail=role))
            if isinstance(cell.value, SpecSnapshot) and role != "old_parent":
                missing.extend(_spec_gaps(path, cell.value, role))
        differences.append(
            Difference(
                path=path,
                old_parent=base,
                new_parent=incoming,
                child=local,
                classification=classification,
                changed_fields=changed_fields,
                reconfirmation=tuple(reconfirmation),
                override=overrides.get(path),
            )
        )
    digest = hashlib.sha256(
        json.dumps(_canonical(request), sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()
    return DerivationResult(
        request_digest=digest,
        old_parent=request.old_parent.ref,
        new_parent=request.new_parent.ref,
        child=request.child.ref,
        differences=tuple(differences),
        missing=tuple(missing),
    )


def _source_union(*groups: tuple[SourceReference, ...]) -> tuple[SourceReference, ...]:
    return tuple(
        sorted(
            set().union(*groups),
            key=lambda ref: (str(ref.artifact_id), ref.expected_revision, ref.line, ref.quote),
        )
    )


def accept_changes(
    request: DerivationRequest,
    selection: AdoptionSelection,
    validation_port: ReuseValidationPort | None = None,
) -> AdoptionCandidate:
    """Prepare only selected changes. Even an allowed port result is not a command receipt."""
    comparison = compare_snapshots(request)
    if selection.request_digest != comparison.request_digest:
        raise DerivationError("STALE_COMPARISON", "Selection does not match the fixed snapshots")
    child_ref = request.child.ref
    if (selection.scope.category_id, selection.scope.product_id, selection.scope.variant_id) != (
        child_ref.category_id,
        child_ref.product_id,
        child_ref.variant_id,
    ):
        raise DerivationError("SELECTION_SCOPE_MISMATCH", "Selection must describe this child")
    if len(set(selection.paths)) != len(selection.paths):
        raise DerivationError("DUPLICATE_SELECTION", "Select each path once")
    if len(set(selection.resolve_conflicts)) != len(selection.resolve_conflicts):
        raise DerivationError("DUPLICATE_RESOLUTION", "Resolve each conflict once")
    by_path = {row.path: row for row in comparison.differences}
    for path in selection.paths:
        if not _valid_path(path) or path not in by_path:
            raise DerivationError(
                "INVALID_SELECTION_PATH", "Selected path must be an inheritable difference"
            )
        row = by_path[path]
        if row.classification not in {"parent_only", "same_change", "conflict"}:
            raise DerivationError("NO_PARENT_CHANGE", "Selected path has no incoming parent change")
        if row.classification == "conflict" and path not in selection.resolve_conflicts:
            raise DerivationError(
                "UNRESOLVED_CONFLICT", "Conflict requires an explicit parent selection"
            )
        if row.new_parent.state == "missing":
            raise DerivationError(
                "INCOMING_VALUE_MISSING", "Missing input cannot be adopted or deleted"
            )
    if any(
        path not in selection.paths or by_path[path].classification != "conflict"
        for path in selection.resolve_conflicts
    ):
        raise DerivationError("INVALID_RESOLUTION", "Resolution must reference a selected conflict")

    data = request.child.content.model_dump(exclude_unset=True)
    specs = {spec.key: spec for spec in request.child.content.specs}
    tombstones = set(request.child.content.deleted_fields)
    overrides = {override.path: override for override in request.overrides}
    traces, missing = [], list(comparison.missing)
    for path in sorted(selection.paths):
        incoming = by_path[path].new_parent
        refs = _source_union(
            selection.sources,
            incoming.value.sources
            if isinstance(incoming.value, SpecSnapshot)
            else request.new_parent.content.sources or (),
        )
        assessment = None
        if validation_port is not None:
            assessment = validation_port.assess(
                ReuseCheck(
                    path=path,
                    old_parent=request.old_parent.ref,
                    new_parent=request.new_parent.ref,
                    child=child_ref,
                    sources=refs,
                    scope=selection.scope,
                )
            )
            if not (
                assessment.audience == "allowed"
                and assessment.cross_customer in {"allowed", "not_required"}
                and assessment.applicability == "applicable"
            ):
                missing.append(
                    Diagnostic(
                        path=path, code="reuse_not_permitted", detail="; ".join(assessment.basis)
                    )
                )
                continue
        else:
            missing.append(
                Diagnostic(
                    path=path,
                    code="authority_pending",
                    detail="Preview only; mainline must check reuse",
                )
            )
        origin_nature = None
        if path.startswith("specs/"):
            key = path.removeprefix("specs/")
            if incoming.state == "deleted":
                specs.pop(key, None)
            else:
                adopted = incoming.value
                assert isinstance(adopted, SpecSnapshot)
                origin_nature = adopted.nature
                payload = adopted.model_dump()
                payload.update(
                    state="needs_confirmation",
                    owner_id=specs[key].owner_id if key in specs else None,
                    nature="extracted" if adopted.nature == "decided" else adopted.nature,
                )
                specs[key] = SpecSnapshot.model_validate(payload)
        else:
            name = path.removeprefix("field/")
            if incoming.state == "deleted":
                data.pop(name, None)
                tombstones.add(name)
            else:
                data[name] = incoming.value
                tombstones.discard(name)
        traces.append(
            AdoptionTrace(
                path=path,
                source_parent=request.new_parent.ref,
                reason=selection.reason,
                sources=refs,
                scope=selection.scope,
                origin_nature=origin_nature,
                assessment=assessment,
            )
        )
        overrides[path] = Override(
            path=path,
            operation="delete" if incoming.state == "deleted" else "set",
            reason=selection.reason,
            sources=selection.sources,
            scope=selection.scope,
        )
    data["specs"] = tuple(specs[key] for key in sorted(specs))
    sources_selected = any(trace.path == "field/sources" for trace in traces)
    if traces and not sources_selected:
        # Retained local specs must not lose their exact references during source adoption.
        data["sources"] = _source_union(
            request.child.content.sources or (),
            selection.sources,
            *(spec.sources for spec in specs.values()),
        )
        tombstones.discard("sources")
    data["deleted_fields"] = tuple(sorted(tombstones))
    content = DefinitionContent.model_validate(data)
    adopted_paths = {trace.path for trace in traces}
    missing = [
        gap for gap in missing if gap.code != "missing_override" or gap.path not in adopted_paths
    ]
    available_sources = set(content.sources or ())
    for spec in content.specs:
        if not set(spec.sources) <= available_sources:
            missing.append(
                Diagnostic(
                    path=f"specs/{spec.key}",
                    code="missing_definition_source",
                    detail="Retained specification references must remain in definition sources",
                )
            )
    if not available_sources:
        missing.append(
            Diagnostic(
                path="field/sources",
                code="missing_definition_source",
                detail="Candidate has no definition sources; current draft schema requires them",
            )
        )
    return AdoptionCandidate(
        request_digest=comparison.request_digest,
        based_on_child=child_ref,
        pinned_parent=request.pinned_parent,
        offered_parent=request.new_parent.ref,
        content=content,
        traces=tuple(traces),
        missing=tuple(missing),
        overrides=tuple(overrides[path] for path in sorted(overrides)),
    )


def snapshot_from_definition(view: dict, *, variant_id=None) -> DefinitionSnapshot:
    """Adapt a current authorized Definition view, ignoring UI/history/authority adornments."""
    data = {name: view[name] for name in CONTENT_FIELDS if name in view}

    def reference(raw):
        return {name: raw[name] for name in ("artifact_id", "expected_revision", "line", "quote")}

    if data.get("sources") is not None:
        data["sources"] = [reference(ref) for ref in data["sources"]]
    data["specs"] = [
        {**spec, "sources": [reference(ref) for ref in spec["sources"]]} for spec in view["specs"]
    ]
    return DefinitionSnapshot.model_validate(
        {
            "ref": {
                "definition_id": view["id"],
                "revision": view["revision"],
                "category_id": view["category_id"],
                "product_id": view["product_id"],
                "variant_id": variant_id,
            },
            "content": data,
            "title": view["title"],
            "status": view["status"],
            "owner_id": view.get("owner_id"),
        }
    )


FIELDS = ("title", "purpose", "use_cases", "requirements", "constraints", "unknowns", "exclusions")


def _references(values):
    result = {}
    for value in values:
        ref = DefinitionReference.model_validate(
            {
                key: value[key]
                for key in (
                    "artifact_id",
                    "expected_revision",
                    "line",
                    "quote",
                )
            }
        ).model_dump(mode="json")
        result[(ref["artifact_id"], ref["expected_revision"], ref["line"], ref["quote"])] = ref
    return [result[key] for key in sorted(result)]


def _spec(value):
    result = deepcopy(value)
    result.pop("owner_id", None)
    result.pop("state", None)
    result["sources"] = _references(result.get("sources", []))
    for key in ("value", "lower", "upper", "tolerance"):
        if result.get(key) is not None:
            with localcontext() as decimal_context:
                decimal_context.prec = 50
                result[key] = str(Decimal(str(result[key])).normalize())
    return result


def paths(content):
    return {
        **{name: deepcopy(content.get(name)) for name in FIELDS},
        **{f"specs/{item['key']}": _spec(item) for item in content.get("specs", [])},
    }


def three_way(old_parent, new_parent, current_child):
    old, incoming, child = (paths(content) for content in (old_parent, new_parent, current_child))
    changes = []
    for path in sorted(old.keys() | incoming.keys() | child.keys()):
        before, new, current = old.get(path), incoming.get(path), child.get(path)
        if before == new == current:
            continue
        category = _classify(_canonical(before), _canonical(new), _canonical(current))
        if category == "unchanged":
            continue
        changes.append(
            {
                "path": path,
                "old_parent": deepcopy(before),
                "new_parent": deepcopy(new),
                "current_child": deepcopy(current),
                "category": category,
            }
        )
    return changes


def merge_content(old_parent, new_parent, current_child, choices, *, require_choices=True):
    changes = three_way(old_parent, new_parent, current_child)
    decisions = {choice.path: choice.selection for choice in choices}
    if decisions.keys() - {change["path"] for change in changes}:
        raise DomainError("VERSION_CONFLICT", "选择不对应当前三方差异，请重新比较。")
    result = deepcopy(new_parent)
    merged = paths(current_child)
    for change in changes:
        selection = decisions.get(change["path"])
        if change["category"] == "conflict" and selection is None and require_choices:
            raise DomainError(
                "CONFIRMATION_REQUIRED", "每个冲突须明确选择父版或当前子版并说明原因。"
            )
        if selection is None:
            selection = (
                "parent" if change["category"] in {"parent_only", "same_change"} else "child"
            )
        merged[change["path"]] = deepcopy(
            change["new_parent"] if selection == "parent" else change["current_child"]
        )
    for field in FIELDS:
        result[field] = merged[field]
    result["specs"] = [
        value
        for key, value in sorted(merged.items())
        if key.startswith("specs/") and value is not None
    ]
    return result


def effective_definition(parent, overrides, sources, visibility, reason):
    result = {name: deepcopy(parent[name]) for name in FIELDS}
    result["specs"] = [_spec(spec) for spec in parent.get("specs", [])]
    result.update(deepcopy(overrides))
    for spec in result["specs"]:
        spec["owner_id"] = None
        spec["state"] = "needs_confirmation"
    result.update(
        parent_definition_id=parent["id"],
        expected_parent_revision=parent["revision"],
        visibility=visibility,
        change_reason=reason,
        sources=_references(
            [
                *parent["sources"],
                *sources,
                *[ref for spec in result["specs"] for ref in spec["sources"]],
            ]
        ),
    )
    return DefinitionDraftPayload.model_validate(result)


def semantic(payload):
    result = payload.model_dump(mode="json", exclude={"confirmation_token"})
    result["sources"] = _references(result["sources"])
    if isinstance(payload, VariantDerivePayload):
        result["overrides"] = payload.overrides.model_dump(mode="json", exclude_unset=True)
        if "specs" in result["overrides"]:
            result["overrides"]["specs"] = sorted(
                [_spec(spec) for spec in result["overrides"]["specs"]],
                key=lambda spec: spec["key"],
            )
    else:
        result["choices"] = sorted(result["choices"], key=lambda choice: choice["path"])
    return result


def _parent(s, ctx, product_id, parent_id, revision=None):
    parent = s.scalar(
        select(DefinitionRevision).where(
            DefinitionRevision.tenant_id == ctx.tenant_id,
            DefinitionRevision.product_id == product_id,
            DefinitionRevision.id == parent_id,
        )
    )
    if not parent:
        raise DomainError("FORBIDDEN_SCOPE", "固定父定义不在当前型号授权范围。", 403)
    if revision is not None and parent.revision != revision:
        raise DomainError("VERSION_CONFLICT", "固定父定义版本不匹配。")
    return definition_view(s, ctx, parent)


def _variant_revision(s, ctx, product_id, variant_id, expected=None):
    query = select(Variant).where(
        Variant.tenant_id == ctx.tenant_id,
        Variant.product_id == product_id,
        Variant.id == variant_id,
    )
    variant = s.scalar(query)
    if not variant:
        raise DomainError("FORBIDDEN_SCOPE", "派生不在当前型号授权范围。", 403)
    revisions = select(VariantRevision).where(
        VariantRevision.tenant_id == ctx.tenant_id,
        VariantRevision.product_id == product_id,
        VariantRevision.variant_id == variant.id,
    )
    if expected is not None:
        revisions = revisions.where(VariantRevision.revision == expected)
    current = s.scalar(revisions.order_by(VariantRevision.revision.desc()).limit(1))
    if not current:
        raise DomainError("VERSION_CONFLICT", "所选派生版本不存在。")
    return variant, current


def _assemble(s, ctx, command, product, payload):
    parent = _parent(
        s, ctx, product.id, payload.parent_definition_id, payload.expected_parent_revision
    )
    if isinstance(payload, VariantDerivePayload):
        visibility = payload.visibility
        overrides = semantic(payload)["overrides"]
        current = None
    else:
        _, current = _variant_revision(
            s, ctx, product.id, payload.variant_id, payload.expected_variant_revision
        )
        visibility = current.visibility
        old = _parent(s, ctx, product.id, current.parent_definition_id, current.parent_revision)
        if parent["revision"] <= old["revision"]:
            raise DomainError("VERSION_CONFLICT", "重核父版须选择较新的真实定义版本。")
        merged = merge_content(old, parent, current.effective_definition, payload.choices)
        overrides = {field: merged[field] for field in FIELDS}
        overrides["specs"] = merged["specs"]
    if parent["visibility"] != "category" and visibility == "category":
        raise DomainError("FORBIDDEN_SCOPE", "私人父版不能扩大为品类共享派生。", 403)
    sources = [source.model_dump(mode="json") for source in payload.sources]
    if current:
        sources += current.effective_definition["sources"]
    effective = effective_definition(parent, overrides, sources, visibility, payload.reason)
    validate_definition(s, ctx, command, product, effective)
    return parent, current, effective


def validate(s, ctx, command, product, payload):
    from pdos_next.service import require_access

    require_access(s, ctx, product.id, write=True, lock=True)
    actor = s.get(Principal, ctx.actor_id)
    if (
        ctx.run_id is not None
        or ctx.actor_id != ctx.requester_id
        or not actor
        or actor.kind != "human"
    ):
        raise DomainError("NAMED_DECISION_REQUIRED", "派生当前仅支持本人一次确认。", 403)
    _assemble(s, ctx, command, product, payload)


def _sparse(parent, effective):
    old, new = paths(parent), paths(effective)
    result = {field: deepcopy(new[field]) for field in FIELDS if old[field] != new[field]}
    if {key: value for key, value in old.items() if key.startswith("specs/")} != {
        key: value for key, value in new.items() if key.startswith("specs/")
    }:
        result["specs"] = [_spec(spec) for spec in effective["specs"]]
    return result


def apply(s, ctx, command, product, payload):
    validate(s, ctx, command, product, payload)
    parent, original, effective = _assemble(s, ctx, command, product, payload)
    latest_parent = s.scalar(
        select(DefinitionRevision)
        .where(
            DefinitionRevision.tenant_id == ctx.tenant_id,
            DefinitionRevision.product_id == product.id,
        )
        .order_by(DefinitionRevision.revision.desc())
        .limit(1)
    )
    if not latest_parent or latest_parent.id != payload.parent_definition_id:
        raise DomainError("VERSION_CONFLICT", "确认后父定义已有新版本，请重新比较并确认。")
    if isinstance(payload, VariantDerivePayload):
        variant = Variant(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            product_id=product.id,
            owner_id=ctx.requester_id,
            name=payload.name,
            kind=payload.kind,
            visibility=payload.visibility,
            status="draft",
        )
        s.add(variant)
        s.flush()
        revision, previous, applicability, choices = 1, None, payload.applicability, []
    else:
        # The command transaction holds the Product lock; immutable rows stay SELECT/INSERT only.
        variant, latest = _variant_revision(s, ctx, product.id, payload.variant_id)
        if latest.id != original.id:
            raise DomainError("VERSION_CONFLICT", "确认后派生已有新版本，请重新比较。")
        revision, previous = latest.revision + 1, latest.id
        applicability, choices = (
            latest.applicability,
            [choice.model_dump(mode="json") for choice in payload.choices],
        )
    value = effective.model_dump(mode="json")
    subject = VariantRevision(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        product_id=product.id,
        variant_id=variant.id,
        owner_id=ctx.requester_id,
        parent_definition_id=payload.parent_definition_id,
        parent_revision=payload.expected_parent_revision,
        previous_revision_id=previous,
        revision=revision,
        status="draft",
        visibility=effective.visibility,
        effective_definition=value,
        overrides=_sparse(parent, value),
        applicability=applicability,
        sources=[source.model_dump(mode="json") for source in payload.sources],
        choices=choices,
        reason=payload.reason,
    )
    s.add(subject)
    s.flush()
    return subject, "variant_revision", subject.visibility


def preview_view(s, ctx, command, product, payload):
    validate(s, ctx, command, product, payload)
    parent, current, effective = _assemble(s, ctx, command, product, payload)
    if current:
        old = _parent(s, ctx, product.id, current.parent_definition_id, current.parent_revision)
        changes = three_way(old, parent, current.effective_definition)
        before = current.effective_definition
        applicability = current.applicability
    else:
        changes, before, applicability = [], None, payload.applicability
    return {
        "operation": command.operation,
        "parent_definition_id": parent["id"],
        "parent_revision": parent["revision"],
        "variant_revision": current.revision if current else None,
        "visibility": effective.visibility,
        "applicability": applicability,
        "before": before,
        "after": effective.model_dump(mode="json"),
        "changes": changes,
        "reason": payload.reason,
        "effect": "创建一个不可变派生草稿版本，固定父定义与当前选择；不修改父版、不发布。",
    }


def compare_variant(s, ctx, product_id, variant_id, parent_definition_id):
    from pdos_next.service import require_access, source_for

    require_access(s, ctx, product_id)
    variant, current = _variant_revision(s, ctx, product_id, variant_id)
    old = _parent(s, ctx, product_id, current.parent_definition_id, current.parent_revision)
    new = _parent(s, ctx, product_id, parent_definition_id)
    refs = _references([*old["sources"], *new["sources"], *current.effective_definition["sources"]])
    for ref in refs:
        source_for(s, ctx, product_id, UUID(ref["artifact_id"]), ref["expected_revision"])
    changes = three_way(old, new, current.effective_definition)
    return {
        "variant_id": str(variant.id),
        "name": variant.name,
        "variant_revision": current.revision,
        "old_parent_id": old["id"],
        "old_parent_revision": old["revision"],
        "new_parent_id": new["id"],
        "new_parent_revision": new["revision"],
        "changes": changes,
        "conflict_count": sum(change["category"] == "conflict" for change in changes),
        "sources": refs,
        "required_source_read_set": [
            {"artifact_id": key, "expected_revision": value}
            for key, value in sorted(
                {ref["artifact_id"]: ref["expected_revision"] for ref in refs}.items()
            )
        ],
    }


def revision_view(s, ctx, row):
    from pdos_next.models import Artifact
    from pdos_next.original_security import source_status

    value = row.effective_definition
    current = True
    for ref in value["sources"]:
        source = s.get(Artifact, UUID(ref["artifact_id"]))
        if not source or source.tenant_id != ctx.tenant_id:
            raise DomainError("SOURCE_UNAVAILABLE", "派生来源权限待重核，正文已隐藏。", 403)
        current = (
            current
            and source_status(s, source) == "active"
            and source.revision == ref["expected_revision"]
        )
    return {
        "id": str(row.id),
        "revision": row.revision,
        "status": row.status,
        "parent_definition_id": str(row.parent_definition_id),
        "parent_revision": row.parent_revision,
        "previous_revision_id": str(row.previous_revision_id) if row.previous_revision_id else None,
        "visibility": row.visibility,
        "owner_id": str(row.owner_id),
        "effective_definition": value,
        "overrides": row.overrides,
        "applicability": row.applicability,
        "sources": row.sources,
        "choices": row.choices,
        "reason": row.reason,
        "created_at": row.created_at.isoformat(),
        "source_status": "current" if current else "needs_recheck",
    }


def list_variants(s, ctx, product_id):
    from pdos_next.service import require_access

    require_access(s, ctx, product_id)
    rows = s.scalars(
        select(Variant)
        .where(
            Variant.tenant_id == ctx.tenant_id,
            Variant.product_id == product_id,
        )
        .order_by(Variant.created_at.desc())
        .limit(101)
    ).all()
    items, unavailable = [], 0
    for variant in rows[:100]:
        revisions = []
        for row in s.scalars(
            select(VariantRevision)
            .where(
                VariantRevision.tenant_id == ctx.tenant_id,
                VariantRevision.variant_id == variant.id,
            )
            .order_by(VariantRevision.revision.desc())
            .limit(100)
        ):
            try:
                revisions.append(revision_view(s, ctx, row))
            except DomainError as error:
                if error.code != "SOURCE_UNAVAILABLE":
                    raise
                unavailable += 1
        if revisions:
            items.append(
                {
                    "id": str(variant.id),
                    "name": variant.name,
                    "kind": variant.kind,
                    "visibility": variant.visibility,
                    "owner_id": str(variant.owner_id),
                    "revisions": revisions,
                }
            )
    return {"items": items, "has_more": len(rows) > 100, "unavailable_count": unavailable}
