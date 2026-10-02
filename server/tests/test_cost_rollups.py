"""Cost scope, units, currencies and historical comparisons without database access."""

from copy import deepcopy
from datetime import date
from typing import Any
from uuid import UUID

import pytest

from app.domain.cost_backtests import BacktestDraft, compare
from app.domain.cost_inputs import PriceDraft, RateDraft
from app.domain.cost_rollups import RollupDraft, calculate
from app.domain.product_workspace import ProductWorkError

BOM, ITEM, PRICE, RATE, DOCUMENT, SUPPLIER = (UUID(int=i) for i in range(1, 7))


def fixture(stage: str = "estimate", unit: str = "个") -> tuple[RollupDraft, dict[str, Any]]:
    values: dict[str, Any] = dict(
        kind="price",
        stage=stage,
        title="物料成本",
        subsystem="硬件",
        category="material",
        basis="unit",
        currency="CNY",
        amount="2",
        price_quantity="1",
        unit=unit,
        tax_basis="exclusive",
        freight_basis="included",
        scope_basis="原BOM材料",
        bom_item_id=ITEM,
        evidence_id=DOCUMENT,
        source_reference="授权成本凭证",
        source_line="行1",
        location="Sheet1!A2",
        as_of=date(2020, 1, 1),
        reason="按原件登记",
    )
    if stage == "quote":
        values.update(
            supplier_id=SUPPLIER,
            valid_from=date(2020, 1, 1),
            valid_until=date(2020, 1, 31),
            minimum_order_quantity="10",
        )
    if stage == "actual":
        values.update(
            actual_source="erp_snapshot", actual_quantity="20", price_quantity="20", amount="60"
        )
    price = PriceDraft.model_validate(values)
    command = RollupDraft.model_validate(
        dict(
            bom_id=BOM,
            title="同口径成本",
            stage=stage,
            currency="CNY",
            as_of="2020-01-02",
            product_quantity="10",
            product_unit="台",
            tax_basis="exclusive",
            freight_basis="included",
            rate_type="spot",
            max_rate_age_days=10,
            nre_policy="separate",
            quantity_basis="10台，每台2个",
            scope_basis="BOM原材料",
            prices=[dict(input_id=PRICE)],
        )
    )
    fixed = dict(
        items=[dict(id=str(ITEM), parent_item_id=None, part_number="P", unit="个", quantity="2")],
        inputs=[
            dict(
                id=str(PRICE),
                record_id=str(PRICE),
                version=1,
                current=True,
                source_current=True,
                payload=price.model_dump(mode="json"),
            )
        ],
    )
    return command, fixed


@pytest.mark.parametrize("stage", ["estimate", "quote", "actual"])
def test_unit_mismatch_is_visible_gap_in_each_cost_stage(stage: str) -> None:
    command, fixed = fixture(stage, unit="盒")
    result = calculate(command, fixed)
    assert not result["complete"]
    assert result["unit_total"] is None
    assert result["lines"][0]["value"] is None
    assert any("计价单位" in gap for gap in result["gaps"])


def test_valid_quote_and_actual_stay_separate_and_recomputable() -> None:
    quote, quoted = fixture("quote")
    actual, observed = fixture("actual")
    quote_result, actual_result = calculate(quote, quoted), calculate(actual, observed)
    assert quote_result["complete"] and quote_result["unit_total"] == "4"
    assert actual_result["complete"] and actual_result["unit_total"] == "6"
    assert quote_result["lines"][0]["stage"] == "quote"
    with pytest.raises(ProductWorkError, match="对应阶段"):
        calculate(actual, quoted)


def test_same_quantity_different_bom_units_cannot_be_compared_as_saving() -> None:
    frozen_command, frozen_basis = fixture()
    actual_command, actual_basis = fixture("actual")
    frozen = dict(
        command=frozen_command.model_dump(mode="json"),
        snapshot=frozen_basis,
        result=calculate(frozen_command, frozen_basis),
    )
    actual = dict(
        command=actual_command.model_dump(mode="json"),
        snapshot=actual_basis,
        result=calculate(actual_command, actual_basis),
    )
    command = BacktestDraft.model_validate(
        dict(
            freeze_id=BOM,
            actual_rollup_id=ITEM,
            expected_calculation_digest="a" * 64,
            title="授权历史成本对照",
            purpose="historical_snapshot",
            period_from="2020-01-01",
            period_to="2020-01-02",
            evidence_id=DOCUMENT,
            evidence_location="原ERP行",
            scope_basis="同BOM材料",
            quantity_basis="10台",
            limitations="历史快照，非当前量产成果",
            pairs=[
                dict(frozen_input_id=PRICE, actual_input_id=PRICE, correspondence_basis="原料号")
            ],
        )
    )
    valid = compare(command, frozen, actual)
    assert valid["totals"]["unit"]["delta"] == "2"
    historical = deepcopy(actual)
    historical["snapshot"]["items"][0]["unit"] = "盒"
    result = compare(command, frozen, historical)
    assert not result["totals"]["unit"]["comparable"]
    assert result["totals"]["unit"]["delta"] is None
    assert any("单位" in gap for gap in result["pairs"][0]["gaps"])


def test_conversion_keeps_selected_rate_and_rejects_stale_rate() -> None:
    command, fixed = fixture()
    fixed["inputs"][0]["payload"]["currency"] = "USD"
    rate = RateDraft.model_validate(
        dict(
            kind="exchange_rate",
            scope_basis="本次计算时点",
            from_currency="USD",
            to_currency="CNY",
            rate="7",
            rate_type="spot",
            source_reference="批准汇率",
            source_line="行2",
            evidence_id=DOCUMENT,
            location="A3",
            as_of="2020-01-01",
            reason="固定汇率时点",
        )
    )
    fixed["inputs"].append(
        dict(
            id=str(RATE),
            record_id=str(RATE),
            version=1,
            current=True,
            source_current=True,
            payload=rate.model_dump(mode="json"),
        )
    )
    command = RollupDraft.model_validate({**command.model_dump(), "rate_ids": [RATE]})
    result = calculate(command, fixed)
    assert result["unit_total"] == "28"
    assert result["lines"][0]["rate_input_id"] == str(RATE)
    fixed["inputs"][1]["source_current"] = False
    result = calculate(command, fixed)
    assert not result["complete"]
    assert result["unit_total"] is None
