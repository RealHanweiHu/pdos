"""Host TestRun plans, promises and atomic actual launch using the verification kernel."""

# Domain models share the single common registry. Initialize it before child imports.
from pdos_next import models as _registry  # noqa: F401
