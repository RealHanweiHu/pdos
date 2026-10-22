"""Pure real-module boundaries. Database owners and qualification are substituted."""

import psycopg
import pytest
from sqlalchemy.engine import Engine
from test_fingerprint_compatibility import materials  # noqa: F401 -- reuse actual full fixture

from .harness import h  # noqa: F401 -- local pure owner fixture
from .test_stage_v2 import staging  # noqa: F401 -- local pure staging fixture


@pytest.fixture(autouse=True)
def forbid_connections(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Resource dependency pure checks must not connect to a database")

    monkeypatch.setattr(Engine, "connect", forbidden)
    monkeypatch.setattr(Engine, "raw_connection", forbidden)
    monkeypatch.setattr(psycopg, "connect", forbidden)
    monkeypatch.setattr(psycopg.Connection, "connect", forbidden)
