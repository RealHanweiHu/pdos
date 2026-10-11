"""Financial precision, explicit assumptions and frozen comparability boundaries."""

import json
from copy import deepcopy
from decimal import Decimal, localcontext
from uuid import UUID

import pytest
from pydantic import ValidationError

from pdos_next.agent_kernel.m3_calculators import (
    ENGINES,
    PRICE_FIELDS,
    SCHEMAS,
    cost_subtotal,
    market_size,
    opportunity_score,
    price_band,
)
from pdos_next.domain.preproject.evidence_schemas import ClaimContent
from pdos_next.service import digest

REF = {"type": "claim", "id": str(UUID(int=10)), "version": 2, "line": 4, "quote": "synthetic"}


def interval(low, high=None):
    return {"low": str(low), "high": str(high if high is not None else low)}


def cost(label="pump", **changes):
    return {
        "label": label,
        "qty": "3",
        "unit_cost": "0.1",
        "currency": "USD",
        "as_of": "2026-10-10",
        "source_ref": REF,
        **changes,
    }


def point(amount="10", **changes):
    return {
        "amount": amount,
        "currency": "USD",
        "observed_on": "2026-10-10",
        "price_type": "retail",
        "includes_tax": True,
        "includes_shipping": False,
        "channel": "online",
        "region": "US",
        "source_ref": REF,
        **changes,
    }


def fx(pair="USD/CNY", rate="7.1", **changes):
    return {"pair": pair, "rate": rate, "as_of": "2026-10-09", "source_ref": REF, **changes}


def test_money_is_exact_and_independent_of_ambient_decimal_context():
    with localcontext() as ctx:
        ctx.prec = 2
        result = cost_subtotal({"lines": [cost(), cost("seal", qty="1", unit_cost="0.2")]})
    assert result["groups"][0]["amount"] == "0.5"
    assert result["groups"][0]["items"][0]["source_ref"] == {**REF, "statement": None}
    json.dumps(result, allow_nan=False)


def test_missing_price_with_zero_quantity_is_unknown_not_zero():
    result = cost_subtotal({"lines": [cost(), cost("unknown", qty="0", unit_cost=None)]})
    group = result["groups"][0]
    assert group["availability"] == "partial"
    assert group["amount"] is None
    assert group["known_subtotal"]["amount"] == "0.3"
    assert result["missing"] == [{"input_index": 1, "reasons": ["missing_unit_cost"]}]
    only_missing = cost_subtotal({"lines": [cost(unit_cost=None)]})
    assert only_missing["groups"][0]["known_subtotal"]["amount"] is None


def test_cost_currency_date_and_basis_are_not_merged():
    result = cost_subtotal(
        {
            "lines": [
                cost(),
                cost(currency="EUR"),
                cost(as_of="2026-10-09"),
                cost(basis="per carton"),
            ]
        }
    )
    assert len(result["groups"]) == 4
    assert result["converted_groups"] == []
    assert all(g["amount"] == "0.3" for g in result["groups"])


def test_explicit_fx_preserves_original_price_rate_date_and_sources():
    args = {
        "lines": [cost(), cost("local", currency="CNY", unit_cost="1", qty="1")],
        "target_currency": "CNY",
        "fx": [fx()],
    }
    result = cost_subtotal(args)
    assert result["converted_groups"][0]["amount"] == "3.13"
    converted = result["lines"][0]["conversion"]
    assert converted["amount"] == "2.13"
    assert converted["fx"]["as_of"] == "2026-10-09"
    assert converted["fx"]["source_ref"]["id"] == REF["id"]
    assert result["lines"][0]["as_of"] == "2026-10-10"
    assert result["lines"][0]["currency"] == "USD"


