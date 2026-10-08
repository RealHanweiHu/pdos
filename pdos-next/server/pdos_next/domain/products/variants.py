from copy import deepcopy
from decimal import Decimal, localcontext
from uuid import UUID, uuid4

from sqlalchemy import select

from pdos_next.errors import DomainError
from pdos_next.models import Principal
from pdos_next.schemas.products.definitions import DefinitionDraftPayload, DefinitionReference
from pdos_next.schemas.products.variants import VariantDerivePayload

from .definitions import definition_view
from .definitions import validate as validate_definition
from .models import DefinitionRevision
from .variant_models import Variant, VariantRevision

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
        category = (
            "child_only"
            if before == new
            else "parent_only"
            if before == current
            else "same_change"
            if new == current
            else "conflict"
        )
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
    if not parent or (parent.visibility == "private" and parent.owner_id != ctx.requester_id):
        raise DomainError("FORBIDDEN_SCOPE", "固定父定义不在当前产品授权范围。", 403)
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
    if not variant or (variant.visibility == "private" and variant.owner_id != ctx.requester_id):
        raise DomainError("FORBIDDEN_SCOPE", "派生不在当前产品授权范围。", 403)
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
    if parent["visibility"] == "private" and visibility != "private":
        raise DomainError("FORBIDDEN_SCOPE", "私人父版不能扩大为产品共享派生。", 403)
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
            (DefinitionRevision.visibility == "product")
            | (DefinitionRevision.owner_id == ctx.requester_id),
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
        if (
            not source
            or source.tenant_id != ctx.tenant_id
            or (source.visibility == "private" and source.owner_id != ctx.requester_id)
        ):
            raise DomainError("SOURCE_UNAVAILABLE", "派生来源权限待重核，正文已隐藏。", 403)
        current = (
            current and source_status(s, source) == "active"
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
            (Variant.visibility == "product") | (Variant.owner_id == ctx.requester_id),
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
