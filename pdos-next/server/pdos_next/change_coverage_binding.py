"""Concrete current coverage binding for captures and named change actions."""

from copy import deepcopy

from pdos_next.errors import DomainError
from pdos_next.schemas.change_control.contracts import GraphSnapshot


def require(ok):
    if not ok:
        raise DomainError("COVERAGE_OWNER_STALE", "固定覆盖依据变化，请重新核对并捕获。", 409)


def stable_basis(value):
    """Only a verified canonical successor may change the current Change header.

    The concrete owner checks ancestry and the unchanged origin/fixed request.
    Coverage Current, source, issuer, graph, clock and publication proof stay exact.
    """
    require(type(value) is dict and type(value.get("binding")) is dict)
    result = deepcopy(value)
    bound = result["binding"]
    require(
        set(bound)
        == {
            "current_id",
            "version_id",
            "revision",
            "origin_version_id",
            "origin_revision",
            "fixed_request",
        }
    )
    for field in ("version_id", "revision"):
        del bound[field]
    return result


def require_saved(previous, current):
    require(stable_basis(previous) == stable_basis(current.source_basis))


def same_capture_basis(previous, current):
    left, right = deepcopy(previous), deepcopy(current)
    if "coverage" in left or "coverage" in right:
        require("coverage" in left and "coverage" in right)
        left["coverage"] = stable_basis(left["coverage"])
        right["coverage"] = stable_basis(right["coverage"])
    return left == right


def read_graph(s, ctx, pid, *, request, purpose, graph, saved=None, optional=False):
    """A missing owner permits a new UNKNOWN capture; a saved proof never does."""
    from pdos_next.domain.change_coverage_owner import owner

    require(type(graph) is GraphSnapshot)
    positive = any(value.status != "unknown" for value in graph.coverage) or any(
        value.status != "unknown" for value in graph.path_applicability
    )
    require(not positive or saved is not None)
    if optional and saved is None:
        with owner._fresh_selects(s), owner._people_fence(s):
            owner.quiet(s)
            _, fact = owner.pointer(s, ctx, pid, request.scope, request.id, purpose)
        if fact is None:
            return None
    # A present but stale/unconfigured owner must reject, never fall back to UNKNOWN.
    current = owner.read(s, ctx, pid, change_id=request.id, purpose=purpose, graph=graph)
    if saved is not None:
        require_saved(saved, current)
        require(current.coverage == graph.coverage)
        require(current.path_applicability == graph.path_applicability)
    return current


def covered_graph(graph, current):
    if current is None:
        return graph
    from pdos_next.domain.change_coverage_owner.owner import CoverageRead

    require(type(current) is CoverageRead)
    return GraphSnapshot.model_validate(
        {
            **graph.model_dump(mode="python"),
            "coverage": current.coverage,
            "path_applicability": current.path_applicability,
        }
    )


def refresh_graph(s, ctx, pid, current, *, request, purpose, graph):
    from pdos_next.domain.change_coverage_owner import owner

    value = owner.refresh(s, ctx, pid, current, change_id=request.id, purpose=purpose, graph=graph)
    require(value.coverage == graph.coverage)
    require(value.path_applicability == graph.path_applicability)
    return value


def read_retained_graph(s, ctx, pid, *, request, purpose, graph, saved):
    from pdos_next.domain.change_coverage_owner import owner

    value = owner.read_retained(
        s, ctx, pid, change_id=request.id, purpose=purpose, graph=graph, saved=saved
    )
    require_saved(saved, value)
    return value


def refresh_retained_graph(s, ctx, pid, previous, *, request, purpose, graph):
    from pdos_next.domain.change_coverage_owner import owner

    return owner.refresh_retained(
        s, ctx, pid, previous, change_id=request.id, purpose=purpose, graph=graph
    )
