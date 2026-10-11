"""Opaque host imports and caller-UOW material/resource facts, never self-grants.

No connector network, commit, receipt, default positive qualification, fabricated
TestRun or second BOM expansion is owned here. The host owns trusted issuers,
existing named decision verification, scoped receipt/audit/outbox, and start FK.
"""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from pdos_next.contracts import SourceRead
from pdos_next.domain.builds.demand import load_bound_demand
from pdos_next.domain.builds.service import _build, _linked
from pdos_next.domain.professional_authority.service import _evidence
from pdos_next.domain.resource_readiness.rules import aggregate, capacity_exceeded, evaluate
from pdos_next.engines.supply_cost import calculate_coverage
from pdos_next.engines.supply_cost.common import SnapshotRef
from pdos_next.engines.supply_cost.dto import (
    CoverageRequest,
    PoolKey,
    ReservationSnapshot,
    SupplyPool,
)
from pdos_next.engines.supply_cost.units import conversion
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Principal, Product, now
from pdos_next.schemas.resource_readiness.contracts import (
    Check,
    MaintenanceFact,
    Occupancy,
    QualificationFact,
    ReadinessReport,
    Reservation,
    ReservationEvent,
    ReservationRequest,
    ResourceContext,
    ResourceSnapshot,
    ResourceUse,
)
from pdos_next.schemas.supply_cost.dto import Scope as DemandScope
from pdos_next.schemas.verification.contracts import Scope, SourceRef
from pdos_next.service import digest as _raw_digest
from pdos_next.service import require_access

from .models import (
    BuildOperationalCurrent,
    BuildOperationalFact,
    MaterialHold,
    OperationalAsset,
    ResourceOccupancy,
)
from .schemas import (
    DecisionProof,
    FactInput,
    FactRef,
    OperationalBundle,
    OperationalCheck,
    OperationalScope,
    ReservationResult,
)

_TOKEN = object()


def digest(value):
    """Engine-compatible Decimal/time normalization plus scoped UUID support."""

    def canonical(v):
        kind = type(v)
        if v is None or kind is str or kind is bool or kind is int or kind is float:
            return v
        if isinstance(v, BaseModel):
            return canonical(v.model_dump(mode="python"))
        if isinstance(v, UUID):
            return str(v)
        if isinstance(v, Decimal):
            text = format(v, "f")
            return (text.rstrip("0").rstrip(".") if "." in text else text) if v else "0"
        if isinstance(v, datetime):
            return v.astimezone(UTC).isoformat()
        if isinstance(v, dict):
            return {key: canonical(child) for key, child in v.items()}
        if isinstance(v, (tuple, list)):
            return [canonical(child) for child in v]
        return v

    return _raw_digest(canonical(value))


@dataclass(frozen=True)
class IssuerContext:
    key: str
    version: str
    tenant_id: UUID
    product_id: UUID
    project_id: UUID | None
    nature: str
    epoch: int
    verify_named_decision: Callable | None
    _token: object


def configure_issuer(
    engine,
    *,
    key,
    version,
    tenant_id,
    product_id,
    project_id=None,
    verify_named_decision=None,
):
    """Host provisioning after external issuer verification; never a public DTO."""
    return _configure(
        engine, key, version, tenant_id, product_id, project_id, "real", verify_named_decision
    )


def configure_local_synthetic(
    engine,
    *,
    tenant_id,
    product_id,
    project_id=None,
    key="synthetic-operational-facts",
    version="v1",
    enabled=False,
    test_marker_verified=False,
    verify_named_decision=None,
):
    """Host must verify its exact own isolated environment before opting in."""
    if enabled is not True or test_marker_verified is not True:
        raise ValueError("Synthetic operational facts require an exact verified host marker")
    return _configure(
        engine, key, version, tenant_id, product_id, project_id, "synthetic", verify_named_decision
    )


def _configure(engine, key, version, tenant_id, product_id, project_id, nature, verifier):
    if (
        not all(isinstance(v, str) and v.strip() and len(v) <= 100 for v in (key, version))
        or not isinstance(tenant_id, UUID)
        or not isinstance(product_id, UUID)
        or (project_id is not None and not isinstance(project_id, UUID))
        or (verifier is not None and not callable(verifier))
    ):
        raise ValueError("Exact host issuer/version/scope and a callable verifier are required")
    epochs = dict(getattr(engine, "_pdos_operational_issuer_epochs", {}))
    epochs[key] = epochs.get(key, 0) + 1
    issuer = IssuerContext(
        key, version, tenant_id, product_id, project_id, nature, epochs[key], verifier, _TOKEN
    )
    registry = dict(getattr(engine, "_pdos_operational_issuers", {}))
    registry[key] = issuer
    engine._pdos_operational_issuers = registry
    engine._pdos_operational_issuer_epochs = epochs
    return issuer


def disable_issuer(engine, key):
    registry = dict(getattr(engine, "_pdos_operational_issuers", {}))
    registry.pop(key, None)
    engine._pdos_operational_issuers = registry
    epochs = dict(getattr(engine, "_pdos_operational_issuer_epochs", {}))
    epochs[key] = epochs.get(key, 0) + 1
    engine._pdos_operational_issuer_epochs = epochs


def _aware(at):
    if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None:
        raise DomainError("INVALID_OPERATIONAL_TIME", "权威事实时点须含时区。", 422)
    at = at.astimezone(UTC)
    if at > now():
        raise DomainError("INVALID_OPERATIONAL_TIME", "权威核对时点不能在未来。", 422)
    return at


def _session(s):
    if not isinstance(s, Session) or not s.in_transaction():
        raise DomainError("INTEGRATION_REQUIRED", "事实和占用须参加当前共同事务。")


def _issuer(s, ctx, pid, project_id, issuer):
    registry = getattr(s.get_bind(), "_pdos_operational_issuers", {})
    if (
        not isinstance(issuer, IssuerContext)
        or issuer._token is not _TOKEN
        or registry.get(issuer.key) is not issuer
        or issuer.tenant_id != ctx.tenant_id
        or issuer.product_id != pid
        or (issuer.project_id is not None and issuer.project_id != project_id)
    ):
        raise DomainError("TRUSTED_ISSUER_REQUIRED", "缺少当前精确范围的可信事实签发端口。", 403)
    return issuer


