"""Exact impact closure extended only by actual approved native successor objects."""

from pdos_next.change_graph_closure import (
    VERSION,
    ClosureRead,
    _fresh_selects,
    _json,
    _reader,
    _reads,
    _require,
    _runtime,
    _same_reader,
    _scope,
    approved_projection,
    closure_stamp,
)
from pdos_next.clock import deadline_current, now
from pdos_next.contracts import Command
from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow, _uow
from pdos_next.domain.change_control.rules import digest
from pdos_next.domain.change_execution import graph as graph_owner
from pdos_next.schemas.change_control.contracts import GraphSnapshot
from pdos_next.service import digest as caller_digest


def native_dependency_refs(graph, current, reader, declared):
    """Read graph descendants of the exact approved successor Build.

    A new sample or current Run may already exist when adoption is recorded.
    Its actual owner/retained execution must still pass graph capture. Including
    that dependency never supplies a verification result or approves its method.
    Unrelated Builds/configurations remain outside this finite native scope.
    """
    original = {node.ref.identity for node in graph.nodes}
    successors = {
        ref.id for ref in declared if ref.kind == "build" and ref.identity not in original
    }
    result = {ref.identity: ref for ref in declared}
    for node in current.nodes:
        ref = node.ref
        if ref.identity in original or ref.kind not in {"sample", "test_run"}:
            continue
        obj = reader.objects.get(ref.identity)
        _require(obj is not None and obj.current)
        build = (
            obj.view.get("build_id")
            if ref.kind == "sample"
            else obj.view.get("build", {}).get("id")
        )
        if str(build) in {str(value) for value in successors}:
            result[ref.identity] = ref
    return tuple(result.values())


def recheck_completion_closure(
    s, ctx, command, *, request, graph, expected_closure, captures, completion, retained_coverage
):
    """Rebuild current dependencies after verified, approved output creation.

    A changed watermark is observed, never ignored. The caller holds the DB
    dependency lock, verifies each actual CaptureRead and retains the original
    publication proof independently from current graph coverage.
    """
    from pdos_next.change_completion_owner import CompletionRead
    from pdos_next.change_implementation_owner import CaptureRead

    _require(bool(completion) and all(type(v) is CompletionRead for v in completion))
    native_refs = tuple(dict.fromkeys(ref for v in completion for ref in v.owner.actual_refs))
    scope, audience = request.scope, request.audience
    _scope(ctx, scope, audience)
    _require(
        type(command) is Command
        and command.operation
        in {"change.effectivity.record", "change.verification.record", "change.close"}
        and command.product_id == scope.product_id
    )
    _require(
        type(graph) is GraphSnapshot
        and graph.scope == scope
        and graph.audience == audience
        and graph.roots == request.roots
    )
    _require(type(expected_closure) is dict and expected_closure.get("version") == VERSION)
    _require(bool(captures) and all(type(value) is CaptureRead for value in captures))
    outputs = tuple(dict.fromkeys(ref for value in captures for ref in value.fact.outputs))
    _require(retained_coverage is not None)
    original_hash = retained_coverage.source_basis.get("closure_sha256")
    _require(type(original_hash) is str and len(original_hash) == 64)
    uow, caller = _uow(s), caller_digest(vars(ctx))
    runtime = _runtime(s, None)
    material = digest(
        _json(
            (
                request,
                graph,
                expected_closure,
                tuple(value.fact for value in captures),
                original_hash,
                tuple(v.fact for v in completion),
            )
        )
    )
    with _fresh_selects(s):
        observed = closure_stamp(s, ctx, scope=scope, audience=audience)
        _require(
            {k: v for k, v in expected_closure.items() if k != "dependency_epoch"}
            == {k: v for k, v in observed.items() if k != "dependency_epoch"}
        )
        _require(observed["dependency_epoch"] >= expected_closure["dependency_epoch"])
        reader = _reader(s, ctx, scope, audience)
        current = graph_owner.capture_graph(
            reader,
            identity=graph.id,
            roots=graph.roots,
            captured_at=graph.captured_at,
            expires_at=graph.expires_at,
            nature=graph.nature,
            sources=graph.sources,
        )
        _same_reader(reader, s, ctx, scope, audience)
        _require(not reader.hidden_discovered)
        approved_projection(
            graph,
            current,
            reader,
            outputs,
            original_hash,
            native_refs=native_dependency_refs(graph, current, reader, native_refs),
        )
        reads = _reads(reader, current)
        _require(closure_stamp(s, ctx, scope=scope, audience=audience) == observed)
    _same_uow(s, uow, ctx, caller)
    _require(_runtime(s, None) == runtime)
    _require(
        material
        == digest(
            _json(
                (
                    request,
                    graph,
                    expected_closure,
                    tuple(value.fact for value in captures),
                    original_hash,
                    tuple(v.fact for v in completion),
                )
            )
        )
    )
    checked_at = now()
    _require(
        graph.captured_at <= checked_at
        and deadline_current(graph.expires_at, checked_at)
        and deadline_current(retained_coverage.valid_until, checked_at)
    )
    return ClosureRead(graph, observed, reads, checked_at)
