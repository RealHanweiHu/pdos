"""Trusted, scoped test facts and one caller-UOW resource/sample reservation.

No connector calls, commits, receipts or public self-qualification live here.
Capacity, qualification intervals and calendar rules are the delivered resource
kernel. Physical resources and all Build/Test occupants share the existing asset
sentinel and occupancy table; SampleUnit identity and readiness are untouched.
"""

# The central metadata registry must initialize before its domain children.
# ruff: noqa: I001

from collections.abc import Callable
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from math import isfinite
from types import SimpleNamespace
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5
import json

from pydantic import BaseModel, ValidationError
from sqlalchemy import inspect as inspect_row, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import UnboundExecutionError
from sqlalchemy.orm import Session, SessionTransaction

from pdos_next.models import Product, now

from pdos_next.domain.build_operational_facts.models import (
    BuildOperationalCurrent,
    BuildOperationalFact,
    ResourceOccupancy,
)
from pdos_next.domain.build_operational_facts.schemas import DecisionProof, FactRef
from pdos_next.domain.build_operational_facts.schemas import FactInput as BuildFactInput
from pdos_next.domain.build_operational_facts.service import _assets as build_asset_specs
from pdos_next.domain.build_operational_facts.service import (
    _evidence_basis,
    _locked_assets,
    _physical,
    digest,
)
from pdos_next.domain.build_operational_facts.service import (
    _sources as references,
)
from pdos_next.domain.professional_authority import service as professional
from pdos_next.domain.resource_readiness.handlers import ResourceError, ResourceReservationHandler
from pdos_next.domain.resource_readiness.rules import evaluate, overlap
from pdos_next.domain.sample_handoff.service import inspect_sample
from pdos_next.domain.supply_execution.service import _human, _sources
from pdos_next.domain.verification import rules as verification_rules
from pdos_next.domain.verification_front import service as front
from pdos_next.domain.verification_handoff import service as handoff
from pdos_next.errors import DomainError
from pdos_next.schemas.resource_readiness.contracts import (
    Check,
    MaintenanceFact,
    Occupancy,
    QualificationFact,
    Reservation,
    ReservationRequest,
    ResourceContext,
    ResourceSnapshot,
)
from pdos_next.schemas.verification.contracts import EventTime, SampleRef, Scope, SourceRef

from .models import (
    SampleRunUsage,
    SampleUsageSentinel,
    TestResourceCurrent,
    TestResourceFact,
    TestResourceReservation,
)
from .schemas import (
    BoundTestResources,
    SampleUsageView,
    TestPlanBinding,
    TestReservationResult,
    TestResourceFactInput,
)

_TOKEN = object()


def expired(value, at):
    """Recheck each actual fact's boundary; no material-wide earliest TTL."""
    return (
        (
            value.authority_basis is not None
            and not professional.authority_time_current(value.authority_basis, at)
        )
        or (value.valid_until is not None and at >= value.valid_until)
        or any(at >= deadline for deadline in value.expiry_boundaries)
    )


OPERATION = "test.run.start"


def inspect_retained_execution(s, ctx, product_id, run_row, *, at=None, write=False):
    from .retained import inspect_retained_execution as inspect

    return inspect(s, ctx, product_id, run_row, at=at, write=write)


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
    engine, *, key, version, tenant_id, product_id, project_id=None, verify_named_decision=None
):
    return _configure(
        engine, key, version, tenant_id, product_id, project_id, "real", verify_named_decision
    )


def configure_local_synthetic(
    engine,
    *,
    tenant_id,
    product_id,
    project_id=None,
    key="synthetic-test-resources",
    version="v1",
    enabled=False,
    test_marker_verified=False,
    verify_named_decision=None,
):
    if enabled is not True or test_marker_verified is not True:
        raise ValueError("Synthetic test resources require the verified isolated host marker")
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
        raise ValueError("Exact server issuer identity and scope are required")
    epochs = dict(getattr(engine, "_pdos_test_resource_issuer_epochs", {}))
    epochs[key] = epochs.get(key, 0) + 1
    issuer = IssuerContext(
        key, version, tenant_id, product_id, project_id, nature, epochs[key], verifier, _TOKEN
    )
    registry = dict(getattr(engine, "_pdos_test_resource_issuers", {}))
    registry[key] = issuer
    engine._pdos_test_resource_issuers = registry
    engine._pdos_test_resource_issuer_epochs = epochs
    return issuer


def disable_issuer(engine, key):
    registry = dict(getattr(engine, "_pdos_test_resource_issuers", {}))
    registry.pop(key, None)
    epochs = dict(getattr(engine, "_pdos_test_resource_issuer_epochs", {}))
    epochs[key] = epochs.get(key, 0) + 1
    engine._pdos_test_resource_issuers = registry
    engine._pdos_test_resource_issuer_epochs = epochs


def _issuer(s, ctx, product_id, project_id, value):
    registry = getattr(s.get_bind(), "_pdos_test_resource_issuers", {})
    if (
        not isinstance(value, IssuerContext)
        or value._token is not _TOKEN
        or registry.get(value.key) is not value
        or value.tenant_id != ctx.tenant_id
        or value.product_id != product_id
        or (value.project_id is not None and value.project_id != project_id)
    ):
        raise DomainError("TRUSTED_ISSUER_REQUIRED", "缺少当前精确范围的可信测试事实端口。", 403)
    return value


def _at(value):
    value = now() if value is None else value
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise DomainError("INVALID_RESOURCE_TIME", "资源核对时间须含时区。", 422)
    value = value.astimezone(UTC)
    if value > now():
        raise DomainError("INVALID_RESOURCE_TIME", "不能以未来时点授予当前资源资格。", 422)
    return value


def _union(*groups):
    result = {}
    for group in groups:
        for read in group:
            value = read.model_dump(mode="json") if hasattr(read, "model_dump") else read
            identity = str(value["artifact_id"])
            if (
                identity in result
                and result[identity]["expected_revision"] != value["expected_revision"]
            ):
                raise DomainError("SOURCE_STALE", "同一来源不能绑定两个版本。")
            result[identity] = {
                "artifact_id": identity,
                "expected_revision": value["expected_revision"],
            }
    return [result[key] for key in sorted(result)]


def _visible(row, ctx):
    return row.visibility in {"category", "audience"} or row.owner_id == ctx.requester_id


def _parent_locks(s, ctx, product_id, binding, *, write=False):
    if not isinstance(s, Session) or not s.in_transaction():
        raise DomainError("INTEGRATION_REQUIRED", "测试资源必须参与当前共同事务。")
    binding = TestPlanBinding.model_validate(binding)
    if len(binding.purpose) > 160:
        raise DomainError("RESOURCE_PURPOSE_LIMIT", "资源核支持的精确用途长度上限为160。", 422)
    from pdos_next.request_proof import scoped_rows, snapshot_get, snapshot_scalar

    if getattr(s, "info", {}).get("read_snapshot") and not write:
        product = snapshot_get(s, Product, product_id, scope_id=product_id)
    else:
        products = scoped_rows(
            s,
            (Product, product_id),
            select(Product).where(Product.tenant_id == ctx.tenant_id, Product.id == product_id),
            lock=write,
        )
        product = products[0] if products else None
    if product is None or product.tenant_id != ctx.tenant_id:
        raise DomainError("FORBIDDEN_SCOPE", "测试资源不在当前型号范围。", 403)
    _human(s, ctx, product_id, write=write)
    row = front._row(s, ctx, product_id, binding.accepted_request_id)
    request = front._snapshot(row)
    if (
        row.request_id != binding.request_id
        or row.revision != binding.accepted_request_revision
        or row.project_id != binding.project_id
        or row.build_id != binding.build_id
        or request.purpose != binding.purpose
        or not {(p.sample.id, p.item_id) for p in binding.pairs}
        <= {(c.sample_id, c.item_id) for c in verification_rules.accepted_coverage(request)}
    ):
        raise DomainError("TEST_PLAN_SCOPE_MISMATCH", "计划须固定明确的已接收范围和精确用途。")
    # Mutable parent serialization precedes the global resource/sample sentinels.
    pointer, current = front._current(s, ctx, product_id, binding.request_id, lock=write)
    if pointer is None or current is None:
        raise DomainError("TEST_PLAN_SCOPE_MISMATCH", "正式请求当前版本不可核对。")
    latest = front._snapshot(current)
    if not {(p.sample.id, p.item_id) for p in binding.pairs} <= {
        (c.sample_id, c.item_id) for c in verification_rules.accepted_coverage(latest)
    }:
        raise DomainError("TEST_PLAN_SCOPE_MISMATCH", "当前已接收范围已经变化。")
    from pdos_next.domain.verification_launch.models import VerificationRunIdentity

    query = select(VerificationRunIdentity).where(
        VerificationRunIdentity.tenant_id == ctx.tenant_id,
        VerificationRunIdentity.product_id == product_id,
        VerificationRunIdentity.id == binding.run_id,
    )
    run = snapshot_scalar(
        s,
        (VerificationRunIdentity, product_id, binding.run_id),
        query,
        lock=write,
        scope_id=product_id,
    )
    if run and (
        (run.request_id, run.project_id, run.build_id)
        != (binding.request_id, binding.project_id, binding.build_id)
        or not _visible(run, ctx)
    ):
        raise DomainError("TEST_PLAN_SCOPE_MISMATCH", "逻辑Run身份不在固定请求与Build范围。")
    reads = _union(row.required_source_read_set, current.required_source_read_set)
    _sources(s, ctx, product_id, reads)
    return binding, row, request, reads


def _lock_union(s, ctx, product_id, binding, data, *, create=False, lock=True):
    """Complete Build/Test asset union before any Start or physical sample inspector."""
    from pdos_next.request_proof import snapshot_get, snapshot_scalar

    if s.info.get("read_snapshot"):
        from pdos_next.domain.build_operational_facts.service import _pointer

        # The physical Start projection reads this exact pointer later in the
        # same RR transaction. Use its canonical proof, keeping writers intact.
        pointer = _pointer(s, ctx, product_id, binding.build_id)
    else:
        pointer = snapshot_scalar(
            s,
            (BuildOperationalCurrent, product_id, binding.build_id),
            select(BuildOperationalCurrent).where(
                BuildOperationalCurrent.tenant_id == ctx.tenant_id,
                BuildOperationalCurrent.product_id == product_id,
                BuildOperationalCurrent.build_id == binding.build_id,
            ),
            scope_id=product_id,
        )
    manufacturing = (
        snapshot_get(s, BuildOperationalFact, pointer.fact_id, scope_id=product_id)
        if pointer
        else None
    )
    specs = {v[1]: v for v in _specs(data)}
    tests = set(specs)
    if manufacturing:
        if (
            manufacturing.tenant_id != ctx.tenant_id
            or manufacturing.product_id != product_id
            or manufacturing.project_id != binding.project_id
            or manufacturing.build_id != binding.build_id
            or not _visible(manufacturing, ctx)
        ):
            raise DomainError("FORBIDDEN_SCOPE", "制造资源前置绑定不在当前范围。", 403)
        for spec in build_asset_specs(
            BuildFactInput.model_validate(manufacturing.data), ctx.tenant_id
        ):
            specs[spec[1]] = spec
    if create:
        _locked_assets(s, ctx, [specs[identity] for identity in tests], create=True, lock=lock)
    _locked_assets(s, ctx, list(specs.values()), lock=lock)


def lock_binding_assets(
    s, ctx, product_id, binding, resource_fact_id, expected_resource_fact_revision, *, write=False
):
    """No effects: parent+full asset locks before the host inspects any physical sample."""
    binding, _, _, _ = _parent_locks(s, ctx, product_id, binding, write=write)
    _, fact = _current(s, ctx, product_id, binding.run_id)
    if (
        fact is None
        or fact.id != resource_fact_id
        or fact.revision != expected_resource_fact_revision
        or fact.binding != binding.model_dump(mode="json")
        or not _visible(fact, ctx)
    ):
        raise DomainError("RESOURCE_FACT_VERSION_CONFLICT", "测试资源精确前置绑定不能核对。")
    _sources(s, ctx, product_id, fact.required_source_read_set, fact.sources)
    _lock_union(
        s, ctx, product_id, binding, TestResourceFactInput.model_validate(fact.data), lock=write
    )


