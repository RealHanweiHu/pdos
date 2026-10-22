"""Register the actual shared S2 source/physical fixture tree, without executing it."""

from quality_execution.fixtures import (  # noqa: F401
    accepted_work,
    known_configuration,
    launch_work,
    operational_work,
    quality_work,
    ready_work,
    results_work,
)

from .fixtures import native_case  # noqa: F401
