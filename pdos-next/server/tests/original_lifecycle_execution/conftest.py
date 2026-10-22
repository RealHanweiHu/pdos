import socket
import sqlite3
import subprocess

import pytest
from sqlalchemy.engine import Engine


@pytest.fixture
def pure_guard(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Pure lifecycle adapter checks forbid DB/network/process effects")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(Engine, "connect", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