def _require_sample_binding(reference, value):
    """Compare the full fixed physical identity after the narrow availability port."""
    try:
        sample, actual, build = value["sample"], value["actual_configuration"], value["build"]
        observed = SampleRef.model_validate(
            {
                "id": sample["id"],
                "revision": sample["revision"],
                "build_id": build["id"],
                "actual_configuration": {"id": actual["id"], "revision": actual["revision"]},
                "cavity": sample["cavity"],
            }
        )
        # Physical port JSON values are strings; never compare their formatting
        # in place of the UUID identity checked by the fixed SampleRef.
        matches = (
            observed == reference
            and UUID(str(sample["actual_configuration_id"])) == observed.actual_configuration.id
        )
    except (KeyError, TypeError, ValueError, ValidationError) as error:
        raise DomainError("TEST_PLAN_SCOPE_MISMATCH", "实际样件完整身份不能核对。") from error
    if not matches:
        raise DomainError(
            "TEST_PLAN_SCOPE_MISMATCH", "样件版本、Build、实际配置或模穴与固定计划不一致。"
        )


def _scope(
    s,
    ctx,
    product_id,
    binding,
    *,
    write=False,
    resource_data=None,
    create_assets=False,
    retained_at=None,
):
    binding, row, request, reads = _parent_locks(s, ctx, product_id, binding, write=write)
    if resource_data is not None:
        _lock_union(s, ctx, product_id, binding, resource_data, create=create_assets, lock=write)
    samples = {}
    for pair in sorted(binding.pairs, key=lambda v: (v.sample.id.bytes, v.item_id)):
        item = next((i for i in request.items if i.id == pair.item_id), None)
        if item is None or item.destructive != pair.destructive:
            raise DomainError("TEST_PLAN_SCOPE_MISMATCH", "破坏性属性须沿固定测试项。")
        if pair.sample.id not in samples:
            value = inspect_sample(
                s,
                ctx,
                product_id,
                {"id": pair.sample.id, "revision": pair.sample.revision},
                binding.purpose,
                write=False,
                at=retained_at,
                retained_at=retained_at,
            )
            samples[pair.sample.id] = value
            reads = _union(reads, value["required_source_read_set"])
        _require_sample_binding(pair.sample, samples[pair.sample.id])
        _, method = handoff._method_pointer(
            s, ctx, product_id, request.id, pair.sample.id, pair.item_id
        )
        if (
            method is None
            or method.id != pair.method_id
            or method.revision != pair.method_revision
            or method.snapshot_sha256 != pair.method_sha256
        ):
            raise DomainError("ACTUAL_METHOD_UNKNOWN", "实际方法当前版本与计划不一致。")
        handoff._actual_check(
            s,
            ctx,
            product_id,
            request,
            pair.sample,
            samples[pair.sample.id],
            method,
            retained_at=retained_at,
        )
        reads = _union(reads, method.required_source_read_set)
    return binding, row, samples, reads


def physical_projection(value):
    """Only physical facts are shared; scoped manufacturing/test qualifications are not."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return _physical(
        {
            key: value[key]
            for key in ("resource", "lifecycle", "capacity", "calendar", "maintenance")
        }
    )


def _specs(data):
    return [
        (
            "resource",
            r.resource.id,
            digest(r.resource.model_dump(mode="json", exclude={"revision"})),
            r.resource.model_dump(mode="json", exclude={"revision"}),
            r.resource.revision,
            _physical(r.model_dump(mode="json")),
        )
        for r in sorted(data.resources, key=lambda v: v.resource.id.bytes)
    ]


def _assets(s, ctx, data, *, create=False, lock=True):
    values = _locked_assets(s, ctx, _specs(data), create=create, lock=lock)
    for resource in data.resources:
        row = values[resource.resource.id]
        if (
            row.revision != resource.resource.revision
            or row.data.get("state") != "active"
            or physical_projection(row.data["value"]) != physical_projection(resource)
        ):
            raise DomainError("RESOURCE_VERSION_CONFLICT", "当前物理版本、日历、维护或容量已变化。")
    return values


_HASH_FIELDS = (
    "id",
    "tenant_id",
    "product_id",
    "project_id",
    "build_id",
    "run_id",
    "request_id",
    "accepted_request_id",
    "accepted_request_revision",
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


def _fact_hash(row):
    return digest({key: getattr(row, key) for key in _HASH_FIELDS})


def _canonical_rr(s):
    """Only this actual pristine RR transaction may share owner query sets."""
    return (
        isinstance(s, Session)
        and s.is_active is True
        and s.in_transaction()
        and s.info.get("read_snapshot") is True
        and not (s.new or s.dirty or s.deleted)
    )


_MAKER_FACT_STAGE = "test_resource_maker_fact_stage"
_ABSENT_MAKER_ROW = object()


def _held_owner_scope(s, ctx, pid):
    """Exact clean writer scope; the acquired Product gate alone is not a row proof."""
    if (
        not isinstance(s, Session)
        or s.is_active is not True
        or not s.in_transaction()
        or s.info.get("read_snapshot") is True
        or s.new
        or s.dirty
        or s.deleted
    ):
        return None
    from pdos_next.database import require_context
    from pdos_next.request_proof import request_proof

    require_context(s, ctx)
    scope = s.info.get("scope")
    if scope != (ctx.tenant_id, ctx.actor_id, ctx.requester_id, ctx.category_id):
        return None
    # A raw set cannot cross a SAVEPOINT, even when its root lock remains held.
    chain, seen = [], set()
    node = s._transaction
    while node is not None:
        if (
            not isinstance(node, SessionTransaction)
            or id(node) in seen
            or len(chain) >= 128
            or node.session is not s
            or node.is_active is not True
        ):
            return None
        seen.add(id(node))
        chain.append(node)
        node = node.parent
    if not chain:
        return None
    proof = request_proof(s)
    if pid not in proof.scope_locks or chain[-1] is not proof.transaction:
        return None
    if s.get_nested_transaction() is not next((value for value in chain if value.nested), None):
        return None
    try:
        bind = s.get_bind()
    except UnboundExecutionError:
        return None
    stage = s.info.get(_MAKER_FACT_STAGE)
    token = stage.get("token") if isinstance(stage, dict) else None
    return (
        digest(vars(ctx)),
        digest(scope),
        pid,
        proof.transaction,
        tuple(chain),
        proof.mutation_epoch,
        id(bind),
        token,
    )


@contextmanager
def _maker_fact_scope(s):
    """Keep an actual maker row only inside one retained owner inspection."""
    if not isinstance(s, Session):
        yield
        return
    previous = s.info.get(_MAKER_FACT_STAGE, _ABSENT_MAKER_ROW)
    stage = {"token": object(), "rows": {}}
    s.info[_MAKER_FACT_STAGE] = stage
    try:
        yield
    finally:
        if s.info.get(_MAKER_FACT_STAGE) is stage:
            if previous is _ABSENT_MAKER_ROW:
                s.info.pop(_MAKER_FACT_STAGE, None)
            else:
                s.info[_MAKER_FACT_STAGE] = previous


def _remember_maker_fact(s, ctx, pid, run_id, row, *, identity, revision):
    """Register only the complete RLS row returned by the owner's exact maker SELECT."""
    scope = _held_owner_scope(s, ctx, pid)
    stage = s.info.get(_MAKER_FACT_STAGE) if isinstance(s, Session) else None
    if scope is None or not isinstance(stage, dict) or not isinstance(row, TestResourceFact):
        return
    state = inspect_row(row)
    if (
        not state.persistent
        or state.session is not s
        or state.expired
        or state.unloaded & {attribute.key for attribute in row.__mapper__.column_attrs}
        or (row.tenant_id, row.category_id, row.product_id, row.run_id, row.id, row.revision)
        != (ctx.tenant_id, ctx.category_id, pid, run_id, identity, revision)
    ):
        return
    stage["rows"][(scope, run_id, identity)] = row


def _current_fact(s, ctx, pid, run_id, pointer, *, lock=False):
    from pdos_next.request_proof import batch_read, request_proof

    if pointer is None:
        return None
    scope = None if lock else _held_owner_scope(s, ctx, pid)
    stage = s.info.get(_MAKER_FACT_STAGE) if isinstance(s, Session) else None
    maker = (
        stage["rows"].get((scope, run_id, pointer.fact_id))
        if scope and isinstance(stage, dict) and isinstance(stage.get("rows"), dict)
        else None
    )
    if maker is None:
        return batch_read(s, TestResourceFact, [pointer.fact_id]).get(pointer.fact_id)
    state = inspect_row(maker)
    if (
        state.session is not s
        or not state.persistent
        or state.expired
        or state.unloaded & {attribute.key for attribute in maker.__mapper__.column_attrs}
        or (maker.tenant_id, maker.category_id, maker.product_id, maker.run_id, maker.id)
        != (ctx.tenant_id, ctx.category_id, pid, run_id, pointer.fact_id)
    ):
        return batch_read(s, TestResourceFact, [pointer.fact_id]).get(pointer.fact_id)
    # Feed the existing exact-ID reader only for this invocation. Every owner
    # scope/revision/hash/binding check still runs; no other consumer receives
    # a new request-wide row or affirmative source/qualification decision.
    proof = request_proof(s)
    key = (TestResourceFact, pointer.fact_id)
    previous = proof.read_rows.get(key, _ABSENT_MAKER_ROW)
    proof.read_rows[key] = maker
    try:
        return batch_read(s, TestResourceFact, [pointer.fact_id]).get(pointer.fact_id)
    finally:
        if proof.read_rows.get(key) is maker:
            if previous is _ABSENT_MAKER_ROW:
                proof.read_rows.pop(key, None)
            else:
                proof.read_rows[key] = previous


def _current_rows(s, ctx, pid, run_id, *, lock=False):
    from pdos_next.request_proof import scoped_rows

    query = select(TestResourceCurrent).where(
        TestResourceCurrent.tenant_id == ctx.tenant_id,
        TestResourceCurrent.product_id == pid,
        TestResourceCurrent.run_id == run_id,
    )
    if not lock and _canonical_rr(s):
        # Complete raw rows, with actual ctx/scope/query parameters in the key.
        # Retained still requires exactly one; no affirmative status is stored.
        return _owned_rows(s, ctx, pid, query)
    scope = None if lock else _held_owner_scope(s, ctx, pid)
    if scope is not None:
        from pdos_next.request_proof import snapshot_rows

        compiled = query.compile()
        return snapshot_rows(
            s,
            (
                "test-resource-current-owner",
                scope,
                str(compiled),
                json.dumps(compiled.params, sort_keys=True, default=str),
            ),
            query.execution_options(populate_existing=True),
            scope_id=pid,
        )
    return scoped_rows(s, (TestResourceCurrent, run_id), query, lock=lock)


def _current(s, ctx, pid, run_id, *, lock=False):
    pointers = _current_rows(s, ctx, pid, run_id, lock=lock)
    pointer = pointers[0] if pointers else None
    row = _current_fact(s, ctx, pid, run_id, pointer, lock=lock)
    if pointer and (
        row is None
        or row.revision != pointer.fact_revision
        or row.run_id != run_id
        or row.tenant_id != ctx.tenant_id
        or row.product_id != pid
        or row.project_id != pointer.project_id
        or row.build_id != pointer.build_id
        or row.request_id != pointer.request_id
        or _fact_hash(row) != row.fact_sha256
    ):
        raise DomainError("INTEGRITY_MISMATCH", "测试资源事实当前指针无法核对。")
    return pointer, row


