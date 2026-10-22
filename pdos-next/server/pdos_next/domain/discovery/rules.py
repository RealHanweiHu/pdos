"""Deterministic comparison; no unit conversion, latest-wins or maturity inference."""

import hashlib
import json
from decimal import Decimal
from uuid import UUID

from pdos_next.schemas.discovery.contracts import Conflict, Research


def digest(value) -> str:
    def canonical(item):
        if hasattr(item, "model_dump"):
            return item.model_dump(mode="json")
        if isinstance(item, UUID):
            return str(item)
        if isinstance(item, Decimal):
            return str(item.normalize())
        if isinstance(item, (tuple, list)):
            return [canonical(v) for v in item]
        if isinstance(item, dict):
            return {k: canonical(v) for k, v in item.items()}
        return item

    value = canonical(value)
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def groups(research: Research):
    result = {}
    for stored in research.observations:
        result.setdefault(stored.observation.key, []).append(stored)
    return result


def conflicts(research: Research) -> tuple[Conflict, ...]:
    result = []
    for key, entries in sorted(groups(research).items()):
        if len(entries) < 2:
            continue
        reasons = []
        observations = [e.observation for e in entries]
        for field in ("kind", "statement"):
            if len({getattr(o, field) for o in observations}) > 1:
                reasons.append(field)
        specs = [o.spec for o in observations if o.spec]
        if len(specs) == len(observations):
            for field in type(specs[0]).model_fields:
                if len({digest(getattr(s, field)) for s in specs}) > 1:
                    reasons.append(field)
        if reasons:
            result.append(
                Conflict(
                    key=key,
                    observation_ids=tuple(o.id for o in observations),
                    reasons=tuple(reasons),
                )
            )
    return tuple(result)


def missing_categories(research: Research, required: tuple[str, ...]) -> tuple[str, ...]:
    present = {item.category for item in research.items}
    return tuple(sorted(set(required) - present))


def spec_unknowns(spec) -> list[str]:
    fields = {"number": ("value",), "range": ("lower", "upper"), "text": ("text",)}
    gaps = [name for name in fields[spec.value_type] if getattr(spec, name) is None]
    if spec.value_type != "text" and not spec.unit:
        gaps.append("unit")
    if not spec.test_conditions:
        gaps.append("test_conditions")
    for name in ("method", "applicability", "acceptance_criterion"):
        if not getattr(spec, name):
            gaps.append(name)
    return gaps
