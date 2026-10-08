"""Hard no-DB/no-network boundary; owner IO replacements are explicit in tests."""

import socket

import httpx
import psycopg
import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


@pytest.fixture(autouse=True)
def forbidden_io(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Pure candidate must not access DB/network")

    for name in ("connect", "raw_connection", "begin"):
        monkeypatch.setattr(Engine, name, forbidden)
    for name in ("execute", "scalar", "scalars", "get", "flush", "commit"):
        monkeypatch.setattr(Session, name, forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(psycopg, "connect", forbidden)
    monkeypatch.setattr(httpx.Client, "request", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "request", forbidden)
