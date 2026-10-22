"""Reuse the existing legitimate API-created parent chain; Root alone executes PG."""

from test_builds import configuration  # noqa: F401 -- shared real API fixture
from test_project_first_plan import definition, project  # noqa: F401 -- transitive fixtures

from .fixtures import manufacturing_case  # noqa: F401 -- explicitly synthetic scoped owner
