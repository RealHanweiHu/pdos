"""Explicit read selection, without tenant, authority or decision assertions."""

from uuid import UUID

from pdos_next.domain.build_operational_facts.schemas import DTO, OperationalScope, Revision
from pdos_next.domain.manufacturing_resource_owner.schemas import Key, VersionRef
from pdos_next.schemas.resource_readiness.contracts import ResourceRef


class ResourceInspectInput(DTO):
    # A fixed expectation only: the concrete owner verifies the actual Build's
    # Project and ACL. This field neither creates nor selects a different root.
    project_id: UUID
    expected_build_revision: Revision
    process: VersionRef
    execution: OperationalScope
    operation_key: Key
    resource: ResourceRef | None = None
    # Explicit immutable historical Fact selection; omission selects Current.
    fact: VersionRef | None = None