def trusted_import(s, ctx, product_id, issuer, payload):
    data = TestResourceFactInput.model_validate(payload)
    issuer = _issuer(s, ctx, product_id, data.binding.project_id, issuer)
    binding, request_row, _, reads = _scope(
        s, ctx, product_id, data.binding, write=True, resource_data=data, create_assets=True
    )
    if data.valid_from > now():
        raise DomainError("INVALID_RESOURCE_TIME", "未来生效事实不能作为已生效导入。", 422)
    sources = references(data)
    evidence_reads, private, basis = _evidence_basis(s, ctx, product_id, sources, reads)
    reads = _union(reads, evidence_reads)
    _, _, basis = _evidence_basis(s, ctx, product_id, sources, reads)
    if request_row.visibility == "category" and private:
        raise DomainError("FORBIDDEN_SCOPE", "私人测试事实不能扩大到共享请求。", 403)
    prior = s.scalar(
        select(TestResourceFact).where(
            TestResourceFact.tenant_id == ctx.tenant_id,
            TestResourceFact.product_id == product_id,
            TestResourceFact.run_id == binding.run_id,
            TestResourceFact.owner_id == ctx.requester_id,
            TestResourceFact.issuer_key == issuer.key,
            TestResourceFact.issuer_version == issuer.version,
            TestResourceFact.issuer_epoch == issuer.epoch,
            TestResourceFact.data == data.model_dump(mode="json"),
        )
    )
    if prior:
        if _fact_hash(prior) != prior.fact_sha256 or prior.source_basis != basis:
            raise DomainError("SOURCE_STALE", "原测试导入依据已经变化。")
        return _fact_view(prior, prior.revision)
    pointer, previous = _current(s, ctx, product_id, binding.run_id, lock=True)
    if (previous.id if previous else None) != data.expected_previous_id or (
        previous.revision if previous else 0
    ) != data.expected_previous_revision:
        raise DomainError("VERSION_CONFLICT", "测试资源整版事实已经变化。")
    if previous and (
        previous.binding != binding.model_dump(mode="json")
        or previous.owner_id != ctx.requester_id
        or previous.issuer_key != issuer.key
        or previous.external_id != data.external_id
    ):
        raise DomainError("TEST_PLAN_SCOPE_MISMATCH", "续版不能改变固定范围、签发方或责任人。")
    # Existing physical mirrors are compared, never rewritten into test-qualified assets.
    _assets(s, ctx, data, create=True)
    identity = uuid4()
    row = TestResourceFact(
        id=identity,
        tenant_id=ctx.tenant_id,
        product_id=product_id,
        project_id=binding.project_id,
        build_id=binding.build_id,
        run_id=binding.run_id,
        request_id=binding.request_id,
        accepted_request_id=binding.accepted_request_id,
        accepted_request_revision=binding.accepted_request_revision,
        owner_id=ctx.requester_id,
        visibility=request_row.visibility,
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
        binding=binding.model_dump(mode="json"),
        data=data.model_dump(mode="json"),
        sources=sources,
        required_source_read_set=reads,
        source_basis=basis,
        reason=data.reason,
    )
    row.fact_sha256 = _fact_hash(row)
    s.add(row)
    s.flush()
    if pointer is None:
        pointer = TestResourceCurrent(
            tenant_id=ctx.tenant_id,
            product_id=product_id,
            project_id=binding.project_id,
            build_id=binding.build_id,
            run_id=binding.run_id,
            request_id=binding.request_id,
            fact_id=row.id,
            fact_revision=row.revision,
            epoch=1,
        )
        s.add(pointer)
    else:
        pointer.fact_id, pointer.fact_revision = row.id, row.revision
        pointer.epoch += 1
    s.flush()
    return _fact_view(row, pointer.epoch)


def _fact_view(row, epoch, *, current=True, source_status="current"):
    return {
        "id": str(row.id),
        "revision": row.revision,
        "epoch": epoch,
        "state": row.state,
        "nature": row.nature,
        "current": current,
        "source_status": source_status,
        "owner_id": str(row.owner_id),
        "visibility": row.visibility,
        "binding": row.binding,
        "resources": row.data["resources"],
        "required_uses": row.data["required_uses"],
        "approved_conditions": row.data["approved_conditions"],
        "valid_from": row.valid_from.isoformat(),
        "valid_until": row.valid_until.isoformat() if row.valid_until else None,
        "sources": row.sources,
        "required_source_read_set": row.required_source_read_set,
        "sha256": row.fact_sha256,
        "reason": row.reason,
    }


def _reservation(s, ctx, pid, binding):
    from pdos_next.request_proof import snapshot_scalar

    row = snapshot_scalar(
        s,
        (TestResourceReservation, pid, binding.run_id),
        select(TestResourceReservation).where(
            TestResourceReservation.tenant_id == ctx.tenant_id,
            TestResourceReservation.product_id == pid,
            TestResourceReservation.run_id == binding.run_id,
        ),
        scope_id=pid,
    )
    if row and (
        not _visible(row, ctx)
        or row.binding != binding.model_dump(mode="json")
        or digest(row.reservation) != row.reservation_sha256
    ):
        raise DomainError("INTEGRITY_MISMATCH", "既有Run预约绑定或摘要无法核对。")
    return row


def _sample_sentinels(s, ctx, pid, binding, *, create=False, lock=True):
    from pdos_next.request_proof import scoped_rows

    sample_ids = sorted({p.sample.id for p in binding.pairs}, key=lambda v: v.bytes)
    if create and sample_ids:
        s.execute(
            insert(SampleUsageSentinel)
            .values(
                [
                    dict(
                        id=uuid5(NAMESPACE_URL, f"pdos:sample-use:{ctx.tenant_id}:{sample_id}"),
                        tenant_id=ctx.tenant_id,
                        product_id=pid,
                        sample_id=sample_id,
                        epoch=1,
                    )
                    for sample_id in sample_ids
                ]
            )
            .on_conflict_do_nothing()
        )
    query = (
        select(SampleUsageSentinel)
        .where(
            SampleUsageSentinel.tenant_id == ctx.tenant_id,
            SampleUsageSentinel.product_id == pid,
            SampleUsageSentinel.sample_id.in_(sample_ids),
        )
        .order_by(SampleUsageSentinel.sample_id)
    )
    return {
        row.sample_id: row
        for row in scoped_rows(s, (SampleUsageSentinel, pid, tuple(sample_ids)), query, lock=lock)
    }


def sample_usage_checks(binding, usages, *, owned_intent=None):
    """Pure capacity-one physical sample check; destructive use is permanent."""
    views, checks = [], []
    for sample_id in sorted({p.sample.id for p in binding.pairs}, key=lambda v: v.bytes):
        relevant = [u for u in usages if u.sample_id == sample_id]
        conflict = next(
            (
                u
                for u in relevant
                if not (u.run_id == binding.run_id and owned_intent == u.intent_digest)
                and (
                    u.destructive
                    or overlap(
                        SimpleNamespace(start=u.window_start, finish=u.window_finish),
                        binding.window,
                    )
                )
            ),
            None,
        )
        own = next((u for u in relevant if u.run_id == binding.run_id), None)
        if conflict:
            state = "consumed" if conflict.destructive else "reserved"
            # Foreign Run identity is deliberately not disclosed by the capacity view.
            views.append(
                SampleUsageView(
                    sample_id=sample_id, state=state, reason="实物已消费或与完整窗口占用冲突。"
                )
            )
            checks.append(
                Check(
                    code="sample_usage_conflict",
                    status="BLOCKED",
                    detail=f"Sample {sample_id} is consumed or reserved in this interval",
                )
            )
        elif own:
            views.append(
                SampleUsageView(
                    sample_id=sample_id,
                    state=own.state,
                    owner_run_id=own.run_id,
                    revision=own.revision,
                )
            )
        else:
            views.append(SampleUsageView(sample_id=sample_id, state="available"))
    return tuple(views), tuple(checks)


def _resource_source(fact, position):
    return SourceRef(id=fact.id, revision=fact.revision, kind="domain", position=position)


def _occupancies(s, ctx, ids, data, *, product_id, own_run_id):
    from pdos_next.domain.build_operational_facts.physical_summary import capacity_summary

    result = [
        Occupancy(
            reservation_id=UUID(value["id"]),
            resource_id=UUID(value["resource_id"]),
            window={
                "start": value["window_start"],
                "finish": value["window_finish"],
                "original_timezone": "UTC",
            },
            units=Decimal(str(value["units"])),
        )
        for value in capacity_summary(
            s, ctx, product_id, "resource", ids, own=own_run_id, own_kind="test_run"
        )
    ]
    for resource in data.resources:
        result.extend(
            Occupancy(
                reservation_id=o.reservation_id,
                resource_id=resource.resource.id,
                window=o.window,
                units=o.units,
            )
            for o in resource.external_occupancies
        )
    return tuple(result)


_FINGERPRINT_V1 = "test-resource-dependency-v1"
_FINGERPRINT_V2 = "test-resource-dependency-v2"
_FINGERPRINT_KEYS = (
    "binding",
    "fact",
    "epoch",
    "issuer",
    "issuer_epochs",
    "assets",
    "sample_epochs",
    "samples",
    "authority",
    "source_basis",
    "proofs",
    "checks",
)


def _fingerprint_json(value):
    """Strict stored JSON with the existing operational digest's exact conversions."""
    if isinstance(value, BaseModel):
        return _fingerprint_json(value.model_dump(mode="python"))
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise TypeError("Non-finite fingerprint decimal")
        text = format(value, "f")
        return (text.rstrip("0").rstrip(".") if "." in text else text) if value else "0"
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise TypeError("Fingerprint datetime must be aware")
        return value.astimezone(UTC).isoformat()
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise TypeError("Fingerprint JSON object keys must be strings")
        return {key: _fingerprint_json(child) for key, child in value.items()}
    if type(value) in (tuple, list):
        return [_fingerprint_json(child) for child in value]
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and isfinite(value):
        return value
    raise TypeError("Unsupported fingerprint JSON value")


def _fingerprint_runtime(s):
    """Full registry is an IO-boundary guard, not a v2 business dependency."""
    engine = s.get_bind()
    registry = getattr(engine, "_pdos_test_resource_issuers", None)
    epochs = getattr(engine, "_pdos_test_resource_issuer_epochs", None)
    if type(registry) is not dict or type(epochs) is not dict:
        raise DomainError("SOURCE_STALE", "缺少完整可信资源配置守卫。")
    if any(
        type(key) is not str or not key or len(key) > 100 or type(epoch) is not int or epoch < 1
        for key, epoch in epochs.items()
    ):
        raise DomainError("SOURCE_STALE", "可信资源配置epoch不可核对。")
    if any(type(key) is not str or not key or len(key) > 100 for key in registry):
        raise DomainError("SOURCE_STALE", "可信资源配置key不可核对。")
    entries = []
    for key, issuer in sorted(registry.items()):
        if (
            type(key) is not str
            or not isinstance(issuer, IssuerContext)
            or issuer._token is not _TOKEN
            or issuer.key != key
            or epochs.get(key) != issuer.epoch
        ):
            raise DomainError("SOURCE_STALE", "可信资源配置身份不可核对。")
        entries.append(
            (
                key,
                id(issuer),
                issuer.version,
                issuer.tenant_id,
                issuer.product_id,
                issuer.project_id,
                issuer.nature,
                issuer.epoch,
                id(issuer._token),
                id(issuer.verify_named_decision),
            )
        )
    return engine, registry, epochs, tuple(entries), tuple(sorted(epochs.items()))


def _same_fingerprint_runtime(s, previous):
    current = _fingerprint_runtime(s)
    if (
        any(current[index] is not previous[index] for index in (0, 1, 2))
        or current[3:] != previous[3:]
    ):
        raise DomainError("SOURCE_STALE", "资源配置在本次完整核对期间变化。")


def _scoped_fingerprint_material(s, ctx, pid, binding, fact, issuer, material):
    """Only called after the actual load's selected issuer/source/owner checks."""
    if (
        issuer is None
        or getattr(fact, "tenant_id", None) != ctx.tenant_id
        or getattr(fact, "product_id", None) != pid
        or getattr(fact, "project_id", None) != binding.project_id
        or issuer.tenant_id != ctx.tenant_id
        or issuer.product_id != pid
        or issuer.project_id not in (None, binding.project_id)
        or issuer.key != fact.issuer_key
        or issuer.version != fact.issuer_version
        or issuer.nature != fact.nature
        or issuer.epoch != fact.issuer_epoch
        or getattr(s.get_bind(), "_pdos_test_resource_issuer_epochs", {}).get(fact.issuer_key)
        != fact.issuer_epoch
    ):
        raise DomainError("TRUSTED_ISSUER_REQUIRED", "v2缺少当前精确固定资源依赖。", 503)
    selected = dict(material)
    selected["issuer"] = {
        "key": fact.issuer_key,
        "scope": {
            "tenant_id": issuer.tenant_id,
            "product_id": issuer.product_id,
            "project_id": issuer.project_id,
        },
        "version": fact.issuer_version,
        "nature": fact.nature,
        "epoch": fact.issuer_epoch,
    }
    selected["issuer_epochs"] = {fact.issuer_key: fact.issuer_epoch}
    return selected


