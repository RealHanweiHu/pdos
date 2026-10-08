"""Quality partition equality must not depend on rounded repeating conversions."""

from decimal import localcontext

import pytest

from pdos_next.domain.supply_cost import canonical_supply
from pdos_next.schemas.supply_cost.dto import QualityRestriction

from .helpers import pool, ref, supply


@pytest.mark.parametrize(
    "pool_quantity,pool_unit,restricted_quantity,restricted_unit",
    [("1", "min", "60", "s"), ("1", "h", "3600", "s"), ("1", "kg", "1000", "g")],
)
def test_equal_quality_partition_uses_exact_canonical_units(
    bound, pool_quantity, pool_unit, restricted_quantity, restricted_unit
):
    physical = pool(quantity=pool_quantity, unit=pool_unit)
    release = QualityRestriction(
        record_id="release",
        ref=ref("release"),
        pool=physical.key,
        quality="released",
        availability="available",
        affected_quantity=restricted_quantity,
        unit=restricted_unit,
        note="Exact whole-pool partition release",
    )
    with localcontext() as context:
        context.prec = 2
        result = canonical_supply(supply(bound, pools=(physical,), restrictions=(release,)))
    assert result.pools == (physical,)
    assert result.restrictions == (release,)
