"""Coverage scores preserve unknowns, explicit policy and historical input identity."""

from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain.product_matrix_coverage import CoverageCalculation, calculate_snapshot
from app.domain.product_workspace import digest


def fixture():
    a, b = str(uuid4()), str(uuid4())
    query = dict(
        segment_id=str(uuid4()),
        expected_source_digest="a" * 64,
        choices=[dict(product_id=p, release_id=str(uuid4())) for p in (a, b)],
        criteria=[
            dict(
                key=key,
                source_locator="job_to_be_done",
                interpretation="合成判据",
                mode="feature",
                mappings=[
                    dict(product_id=a, item_key=key),
                    *([dict(product_id=b, item_key=key)] if key == "inflate" else []),
                ],
                lower=None,
                upper=None,
                unit=None,
                conditions=[],
            )
            for key in ("inflate", "light")
        ],
    )
    prepared = dict(
        version="market-definition-coverage.v1",
        facts=[dict(locator="job_to_be_done", fact={"text": "合成需求"})],
        products=[
            dict(
                id=a,
                path=[],
                content=dict(included_features=["inflate"], excluded_features=["light"], items=[]),
            ),
            dict(
                id=b,
                path=[],
                content=dict(included_features=["inflate"], excluded_features=[], items=[]),
            ),
        ],
    )
    policy = dict(
        formula_version="product-coverage-weighted.v1",
        policy_key="sample",
        policy_version=1,
        title="合成覆盖口径",
        basis="合成显式政策，非商业事实",
        weights=[
            dict(criterion_key="inflate", weight="0.7", basis="合成补气需求优先"),
            dict(criterion_key="light", weight="0.3", basis="合成照明需求"),
        ],
    )
    return query, prepared, policy


def test_unknown_range_no_renormalization_no_double_count_and_exact_replay():
    query, prepared, policy = fixture()
    query["scoring_policy"] = policy
    result = calculate_snapshot(CoverageCalculation.model_validate(query), prepared)
    score = result["scoring"]
    a, b = score["products"]
    assert Decimal(a["score"]) == 70
    assert (
        b["score"] is None and Decimal(b["lower_bound"]) == 70 and Decimal(b["upper_bound"]) == 100
    )
    assert b["contributions"][1]["points"] is None
    assert score["selected_portfolio"]["score"] is None
    assert Decimal(score["selected_portfolio"]["lower_bound"]) == 70  # not 140
    assert score["policy"] == policy and score["policy_digest"] == digest(policy)
    replay = calculate_snapshot(
        CoverageCalculation.model_validate(deepcopy(query)), deepcopy(prepared)
    )
    assert result == replay
    assert result["formula_version"] == "market-definition-coverage.v2"
    query["scoring_policy"]["weights"][0]["weight"] = "0.2"
    query["scoring_policy"]["weights"][1]["weight"] = "0.8"
    changed = calculate_snapshot(CoverageCalculation.model_validate(query), prepared)
    assert Decimal(changed["scoring"]["products"][0]["score"]) == 20
    assert changed["result_digest"] != result["result_digest"]


def test_legacy_v1_input_and_result_do_not_gain_optional_fields():
    query, prepared, _ = fixture()
    original = CoverageCalculation.model_validate(query)
    assert original.model_dump(mode="json") == query
    result = calculate_snapshot(original, prepared)
    assert result["formula_version"] == "market-definition-coverage.v1" and "scoring" not in result
    assert result["input_digest"] == digest(query)
    assert (
        calculate_snapshot(
            CoverageCalculation.model_validate({**query, "scoring_policy": None}), prepared
        )
        == result
    )


@pytest.mark.parametrize(
    "weights",
    [
        [("inflate", "0.5")],
        [("inflate", "0.5"), ("light", "0.4")],
        [("inflate", "0.5"), ("inflate", "0.5")],
        [("inflate", "0.5"), ("outside", "0.5")],
        [("inflate", "1"), ("light", "0")],
        [("inflate", "NaN"), ("light", "0.5")],
        [("inflate", "1.1"), ("light", "-0.1")],
    ],
)
def test_invalid_policy_never_silently_normalizes_or_omits(weights):
    query, _, policy = fixture()
    policy["weights"] = [
        dict(criterion_key=key, weight=weight, basis="合成依据") for key, weight in weights
    ]
    with pytest.raises(ValidationError):
        CoverageCalculation.model_validate({**query, "scoring_policy": policy})


def test_numeric_condition_mismatch_is_unknown_even_with_full_weight():
    query, prepared, policy = fixture()
    query["criteria"] = [
        dict(
            key="pressure",
            source_locator="job_to_be_done",
            interpretation="同工况压力",
            mode="numeric_spec",
            lower="95",
            upper="105",
            unit="kPa",
            conditions=["25℃"],
            mappings=[dict(product_id=p["id"], item_key="pressure") for p in prepared["products"]],
        )
    ]
    policy["weights"] = [dict(criterion_key="pressure", weight="1", basis="唯一所选判据")]
    for product in prepared["products"]:
        product["content"]["items"] = [
            dict(
                item_key="pressure",
                target_value="100",
                unit="kPa",
                conditions=["0℃"],
                state="confirmed",
            )
        ]
    score = calculate_snapshot(
        CoverageCalculation.model_validate({**query, "scoring_policy": policy}), prepared
    )["scoring"]
    assert score["selected_portfolio"]["score"] is None
    assert Decimal(score["selected_portfolio"]["lower_bound"]) == 0
    assert Decimal(score["selected_portfolio"]["upper_bound"]) == 100
