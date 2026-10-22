"""Closed human inputs; resources, eligibility and consumption are server facts."""

from uuid import UUID

from pydantic import Field, model_validator

from pdos_next.domain.configurations.schemas import DefinitionReference
from pdos_next.domain.verification_front.schemas import Revision, Sha256, Text
from pdos_next.schemas.resource_readiness.contracts import ExecutionWindow
from pdos_next.schemas.verification.contracts import DTO, Coverage, EventTime


class ExecutionPlan(DTO):
    window: ExecutionWindow
    executor_id: UUID
    equipment: DefinitionReference
    calibration: DefinitionReference
    environment: Text
    conditions: Text
    resource_fact_id: UUID
    expected_resource_fact_revision: Revision


class LaunchBase(DTO):
    request_id: UUID
    expected_request_revision: Revision
    sources: tuple[DefinitionReference, ...] = Field(default=())
    reason: Text
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)


class PlanPayload(LaunchBase):
    run_id: UUID
    coverage: tuple[Coverage, ...] = Field(min_length=1)
    execution_plan: ExecutionPlan

    @model_validator(mode="after")
    def unique_coverage(self):
        if len({(c.sample_id, c.item_id) for c in self.coverage}) != len(self.coverage):
            raise ValueError("Run覆盖范围中的样件/测试项不能重复")
        return self


class PromisePayload(LaunchBase):
    run_id: UUID
    expected_run_revision: Revision
    expected_plan_sha256: Sha256
    at: EventTime


class StartPayload(PromisePayload):
    """Execution conditions are loaded from the fixed plan, never changed by Start."""
