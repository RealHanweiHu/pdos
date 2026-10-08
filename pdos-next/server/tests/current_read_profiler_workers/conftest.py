"""The profiler pure suite has no database or network connections."""

import socket
import sys
from pathlib import Path

import psycopg
import pytest
from sqlalchemy.engine import Engine

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))


@pytest.fixture(autouse=True)
def forbid_connections(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("Pure profiler checks prohibit database and network access")

    monkeypatch.setattr(Engine, "connect", denied)
    monkeypatch.setattr(Engine, "raw_connection", denied)
    monkeypatch.setattr(psycopg, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
