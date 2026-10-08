"""This package uses fake transports only, regardless of caller environment."""

import socket

import pytest
from sqlalchemy.engine import Engine


@pytest.fixture(autouse=True)
def forbid_network_and_database(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Provider pure checks forbid network and database connections")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(Engine, "connect", forbidden)
