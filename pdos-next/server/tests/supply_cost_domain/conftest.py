"""Only pure local fixtures; run using --confcutdir=tests/supply_cost_domain."""

import pytest

from .helpers import bound_demand, cost_inputs, supply


@pytest.fixture
def bound():
    return bound_demand()


@pytest.fixture
def snapshot(bound):
    return supply(bound)


@pytest.fixture
def costs(bound):
    return cost_inputs(bound)
