"""Local, side-effect-free contracts for fixed supply/cost calculations."""

import hashlib
import json
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, InvalidOperation, localcontext
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

Text = Annotated[str, Field(min_length=1, max_length=500)]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]


def bounded_decimal(value: Any) -> Decimal:
    if isinstance(value, (bool, float)) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("Use decimal strings, integers or Decimal")
    if isinstance(value, str) and len(value) > 80:
        raise ValueError("Decimal input representation must be bounded")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid decimal input") from exc
    exponent = parsed.as_tuple().exponent
    if not parsed.is_finite() or not isinstance(exponent, int) or abs(exponent) > 32:
        raise ValueError("Decimal input must be finite with a bounded exponent")
    return parsed


Quantity = Annotated[
    Decimal,
    BeforeValidator(bounded_decimal, json_schema_input_type=str | int),
    Field(ge=0, max_digits=24, decimal_places=8),
]
Positive = Annotated[
    Decimal,
    BeforeValidator(bounded_decimal, json_schema_input_type=str | int),
    Field(gt=0, max_digits=24, decimal_places=8),
]
Loss = Annotated[
    Decimal,
    BeforeValidator(bounded_decimal, json_schema_input_type=str | int),
    Field(ge=0, le=1, max_digits=9, decimal_places=8),
]


class FrozenDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    @model_validator(mode="before")
    @classmethod
    def no_binary_floats(cls, value: Any) -> Any:
        def visit(item: Any) -> None:
            kind = type(item)
            if item is None or kind is str or kind is bool or kind is int:
                return
            if isinstance(item, float):
                raise ValueError("Use decimal strings or Decimal, never binary floats")
            if isinstance(item, dict):
                for child in item.values():
                    visit(child)
            elif isinstance(item, (tuple, list)):
                for child in item:
                    visit(child)

        visit(value)
        return value


class SnapshotRef(FrozenDTO):
    source_id: Text
    version: Text
    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    captured_at: datetime
    valid_until: datetime | None = None
    state: Literal["current", "stale", "withdrawn", "unknown"]

    @field_validator("captured_at", "valid_until")
    @classmethod
    def aware_time(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("Snapshot times must include an explicit timezone")
            return value.astimezone(UTC)
        return value


class Issue(FrozenDTO):
    code: Text
    path: Text
    message: Text
    kind: Literal["missing", "conflict", "restriction", "sensitivity"] = "missing"


def issue(code: str, path: str, message: str, kind: str = "missing") -> Issue:
    return Issue(code=code, path=path, message=message, kind=kind)


def source_issues(ref: SnapshotRef, as_of: datetime, path: str) -> list[Issue]:
    problems = []
    if ref.state != "current":
        problems.append(issue("source_not_current", path, f"Source state is {ref.state}"))
    if ref.captured_at > as_of:
        problems.append(issue("future_source", path, "Source was captured after calculation time"))
    if ref.valid_until is not None and as_of >= ref.valid_until:
        problems.append(issue("source_expired", path, "Source validity ended at calculation time"))
    return problems


def sorted_issues(items: list[Issue]) -> tuple[Issue, ...]:
    return tuple(sorted(set(items), key=lambda x: (x.path, x.code, x.message, x.kind)))


def calculation_context(precision: int = 4096):
    # Fresh Context also fixes rounding, exponent bounds and traps inherited from callers.
    return localcontext(Context(prec=precision, rounding=ROUND_HALF_EVEN))


def digest(value: BaseModel) -> str:
    def normalize(item: Any) -> Any:
        if isinstance(item, Decimal):
            text = format(item, "f")
            return (text.rstrip("0").rstrip(".") if "." in text else text) if item else "0"
        if isinstance(item, datetime):
            return item.astimezone(UTC).isoformat()
        if isinstance(item, dict):
            return {key: normalize(child) for key, child in item.items()}
        if isinstance(item, (tuple, list)):
            return [normalize(child) for child in item]
        return item

    encoded = json.dumps(
        normalize(value.model_dump(mode="python")),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