@pytest.mark.parametrize(
    "rates, reason",
    [
        ([], "missing_fx"),
        ([fx("CNY/USD")], "missing_fx"),
        ([fx(), fx(as_of="2026-10-08")], "ambiguous_fx"),
    ],
)
def test_fx_is_never_inferred_inverted_or_arbitrarily_selected(rates, reason):
    result = cost_subtotal({"lines": [cost()], "target_currency": "CNY", "fx": rates})
    assert result["lines"][0]["conversion"]["reason"] == reason
    assert result["groups"][0]["amount"] == "0.3"
    assert result["converted_groups"][0]["amount"] is None


def test_market_intervals_quantity_and_population_methods_with_partial_segment():
    result = market_size(
        {
            "segments": [
                {
                    "name": "existing",
                    "quantity": interval(10, 20),
                    "price": interval("0.1", "0.2"),
                    "currency": "USD",
                    "source_refs": [REF],
                    "assumptions": ["annual units"],
                },
                {
                    "name": "new",
                    "population": interval(100, 200),
                    "penetration": interval("0.1", "0.2"),
                    "price": interval(2, 3),
                    "currency": "USD",
                },
                {"name": "unknown", "quantity": interval(5), "currency": "EUR"},
            ]
        }
    )
    usd, eur = result["groups"]
    assert Decimal(usd["low"]) == Decimal("21")
    assert Decimal(usd["high"]) == Decimal("124")
    assert eur["low"] is None and eur["high"] is None
    assert result["availability"] == "partial"
    assert result["missing"] == [{"input_index": 2, "reasons": ["missing_price"]}]
    assert result["assumptions"][0]["statements"] == ["annual units"]
    assert result["segments"][0]["source_refs"][0]["id"] == REF["id"]


def test_market_large_finite_inputs_do_not_revalidate_intermediate_as_input():
    result = market_size(
        {
            "segments": [
                {
                    "name": "large synthetic",
                    "population": interval("1e59"),
                    "penetration": interval("0.999999999999999999999999999999"),
                    "price": interval("1e59"),
                    "currency": "USD",
                }
            ]
        }
    )
    assert result["availability"] == "known"
    assert len(result["groups"][0]["low"].split(".")[0]) == 118


def test_explicit_weights_no_hidden_normalization_and_no_gate_decision():
    result = opportunity_score(
        {
            "criteria": [
                {
                    "key": "fit",
                    "weight": "0.7",
                    "score": "4",
                    "rationale": "synthetic fit",
                    "weight_rationale": "owner choice",
                    "weight_source_refs": [REF],
                },
                {"key": "risk", "weight": "0.2", "score": "2", "source_refs": [REF]},
            ]
        }
    )
    assert result["total_score"] == "3.2"
    assert result["total_weight"] == "0.9"
    assert result["advisory_only"] is True
    assert result["criteria"][0]["weight_source_refs"][0]["id"] == REF["id"]
    assert "qualified" not in result and "passed" not in result


def test_missing_weight_or_score_prevents_total_even_for_zero_weight():
    result = opportunity_score(
        {
            "criteria": [
                {"key": "fit", "weight": "1", "score": "3"},
                {"key": "unknown", "score": "5"},
                {"key": "zero", "weight": "0"},
            ]
        }
    )
    assert result["total_score"] is None and result["total_weight"] is None
    assert result["known_weighted_subtotal"] == "3"
    assert result["criteria"][2]["weighted_score"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("currency", "EUR"),
        ("observed_on", "2026-10-09"),
        ("price_type", "wholesale"),
        ("includes_tax", False),
        ("includes_shipping", True),
        ("channel", "store"),
        ("region", "CN"),
    ],
)
def test_price_group_by_cannot_erase_frozen_comparability_fields(field, value):
    result = price_band(
        {
            "price_points": [point(), point("20", **{field: value})],
            "quantiles": ["0.5"],
            "group_by": [],
        }
    )
    assert len(result["groups"]) == 2
    assert set(result["effective_group_by"]) == set(PRICE_FIELDS)
    assert [g["count"] for g in result["groups"]] == [1, 1]