def _scope(s, ctx, pid, bid, execution_scope, *, write=False):
    _session(s)
    execution_scope = OperationalScope.model_validate(execution_scope)
    from pdos_next.request_proof import scoped_rows

    products = scoped_rows(
        s,
        (Product, pid),
        select(Product).where(Product.id == pid, Product.tenant_id == ctx.tenant_id),
        lock=write,
    )
    product = products[0] if products else None
    if product is None:
        raise DomainError("FORBIDDEN_SCOPE", "实际事实不在当前型号范围。", 403)
    require_access(s, ctx, pid, write=write, lock=write)
    principal = s.get(Principal, ctx.requester_id)
    if ctx.actor_id != ctx.requester_id or ctx.run_id or principal.kind != "human":
        raise DomainError("NAMED_PERSON_REQUIRED", "实际输入与开工事实由本人受控办理。", 403)
    build = _build(s, ctx, pid, bid)
    _, engineering, manufacturing, reads = _linked(s, ctx, pid, build)
    if execution_scope.quantity != build.planned_quantity or execution_scope.unit != build.unit:
        raise DomainError(
            "OPERATIONAL_SCOPE_MISMATCH", "执行量和单位须精确等于固定Build计划。", 409
        )
    scope = Scope(tenant_id=ctx.tenant_id, product_id=pid, project_id=build.project_id)
    return build, engineering, manufacturing, reads, scope, execution_scope


def _sources(data):
    refs = {}

    def visit(value):
        if isinstance(value, dict):
            if {"artifact_id", "expected_revision", "line", "quote"} <= set(value):
                refs[digest(value)] = value
            else:
                for child in value.values():
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(data.model_dump(mode="json"))
    return [refs[key] for key in sorted(refs)]


def _physical(value):
    """Non-consuming global mirror; scoped immutable Fact retains every source."""
    if isinstance(value, dict):
        return {
            key: _physical(child)
            for key, child in value.items()
            if key not in {"sources", "calendar_sources", "source"}
        }
    if isinstance(value, list):
        return [_physical(child) for child in value]
    return value


def _assets(data, tenant_id):
    result = []
    for material in data.materials:
        identity = material.key.model_dump(mode="json")
        key = digest(identity)
        aid = uuid5(NAMESPACE_URL, f"pdos:material:{tenant_id}:{key}")
        result.append(
            (
                "material",
                aid,
                key,
                identity,
                material.version,
                _physical(material.model_dump(mode="json")),
            )
        )
    for resource in data.resources:
        identity = resource.resource.model_dump(mode="json", exclude={"revision"})
        key = digest(identity)
        result.append(
            (
                "resource",
                resource.resource.id,
                key,
                identity,
                resource.resource.revision,
                _physical(resource.model_dump(mode="json")),
            )
        )
    return sorted(result, key=lambda value: (value[0], value[1].bytes))


def _locked_assets(s, ctx, specifications, *, create=False, lock=True):
    from pdos_next.request_proof import batch_read

    specifications = list(specifications)
    if create and specifications:
        s.execute(
            insert(OperationalAsset)
            .values(
                [
                    dict(
                        id=aid,
                        tenant_id=ctx.tenant_id,
                        kind=kind,
                        external_key=key,
                        identity=identity,
                        revision=revision,
                        data_sha256=digest(data),
                        data={"value": data, "state": "active"},
                        occupancy_epoch=1,
                    )
                    for kind, aid, key, identity, revision, data in specifications
                ]
            )
            .on_conflict_do_nothing()
        )
    rows = batch_read(s, OperationalAsset, [spec[1] for spec in specifications], lock=lock)
    result = {}
    for kind, aid, key, identity, _revision, _data in specifications:
        row = rows.get(aid)
        if row is None or row.tenant_id != ctx.tenant_id:
            raise DomainError("OPERATIONAL_ASSET_MISSING", "全局物理身份尚不可核对。")
        if row.kind != kind or row.external_key != key or row.identity != identity:
            raise DomainError("OPERATIONAL_IDENTITY_CONFLICT", "共享物理身份发生冲突。")
        if digest(row.data["value"]) != row.data_sha256:
            raise DomainError("INTEGRITY_MISMATCH", "全局物理镜像摘要无法核对。")
        result[aid] = row
    return result


def _pointer(s, ctx, pid, bid, *, lock=False):
    from pdos_next.request_proof import scoped_rows

    rows = scoped_rows(
        s,
        (BuildOperationalCurrent, bid),
        select(BuildOperationalCurrent).where(
            BuildOperationalCurrent.tenant_id == ctx.tenant_id,
            BuildOperationalCurrent.product_id == pid,
            BuildOperationalCurrent.build_id == bid,
        ),
        lock=lock,
    )
    return rows[0] if rows else None


def _binding(build, engineering, manufacturing, scope):
    return {
        "build_id": str(build.id),
        "build_revision": build.revision,
        "project_id": str(build.project_id),
        "scope": scope.model_dump(mode="json"),
        "engineering_configuration_id": engineering["id"],
        "engineering_configuration_revision": engineering["revision"],
        "manufacturing_configuration_id": manufacturing["id"],
        "manufacturing_configuration_revision": manufacturing["revision"],
    }


def _evidence_basis(s, ctx, product_id, sources, required_reads=()):
    reads, private, basis = _evidence(s, ctx, product_id, sources)
    from pdos_next.domain.professional_authority.service import _subject_access
    from pdos_next.original_security import security_row
    from pdos_next.originals import require_original
    from pdos_next.request_proof import batch_read

    principal, grant = _subject_access(s, ctx, product_id, ctx.requester_id)
    artifacts = batch_read(s, Artifact, [UUID(str(read["artifact_id"])) for read in required_reads])
    security = []
    for read in sorted(required_reads, key=lambda v: str(v["artifact_id"])):
        artifact = artifacts[UUID(str(read["artifact_id"]))]
        if artifact.original_id:
            original = require_original(s, ctx, product_id, artifact.original_id)
            state = security_row(s, original, lock=False)
            security.append(
                {
                    "artifact_id": str(artifact.id),
                    "original_id": str(artifact.original_id),
                    "epoch": state.epoch if state else None,
                    "source_state": state.source_state if state else None,
                    "disposition": state.disposition if state else None,
                }
            )
    return (
        reads,
        private,
        {
            **basis,
            "fixed_readset_security": security,
            "access": {
                "principal_id": str(principal.id),
                "principal_epoch": principal.access_epoch,
                "grant_id": str(grant.id),
                "grant_epoch": grant.access_epoch,
            },
        },
    )


def evidence_watermark(basis):
    """The importer's recorded access is provenance; readers prove their own access."""
    return {key: value for key, value in basis.items() if key != "access"}


