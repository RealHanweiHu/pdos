"""Read Build's persisted demand in the caller's single command transaction.

No expansion, calculation, connection, commit, mutation, inventory or qualification
is performed here. ``current`` describes authorized fixed provenance; it never
claims malware clean, stock availability, method applicability or Build release.
SnapshotRef.captured_at is the record's server availability time, not a newly
invented observation time. The demand became available at Readiness.created_at.
"""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import JsonValue, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.engines.supply_cost.common import FrozenDTO, SnapshotRef, digest, source_issues
from pdos_next.engines.supply_cost.dto import CoverageResult, DemandLine, FixedBasis
from pdos_next.errors import DomainError
from pdos_next.models import now
from pdos_next.schemas.supply_cost.dto import BoundDemand, DemandSnapshot, Scope

from .models import Build, BuildReadiness
from .readiness import _Input, _ref
from .service import _linked, readiness_snapshot

if TYPE_CHECKING:
    from pdos_next.service import Context


class _DemandFingerprint(FrozenDTO):
    scope: Scope
    readiness_id: str
    revision: int
    input_sha256: str
    input_snapshot: dict[str, JsonValue]
    basis: FixedBasis
    manufacturing_configuration: SnapshotRef
    lines: tuple[DemandLine, ...]


def _unavailable():
    return DomainError(
        "DEMAND_SNAPSHOT_INCOMPLETE", "本轮完整固定需求快照尚不可用，请先计算并核对准备结果。"
    )


def _identity(value):
    try:
        return UUID(value)
    except (TypeError, ValueError, AttributeError):
        raise DomainError("FORBIDDEN_SCOPE", "固定需求不在当前服务器绑定范围。", 403) from None


def _current(ref, as_of):
    if source_issues(ref, as_of, ref.source_id):
        raise DomainError("SOURCE_STALE", "固定需求来源在本次计算时点尚不可用或已经失效。")


def _saved_bundle(readiness, build, engineering, manufacturing):
    """Validate stored identity/integrity; never expand a live or saved BOM."""
    result = readiness.result
    try:
        data = _Input.model_validate(result["input_snapshot"])
        coverage = CoverageResult.model_validate(result["coverage"])
        lines = tuple(DemandLine.model_validate(row) for row in result["demands"])
        live = readiness_snapshot(build, engineering, manufacturing)
        live["as_of"] = data.as_of
        same_fixed_objects = _Input.model_validate(live)
        if (
            result["schema_version"] != "build-readiness-result.v1"
            or result["algorithm"] != "fixed-build-readiness.v1"
            or result["build_id"] != str(build.id)
            or type(result["build_revision"]) is not int
            or result["build_revision"] != build.revision
            or digest(data) != result["input_sha256"]
            or digest(same_fixed_objects) != result["input_sha256"]
            or SnapshotRef.aware_time(datetime.fromisoformat(result["as_of"])) != data.as_of
            or coverage.input_snapshot.as_of != data.as_of
            or coverage.input_sha256 != digest(coverage.input_snapshot)
            or data.engineering_configuration is None
            or data.engineering_configuration.bom is None
            or data.manufacturing_configuration is None
            or not lines
            or not data.manufacturing_configuration.operations
        ):
            raise _unavailable()
        basis = coverage.input_snapshot.basis
        if (
            basis.build.ref != _ref("build", data.build)
            or basis.build.build_id != str(build.id)
            or basis.build.quantity != build.planned_quantity
            or basis.build.product_unit != build.unit
            or basis.bom.ref != _ref("bom", data.engineering_configuration.bom)
            or basis.bom.engineering_configuration
            != _ref("configuration", data.engineering_configuration)
            or len({row.item_id for row in lines}) != len(lines)
            or {row.item_id for row in lines} != {row.item_id for row in basis.bom.items}
            or sorted(lines, key=lambda row: row.item_id)
            != sorted((row.demand for row in coverage.lines), key=lambda row: row.item_id)
        ):
            raise _unavailable()
        return data, basis, lines
    except (ValidationError, KeyError, TypeError, ValueError, AttributeError):
        raise _unavailable() from None


