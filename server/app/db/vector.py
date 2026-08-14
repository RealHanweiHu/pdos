"""Minimal SQLAlchemy type support for pgvector without leaking vectors to API models."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from sqlalchemy.dialects.postgresql.base import ischema_names
from sqlalchemy.types import UserDefinedType


class Vector(UserDefinedType[list[float]]):
    """PostgreSQL pgvector column with bounded text serialization."""

    cache_ok = True

    def get_col_spec(self, **kw: Any) -> str:  # noqa: ARG002
        return "VECTOR"

    @property
    def python_type(self) -> type[list[float]]:
        return list

    def bind_processor(self, dialect: Any) -> Callable[[Sequence[float] | None], str | None]:  # noqa: ARG002
        def process(value: Sequence[float] | None) -> str | None:
            if value is None:
                return None
            return "[" + ",".join(format(float(item), ".17g") for item in value) + "]"

        return process

    def result_processor(
        self,
        dialect: Any,  # noqa: ARG002
        coltype: Any,  # noqa: ARG002
    ) -> Callable[[object], list[float] | None]:
        def process(value: object) -> list[float] | None:
            if value is None:
                return None
            if isinstance(value, list):
                return [float(item) for item in value]
            parsed = json.loads(str(value))
            if not isinstance(parsed, list):
                raise ValueError("invalid pgvector value")
            return [float(item) for item in parsed]

        return process


# SQLAlchemy does not bundle pgvector reflection. Register the extension type so
# Alembic drift checks see the same type instead of degrading to NullType.
ischema_names.setdefault("vector", Vector)