def trusted_import(s, ctx, issuer, data):
    """No receipt/commit here; host importer appends its common audit atomically."""
    data = FactInput.model_validate(data)
    build, eng, mfg, reads, _, execution_scope = _scope(
        s,
        ctx,
        issuer.product_id if isinstance(issuer, IssuerContext) else UUID(int=0),
        data.build_id,
        data.scope,
        write=True,
    )
    issuer = _issuer(s, ctx, build.product_id, build.project_id, issuer)
    at = now()
    if data.expected_build_revision != build.revision or data.valid_from > at:
        raise DomainError("OPERATIONAL_SCOPE_MISMATCH", "Build版本或事实生效时间不匹配。")
    if any(v.observed_at > at for v in data.materials):
        raise DomainError("INVALID_OPERATIONAL_TIME", "物料观察不能来自未来。", 422)
    sources = _sources(data)
    evidence_reads, private, source_basis = _evidence_basis(
        s, ctx, build.product_id, sources, reads
    )
    # Semantic host replay is read-only and never rewinds a later current pointer
    # or global physical version. The wrapper must locate its original receipt.
    replay = s.scalar(
        select(BuildOperationalFact).where(
            BuildOperationalFact.tenant_id == ctx.tenant_id,
            BuildOperationalFact.product_id == build.product_id,
            BuildOperationalFact.build_id == build.id,
            BuildOperationalFact.owner_id == ctx.requester_id,
            BuildOperationalFact.issuer_key == issuer.key,
            BuildOperationalFact.issuer_version == issuer.version,
            BuildOperationalFact.issuer_epoch == issuer.epoch,
            BuildOperationalFact.data == data.model_dump(mode="json"),
        )
    )
    if replay:
        if _fact_hash(replay) != replay.fact_sha256 or replay.binding != _binding(
            build, eng, mfg, execution_scope
        ):
            raise DomainError("INTEGRITY_MISMATCH", "原导入的固定绑定或摘要无法核对。")
        if replay.source_basis != source_basis:
            raise DomainError(
                "OPERATIONAL_FACTS_CHANGED", "原导入来源或权限已经变化，须重新核对新版。"
            )
        return replay
    pointer = _pointer(s, ctx, build.product_id, build.id, lock=True)
    previous = s.get(BuildOperationalFact, pointer.fact_id) if pointer else None
    if (previous.id if previous else None) != data.expected_previous_id or (
        previous.revision if previous else 0
    ) != data.expected_previous_revision:
        raise DomainError("VERSION_CONFLICT", "权威事实当前版已变化。")
    if previous and (
        previous.issuer_key != issuer.key
        or previous.external_id != data.external_id
        or previous.owner_id != ctx.requester_id
        or previous.binding != _binding(build, eng, mfg, execution_scope)
    ):
        raise DomainError("OPERATIONAL_SCOPE_MISMATCH", "事实续版不能换签发主体、范围或所有者。")
    required = {v["artifact_id"]: v for v in [*reads, *evidence_reads]}
    if build.visibility == "category" and private:
        raise DomainError("FORBIDDEN_SCOPE", "私人事实不能扩大到共享Build。", 403)
    specs = _assets(data, ctx.tenant_id)
    assets = _locked_assets(s, ctx, specs, create=True)
    for _, aid, _, _, revision, physical in specs:
        row = assets[aid]
        if revision < row.revision or (
            revision == row.revision and digest(physical) != row.data_sha256
        ):
            raise DomainError("OPERATIONAL_ASSET_VERSION_CONFLICT", "共享物理版本或同版内容冲突。")
        desired = {"value": physical, "state": data.state}
        if row.revision != revision or row.data != desired:
            row.revision, row.data_sha256, row.data = revision, digest(physical), desired
            row.occupancy_epoch += 1
    identity = uuid4()
    fact = BuildOperationalFact(
        id=identity,
        tenant_id=ctx.tenant_id,
        product_id=build.product_id,
        project_id=build.project_id,
        build_id=build.id,
        build_revision=build.revision,
        owner_id=ctx.requester_id,
        visibility=build.visibility,
        issuer_key=issuer.key,
        issuer_version=issuer.version,
        issuer_epoch=issuer.epoch,
        nature=issuer.nature,
        external_id=data.external_id,
        series_id=previous.series_id if previous else identity,
        revision=previous.revision + 1 if previous else 1,
        previous_id=previous.id if previous else None,
        previous_revision=previous.revision if previous else None,
        state=data.state,
        valid_from=data.valid_from,
        valid_until=data.valid_until,
        binding=_binding(build, eng, mfg, execution_scope),
        data=data.model_dump(mode="json"),
        sources=sources,
        required_source_read_set=[required[key] for key in sorted(required)],
        source_basis=source_basis,
        fact_sha256="0" * 64,
        reason=data.reason,
    )
    fact.fact_sha256 = _fact_hash(fact)
    s.add(fact)
    s.flush()
    if pointer:
        pointer.fact_id, pointer.fact_revision, pointer.epoch = (
            fact.id,
            fact.revision,
            pointer.epoch + 1,
        )
    else:
        s.add(
            BuildOperationalCurrent(
                tenant_id=ctx.tenant_id,
                product_id=build.product_id,
                project_id=build.project_id,
                build_id=build.id,
                fact_id=fact.id,
                fact_revision=fact.revision,
                epoch=1,
            )
        )
    s.flush()
    return fact


_FACT_FIELDS = (
    "id",
    "tenant_id",
    "product_id",
    "project_id",
    "build_id",
    "build_revision",
    "owner_id",
    "visibility",
    "issuer_key",
    "issuer_version",
    "issuer_epoch",
    "nature",
    "external_id",
    "series_id",
    "revision",
    "previous_id",
    "previous_revision",
    "state",
    "valid_from",
    "valid_until",
    "binding",
    "data",
    "sources",
    "required_source_read_set",
    "source_basis",
    "reason",
)


def _fact_hash(fact):
    def value(v):
        return str(v) if isinstance(v, UUID) else v.isoformat() if isinstance(v, datetime) else v

    return digest({key: value(getattr(fact, key)) for key in _FACT_FIELDS})


def _source(fact, position):
    return SourceRef(id=fact.id, revision=fact.revision, kind="domain", position=position)


def _asset_ref(fact, asset, observed_at):
    return SnapshotRef(
        source_id=f"operational-asset:{asset.id}",
        version=str(asset.revision),
        sha256=asset.data_sha256,
        captured_at=observed_at,
        valid_until=fact.valid_until,
        state="current",
    )


def _check(dimension, code, status, detail):
    return OperationalCheck(dimension=dimension, code=code, status=status, detail=detail)


def _proof(s, ctx, issuer, fact, resource, decision, at):
    if (
        decision.status != "accepted"
        or not isinstance(issuer, IssuerContext)
        or issuer._token is not _TOKEN
        or issuer.version != fact.issuer_version
        or issuer.epoch != fact.issuer_epoch
        or issuer.verify_named_decision is None
    ):
        return None
    proof = issuer.verify_named_decision(s, ctx, fact.binding, resource.resource, decision, at)
    return DecisionProof.model_validate(proof) if proof is not None else None