def _validate_fingerprint_v2_json(material):
    """Complete producer shape; never an owner/qualification conclusion."""

    def positive(value, minimum=1):
        return type(value) is int and value >= minimum

    def hash_value(value):
        return (
            type(value) is str
            and len(value) == 64
            and all(char in "0123456789abcdef" for char in value)
        )

    if type(material) is not dict or set(material) != set(_FINGERPRINT_KEYS):
        raise TypeError("v2 fingerprint requires the entire twelve-key material")
    binding = TestPlanBinding.model_validate(material["binding"])
    issuer = material["issuer"]
    if (
        type(issuer) is not dict
        or set(issuer) != {"key", "scope", "version", "nature", "epoch"}
        or type(issuer["key"]) is not str
        or not issuer["key"].strip()
        or len(issuer["key"]) > 100
        or type(issuer["version"]) is not str
        or not issuer["version"].strip()
        or len(issuer["version"]) > 100
        or issuer["nature"] not in {"real", "synthetic"}
        or not positive(issuer["epoch"])
        or type(issuer["scope"]) is not dict
        or set(issuer["scope"]) != {"tenant_id", "product_id", "project_id"}
        or type(material["issuer_epochs"]) is not dict
        or len(material["issuer_epochs"]) != 1
        or type(material["issuer_epochs"].get(issuer["key"])) is not int
        or material["issuer_epochs"] != {issuer["key"]: issuer["epoch"]}
        or not hash_value(material["fact"])
        or not positive(material["epoch"])
    ):
        raise TypeError("Invalid exact scoped dependency")
    # IssuerContext may intentionally be tenant/product scoped with no project;
    # verification.Scope itself requires a project and must not fill one in here.
    for name in ("tenant_id", "product_id"):
        value = issuer["scope"][name]
        if type(value) is not str or str(UUID(value)) != value:
            raise TypeError("Issuer scope requires exact stored UUIDs")
    project = issuer["scope"]["project_id"]
    if project is not None and (type(project) is not str or str(UUID(project)) != project):
        raise TypeError("Issuer project requires an exact stored UUID or null")
    project = UUID(project) if project is not None else None
    if project not in (None, binding.project_id):
        raise TypeError("Issuer project does not bind the actual test scope")
    # The full v1 producer validator checks nested authority, raw source/security
    # closure, complete dumped DTO keys, named proofs and actual sample hashes.
    # Only its validation view has the v1 issuer shape. Never hash or store that
    # view, fill defaults in the original, or treat validation as a current gate.
    try:
        from .fingerprint_compatibility import _READ_ONLY_MATERIAL_VALIDATOR, validate_material
    except ImportError as exc:
        raise DomainError("INTEGRATION_REQUIRED", "v2缺少完整资源材料结构核对端口。", 503) from exc
    read_only = (
        validate_material is _READ_ONLY_MATERIAL_VALIDATOR[0]
        and validate_material.__code__ is _READ_ONLY_MATERIAL_VALIDATOR[1]
    )
    validation_copy = dict(material) if read_only else deepcopy(material)
    validation_copy["issuer"] = [issuer["key"], issuer["version"], issuer["epoch"], True]
    try:
        validate_material(validation_copy)
    except DomainError as exc:
        raise TypeError("Incomplete actual resource producer material") from exc
    authority_scope = material["authority"]["scope"]
    if any(issuer["scope"][name] != authority_scope[name] for name in ("tenant_id", "product_id")):
        raise TypeError("Issuer and actual authority scopes must agree")


def _stored_fingerprint_v2(material):
    """Encoding/integrity only; this pure record is never an owner attestation."""
    if type(material) is not dict or set(material) != set(_FINGERPRINT_KEYS):
        raise TypeError("v2 fingerprint requires the entire twelve-key material")
    raw = {"schema_version": _FINGERPRINT_V2, "material": material}
    stored = _fingerprint_json(raw)
    _validate_fingerprint_v2_json(stored["material"])
    fp = digest(raw)
    if digest(stored) != fp:
        raise DomainError("RESOURCE_FINGERPRINT_MATERIAL_INVALID", "资源存储材料摘要不等价。")
    return {**stored, "facts_revision": fp}


def _verify_stored_fingerprint_v2(record):
    """No v1 fallback, version inference, historical reconstruction or qualification."""
    if (
        type(record) is not dict
        or set(record) != {"schema_version", "material", "facts_revision"}
        or record["schema_version"] != _FINGERPRINT_V2
        or type(record["facts_revision"]) is not str
        or len(record["facts_revision"]) != 64
        or any(char not in "0123456789abcdef" for char in record["facts_revision"])
    ):
        raise DomainError("RESOURCE_FINGERPRINT_MATERIAL_INVALID", "缺少明确v2完整保存材料。")
    try:
        encoded = _stored_fingerprint_v2(record["material"])
    except (TypeError, ValueError, AttributeError) as exc:
        raise DomainError(
            "RESOURCE_FINGERPRINT_MATERIAL_INVALID", "v2完整保存材料结构不可核对。"
        ) from exc
    if encoded != record:
        raise DomainError("RESOURCE_FINGERPRINT_MATERIAL_INVALID", "v2保存材料或摘要不可核对。")
    # _fingerprint_json already rebuilt every dict/list from the caller's record.
    # The complete verified tree is independent without another recursive copy.
    return encoded


def _reservation_fingerprint(row):
    """Dispatch solely from the saved owner; absent v1 columns stay compatible."""
    version = getattr(row, "fingerprint_version", None)
    record = getattr(row, "dependency_proof", None)
    if version is None and record is None:
        return _FINGERPRINT_V1, None
    if type(version) is not str or version != _FINGERPRINT_V2:
        raise DomainError("RESOURCE_FINGERPRINT_VERSION_UNSUPPORTED", "保存资源版本不可核对。", 503)
    record = _verify_stored_fingerprint_v2(record)
    try:
        binding = _fingerprint_json(TestPlanBinding.model_validate(row.binding))
    except (TypeError, ValueError, AttributeError) as exc:
        raise DomainError("INTEGRITY_MISMATCH", "保存预约的完整计划绑定不可核对。") from exc
    if record["facts_revision"] != row.facts_revision or record["material"]["binding"] != binding:
        raise DomainError("INTEGRITY_MISMATCH", "保存材料不等于原Run预约绑定与摘要。")
    return version, record


def _fingerprint_sink(version, collector):
    if collector is not None and (type(collector) is not list or collector):
        raise TypeError("Fingerprint collector must be an empty builtin list")
    if type(version) is not str or version not in (_FINGERPRINT_V1, _FINGERPRINT_V2):
        raise DomainError("RESOURCE_FINGERPRINT_VERSION_UNSUPPORTED", "不支持的资源材料版本。", 503)
    if version == _FINGERPRINT_V2 and collector is None:
        raise DomainError("RESOURCE_FINGERPRINT_MATERIAL_REQUIRED", "v2须由宿主完整收集。", 503)


