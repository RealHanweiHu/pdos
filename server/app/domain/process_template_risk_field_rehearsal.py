"""Simulated supplemental field inputs checked by the actual Risk validator."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt

from app.domain.process_template_fields import TemplateFieldError
from app.domain.process_template_risk_fields import definitions, validate_values

Scalar = StrictBool | StrictInt | StrictFloat | Annotated[str, Field(max_length=6000)] | None
RANK = {"open": 0, "response": 1, "mitigating": 1, "watching": 1, "closed": 2}


class RiskFieldRehearsal(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    name: str = Field(min_length=1, max_length=200)
    status: Literal["open", "mitigating", "watching", "closed"]
    values: dict[str, Scalar] = Field(default_factory=dict, max_length=30)
    expected_valid: bool
    expected_error_field: str | None = Field(default=None, max_length=64)


def rehearse_risk_fields(
    snapshot: dict[str, Any], cases: list[RiskFieldRehearsal]
) -> dict[str, Any]:
    fields = definitions(snapshot)
    positive: set[str] = set()
    invalid: set[str] = set()
    missing: set[str] = set()
    response_missing: set[tuple[str, str]] = set()
    drafts: set[str] = set()
    results = []
    for case in cases:
        error_field = None
        error_kind = None
        error = None
        normalized: dict[str, Any] = {}
        try:
            normalized = validate_values(fields, case.values, case.status)
            valid = True
        except TemplateFieldError as failure:
            valid = False
            error_field, error_kind, error = failure.field_key, failure.kind, str(failure)
        passed = valid == case.expected_valid and error_field == case.expected_error_field
        if passed and valid:
            for item in fields:
                if item.key in normalized and (
                    item.required_at is None or RANK[case.status] >= RANK[item.required_at]
                ):
                    positive.add(item.key)
                if case.status == "open" and item.key not in normalized:
                    drafts.add(item.key)
        if passed and not valid and error_field is not None:
            # An isolated failing field must explain the negative example.
            try:
                validate_values(
                    [item for item in fields if item.key != error_field],
                    {key: value for key, value in case.values.items() if key != error_field},
                    case.status,
                )
            except TemplateFieldError:
                pass
            else:
                (missing if error_kind == "missing" else invalid).add(error_field)
                if error_kind == "missing":
                    response_missing.add((error_field, case.status))
        results.append(
            {
                "name": case.name,
                "inputs": case.model_dump(mode="json"),
                "valid": valid,
                "passed": passed,
                "error": error,
                "error_field": error_field,
                "error_kind": error_kind,
                "normalized": normalized,
            }
        )
    required = {item.key for item in fields}
    mandatory = {item.key for item in fields if item.required_at is not None}
    response = {item.key for item in fields if item.required_at == "response"}
    return {
        "cases": results,
        "coverage": [
            {
                "key": item.key,
                "label": item.label,
                "positive": item.key in positive,
                "invalid": item.key in invalid,
                "required": item.required_at is not None,
                "missing": item.key in missing,
                "draft": item.key in drafts,
                "response_branches": item.key not in response
                or all(
                    (item.key, state) in response_missing for state in ("mitigating", "watching")
                ),
            }
            for item in fields
        ],
        "passed": required <= positive
        and required <= invalid
        and mandatory <= missing
        and mandatory <= drafts
        and all(
            (key, state) in response_missing
            for key in response
            for state in ("mitigating", "watching")
        )
        and all(item["passed"] for item in results),
        "scope": (
            "用虚构填写内容复用实际风险字段校验；每项字段核对正确值和单项格式错误，"
            "必填项另核对可先暂存与到办理节点缺项会被拦截。"
            "不代表实际风险已确认、处理或关闭；原有责任、评分、处理方案和结果仍须核验。"
        ),
    }


def risk_field_examples(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    fields = definitions(snapshot)
    if not fields:
        return []
    valid: dict[str, Scalar] = {}
    for item in fields:
        if item.kind == "number":
            valid[item.key] = (
                item.minimum
                if item.minimum is not None
                else min(0.0, item.maximum)
                if item.maximum is not None
                else 0
            )
        elif item.kind == "boolean":
            valid[item.key] = False
        elif item.kind == "date":
            valid[item.key] = "2026-01-10"
        elif item.kind == "choice":
            valid[item.key] = item.choices[0]
        else:
            valid[item.key] = "模拟资料"[: item.max_length]
    cases = [
        RiskFieldRehearsal(
            name="资料齐全时满足字段要求", status="closed", values=valid, expected_valid=True
        ),
        RiskFieldRehearsal(
            name="风险可先暂存再补齐", status="open", values={}, expected_valid=True
        ),
    ]
    for item in fields:
        wrong: Scalar = "非数值" if item.kind in {"number", "boolean"} else 123
        cases.append(
            RiskFieldRehearsal(
                name=f"{item.label}格式不符"[:200],
                status="closed",
                values=valid | {item.key: wrong},
                expected_valid=False,
                expected_error_field=item.key,
            )
        )
        checkpoints: tuple[Literal["mitigating", "watching", "closed"], ...] = (
            ("mitigating", "watching")
            if item.required_at == "response"
            else ("closed",)
            if item.required_at == "closed"
            else ()
        )
        for checkpoint in checkpoints:
            cases.append(
                RiskFieldRehearsal(
                    name=f"办理前缺少{item.label}"[:200],
                    status=checkpoint,
                    values={key: value for key, value in valid.items() if key != item.key},
                    expected_valid=False,
                    expected_error_field=item.key,
                )
            )
    return [case.model_dump(mode="json") for case in cases]
