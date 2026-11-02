"""Reuse the existing legitimate API-created parent chain; Root alone executes PG."""

from builds.test_builds import configuration  # noqa: F401 -- shared real API fixture
from projects.test_project_first_plan import (  # noqa: F401 -- transitive fixtures
    definition,
    project,
)

from .fixtures import manufacturing_case  # noqa: F401 -- explicitly synthetic scoped owner
