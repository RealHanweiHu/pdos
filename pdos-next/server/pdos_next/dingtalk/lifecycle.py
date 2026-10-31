"""Private immutable retention identities from the actual checked native answer.

This is not an authority proof, an audience cache, a physical-table mapping or a
client schema. The shared assistant_source_lifecycle_links resolver belongs to F.
"""

from collections import defaultdict
from uuid import UUID

from pydantic import Field, ValidationError

from pdos_next.enterprise_search.schemas import SourceType
from pdos_next.errors import DomainError
from pdos_next.schema_base import StrictModel


class FixedDependency(StrictModel):
    source_type: SourceType
    source_id: UUID
    source_revision: int = Field(gt=0, strict=True)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    category_id: UUID


def capture(answer):
    """Only ChannelService's actual owner-ledger/current READ result enters here."""
    if answer.withheld_reason:
        return []
    if not answer.footprint:
        raise DomainError("SOURCE_UNAVAILABLE", "外部事实副本缺少完整固定来源依赖。")
    values = {}
    try:
        for item in answer.footprint.values():
            value = FixedDependency.model_validate(
                {key: item[key] for key in FixedDependency.model_fields}
            ).model_dump(mode="json")
            key = tuple(value[name] for name in FixedDependency.model_fields)
            values[key] = value
    except (ValidationError, KeyError, TypeError):
        raise DomainError("SOURCE_UNAVAILABLE", "外部事实副本的固定来源依赖不完整。") from None
    return [values[key] for key in sorted(values)]


def grouped(dependencies):
    """Root calls its shared resolver once per REAL category, never c=NULL."""
    result = defaultdict(list)
    for raw in dependencies:
        value = FixedDependency.model_validate(raw).model_dump(mode="json")
        result[value["category_id"]].append(value)
    return dict(sorted(result.items()))
