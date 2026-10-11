from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from pdos_next.schema_base import StrictModel
from pdos_next.schemas.planning import ScheduleInput


class PlanProposePayload(StrictModel):
    project_id: UUID
    expected_project_revision: int = Field(ge=1)
    schedule: ScheduleInput
    reason: str = Field(min_length=3, max_length=2000)

    @model_validator(mode="after")
    def actual_work_packages(self) -> Self:
        if any(task.discipline not in {"engineering", "npi"} for task in self.schedule.tasks):
            raise ValueError("首版计划的任务须归属工程或NPI工作包")
        if any(
            (task.duration_min_minutes is not None or task.duration_max_minutes is not None)
            and not task.estimate_source
            for task in self.schedule.tasks
        ):
            raise ValueError("已知工时须注明估计依据，未知工时保留空值")
        return self


class PlanApplyPayload(StrictModel):
    project_id: UUID
    proposal_id: UUID
    expected_project_revision: int = Field(ge=1)
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)
