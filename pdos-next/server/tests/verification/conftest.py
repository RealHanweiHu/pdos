"""Run with --confcutdir=tests/verification; never load the repository DB fixture."""

import pytest

from pdos_next.domain.verification.ports import Ports

from .helpers import FakeBuilds, FakeCommands, FakeEvidence, FakeSamples


@pytest.fixture
def host():
    return Ports(
        commands=FakeCommands(), builds=FakeBuilds(), evidence=FakeEvidence(),
        samples=FakeSamples(),
    )
