"""T1 ``product.definition.update``: edit the header as a new draft revision (P100, D311).

A named person reads one fixed, current, base-model revision and confirms once.
The server writes the next draft revision with the new header and copies the
parent's current items and sources exactly as ``inherit_parent`` does, so the
read revision, its items and anything consuming it stay unchanged. A published
(spec-frozen) revision is never edited here: changes after the freeze go through
a change order. Variant definitions keep their own derive/rebase path.
"""

from copy import deepcopy
from dataclasses import dataclass

from pdos_next.domain.categories.preproject.access import fail
from pdos_next.schemas.products.definition_update import HEADER

from . import definition_inherit as inherit
from .models import DefinitionSource, DefinitionSpecRow

OPERATION = "product.definition.update"
EFFECT = (
    "生成新的草稿版本，写入新的整体字段，并原样带入当前条目与来源；"
    "所读版本、其条目和已使用它的对象都不变。条目级修改仍用条目编辑；规格冻结后的修改须走变更单。"
)


@dataclass(frozen=True)
class Validated:
    inherited: inherit.InheritedDefinition
    fields: dict
    changes: list


category_lifecycle_fence = True


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"confirmation_token"})


def _as_inherit(payload):
    from pdos_next.schemas.products.definitions import DefinitionDraftPayload

    return DefinitionDraftPayload(
        mode="inherit_parent",
        parent_definition_id=payload.definition_id,
        expected_parent_revision=payload.expected_definition_revision,
        change_reason=payload.change_reason,
    )


def validate(s, ctx, command, product, payload):
    inherited = inherit.validate(s, ctx, command, product, _as_inherit(payload))
    parent = inherited.parent
    if parent.variant_id is not None:
        fail(
            "VALIDATION_FAILED",
            "definition_variant_update",
            "派生型号的定义按派生与重新基准办理，不在此修改整体字段。",
        )
    if parent.status == "published" or parent.publication_receipt_id is not None:
        fail(
            "VALIDATION_FAILED",
            "definition_frozen",
            "规格已冻结，冻结后的修改须走变更单。",
        )
    after = payload.header()
    changes = [
        {"path": name, "before": deepcopy(getattr(parent, name)), "after": deepcopy(after[name])}
        for name in HEADER
        if getattr(parent, name) != after[name]
    ]
    if not changes:
        fail("VALIDATION_FAILED", "definition_unchanged", "整体字段没有变化，无需生成新版本。")
    fields = {name: deepcopy(getattr(parent, name)) for name in inherit._HEADER_CONTENT}
    fields.update(after)
    fields.update(parent_definition_id=parent.id, change_reason=payload.change_reason)
    return Validated(inherited, fields, changes)


def confirmation_subject(s, ctx, command, product, payload):
    value = validate(s, ctx, command, product, payload)
    return "definition_revision", value.inherited.parent


def preview_view(s, ctx, command, product, payload):
    value = validate(s, ctx, command, product, payload)
    parent = value.inherited.parent
    return {
        "operation": OPERATION,
        "definition": {"id": str(parent.id), "revision": parent.revision, "sealed": parent.sealed},
        "new_revision": parent.revision + 1,
        "changes": value.changes,
        "change_reason": payload.change_reason,
        "copied_items": len(value.inherited.specs),
        "copied_sources": len(value.inherited.sources),
        "effect": EFFECT,
    }


def apply_validated(s, ctx, command, product, payload, value):
    from .definitions import create_revision

    parent = value.inherited.parent
    subject = create_revision(
        s,
        ctx,
        product,
        owner_id=ctx.requester_id,
        revision=parent.revision + 1,
        fields=value.fields,
        specs=[
            {
                column.name: deepcopy(getattr(row, column.name))
                for column in DefinitionSpecRow.__table__.columns
                if column.name not in inherit._NEW_ITEM_FIELDS
            }
            for row in value.inherited.specs
        ],
        sources=[
            {
                column.name: deepcopy(getattr(row, column.name))
                for column in DefinitionSource.__table__.columns
                if column.name not in inherit._NEW_SOURCE_FIELDS
            }
            for row in value.inherited.sources
        ],
    )
    subject.action_result = {
        "updated_from": str(parent.id),
        "changes": [change["path"] for change in value.changes],
        "item_copies": [
            {"row_id": str(new.id), "parent_row_id": str(old.id)}
            for old, new in zip(value.inherited.specs, subject.created_specs, strict=True)
        ],
    }
    return subject, "definition_revision", subject.visibility


def finalize_receipt(s, ctx, command, product, payload, subject, receipt):
    """Bind copied items to this update receipt, never their parent's receipt."""
    for row in subject.created_specs:
        row.receipt_id = receipt.id
    s.flush(subject.created_specs)
