"""Actual package pure checks; prohibit all real database/network access."""

import socket

import httpx
import psycopg
import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


def forbidden(*args, **kwargs):
    raise AssertionError("Coverage owner pure checks prohibit database/network IO")


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    for cls, method in (
        (Engine, "connect"),
        (Engine, "raw_connection"),
        (Session, "execute"),
        (Session, "connection"),
        (Session, "commit"),
        (Session, "flush"),
        (httpx.Client, "request"),
        (httpx.AsyncClient, "request"),
        (socket.socket, "connect"),
        (socket.socket, "connect_ex"),
    ):
        monkeypatch.setattr(cls, method, forbidden)
    monkeypatch.setattr(psycopg, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
