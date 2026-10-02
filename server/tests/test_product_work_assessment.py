"""Field citation integrity and capability coverage, with no model qualification."""

from copy import deepcopy
from typing import Any

import pytest
from pydantic import ValidationError

from app.ai.product_work_context import validate_assessment
from app.contracts.product_work_ai import REQUIRED_SECTIONS, ProductWorkAssessment
from app.domain.product_workspace import ProductWorkError


def fixture(capability: str = "research_planning") -> tuple[dict[str, Any], dict[str, Any]]:
    ref = dict(
        reference_id="evidence:original",
        digest="a" * 64,
        fields={"content": "前文" * 4000 + "原始结论尚未实测。" + "后文" * 4000},
    )
    snapshot = {"selection": {"capability": capability}, "references": [ref]}
    statement = dict(
        nature="observed",
        text="来源没有提供实测结果",
        citations=[
            dict(
                reference_id=ref["reference_id"],
                digest=ref["digest"],
                field_path=["content"],
                quoted_value="原始结论尚未实测。",
            )
        ],
    )
    output = dict(
        capability=capability,
        disposition="analysis",
        summary=[statement],
        sections=[
            dict(key=k, statements=[], missing=["待补依据"]) for k in REQUIRED_SECTIONS[capability]
        ],
        next_steps=[],
        missing=[],
        coverage_limits="仅所选原始资料",
    )
    return snapshot, output


@pytest.mark.parametrize("capability", list(REQUIRED_SECTIONS))
def test_sections_and_real_long_document_excerpt(capability: str) -> None:
    snapshot, output = fixture(capability)
    validate_assessment(ProductWorkAssessment.model_validate(output), snapshot)
    output["sections"][0]["key"] = output["sections"][1]["key"]
    with pytest.raises(ValidationError):
        ProductWorkAssessment.model_validate(output)


@pytest.mark.parametrize("change", ["digest", "field", "quote", "reference", "capability"])
def test_forged_citations_or_cross_capability_outputs_are_rejected(change: str) -> None:
    snapshot, output = fixture()
    citation = output["summary"][0]["citations"][0]
    if change == "capability":
        snapshot["selection"]["capability"] = "competitor_analysis"
    else:
        field, value = {
            "digest": ("digest", "b" * 64),
            "field": ("field_path", ["content", "excerpt"]),
            "quote": ("quoted_value", "原始结论已完成实测。"),
            "reference": ("reference_id", "evidence:unread"),
        }[change]
        citation[field] = value
    with pytest.raises(ProductWorkError):
        validate_assessment(ProductWorkAssessment.model_validate(output), snapshot)


def test_market_size_requires_deterministic_original_and_nonbody_fields_must_be_exact() -> None:
    snapshot, output = fixture("market_analysis")
    output["sections"][1]["statements"] = deepcopy(output["summary"])
    with pytest.raises(ProductWorkError, match="确定性计算"):
        validate_assessment(ProductWorkAssessment.model_validate(output), snapshot)
    output["sections"][1]["statements"][0]["nature"] = "hypothesis"
    validate_assessment(ProductWorkAssessment.model_validate(output), snapshot)
    snapshot, output = fixture()
    snapshot["references"][0]["fields"]["title"] = "合成完整标题"
    output["summary"][0]["citations"][0].update(field_path=["title"], quoted_value="完整标题")
    with pytest.raises(ProductWorkError):
        validate_assessment(ProductWorkAssessment.model_validate(output), snapshot)


@pytest.mark.parametrize("capability", ["product_strategy", "product_definition"])
def test_planning_defaults_to_pie_v6_and_retains_explicit_legacy_prompt(capability: str) -> None:
    import json
    from pathlib import Path

    from app.ai import product_work_context
    from app.contracts.product_planning_ai import ProductPlanningAssessment

    prompt, output_type = product_work_context.contract(capability=capability)
    assert prompt.version == "product-planning-v6"
    assert output_type is ProductPlanningAssessment
    historical, historical_type = product_work_context.contract("product-planning-v5")
    original = json.loads(
        (
            Path(product_work_context.__file__).with_name("prompts") / "product_planning_v5.json"
        ).read_text()
    )
    assert historical.model_dump() == original
    assert historical_type is ProductPlanningAssessment


def test_planning_pie_prefix_stays_fixed_while_dynamic_context_changes() -> None:
    from uuid import UUID

    from app.ai.product_work_context import contract, model_context

    prompt, _ = contract(capability="product_strategy")
    frozen = (prompt.system_prompt, prompt.instruction)
    snapshot: dict[str, Any] = {
        "selection": {
            "capability": "product_strategy",
            "product_line_id": str(UUID(int=1)),
            "question": "合成研究问题A",
            "sources": [],
        },
        "warnings": ["合成未知A"],
        "coverage_limits": ["仅当前资料"],
        "references": [],
    }
    first = model_context(
        snapshot, "合成用户指令A", prompt_version=prompt.version, tenant_id=UUID(int=2)
    )
    snapshot["selection"]["question"] = "合成研究问题B"
    snapshot["warnings"] = ["合成未知B"]
    second = model_context(
        snapshot, "合成用户指令B", prompt_version=prompt.version, tenant_id=UUID(int=2)
    )
    assert first != second
    assert "合成用户指令A" in first["question"] and "合成未知A" in first["question"]
    assert "合成用户指令B" in second["question"] and "合成未知B" in second["question"]
    assert frozen == (prompt.system_prompt, prompt.instruction)
    assert all(
        marker not in "\n".join(frozen)
        for marker in ("合成未知A", "合成未知B", "合成用户指令A", "合成用户指令B")
    )
