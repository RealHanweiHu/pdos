"""Offline substitutes cannot establish real SQL, qualifications or G3 approval."""

import socket

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


@pytest.fixture(autouse=True)
def no_io(monkeypatch):
    def reject(*args, **kwargs):
        pytest.fail("Closure pure tests may not execute SQL or connect to DB/network")

    monkeypatch.setattr(Engine, "connect", reject)
    monkeypatch.setattr(Engine, "raw_connection", reject)
    monkeypatch.setattr(Session, "execute", reject)
    monkeypatch.setattr(socket, "create_connection", reject)
