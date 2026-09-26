"""Human-readable simulated routing inputs using the actual plan route resolver."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.process_template_routing import ProfessionalRole, planned_routes
from app.domain.project_templates import (
    ProjectTemplateError,
    ProjectTemplateSelection,
    compile_selection,
)

Person = Annotated[str, Field(min_length=1, max_length=100)]


class RouteRehearsal(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    features: dict[str, bool] = Field(default_factory=dict, max_length=30)
    participants: list[Person] = Field(default_factory=list, max_length=30)
    bindings: dict[ProfessionalRole, Person] = Field(default_factory=dict, max_length=8)
    expected: dict[str, dict[Literal["owner", "receiver"], Person | None]] = Field(
        default_factory=dict, max_length=200
    )
    expect_valid: bool = True


def rehearse_routes(snapshot: dict[str, Any], cases: list[RouteRehearsal]) -> dict[str, Any]:
    required = {(row["node_key"], row["slot"]) for row in planned_routes(snapshot, {})}
    positives: set[tuple[str, str]] = set()
    negatives: set[tuple[str, str]] = set()
    results = []
    for case in cases:
        try:
            if len(set(case.participants)) != len(case.participants):
                raise ProjectTemplateError("模拟参与人标识不能重复")
            if set(case.bindings.values()) - set(case.participants):
                raise ProjectTemplateError("职责联系人不在本场景的模拟参与人范围")
            selected = compile_selection(
                ProjectTemplateSelection(
                    template_id=snapshot["id"],
                    version=snapshot["version"],
                    features=case.features,
                    reason=case.name,
                ),
                templates=[snapshot],
            )
            routes = {
                (row["node_key"], row["slot"]): row
                for row in planned_routes(selected, case.bindings)
            }
            expected = {
                (code, slot): person
                for code, slots in case.expected.items()
                for slot, person in slots.items()
            }
            if expected.keys() - routes.keys():
                raise ProjectTemplateError("预期分派引用了不适用或未配置的任务路由")
            checks = [
                {
                    **routes[key],
                    "expected_user": person,
                    "matches": person == routes[key]["user_id"],
                }
                for key, person in sorted(expected.items())
            ]
            passed = case.expect_valid and bool(checks) and all(item["matches"] for item in checks)
            if passed:
                positives.update(key for key in expected if routes[key]["user_id"] is not None)
                negatives.update(key for key in expected if routes[key]["user_id"] is None)
            results.append(
                {
                    "name": case.name,
                    "inputs": case.model_dump(mode="json"),
                    "valid": True,
                    "passed": passed,
                    "checks": checks,
                }
            )
        except ProjectTemplateError as error:
            results.append(
                {
                    "name": case.name,
                    "inputs": case.model_dump(mode="json"),
                    "valid": False,
                    "passed": not case.expect_valid,
                    "error": str(error),
                    "checks": [],
                }
            )
    return {
        "cases": results,
        "coverage": [
            {
                "node_key": code,
                "slot": slot,
                "positive": (code, slot) in positives,
                "missing_contact": (code, slot) in negatives,
            }
            for code, slot in sorted(required)
        ],
        "passed": required <= positives
        and required <= negatives
        and all(item["passed"] for item in results),
        "scope": (
            "使用模拟联系人和参与人范围，复用实际计划分派计算；"
            "不代表真实成员资格、本人确认或正式任务已应用。"
            "每项路由需覆盖有联系人及缺联系人两种情况。"
        ),
    }
