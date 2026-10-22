"""Report the actual swallowed quality-read rejection when a coverage fixture fails."""

import pytest

from pdos_next.domain.quality_execution import service
from pdos_next.errors import DomainError


@pytest.fixture(autouse=True)
def truth_diagnostics(monkeypatch):
    for owner, name in ((service, "_result"), (service.policy, "assess")):
        actual = getattr(owner, name)

        def checked(*args, _actual=actual, _name=name, **kwargs):
            try:
                return _actual(*args, **kwargs)
            except DomainError as error:
                print("Actual coverage dependency rejection:", _name, error.payload())
                raise

        monkeypatch.setattr(owner, name, checked)