def _material_coverage(s, ctx, fact, data, bound, assets, at, excluded_owner):
    pools, reservations = [], []
    asset_specs = {digest(v.key): v for v in data.materials}
    material_assets = {aid: row for aid, row in assets.items() if row.kind == "material"}
    for asset in material_assets.values():
        material = asset_specs[digest(PoolKey.model_validate(asset.identity))]
        ref = _asset_ref(fact, asset, material.observed_at)
        pools.append(
            SupplyPool(
                key=material.key,
                ref=ref,
                stage=material.stage,
                quantity=material.quantity,
                unit=material.unit,
                availability=material.availability,
                quality=material.quality,
            )
        )
        for held in material.external_holds:
            reservations.append(
                ReservationSnapshot(
                    reservation_id=f"external:{material.key.source_system}:{held.id}",
                    ref=ref,
                    pool=material.key,
                    build_id=held.build_id,
                    bom_item_id=held.bom_item_id,
                    quantity=held.quantity,
                    unit=held.unit,
                )
            )
    from .physical_summary import capacity_summary

    holds = capacity_summary(
        s,
        ctx,
        fact.product_id,
        "material",
        material_assets,
        own=excluded_owner,
        watermark=tuple((aid, assets[aid].occupancy_epoch) for aid in sorted(material_assets)),
    )
    for held in holds:
        asset = assets[UUID(held["asset_id"])]
        material = asset_specs[digest(PoolKey.model_validate(asset.identity))]
        reservations.append(
            ReservationSnapshot(
                reservation_id=f"physical-capacity:{asset.id}:{held['unit']}",
                ref=_asset_ref(fact, asset, material.observed_at),
                pool=material.key,
                build_id="other-builds",
                bom_item_id=None,
                quantity=Decimal(str(held["quantity"])),
                unit=held["unit"],
            )
        )
    # Keep exact global rows for accounting, but never expose another Build's
    # private identity or per-line quantity in this Build's computation DTO.
    own, foreign = [], defaultdict(list)
    for held in reservations:
        if held.build_id == str(fact.build_id):
            own.append(held)
        else:
            foreign[held.pool].append(held)
    pool_by_key = {pool.key: pool for pool in pools}
    for key, values in sorted(foreign.items(), key=lambda v: digest(v[0])):
        pool = pool_by_key[key]
        quantity = Decimal(0)
        with localcontext() as context:
            context.prec = 60
            for held in values:
                factor = conversion(held.unit, pool.unit)
                if held.quantity is None or factor is None:
                    quantity = None
                    break
                quantity += held.quantity * factor
            if quantity is not None and (
                quantity >= Decimal("10000000000000000")
                or quantity != quantity.quantize(Decimal("0.00000001"))
            ):
                quantity = None
        own.append(
            ReservationSnapshot(
                reservation_id=f"foreign-aggregate:{digest(key)}",
                ref=values[0].ref,
                pool=key,
                build_id="other-builds",
                bom_item_id=None,
                quantity=quantity,
                unit=pool.unit,
            )
        )
    result = calculate_coverage(
        CoverageRequest(
            as_of=at,
            basis=bound.basis,
            supply_snapshot=SnapshotRef(
                source_id=f"operational-fact:{fact.id}",
                version=str(fact.revision),
                sha256=fact.fact_sha256,
                captured_at=max(fact.created_at, fact.valid_from),
                valid_until=fact.valid_until,
                state="current",
            ),
            supply_scope_complete=data.materials_scope_complete
            and all(v.external_holds_complete for v in data.materials),
            pools=tuple(pools),
            reservations=tuple(own),
        )
    )
    if tuple(v.demand for v in result.lines) != bound.demand.lines:
        if sorted((v.demand for v in result.lines), key=lambda v: v.item_id) != sorted(
            bound.demand.lines, key=lambda v: v.item_id
        ):
            raise DomainError("INTEGRITY_MISMATCH", "齐套必须消费已存同次完整需求。")
    return result


