"""Current concrete owner, fixed source IO and bounded actual registry closure."""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import event, or_, select

import pdos_next.models  # noqa: F401 - complete model registration before runtime imports
from pdos_next import change_controlled_owner as controlled
from pdos_next.change_dependency_clock import ChangeDependencyClock
from pdos_next.change_graph_closure import (
    _fresh_selects,
    _pending_dependencies,
    lock_dependency_clock,
)
from pdos_next.change_implementation_owner import common_group
from pdos_next.change_order_service import _one, current_fixed, snapshot
from pdos_next.clock import deadline_current, earliest_deadline
from pdos_next.clock import now as server_now
from pdos_next.database import category_for_product
from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow, _uow
from pdos_next.domain.change_control.rules import digest, graph_sources
from pdos_next.domain.change_execution import service as old
from pdos_next.domain.change_execution.models import ChangeRequestVersion
from pdos_next.domain.professional_authority import service as professional
from pdos_next.domain.professional_authority.models import ProfessionalCurrent
from pdos_next.models import Grant, Principal, Product
from pdos_next.schemas.change_control.contracts import Coverage, GraphSnapshot, PathApplicability
from pdos_next.schemas.verification.contracts import Scope, SourceRef
from pdos_next.service import digest as common_digest

from . import models, registry, trust
from .schemas import EVENT, FACETS, FAMILY, OPERATION, CoverageMaterial
from .trust import require

_READ_TOKEN = object()
_RETAINED_TOKEN = object()


def clock():
    return server_now()


def _pending_people(s):
    # Never refresh pending authority rows away, including changed scope/IDs.
    require(not any(isinstance(row, (Principal, Grant)) for row in (*s.new, *s.dirty, *s.deleted)))


@contextmanager
def _people_fence(s):
    _pending_people(s)

    def before_select(state):
        if state.is_select:
            _pending_people(s)

    event.listen(s, "do_orm_execute", before_select)
    try:
        yield
        _pending_people(s)
    finally:
        event.remove(s, "do_orm_execute", before_select)
        _pending_people(s)


def quiet(s):
    _pending_people(s)
    _pending_dependencies(s)
    tables = {models.ChangeCoverageFact.__tablename__, models.ChangeCoverageCurrent.__tablename__}
    require(not any(row.__table__.name in tables for row in (*s.new, *s.dirty, *s.deleted)))


def lock_people(s, ctx, pid, publisher_id, *, nowait=False):
    """Keep publisher/current reader authority rows locked until the caller's UOW ends.

    Product/scope locks are already held. Existing outer locks or cross-product
    A/B readers can still deadlock; the caller must roll back that entire UOW.
    These rows fence revocation, and never confer new execution permission.
    """
    _uow(s)
    identities = sorted({publisher_id, ctx.actor_id, ctx.requester_id}, key=str)
    # A fresh SELECT must not erase a pending revocation. Reject all pending
    # authority rows in this Session: changing tenant/product/identity in memory
    # cannot escape a narrower predicate. No pending field is refreshed away.
    _pending_people(s)
    stamps, deadlines = [], []
    for identity in identities:
        person = _one(
            s,
            Principal,
            Principal.tenant_id == ctx.tenant_id,
            Principal.id == identity,
            lock=True,
            nowait=nowait,
        )
        grant = _one(
            s,
            Grant,
            Grant.tenant_id == ctx.tenant_id,
            Grant.category_id == category_for_product(pid),
            Grant.principal_id == identity,
            lock=True,
            nowait=nowait,
        )
        require(
            person.active is True
            and person.kind == "human"
            and type(person.access_epoch) is int
            and person.access_epoch > 0
            and type(grant.access_epoch) is int
            and grant.access_epoch > 0,
            status=403,
        )
        stamps.append(
            (
                person.id,
                person.tenant_id,
                person.kind,
                person.active,
                person.access_epoch,
                grant.id,
                grant.tenant_id,
                grant.category_id,
                grant.principal_id,
                grant.access_epoch,
                grant.can_write,
                grant.expires_at.isoformat() if grant.expires_at else None,
            )
        )
        if grant.expires_at is not None:
            deadlines.append(grant.expires_at)
    until = min(deadlines, default=None)
    require(until is None or clock() < until, status=403)
    return tuple(stamps), until