def _load(
    s,
    ctx,
    pid,
    binding,
    fact_id,
    revision,
    *,
    at=None,
    write=False,
    verified_actual_start=None,
    own_intent=None,
    retained=False,
    retained_authority=None,
    _fingerprint_collector=None,
    _fingerprint_version=_FINGERPRINT_V1,
):
    # A private, non-callback sink: invalid/reused sinks fail before owner IO.
    _fingerprint_sink(_fingerprint_version, _fingerprint_collector)
    if _fingerprint_version == _FINGERPRINT_V2 and retained and own_intent is None:
        raise DomainError(
            "RESOURCE_FINGERPRINT_MATERIAL_REQUIRED", "v2历史核对须读取实际保存预约。", 503
        )
    fingerprint_runtime = (
        _fingerprint_runtime(s) if _fingerprint_version == _FINGERPRINT_V2 else None
    )
    at = _at(at)
    lock_binding_assets(s, ctx, pid, binding, fact_id, revision, write=write)
    _, fixed = _current(s, ctx, pid, TestPlanBinding.model_validate(binding).run_id)
    binding, _parent, samples, reads = _scope(
        s,
        ctx,
        pid,
        binding,
        write=write,
        resource_data=TestResourceFactInput.model_validate(fixed.data),
        retained_at=at if retained else None,
    )
    pointer, fact = _current(s, ctx, pid, binding.run_id)
    if (
        fact is None
        or fact.id != fact_id
        or fact.revision != revision
        or fact.binding != binding.model_dump(mode="json")
        or not _visible(fact, ctx)
    ):
        raise DomainError("RESOURCE_FACT_VERSION_CONFLICT", "固定测试事实或当前范围不可核对。")
    data = TestResourceFactInput.model_validate(fact.data)
    reads = _union(reads, fact.required_source_read_set)
    _sources(s, ctx, pid, reads, fact.sources)  # Current consumer, independent of provenance.
    from pdos_next.domain.build_operational_facts.service import evidence_watermark

    _, _, basis = _evidence_basis(s, ctx, pid, fact.sources, fact.required_source_read_set)
    checks = []
    if evidence_watermark(basis) != evidence_watermark(fact.source_basis):
        checks.append(
            Check(
                code="resource_source_changed",
                status="BLOCKED",
                detail="Imported original/source or issuer access epoch changed",
            )
        )
    issuer = getattr(s.get_bind(), "_pdos_test_resource_issuers", {}).get(fact.issuer_key)
    if (
        issuer is None
        or issuer.version != fact.issuer_version
        or issuer.epoch != fact.issuer_epoch
        or issuer.nature != fact.nature
    ):
        checks.append(
            Check(
                code="trusted_issuer_unavailable",
                status="UNKNOWN",
                detail="The exact current trusted issuer is unavailable",
            )
        )
        issuer = None
    else:
        _issuer(s, ctx, pid, binding.project_id, issuer)
    if (
        fact.state != "active"
        or fact.valid_from > at
        or (fact.valid_until is not None and at >= fact.valid_until)
    ):
        checks.append(
            Check(
                code="test_fact_inactive",
                status="BLOCKED",
                detail="Fixed test facts are withdrawn or outside their validity",
            )
        )
    if fact.valid_from > binding.window.start or (
        fact.valid_until is not None and fact.valid_until < binding.window.finish
    ):
        checks.append(
            Check(
                code="test_fact_window_unknown",
                status="UNKNOWN",
                detail="Test facts do not cover the whole execution window",
            )
        )
    assets = _assets(s, ctx, data, lock=write)
    existing = _reservation(s, ctx, pid, binding)
    if existing and own_intent is not None and existing.intent_digest != own_intent:
        raise DomainError("RUN_INTENT_CONFLICT", "该Run已有不同开测意图。")
    saved_record = None
    if _fingerprint_version == _FINGERPRINT_V2:
        if retained and (existing is None or own_intent is None):
            raise DomainError(
                "RESOURCE_FINGERPRINT_MATERIAL_REQUIRED", "v2历史核对须读取实际保存预约。", 503
            )
        if existing is not None:
            saved_version, saved_record = _reservation_fingerprint(existing)
            if saved_version != _FINGERPRINT_V2:
                raise DomainError(
                    "RESOURCE_FINGERPRINT_VERSION_UNSUPPORTED", "不能将旧预约推断为v2。", 503
                )
    # Current write authorization also protects saved-owner replay, but it must
    # never bootstrap a consuming reference again. Even a conflicting INSERT
    # fires the lifecycle BEFORE trigger and changes the Product watermark.
    sentinels = _sample_sentinels(
        s, ctx, pid, binding, create=write and existing is None, lock=write
    )
    if existing is not None and set(sentinels) != {p.sample.id for p in binding.pairs}:
        raise DomainError("RUN_SAMPLE_USAGE_MISSING", "原Run样件使用门栓缺失，不能重建。")
    from pdos_next.domain.build_operational_facts.physical_summary import capacity_summary

    own_usages = _own_usages(s, ctx, pid, binding.run_id, write=write)
    foreign_usages = [
        SimpleNamespace(
            sample_id=UUID(value["sample_id"]),
            destructive=value["destructive"],
            window_start=datetime.fromisoformat(value["window_start"]),
            window_finish=datetime.fromisoformat(value["window_finish"]),
            run_id=None,
            intent_digest=None,
            state="consumed" if value["destructive"] else "reserved",
        )
        for value in capacity_summary(
            s,
            ctx,
            pid,
            "sample",
            {pair.sample.id for pair in binding.pairs},
            own=binding.run_id,
            own_kind="test_run",
            watermark=tuple((key, row.epoch) for key, row in sorted(sentinels.items())),
        )
    ]
    usages = [*own_usages, *foreign_usages]
    if existing:
        _own_proof(s, ctx, pid, binding, data, existing, usages, write=write)
    owned = existing is not None and own_intent is not None
    own = own_intent if owned else None
    usage_views, usage_checks = sample_usage_checks(binding, usages, owned_intent=own)
    checks.extend(usage_checks)
    for sample_id, value in samples.items():
        if value["availability"] != "ready":
            checks.append(
                Check(
                    code="sample_not_ready",
                    status="BLOCKED",
                    detail=f"Sample {sample_id} current purpose readiness is not ready",
                )
            )
    if retained and retained_authority:
        retained_check = professional.recheck_snapshot(
            s, ctx, pid, binding.project_id, retained_authority, at, retained=True
        )
        authority = retained_check["assessment"] if retained_check["current"] else {}
    else:
        authority = professional.assess(
            s,
            ctx,
            pid,
            binding.project_id,
            OPERATION,
            binding.purpose,
            at,
            subject_id=binding.executor_id,
        )
    qualified = (
        authority.get("authorized") is True
        and authority.get("qualified") is True
        and "quality" in authority.get("roles", ())
    )
    if not professional.authority_time_current(authority, at):
        qualified = False
        checks.append(
            Check(
                code="executor_window_unknown",
                status="UNKNOWN",
                detail="Named quality qualification is not currently eligible",
            )
        )
    reads = _union(reads, authority.get("required_source_read_set", ()))
    _sources(s, ctx, pid, reads)
    snapshots, proofs = [], []
    deadlines = []
    for resource in data.resources:
        asset = assets[resource.resource.id]
        facts = []
        for decision in resource.facts:
            proof = None
            if issuer and issuer.verify_named_decision and decision.status == "accepted":
                raw = issuer.verify_named_decision(
                    s, ctx, fact.binding, resource.resource, decision, at
                )
                proof = DecisionProof.model_validate(raw) if raw is not None else None
            status = decision.status
            if status == "accepted" and (
                proof is None
                or not proof.current
                or (proof.valid_until is not None and proof.valid_until < binding.window.finish)
            ):
                status = "unknown"
            proofs.append(
                {
                    "resource": resource.resource.model_dump(mode="json"),
                    "decision": decision.model_dump(mode="json"),
                    "proof": proof.model_dump(mode="json") if proof else None,
                }
            )
            if proof and proof.valid_until:
                deadlines.append(proof.valid_until)
            if decision.valid_until:
                deadlines.append(decision.valid_until)
            facts.append(
                QualificationFact(
                    kind=decision.kind,
                    purpose=decision.purpose,
                    operation_id=decision.operation_id,
                    status=status,
                    source=_resource_source(
                        fact, f"resource:{resource.resource.id}:" + decision.kind
                    ),
                    valid_from=decision.valid_from,
                    valid_until=decision.valid_until,
                    conditions=decision.conditions,
                    named_decision_id=decision.named_decision_id,
                    actor_id=decision.actor_id,
                )
            )
        if not resource.external_occupancies_complete:
            checks.append(
                Check(
                    resource=resource.resource,
                    code="occupancy_scope_unknown",
                    status="UNKNOWN",
                    detail="External occupancy completeness has not been verified",
                )
            )
        snapshots.append(
            ResourceSnapshot(
                ref=resource.resource,
                scope=Scope(tenant_id=ctx.tenant_id, product_id=pid, project_id=binding.project_id),
                source=_resource_source(fact, f"resource:{resource.resource.id}"),
                purposes=resource.purposes,
                operation_ids=resource.operation_ids,
                lifecycle=resource.lifecycle,
                facts=tuple(facts),
                maintenance=tuple(
                    MaintenanceFact(
                        window=v.window,
                        status=v.status,
                        source=_resource_source(fact, f"maintenance:{resource.resource.id}:{i}"),
                    )
                    for i, v in enumerate(resource.maintenance)
                )
                if resource.maintenance is not None
                else None,
                calendar=resource.calendar,
                calendar_source=_resource_source(fact, f"calendar:{resource.resource.id}")
                if resource.calendar
                else None,
                capacity=resource.capacity,
                occupancy_revision=asset.occupancy_epoch - (1 if owned else 0),
            )
        )
    fp_material = {
        "binding": binding,
        "fact": fact.fact_sha256,
        "epoch": pointer.epoch,
        "issuer": [fact.issuer_key, fact.issuer_version, fact.issuer_epoch, issuer is not None],
        "issuer_epochs": getattr(s.get_bind(), "_pdos_test_resource_issuer_epochs", {}),
        "assets": [
            {
                "id": a.id,
                "revision": a.revision,
                "sha256": a.data_sha256,
                "epoch": a.occupancy_epoch - (1 if owned else 0),
            }
            for a in assets.values()
        ],
        "sample_epochs": {
            str(k): (sentinels[k].epoch if k in sentinels else 1) - (1 if owned else 0)
            for k in sorted(samples, key=lambda v: v.bytes)
        },
        "samples": {str(k): v.get("facts_revision") for k, v in samples.items()},
        "authority": authority,
        "source_basis": basis,
        "proofs": proofs,
        "checks": [v.model_dump(mode="json") for v in checks],
    }
    if _fingerprint_version == _FINGERPRINT_V2:
        fp_material = _scoped_fingerprint_material(s, ctx, pid, binding, fact, issuer, fp_material)
        fingerprint_record = _stored_fingerprint_v2(fp_material)
        fp = fingerprint_record["facts_revision"]
        if saved_record is not None and fingerprint_record != saved_record:
            raise DomainError("RESOURCE_FACTS_CHANGED", "完整当前资源材料不等于原保存v2依赖。")
    else:
        fp = digest(fp_material)
        # Preserve the original v1 typed two-key collector protocol exactly.
        fingerprint_record = (
            {"material": deepcopy(fp_material), "facts_revision": fp}
            if _fingerprint_collector is not None
            else None
        )
    context = ResourceContext(
        scope=Scope(tenant_id=ctx.tenant_id, product_id=pid, project_id=binding.project_id),
        actor_id=ctx.requester_id,
        owner_run_id=binding.run_id,
        executor_id=binding.executor_id,
        now=at,
        authorized=True,
        qualified=qualified,
        cancelled=False,
        sources_current=not any(v.code == "resource_source_changed" for v in checks),
        policy_registered=True,
        facts_revision=fp,
        purpose=binding.purpose,
        operation_id=OPERATION,
        required_resources=data.required_uses,
        approved_conditions=data.approved_conditions,
        verified_actual_start=verified_actual_start.occurred_at if verified_actual_start else None,
    )
    request = _request(binding, data)
    occupancies = _occupancies(
        s, ctx, tuple(assets), data, product_id=pid, own_run_id=binding.run_id
    )
    report = evaluate(
        context,
        request,
        tuple(snapshots),
        occupancies,
        tuple(checks),
        exclude_reservation_id=binding.run_id if owned else None,
    )
    value = BoundTestResources(
        binding=binding,
        report=report,
        fact_ref=FactRef(
            id=fact.id,
            revision=fact.revision,
            epoch=pointer.epoch,
            sha256=fact.fact_sha256,
            nature=fact.nature,
        ),
        facts_revision=fp,
        resources=tuple(snapshots),
        uses=data.required_uses,
        required_source_read_set=reads,
        valid_until=fact.valid_until,
        expiry_boundaries=tuple(deadlines),
        authority_basis=deepcopy(authority),
        nature=fact.nature,
        sample_usage=usage_views,
    )
    if saved_record is not None:
        saved_version, latest_record = _reservation_fingerprint(existing)
        if (
            saved_version != _FINGERPRINT_V2
            or latest_record != fingerprint_record
            or (own_intent is not None and existing.intent_digest != own_intent)
        ):
            raise DomainError("INTEGRITY_MISMATCH", "原v2预约在完整当前核对期间改变。")
    if fingerprint_runtime is not None:
        _same_fingerprint_runtime(s, fingerprint_runtime)
    # An expensive check must never return an affirmative value after a bound
    # authority/issuer decision expires during that very check.
    if (
        not retained
        and value.report.status in {"READY", "READY_WITH_CONDITIONS"}
        and expired(value, now())
    ):
        raise DomainError("SOURCE_STALE", "资格在本次核对期间到期，请重新核对。")
    if _fingerprint_collector is not None:
        # Failed/expired checks emit nothing; a sink cannot be reused mid-load.
        if _fingerprint_collector:
            raise TypeError("Fingerprint collector changed during owner IO")
        _fingerprint_collector.append(fingerprint_record)
    return value, context, request, data, assets, sentinels, existing


def _owned_read_snapshot(s, pid=None, *, write=False):
    if not isinstance(s, Session) or not s.in_transaction() or s.new or s.dirty or s.deleted:
        return False
    if not write and s.info.get("read_snapshot") is True:
        return True
    from pdos_next.request_proof import request_proof

    return pid is not None and pid in request_proof(s).scope_locks


def _owned_rows(s, ctx, pid, query, *, write=False, fresh=False):
    """Share exact own rows under RR or their actual held Product fence.

    Every own-row writer takes this same Product gate through the database's
    lifecycle_reference BEFORE trigger. Full binding/hash/source checks still
    run for every caller; the terminal owner uses fresh=True to catch writes
    in this Session, including raw SQL that bypassed ORM invalidation.
    """
    from pdos_next.database import require_context
    from pdos_next.request_proof import snapshot_rows

    if isinstance(s, Session):
        require_context(s, ctx)
    if fresh or not _owned_read_snapshot(s, pid, write=write):
        return list(s.scalars(query.execution_options(populate_existing=True)))
    compiled = query.compile()
    key = (
        "test-resource-own-effects",
        digest(vars(ctx)),
        digest(s.info.get("scope")),
        str(compiled),
        json.dumps(compiled.params, sort_keys=True, default=str),
    )
    return snapshot_rows(s, key, query, scope_id=pid)


def _own_occupancies(s, ctx, pid, run_id, *, write=False):
    # Do not narrow product/project/build: malformed extra own rows must remain
    # visible to the complete owner cardinality and binding checks.
    return _owned_rows(
        s,
        ctx,
        pid,
        select(ResourceOccupancy).where(
            ResourceOccupancy.tenant_id == ctx.tenant_id,
            ResourceOccupancy.owner_kind == "test_run",
            ResourceOccupancy.owner_execution_id == run_id,
        ),
        write=write,
    )


def _own_usages(s, ctx, pid, run_id, *, write=False):
    # This is the original full Run collection, without project/build filtering.
    return _owned_rows(
        s,
        ctx,
        pid,
        select(SampleRunUsage).where(
            SampleRunUsage.tenant_id == ctx.tenant_id,
            SampleRunUsage.product_id == pid,
            SampleRunUsage.run_id == run_id,
        ),
        write=write,
    )


def _own_proof(s, ctx, pid, binding, data, existing, usages, *, write=False):
    """Only exact retained own effects permit subtracting one own epoch bump."""
    reservation = Reservation.model_validate(existing.reservation)
    request = _request(binding, data)
    if reservation.state != "formal" or reservation.request != request:
        raise DomainError("RUN_RESERVATION_MISSING", "原Run资源预约不等于当前固定绑定。")
    own = _own_occupancies(s, ctx, pid, binding.run_id, write=write)
    if len(own) != len(request.uses) or {
        (
            o.resource_id,
            o.resource_revision,
            o.units,
            o.window_start,
            o.window_finish,
            o.intent_digest,
            o.product_id,
            o.project_id,
            o.build_id,
            o.test_run_id,
            digest(o.reservation),
        )
        for o in own
    } != {
        (
            u.resource.id,
            u.resource.revision,
            u.units,
            binding.window.start,
            binding.window.finish,
            existing.intent_digest,
            pid,
            binding.project_id,
            binding.build_id,
            binding.run_id,
            existing.reservation_sha256,
        )
        for u in request.uses
    }:
        raise DomainError("RUN_RESERVATION_MISSING", "原Run资源占用证据缺失或改变。")
    relevant = [u for u in usages if u.run_id == binding.run_id]
    if len(relevant) != len({p.sample.id for p in binding.pairs}):
        raise DomainError("RUN_SAMPLE_USAGE_MISSING", "原Run样件使用证据不完整。")
    for sample_id in {p.sample.id for p in binding.pairs}:
        pairs = [p for p in binding.pairs if p.sample.id == sample_id]
        matches = [u for u in relevant if u.sample_id == sample_id]
        if len(matches) != 1:
            raise DomainError("RUN_SAMPLE_USAGE_MISSING", "原Run样件使用证据缺失。")
        usage, sample = matches[0], pairs[0].sample
        destructive = any(p.destructive for p in pairs)
        if (
            usage.product_id != pid
            or usage.project_id != binding.project_id
            or usage.build_id != binding.build_id
            or usage.intent_digest != existing.intent_digest
            or usage.sample_revision != sample.revision
            or usage.actual_configuration_id != sample.actual_configuration.id
            or usage.actual_configuration_revision != sample.actual_configuration.revision
            or usage.window_start != binding.window.start
            or usage.window_finish != binding.window.finish
            or usage.destructive != destructive
            or usage.state != ("consumed" if destructive else "reserved")
            or usage.source_basis["pairs"] != [p.model_dump(mode="json") for p in pairs]
        ):
            raise DomainError("RUN_SAMPLE_USAGE_MISSING", "原Run样件固定版本或用途证据漂移。")
        _sources(s, ctx, pid, usage.required_source_read_set)