def _resource_report(s, ctx, fact, data, bound, scope, assets, issuer, at, excluded_owner):
    snapshots, checks, reports, proofs, total = {}, [], [], [], defaultdict(Decimal)
    vscope = Scope(tenant_id=ctx.tenant_id, product_id=fact.product_id, project_id=fact.project_id)
    required_keys = set(bound.manufacturing_operation_ids or ())
    if not required_keys or {v.operation_key for v in data.requirements} != required_keys:
        checks.append(
            Check(
                code="operation_requirements_incomplete",
                status="UNKNOWN",
                detail="全部固定制造工序的资源要求尚未核实。",
            )
        )
    resources = {v.resource.id: v for v in data.resources}
    required_ids = {u.resource.id for v in data.requirements for u in v.uses}
    if set(resources) != required_ids:
        checks.append(
            Check(
                code="resource_set_incomplete",
                status="UNKNOWN",
                detail="资源全集与受控工序要求不能一致核对。",
            )
        )
    occupancies = []
    for resource in data.resources:
        asset = assets[resource.resource.id]
        decisions = []
        for decision in resource.facts:
            proof = _proof(s, ctx, issuer, fact, resource, decision, at)
            proofs.append(
                {
                    "resource": str(resource.resource.id),
                    "kind": decision.kind,
                    "operation_id": decision.operation_id,
                    "proof": proof.model_dump(mode="json") if proof else None,
                }
            )
            current = (
                proof is not None
                and proof.current is True
                and (proof.valid_until is None or proof.valid_until >= scope.window.finish)
            )
            decisions.append(
                QualificationFact(
                    **decision.model_dump(exclude={"sources", "status"}),
                    status="unknown"
                    if decision.status == "accepted" and not current
                    else decision.status,
                    source=_source(
                        fact,
                        f"resource:{resource.resource.id}:{decision.kind}:{decision.operation_id}",
                    ),
                )
            )
        snapshots[resource.resource.id] = ResourceSnapshot(
            ref=resource.resource,
            scope=vscope,
            source=_source(fact, f"resource:{resource.resource.id}"),
            purposes=resource.purposes,
            operation_ids=resource.operation_ids,
            lifecycle=resource.lifecycle,
            facts=tuple(decisions),
            maintenance=None
            if resource.maintenance is None
            else tuple(
                MaintenanceFact(
                    window=v.window,
                    status=v.status,
                    source=_source(fact, f"maintenance:{resource.resource.id}:{i}"),
                )
                for i, v in enumerate(resource.maintenance)
            ),
            calendar=resource.calendar,
            calendar_source=_source(fact, f"calendar:{resource.resource.id}")
            if resource.calendar
            else None,
            capacity=resource.capacity,
            occupancy_revision=asset.occupancy_epoch,
        )
        if not resource.external_occupancies_complete:
            checks.append(
                Check(
                    resource=resource.resource,
                    code="external_occupancy_scope_incomplete",
                    status="UNKNOWN",
                    detail="共享资源外部占用范围尚不完整。",
                )
            )
        occupancies.extend(
            Occupancy(
                reservation_id=v.reservation_id,
                resource_id=resource.resource.id,
                window=v.window,
                units=v.units,
            )
            for v in resource.external_occupancies
        )
    from pdos_next.schemas.resource_readiness.contracts import ExecutionWindow

    from .physical_summary import capacity_summary

    occupancies.extend(
        Occupancy(
            reservation_id=UUID(held["id"]),
            resource_id=UUID(held["resource_id"]),
            window=ExecutionWindow(
                start=held["window_start"], finish=held["window_finish"], original_timezone="UTC"
            ),
            units=Decimal(str(held["units"])),
        )
        for held in capacity_summary(
            s,
            ctx,
            fact.product_id,
            "resource",
            required_ids,
            own=excluded_owner,
            watermark=tuple((aid, assets[aid].occupancy_epoch) for aid in sorted(required_ids)),
        )
    )
    for requirement in data.requirements:
        for use in requirement.uses:
            total[use.resource.id] += use.units
        request = ReservationRequest(
            reservation_id=uuid5(fact.id, requirement.operation_key),
            owner_run_id=fact.build_id,
            intent_key="read-only-build-candidate",
            purpose=scope.purpose,
            operation_id=requirement.operation_key,
            window=scope.window,
            uses=requirement.uses,
        )
        context = ResourceContext(
            scope=vscope,
            actor_id=ctx.requester_id,
            owner_run_id=fact.build_id,
            executor_id=ctx.requester_id,
            assigned_person_ids=tuple(
                v.resource.id for v in data.resources if v.resource.kind == "person"
            ),
            now=at,
            authorized=True,
            qualified=True,
            cancelled=False,
            sources_current=True,
            policy_registered=True,
            facts_revision=fact.fact_sha256,
            purpose=scope.purpose,
            operation_id=requirement.operation_key,
            required_resources=requirement.uses,
        )
        reports.append(
            evaluate(
                context,
                request,
                tuple(
                    snapshots[u.resource.id] for u in requirement.uses if u.resource.id in snapshots
                ),
                tuple(occupancies),
            )
        )
    checks.extend(c for report in reports for c in report.checks)
    # No assumed operation schedule: conservatively occupy summed units for the
    # entire Build interval, so shared operations cannot double-book a resource.
    for identity, units in total.items():
        snapshot = snapshots.get(identity)
        if (
            snapshot
            and snapshot.capacity is not None
            and capacity_exceeded(
                scope.window,
                units,
                snapshot.capacity,
                tuple(v for v in occupancies if v.resource_id == identity),
            )
        ):
            checks.append(
                Check(
                    resource=snapshot.ref if snapshot else None,
                    code="combined_capacity_conflict",
                    status="BLOCKED",
                    detail="全部工序合并占用超出完整区间容量。",
                )
            )
    if not checks:
        checks.append(
            Check(
                code="resource_requirements_missing", status="UNKNOWN", detail="缺少权威资源要求。"
            )
        )
    return (
        ReadinessReport(
            status=aggregate(tuple(checks)),
            capacity_status="conflicted"
            if any("capacity" in c.code and c.status == "BLOCKED" for c in checks)
            else "unknown"
            if any(c.status == "UNKNOWN" for c in checks)
            else "checked",
            checks=tuple(checks),
            fixed_resources=tuple(snapshots[k] for k in sorted(snapshots, key=lambda k: k.bytes)),
            input_digest=digest(
                {
                    "fact": fact.fact_sha256,
                    "proofs": proofs,
                    "reports": [v.input_digest for v in reports],
                }
            ),
            checked_at=at,
            conditions=tuple(sorted({v for report in reports for v in report.conditions})),
        ),
        proofs,
        total,
    )


def _state(checks):
    for status in ("BLOCKED", "UNKNOWN", "READY_WITH_CONDITIONS"):
        if any(check.status == status for check in checks):
            return status
    return "READY" if checks else "UNKNOWN"


def _account_rows(s, ctx, assets, excluded_owner):
    material = select(MaterialHold).where(
        MaterialHold.tenant_id == ctx.tenant_id, MaterialHold.asset_id.in_(assets)
    )
    resource = select(ResourceOccupancy).where(
        ResourceOccupancy.tenant_id == ctx.tenant_id, ResourceOccupancy.asset_id.in_(assets)
    )
    if excluded_owner:
        material = material.where(MaterialHold.owner_execution_id != excluded_owner)
        resource = resource.where(
            or_(
                ResourceOccupancy.owner_kind != "build",
                ResourceOccupancy.owner_execution_id != excluded_owner,
            )
        )
    holds, occupied = list(s.scalars(material)), list(s.scalars(resource))
    return holds, occupied


def _account_fingerprint(holds, occupied):
    def values(row, fields):
        return {
            key: str(value)
            if isinstance(value, (UUID, Decimal))
            else value.isoformat()
            if isinstance(value, datetime)
            else value
            for key in fields
            for value in (getattr(row, key),)
        }

    return {
        "material": [
            values(
                row,
                (
                    "id",
                    "tenant_id",
                    "product_id",
                    "project_id",
                    "build_id",
                    "asset_id",
                    "owner_execution_id",
                    "bom_item_id",
                    "quantity",
                    "unit",
                    "intent_digest",
                ),
            )
            for row in sorted(holds, key=lambda value: value.id.bytes)
        ],
        "resource": [
            values(
                row,
                (
                    "id",
                    "tenant_id",
                    "product_id",
                    "project_id",
                    "build_id",
                    "asset_id",
                    "owner_execution_id",
                    "resource_id",
                    "resource_revision",
                    "window_start",
                    "window_finish",
                    "units",
                    "intent_digest",
                    "reservation",
                ),
            )
            for row in sorted(occupied, key=lambda value: value.id.bytes)
        ],
    }


def _persistable(quantity):
    # PostgreSQL Numeric(24,12) must preserve the exact engine allocation. Never
    # round a recurring conversion or overflow an inventory hold into readiness.
    with localcontext() as context:
        context.prec = 60
        return (
            quantity > 0
            and quantity < Decimal("1000000000000")
            and (quantity == quantity.quantize(Decimal("0.00000001")))
        )


def _material_check(coverage):
    if not coverage.input_snapshot.supply_scope_complete:
        return _check(
            "materials",
            "material_scope_incomplete",
            "UNKNOWN",
            "外部库存和全部共享保留范围不完整，已知部分不能解除阻塞。",
        )
    if any(use.kind == "secured" for line in coverage.lines for use in line.uses):
        return _check(
            "materials",
            "external_own_hold_unreconciled",
            "UNKNOWN",
            "外部已保留给本Build的数量尚未与本地占用身份对账。",
        )
    if any(
        not _persistable(use.quantity_in_pool_unit) for line in coverage.lines for use in line.uses
    ):
        return _check(
            "materials",
            "hold_precision_unrepresentable",
            "UNKNOWN",
            "候选保留量不能在既定账本精度中准确保存。",
        )
    if coverage.potential_ready is True:
        return _check(
            "materials",
            "material_candidate_complete",
            "READY",
            "完整库存范围的候选可覆盖同次固定需求，开工提交时须实际保留。",
        )
    if coverage.potential_ready is None:
        return _check(
            "materials",
            "material_coverage_unknown",
            "UNKNOWN",
            "数量、单位、实物可用、质量或完整库存范围仍有未知。",
        )
    return _check(
        "materials", "material_shortage", "BLOCKED", "明确可用的共享库存不能覆盖本次固定需求。"
    )


