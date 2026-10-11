"""Human continuation of an actual, fully readable definition revision.

The client pins only a parent and a reason. Current item contents and provenance
are copied by the server; neither historical item versions nor G0/publishing
credentials become credentials for the new draft.
"""

from copy import deepcopy
from dataclasses import dataclass

from sqlalchemy import select

from pdos_next.domain.preproject.access import fail, human
from pdos_next.domain.preproject.baseline import validate_sources
from pdos_next.service import require_access

from .models import DefinitionRevision, DefinitionSource, DefinitionSpecCurrent, DefinitionSpecRow

_HEADER_CONTENT = (
    "title",
    "purpose",
    "visibility",
    "variant_id",
    "use_cases",
    "requirements",
    "constraints",
    "unknowns",
    "exclusions",
)
_NEW_ITEM_FIELDS = {
    "id",
    "tenant_id",
    "category_id",
    "product_id",
    "definition_id",
    "created_at",
    "item_id",
    "item_version",
    "removed",
    "receipt_id",
}
_NEW_SOURCE_FIELDS = {
    "id",
    "tenant_id",
    "category_id",
    "product_id",
    "definition_id",
    "created_at",
}


@dataclass(frozen=True)
class InheritedDefinition:
    parent: DefinitionRevision
    specs: tuple[DefinitionSpecRow, ...]
    sources: tuple[DefinitionSource, ...]


def semantic(payload):
    return payload.model_dump(
        mode="json",
        include={
            "mode",
            "parent_definition_id",
            "expected_parent_revision",
            "change_reason",
        },
    )


def validate(s, ctx, command, product, payload):
    """Resolve and authorize every fixed source before copying any business row."""
    from .definitions import definition_view

    human(s, ctx)
    require_access(s, ctx, product.id, write=True, lock=True)
    if (
        payload.mode != "inherit_parent"
        or command.product_id != product.id
        or product.tenant_id != ctx.tenant_id
        or product.category_id != ctx.category_id
    ):
        fail("FORBIDDEN_SCOPE", "definition_scope_mismatch", "定义不在当前型号范围。", 403)
    if command.expected_revision != product.revision:
        fail("VERSION_CONFLICT", "product_version_moved", "型号范围已变化，请重新读取。")
    parent = s.scalar(
        select(DefinitionRevision)
        .where(
            DefinitionRevision.id == payload.parent_definition_id,
            DefinitionRevision.tenant_id == ctx.tenant_id,
            DefinitionRevision.category_id == ctx.category_id,
            DefinitionRevision.product_id == product.id,
        )
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if parent is None:
        fail("FORBIDDEN_SCOPE", "parent_not_readable", "父定义不在当前可读型号范围。", 403)
    if parent.revision != payload.expected_parent_revision:
        fail("VERSION_CONFLICT", "parent_version_moved", "父定义版本与所选固定版本不一致。")
    newer = s.scalar(
        select(DefinitionRevision.id)
        .where(
            DefinitionRevision.tenant_id == ctx.tenant_id,
            DefinitionRevision.category_id == ctx.category_id,
            DefinitionRevision.product_id == product.id,
            DefinitionRevision.variant_id == parent.variant_id,
            DefinitionRevision.revision > parent.revision,
        )
        .limit(1)
    )
    if newer:
        fail("VERSION_CONFLICT", "definition_not_current", "已有后续定义版本，请读取当前版本。")

    # This traverses typed references, nested knowledge, fixed parents and actual
    # source visibility/status. Reading the definition header alone is insufficient.
    validate_sources(s, ctx, definition_view(s, ctx, parent))
    specs = tuple(
        s.scalars(
            select(DefinitionSpecRow)
            .join(
                DefinitionSpecCurrent, DefinitionSpecCurrent.current_row_id == DefinitionSpecRow.id
            )
            .where(
                DefinitionSpecCurrent.tenant_id == ctx.tenant_id,
                DefinitionSpecCurrent.category_id == ctx.category_id,
                DefinitionSpecCurrent.product_id == product.id,
                DefinitionSpecCurrent.definition_id == parent.id,
                DefinitionSpecCurrent.removed.is_(False),
                DefinitionSpecRow.tenant_id == ctx.tenant_id,
                DefinitionSpecRow.definition_id == parent.id,
            )
            .order_by(DefinitionSpecCurrent.key)
            .execution_options(populate_existing=True)
        )
    )
    sources = tuple(
        s.scalars(
            select(DefinitionSource)
            .where(
                DefinitionSource.tenant_id == ctx.tenant_id,
                DefinitionSource.category_id == ctx.category_id,
                DefinitionSource.product_id == product.id,
                DefinitionSource.definition_id == parent.id,
            )
            .order_by(DefinitionSource.id)
        )
    )
    return InheritedDefinition(parent, specs, sources)


def apply_draft(s, ctx, command, product, payload):
    from .definitions import create_revision

    inherited = validate(s, ctx, command, product, payload)
    parent = inherited.parent
    fields = {name: deepcopy(getattr(parent, name)) for name in _HEADER_CONTENT}
    fields.update(parent_definition_id=parent.id, change_reason=payload.change_reason)
    subject = create_revision(
        s,
        ctx,
        product,
        owner_id=ctx.requester_id,
        revision=parent.revision + 1,
        fields=fields,
        specs=[
            {
                column.name: deepcopy(getattr(row, column.name))
                for column in DefinitionSpecRow.__table__.columns
                if column.name not in _NEW_ITEM_FIELDS
            }
            for row in inherited.specs
        ],
        sources=[
            {
                column.name: deepcopy(getattr(row, column.name))
                for column in DefinitionSource.__table__.columns
                if column.name not in _NEW_SOURCE_FIELDS
            }
            for row in inherited.sources
        ],
    )
    subject.action_result = {
        "inherited_from": str(parent.id),
        "item_copies": [
            {"row_id": str(new.id), "parent_row_id": str(old.id)}
            for old, new in zip(inherited.specs, subject.created_specs, strict=True)
        ],
    }
    return subject, "definition_revision", subject.visibility


def finalize_draft_receipt(s, ctx, command, product, payload, subject, receipt):
    """Bind copied atoms to this creation receipt, never their parent's receipt."""
    for row in subject.created_specs:
        row.receipt_id = receipt.id
    s.flush(subject.created_specs)