def _request(binding, data):
    return ReservationRequest(
        reservation_id=binding.run_id,
        owner_run_id=binding.run_id,
        intent_key="canonical-test-start",
        purpose=binding.purpose,
        operation_id=OPERATION,
        window=binding.window,
        uses=data.required_uses,
    )


def load_bundle(
    s,
    ctx,
    product_id,
    binding,
    resource_fact_id,
    expected_resource_fact_revision,
    *,
    at=None,
    write=False,
    verified_actual_start=None,
    own_intent=None,
    _fingerprint_version=_FINGERPRINT_V1,
    _fingerprint_collector=None,
):
    _fingerprint_sink(_fingerprint_version, _fingerprint_collector)
    if own_intent is not None:
        fixed, _, _, _ = _scope(s, ctx, product_id, binding, write=write)
        owner = _reservation(s, ctx, product_id, fixed)
        if owner is not None:
            if owner.intent_digest != own_intent:
                raise DomainError("RUN_INTENT_CONFLICT", "该Run已有不同开测意图。")
            saved_version, _ = _reservation_fingerprint(owner)
            if _fingerprint_version == _FINGERPRINT_V2 and saved_version != _FINGERPRINT_V2:
                raise DomainError(
                    "RESOURCE_FINGERPRINT_VERSION_UNSUPPORTED", "不能将旧预约推断为v2。", 503
                )
            _fingerprint_version = saved_version
            if saved_version == _FINGERPRINT_V2 and _fingerprint_collector is None:
                _fingerprint_collector = []
    return _load(
        s,
        ctx,
        product_id,
        binding,
        resource_fact_id,
        expected_resource_fact_revision,
        at=at,
        write=write,
        verified_actual_start=verified_actual_start,
        own_intent=own_intent,
        _fingerprint_version=_fingerprint_version,
        _fingerprint_collector=_fingerprint_collector,
    )[0]


inspect_plan = load_bundle


class _Ports:
    """One host-bound resource subprotocol; proof is asserted, never minted or consumed."""

    def __init__(
        self,
        s,
        ctx,
        pid,
        binding,
        fact_id,
        revision,
        *,
        intent,
        accepted,
        verified_actual_start,
        fingerprint_version=_FINGERPRINT_V1,
        expected_facts_revision=None,
    ):
        self.s, self.ctx, self.pid = s, ctx, pid
        self.binding, self.fact_id, self.revision = binding, fact_id, revision
        self.intent, self.accepted = intent, accepted
        self.event = verified_actual_start
        self.latest = None
        self.fingerprint_version = fingerprint_version
        self.expected_facts_revision = expected_facts_revision
        self.latest_record = None
        self.latest_runtime = None
        self.latest_stamp = None

    def _stamp(self):
        from pdos_next.domain.capa_effectiveness.fact_atom_storage import _uow
        from pdos_next.request_proof import request_proof

        return (
            _uow(self.s),
            digest(vars(self.ctx)),
            digest(
                (
                    self.pid,
                    self.binding,
                    self.fact_id,
                    self.revision,
                    self.intent,
                    self.accepted,
                    self.event,
                    self.expected_facts_revision,
                )
            ),
            _fingerprint_runtime(self.s),
            request_proof(self.s).mutation_epoch,
        )

    def _close(self):
        _same_fingerprint_runtime(self.s, self.latest_runtime)
        at = now()
        if expired(self.latest[0], at) or not (
            self.binding.window.start <= at < self.binding.window.finish
        ):
            raise DomainError("SOURCE_STALE", "具名资格、资源或执行窗口在开测核对期间到期。")

    def fresh(self):
        # First v2 load holds the complete parent, asset and sample sentinel
        # locks. The kernel's context/lock/stage callbacks share that same UOW.
        # Changes or mutations rebuild it; every hit still closes real time and
        # issuer state. This private port never survives this one Start.
        from pdos_next.request_proof import request_proof

        memo = (
            isinstance(self.s, Session)
            and self.fingerprint_version == _FINGERPRINT_V2
            and self.pid in request_proof(self.s).scope_locks
            and not (self.s.new or self.s.dirty or self.s.deleted)
        )
        if memo and self.latest_stamp is not None and self.latest_stamp == self._stamp():
            self._close()
            return self.latest
        collector = [] if self.fingerprint_version == _FINGERPRINT_V2 else None
        runtime = _fingerprint_runtime(self.s) if collector is not None else None
        self.latest = _load(
            self.s,
            self.ctx,
            self.pid,
            self.binding,
            self.fact_id,
            self.revision,
            write=True,
            verified_actual_start=self.event,
            own_intent=self.intent,
            _fingerprint_version=self.fingerprint_version,
            _fingerprint_collector=collector,
        )
        if collector is not None:
            if len(collector) != 1:
                raise DomainError("INTEGRATION_REQUIRED", "宿主未取得完整v2当前资源记录。", 503)
            self.latest_record = _verify_stored_fingerprint_v2(collector[0])
            if (
                self.latest_record["facts_revision"] != self.latest[0].facts_revision
                or self.latest[0].facts_revision != self.expected_facts_revision
            ):
                raise DomainError("RESOURCE_FACTS_CHANGED", "v2材料在共同确认后发生变化。")
            _same_fingerprint_runtime(self.s, runtime)
            self.latest_runtime = runtime
        if self.latest[0].report.status not in {"READY", "READY_WITH_CONDITIONS"}:
            raise DomainError("TEST_RESOURCES_NOT_READY", "完整测试资源或样件当前不可开测。")
        if memo:
            self.latest_stamp = self._stamp()
            self._close()
        return self.latest

    def context(self, owner_run_id, purpose, operation_id):
        value = self.fresh()
        if (owner_run_id, purpose, operation_id) != (
            self.binding.run_id,
            self.binding.purpose,
            OPERATION,
        ):
            raise DomainError("TEST_PLAN_SCOPE_MISMATCH", "资源协议不能变更Run、用途或操作。")
        return value[1]

    def resources(self, context, resource_ids):
        return tuple(v for v in self.latest[0].resources if v.ref.id in resource_ids)

    def source_status(self, context, source):
        # Domain references here are generated solely from the exact current Fact.
        fact = self.latest[0].fact_ref
        if source.kind != "domain" or source.id != fact.id or source.revision != fact.revision:
            return "drifted"
        return "current"

    def lock(self, context, request):
        self.fresh()  # Product→Formal→Run→same global assets→sample-use sentinels.

    def find(self, context, request):
        row = self.latest[6]
        return Reservation.model_validate(row.reservation) if row else None

    def occupancies(self, context, resource_ids):
        return _occupancies(
            self.s,
            self.ctx,
            resource_ids,
            self.latest[3],
            product_id=self.pid,
            own_run_id=self.binding.run_id,
        )

    def confirm(self, context, preview):
        if (
            self.accepted is not True
            or self.ctx.requester_id != self.binding.executor_id
            or preview.request != self.latest[2]
            or preview.context_revision != self.latest[0].facts_revision
        ):
            raise DomainError(
                "CONFIRMATION_REQUIRED", "必须先消费绑定本Run完整读集的共同开测确认。", 403
            )

    def stage(self, context, reservation, expected_revision, expected_occupancy_revisions):
        bundle, _, request, _, assets, sentinels, previous = self.fresh()
        if (
            previous is not None
            or expected_revision != 0
            or reservation.request != request
            or reservation.state != "formal"
            or dict(expected_occupancy_revisions)
            != {k: v.occupancy_epoch for k, v in assets.items()}
            or reservation.id != self.binding.run_id
        ):
            raise DomainError("RUN_RESERVATION_CONFLICT", "Run预约或共享容量版本发生冲突。")
        from pdos_next.domain.verification_launch.models import VerificationRunIdentity

        identity = self.s.scalar(
            select(VerificationRunIdentity).where(
                VerificationRunIdentity.tenant_id == self.ctx.tenant_id,
                VerificationRunIdentity.product_id == self.pid,
                VerificationRunIdentity.id == self.binding.run_id,
            )
        )
        if identity is None:
            raise DomainError("INTEGRATION_REQUIRED", "正式预约须绑定本事务真实Run身份。")
        event_reads = [
            {
                "artifact_id": str(self.event.source.id),
                "expected_revision": self.event.source.revision,
            }
        ]
        reads = _union(bundle.required_source_read_set, event_reads)
        if getattr(self, "direct_contract", False):
            self._close()
        else:
            _sources(self.s, self.ctx, self.pid, reads)
        fields = {}
        if self.fingerprint_version == _FINGERPRINT_V2:
            if (
                context.facts_revision != bundle.facts_revision
                or self.latest_record is None
                or self.latest_record["facts_revision"] != bundle.facts_revision
            ):
                raise DomainError("RESOURCE_FACTS_CHANGED", "保存预约须沿共同确认的完整v2材料。")
            if getattr(self, "direct_contract", False):
                self._close()
            else:
                _same_fingerprint_runtime(self.s, self.latest_runtime)
            fields = {
                "fingerprint_version": _FINGERPRINT_V2,
                "dependency_proof": deepcopy(self.latest_record),
            }
        encoded = reservation.model_dump(mode="json")
        row = TestResourceReservation(
            id=reservation.id,
            tenant_id=self.ctx.tenant_id,
            product_id=self.pid,
            project_id=self.binding.project_id,
            build_id=self.binding.build_id,
            run_id=self.binding.run_id,
            fact_id=self.fact_id,
            fact_revision=self.revision,
            owner_id=self.ctx.requester_id,
            visibility=identity.visibility,
            revision=1,
            state="formal",
            intent_digest=self.intent,
            binding=self.binding.model_dump(mode="json"),
            reservation=encoded,
            reservation_sha256=digest(encoded),
            required_source_read_set=reads,
            facts_revision=bundle.facts_revision,
            **fields,
        )
        self.s.add(row)
        for use in request.uses:
            oid = uuid5(self.binding.run_id, f"test-resource:{use.resource.id}")
            self.s.add(
                ResourceOccupancy(
                    id=oid,
                    tenant_id=self.ctx.tenant_id,
                    product_id=self.pid,
                    project_id=self.binding.project_id,
                    build_id=self.binding.build_id,
                    owner_execution_id=self.binding.run_id,
                    owner_kind="test_run",
                    build_start_id=None,
                    test_run_id=self.binding.run_id,
                    asset_id=use.resource.id,
                    resource_id=use.resource.id,
                    resource_revision=use.resource.revision,
                    window_start=request.window.start,
                    window_finish=request.window.finish,
                    units=use.units,
                    intent_digest=self.intent,
                    reservation=encoded,
                )
            )
            assets[use.resource.id].occupancy_epoch += 1
        for sample_id in sorted(sentinels, key=lambda v: v.bytes):
            pairs = [p for p in self.binding.pairs if p.sample.id == sample_id]
            sample = pairs[0].sample
            destructive = any(p.destructive for p in pairs)
            self.s.add(
                SampleRunUsage(
                    id=uuid5(self.binding.run_id, f"test-sample:{sample_id}"),
                    tenant_id=self.ctx.tenant_id,
                    product_id=self.pid,
                    project_id=self.binding.project_id,
                    build_id=self.binding.build_id,
                    run_id=self.binding.run_id,
                    sample_id=sample_id,
                    sample_revision=sample.revision,
                    actual_configuration_id=sample.actual_configuration.id,
                    actual_configuration_revision=sample.actual_configuration.revision,
                    revision=1,
                    owner_id=self.ctx.requester_id,
                    visibility=identity.visibility,
                    destructive=destructive,
                    state="consumed" if destructive else "reserved",
                    window_start=request.window.start,
                    window_finish=request.window.finish,
                    coverage=[{"sample_id": str(p.sample.id), "item_id": p.item_id} for p in pairs],
                    intent_digest=self.intent,
                    source_basis={
                        "actual_start": self.event.model_dump(mode="json"),
                        "pairs": [p.model_dump(mode="json") for p in pairs],
                        "facts_revision": bundle.facts_revision,
                    },
                    required_source_read_set=reads,
                )
            )
            sentinels[sample_id].epoch += 1
        self.s.flush()  # Caller owns rollback, Receipt/Audit/Outbox and commit.
        if self.fingerprint_version == _FINGERPRINT_V2:
            if getattr(self, "direct_contract", False):
                self._close()
            else:
                _same_fingerprint_runtime(self.s, self.latest_runtime)
            checked_at = now()
            if (
                not getattr(self, "direct_contract", False) and expired(bundle, checked_at)
            ) or not (self.binding.window.start <= checked_at < self.binding.window.finish):
                raise DomainError("SOURCE_STALE", "v2资格或执行窗口在保存期间到期。")
            version, proof = _reservation_fingerprint(row)
            if version != _FINGERPRINT_V2 or proof != self.latest_record:
                raise DomainError("INTEGRITY_MISMATCH", "同事务保存v2材料不能精确核对。")