def _load_bundle(
    s,
    ctx,
    pid,
    bid,
    execution_scope,
    at,
    *,
    write=False,
    excluded_owner=None,
    own_assets=frozenset(),
):
    at = _aware(at)
    build, engineering, manufacturing, build_reads, _, scope = _scope(
        s, ctx, pid, bid, execution_scope, write=write
    )
    basic = dict(
        scope=scope,
        build_revision=build.revision,
        engineering_configuration_id=UUID(engineering["id"]),
        engineering_configuration_revision=engineering["revision"],
        manufacturing_configuration_id=UUID(manufacturing["id"]),
        manufacturing_configuration_revision=manufacturing["revision"],
    )
    reads = {str(v["artifact_id"]): v for v in build_reads}
    fingerprint = {
        "binding": _binding(build, engineering, manufacturing, scope),
    }
    checks = [
        _check("binding", "fixed_plan_bound", "READY", "服务器已核对固定计划双配置和全部数量。")
    ]
    demand_scope = DemandScope(
        tenant_id=str(ctx.tenant_id),
        category_id=str(build.category_id),
        product_id=str(pid),
        project_id=str(build.project_id),
        audience=(
            f"private:{build.owner_id}"
            if build.visibility == "private"
            else f"audience:build:{build.id}"
            if build.visibility == "audience"
            else f"category:{build.category_id}"
        ),
    )
    try:
        bound = load_bound_demand(s, ctx, demand_scope, str(bid), build.revision, at)
    except DomainError as error:
        if error.reason not in {"PORT_UNCONNECTED", "DEMAND_SNAPSHOT_INCOMPLETE"}:
            raise
        checks.append(_check("binding", "demand_port_unavailable", "UNKNOWN", error.message))
        fingerprint["missing"] = error.reason
        return OperationalBundle(
            **basic,
            checks=tuple(checks),
            state="UNKNOWN",
            facts_revision=digest(fingerprint),
            required_source_read_set=tuple(SourceRead.model_validate(v) for v in reads.values()),
        )
    fingerprint["demand"] = bound.model_dump(mode="json")
    if not bound.source_read_set_complete or not bound.demand.lines:
        raise DomainError("DEMAND_SNAPSHOT_INCOMPLETE", "固定需求及来源全集未完整绑定。")
    pointer = _pointer(s, ctx, pid, bid, lock=write)
    if pointer is None:
        checks.append(
            _check(
                "authority",
                "operational_facts_missing",
                "UNKNOWN",
                "当前未提供可信物料及资源事实。",
            )
        )
        fingerprint["missing"] = "operational_facts"
        return OperationalBundle(
            **basic,
            binding=bound,
            checks=tuple(checks),
            state="UNKNOWN",
            facts_revision=digest(fingerprint),
            required_source_read_set=tuple(SourceRead.model_validate(v) for v in reads.values()),
        )
    from pdos_next.request_proof import snapshot_scalar

    fact = snapshot_scalar(
        s,
        (BuildOperationalFact, pid, pointer.fact_id),
        select(BuildOperationalFact).where(BuildOperationalFact.id == pointer.fact_id),
        scope_id=pid,
    )
    if fact is None or any(
        (
            fact.tenant_id != ctx.tenant_id,
            fact.product_id != pid,
            fact.project_id != build.project_id,
            fact.build_id != bid,
            fact.revision != pointer.fact_revision,
            fact.binding != fingerprint["binding"],
            _fact_hash(fact) != fact.fact_sha256,
        )
    ):
        raise DomainError("INTEGRITY_MISMATCH", "当前权威事实固定范围或摘要无法核对。")
    data = FactInput.model_validate(fact.data)
    if (
        data.scope != scope
        or data.build_id != bid
        or data.expected_build_revision != build.revision
    ):
        raise DomainError("INTEGRITY_MISMATCH", "权威输入与固定绑定不一致。")
    # Caller ACL remains a current independent guard. Retained import-owner
    # provenance is read-only; it never authorizes this caller's writes.
    evidence_reads, private, _ = _evidence(s, ctx, pid, fact.sources)
    _, _, source_basis = _evidence_basis(s, ctx, pid, fact.sources, build_reads)
    fingerprint["demand"] = bound.model_dump(mode="json")
    if private and build.visibility == "category":
        raise DomainError("FORBIDDEN_SCOPE", "私人来源不能扩大到共享Build。", 403)
    reads.update({str(v["artifact_id"]): v for v in evidence_reads})
    if sorted(reads.values(), key=lambda v: str(v["artifact_id"])) != sorted(
        fact.required_source_read_set, key=lambda v: str(v["artifact_id"])
    ):
        raise DomainError("MISSING_REQUIRED_EVIDENCE", "固定权威事实完整读集不一致。")
    issuer = getattr(s.get_bind(), "_pdos_operational_issuers", {}).get(fact.issuer_key)
    current_issuer = isinstance(issuer, IssuerContext) and all(
        (
            issuer._token is _TOKEN,
            issuer.tenant_id == ctx.tenant_id,
            issuer.product_id == pid,
            issuer.project_id is None or issuer.project_id == build.project_id,
            issuer.version == fact.issuer_version,
            issuer.epoch == fact.issuer_epoch,
            issuer.nature == fact.nature,
        )
    )
    fingerprint.update(
        {
            "source_basis": evidence_watermark(source_basis),
            "fact": fact.fact_sha256,
            "pointer_epoch": pointer.epoch,
            "issuer_current": current_issuer,
            "issuer_epoch": getattr(s.get_bind(), "_pdos_operational_issuer_epochs", {}).get(
                fact.issuer_key
            ),
        }
    )
    if not current_issuer:
        checks.append(
            _check(
                "authority",
                "trusted_issuer_unavailable",
                "UNKNOWN",
                "当前签发端口未配置或已换版、撤销。",
            )
        )
    if evidence_watermark(source_basis) != evidence_watermark(fact.source_basis):
        checks.append(
            _check(
                "authority",
                "source_basis_changed",
                "BLOCKED",
                "来源安全或当前权限已变化，需重新导入核对。",
            )
        )
    valid = (
        fact.state == "active"
        and fact.valid_from <= at
        and (fact.valid_until is None or at < fact.valid_until)
        and fact.valid_from <= scope.window.start
        and (fact.valid_until is None or fact.valid_until >= scope.window.finish)
    )
    fingerprint["valid"] = valid
    checks.append(
        _check(
            "authority",
            "operational_validity",
            "READY" if valid else "BLOCKED",
            "事实覆盖本次完整执行区间。" if valid else "事实撤回、过期或未覆盖完整执行区间。",
        )
    )
    specs = _assets(data, ctx.tenant_id)
    assets = _locked_assets(s, ctx, specs, lock=write)
    asset_basis = []
    for _, aid, _, _, revision, physical in specs:
        asset = assets[aid]
        same = (
            asset.revision == revision
            and asset.data_sha256 == digest(physical)
            and asset.data["state"] == "active"
        )
        if not same:
            checks.append(
                _check(
                    "authority",
                    "physical_asset_stale",
                    "BLOCKED",
                    "共享物理事实已换版或撤回，旧Build事实需重核。",
                )
            )
        epoch = asset.occupancy_epoch - (1 if aid in own_assets else 0)
        if epoch < 1:
            raise DomainError("INTEGRITY_MISMATCH", "自身占用epoch证明无法核对。")
        asset_basis.append(
            {
                "id": str(aid),
                "revision": asset.revision,
                "sha256": asset.data_sha256,
                "state": asset.data["state"],
                "occupancy_epoch": epoch,
            }
        )
    fingerprint["assets"] = asset_basis
    held, occupied = _account_rows(s, ctx, assets, excluded_owner)
    fingerprint["accounts"] = _account_fingerprint(held, occupied)
    coverage = _material_coverage(s, ctx, fact, data, bound, assets, at, excluded_owner)
    checks.append(_material_check(coverage))
    report, proofs, _ = _resource_report(
        s, ctx, fact, data, bound, scope, assets, issuer, at, excluded_owner
    )
    checks.extend(_check("resources", v.code, v.status, v.detail) for v in report.checks)
    fingerprint["named_decisions"] = proofs
    # Readiness category transitions matter; the sampling clock, engine as_of
    # and checked_at do not change a still-current version/occupancy binding.
    fingerprint["checks"] = [v.model_dump(mode="json") for v in checks]
    # Actual caller access was checked above. Its deadline does not shorten a
    # physical fact or invalidate another authorized person's fixed assessment.
    return OperationalBundle(
        **basic,
        binding=bound,
        coverage=coverage,
        resources=report,
        checks=tuple(checks),
        state=_state(checks),
        fact_refs=(
            FactRef(
                id=fact.id,
                revision=fact.revision,
                epoch=pointer.epoch,
                sha256=fact.fact_sha256,
                nature=fact.nature,
            ),
        ),
        required_source_read_set=tuple(
            SourceRead.model_validate(reads[key]) for key in sorted(reads)
        ),
        facts_revision=digest(fingerprint),
        decision_watermarks=tuple(proofs),
        nature=fact.nature,
    )


