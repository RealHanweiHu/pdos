"""This package permits only synthetic, temporary local-file effects."""

import socket
import sqlite3
import subprocess

import pytest
from sqlalchemy.engine import Engine


@pytest.fixture(autouse=True)
def forbid_external_effects(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Object journal tests forbid network, database and subprocess effects")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(Engine, "connect", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
