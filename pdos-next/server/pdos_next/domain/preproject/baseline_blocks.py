"""Definition-bound baseline blocks, using ordinary configuration read guards."""

from uuid import UUID

from sqlalchemy import select

from pdos_next.domain.configurations import service as configurations
from pdos_next.domain.configurations.models import BomRevision, EngineeringConfiguration
from pdos_next.domain.products.models import DefinitionRevision
from pdos_next.errors import DomainError


def _unknown(reason):
    return {"status": "unknown", "items": [], "reason": reason}


def read_blocks(s, ctx, definition):
    """Read every visible fixed configuration for an already-authorized definition view.

    The caller owns definition source-closure verification. This reader independently
    checks its identity/scope and each configuration/BOM/part source guard. It neither
    picks the newest BOM nor assumes one configuration is the authoritative choice.
    No human-only mutation guard is applied to these ordinary read operations.
    """
    result = {
        "bom": _unknown("definition_binding_unavailable"),
        "certification": _unknown("baseline_block_not_available"),
        "tooling": _unknown("baseline_block_not_available"),
    }
    if definition is None:
        return result
    product_id = UUID(str(definition["product_id"]))
    definition_id = UUID(str(definition["id"]))
    revision = definition["revision"]
    actual = configurations._row(s, ctx, product_id, DefinitionRevision, definition_id)
    if actual.category_id != ctx.category_id or actual.revision != revision:
        raise DomainError("VERSION_CONFLICT", "基线定义固定版本不一致。")
    rows = s.scalars(
        select(EngineeringConfiguration)
        .where(
            EngineeringConfiguration.tenant_id == ctx.tenant_id,
            EngineeringConfiguration.product_id == product_id,
            EngineeringConfiguration.definition_id == definition_id,
            EngineeringConfiguration.definition_revision == revision,
        )
        .order_by(
            EngineeringConfiguration.series_id,
            EngineeringConfiguration.revision,
            EngineeringConfiguration.id,
        )
    )
    items, unavailable = [], 0
    for row in rows:
        try:
            if (
                row.tenant_id != ctx.tenant_id
                or row.product_id != product_id
                or row.definition_id != definition_id
                or row.definition_revision != revision
            ):
                raise DomainError("FORBIDDEN_SCOPE", "工程配置不在所选定义范围。", 403)
            cache = {}
            configuration = configurations._base_view(s, ctx, product_id, row, cache)
            bom = configurations._row(s, ctx, product_id, BomRevision, row.bom_id)
            if bom.revision != row.bom_revision:
                raise DomainError("VERSION_CONFLICT", "工程配置固定 BOM 版本不一致。")
            value = configurations._bom_view(s, ctx, product_id, bom, cache)
            items.append(
                {
                    "configuration": configuration,
                    "definition_id": str(definition_id),
                    "definition_revision": revision,
                    "bom_id": str(row.bom_id),
                    "bom_revision": row.bom_revision,
                    "bom": value,
                    "source_status": "current"
                    if configuration["source_status"] == "current"
                    and value["source_status"] == "current"
                    else "needs_recheck",
                }
            )
        except DomainError as error:
            if error.code not in {
                "FORBIDDEN_SCOPE",
                "SOURCE_UNAVAILABLE",
                "SOURCE_STALE",
                "VERSION_CONFLICT",
                "NOT_FOUND",
            }:
                raise
            unavailable += 1
    if items:
        result["bom"] = {
            "status": "available",
            "items": items,
            "source_status": "current"
            if all(item["source_status"] == "current" for item in items)
            else "needs_recheck",
        }
    if unavailable:
        result["bom"]["unavailable_configuration_count"] = unavailable
    return result