def dependency_epoch(s, ctx, pid):
    quiet(s)
    row = _one(
        s,
        ChangeDependencyClock,
        ChangeDependencyClock.tenant_id == ctx.tenant_id,
        ChangeDependencyClock.product_id == pid,
    )
    require(type(row.epoch) is int and row.epoch > 0, "COVERAGE_CLOCK_REQUIRED", 503)
    quiet(s)
    return row.epoch


def temporal(s, ctx, pid, scope):
    """Compare Current authority intervals and member epochs at the final clock.

    Ordinary grants have no TTL. A fact entering or leaving its real interval
    still changes this stamp, without shortening unrelated captures.
    """
    at, stamps = clock(), []
    # Current's trigger-maintained summary has these exact immutable fact fields.
    # Its RLS already proves the referenced Fact's complete live audience; a
    # second Fact join repeats that work for every watermark comparison.
    pointers = s.scalars(
        select(ProfessionalCurrent)
        .where(
            ProfessionalCurrent.tenant_id == ctx.tenant_id,
            ProfessionalCurrent.product_id == pid,
            or_(
                ProfessionalCurrent.project_id == scope.project_id,
                ProfessionalCurrent.project_id.is_(None),
            ),
        )
        .order_by(ProfessionalCurrent.fact_id)
        .execution_options(populate_existing=True, autoflush=False)
    )
    for pointer in pointers:
        row = professional._summary_row(pointer)
        professional._check_current(
            pointer, row, ctx, pid, pointer.project_id, pointer.subject_id, summary=True
        )
        stamps.append(
            [
                str(row.id),
                row.revision,
                row.fact_sha256,
                row.state,
                row.valid_from.isoformat(),
                row.valid_until.isoformat(),
                row.valid_from <= at < row.valid_until,
            ]
        )
    grants = s.execute(
        select(Grant.id, Grant.access_epoch, Grant.can_write, Grant.expires_at)
        .where(Grant.tenant_id == ctx.tenant_id, Grant.category_id == category_for_product(pid))
        .order_by(Grant.id)
        .execution_options(autoflush=False)
    )
    for row in grants:
        stamps.append(
            [
                str(row.id),
                row.access_epoch,
                row.can_write,
                row.expires_at.isoformat() if row.expires_at else None,
                deadline_current(row.expires_at, at),
            ]
        )
    # This opaque digest exposes no identities or counts to the reader.
    return digest(stamps), None


def _fixed_request(value):
    return {
        "scope": value.scope.model_dump(mode="json"),
        "audience": list(value.audience),
        "requester_id": str(value.requester_id),
        "roots": [v.model_dump(mode="json") for v in value.roots],
        "references": [v.model_dump(mode="json") for v in value.references],
    }


