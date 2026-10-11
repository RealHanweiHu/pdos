"""Read actual Build-bound resource facts under the existing caller transaction.

No persistence, issuer registration, callback, qualification or decision is
created. A fixed resource relation has a bounded Build scope, never global
Process completeness. Principal locks are the existing shared people fence;
their reuse confers no coverage fact, professional role or execution right.
"""

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from inspect import signature
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from pdos_next.change_graph_closure import (
    _fresh_selects,
    _pending_dependencies,
    closure_stamp,
    lock_dependency_clock,
)
from pdos_next.clock import deadline_current, earliest_deadline
from pdos_next.domain.build_operational_facts import service as operational
from pdos_next.domain.build_operational_facts.models import BuildOperationalFact, OperationalAsset
from pdos_next.domain.build_operational_facts.schemas import FactInput
from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow, _uow
from pdos_next.domain.change_coverage_owner.owner import (
    _people_fence,
    lock_people,
)
from pdos_next.domain.change_execution import service as change
from pdos_next.domain.configurations.service import _merge_reads
from pdos_next.errors import DomainError
from pdos_next.models import Product
from pdos_next.service import Context
from pdos_next.service import digest as caller_digest

from .relations import project
from .schemas import ResourceRequest, ResourceView, VersionRef

_READ_TOKEN = object()
VERSION = "manufacturing-resource-read-v2"
GAPS = (
    "NATIVE_ACCEPTANCE_OWNER_UNCONNECTED",
    "NATIVE_CALIBRATION_OWNER_UNCONNECTED",
    "NATIVE_QUALIFICATION_OWNER_UNCONNECTED",
    "RESOURCE_DOCUMENT_RELATION_UNKNOWN",
    "GLOBAL_PROCESS_RESOURCE_CLOSURE_UNKNOWN",
)


def clock():
    return datetime.now(UTC)


def require(test):
    if not test:
        raise DomainError("RESOURCE_RECHECK_REQUIRED", "固定资源依据或当前只读守卫需重新核对。")


@dataclass(frozen=True)
class ResourceRead:
    """Server-private same-UOW read; never accepted through a public DTO/API."""

    view: ResourceView
    source_basis: dict
    owner_id: UUID | None
    visibility: str | None
    _uow: object
    _caller: str
    _runtime: str
    _stamp: dict
    _people: tuple
    _deadline: datetime | None
    _basis: dict
    _hash: str
    _token: object


def _read_hash(value):
    return operational.digest(
        {
            "view": value.view,
            "sources": value.source_basis,
            "owner_id": value.owner_id,
            "visibility": value.visibility,
            "caller": value._caller,
            "runtime": value._runtime,
            "stamp": value._stamp,
            "people": value._people,
            "deadline": value._deadline,
            "basis": value._basis,
            "uow": ([id(node) for node in value._uow[0]], id(value._uow[1])),
        }
    )


def _audience(ctx):
    # Reads are narrowed to this named reader; no private data is made product-wide.
    return (f"private:{ctx.requester_id}",)


def _lock_product(s, ctx, product_id):
    """Canonical root row lock before people/Clock; never an access grant.

    operational._scope and common.execute already acquire this same Product
    first. Reacquiring our own row later cannot wait on a different transaction.
    Asset reads stay ordinary MVCC under the held Scope Clock, avoiding a
    Clock -> shared Asset tuple wait in this read-only adapter.
    """
    _uow(s)
    rows = list(
        s.scalars(
            select(Product)
            .where(Product.tenant_id == ctx.tenant_id, Product.id == product_id)
            .limit(2)
            .with_for_update()
            .execution_options(populate_existing=True, autoflush=False)
        )
    )
    if len(rows) != 1 or rows[0].tenant_id != ctx.tenant_id or rows[0].id != product_id:
        raise DomainError("FORBIDDEN_SCOPE", "资源读取不在当前型号范围。", 403)
    return rows[0]


