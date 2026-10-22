"""Concrete bounded owner traversal; hidden dependencies cannot disappear."""

from dataclasses import dataclass
from datetime import UTC, datetime

import pdos_next.models  # noqa: F401 - complete model registration before runtime imports
from pdos_next import change_controlled_owner as controlled
from pdos_next.change_graph_closure import _fresh_selects, _json, _pending_dependencies
from pdos_next.domain.change_control.rules import digest
from pdos_next.domain.change_execution.graph import OwnerReader
from pdos_next.domain.quality_execution.service import get_issue_for_change
from pdos_next.errors import DomainError
from pdos_next.schemas.change_control.contracts import Node

from .trust import require


def graph_projection(graph):
    return {
        "scope": graph.scope.model_dump(mode="json"),
        "audience": list(graph.audience),
        "roots": sorted(r.identity for r in graph.roots),
        "nodes": sorted(
            (v.model_dump(mode="json") for v in graph.nodes), key=lambda v: str(v["ref"])
        ),
        "edges": sorted(
            [
                (e.origin.identity, e.target.identity, e.relation, e.source.model_dump(mode="json"))
                for e in graph.edges
            ],
            key=lambda v: (v[0], v[1], v[2]),
        ),
    }


def _deadlines(value, at):
    # Current owner material already carries saved authority/security windows.
    # Relevant future professional activations are additionally read by owner.py.
    result = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"valid_from", "valid_until", "expires_at"} and child is not None:
                try:
                    time = (
                        child
                        if isinstance(child, datetime)
                        else datetime.fromisoformat(child.replace("Z", "+00:00"))
                    )
                except (ValueError, TypeError, AttributeError):
                    require(False, "COVERAGE_DEPENDENCY_UNRESOLVED")
                require(time.tzinfo is not None)
                if time > at:
                    result.append(time)
            else:
                result.extend(_deadlines(child, at))
    elif isinstance(value, (list, tuple)):
        for child in value:
            result.extend(_deadlines(child, at))
    return result


@dataclass(frozen=True)
class RegistryBasis:
    projection: dict
    closure: dict
    closure_sha256: str
    sources: tuple
    reads: list
    valid_until: datetime | None


def read_registry(s, ctx, pid, request):
    _pending_dependencies(s)
    with _fresh_selects(s):
        value = _read_registry(s, ctx, pid, request)
    _pending_dependencies(s)
    return value


def _read_registry(s, ctx, pid, request):
    """Only the actual fixed OwnerReader is used, not a registered callback."""
    at = datetime.now(UTC)
    reader = OwnerReader(s, ctx, pid, request.scope, request.audience, get_issue_for_change)
    pending, objects, edges, deadlines = list(request.roots), {}, {}, []
    try:
        while pending:
            ref = pending.pop(0)
            if ref.identity in objects:
                continue
            obj = reader.resolve(ref)
            require(obj.current is True, "COVERAGE_DEPENDENCY_UNRESOLVED")
            objects[ref.identity] = obj
            deadlines.extend(_deadlines(obj.source_basis, at))
            deadlines.extend(_deadlines(obj.view, at))
            for target, relation in reader.links(obj):
                # Unlike ordinary UNKNOWN capture, a hidden child must not be skipped.
                reader.resolve(target)
                key = (ref.identity, target.identity, relation)
                edges[key] = (
                    ref.identity,
                    target.identity,
                    relation,
                    obj.source.model_dump(mode="json"),
                )
                pending.append(target)
    except DomainError as error:
        if error.status == 403:
            raise DomainError("COVERAGE_DEPENDENCY_UNRESOLVED", "依赖闭包未完整核对。") from None
        raise
    nodes = [
        Node(
            ref=o.ref, scope=o.scope, audience=request.audience, source=o.source, label=o.label
        ).model_dump(mode="json")
        for o in objects.values()
    ]
    projection = {
        "scope": request.scope.model_dump(mode="json"),
        "audience": list(request.audience),
        "roots": sorted(r.identity for r in request.roots),
        "nodes": sorted(nodes, key=lambda v: str(v["ref"])),
        "edges": sorted(edges.values(), key=lambda v: (v[0], v[1], v[2])),
    }
    closure = {
        "projection": projection,
        "owners": [
            {
                "ref": o.ref.model_dump(mode="json"),
                "view": o.view,
                "reads": o.reads,
                "source_basis": o.source_basis,
            }
            for _, o in sorted(objects.items())
        ],
    }
    closure = _json(closure)
    return RegistryBasis(
        projection,
        closure,
        digest(closure),
        tuple(o.source for _, o in sorted(objects.items())),
        controlled._reads(*(o.reads for o in objects.values())),
        min(deadlines) if deadlines else None,
    )