def fixed_seed(s, ctx, pid, refs, *, verify_sources=True):
    # The existing optional arbitrary Issue loader is not a coverage truth root.
    from pdos_next.domain.change_execution.field_bridge import get as field_feedback
    from pdos_next.domain.quality_execution.service import (
        _change_scope_for_change,
        get_issue_for_change,
    )

    fixed = {}
    for ref in refs:
        if ref.kind == "field_feedback":
            key = ("field_feedback", ref.id, ref.revision)
            if key not in fixed:
                # Field's native owner checks Current, real configuration,
                # source status and caller ACL even in a metadata-only binding.
                # This derives scope; it grants no completeness or publication.
                _, _, scope, purpose = field_feedback(s, ctx, pid, ref)
                fixed[key] = (scope.project_id, purpose)
            continue
        if ref.kind not in {"issue", "capa"}:
            continue
        key = ("issue", ref.id, ref.revision)
        if key in fixed:
            continue
        if not verify_sources:
            scope, purpose = _change_scope_for_change(s, ctx, pid, ref)
            fixed[key] = (scope.project_id, purpose)
            continue
        row, view = get_issue_for_change(s, ctx, pid, ref.id, ref.revision)
        require(
            row.tenant_id == ctx.tenant_id
            and row.product_id == pid
            and view.issue_id == ref.id
            and view.revision == ref.revision
            and view.source_status == "current",
            "COVERAGE_DEPENDENCY_UNRESOLVED",
        )
        fixed[key] = (row.project_id, view.purpose)
    require(bool(fixed) and len(set(fixed.values())) == 1, "COVERAGE_DEPENDENCY_UNRESOLVED")
    project_id, purpose = next(iter(fixed.values()))
    return Scope(tenant_id=ctx.tenant_id, product_id=pid, project_id=project_id), purpose


def binding(s, ctx, pid, change_id, purpose, *, material=None, lock=False, verify_sources=True):
    quiet(s)
    pointer, row = current_fixed(s, ctx, pid, change_id, lock=lock)
    request = snapshot(row)
    # Real SHARE watermark lock survives the entire original caller transaction.
    lock_dependency_clock(s, ctx, scope=request.scope, audience=request.audience)
    scope, actual_purpose = fixed_seed(
        s, ctx, pid, (*request.roots, *request.references), verify_sources=verify_sources
    )
    require(request.scope == scope and actual_purpose == purpose, status=403)
    # Every saved version is a publication. A rolled-back Current cannot erase later history.
    latest = list(
        s.scalars(
            select(ChangeRequestVersion)
            .where(
                ChangeRequestVersion.tenant_id == ctx.tenant_id,
                ChangeRequestVersion.product_id == pid,
                ChangeRequestVersion.change_id == change_id,
            )
            .order_by(ChangeRequestVersion.revision.desc())
            .limit(1)
            .execution_options(populate_existing=True, autoflush=False)
        )
    )
    require(len(latest) == 1 and latest[0].id == row.id and latest[0].revision == row.revision)
    origin = row
    if material is not None:
        require(
            material.change_id == change_id
            and material.scope == scope
            and material.purpose == purpose
            and material.roots == request.roots
            and material.visibility == row.visibility
            and material.owner_id == row.owner_id,
            status=403,
        )
        require(
            material.origin_revision <= row.revision,
            "VERSION_CONFLICT",
            422,
        )
        seen = set()
        while origin.revision > material.origin_revision:
            require(
                origin.id not in seen
                and origin.previous_version_id is not None
                and origin.previous_revision == origin.revision - 1
            )
            seen.add(origin.id)
            require(
                origin.operation
                in {
                    "change.impact.compute",
                    "change.order.prepare",
                    "change.order.approve",
                    "change.implementation.record",
                    "change.effectivity.record",
                    "change.verification.record",
                    "change.close",
                }
            )
            origin = _one(
                s,
                ChangeRequestVersion,
                ChangeRequestVersion.tenant_id == ctx.tenant_id,
                ChangeRequestVersion.product_id == pid,
                ChangeRequestVersion.project_id == scope.project_id,
                ChangeRequestVersion.change_id == change_id,
                ChangeRequestVersion.id == origin.previous_version_id,
                ChangeRequestVersion.revision == origin.previous_revision,
            )
            require(
                _fixed_request(snapshot(origin)) == _fixed_request(request)
                and (origin.owner_id, origin.visibility) == (row.owner_id, row.visibility),
                status=403,
            )
        require(
            (origin.id, origin.revision) == (material.origin_version_id, material.origin_revision)
            and (origin.owner_id, origin.visibility) == (material.owner_id, material.visibility),
            status=403,
        )
    return (
        row,
        request,
        scope,
        {
            "current_id": str(pointer.id),
            "version_id": str(row.id),
            "revision": row.revision,
            "origin_version_id": str(origin.id),
            "origin_revision": origin.revision,
            "fixed_request": _fixed_request(request),
        },
    )


