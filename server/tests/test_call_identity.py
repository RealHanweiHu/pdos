from collections.abc import Callable
from uuid import UUID, uuid4

import pytest

from app.ai.call_identity import ModelCallSlot, model_call_id


def test_stable_identity_survives_serialization_and_has_distinct_server_slots() -> None:
    run = uuid4()
    ids = {slot: model_call_id(run, slot) for slot in ModelCallSlot}
    assert len(set(ids.values())) == len(ModelCallSlot)
    for slot, identity in ids.items():
        assert model_call_id(UUID(str(run)), slot) == identity
        assert model_call_id(uuid4(), slot) != identity


@pytest.mark.parametrize(
    "run,slot",
    [
        (None, ModelCallSlot.EVENT_ASSESSMENT),
        ("external-run", ModelCallSlot.EVENT_ASSESSMENT),
        (uuid4(), "event_assessment"),
        (uuid4(), "invented"),
    ],
)
def test_identity_requires_persisted_run_and_server_slot(run: object, slot: object) -> None:
    # Invoke the runtime boundary with deliberately invalid argument types.
    boundary: Callable[..., UUID] = model_call_id
    with pytest.raises(ValueError):
        boundary(run, slot)