def _start_guard(s, ctx, pid, binding, verified_actual_start):
    event = EventTime.model_validate(verified_actual_start)
    if (
        ctx.requester_id != binding.executor_id
        or event.source.kind != "artifact"
        or event.occurred_at > now()
        or not binding.window.start <= event.occurred_at < binding.window.finish
        or not binding.window.start <= now() < binding.window.finish
    ):
        raise DomainError("INVALID_TEST_START", "实际开测须本人、精确原文且处于固定执行窗口。")
    _sources(
        s,
        ctx,
        pid,
        [{"artifact_id": str(event.source.id), "expected_revision": event.source.revision}],
    )
    request = front._snapshot(front._row(s, ctx, pid, binding.accepted_request_id))
    selected = {(p.sample.id, p.item_id) for p in binding.pairs}
    last_acceptance = max(
        a.at.occurred_at
        for a in request.acceptances
        if selected & verification_rules.pairs(a.coverage)
    )
    if event.occurred_at < last_acceptance:
        raise DomainError("INVALID_TEST_START", "实际开测不能早于对应实物接收。")
    return event


def stage_start(
    s,
    ctx,
    product_id,
    binding,
    resource_fact_id,
    expected_resource_fact_revision,
    *,
    expected_facts_revision,
    intent_digest,
    accepted_confirmation,
    verified_actual_start,
    _fingerprint_version=_FINGERPRINT_V1,
    _fingerprint_collector=None,
):
    """Internal host RunStart hook after one common T1; no second command/confirmation."""
    _fingerprint_sink(_fingerprint_version, _fingerprint_collector)
    if _fingerprint_version == _FINGERPRINT_V1 and _fingerprint_collector is not None:
        raise DomainError("RESOURCE_FINGERPRINT_MATERIAL_REQUIRED", "v1开测不保存v2资源材料。", 503)
    binding = TestPlanBinding.model_validate(binding)
    # Run identity/parent locks and all current guards precede any effect/replay.
    _scope(s, ctx, product_id, binding, write=True)
    event = _start_guard(s, ctx, product_id, binding, verified_actual_start)
    ports = _Ports(
        s,
        ctx,
        product_id,
        binding,
        resource_fact_id,
        expected_resource_fact_revision,
        intent=intent_digest,
        accepted=accepted_confirmation,
        verified_actual_start=event,
        fingerprint_version=_fingerprint_version,
        expected_facts_revision=expected_facts_revision,
    )
    bundle = ports.fresh()[0]
    if bundle.facts_revision != expected_facts_revision:
        raise DomainError("RESOURCE_FACTS_CHANGED", "来源、资格或占用在确认后变化，请重核。")
    handler = ResourceReservationHandler(ports, ports)
    try:
        preview = handler.preview(ports.latest[2], expected_revision=0)
        outcome = handler.stage_formal(ports.latest[2], preview, expected_revision=0)
    except ResourceError as exc:
        raise DomainError("TEST_RESOURCE_" + exc.code.upper(), str(exc)) from exc
    result = TestReservationResult(
        owner_run_id=binding.run_id,
        reservation_id=outcome.reservation.id,
        occupancy_ids=tuple(
            uuid5(binding.run_id, f"test-resource:{u.resource.id}") for u in bundle.uses
        ),
        sample_usage_ids=tuple(
            uuid5(binding.run_id, f"test-sample:{sid}")
            for sid in sorted({p.sample.id for p in binding.pairs}, key=lambda v: v.bytes)
        ),
        facts_revision=bundle.facts_revision,
        replayed=outcome.replayed,
    )
    if _fingerprint_version == _FINGERPRINT_V2:
        owner = _reservation(s, ctx, product_id, binding)
        if owner is None or owner.intent_digest != intent_digest:
            raise DomainError("RUN_RESERVATION_MISSING", "同事务保存v2预约不可核对。")
        version, record = _reservation_fingerprint(owner)
        if (
            version != _FINGERPRINT_V2
            or record != ports.latest_record
            or result.facts_revision != owner.facts_revision
            or owner.id != result.reservation_id
        ):
            raise DomainError("INTEGRITY_MISMATCH", "实际预约、返回结果与v2完整材料不一致。")
        _same_fingerprint_runtime(s, ports.latest_runtime)
        checked_at = now()
        if expired(ports.latest[0], checked_at) or not (
            binding.window.start <= checked_at < binding.window.finish
        ):
            raise DomainError("SOURCE_STALE", "v2资格或执行窗口在最终核对期间到期。")
        if _fingerprint_collector:
            raise TypeError("Fingerprint collector changed during owner IO")
        _fingerprint_collector.append(deepcopy(record))
    return result


def recheck_running(
    s,
    ctx,
    product_id,
    binding,
    resource_fact_id,
    expected_resource_fact_revision,
    *,
    intent_digest,
    at=None,
):
    """Current authorization and exact owning proofs; never reserve or consume again."""
    binding = TestPlanBinding.model_validate(binding)
    _scope(s, ctx, product_id, binding, write=True)
    saved = _reservation(s, ctx, product_id, binding)
    if saved is None or saved.intent_digest != intent_digest:
        raise DomainError("RUN_RESERVATION_MISSING", "本Run没有精确已提交的预约与消费证明。")
    fingerprint_version, _ = _reservation_fingerprint(saved)
    collector = [] if fingerprint_version == _FINGERPRINT_V2 else None
    runtime = _fingerprint_runtime(s) if collector is not None else None
    value, _, request, _, _, _, existing = _load(
        s,
        ctx,
        product_id,
        binding,
        resource_fact_id,
        expected_resource_fact_revision,
        at=at,
        write=True,
        own_intent=intent_digest,
        _fingerprint_version=fingerprint_version,
        _fingerprint_collector=collector,
    )
    if existing is None or existing.intent_digest != intent_digest:
        raise DomainError("RUN_RESERVATION_MISSING", "本Run没有精确已提交的预约与消费证明。")
    proof = Reservation.model_validate(existing.reservation)
    if proof.request != request or proof.state != "formal":
        raise DomainError("INTEGRITY_MISMATCH", "已提交Run的资源证明不匹配。")
    owned = list(
        s.scalars(
            select(ResourceOccupancy).where(
                ResourceOccupancy.tenant_id == ctx.tenant_id,
                ResourceOccupancy.owner_kind == "test_run",
                ResourceOccupancy.owner_execution_id == binding.run_id,
            )
        )
    )
    if len(owned) != len(value.uses) or {
        (
            o.resource_id,
            o.resource_revision,
            o.units,
            o.window_start,
            o.window_finish,
            o.intent_digest,
        )
        for o in owned
    } != {
        (
            u.resource.id,
            u.resource.revision,
            u.units,
            binding.window.start,
            binding.window.finish,
            intent_digest,
        )
        for u in value.uses
    }:
        raise DomainError("RUN_RESERVATION_MISSING", "当前资源占用不再等于原精确预约。")
    usages = list(
        s.scalars(
            select(SampleRunUsage).where(
                SampleRunUsage.tenant_id == ctx.tenant_id, SampleRunUsage.run_id == binding.run_id
            )
        )
    )
    expected = {p.sample.id for p in binding.pairs}
    if len(usages) != len(expected) or {u.sample_id for u in usages} != expected:
        raise DomainError("RUN_SAMPLE_USAGE_MISSING", "原Run实物使用证明缺失或重复。")
    for usage in usages:
        pairs = [p for p in binding.pairs if p.sample.id == usage.sample_id]
        sample = pairs[0].sample
        if (
            usage.intent_digest != intent_digest
            or usage.sample_revision != sample.revision
            or usage.actual_configuration_id != sample.actual_configuration.id
            or usage.actual_configuration_revision != sample.actual_configuration.revision
            or usage.destructive != any(p.destructive for p in pairs)
            or usage.window_start != binding.window.start
            or usage.window_finish != binding.window.finish
            or usage.source_basis["pairs"] != [p.model_dump(mode="json") for p in pairs]
            or usage.coverage
            != [{"sample_id": str(p.sample.id), "item_id": p.item_id} for p in pairs]
        ):
            raise DomainError("RUN_SAMPLE_USAGE_MISSING", "原Run的范围、破坏性与实物证明已漂移。")
        _sources(s, ctx, product_id, usage.required_source_read_set)
    if value.facts_revision != existing.facts_revision or value.report.status not in {
        "READY",
        "READY_WITH_CONDITIONS",
    }:
        raise DomainError("RESOURCE_FACTS_CHANGED", "旧Run当前资格、来源或外部占用须重核。")
    if runtime is not None:
        saved_version, record = _reservation_fingerprint(existing)
        if (
            saved_version != _FINGERPRINT_V2
            or len(collector) != 1
            or record != collector[0]
            or existing.intent_digest != intent_digest
        ):
            raise DomainError("INTEGRITY_MISMATCH", "原v2预约在当前执行重核期间改变。")
        _same_fingerprint_runtime(s, runtime)
        if expired(value, now()):
            raise DomainError("SOURCE_STALE", "v2资格在当前执行重核期间到期。")
    return value


def list_resources(s, ctx, product_id, *, request_id=None, build_id=None):
    from pdos_next.request_proof import snapshot_get

    _human(s, ctx, product_id)
    product = snapshot_get(s, Product, product_id, scope_id=product_id)
    if product is None or product.tenant_id != ctx.tenant_id:
        raise DomainError("FORBIDDEN_SCOPE", "测试资源不在当前型号范围。", 403)
    query = select(TestResourceFact).where(
        TestResourceFact.tenant_id == ctx.tenant_id, TestResourceFact.product_id == product_id
    )
    if request_id is not None:
        query = query.where(TestResourceFact.request_id == request_id)
    if build_id is not None:
        query = query.where(TestResourceFact.build_id == build_id)
    values = []
    for row in s.scalars(query.order_by(TestResourceFact.created_at, TestResourceFact.id)):
        if not _visible(row, ctx):
            continue
        pointer, _ = _current(s, ctx, product_id, row.run_id)
        status = "current"
        try:
            _sources(s, ctx, product_id, row.required_source_read_set, row.sources)
        except DomainError as exc:
            if exc.status == 403:
                continue
            status = "stale"
        values.append(
            _fact_view(row, pointer.epoch, current=pointer.fact_id == row.id, source_status=status)
        )
    return {"resource_facts": values}


_DIRECT_START_CONTRACT = "s0-direct-v1"


def _direct_start_inputs(s, ctx, pid, binding, fact_id, revision, *, write):
    """One direct Current and the physical capacity watermarks, never their ancestors."""
    from pdos_next.database import require_context
    from pdos_next.request_proof import request_proof

    if not isinstance(s, Session) or not s.is_active or not s.in_transaction():
        raise DomainError("INVALID_READ_CONTEXT", "开测材料须来自实际调用事务。")
    require_context(s, ctx)
    if write and pid not in request_proof(s).scope_locks:
        raise DomainError("FORBIDDEN_SCOPE", "实际开测须持有真实型号事务门栓。", 403)
    pointer, fact = _current(s, ctx, pid, binding.run_id, lock=write)
    if (
        fact is None
        or fact.id != fact_id
        or fact.revision != revision
        or fact.binding != binding.model_dump(mode="json")
        or fact.project_id != binding.project_id
        or fact.build_id != binding.build_id
        or fact.request_id != binding.request_id
        or not _visible(fact, ctx)
    ):
        raise DomainError("RESOURCE_FACTS_CHANGED", "直接测试资源Current或固定范围已变化。")
    data = TestResourceFactInput.model_validate(fact.data)
    if data.binding != binding or data.state != "active" or fact.state != "active":
        raise DomainError("RESOURCE_NOT_READY", "当前测试资源整版事实不可执行。")
    if fact.valid_from > binding.window.start or (
        fact.valid_until is not None and fact.valid_until < binding.window.finish
    ):
        raise DomainError("RESOURCE_NOT_READY", "资源事实未覆盖固定执行窗口。")
    assets = _assets(s, ctx, data, lock=write)
    sentinels = _sample_sentinels(s, ctx, pid, binding, create=False, lock=write)
    existing = _reservation(s, ctx, pid, binding)
    if existing is not None:
        raise DomainError("RUN_RESERVATION_CONFLICT", "该Run已有正式预约或历史使用。")
    watermark = {
        "resource": [
            str(ctx.tenant_id),
            str(pid),
            str(binding.project_id),
            str(binding.build_id),
            str(binding.run_id),
            str(binding.request_id),
            str(fact.id),
            fact.revision,
            pointer.epoch,
            fact.fact_sha256,
        ],
        "assets": [
            [str(a.id), a.revision, a.data_sha256, a.occupancy_epoch]
            for a in sorted(assets.values(), key=lambda a: a.id.bytes)
        ],
        "sample_usage": [
            [str(identity), sentinels[identity].epoch if identity in sentinels else 0]
            for identity in sorted({p.sample.id for p in binding.pairs}, key=lambda v: v.bytes)
        ],
    }
    return fact, data, assets, sentinels, watermark


