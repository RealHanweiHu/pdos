"""Explicit v1 conversion range; no guessed package, density or currency conversion."""

from decimal import Decimal
from types import MappingProxyType

# dimension, number of canonical units in one input unit
UNITS = MappingProxyType(
    {
        "ea": ("count", Decimal(1)),
        "pcs": ("count", Decimal(1)),
        "个": ("count", Decimal(1)),
        "件": ("count", Decimal(1)),
        "台": ("count", Decimal(1)),
        "kg": ("mass", Decimal(1)),
        "g": ("mass", Decimal("0.001")),
        "mg": ("mass", Decimal("0.000001")),
        "m": ("length", Decimal(1)),
        "cm": ("length", Decimal("0.01")),
        "mm": ("length", Decimal("0.001")),
        "L": ("volume", Decimal(1)),
        "mL": ("volume", Decimal("0.001")),
        "h": ("time", Decimal(3600)),
        "min": ("time", Decimal(60)),
        "s": ("time", Decimal(1)),
    }
)


def conversion(from_unit: str | None, to_unit: str | None) -> Decimal | None:
    left, right = UNITS.get(from_unit or ""), UNITS.get(to_unit or "")
    if left is None or right is None or left[0] != right[0]:
        return None
    return left[1] / right[1]
