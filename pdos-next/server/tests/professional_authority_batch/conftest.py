"""Pure offline decoder checks never reach business or infrastructure IO."""

import socket
import subprocess

import httpx
import psycopg
import pytest
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session


def forbidden(*args, **kwargs):
    raise AssertionError("Professional batch pure tests prohibit external IO")


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    for target, name in (
        (socket, "getaddrinfo"),
        (socket, "create_connection"),
        (socket.socket, "connect"),
        (socket.socket, "connect_ex"),
        (subprocess, "run"),
        (subprocess, "Popen"),
        (Engine, "connect"),
        (Engine, "raw_connection"),
        (Connection, "execute"),
        (Connection, "exec_driver_sql"),
        (Session, "execute"),
        (Session, "connection"),
        (Session, "flush"),
        (Session, "commit"),
        (httpx.Client, "request"),
        (httpx.AsyncClient, "request"),
        (psycopg, "connect"),
    ):
        monkeypatch.setattr(target, name, forbidden)
