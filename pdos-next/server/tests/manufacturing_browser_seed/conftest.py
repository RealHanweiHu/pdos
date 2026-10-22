"""Import actual setup and its complete registered model tree, including when staged."""

import importlib.util
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url


def _actual_server():
    for parent in Path(__file__).resolve().parents:
        for candidate in (parent, parent / "server"):
            if (candidate / "pdos_next" / "models.py").is_file() and (
                candidate / "tests" / "conftest.py"
            ).is_file():
                return candidate
    raise RuntimeError("Actual server fixtures were not found")


ACTUAL_SERVER = _actual_server()
PDOS_NEXT_ROOT = ACTUAL_SERVER.parent
ACTUAL_TESTS = ACTUAL_SERVER / "tests"
sys.path.insert(0, str(ACTUAL_TESTS))
sys.path.insert(0, str(ACTUAL_SERVER))

# This canonical module registers the entire actual child-table tree. Import it first.
from pdos_next import models as _actual_registered_models  # noqa: E402

assert (
    Path(_actual_registered_models.__file__).resolve()
    == (ACTUAL_SERVER / "pdos_next" / "models.py").resolve()
)

_spec = importlib.util.spec_from_file_location(
    "_pdos_wave28_actual_shared_test_setup", ACTUAL_TESTS / "conftest.py"
)
if _spec is None or _spec.loader is None:
    raise RuntimeError("Actual shared fixture loader is unavailable")
_shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_shared)
engines = _shared.engines
setup = _shared.setup

from manufacturing_preparation_transactions.fixtures import manufacturing_case  # noqa: E402,F401
from test_builds import configuration  # noqa: E402,F401
from test_project_first_plan import definition, project  # noqa: E402,F401


@pytest.fixture(scope="session", autouse=True)
def browser_seed_authorization():
    if os.environ.get("PDOS_MANUFACTURING_BROWSER_SEED") != "1":
        pytest.skip("Browser seed requires its explicit new-path host invocation")
    output = Path(os.environ["PDOS_MANUFACTURING_BROWSER_SEED_PATH"])
    local = (PDOS_NEXT_ROOT / ".local").resolve()
    if (
        not output.is_absolute()
        or output.parent.resolve() != local
        or not output.name.startswith("wave28-manufacturing-browser-seed-")
        or output.suffix != ".json"
        or output.exists()
        or output.is_symlink()
    ):
        raise RuntimeError("Use a fresh explicit private seed path under pdos-next/.local")
    urls = [
        make_url(os.environ[key])
        for key in ("TEST_DATABASE_URL", "DATABASE_URL", "AUTH_DATABASE_URL")
    ]
    expected_port = int(os.environ["TEST_DATABASE_PORT"])
    if not os.environ.get("TEST_DATABASE_MARKER"):
        raise RuntimeError("Explicit independent test marker is required")
    for url in urls:
        if (
            url.drivername != "postgresql+psycopg"
            or url.host not in {"127.0.0.1", "localhost"}
            or url.port != expected_port
            or url.database != "pdos_test"
            or url.query
            or url.port in {57432, 55432, 55433, 55434, 55435, 57439, 57441}
        ):
            raise RuntimeError("All seed engines must use the explicit isolated test target")
    return output
