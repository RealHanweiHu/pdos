"""Pure in-process HTTP parsing only; real DB and network transports are forbidden."""

import socket

import httpx
import psycopg
import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


@pytest.fixture(autouse=True)
def forbidden_io(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Staged route tests cannot access DB/network")

    for name in ("connect", "raw_connection", "begin"):
        monkeypatch.setattr(Engine, name, forbidden)
    for name in ("execute", "scalar", "scalars", "get", "flush", "commit"):
        monkeypatch.setattr(Session, name, forbidden)
    monkeypatch.setattr(psycopg, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
