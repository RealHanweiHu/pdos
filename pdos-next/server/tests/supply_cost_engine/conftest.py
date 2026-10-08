"""Local pure DTO fixtures; run with --confcutdir=tests/supply_cost_engine."""

from copy import deepcopy

import pytest

from .helpers import bom_item, pool, price, ref


@pytest.fixture
def basis():
    return dict(
        build=dict(build_id="build", ref=ref("build"), quantity="5", product_unit="ea"),
        bom=dict(
            ref=ref("bom"), engineering_configuration=ref("configuration"), items=[bom_item()]
        ),
    )


@pytest.fixture
def coverage(basis):
    return dict(
        as_of="2026-01-02T00:00:00Z",
        basis=deepcopy(basis),
        supply_snapshot=ref("availability"),
        supply_scope_complete=True,
        pools=[pool()],
    )


@pytest.fixture
def cost(basis):
    return dict(
        as_of="2026-01-02T00:00:00Z",
        basis=deepcopy(basis),
        scope=dict(
            currency="USD",
            tax_basis="exclusive",
            freight_basis="included",
            coverage="materials_only",
            rate_purpose="budget",
            max_rate_age_days=7,
            nre_policy="excluded",
            assumptions=["Explicit materials-only estimate"],
        ),
        material_prices=[dict(bom_item_id="a", price_id="price")],
        prices=[price()],
    )