def pointer(s, ctx, pid, scope, change_id, purpose, *, lock=False):
    model = models.ChangeCoverageCurrent
    q = (
        select(model)
        .where(
            model.tenant_id == ctx.tenant_id,
            model.product_id == pid,
            model.project_id == scope.project_id,
            model.change_id == change_id,
            model.purpose_sha256 == digest(purpose),
        )
        .limit(2)
        .execution_options(populate_existing=True, autoflush=False)
    )
    values = list(s.scalars(q.with_for_update() if lock else q))
    require(len(values) <= 1, "INTEGRITY_MISMATCH")
    if not values:
        return None, None
    p = values[0]
    f = models.ChangeCoverageFact
    row = _one(
        s,
        f,
        f.tenant_id == ctx.tenant_id,
        f.product_id == pid,
        f.project_id == scope.project_id,
        f.change_id == change_id,
        f.id == p.fact_id,
        f.revision == p.revision,
    )
    latest = list(
        s.scalars(
            select(f)
            .where(
                f.tenant_id == ctx.tenant_id,
                f.product_id == pid,
                f.project_id == scope.project_id,
                f.change_id == change_id,
                f.purpose_sha256 == digest(purpose),
            )
            .order_by(f.revision.desc())
            .limit(1)
            .execution_options(populate_existing=True, autoflush=False)
        )
    )
    require(
        len(latest) == 1 and latest[0].id == row.id and latest[0].revision == row.revision,
        "INTEGRITY_MISMATCH",
    )
    require(
        (p.owner_id, p.visibility, p.revision, p.epoch, p.purpose_sha256)
        == (row.owner_id, row.visibility, row.revision, row.epoch, row.purpose_sha256)
        and row.purpose == purpose
        and row.purpose_sha256 == digest(purpose)
        and row.epoch == row.revision,
        "INTEGRITY_MISMATCH",
    )
    return p, row


def pointer_stamp(p):
    return (p.id, p.fact_id, p.revision, p.epoch, p.owner_id, p.visibility, p.purpose_sha256)


def inspect_basis(s, ctx, pid, *, change_id, purpose):
    """Host source preparation only: actual closure evidence, no complete projection."""
    uow, caller_hash = _uow(s), common_digest(vars(ctx))
    quiet(s)
    _one(s, Product, Product.tenant_id == ctx.tenant_id, Product.id == pid, lock=True)
    caller, until = controlled._caller(s, ctx, pid, write=False)
    _, request, scope, bound = binding(s, ctx, pid, change_id, purpose)
    controlled._project(s, ctx, scope)
    auth, auth_until = controlled.authority(
        s, ctx, pid, scope, "change.impact.compute", purpose, write=False
    )
    epoch = dependency_epoch(s, ctx, pid)
    result = registry.read_registry(s, ctx, pid, request)
    require(
        epoch == dependency_epoch(s, ctx, pid)
        and controlled._caller(s, ctx, pid, write=False)[0] == caller
    )
    _same_uow(s, uow, ctx, caller_hash)
    require(deadline_current(earliest_deadline(until, auth_until, result.valid_until), clock()))
    return {
        "scope": scope.model_dump(mode="json"),
        "binding": bound,
        "closure": deepcopy(result.closure),
        "closure_sha256": result.closure_sha256,
        "dependency_epoch": epoch,
        "nature": "synthetic" if auth.get("synthetic") else "real",
    }


@dataclass(frozen=True, eq=False)
class CoverageRead:
    coverage: tuple[Coverage, ...]
    sources: tuple[SourceRef, ...]
    required_source_read_set: tuple[dict, ...]
    source_basis: dict
    valid_until: datetime
    _token: object
    _session: object
    _uow: object
    _caller_hash: str
    _proof_sha256: str
    path_applicability: tuple[PathApplicability, ...] = ()


