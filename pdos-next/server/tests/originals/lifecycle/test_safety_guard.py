import socket
import sqlite3
import subprocess

import pytest
from sqlalchemy.engine import Engine


@pytest.mark.parametrize(
    "effect",
    [
        lambda: socket.create_connection(("127.0.0.1", 1)),
        lambda: sqlite3.connect(":memory:"),
        lambda: Engine.connect(None),
        lambda: subprocess.Popen(["true"]),
    ],
)
def test_external_effects_are_explicitly_forbidden(effect):
    with pytest.raises(AssertionError, match="forbid network, database and subprocess"):
        effect()


@pytest.mark.parametrize("method", ["connect", "connect_ex"])
def test_socket_methods_are_also_forbidden(method):
    with socket.socket() as sock, pytest.raises(AssertionError, match="forbid network"):
        getattr(sock, method)(("127.0.0.1", 1))
