"""Pure exact relations from an already guarded immutable operational Fact.

This module performs no owner/Source IO. Its output is not a permission or a
qualification. Only owner.inspect_resource may issue the same-UOW sealed read.
"""

from pdos_next.domain.build_operational_facts.service import _source
from pdos_next.errors import DomainError

from .schemas import ResourceProjection, ResourceRelation


def project(fact, data, request, *, current):
    requirements = [
        (index, value)
        for index, value in enumerate(data.requirements)
        if value.operation_key == request.operation_key
    ]
    if len(requirements) != 1:
        return (), (), ("OPERATION_RESOURCE_RELATION_UNKNOWN",)
    index, requirement = requirements[0]
    by_id = {value.resource.id: value for value in data.resources}
    resources, relations, gaps = [], [], []
    for use_index, use in enumerate(requirement.uses):
        if request.resource is not None and use.resource != request.resource:
            continue
        value = by_id.get(use.resource.id)
        if value is None:
            gaps.append("RESOURCE_DECLARATION_UNKNOWN")
            continue
        if value.resource != use.resource:
            raise DomainError("RESOURCE_VERSION_CONFLICT", "固定资源身份与版本不能一致核对。")
        if (
            request.execution.purpose not in value.purposes
            or request.operation_key not in value.operation_ids
        ):
            gaps.append("RESOURCE_APPLICABILITY_UNKNOWN")
            continue
        resources.append(
            ResourceProjection(
                resource=value.resource,
                lifecycle=value.lifecycle,
                current=current and value.lifecycle == "active",
                originals=value.sources,
            )
        )
        if current and value.lifecycle == "active":
            relations.append(
                ResourceRelation(
                    build=request.build,
                    process=request.process,
                    operation_key=request.operation_key,
                    resource=use.resource,
                    units=use.units,
                    relation_source=_source(fact, f"requirements[{index}].uses[{use_index}]"),
                    relation_originals=requirement.sources,
                )
            )
        else:
            gaps.append("RESOURCE_CURRENT_APPLICABILITY_UNKNOWN")
    if not resources:
        gaps.append("RESOURCE_RELATION_UNKNOWN")
    return tuple(resources), tuple(relations), tuple(sorted(set(gaps)))
