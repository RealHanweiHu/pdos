"""Scope-only pure checks must never connect to PostgreSQL or a socket."""

import socket

import pytest
from sqlalchemy import Engine


@pytest.fixture(autouse=True)
def deny_connections(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("This pure scope check cannot connect")

    monkeypatch.setattr(Engine, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
