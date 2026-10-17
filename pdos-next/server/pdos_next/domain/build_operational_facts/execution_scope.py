"""One operational scope type shared by facts and public command payloads."""

from decimal import Decimal
from typing import Annotated

from pydantic import BeforeValidator, Field, field_serializer

from pdos_next.engines.supply_cost.common import FrozenDTO, bounded_decimal
from pdos_next.schemas.resource_readiness.contracts import ExecutionWindow

Key = Annotated[str, Field(min_length=1, max_length=160)]
Positive = Annotated[
    Decimal, BeforeValidator(bounded_decimal), Field(gt=0, max_digits=24, decimal_places=8)
]


class OperationalScope(FrozenDTO):
    purpose: Key
    quantity: Positive
    unit: Key
    site: Key
    window: ExecutionWindow

    @field_serializer("quantity")
    def decimal_quantity(self, value: Decimal) -> str:
        text = format(value, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text
