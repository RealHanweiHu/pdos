"""Actual module checks; owner IO substitutes cannot establish SQL qualification."""

import socket

import pytest
from sqlalchemy.engine import Engine


@pytest.fixture(autouse=True)
def no_io(monkeypatch):
    def reject(*args, **kwargs):
        pytest.fail("This pure check must not open a DB or network connection")

    monkeypatch.setattr(Engine, "connect", reject)
    monkeypatch.setattr(Engine, "raw_connection", reject)
    monkeypatch.setattr(socket, "create_connection", reject)