@dataclass(frozen=True, eq=False)
class RetainedCoverageRead:
    """Original publication proof only; cannot project coverage onto any graph.

    The implementation owner must separately compare the actual old-owner
    closure and authorize every new output/source delta against its approved plan.
    """

    sources: tuple[SourceRef, ...]
    required_source_read_set: tuple[dict, ...]
    source_basis: dict
    valid_until: datetime
    observed_dependency_epoch: int
    _token: object
    _session: object
    _uow: object
    _caller_hash: str
    _proof_sha256: str


def _material_projection(value, graph, source):
    states = {(v.node.identity, v.facet): v for v in value.facet_states}
    coverage = tuple(
        Coverage(
            node=node.ref,
            facet=facet,
            status=state.status
            if (state := states.get((node.ref.identity, facet)))
            else "complete",
            reason=state.reason if state else None,
            source=source,
        )
        for node in graph.nodes
        for facet in FACETS
    )
    paths = tuple(
        PathApplicability(**path.model_dump(mode="python"), source=source) for path in value.paths
    )
    return coverage, paths


def _read(s, ctx, pid, *, change_id, purpose, graph, origin_version=None, retained=None):
    """Read actual Current + original + actual closure. Input graph alone is not trusted."""
    require(type(graph) is GraphSnapshot, "COVERAGE_GRAPH_REQUIRED", 503)
    uow, caller_hash = _uow(s), common_digest(vars(ctx))
    quiet(s)
    _one(s, Product, Product.tenant_id == ctx.tenant_id, Product.id == pid, lock=True)
    caller, caller_until = controlled._caller(s, ctx, pid, write=False)
    _, request, scope, _ = binding(s, ctx, pid, change_id, purpose)
    _, project_stamp = controlled._project(s, ctx, scope)
    require(
        graph.scope == scope
        and graph.audience == request.audience
        and graph.roots == request.roots,
        status=403,
    )
    p, row = pointer(s, ctx, pid, scope, change_id, purpose)
    require(row is not None, "COVERAGE_OWNER_REQUIRED", 503)
    people, people_until = lock_people(s, ctx, pid, row.actor_id)
    publisher_stamp = next(v for v in people if v[0] == row.actor_id)
    saved_pointer, saved_row = (
        pointer_stamp(p),
        common_digest(
            {
                v.name: getattr(row, v.name)
                for v in row.__table__.columns
                if v.name != "audience_dependencies"
            }
        ),
    )
    source = SourceRef.model_validate(row.source)
    value, _ = controlled.original(s, ctx, pid, source, CoverageMaterial)
    require(
        row.operation == OPERATION
        and row.status == "published"
        and row.material == value.model_dump(mode="json")
        and row.material_sha256 == digest(value)
        and (
            row.origin_version_id,
            row.origin_revision,
            row.closure_sha256,
            row.valid_from,
            row.valid_until,
            row.nature,
        )
        == (
            value.origin_version_id,
            value.origin_revision,
            value.closure_sha256,
            value.valid_from,
            value.valid_until,
            value.nature,
        ),
        "INTEGRITY_MISMATCH",
    )
    if origin_version is not None:
        require(
            type(origin_version) is tuple
            and len(origin_version) == 2
            and type(origin_version[1]) is int
            and origin_version == (value.origin_version_id, value.origin_revision)
        )
    _, request, _, bound = binding(s, ctx, pid, change_id, purpose, material=value)
    require(value.publisher_id == row.actor_id)
    issuer = trust.check(s.get_bind(), scope, source, value)
    issuer_stamp, runtime = trust.stamp(issuer), old._runtime_stamp(s)
    require(row.issuer_stamp == issuer_stamp)
    signer_until = controlled.original_authority(s, ctx, pid, row)
    group = common_group(s, ctx, pid, row, operation=OPERATION, event=EVENT, actor=row.actor_id)
    require(
        group["receipt"]["subject_type"] == FAMILY
        and group["receipt"]["command_id"] == row.command_id
        and group["receipt"]["intent_digest"] == row.intent_digest
        and group["receipt"]["request_digest"] == row.intent_digest,
        "INTEGRITY_MISMATCH",
    )
    observed_epoch = dependency_epoch(s, ctx, pid)
    epoch = row.dependency_epoch
    if retained is None:
        require(observed_epoch == epoch)
    temporal_stamp, temporal_until = temporal(s, ctx, pid, scope)
    owned = None
    if retained is None:
        owned = registry.read_registry(s, ctx, pid, request)
        require(
            controlled.same(owned.projection, registry.graph_projection(graph))
            and owned.closure_sha256 == value.closure_sha256
        )
    refs = {n.ref.identity for n in graph.nodes}
    require(refs == {r.identity for r in value.nodes} and graph.nature == value.nature)
    sources = (
        tuple(dict.fromkeys((source, *owned.sources, *request.sources)))
        if owned is not None
        else tuple(SourceRef.model_validate(v) for v in row.sources)
    )
    reads = (
        controlled._reads(
            old._source_reads(sources),
            owned.reads,
            row.authority_snapshot["required_source_read_set"],
        )
        if owned is not None
        else controlled._reads(row.required_source_read_set)
    )
    require(
        source in sources
        and set(request.sources) <= set(sources)
        and controlled._reads(
            reads, old._source_reads(sources), row.authority_snapshot["required_source_read_set"]
        )
        == reads
    )
    require(bool(reads), "MISSING_REQUIRED_EVIDENCE", 422)
    artifact_basis = controlled._source_guard(
        s, ctx, pid, value.visibility, value.owner_id, reads, sources
    )
    # Saved original publication evidence is exact; Root retains action authority.
    require(row.sources == [v.model_dump(mode="json") for v in sources])
    require(row.required_source_read_set == reads)
    require(
        row.source_basis
        == {
            "artifact_basis": controlled._source_guard(
                s,
                ctx,
                pid,
                value.visibility,
                value.owner_id,
                row.required_source_read_set,
                tuple(SourceRef.model_validate(v) for v in row.sources),
                io=False,
            ),
            "closure_sha256": value.closure_sha256,
            "dependency_epoch": epoch,
            "temporal_sha256": temporal_stamp,
        }
    )
    # After source IO: refresh all concrete sources/owners, then final identity/TTL.
    if owned is not None:
        require(registry.read_registry(s, ctx, pid, request).closure_sha256 == owned.closure_sha256)
    require(controlled.original(s, ctx, pid, source, CoverageMaterial)[0] == value)
    require(
        controlled._source_guard(
            s, ctx, pid, value.visibility, value.owner_id, reads, sources, io=False
        )
        == artifact_basis
    )
    signer_until = earliest_deadline(signer_until, controlled.original_authority(s, ctx, pid, row))
    require(
        temporal(s, ctx, pid, scope)[0] == temporal_stamp
        and dependency_epoch(s, ctx, pid) == observed_epoch
    )
    fresh_p, fresh_row = pointer(s, ctx, pid, scope, change_id, purpose)
    require(
        pointer_stamp(fresh_p) == saved_pointer
        and common_digest(
            {
                v.name: getattr(fresh_row, v.name)
                for v in fresh_row.__table__.columns
                if v.name != "audience_dependencies"
            }
        )
        == saved_row
    )
    require(binding(s, ctx, pid, change_id, purpose, material=value)[3] == bound)
    require(
        controlled._caller(s, ctx, pid, write=False)[0] == caller
        and controlled._project(s, ctx, scope)[1] == project_stamp
        and old._runtime_stamp(s) == runtime
        and trust.current(s.get_bind(), scope) is issuer
    )
    require(dependency_epoch(s, ctx, pid) == observed_epoch)
    fresh_people, fresh_people_until = lock_people(s, ctx, pid, row.actor_id)
    require(fresh_people == people, status=403)
    _same_uow(s, uow, ctx, caller_hash)
    until = earliest_deadline(
        value.valid_until,
        graph.expires_at,
        caller_until,
        signer_until,
        people_until,
        fresh_people_until,
        temporal_until or value.valid_until,
        (owned.valid_until if owned is not None else None) or value.valid_until,
    )
    at = clock()
    require(value.valid_from <= at < until and graph.captured_at <= at)
    proof = {
        "fact_id": str(row.id),
        "revision": row.revision,
        "epoch": row.epoch,
        "material_sha256": row.material_sha256,
        "units": [v.model_dump(mode="json") for v in value.units],
        "graph": {
            "id": str(graph.id),
            "revision": graph.revision,
            "captured_at": graph.captured_at.isoformat(),
            "expires_at": graph.expires_at.isoformat() if graph.expires_at is not None else None,
        },
        "binding": bound,
        "issuer": issuer_stamp,
        "publisher_access_sha256": common_digest(publisher_stamp),
        "dependency_epoch": epoch,
        "closure_sha256": value.closure_sha256,
        "artifact_basis": artifact_basis,
        "temporal_sha256": temporal_stamp,
        "publication_group_sha256": common_digest(group),
        "sources": [v.model_dump(mode="json") for v in sources],
        "reads": reads,
        "nature": value.nature,
    }
    coverage, paths = _material_projection(value, graph, source)
    if retained is not None:
        from pdos_next.change_coverage_binding import stable_basis

        require(
            stable_basis(retained) == stable_basis(proof)
            and graph.coverage == coverage
            and graph.path_applicability == paths
            and set(graph_sources(graph)) <= set(sources)
        )
        return RetainedCoverageRead(
            sources,
            tuple(deepcopy(reads)),
            deepcopy(proof),
            until,
            observed_epoch,
            _RETAINED_TOKEN,
            s,
            uow,
            caller_hash,
            common_digest(proof),
        )
    return CoverageRead(
        coverage,
        sources,
        tuple(deepcopy(reads)),
        deepcopy(proof),
        until,
        _READ_TOKEN,
        s,
        uow,
        caller_hash,
        common_digest(proof),
        paths,
    )


