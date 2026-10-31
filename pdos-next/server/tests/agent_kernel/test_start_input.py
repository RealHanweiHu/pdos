"""Short natural-language messages work; empty or oversized requests stay invalid."""

import pytest
from pdos_next.agent_kernel.api import StartInput
from pydantic import ValidationError


@pytest.mark.parametrize("goal", ["你好", "好", "  你好\n"])
def test_short_messages_are_accepted(goal):
    assert StartInput(goal=goal, idempotency_key="short-message").goal == goal.strip()


@pytest.mark.parametrize("goal", ["", " \n\t", "字" * 8001])
def test_blank_and_oversized_messages_are_rejected(goal):
    with pytest.raises(ValidationError):
        StartInput(goal=goal, idempotency_key="short-message")