def prepare_start_direct(
    s,
    ctx,
    pid,
    binding,
    fact_id,
    revision,
    *,
    authority,
    samples,
    source_basis,
    reads,
    verified_actual_start,
):
    """Prepare the resource rule once from signed summaries and direct capacity rows."""
    from pdos_next.domain.build_operational_facts.physical_summary import capacity_summary
    from pdos_next.engines.supply_cost.common import SnapshotRef

    binding = TestPlanBinding.model_validate(binding)
    write = not s.info.get("read_snapshot", False)
    fact, data, assets, sentinels, watermark = _direct_start_inputs(
        s, ctx, pid, binding, fact_id, revision, write=write
    )
    clock = now()
    snapshots, proofs, checks = [], [], []
    for resource in data.resources:
        # These named decisions were checked at import/signature. Start consumes
        # the current signed resource summary, never requalifies its old signer.
        facts = tuple(
            QualificationFact(
                kind=d.kind,
                purpose=d.purpose,
                operation_id=d.operation_id,
                status=d.status,
                source=_resource_source(fact, f"resource:{resource.resource.id}:" + d.kind),
                valid_from=d.valid_from,
                valid_until=d.valid_until,
                conditions=d.conditions,
                named_decision_id=d.named_decision_id,
                actor_id=d.actor_id,
            )
            for d in resource.facts
        )
        proofs.extend(
            {
                "resource": resource.resource.model_dump(mode="json"),
                "decision": d.model_dump(mode="json"),
                "proof": None,
            }
            for d in resource.facts
        )
        if not resource.external_occupancies_complete:
            checks.append(
                Check(
                    resource=resource.resource,
                    code="occupancy_scope_unknown",
                    status="UNKNOWN",
                    detail="External occupancy completeness unknown",
                )
            )
        snapshots.append(
            ResourceSnapshot(
                ref=resource.resource,
                scope=Scope(tenant_id=ctx.tenant_id, product_id=pid, project_id=binding.project_id),
                source=_resource_source(fact, f"resource:{resource.resource.id}"),
                purposes=resource.purposes,
                operation_ids=resource.operation_ids,
                lifecycle=resource.lifecycle,
                facts=facts,
                maintenance=tuple(
                    MaintenanceFact(
                        window=v.window,
                        status=v.status,
                        source=_resource_source(fact, f"maintenance:{resource.resource.id}:{i}"),
                    )
                    for i, v in enumerate(resource.maintenance)
                )
                if resource.maintenance is not None
                else None,
                calendar=resource.calendar,
                calendar_source=_resource_source(fact, f"calendar:{resource.resource.id}")
                if resource.calendar
                else None,
                capacity=resource.capacity,
                occupancy_revision=assets[resource.resource.id].occupancy_epoch,
            )
        )
    usages = [
        SimpleNamespace(
            sample_id=UUID(v["sample_id"]),
            destructive=v["destructive"],
            window_start=datetime.fromisoformat(v["window_start"]),
            window_finish=datetime.fromisoformat(v["window_finish"]),
            run_id=None,
            intent_digest=None,
            state="consumed" if v["destructive"] else "reserved",
        )
        for v in capacity_summary(
            s,
            ctx,
            pid,
            "sample",
            {p.sample.id for p in binding.pairs},
            own=binding.run_id,
            own_kind="test_run",
            watermark=tuple((k, row.epoch) for k, row in sorted(sentinels.items())),
        )
    ]
    usage_views, usage_checks = sample_usage_checks(binding, usages)
    checks.extend(usage_checks)
    provenance = {
        "refs": [
            SnapshotRef(
                source_id="artifact:" + v["id"],
                version=str(v["revision"]),
                sha256=v["hash"],
                captured_at=clock,
                state="current",
            ).model_dump(mode="json")
            for v in source_basis
        ],
        "security": [
            {
                "original_id": v["original"]["id"],
                "security_epoch": v["original"]["epoch"],
                "source_state": v["original"]["source_state"],
                "disposition": v["original"]["disposition"],
            }
            for v in source_basis
            if "original" in v
        ],
        "fixed_readset_security": [
            {
                "artifact_id": v["id"],
                "original_id": v["original"]["id"],
                "epoch": v["original"]["epoch"],
                "source_state": v["original"]["source_state"],
                "disposition": v["original"]["disposition"],
            }
            for v in source_basis
            if "original" in v
        ],
    }
    material = {
        "binding": binding,
        "fact": fact.fact_sha256,
        "epoch": watermark["resource"][-2],
        "issuer": {
            "key": fact.issuer_key,
            "scope": {
                "tenant_id": str(ctx.tenant_id),
                "product_id": str(pid),
                "project_id": str(binding.project_id),
            },
            "version": fact.issuer_version,
            "nature": fact.nature,
            "epoch": fact.issuer_epoch,
        },
        "issuer_epochs": {fact.issuer_key: fact.issuer_epoch},
        "assets": [
            {
                "id": a.id,
                "revision": a.revision,
                "sha256": a.data_sha256,
                "epoch": a.occupancy_epoch,
            }
            for a in assets.values()
        ],
        "sample_epochs": {
            str(identity): row.epoch if row else 1
            for identity, row in ((p.sample.id, sentinels.get(p.sample.id)) for p in binding.pairs)
        },
        "samples": {str(k): v["facts_revision"] for k, v in samples.items()},
        "authority": authority,
        "source_basis": provenance,
        "proofs": proofs,
        "checks": [v.model_dump(mode="json") for v in checks],
    }
    proof = _stored_fingerprint_v2(material)
    context = ResourceContext(
        scope=Scope(tenant_id=ctx.tenant_id, product_id=pid, project_id=binding.project_id),
        actor_id=ctx.requester_id,
        owner_run_id=binding.run_id,
        executor_id=binding.executor_id,
        now=clock,
        authorized=authority["authorized"],
        qualified=authority["qualified"],
        cancelled=False,
        sources_current=True,
        policy_registered=True,
        facts_revision=proof["facts_revision"],
        purpose=binding.purpose,
        operation_id=OPERATION,
        required_resources=data.required_uses,
        approved_conditions=data.approved_conditions,
        verified_actual_start=verified_actual_start.occurred_at
        if verified_actual_start is not None
        else None,
    )
    request = _request(binding, data)
    report = evaluate(
        context,
        request,
        tuple(snapshots),
        _occupancies(s, ctx, tuple(assets), data, product_id=pid, own_run_id=binding.run_id),
        tuple(checks),
    )
    if report.status not in {"READY", "READY_WITH_CONDITIONS"}:
        raise DomainError("RESOURCE_NOT_READY", "直接资源、容量或样件使用未就绪。")
    bundle = BoundTestResources(
        binding=binding,
        report=report,
        fact_ref=FactRef(
            id=fact.id,
            revision=fact.revision,
            epoch=watermark["resource"][-2],
            sha256=fact.fact_sha256,
            nature=fact.nature,
        ),
        facts_revision=proof["facts_revision"],
        resources=tuple(snapshots),
        uses=data.required_uses,
        required_source_read_set=reads,
        nature=fact.nature,
        sample_usage=usage_views,
    )
    return {
        "bundle": bundle.model_dump(mode="json"),
        "context": context.model_dump(mode="json"),
        "request": request.model_dump(mode="json"),
        "data": data.model_dump(mode="json"),
        "dependency_proof": proof,
        "watermark": watermark,
        "visibility": fact.visibility,
    }


class _PreparedDirectPorts(_Ports):
    """One already-confirmed direct owner phase; no historical callback or graph load."""

    direct_contract = True

    def fresh(self):
        from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow

        _same_uow(self.s, self.direct_uow, self.ctx, self.direct_caller)
        self.direct_close()
        return self.latest

    def _close(self):
        self.fresh()


def stage_start_prepared_direct(
    s,
    ctx,
    product_id,
    binding,
    resource_fact_id,
    expected_resource_fact_revision,
    *,
    prepared,
    intent_digest,
    accepted_confirmation,
    verified_actual_start,
    close_current,
):
    """Apply server preview material after direct version/epoch CAS, in caller UOW."""
    from pdos_next.domain.capa_effectiveness.fact_atom_storage import _uow
    from pdos_next.domain.resource_readiness.handlers import semantic_digest as resource_digest
    from pdos_next.schemas.resource_readiness.contracts import ReservationEvent

    if accepted_confirmation is not True or not callable(close_current):
        raise DomainError("CONFIRMATION_REQUIRED", "须消费真实共同开测确认。", 403)
    binding = TestPlanBinding.model_validate(binding)
    fact, data, assets, sentinels, watermark = _direct_start_inputs(
        s, ctx, product_id, binding, resource_fact_id, expected_resource_fact_revision, write=True
    )
    if watermark != prepared["watermark"] or data.model_dump(mode="json") != prepared["data"]:
        raise DomainError("RESOURCE_FACTS_CHANGED", "预览后的直接资源或容量水位已变化。")
    bundle = BoundTestResources.model_validate(prepared["bundle"])
    request = ReservationRequest.model_validate(prepared["request"])
    context = ResourceContext.model_validate(prepared["context"])
    proof = _verify_stored_fingerprint_v2(prepared["dependency_proof"])
    if (
        bundle.binding != binding
        or request != _request(binding, data)
        or proof["facts_revision"] != bundle.facts_revision
        or proof["material"]["binding"] != _fingerprint_json(binding)
        or bundle.report.status not in {"READY", "READY_WITH_CONDITIONS"}
        or ctx.requester_id != binding.executor_id
    ):
        raise DomainError("INTEGRITY_MISMATCH", "服务器预览资源材料未绑定本次完整Run。")
    event = EventTime.model_validate(verified_actual_start)
    close_current()
    sentinels = _sample_sentinels(s, ctx, product_id, binding, create=True, lock=True)
    if {str(k): row.epoch for k, row in sentinels.items()} != {
        identity: epoch or 1 for identity, epoch in watermark["sample_usage"]
    }:
        raise DomainError("RESOURCE_FACTS_CHANGED", "样件使用水位在创建门栓期间变化。")
    ports = _PreparedDirectPorts(
        s,
        ctx,
        product_id,
        binding,
        resource_fact_id,
        expected_resource_fact_revision,
        intent=intent_digest,
        accepted=True,
        verified_actual_start=event,
        fingerprint_version=_FINGERPRINT_V2,
    )
    ports.latest = bundle, context, request, data, assets, sentinels, None
    ports.latest_record = proof
    ports.direct_uow, ports.direct_caller = _uow(s), digest(vars(ctx))
    ports.direct_close = close_current
    record = Reservation(
        id=binding.run_id,
        revision=1,
        scope=context.scope,
        request=request,
        semantic_digest=resource_digest(request),
        state="formal",
        fixed_resources=bundle.resources,
        report=bundle.report,
        events=(ReservationEvent(kind="formal", at=now(), actor_id=ctx.requester_id),),
    )
    ports.stage(
        context, record, 0, tuple((v.ref.id, v.occupancy_revision) for v in bundle.resources)
    )
    close_current()
    return TestReservationResult(
        owner_run_id=binding.run_id,
        reservation_id=binding.run_id,
        occupancy_ids=tuple(
            uuid5(binding.run_id, f"test-resource:{u.resource.id}") for u in bundle.uses
        ),
        sample_usage_ids=tuple(
            uuid5(binding.run_id, f"test-sample:{sid}")
            for sid in sorted(sentinels, key=lambda v: v.bytes)
        ),
        facts_revision=bundle.facts_revision,
    )
