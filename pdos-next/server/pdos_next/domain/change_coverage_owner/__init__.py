"""Lazy server-private exports; registering models must not load runtime services."""

from importlib import import_module

_EXPORTS = {
    "CoverageImport": ("schemas", "CoverageImport"),
    "CoverageIssuer": ("trust", "CoverageIssuer"),
    "CoverageMaterial": ("schemas", "CoverageMaterial"),
    "CoverageRead": ("owner", "CoverageRead"),
    "OriginalApproval": ("schemas", "OriginalApproval"),
    "configure": ("trust", "configure"),
    "disable": ("trust", "disable"),
    "inspect_basis": ("owner", "inspect_basis"),
    "read": ("owner", "read"),
    "refresh": ("owner", "refresh"),
    "trusted_import": ("importer", "trusted_import"),
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, attribute = _EXPORTS[name]
    return getattr(import_module(f"{__name__}.{module}"), attribute)