def _read_assets(s, ctx, specifications):
    """Exact existing mirror SELECT, never a reservation/create/write or tuple lock.

    Before this helper, inspect holds the actual Scope Clock SHARE until UOW
    end. The trigger advances only clocks of actual physical references, so
    a concurrent writer of a referenced asset cannot commit first.
    Ordinary MVCC SELECT can read its prior committed mirror without waiting
    on that writer's tuple. Full identity/hash/current checks stay unchanged.
    The shared trigger/0014 identity/DDL ACL contract is a deployment prerequisite;
    without it this adapter cannot be wired. Read-only does not confer execution.
    """
    _uow(s)
    result = {}
    for kind, aid, key, identity, _revision, _data in specifications:
        rows = list(
            s.scalars(
                select(OperationalAsset)
                .where(OperationalAsset.tenant_id == ctx.tenant_id, OperationalAsset.id == aid)
                .limit(2)
                .execution_options(populate_existing=True, autoflush=False)
            )
        )
        if not rows:
            raise DomainError("OPERATIONAL_ASSET_MISSING", "全局物理身份尚不可核对。")
        require(len(rows) == 1)
        row = rows[0]
        if (
            row.id != aid
            or row.tenant_id != ctx.tenant_id
            or row.kind != kind
            or row.external_key != key
            or row.identity != identity
        ):
            raise DomainError("OPERATIONAL_IDENTITY_CONFLICT", "共享物理身份发生冲突。")
        if (
            type(row.data) is not dict
            or "value" not in row.data
            or operational.digest(row.data["value"]) != row.data_sha256
        ):
            raise DomainError("INTEGRITY_MISMATCH", "全局物理镜像摘要无法核对。")
        result[aid] = row
    return result


def _people_nowait(s, ctx, product_id, publisher_id):
    """Reuse Root's existing people owner with a fail-fast lock mode.

    Graph/common may already hold the Scope Clock. No People lock can wait
    behind a cross-product writer that holds that person and waits on our Clock.
    Missing Root seam is a configured integration failure, never a fallback.
    A 55P03 leaves the DB transaction failed; caller must roll back the whole UOW.
    """
    if "nowait" not in signature(lock_people).parameters:
        raise DomainError("RESOURCE_PEOPLE_NOWAIT_REQUIRED", "当前只读人员锁端口未接入。", 503)
    try:
        return lock_people(s, ctx, product_id, publisher_id, nowait=True)
    except DBAPIError as error:
        if getattr(error.orig, "sqlstate", None) == "55P03":
            raise DomainError(
                "RESOURCE_RECHECK_REQUIRED", "当前人员锁需整事务回滚后重核。"
            ) from None
        raise


def _pin(pointer, fact):
    return {
        "pointer": None
        if pointer is None
        else {
            key: deepcopy(getattr(pointer, key))
            for key in (
                "id",
                "tenant_id",
                "product_id",
                "project_id",
                "build_id",
                "fact_id",
                "fact_revision",
                "epoch",
            )
        },
        "fact": None
        if fact is None
        else {
            key: deepcopy(getattr(fact, key))
            for key in (
                "id",
                "tenant_id",
                "product_id",
                "project_id",
                "build_id",
                "build_revision",
                "revision",
                "owner_id",
                "visibility",
                "fact_sha256",
            )
        },
    }


def _preflight(s, ctx, request):
    """Only pin Current/Fact/publisher before the first Clock; no Source IO.

    Scope Product is already held. The pin is private and grants no visibility,
    Source trust or qualification; the full concrete owner runs after the Clock.
    """
    pointer = operational._pointer(s, ctx, request.scope.product_id, request.build.id)
    try:
        fact = _fact(s, ctx, request, pointer)
    except DomainError as error:
        if error.status != 403:
            raise
        return {"availability": "unknown"}, None
    return _pin(pointer, fact), fact.owner_id if fact is not None else None


