"""Stable business time for functional cases that do not exercise deadlines.

The real T1 expiry policy remains covered with an advancing server clock. Host
suspension must not turn an unrelated immutability/context test into expiry QA.
"""

import pytest

from pdos_next.clock import now, using_clock


@pytest.fixture
def confirmation_clock():
    instant = now()
    with using_clock(lambda: instant):
        yield instant
