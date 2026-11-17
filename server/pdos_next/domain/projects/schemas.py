from typing import Literal, Self
from uuid import UUID

from pdos_next.core.schema_base import StrictModel
from pdos_next.domain.projects.npi.rules import PlanBasis
from pdos_next.schemas.planning import ScheduleInput
from pydantic import Field, model_serializer, model_validator


class ResourceDemand(StrictModel):
    task_key: str = Field(min_length=1, max_length=80)
    resource_id: UUID
    kind: Literal["person", "resource"]
    coordinator_id: UUID
    purpose: str = Field(min_length=3, max_length=500)
    units: int = Field(default=1, ge=1, le=10000, strict=True)


class PlanProposePayload(StrictModel):
    project_id: UUID
    expected_project_revision: int = Field(ge=1)
    base_plan_id: UUID | None = None
    resource_demands: tuple[ResourceDemand, ...] = Field(default=(), max_length=1000)
    schedule: ScheduleInput
    npi: PlanBasis | None = None
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
        keys = {task.key for task in self.schedule.tasks}
        if any(d.task_key not in keys for d in self.resource_demands):
            raise ValueError("资源需求须对应本候选的真实任务")
        if len({(d.task_key, d.kind, d.resource_id) for d in self.resource_demands}) != len(
            self.resource_demands
        ):
            raise ValueError("同一任务的资源需求不得重复")
        return self


class PlanApplyPayload(StrictModel):
    project_id: UUID
    proposal_id: UUID | None = None
    draft: PlanProposePayload | None = None
    expected_project_revision: int = Field(ge=1)
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)

    @model_serializer(mode="wrap")
    def serialize(self, handler):
        result = handler(self)
        if self.draft is None:
            result.pop("draft", None)
        if self.proposal_id is None:
            result.pop("proposal_id", None)
        return result

    @model_validator(mode="after")
    def intent(self):
        if (self.proposal_id is None) == (self.draft is None):
            raise ValueError("请选择固定计划候选，或提交一份待确认的框架计划")
        if self.draft and (
            self.draft.project_id != self.project_id
            or self.draft.expected_project_revision != self.expected_project_revision
            or self.draft.npi is None
        ):
            raise ValueError("待确认框架计划须固定同一个项目与版本")
        return self
