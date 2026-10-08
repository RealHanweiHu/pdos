"""Real existing fixture tree. No staged IO interception is installed for Root."""

from build_operational_facts.fixtures import known_configuration, operational_work  # noqa: F401
from test_builds import configuration  # noqa: F401
from test_project_first_plan import definition, project  # noqa: F401

from .fixtures import native_resource_case  # noqa: F401