def read(s, ctx, pid, *, change_id, purpose, graph, origin_version=None):
    """Keep the original loaded Confirmation baseline across all source IO.

    The actual guard uses identity-map/new-row dictionaries, never a
    Confirmation SELECT. Its listener is always removed in finally.
    """
    _uow(s)
    with _fresh_selects(s), _people_fence(s):
        return _read(
            s,
            ctx,
            pid,
            change_id=change_id,
            purpose=purpose,
            graph=graph,
            origin_version=origin_version,
        )


def read_retained(s, ctx, pid, *, change_id, purpose, graph, saved, origin_version=None):
    """Reprove an approved publication, not current graph completeness.

    ``saved`` and ``graph`` must come from the host's immutable approved capture.
    No dependency-clock equality with the original publication is claimed. The
    current clock is still fenced across this read, and old source/authority,
    exact Current/Fact, original, origin and publication group stay checked.
    """
    require(type(saved) is dict)
    _uow(s)
    with _fresh_selects(s), _people_fence(s):
        return _read(
            s,
            ctx,
            pid,
            change_id=change_id,
            purpose=purpose,
            graph=graph,
            origin_version=origin_version,
            retained=saved,
        )


def refresh_retained(s, ctx, pid, previous, *, change_id, purpose, graph, origin_version=None):
    require(
        type(previous) is RetainedCoverageRead
        and previous._token is _RETAINED_TOKEN
        and previous._session is s
        and previous._proof_sha256 == common_digest(previous.source_basis)
    )
    _same_uow(s, previous._uow, ctx, previous._caller_hash)
    current = read_retained(
        s,
        ctx,
        pid,
        change_id=change_id,
        purpose=purpose,
        graph=graph,
        saved=previous.source_basis,
        origin_version=origin_version,
    )
    require(
        current._proof_sha256 == previous._proof_sha256
        and current.sources == previous.sources
        and current.required_source_read_set == previous.required_source_read_set
        and current.observed_dependency_epoch == previous.observed_dependency_epoch
    )
    require(clock() < min(current.valid_until, previous.valid_until))
    return current