def load_bundle(s, ctx, product_id, build_id, scope, at, write=False):
    """Authoritative read under Product → stable global asset locks, no writes."""
    return _load_bundle(s, ctx, product_id, build_id, scope, at, write=write)


def _allocation(bundle, tenant_id):
    pools = {v.key: v for v in bundle.coverage.input_snapshot.pools}
    values = defaultdict(Decimal)
    for line in bundle.coverage.lines:
        for use in line.uses:
            if use.kind != "unreserved_candidate" or use.qualification_id is not None:
                raise DomainError("MATERIAL_HOLD_UNRECONCILED", "外部保留或替代材料尚未接线。")
            values[(use.pool, line.demand.item_id)] += use.quantity_in_pool_unit
    result = []
    for (pool, item), quantity in sorted(
        values.items(), key=lambda row: (digest(row[0][0]), row[0][1])
    ):
        asset = uuid5(NAMESPACE_URL, f"pdos:material:{tenant_id}:{digest(pool)}")
        result.append((asset, item, quantity, pools[pool].unit))
    return result


def reserve(
    s,
    ctx,
    product_id,
    build_id,
    scope,
    *,
    owner_execution_id,
    intent_digest,
    expected_facts_revision,
    at,
):
    """Stage exact local holds in the start UOW; deferred FK enforces its owner."""
    if (
        not isinstance(owner_execution_id, UUID)
        or len(intent_digest) != 64
        or any(value not in "0123456789abcdef" for value in intent_digest)
    ):
        raise DomainError("INVALID_OPERATIONAL_INTENT", "占用须固定服务器开工身份和摘要。", 422)
    bundle = load_bundle(s, ctx, product_id, build_id, scope, at, write=True)
    if bundle.facts_revision != expected_facts_revision:
        raise DomainError("OPERATIONAL_FACTS_CHANGED", "当前物理事实或共享占用已变化。")
    if bundle.state != "READY":
        raise DomainError("BUILD_OPERATIONAL_NOT_READY", "物料和资源尚未完整就绪。")
    fact = s.get(BuildOperationalFact, bundle.fact_refs[0].id)
    data = FactInput.model_validate(fact.data)
    assets = _locked_assets(s, ctx, _assets(data, ctx.tenant_id))
    for model in (MaterialHold, ResourceOccupancy):
        query = select(model.id).where(model.tenant_id == ctx.tenant_id, model.build_id == build_id)
        if model is ResourceOccupancy:
            query = query.where(ResourceOccupancy.owner_kind == "build")
        if s.scalar(query.limit(1)):
            raise DomainError("BUILD_ALREADY_RESERVED", "当前Build已存在占用，须重放共同开工回执。")
    material_ids, resource_ids, touched = [], [], set()
    material_plan = _allocation(bundle, ctx.tenant_id)
    for aid, item, quantity, unit in material_plan:
        if not _persistable(quantity) or unit is None:
            raise DomainError("MATERIAL_HOLD_PRECISION_UNKNOWN", "物料保留量不能精确落账。")
        identity = uuid5(owner_execution_id, f"material:{aid}:{item}")
        s.add(
            MaterialHold(
                id=identity,
                tenant_id=ctx.tenant_id,
                category_id=fact.category_id,
                product_id=product_id,
                project_id=fact.project_id,
                build_id=build_id,
                owner_execution_id=owner_execution_id,
                asset_id=aid,
                bom_item_id=item,
                quantity=quantity,
                unit=unit,
                intent_digest=intent_digest,
            )
        )
        material_ids.append(identity)
        touched.add(aid)
    total = defaultdict(Decimal)
    refs = {v.resource.id: v.resource for v in data.resources}
    for requirement in data.requirements:
        for use in requirement.uses:
            total[use.resource.id] += use.units
    request = ReservationRequest(
        reservation_id=owner_execution_id,
        owner_run_id=owner_execution_id,
        intent_key="canonical-build-start",
        purpose=bundle.scope.purpose,
        operation_id="build.start",
        window=bundle.scope.window,
        uses=tuple(
            ResourceUse(resource=refs[key], units=total[key])
            for key in sorted(total, key=lambda k: k.bytes)
        ),
    )
    retained = Reservation(
        id=owner_execution_id,
        revision=1,
        scope=Scope(tenant_id=ctx.tenant_id, product_id=product_id, project_id=fact.project_id),
        request=request,
        semantic_digest=intent_digest,
        state="formal",
        fixed_resources=bundle.resources.fixed_resources,
        report=bundle.resources,
        events=(ReservationEvent(kind="formal", at=at, actor_id=ctx.requester_id),),
    )
    proof = {
        "reservation": retained.model_dump(mode="json"),
        "scope": bundle.scope.model_dump(mode="json"),
        "facts_revision": bundle.facts_revision,
        "fact_id": str(fact.id),
        "fact_sha256": fact.fact_sha256,
        "source_read_set": [v.model_dump(mode="json") for v in bundle.required_source_read_set],
        "material_plan": [
            {"asset_id": str(aid), "item_id": item, "quantity": str(qty), "unit": unit}
            for aid, item, qty, unit in material_plan
        ],
        "asset_epochs": {str(aid): assets[aid].occupancy_epoch for aid in assets},
        "decision_watermarks": list(bundle.decision_watermarks),
    }
    for aid in sorted(total, key=lambda k: k.bytes):
        identity = uuid5(owner_execution_id, f"resource:{aid}")
        s.add(
            ResourceOccupancy(
                id=identity,
                tenant_id=ctx.tenant_id,
                category_id=fact.category_id,
                product_id=product_id,
                project_id=fact.project_id,
                build_id=build_id,
                owner_execution_id=owner_execution_id,
                owner_kind="build",
                build_start_id=owner_execution_id,
                test_run_id=None,
                asset_id=aid,
                resource_id=aid,
                resource_revision=refs[aid].revision,
                window_start=bundle.scope.window.start,
                window_finish=bundle.scope.window.finish,
                units=total[aid],
                intent_digest=intent_digest,
                reservation=proof,
            )
        )
        resource_ids.append(identity)
        touched.add(aid)
    for aid in touched:
        assets[aid].occupancy_epoch += 1
    s.flush()
    return ReservationResult(
        owner_execution_id=owner_execution_id,
        material_holds=tuple(material_ids),
        resource_reservations=tuple(resource_ids),
        facts_revision=bundle.facts_revision,
    )