def _issuer(s, ctx, request, fact):
    engine = s.get_bind()
    value = getattr(engine, "_pdos_operational_issuers", {}).get(fact.issuer_key)
    epochs = getattr(engine, "_pdos_operational_issuer_epochs", {})
    current = (
        type(value) is operational.IssuerContext
        and value._token is operational._TOKEN
        and value.tenant_id == ctx.tenant_id
        and value.product_id == request.scope.product_id
        and value.project_id in (None, request.scope.project_id)
        and value.key == fact.issuer_key
        and value.version == fact.issuer_version
        and value.epoch == fact.issuer_epoch
        and epochs.get(fact.issuer_key) == value.epoch
        and value.nature == fact.nature
    )
    return current, {
        "current": current,
        "identity": id(value),
        "epoch": epochs.get(fact.issuer_key),
        "value": None
        if value is None
        else {
            "key": getattr(value, "key", None),
            "version": getattr(value, "version", None),
            "tenant_id": getattr(value, "tenant_id", None),
            "product_id": getattr(value, "product_id", None),
            "project_id": getattr(value, "project_id", None),
            "nature": getattr(value, "nature", None),
            "epoch": getattr(value, "epoch", None),
            "verifier_identity": id(getattr(value, "verify_named_decision", None)),
        },
    }


def _fact(s, ctx, request, pointer):
    ref = request.fact
    identity = ref.id if ref else pointer.fact_id if pointer else None
    if identity is None:
        return None
    rows = list(
        s.scalars(
            select(BuildOperationalFact)
            .where(
                BuildOperationalFact.tenant_id == ctx.tenant_id,
                BuildOperationalFact.product_id == request.scope.product_id,
                BuildOperationalFact.build_id == request.build.id,
                BuildOperationalFact.id == identity,
            )
            .limit(2)
            .execution_options(populate_existing=True, autoflush=False)
        )
    )
    require(len(rows) <= 1)
    if not rows:
        return None
    row = rows[0]
    require(
        row.tenant_id == ctx.tenant_id
        and row.product_id == request.scope.product_id
        and row.build_id == request.build.id
    )
    if row.visibility == "private" and row.owner_id != ctx.requester_id:
        raise DomainError("FORBIDDEN_SCOPE", "资源依据当前不可用。", 403)
    require(ref is None or row.revision == ref.revision)
    require(row.project_id == request.scope.project_id)
    return row


