"""Compare Current watermarks; rebuild a fixed Change graph once for a T2 commit.

This candidate reads actual owners, never writes or creates another graph identity.
The dependency clock fences committed reverse/hidden dependency changes. It is
not a permission proof. Callers must still run their live Source/Grant/authority,
runtime and common confirmation guards after merging the returned artifact reads.
"""

import json
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, event, inspect, select, text
from sqlalchemy.sql import visitors

from pdos_next.change_dependency_clock import ChangeDependencyClock
from pdos_next.clock import deadline_current, earliest_deadline, now
from pdos_next.contracts import Command
from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow, _uow
from pdos_next.domain.change_control.rules import digest, graph_sources
from pdos_next.domain.change_execution import graph as graph_owner
from pdos_next.domain.change_execution import service as old
from pdos_next.errors import DomainError
from pdos_next.models import Confirmation, Product
from pdos_next.schemas.change_control.contracts import Coverage, GraphSnapshot
from pdos_next.schemas.verification.contracts import Scope
from pdos_next.service import Context
from pdos_next.service import digest as caller_digest

VERSION = "change-dependency-closure-v1"

# Same candidate as next_0030; the manifest checks the two sets independently.
# A pending dependency must be rejected, rather than hidden by no_autoflush.
DEPENDENCY_TABLES = frozenset(
    "field_feedback_versions field_feedback_currents "
    "artifact_versions uploaded_originals original_security original_scan_requests "
    "original_scan_results lifecycle_objects lifecycle_candidates lifecycle_intents "
    "lifecycle_requests projects project_product_links definition_revisions definition_specs "
    "definition_sources parts bom_revisions bom_lines engineering_configurations "
    "process_revisions actual_configurations build_authorization_decisions "
    "build_current_authorizations build_current_execution_assessments build_execution_assessments "
    "build_lots build_operational_current build_operational_facts build_readiness build_starts "
    "builds operational_asset_sentinels operational_material_holds "
    "operational_resource_occupancies "
    "professional_authority_current professional_authority_facts quality_current_issues "
    "quality_current_policies quality_event_failure_links quality_failure_maps "
    "quality_issue_versions "
    "quality_policy_facts sample_allocations sample_current_readiness sample_readiness_facts "
    "sample_run_usages sample_units sample_usage_sentinels test_measurements test_resource_current "
    "test_resource_facts test_resource_reservations test_result_actions test_result_projections "
    "verification_actual_method_applicabilities verification_actual_method_batches "
    "verification_current_actual_methods verification_current_formal_requests "
    "verification_current_preparations verification_current_runs verification_formal_requests "
    "verification_handoff_facts verification_launch_facts verification_method_applicabilities "
    "verification_preparations verification_run_identities verification_run_versions "
    "verification_window_proposals manufacturing_preparation_versions "
    "manufacturing_preparation_currents manufacturing_baseline_document_links".split()
)


def _require(test):
    if not test:
        # No discovered hidden reference, source content or token value is emitted.
        raise DomainError("RECHECK_REQUIRED", "当前依赖闭包或同事务来源待重新捕获核对。", 409)


