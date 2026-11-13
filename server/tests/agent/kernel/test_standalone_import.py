"""D303: kernel modules import on their own and leave the same schema as the registry.

Each module runs first in a fresh interpreter. These six used to stop on a circular
import because the registry loads table modules that needed ``kernel.models`` complete.
"""

import os
import subprocess
import sys
from functools import cache
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[3]

FINGERPRINT = """
import hashlib, importlib, sys
importlib.import_module(sys.argv[1])
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateIndex, CreateTable
from pdos_next.core.models import Base
configure_mappers()
dialect = postgresql.dialect()
parts = []
for table in sorted(Base.metadata.tables.values(), key=lambda table: table.name):
    parts.append(str(CreateTable(table).compile(dialect=dialect)))
    parts += sorted(str(CreateIndex(index).compile(dialect=dialect)) for index in table.indexes)
print(len(Base.metadata.tables), hashlib.sha256("\\n".join(parts).encode()).hexdigest())
"""


@cache
def fingerprint(module):
    result = subprocess.run(
        [sys.executable, "-c", FINGERPRINT, module],
        cwd=SERVER,
        env={**os.environ, "PYTHONPATH": str(SERVER)},
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    return result.stdout.strip()


@pytest.mark.parametrize(
    "module",
    [
        "pdos_next.agent.kernel.models",
        "pdos_next.agent.kernel.api",
        "pdos_next.agent.kernel.context_observability",
        "pdos_next.agent.kernel.policy",
        "pdos_next.agent.kernel.project_work_task_context",
        "pdos_next.agent.kernel.session_bindings",
    ],
)
def test_kernel_module_imported_first_leaves_the_registry_schema(module):
    assert fingerprint(module) == fingerprint("pdos_next.core.models")