def test_price_quantiles_are_explicit_decimal_interpolations_with_duplicate_points_kept():
    result = price_band(
        {
            "price_points": [point("0.1"), point("0.2"), point("0.2"), point("0.4")],
            "quantiles": ["0", "0.25", "0.5", "1"],
        }
    )
    group = result["groups"][0]
    assert [Decimal(q["value"]) for q in group["quantiles"]] == list(
        map(Decimal, ["0.1", "0.175", "0.2", "0.4"])
    )
    assert group["count"] == 4
    assert len(group["price_points"]) == 4


def test_explicit_bands_have_unambiguous_boundaries_and_report_uncovered_points():
    result = price_band(
        {
            "price_points": [point("0"), point("10"), point("20")],
            "bands": [interval(0, 10), interval(10, 20)],
        }
    )
    group = result["groups"][0]
    assert [b["count"] for b in group["bands"]] == [1, 1]
    assert group["out_of_band_count"] == 1
    assert result["band_boundary_rule"] == "low <= amount < high"


def test_price_conversion_merges_only_otherwise_comparable_points_and_keeps_rate_date():
    result = price_band(
        {
            "price_points": [
                point("10"),
                point("71", currency="CNY"),
                point("10", observed_on="2026-10-08"),
            ],
            "quantiles": ["0.5"],
            "target_currency": "CNY",
            "fx": [fx()],
        }
    )
    assert len(result["groups"]) == 2
    group = result["groups"][0]
    assert group["currency"] == "CNY" and group["count"] == 2
    assert Decimal(group["min"]) == Decimal("71")
    source = group["price_points"][0]
    assert source["currency"] == "USD" and source["amount"] == "10"
    assert source["observed_on"] == "2026-10-10"
    assert source["conversion"]["fx"]["as_of"] == "2026-10-09"


def test_price_without_fx_retains_currency_and_reports_conversion_gap():
    result = price_band(
        {
            "price_points": [point(), point(currency="CNY")],
            "target_currency": "CNY",
            "quantiles": ["0.5"],
        }
    )
    assert [g["currency"] for g in result["groups"]] == ["USD", "CNY"]
    assert result["conversion_gaps"][0]["reason"] == "missing_fx"


def test_missing_price_or_any_basis_is_separate_and_never_a_zero_point():
    result = price_band(
        {
            "price_points": [
                point(None),
                point(observed_on=None),
                point(includes_tax=None),
                point("0"),
            ],
            "quantiles": ["0.5"],
        }
    )
    assert result["availability"] == "partial"
    assert result["unknown_count"] == 3
    assert result["groups"][0]["count"] == 1
    assert result["groups"][0]["min"] == "0"
    assert result["incomparable_points"][0]["reasons"] == ["missing_amount"]


@pytest.mark.parametrize(
    "tool,args",
    [
        ("calc.cost_subtotal", {"lines": []}),
        ("calc.market_size", {"segments": []}),
        ("calc.opportunity_score", {"criteria": []}),
        ("calc.price_band", {"price_points": [], "quantiles": ["0.5"]}),
    ],
)
def test_empty_input_is_unknown_and_engine_metadata_has_only_fixed_claim_projection(tool, args):
    original = deepcopy(args)
    engine = ENGINES[tool]
    result = engine.calculate(args)
    assert result["availability"] == "unknown"
    assert result["engine_version"] == engine.version
    assert result["input_digest"] == digest([tool, args])
    if tool == "calc.cost_subtotal":
        assert engine.claim_paths == (("proof_claims", "single_currency_subtotal"),)
        assert result["proof_claims"] == {}
    else:
        assert engine.claim_paths == ()
    assert args == original
    assert engine.calculate(args) == result
    assert SCHEMAS[tool].model_json_schema()["additionalProperties"] is False


@pytest.mark.parametrize("value", [True, False, 0.1, "NaN", "Infinity", "-1"])
def test_invalid_money_cannot_enter_arithmetic(value):
    with pytest.raises(ValidationError):
        cost_subtotal({"lines": [cost(unit_cost=value)]})