def load_bound_demand(
    s: Session,
    ctx: "Context",
    scope: Scope,
    build_id: str,
    expected_revision: int,
    as_of: datetime,
) -> BoundDemand:
    """Load under Product/Grant/source locks; immutable Build needs no row lock.

    ``scope`` and ``as_of`` must come from the common server command binding.
    This adapter independently compares scope to actual persisted objects and
    rechecks access at real server time, including replay after an old preview.
    """
    from pdos_next.originals import object_reference, require_original
    from pdos_next.request_proof import snapshot_scalar
    from pdos_next.service import digest as source_digest
    from pdos_next.service import require_access, source_for

    if not isinstance(s, Session) or not s.in_transaction():
        raise DomainError("INTEGRATION_REQUIRED", "需求读取必须参加调用者已开启的共同事务。")
    try:
        as_of = SnapshotRef.aware_time(as_of)
    except (TypeError, ValueError, AttributeError):
        raise DomainError(
            "INVALID_EVENT_TIME", "需求计算时点须为服务器固定的含时区时间。", 422
        ) from None
    if as_of is None or as_of > now():
        raise DomainError("INVALID_EVENT_TIME", "需求计算时点不能在未来。", 422)
    if type(expected_revision) is not int or expected_revision < 1:
        raise DomainError("VERSION_CONFLICT", "本轮需求须固定真实 Build 版本。")
    product_id = _identity(scope.product_id)
    if scope.tenant_id != str(ctx.tenant_id):
        raise DomainError("FORBIDDEN_SCOPE", "固定需求不在当前服务器绑定租户。", 403)
    product = require_access(s, ctx, product_id)
    build = snapshot_scalar(
        s,
        (Build, product_id, _identity(build_id)),
        select(Build).where(
            Build.id == _identity(build_id),
            Build.tenant_id == ctx.tenant_id,
            Build.product_id == product_id,
        ),
        scope_id=product_id,
    )
    if build is None:
        raise DomainError("FORBIDDEN_SCOPE", "固定需求不在当前可读的试制范围。", 403)
    audience = (
        f"private:{build.owner_id}"
        if build.visibility == "private"
        else f"audience:build:{build.id}"
        if build.visibility == "audience"
        else f"category:{build.category_id}"
    )
    trusted_scope = Scope(
        tenant_id=str(ctx.tenant_id),
        category_id=str(product.category_id),
        product_id=str(product_id),
        project_id=str(build.project_id),
        audience=audience,
    )
    if scope != trusted_scope:
        raise DomainError("FORBIDDEN_SCOPE", "项目或受众与真实试制需求范围不一致。", 403)
    if build.revision != expected_revision:
        raise DomainError("VERSION_CONFLICT", "本轮需求与固定 Build 版本不一致。")
    readiness = snapshot_scalar(
        s,
        (BuildReadiness, product_id, build.id, build.revision),
        select(BuildReadiness).where(
            BuildReadiness.tenant_id == ctx.tenant_id,
            BuildReadiness.product_id == product_id,
            BuildReadiness.build_id == build.id,
            BuildReadiness.build_revision == build.revision,
        ),
        scope_id=product_id,
    )
    if readiness is None:
        raise DomainError("PORT_UNCONNECTED", "本轮尚未保存权威需求准备快照。")
    if (
        readiness.visibility != build.visibility
        or readiness.owner_id != build.owner_id
        or readiness.created_at > as_of
    ):
        raise _unavailable()
    _, engineering, manufacturing, reads = _linked(s, ctx, product_id, build)
    if not reads or any(
        view["source_status"] != "current"
        for view in (
            engineering,
            manufacturing,
        )
    ):
        raise DomainError("SOURCE_STALE", "固定工程、制造或原件来源已失效。")
    data, basis, lines = _saved_bundle(readiness, build, engineering, manufacturing)
    references = {}
    for read in reads:
        source = source_for(
            s, ctx, product_id, UUID(read["artifact_id"]), read["expected_revision"]
        )
        if source.tenant_id != ctx.tenant_id or source.content_hash != source_digest(
            source.content
        ):
            raise DomainError("INTEGRITY_MISMATCH", "原件派生内容摘要无法核对。")
        if build.visibility == "category" and source.visibility != "category":
            raise DomainError("FORBIDDEN_SCOPE", "私人原件不能扩大到品类共享需求。", 403)
        reference = SnapshotRef(
            source_id=f"artifact:{source.id}",
            version=str(source.revision),
            sha256=source.content_hash,
            captured_at=source.created_at,
            state="current",
        )
        _current(reference, as_of)
        references[reference.source_id] = reference
        if source.original_id is not None:
            original = require_original(s, ctx, product_id, source.original_id)
            if (
                original.tenant_id != ctx.tenant_id
                or original.status != "parsed"
                or (build.visibility == "category" and original.visibility != "category")
            ):
                raise DomainError("SOURCE_UNAVAILABLE", "派生需求的固定原件范围或解析状态不可用。")
            # Validate the private object identity without reading bytes, exposing
            # its storage key or asserting the independent scanner returned clean.
            try:
                object_reference(original)
            except (TypeError, ValueError, AttributeError):
                raise DomainError(
                    "INTEGRITY_MISMATCH", "固定原件的私有对象身份无法核对。"
                ) from None
            reference = SnapshotRef(
                source_id=f"original:{original.id}",
                version=str(original.revision),
                sha256=original.content_hash,
                captured_at=max(original.created_at, source.created_at),
                state="current",
            )
            _current(reference, as_of)
            references[reference.source_id] = reference
    manufacturing_ref = _ref("manufacturing_configuration", data.manufacturing_configuration)
    keys = tuple(operation.key for operation in data.manufacturing_configuration.operations)
    if len(keys) != len(set(keys)):
        raise _unavailable()
    fingerprint = _DemandFingerprint(
        scope=trusted_scope,
        readiness_id=str(readiness.id),
        revision=readiness.revision,
        input_sha256=readiness.result["input_sha256"],
        input_snapshot=data.model_dump(mode="json"),
        basis=basis,
        manufacturing_configuration=manufacturing_ref,
        lines=lines,
    )
    demand_ref = SnapshotRef(
        source_id=f"build-readiness:{readiness.id}",
        version=str(readiness.revision),
        sha256=digest(fingerprint),
        captured_at=readiness.created_at,
        state="current",
    )
    for reference in (
        basis.build.ref,
        basis.bom.ref,
        basis.bom.engineering_configuration,
        manufacturing_ref,
        demand_ref,
    ):
        _current(reference, as_of)
    return BoundDemand(
        scope=trusted_scope,
        basis=basis,
        manufacturing_configuration=manufacturing_ref,
        demand=DemandSnapshot(
            ref=demand_ref,
            basis_sha256=digest(basis),
            manufacturing_sha256=manufacturing_ref.sha256,
            lines=lines,
        ),
        manufacturing_operation_ids=keys,
        source_read_set=tuple(references[key] for key in sorted(references)),
        source_read_set_complete=True,
    )


class DatabaseBuildDemandPort:
    """Trusted server Context is constructor-bound, never deserialized from payload."""

    def __init__(self, ctx: "Context"):
        self._ctx = ctx

    def load(
        self, uow: Session, scope: Scope, build_id: str, expected_revision: int, as_of: datetime
    ) -> BoundDemand:
        return load_bound_demand(uow, self._ctx, scope, build_id, expected_revision, as_of)
