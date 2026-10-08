"""Strict, versioned JSON codecs. Exact reference keys are internal persistence only."""

from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from types import UnionType
from typing import Union, get_args, get_origin, get_type_hints
from uuid import UUID

from pdos_next.original_lifecycle.types import (
    LifecycleFailure,
    LifecycleIntent,
    OriginalState,
    OrphanCandidate,
    aware,
)


def _invalid():
    raise LifecycleFailure("LIFECYCLE_DOCUMENT_INVALID", "生命周期持久记录类型或绑定无效。")


def _encode(value):
    if is_dataclass(value):
        value.__post_init__()
        return {f.name: _encode(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, datetime):
        aware(value)
        return value.astimezone(UTC).isoformat(timespec="microseconds")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    if value is None or type(value) in (str, int, bool):
        return value
    _invalid()


def _decode(kind, value, depth=0):
    if depth > 16:
        _invalid()
    origin, args = get_origin(kind), get_args(kind)
    if origin in (Union, UnionType):
        for choice in args:
            try:
                return _decode(choice, value, depth + 1)
            except (LifecycleFailure, ValueError, TypeError):
                pass
        _invalid()
    if kind is type(None):
        if value is not None:
            _invalid()
        return None
    if kind in (str, int, bool):
        if type(value) is not kind:
            _invalid()
        return value
    if kind is UUID:
        if type(value) is not str:
            _invalid()
        parsed = UUID(value)
        if str(parsed) != value:
            _invalid()
        return parsed
    if kind is datetime:
        if type(value) is not str or len(value) > 64:
            _invalid()
        parsed = datetime.fromisoformat(value)
        aware(parsed)
        return parsed.astimezone(UTC)
    if origin is tuple:
        if type(value) is not list or len(value) > 100:
            _invalid()
        return tuple(_decode(args[0], item, depth + 1) for item in value)
    if isinstance(kind, type) and issubclass(kind, Enum):
        if type(value) is not str:
            _invalid()
        return kind(value)
    if is_dataclass(kind):
        names = {f.name for f in fields(kind)}
        if type(value) is not dict or set(value) != names:
            _invalid()
        hints = get_type_hints(kind)
        return kind(**{name: _decode(hints[name], value[name], depth + 1) for name in names})
    _invalid()


def _dump(value, kind, name):
    if not isinstance(value, kind):
        _invalid()
    try:
        data = {"schema_version": 1, "kind": name, "value": _encode(value)}
        _load(data, kind, name)
        return data
    except (ValueError, TypeError, AttributeError):
        _invalid()


def _load(document, kind, name):
    try:
        if type(document) is not dict or set(document) != {"schema_version", "kind", "value"}:
            _invalid()
        if type(document["schema_version"]) is not int or document["schema_version"] != 1:
            _invalid()
        if document["kind"] != name:
            _invalid()
        return _decode(kind, document["value"])
    except (ValueError, TypeError, AttributeError, KeyError):
        _invalid()


def encode_state(value: OriginalState) -> dict:
    return _dump(value, OriginalState, "original_state")


def decode_state(document: dict) -> OriginalState:
    return _load(document, OriginalState, "original_state")


def encode_candidate(value: OrphanCandidate) -> dict:
    return _dump(value, OrphanCandidate, "orphan_candidate")


def decode_candidate(document: dict) -> OrphanCandidate:
    return _load(document, OrphanCandidate, "orphan_candidate")


def encode_intent(value: LifecycleIntent) -> dict:
    return _dump(value, LifecycleIntent, "lifecycle_intent")


def decode_intent(document: dict) -> LifecycleIntent:
    return _load(document, LifecycleIntent, "lifecycle_intent")