def _json(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        _require(all(type(k) is str for k in value))
        return {k: _json(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json(v) for v in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        _require(value.tzinfo is not None and value.utcoffset() is not None)
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Decimal):
        return str(value)
    _require(value is None or type(value) in (str, bool, int, float))
    return value


def _key(value):
    return json.dumps(_json(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sorted(values):
    return sorted((_json(v) for v in values), key=_key)


def graph_material(graph):
    """Order-independent actual topology; edge IDs remain intact in saved output.

    capture_graph numbers edges in discovery order. These IDs are stored Impact
    path keys, so comparison ignores only the fresh enumeration's edge ID while
    the caller continues using the original immutable graph and original IDs.
    """
    _require(type(graph) is GraphSnapshot)
    value = graph.model_dump(mode="json")
    for field in ("roots", "nodes", "coverage", "sources", "path_applicability"):
        if field not in value:
            continue
        value[field] = _sorted(value[field])
    edges = [{k: v for k, v in edge.items() if k != "id"} for edge in value["edges"]]
    _require(len({_key(edge) for edge in edges}) == len(edges))
    value["edges"] = _sorted(edges)
    return value


def require_same_graph(expected, current):
    _require(graph_material(expected) == graph_material(current))


def approved_projection(
    graph, current, reader, output_refs, original_owner_sha256, *, native_refs=()
):
    """Remove only actual approved configuration outputs from a rebuilt graph.

    The retained coverage digest includes each original owner's complete view,
    reads and source basis. Topology alone cannot prove that an old owner stayed
    unchanged. New nodes receive no inherited coverage or approval.
    """
    from pdos_next.domain.change_coverage_owner.registry import graph_projection

    original = {n.ref.identity for n in graph.nodes}
    outputs = {ref.identity for ref in output_refs}
    _require(not original.intersection(outputs))
    _require(
        all(
            ref.kind in {"engineering_configuration", "manufacturing_configuration"}
            and ref.key is None
            for ref in output_refs
        )
    )
    actual = {n.ref.identity: n.ref for n in current.nodes}
    _require(outputs <= set(actual))
    configurations = {
        (r.id, r.revision) for r in output_refs if r.kind == "manufacturing_configuration"
    }
    # Only callers that have read an actual approved native successor chain may
    # name these extra concrete objects. Existing implementation callers supply
    # no native refs and retain their original exact topology contract.
    native = {ref.identity for ref in native_refs} - original - outputs
    _require(all(ref.kind in {"build", "sample", "test_run", "engineering_configuration",
                              "manufacturing_configuration"} for ref in native_refs))
    allowed = outputs | native | {
        key
        for key, ref in actual.items()
        if ref.kind in {"operation", "sop"} and (ref.id, ref.revision) in configurations
    }
    _require(set(actual) == original | allowed)
    kept = GraphSnapshot.model_validate(
        {
            **current.model_dump(mode="python"),
            "nodes": tuple(n for n in current.nodes if n.ref.identity in original),
            "edges": tuple(
                e
                for e in current.edges
                if e.origin.identity in original and e.target.identity in original
            ),
            "coverage": graph.coverage,
            **(
                {"path_applicability": graph.path_applicability}
                if hasattr(graph, "path_applicability")
                else {}
            ),
        }
    )
    require_same_graph(graph, kept)
    owners = []
    for identity in sorted(original):
        obj = reader.objects[identity]
        _require(obj.current)
        owners.append(
            {
                "ref": obj.ref.model_dump(mode="json"),
                "view": obj.view,
                "reads": obj.reads,
                "source_basis": obj.source_basis,
            }
        )
    _require(
        digest(_json({"projection": graph_projection(kept), "owners": owners}))
        == original_owner_sha256
    )
    return kept


def _scope(ctx, scope, audience):
    _require(type(ctx) is Context and type(scope) is Scope)
    _require(scope.tenant_id == ctx.tenant_id)
    _require(type(audience) is tuple and len(audience) == 1)
    _require(
        audience == (f"product:{scope.product_id}",) or audience == (f"private:{ctx.requester_id}",)
    )


def stamp_statement(scope):
    """Scalar SQL columns bypass identity-map Product material and pending tokens."""
    columns = [c for c in Product.__table__.columns if c.key != "lifecycle_epoch"]
    return (
        select(*columns, ChangeDependencyClock.epoch.label("dependency_epoch"))
        .join(
            ChangeDependencyClock,
            and_(
                ChangeDependencyClock.tenant_id == Product.tenant_id,
                ChangeDependencyClock.product_id == Product.id,
            ),
        )
        .where(Product.tenant_id == scope.tenant_id, Product.id == scope.product_id)
        .limit(2)
        .execution_options(autoflush=False)
    )


def _stamp_rows(s, scope):
    return list(s.execute(stamp_statement(scope)).mappings())


def _pending_dependencies(s):
    for row in tuple(s.new) + tuple(s.dirty) + tuple(s.deleted):
        state = inspect(row)
        table = state.mapper.local_table.name
        if table in DEPENDENCY_TABLES:
            _require(False)
        if table == Product.__tablename__:
            _require(
                row not in s.new
                and row not in s.deleted
                and not any(
                    state.attrs[c.key].history.has_changes()
                    for c in Product.__table__.columns
                    if c.key != "lifecycle_epoch"
                )
            )


def lock_dependency_clock(s, ctx, *, scope, audience):
    """Hold shared-asset changes through the actual transaction's final commit.

    The server function only takes a scoped SHARE lock. App retains SELECT-only
    table access, and Agent cannot execute the function.
    """
    _scope(ctx, scope, audience)
    _uow(s)
    epoch = s.scalar(
        text("SELECT public.lock_change_dependency_clock(:tenant,:product)"),
        {"tenant": scope.tenant_id, "product": scope.product_id},
    )
    _require(type(epoch) is int and epoch > 0)
    return epoch


def closure_stamp(s, ctx, *, scope, audience):
    """Read the DB-owned product watermark; this result cannot authorize G3."""
    _scope(ctx, scope, audience)
    uow, caller, runtime = _uow(s), caller_digest(vars(ctx)), old._runtime_stamp(s)
    _pending_dependencies(s)
    with s.no_autoflush:
        rows = _stamp_rows(s, scope)
    _require(len(rows) == 1)
    row = dict(rows[0])
    epoch = row.pop("dependency_epoch", None)
    _require(type(epoch) is int and epoch > 0)
    expected_columns = {c.key for c in Product.__table__.columns if c.key != "lifecycle_epoch"}
    _require(set(row) == expected_columns)
    _require(row["tenant_id"] == ctx.tenant_id and row["id"] == scope.product_id)
    _same_uow(s, uow, ctx, caller)
    _require(old._runtime_stamp(s) == runtime)
    _pending_dependencies(s)
    return {
        "version": VERSION,
        "scope": scope.model_dump(mode="json"),
        "audience": list(audience),
        "product": _json(row),
        "dependency_epoch": epoch,
    }


def _is_confirmation(statement):
    return any(
        getattr(item, "name", None) == Confirmation.__tablename__
        for item in visitors.iterate(statement)
    )


def _loaded_confirmations(s):
    # Read only already-loaded __dict__ values: no lazy load, SQL or token logs.
    return tuple(
        (
            row,
            {
                c.key: deepcopy(row.__dict__[c.key])
                for c in Confirmation.__table__.columns
                if c.key in row.__dict__
            },
        )
        for row in tuple(s.identity_map.values()) + tuple(s.new)
        if isinstance(row, Confirmation)
    )


def _same_confirmations(saved):
    for row, fields in saved:
        _require(all(key in row.__dict__ and row.__dict__[key] == v for key, v in fields.items()))


@contextmanager
def _fresh_selects(s):
    """Refresh exact owners without expiring/resetting common's pending proof.

    Actual manufacturing owners may read their own *historical* Confirmation.
    This helper itself never selects Confirmation. The exclusion and memory
    guard preserve an already-loaded pending common confirmation even if a
    nested owner installs a broader refresh listener. Any reset fails closed.
    """
    saved = _loaded_confirmations(s)

    def actual_rows(state):
        if state.is_select:
            state.update_execution_options(
                populate_existing=not _is_confirmation(state.statement), autoflush=False
            )

    event.listen(s, "do_orm_execute", actual_rows)
    try:
        with s.no_autoflush:
            yield
        _same_confirmations(saved)
    finally:
        event.remove(s, "do_orm_execute", actual_rows)
        _same_confirmations(saved)


class _TrackedReader(graph_owner.OwnerReader):
    def __init__(self, *args):
        super().__init__(*args)
        self.hidden_discovered = False

    def resolve(self, ref):
        try:
            return super().resolve(ref)
        except DomainError as error:
            if error.status == 403:
                self.hidden_discovered = True
            raise


def _reader(s, ctx, scope, audience):
    return _TrackedReader(s, ctx, scope.product_id, scope, audience, old._issue_loader(s))


def _same_reader(reader, s, ctx, scope, audience):
    _require(
        isinstance(reader, _TrackedReader)
        and reader.s is s
        and reader.ctx is ctx
        and reader.pid == scope.product_id
        and reader.scope is scope
        and reader.target is audience
        and reader.issue_loader is old._issue_loader(s)
    )


def _owner_material(reader):
    return {
        identity: _json(
            {
                "ref": obj.ref,
                "label": obj.label,
                "scope": obj.scope,
                "owner_id": obj.owner_id,
                "visibility": obj.visibility,
                "view": obj.view,
                "reads": obj.reads,
                "source_basis": obj.source_basis,
                "current": obj.current,
            }
        )
        for identity, obj in reader.objects.items()
    }


def _reads(reader, graph):
    values = [read for obj in reader.objects.values() for read in obj.reads]
    values.extend(
        {"artifact_id": source.id, "expected_revision": source.revision}
        for source in graph_sources(graph)
        if source.kind == "artifact"
    )
    result = {}
    for value in values:
        _require(type(value) is dict and set(value) == {"artifact_id", "expected_revision"})
        identity, revision = str(UUID(str(value["artifact_id"]))), value["expected_revision"]
        _require(type(revision) is int and revision > 0)
        _require(identity not in result or result[identity] == revision)
        result[identity] = revision
    return tuple({"artifact_id": key, "expected_revision": result[key]} for key in sorted(result))


def _runtime(s, coverage_refresh):
    engine = s.get_bind()
    order = getattr(engine, "_pdos_change_order_runtime", None)
    order_ids = None if order is None else (id(order[0]), tuple(id(v) for v in order[1]))
    return (
        old._runtime_stamp(s),
        id(old._issue_loader(s)),
        order_ids,
        id(coverage_refresh),
        id(graph_owner.capture_graph),
        id(graph_owner.OwnerReader.resolve),
        id(graph_owner.OwnerReader.links),
        id(graph_owner.OwnerReader._load),
        id(graph_owner.OwnerReader._query),
        id(graph_owner.OwnerReader._current_runs),
        id(graph_owner.OwnerReader._current_preparations),
    )


@dataclass(frozen=True)
class ClosureRead:
    graph: GraphSnapshot
    closure: dict
    required_source_read_set: tuple
    checked_at: datetime
    authority_attested: bool = False


def recheck_implementation_closure(
    s, ctx, command, *, request, graph, expected_closure, captures, retained_coverage
):
    """Rebuild current dependencies after verified, approved output creation.

    A changed watermark is observed, never ignored. The caller holds the DB
    dependency lock, verifies each actual CaptureRead and retains the original
    publication proof independently from current graph coverage.
    """
    from pdos_next.change_implementation_owner import CaptureRead

    scope, audience = request.scope, request.audience
    _scope(ctx, scope, audience)
    _require(
        type(command) is Command
        and command.operation == "change.implementation.record"
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
        approved_projection(graph, current, reader, outputs, original_hash)
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


def recheck_graph_closure(
    s,
    ctx,
    command,
    *,
    graph,
    scope,
    audience,
    roots,
    expected_closure,
    valid_until,
    coverage_refresh=None,
    complete_recheck=False,
):
    """A snapshot uses its DB watermark and direct read set.

    A T2 commit may additionally reconstruct the full topology once. Coverage
    remains a trusted server callback and cannot promote an UNKNOWN facet.
    """
    _scope(ctx, scope, audience)
    _require(type(command) is Command and command.product_id == scope.product_id)
    _require(
        command.operation
        in {"change.order.prepare", "change.order.approve", "change.implementation.record"}
    )
    _require(type(graph) is GraphSnapshot and graph.scope == scope and graph.audience == audience)
    _require(graph.revision == 1 and tuple(roots) == graph.roots)
    _require(type(expected_closure) is dict and expected_closure.get("version") == VERSION)
    _require(
        valid_until is None
        or (valid_until.tzinfo is not None and valid_until.utcoffset() is not None)
    )
    _require(
        type(complete_recheck) is bool
        and (not complete_recheck or command.operation == "change.order.approve")
    )
    _require(coverage_refresh is None or callable(coverage_refresh))
    _require(
        not (
            any(c.status != "unknown" for c in graph.coverage)
            or any(p.status != "unknown" for p in graph.path_applicability)
        )
        or coverage_refresh is not None
    )
    uow, caller = _uow(s), caller_digest(vars(ctx))
    original = (digest(command), digest(graph), digest(expected_closure), digest(scope), audience)
    runtime = _runtime(s, coverage_refresh)
    earliest = earliest_deadline(valid_until, graph.expires_at)

    def live():
        _same_uow(s, uow, ctx, caller)
        _require(
            original
            == (digest(command), digest(graph), digest(expected_closure), digest(scope), audience)
        )
        _require(_runtime(s, coverage_refresh) == runtime)
        _pending_dependencies(s)
        checked_at = now()
        _require(graph.captured_at <= checked_at and deadline_current(earliest, checked_at))
        return checked_at

    expected = deepcopy(expected_closure)
    live()
    with _fresh_selects(s):
        _require(closure_stamp(s, ctx, scope=scope, audience=audience) == expected)
        reader = _reader(s, ctx, scope, audience)
        current = graph
        if complete_recheck:
            try:
                current = graph_owner.capture_graph(
                    reader,
                    identity=graph.id,
                    roots=roots,
                    captured_at=graph.captured_at,
                    expires_at=graph.expires_at,
                    nature=graph.nature,
                    sources=graph.sources,
                )
            except DomainError:
                raise DomainError("RECHECK_REQUIRED", "当前依赖闭包待重新捕获核对。", 409) from None
        _same_reader(reader, s, ctx, scope, audience)
        _require(not reader.hidden_discovered)
        if coverage_refresh is not None:
            coverage = coverage_refresh(
                s, ctx, scope.product_id, graph=graph, current_graph=current, reader=reader
            )
            _require(type(coverage) is tuple and all(type(c) is Coverage for c in coverage))
            current = GraphSnapshot.model_validate(
                {
                    **current.model_dump(mode="python"),
                    "coverage": coverage,
                    "path_applicability": graph.path_applicability,
                }
            )
        _same_reader(reader, s, ctx, scope, audience)
        require_same_graph(graph, current)
        result_reads = _reads(reader, current)
        _require(closure_stamp(s, ctx, scope=scope, audience=audience) == expected)
        live()
    # No helper IO occurs after this exact root/caller/runtime and clock closure.
    checked_at = live()
    return ClosureRead(graph, expected, result_reads, checked_at)