@pytest.mark.parametrize(
    "args",
    [
        {"price_points": [point()]},
        {"price_points": [point()], "quantiles": ["1.1"]},
        {"price_points": [point()], "quantiles": ["0.5"], "bands": [interval(0, 10)]},
        {"price_points": [point()], "bands": [interval(0, 20), interval(10, 30)]},
        {"price_points": [point(includes_tax="false")], "quantiles": ["0.5"]},
        {
            "price_points": [point(source_ref={**REF, "tenant_id": str(UUID(int=1))})],
            "quantiles": ["0.5"],
        },
        {"price_points": [point()], "quantiles": ["0.5"], "qualified": True},
    ],
)
def test_strict_input_blocks_ambiguous_statistics_policy_fields_and_coercive_booleans(args):
    with pytest.raises(ValidationError):
        price_band(args)


def test_market_rejects_conflicting_quantity_methods_or_invalid_penetration():
    segment = {
        "name": "sample",
        "population": interval(100),
        "penetration": interval("0.1"),
        "price": interval(10),
        "currency": "USD",
    }
    with pytest.raises(ValidationError):
        market_size({"segments": [{**segment, "quantity": interval(10)}]})
    with pytest.raises(ValidationError):
        market_size({"segments": [{**segment, "penetration": interval("1.1")}]})


def test_single_currency_claim_is_exact_complete_and_normalization_stable():
    args = {
        "lines": [
            cost(unit_cost="0.12345678901234567890123456789"),
            cost("seal", qty="1", unit_cost="0.2", as_of="2026-10-09"),
        ]
    }
    with localcontext() as context:
        context.prec = 2
        result = cost_subtotal(args)
    claim = result["proof_claims"]["single_currency_subtotal"]
    assert claim["value"] == "0.57037036703703703670370370367"
    assert claim["unit"] == "USD"
    assert claim["parameter_id"] is None and claim["parameter_version"] is None
    assert claim == ClaimContent.model_validate(claim).model_dump(mode="json")
    assert set(claim) == set(ClaimContent.model_fields)
    assert result["input_digest"] in claim["condition_note"]
    assert "2026-10-09, 2026-10-10" in claim["condition_note"]
    assert "来源、数量和单价尚须核验" in claim["condition_note"]
    assert "未折算" in claim["condition_note"]
    assert len(result["groups"]) == 2  # The original date-grouped output is unchanged.
    assert cost_subtotal(args)["proof_claims"]["single_currency_subtotal"] == claim


@pytest.mark.parametrize("field", ["qty", "unit_cost", "currency", "as_of", "source_ref"])
def test_incomplete_cost_input_never_projects_a_computed_claim(field):
    result = cost_subtotal({"lines": [cost(), cost("incomplete", **{field: None})]})
    assert result["proof_claims"] == {}


def test_single_currency_claim_never_collapses_original_currencies_even_with_complete_fx():
    result = cost_subtotal(
        {
            "lines": [cost(), cost("other", currency="CNY")],
            "target_currency": "CNY",
            "fx": [fx()],
        }
    )
    assert result["converted_groups"][0]["amount"] == "2.43"
    assert result["proof_claims"] == {}


def test_single_currency_claim_uses_native_currency_and_explicit_zero_is_known():
    result = cost_subtotal({"lines": [cost(qty="0")], "target_currency": "CNY", "fx": [fx()]})
    claim = result["proof_claims"]["single_currency_subtotal"]
    assert Decimal(claim["value"]) == Decimal(0)
    assert claim["unit"] == "USD"
    assert result["converted_groups"][0]["currency"] == "CNY"


@pytest.mark.parametrize("placement", ["input", "line"])
def test_model_cannot_supply_or_override_the_fixed_claim_projection(placement):
    forged = {"value": "999", "unit": "USD", "condition_note": "approved"}
    args = {"lines": [cost()]}
    if placement == "input":
        args["proof_claims"] = {"single_currency_subtotal": forged}
    else:
        args["lines"][0]["proof_claims"] = {"single_currency_subtotal": forged}
    with pytest.raises(ValidationError):
        cost_subtotal(args)
