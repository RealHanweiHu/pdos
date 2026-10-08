"""Private work codec. Auth records are references; passwords are never serialized."""

import base64
import dataclasses
import importlib
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.auth.repository import AuthContext, AuthRepository


def encode(value: Any) -> Any:
    if isinstance(value, AuthContext):
        return {"$auth": [str(value.tenant.id), str(value.user.id), value.user.auth_version]}
    if isinstance(value, Enum):
        return {"$enum": type_name(type(value)), "value": value.value}
    if isinstance(value, UUID):
        return {"$uuid": str(value)}
    if isinstance(value, datetime):
        return {"$datetime": value.isoformat()}
    if isinstance(value, date):
        return {"$date": value.isoformat()}
    if isinstance(value, Decimal):
        return {"$decimal": str(value)}
    if isinstance(value, bytes):
        return {"$bytes": base64.b64encode(value).decode()}
    if isinstance(value, BaseModel):
        return {"$model": type_name(type(value)), "value": encode(value.model_dump())}
    if dataclasses.is_dataclass(value):
        return {
            "$dataclass": type_name(type(value)),
            "value": encode({f.name: getattr(value, f.name) for f in dataclasses.fields(value)}),
        }
    if isinstance(value, Mapping):
        if any(not isinstance(k, str) for k in value):
            raise TypeError("Runtime mappings require string keys")
        return {"$mapping": {k: encode(v) for k, v in value.items()}}
    if isinstance(value, tuple):
        return {"$tuple": [encode(v) for v in value]}
    if isinstance(value, list):
        return [encode(v) for v in value]
    if value is None or isinstance(value, (bool, str, int, float)):
        return value
    if callable(value):
        return {"$event_sink": True}
    raise TypeError(f"Unregistered private-work input type: {type(value).__name__}")


def type_name(cls: Any) -> str:
    if not cls.__module__.startswith("app.") or "." in cls.__qualname__:
        raise TypeError("Only host-owned top-level input/output types can be registered")
    return str(cls.__module__) + ":" + str(cls.__qualname__)


def resolve(name: str, base: Any) -> Any:
    module, symbol = name.split(":")
    if not module.startswith(("app.ai.", "app.contracts.", "app.domain.", "app.auth.")):
        raise ValueError("Unregistered host type")
    cls = getattr(importlib.import_module(module), symbol)
    if base is not None and not issubclass(cls, base):
        raise ValueError("Private-work type does not match its registered category")
    if base is None and not dataclasses.is_dataclass(cls):
        raise ValueError("Private-work dataclass is not registered")
    return cls


def decode(value: Any, *, engine: Any, emit: Any = None) -> Any:
    if isinstance(value, list):
        return [decode(v, engine=engine, emit=emit) for v in value]
    if not isinstance(value, dict):
        return value
    if "$auth" in value:
        tenant, actor, version = value["$auth"]
        ctx = AuthRepository(engine).find_user_context(UUID(actor))
        if (
            ctx is None
            or str(ctx.tenant.id) != tenant
            or ctx.user.auth_version != version
            or not ctx.user.is_active
            or ctx.tenant.status != "active"
        ):
            raise PermissionError("Original requester authority is no longer current")
        return ctx
    if "$uuid" in value:
        return UUID(value["$uuid"])
    if "$datetime" in value:
        return datetime.fromisoformat(value["$datetime"])
    if "$date" in value:
        return date.fromisoformat(value["$date"])
    if "$decimal" in value:
        return Decimal(value["$decimal"])
    if "$bytes" in value:
        return base64.b64decode(value["$bytes"], validate=True)
    if "$event_sink" in value:
        if emit is None:
            raise ValueError("Only the executing host can bind a progress sink")
        return emit
    if "$mapping" in value:
        return {k: decode(v, engine=engine, emit=emit) for k, v in value["$mapping"].items()}
    if "$tuple" in value:
        return tuple(decode(v, engine=engine, emit=emit) for v in value["$tuple"])
    body = decode(value.get("value"), engine=engine, emit=emit)
    if "$model" in value:
        return resolve(value["$model"], BaseModel).model_validate(body)
    if "$dataclass" in value:
        return resolve(value["$dataclass"], None)(**body)
    if "$enum" in value:
        return resolve(value["$enum"], Enum)(body)
    raise ValueError("Invalid private-work encoding")
