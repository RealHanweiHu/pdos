import pytest

from pdos_next.domain.manufacturing_trials.read_models import pilot_reading
from pdos_next.errors import DomainError

from .helpers import create_pilot, prepare, record


def test_current_observation_and_historical_readiness_are_separate():
    handler, commands, _, pilot = create_pilot()
    empty = pilot_reading(pilot, ())
    assert empty.latest is None and empty.current_preparation is None
    value = record(pilot)
    handler.execute(prepare(handler, commands, value, "npi.pilot.result.record", pilot.id), value)
    current = commands.pilots[pilot.id]
    reading = pilot_reading(current, tuple(commands.observations.values()))
    assert reading.latest.id == value.observation_id
    assert reading.yield_scope == value.scope
    assert reading.current_preparation is None
    assert reading.preparation_at_creation.state == "UNKNOWN"
    with pytest.raises(DomainError) as error:
        pilot_reading(current, ())
    assert error.value.reason == "INCOMPLETE_HISTORY"


def test_history_duplicate_is_not_counted_twice():
    handler, commands, _, pilot = create_pilot()
    value = record(pilot)
    handler.execute(prepare(handler, commands, value, "npi.pilot.result.record", pilot.id), value)
    observation = commands.observations[value.observation_id]
    with pytest.raises(DomainError) as error:
        pilot_reading(commands.pilots[pilot.id], (observation, observation))
    assert error.value.reason == "DUPLICATE_HISTORY"
