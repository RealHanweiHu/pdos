"""Versioned workflow templates instantiated into project-owned records."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StageTemplate:
    code: str
    name: str
    description: str
    sequence: int


@dataclass(frozen=True)
class WorkflowTemplate:
    code: str
    name: str
    description: str
    version: int
    stages: tuple[StageTemplate, ...]


NPD_WORKFLOW_TEMPLATE = WorkflowTemplate(
    code="npd",
    name="NPD",
    description="新产品开发七阶段基线",
    version=1,
    stages=(
        StageTemplate("concept", "概念阶段", "市场洞察与产品立项", 1),
        StageTemplate("planning", "规划阶段", "产品规格与项目计划", 2),
        StageTemplate("design", "设计阶段", "ID/MD/EE/SW 并行设计", 3),
        StageTemplate("evt", "EVT 工程验证", "工程样机功能验证", 4),
        StageTemplate("dvt", "DVT 设计验证", "设计成熟度全面验证", 5),
        StageTemplate("pvt", "PVT 试产验证", "生产工艺与良率验证", 6),
        StageTemplate("mp", "量产稳定与移交", "量产爬坡、稳定验证与项目关闭移交", 7),
    ),
)