def _refresh(s, ctx, pid, previous, *, change_id, purpose, graph, origin_version=None):
    require(
        type(previous) is CoverageRead
        and previous._token is _READ_TOKEN
        and previous._session is s
        and previous._proof_sha256 == common_digest(previous.source_basis)
    )
    _same_uow(s, previous._uow, ctx, previous._caller_hash)
    current = read(
        s,
        ctx,
        pid,
        change_id=change_id,
        purpose=purpose,
        graph=graph,
        origin_version=origin_version,
    )
    require(
        current._proof_sha256 == previous._proof_sha256
        and current.coverage == previous.coverage
        and current.path_applicability == previous.path_applicability
        and current.required_source_read_set == previous.required_source_read_set
        and current.sources == previous.sources
    )
    require(clock() < min(current.valid_until, previous.valid_until))
    return current


def refresh(s, ctx, pid, previous, *, change_id, purpose, graph, origin_version=None):
    _uow(s)
    with _fresh_selects(s), _people_fence(s):
        return _refresh(
            s,
            ctx,
            pid,
            previous,
            change_id=change_id,
            purpose=purpose,
            graph=graph,
            origin_version=origin_version,
        )


def recheck_access(s, ctx, pid, previous, *, request, purpose):
    """Last non-byte fence after other owners' IO, in the same original UOW.

    Locks cannot prevent a trusted adapter's SQL in this very transaction from
    changing publisher access. Re-read it rather than trusting the prior hash.
    This cannot create a CoverageRead or replace the full read/refresh above.
    """
    _uow(s)
    with _fresh_selects(s), _people_fence(s):
        require(
            type(previous) in {CoverageRead, RetainedCoverageRead}
            and previous._token
            is (_RETAINED_TOKEN if type(previous) is RetainedCoverageRead else _READ_TOKEN)
            and previous._session is s
            and previous._proof_sha256 == common_digest(previous.source_basis)
        )
        _same_uow(s, previous._uow, ctx, previous._caller_hash)
        quiet(s)
        proof = previous.source_basis
        _, row = pointer(s, ctx, pid, request.scope, request.id, purpose)
        require(
            row is not None
            and (str(row.id), row.revision, row.epoch, row.material_sha256)
            == (proof["fact_id"], proof["revision"], proof["epoch"], proof["material_sha256"])
        )
        issuer = trust.current(s.get_bind(), request.scope)
        require(trust.stamp(issuer) == proof["issuer"] and row.issuer_stamp == proof["issuer"])
        signer_until = controlled.original_authority(s, ctx, pid, row)
        require(temporal(s, ctx, pid, request.scope)[0] == proof["temporal_sha256"])
        require(
            dependency_epoch(s, ctx, pid)
            == (
                previous.observed_dependency_epoch
                if type(previous) is RetainedCoverageRead
                else proof["dependency_epoch"]
            )
        )
        people, until = lock_people(s, ctx, pid, row.actor_id)
        publisher = next(v for v in people if v[0] == row.actor_id)
        require(common_digest(publisher) == proof["publisher_access_sha256"], status=403)
        quiet(s)
        _same_uow(s, previous._uow, ctx, previous._caller_hash)
        require(clock() < earliest_deadline(previous.valid_until, signer_until, until))
        return earliest_deadline(previous.valid_until, signer_until, until)
