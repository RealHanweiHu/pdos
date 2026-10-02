from uuid import UUID

import pytest

from app.domain.ai_meeting_write_monitor import retraction_exceeded, sampled_draft
from tests.test_ai_write_qualification_contract import configuration


def test_sampling_is_stable_and_uses_registered_percentage() -> None:
    ids = [UUID(int=i) for i in range(500)]
    config = configuration(sampling_basis_points=2500)
    selected = [sampled_draft(item, config) for item in ids]
    assert selected == [sampled_draft(item, config) for item in ids]
    assert any(selected) and not all(selected)
    assert all(sampled_draft(item, configuration(sampling_basis_points=10000)) for item in ids)


@pytest.mark.parametrize(
    "total,withdrawn,limit,exceeded",
    [
        (0, 0, 500, False),
        (20, 1, 500, False),
        (19, 1, 500, True),
        (199, 1, 50, True),
        (200, 1, 50, False),
        (1, 1, 0, True),
    ],
)
def test_retraction_integer_boundaries(
    total: int, withdrawn: int, limit: int, exceeded: bool
) -> None:
    assert retraction_exceeded(total, withdrawn, limit) is exceeded


def test_unknown_counts_cannot_silently_pass() -> None:
    with pytest.raises(ValueError):
        retraction_exceeded(1, 2, 500)