def _material(s, ctx, request, *, io, pin):
    """Reuse concrete operational owner roots plus actual Source byte validation."""
    pid, bid = request.scope.product_id, request.build.id
    pointer = operational._pointer(s, ctx, pid, bid)
    try:
        fact = _fact(s, ctx, request, pointer)
    except DomainError as error:
        if error.status == 403:
            require(pin == {"availability": "unknown"})
        raise
    require(_pin(pointer, fact) == pin)
    build, eng, process, build_reads, scope, execution = operational._scope(
        s, ctx, pid, bid, request.execution, write=False
    )
    require(scope == request.scope and execution == request.execution)
    require(build.revision == request.build.revision)
    require(process["id"] == str(request.process.id))
    require(process["revision"] == request.process.revision)
    require(len([op for op in process["operations"] if op["key"] == request.operation_key]) == 1)
    # A Process with an explicit site cannot apply to a different site.
    require(process.get("site") in (None, request.execution.site))
    pointer_basis = (
        None
        if pointer is None
        else {
            key: deepcopy(getattr(pointer, key))
            for key in (
                "id",
                "tenant_id",
                "product_id",
                "project_id",
                "build_id",
                "fact_id",
                "fact_revision",
                "epoch",
            )
        }
    )
    if pointer is not None:
        require(
            pointer.tenant_id == ctx.tenant_id
            and pointer.product_id == pid
            and pointer.build_id == bid
            and pointer.project_id == scope.project_id
            and type(pointer.epoch) is int
            and pointer.epoch > 0
        )
    binding = operational._binding(build, eng, process, execution)
    basis = {
        "version": VERSION,
        "binding": binding,
        "engineering": deepcopy(eng),
        "process": deepcopy(process),
        "build_reads": deepcopy(build_reads),
        "pointer": pointer_basis,
    }
    if fact is None:
        return basis, None, None, (), {}, (), None, None
    require(fact.build_revision == build.revision and fact.binding == binding)
    require(operational._fact_hash(fact) == fact.fact_sha256)
    data = FactInput.model_validate(fact.data)
    require(
        data.build_id == bid
        and data.expected_build_revision == build.revision
        and data.scope == execution
        and data.state == fact.state
        and data.valid_from == fact.valid_from
        and data.valid_until == fact.valid_until
        and operational._sources(data) == fact.sources
    )
    people, people_until = _people_nowait(s, ctx, pid, fact.owner_id)
    evidence_reads, private, source_basis = operational._evidence_basis(
        s, ctx, pid, fact.sources, build_reads
    )
    reads = _merge_reads(build_reads, evidence_reads)
    require(reads == fact.required_source_read_set)
    # Caller independently needs every reference; publisher access never widens it.
    operational._evidence(s, ctx, pid, fact.sources)
    bytes_basis, caller_private, _ = change._evidence(s, ctx, pid, reads, io=io)
    require(fact.visibility != "category" or not (private or caller_private))
    specs = operational._assets(data, ctx.tenant_id)
    assets = _read_assets(s, ctx, specs)
    asset_basis, assets_current = [], True
    for kind, aid, key, identity, revision, physical in specs:
        asset = assets[aid]
        require(asset.tenant_id == ctx.tenant_id)
        require(type(asset.occupancy_epoch) is int and asset.occupancy_epoch > 0)
        assets_current &= (
            asset.revision == revision
            and asset.data_sha256 == operational.digest(physical)
            and asset.data == {"value": physical, "state": "active"}
        )
        asset_basis.append(
            {
                "kind": kind,
                "id": aid,
                "key": key,
                "identity": identity,
                "revision": asset.revision,
                "sha256": asset.data_sha256,
                "data": deepcopy(asset.data),
                "occupancy_epoch": asset.occupancy_epoch,
            }
        )
    issuer_current, issuer_basis = _issuer(s, ctx, request, fact)
    current = (
        pointer is not None
        and pointer.fact_id == fact.id
        and pointer.fact_revision == fact.revision
        and fact.state == "active"
        and issuer_current
        and assets_current
        and operational.evidence_watermark(source_basis)
        == operational.evidence_watermark(fact.source_basis)
        and eng["source_status"] == process["source_status"] == "current"
        and fact.valid_from <= clock()
        and deadline_current(fact.valid_until, clock())
        and fact.valid_from <= execution.window.start
        and (fact.valid_until is None or fact.valid_until >= execution.window.finish)
        and clock() < execution.window.finish
    )
    basis.update(
        {
            "fact": {key: deepcopy(getattr(fact, key)) for key in operational._FACT_FIELDS},
            "fact_sha256": fact.fact_sha256,
            "source_basis": source_basis,
            "byte_source_basis": bytes_basis,
            "assets": asset_basis,
            "issuer": issuer_basis,
            "current": current,
        }
    )
    return basis, fact, data, tuple(reads), bytes_basis, people, people_until, current


def _view(request, basis, fact, data, reads, deadline, current):
    gaps = list(GAPS)
    resources, relations = (), ()
    if fact is not None and (current or request.fact is not None):
        resources, relations, relation_gaps = project(fact, data, request, current=current)
        gaps.extend(relation_gaps)
    else:
        gaps.append("RESOURCE_BASIS_UNKNOWN")
    state = "known" if relations else "historical" if resources else "unknown"
    if not current:
        gaps.append("CURRENT_RESOURCE_APPLICABILITY_UNKNOWN")
    # A missing/hidden root never discloses a discovered identity or source.
    disclosed = bool(resources)
    return ResourceView(
        request=request,
        state=state,
        current=bool(relations),
        fact=VersionRef(id=fact.id, revision=fact.revision) if disclosed else None,
        fact_sha256=fact.fact_sha256 if disclosed else None,
        nature=fact.nature if disclosed else "unknown",
        resources=resources,
        relations=relations,
        required_source_read_set=reads if disclosed else (),
        facts_revision=operational.digest(basis),
        valid_until=deadline,
        fact_valid_until=fact.valid_until if disclosed else None,
        gaps=tuple(sorted(set(gaps))),
    )


