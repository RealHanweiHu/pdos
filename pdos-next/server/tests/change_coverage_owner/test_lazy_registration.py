"""Fresh interpreter model registration against actual service, with no DB/network."""

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("entry", ["owner", "importer", "registry", "exports"])
def test_fresh_runtime_entry_registers_models_before_controlled_store(entry):
    script = r"""
import importlib
import sys
from unittest.mock import patch
from sqlalchemy.engine import Engine

def forbidden(*args, **kwargs):
    raise AssertionError("Runtime import must not open the database")

with patch.object(Engine, 'connect', forbidden), patch.object(Engine, 'raw_connection', forbidden):
    name = 'pdos_next.domain.change_coverage_owner'
    if sys.argv[1] == 'exports':
        package = importlib.import_module(name)
        for exported in package.__all__:
            assert getattr(package, exported) is not None
    else:
        assert importlib.import_module(name + '.' + sys.argv[1])
    from pdos_next.models import Base
    tables = {'controlled_change_coverage_facts', 'controlled_change_coverage_currents'}
    assert tables <= set(Base.metadata.tables)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, entry],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_actual_service_first_child_model_registration_is_lazy():
    script = r"""
import importlib
import importlib.abc
import importlib.util
import socket
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import httpx
import psycopg
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

def forbidden(*args, **kwargs):
    raise AssertionError("Fresh registration check prohibits DB/network IO")

with ExitStack() as stack:
    for owner, method in (
        (Engine, "connect"), (Engine, "raw_connection"), (Session, "execute"),
        (Session, "connection"), (Session, "commit"), (Session, "flush"),
        (psycopg, "connect"), (socket.socket, "connect"),
        (socket.socket, "connect_ex"), (socket, "getaddrinfo"),
        (socket, "create_connection"), (httpx.Client, "request"),
        (httpx.AsyncClient, "request"),
    ):
        stack.enter_context(patch.object(owner, method, forbidden))
    name = "pdos_next.domain.change_coverage_owner"
    common = importlib.import_module("pdos_next.service")
    models = importlib.import_module(name + ".models")
    assert common.Context and common.digest
    assert name + ".owner" not in sys.modules
    assert name + ".importer" not in sys.modules
    tables = {"controlled_change_coverage_facts", "controlled_change_coverage_currents"}
    assert tables <= set(models.Base.metadata.tables)
    from pdos_next.domain.change_coverage_owner import owner, importer, trust, CoverageMaterial
    assert owner.read and importer.trusted_import and trust.configure and CoverageMaterial
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
