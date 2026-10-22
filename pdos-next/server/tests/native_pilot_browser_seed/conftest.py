"""Use the actual native PG seed; ordinary collection never exports credentials."""

import os
import stat
from pathlib import Path

import pytest
from native_pilot_transactions.fixtures import native_case  # noqa: F401
from quality_execution.fixtures import (  # noqa: F401
    accepted_work,
    known_configuration,
    launch_work,
    operational_work,
    quality_work,
    ready_work,
    results_work,
)
from sqlalchemy.engine import make_url


@pytest.fixture(scope="session", autouse=True)
def browser_seed_authorization():
    if os.environ.get("PDOS_NATIVE_PILOT_BROWSER_SEED") != "1":
        pytest.skip("Native Pilot browser seed requires explicit local host invocation")
    directory = Path(os.environ["PDOS_NATIVE_PILOT_BROWSER_DIR"])
    if (
        not directory.is_absolute()
        or directory.resolve() != directory
        or ".local" not in directory.parts
        or directory.is_symlink()
    ):
        raise RuntimeError("Use an explicit absolute private directory under the local .local root")
    directory.mkdir(mode=0o700, parents=False, exist_ok=True)
    if not directory.is_dir() or stat.S_IMODE(directory.stat().st_mode) & 0o077:
        raise RuntimeError("Browser seed directory must be private to its local owner")
    if any(
        (directory / name).exists() or (directory / name).is_symlink()
        for name in ("seed.json", "finish")
    ):
        raise RuntimeError("Use a fresh seed directory without seed.json or finish")
    port = int(os.environ["PDOS_NATIVE_PILOT_BROWSER_PORT"])
    database_port = int(os.environ["TEST_DATABASE_PORT"])
    if not 1024 <= port <= 65535 or port == database_port:
        raise RuntimeError("Choose an explicit unused local API port, separate from PostgreSQL")
    if not os.environ.get("TEST_DATABASE_MARKER"):
        raise RuntimeError("The explicit independent test marker is required")
    for key in ("TEST_DATABASE_URL", "DATABASE_URL", "AUTH_DATABASE_URL", "DISPATCH_DATABASE_URL"):
        target = make_url(os.environ[key])
        if (
            target.drivername != "postgresql+psycopg"
            or target.host not in {"127.0.0.1", "localhost"}
            or target.port != database_port
            or target.database != "pdos_test"
            or target.query
        ):
            raise RuntimeError(
                "All browser seed engines must use the explicit isolated test target"
            )
    return directory, port