def inspect_resource(s, ctx, product_id, *, request):
    """Read-only current or explicitly historical fixed Build resource projection."""
    require(type(ctx) is Context)
    request = ResourceRequest.model_validate(request).model_copy(deep=True)
    require(request.scope.tenant_id == ctx.tenant_id)
    require(request.scope.product_id == product_id)
    require(ctx.actor_id == ctx.requester_id and ctx.run_id is None)
    uow, caller, runtime = _uow(s), caller_digest(vars(ctx)), change._runtime_stamp(s)
    with _people_fence(s), _fresh_selects(s):
        _pending_dependencies(s)
        _lock_product(s, ctx, product_id)
        pin, publisher_id = _preflight(s, ctx, request)
        caller_people, caller_until = _people_nowait(
            s, ctx, product_id, publisher_id or ctx.requester_id
        )
        lock_dependency_clock(s, ctx, scope=request.scope, audience=_audience(ctx))
        stamp = closure_stamp(s, ctx, scope=request.scope, audience=_audience(ctx))
        try:
            basis, fact, data, reads, sources, people, until, current = _material(
                s, ctx, request, io=True, pin=pin
            )
        except DomainError as error:
            # Caller access was already positively locked above. Hidden discovered
            # dependencies supply only a generic unknown; no ID/readset is emitted.
            if error.status != 403 and error.reason not in {
                "OPERATIONAL_ASSET_MISSING",
                "SOURCE_UNAVAILABLE",
                "SOURCE_STALE",
                "INTEGRATION_REQUIRED",
            }:
                raise
            basis, fact, data, reads, sources, people, until, current = (
                {"version": VERSION, "availability": "unknown"},
                None,
                None,
                (),
                {},
                caller_people,
                caller_until,
                False,
            )
        basis = deepcopy(basis)
        # Historical access may outlive the immutable fact's application window;
        # it has no current relations/rights and exposes the original deadline.
        deadline = earliest_deadline(caller_until, until)
        if current and fact is not None:
            deadline = earliest_deadline(
                deadline, fact.valid_until, request.execution.window.finish
            )
        # Full concrete metadata pass after the only byte IO, without rereading
        # bytes. Row locks and the real dependency clock remain until UOW end.
        if fact is not None:
            final = _material(s, ctx, request, io=False, pin=pin)
            require(final[0] == basis and final[5] == people)
        require(closure_stamp(s, ctx, scope=request.scope, audience=_audience(ctx)) == stamp)
        require(
            _people_nowait(s, ctx, product_id, publisher_id or ctx.requester_id)[0]
            == (people if fact else caller_people)
        )
        _pending_dependencies(s)
        _same_uow(s, uow, ctx, caller)
        view = _view(request, basis, fact, data, reads, deadline, current)
        require(change._runtime_stamp(s) == runtime)
        require(fact is None or _issuer(s, ctx, request, fact)[1] == basis["issuer"])
        require(deadline_current(deadline, clock()))
        result = ResourceRead(
            view,
            deepcopy(sources),
            fact.owner_id if view.fact else None,
            fact.visibility if view.fact else None,
            uow,
            caller,
            runtime,
            deepcopy(stamp),
            people,
            deadline,
            basis,
            "",
            _READ_TOKEN,
        )
        result = replace(result, _hash=_read_hash(result))
        require(deadline_current(deadline, clock()))
        return result


def refresh_resource(s, ctx, product_id, previous):
    """Re-read the exact saved request in the same UOW; never extend its deadline."""
    require(type(previous) is ResourceRead and previous._token is _READ_TOKEN)
    require(_read_hash(previous) == previous._hash)
    _same_uow(s, previous._uow, ctx, previous._caller)
    require(
        deadline_current(previous._deadline, clock())
        and change._runtime_stamp(s) == previous._runtime
    )
    current = inspect_resource(s, ctx, product_id, request=previous.view.request)
    require(
        current._basis == previous._basis
        and current._stamp == previous._stamp
        and current._people == previous._people
        and current._deadline == previous._deadline
        and current._hash == previous._hash
    )
    _same_uow(s, previous._uow, ctx, previous._caller)
    require(change._runtime_stamp(s) == previous._runtime)
    require(deadline_current(previous._deadline, clock()))
    return current


def operation_resources(s, ctx, product_id, *, request):
    """Bounded Build operation only; complete=False even for zero visible rows."""
    request = ResourceRequest.model_validate(request)
    require(request.resource is None)
    return inspect_resource(s, ctx, product_id, request=request)