def reservation_basis(s, ctx, product_id, build_id, scope, owner_execution_id, intent_digest):
    """Read this owner's stored reservation and exact effects, without reallocating."""
    common = (
        MaterialHold.tenant_id == ctx.tenant_id,
        MaterialHold.owner_execution_id == owner_execution_id,
    )
    from pdos_next.request_proof import snapshot_rows

    holds = snapshot_rows(
        s,
        (MaterialHold, product_id, owner_execution_id),
        select(MaterialHold).where(*common),
        scope_id=product_id,
    )
    occupied = snapshot_rows(
        s,
        (ResourceOccupancy, product_id, "build", owner_execution_id),
        select(ResourceOccupancy).where(
            ResourceOccupancy.tenant_id == ctx.tenant_id,
            ResourceOccupancy.owner_kind == "build",
            ResourceOccupancy.owner_execution_id == owner_execution_id,
        ),
        scope_id=product_id,
    )
    if not occupied:
        raise DomainError("RESERVATION_PROOF_MISSING", "固定开工的完整占用证明缺失。")
    proof = occupied[0].reservation
    for row in [*holds, *occupied]:
        if any(
            (
                row.product_id != product_id,
                row.build_id != build_id,
                row.intent_digest != intent_digest,
            )
        ):
            raise DomainError("RESERVATION_PROOF_MISMATCH", "占用不属于固定开工意图。")
    if any(row.reservation != proof for row in occupied) or proof[
        "scope"
    ] != OperationalScope.model_validate(scope).model_dump(mode="json"):
        raise DomainError("RESERVATION_PROOF_MISMATCH", "占用证明的完整范围不能一致核对。")
    retained = Reservation.model_validate(proof["reservation"])
    if (
        retained.id != owner_execution_id
        or retained.semantic_digest != intent_digest
        or retained.state != "formal"
    ):
        raise DomainError("RESERVATION_PROOF_MISMATCH", "正式占用身份或意图摘要不能核对。")
    expected = {
        (UUID(v["asset_id"]), v["item_id"]): (Decimal(v["quantity"]), v["unit"])
        for v in proof["material_plan"]
    }
    actual = {(v.asset_id, v.bom_item_id): (v.quantity, v.unit) for v in holds}
    resources = {v.resource.id: v for v in retained.request.uses}
    if (
        expected != actual
        or set(resources) != {v.asset_id for v in occupied}
        or any(
            row.resource_id != row.asset_id
            or row.resource_revision != resources[row.asset_id].resource.revision
            or row.units != resources[row.asset_id].units
            or row.window_start != retained.request.window.start
            or row.window_finish != retained.request.window.finish
            for row in occupied
        )
    ):
        raise DomainError("RESERVATION_PROOF_MISMATCH", "物料数量或资源完整区间与原证明不一致。")
    own_assets = frozenset(v.asset_id for v in [*holds, *occupied])
    return proof, own_assets


def recheck_reservation(s, ctx, product_id, build_id, scope, owner_execution_id, intent_digest, at):
    """Read-only replay safety: exact own proof, all other occupancy still counted."""
    _scope(s, ctx, product_id, build_id, scope)
    proof, own_assets = reservation_basis(
        s, ctx, product_id, build_id, scope, owner_execution_id, intent_digest
    )
    expected = {
        (UUID(v["asset_id"]), v["item_id"]): (Decimal(v["quantity"]), v["unit"])
        for v in proof["material_plan"]
    }
    bundle = _load_bundle(
        s,
        ctx,
        product_id,
        build_id,
        scope,
        at,
        excluded_owner=owner_execution_id,
        own_assets=own_assets,
    )
    if (
        bundle.facts_revision != proof["facts_revision"]
        or not bundle.fact_refs
        or any(
            (
                str(bundle.fact_refs[0].id) != proof["fact_id"],
                bundle.fact_refs[0].sha256 != proof["fact_sha256"],
                tuple(_allocation(bundle, ctx.tenant_id))
                != tuple((aid, item, q, u) for (aid, item), (q, u) in expected.items()),
            )
        )
    ):
        raise DomainError(
            "OPERATIONAL_FACTS_CHANGED",
            "当前来源、资格或其他共享占用已变化，原回执不能作为新许可。",
        )
    return bundle
