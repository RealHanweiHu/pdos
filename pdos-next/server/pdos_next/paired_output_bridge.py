"""Actual read-only paired Formal/Run owner.

Storage associations alone never issue a gate. This owner independently reads
current sources and original bytes, saved signers and retained execution. Every
attestation refreshes those owners in its own caller transaction. It neither
creates occupancy nor consumes confirmation, and never changes a result.
"""

from pdos_next.database import category_for_product


# The common registry must initialize before its domain model children.
# ruff: noqa: I001
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from weakref import WeakKeyDictionary, ref
from uuid import UUID

from pdos_next.service import Context, digest
from pdos_next import quality_result_bridge as result_owner
from pdos_next.domain.capa_effectiveness import anchor, anchor_storage, paired, paired_storage
from pdos_next.domain.capa_effectiveness.fact_sources_owner import read_source_closure
from pdos_next.domain.quality_execution import evidence
from pdos_next.domain.professional_authority.schemas import DefinitionReference
from pdos_next.domain.test_resources import service as resources
from pdos_next.domain.test_resources.retained import inspect_retained_execution
from pdos_next.domain.test_resources.schemas import TestPlanBinding
from pdos_next.domain.verification_front import service as front
from pdos_next.domain.verification_front.models import FormalVerificationRequest
from pdos_next.domain.verification_handoff import service as physical
from pdos_next.domain.verification_launch import service as launch
from pdos_next.domain.verification_launch.models import (
    VerificationLaunchFact,
    VerificationRunVersion,
)
from pdos_next.domain.verification_results import service as results
from pdos_next.domain.verification_results.models import TestResultActionFact, TestResultProjection
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Principal, Product
from sqlalchemy import select


def _now():
    return datetime.now(UTC)


def _require(value, code="SOURCE_STALE", status=409):
    if not value:
        raise DomainError(code, "实际配对输出的完整当前证明不能核对。", status)


def _wire(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, (UUID, datetime)):
        return value.isoformat() if isinstance(value, datetime) else str(value)
    if isinstance(value, dict):
        return {str(k): _wire(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_wire(v) for v in value]
    return deepcopy(value)


def _one(s, ctx, pid, model, identity):
    rows = list(
        s.scalars(
            select(model)
            .where(model.tenant_id == ctx.tenant_id, model.product_id == pid, model.id == identity)
            .limit(2)
            .execution_options(populate_existing=True, autoflush=False)
        )
    )
    _require(len(rows) == 1, "PAIR_FIXED_ROW_MISSING", 503)
    row = rows[0]
    _require(
        row.visibility in {"private", "category", "audience"}
        and (row.visibility != "private" or row.owner_id == ctx.requester_id),
        "FORBIDDEN_SCOPE",
        403,
    )
    return row


def _row_material(row):
    # All actual immutable columns, including sparse source_basis and authority.
    return {
        column.key: _wire(deepcopy(getattr(row, column.key)))
        for column in row.__table__.columns
        if column.key != "audience_dependencies"
    }


def _rows(s, ctx, pid, read):
    material = read.material
    selected = []
    for name in ("origin_request", "request_before", "request_after"):
        selected.append((FormalVerificationRequest, getattr(material, name).ref))
    for name in ("run_before", "run_after", "projection_run"):
        typed = getattr(material, name)
        if typed is not None:
            selected.append((VerificationRunVersion, typed.ref))
    selected.append(
        (
            TestResultActionFact if material.fact.kind == "result" else VerificationLaunchFact,
            material.fact.ref,
        )
    )
    if material.projection is not None:
        selected.append((TestResultProjection, material.projection.ref))
    rows = {}
    for model, fixed in selected:
        key = (model.__tablename__, fixed.id)
        if key in rows:
            continue
        row = _one(s, ctx, pid, model, fixed.id)
        _require(row.revision == fixed.revision)
        _require(
            row.project_id == read.binding.scope.project_id
            and row.build_id == read.binding.build.id
            and row.request_id == read.binding.request_id,
            "PAIR_SCOPE_MISMATCH",
            403,
        )
        if hasattr(row, "run_id"):
            _require(row.run_id == read.binding.run_id, "PAIR_SCOPE_MISMATCH", 403)
        rows[key] = row
    return rows


def _stored_digest(rows):
    return digest(
        {f"{table}:{identity}": _row_material(row) for (table, identity), row in rows.items()}
    )


def _authority(s, ctx, pid, rows, read):
    values, reads = {}, []
    for key, row in rows.items():
        saved = getattr(row, "authority_snapshot", None)
        if isinstance(row, TestResultProjection):
            continue  # Projection has no professional decision of its own.
        _require(saved is not None, "PAIR_PROFESSIONAL_OWNER_REQUIRED", 503)
        _require(isinstance(saved, dict) and saved.get("operation") == row.operation)
        _require(
            saved.get("scope") == read.binding.scope.model_dump(mode="json")
            and saved.get("purpose") == read.binding.purpose
            and saved.get("authorized") is True
            and saved.get("qualified") is True,
            "PAIR_PROFESSIONAL_BINDING_MISMATCH",
        )
        actor = (
            row.writer_id
            if isinstance(row, VerificationRunVersion)
            else row.actor_id
            if isinstance(row, TestResultActionFact)
            else row.owner_id
            if isinstance(row, VerificationLaunchFact)
            else UUID(saved["subject_id"])
        )
        _require(saved.get("subject_id") == str(actor), "PAIR_PROFESSIONAL_BINDING_MISMATCH")
        # Historical qualification uses its actual saved period, while the real
        # consumer source/Project ACL is independently guarded by this owner.
        proof = front._recheck(s, ctx, pid, row.project_id, saved, at=_now())
        _require(proof.get("current") is True, "PAIR_PROFESSIONAL_STALE")
        assessment = proof["assessment"]
        values[f"{key[0]}:{key[1]}"] = deepcopy(proof)
        reads.extend(assessment["required_source_read_set"])
    _require(bool(values), "PAIR_PROFESSIONAL_OWNER_REQUIRED", 503)
    return values, reads


def _refs_reads(rows, *extra_reads):
    raw_refs = physical._merge_refs(*(row.sources for row in rows.values()))
    reads = anchor.canonical_reads(
        [v for row in rows.values() for v in row.required_source_read_set]
        + [v for group in extra_reads for v in group]
    )
    return raw_refs, reads


def _fixed_source_basis(s, ctx, pid, rows):
    direct_runs = {
        row.id
        for row in rows.values()
        if isinstance(row, VerificationRunVersion)
        and row.operation == "test.run.start"
        and row.input_snapshot.get("execution_proof_contract") == "s0-direct-v1"
    }
    for row in rows.values():
        if launch._read_evidence(s, ctx, pid, row) != "current":
            raise DomainError("SOURCE_STALE", "配对固定版本的来源当前不可用。")
        if hasattr(row, "source_basis"):
            direct = (isinstance(row, VerificationRunVersion) and row.id in direct_runs) or (
                isinstance(row, VerificationLaunchFact)
                and row.operation == "test.run.start"
                and row.run_version_id in direct_runs
            )
            if direct:
                from pdos_next.source_current import direct_source_basis

                references = tuple(DefinitionReference.model_validate(v) for v in row.sources)
                sources = evidence.refs_from_exact(s, ctx, pid, references)
                actual, private = direct_source_basis(
                    s, ctx, pid, sources, row.required_source_read_set
                )
            else:
                actual, private = physical._basis(
                    s, ctx, pid, row.required_source_read_set, row.sources
                )
            _require(actual == row.source_basis and (row.visibility != "category" or not private))


def _source_read(s, ctx, pid, read, rows, *extra_reads):
    refs, reads = _refs_reads(rows, *extra_reads)
    references = tuple(DefinitionReference.model_validate(_wire(v)) for v in refs)
    sources = evidence.refs_from_exact(s, ctx, pid, references)
    # These are real full-line locations derived from fixed DefinitionReference,
    # never measurement original-line guesses from derived Artifact text.
    value = read_source_closure(
        s,
        ctx,
        pid,
        scope=read.binding.scope,
        owner_id=read.material.request_after.owner_id,
        visibility="private"
        if any(row.visibility == "private" for row in rows.values())
        else "audience"
        if any(row.visibility == "audience" for row in rows.values())
        else "category",
        sources=sources,
        reads=reads,
    )
    _require(not value.missing, "PAIR_SOURCE_OWNER_REQUIRED", 503)
    _fixed_source_basis(s, ctx, pid, rows)
    return value


def _execution(s, ctx, pid, read, structure, rows):
    row = rows[(VerificationRunVersion.__tablename__, read.material.run_after.ref.id)]
    if structure.meaning == "performed":
        value = inspect_retained_execution(s, ctx, pid, row, write=False)
        _require(value.get("current") is True, "PAIR_RETAINED_EXECUTION_STALE")
        return value, None
    binding = TestPlanBinding.model_validate(row.input_snapshot["plan_binding"])
    value = resources.load_bundle(
        s,
        ctx,
        pid,
        binding,
        read.material.run_after.plan.resource_fact_id,
        read.material.run_after.plan.expected_resource_fact_revision,
        at=_now(),
        write=False,
    )
    _require(
        value.binding == binding and value.report.status in {"READY", "READY_WITH_CONDITIONS"},
        "PAIR_PLAN_RESOURCES_NOT_READY",
    )
    return None, value


def _numerical(s, ctx, pid, read, structure):
    if structure.fact_kind != "result":
        return None
    run = read.material.run_after.snapshot
    _require(bool(run.measurements), "PAIR_MEASUREMENT_OWNER_REQUIRED", 503)
    # The explicit new Run/version owns this selection. The reused bridge reads
    # ALL its measurements and real report bytes, not an old CAPA FailureRef.
    value = result_owner.fixed_failure_result(
        s,
        ctx,
        pid,
        run_id=run.id,
        run_revision=run.revision,
        measurement_id=run.measurements[0].id,
        write=False,
    )
    projection = read.material.projection
    _require(
        value.current is True
        and value.verified.run == run
        and value.run_version_id == read.material.run_after.ref.id
        and value.run_revision == run.revision
        and (value.projection_id, value.projection_revision)
        == (projection.ref.id, projection.ref.revision)
        and (value.basis_sha256, value.rules_version, value.rules_sha256)
        == (projection.basis_sha256, projection.rules_version, projection.rules_sha256),
        "PAIR_NUMERICAL_BASIS_MISMATCH",
    )
    return value


def _numerical_material(value):
    if value is None:
        return None
    raw = value.model_dump(mode="json")
    # Exactly these display fields are dynamic; fixed consumption, issuer,
    # occupancy/usage and source safety all remain part of the proof.
    raw["retained"].pop("checked_at", None)
    raw["retained"].pop("execution_window_elapsed", None)
    return raw


def _caller(s, ctx, pid):
    paired_storage._acl(s, ctx, pid, write=False)
    person = paired_storage._query(
        s,
        select(Principal).where(
            Principal.tenant_id == ctx.tenant_id, Principal.id == ctx.requester_id
        ),
    )
    grant = paired_storage._query(
        s,
        select(Grant).where(
            Grant.tenant_id == ctx.tenant_id,
            Grant.category_id == category_for_product(pid),
            Grant.principal_id == ctx.requester_id,
        ),
    )
    product = paired_storage._query(
        s, select(Product).where(Product.tenant_id == ctx.tenant_id, Product.id == pid)
    )
    _require(
        person is not None and grant is not None and product is not None, "FORBIDDEN_SCOPE", 403
    )
    _require(
        ctx.actor_id == ctx.requester_id
        and ctx.run_id is None
        and person.kind == "human"
        and person.active is True,
        "FORBIDDEN_SCOPE",
        403,
    )
    return {
        "product_revision": product.revision,
        "principal_id": person.id,
        "principal_epoch": person.access_epoch,
        "grant_id": grant.id,
        "grant_epoch": grant.access_epoch,
        "can_write": grant.can_write,
        "expires_at": grant.expires_at,
    }


@dataclass(frozen=True)
class _ReadBinding:
    session: object
    uow: tuple
    caller_sha256: str
    runtime_sha256: str
    material_sha256: str
    write: bool


class LivePairedOwner:
    """Server-startup owner; no externally supplied positive proof callbacks.

    Identity registration is only to reject forged/cloned DTOs. It never caches
    a positive source, qualification or execution result across attest phases.
    """

    def __init__(self):
        self._storage = paired_storage.StoragePairReader()
        self._reads = WeakKeyDictionary()

    def _register(self, s, ctx, read, write):
        _require(isinstance(ctx, Context), "CALLER_UOW_REQUIRED", 503)
        state = _ReadBinding(
            s,
            paired_storage._uow(s),
            digest(vars(ctx)),
            result_owner._runtime_stamp(s),
            digest({"binding": _wire(read.binding), "material": _wire(read.material)}),
            write,
        )
        # Per-Session weak ownership; per-read identity avoids Pydantic/dict hash.
        registry = self._reads.setdefault(s, {})
        identity = id(read)
        registry[identity] = (ref(read, lambda _: registry.pop(identity, None)), state)
        return read

    def _bound(self, s, ctx, read, write):
        item = self._reads.get(s, {}).get(id(read))
        _require(item is not None and item[0]() is read, "PAIR_HOST_READ_UNBOUND", 503)
        state = item[1]
        paired_storage._guard_uow(s, state.uow, ctx, state.caller_sha256)
        _require(
            state.session is s and type(write) is bool and state.write == write,
            "PAIR_HOST_READ_UNBOUND",
            503,
        )
        _require(
            state.runtime_sha256 == result_owner._runtime_stamp(s)
            and state.material_sha256
            == digest({"binding": _wire(read.binding), "material": _wire(read.material)})
        )
        return state

    def read(self, s, ctx, product_id, output_ref, *, at, write=False):
        read = self._storage.read(s, ctx, product_id, output_ref, at=at, write=write)
        if read is not None:
            with s.no_autoflush:
                anchor_storage._project(s, ctx, product_id, read.binding.scope.project_id)
        return self._register(s, ctx, read, write) if read is not None else None

    def refresh(self, s, ctx, product_id, previous, *, at, write=False):
        self._bound(s, ctx, previous, write)
        value = self._storage.refresh(s, ctx, product_id, previous, at=at, write=write)
        if value is not None:
            with s.no_autoflush:
                anchor_storage._project(s, ctx, product_id, value.binding.scope.project_id)
        return self._register(s, ctx, value, write) if value is not None else None

    def attest(self, s, ctx, product_id, read, structure, *, at, write=False):
        state = self._bound(s, ctx, read, write)
        _require(
            read.binding.scope.tenant_id == ctx.tenant_id
            and read.binding.scope.product_id == product_id
            and read.binding.caller_id == ctx.requester_id,
            "PAIR_SCOPE_MISMATCH",
            403,
        )
        actual = paired.verify_paired_material(read.binding, read.material, at=at)
        _require(
            actual.proof is not None and actual.proof == structure, "PAIR_STRUCTURE_UNBOUND", 503
        )
        with s.no_autoflush:
            project = anchor_storage._project(s, ctx, product_id, read.binding.scope.project_id)
            caller = _caller(s, ctx, product_id)
            rows = _rows(s, ctx, product_id, read)
            stored = _stored_digest(rows)
            authorities, authority_reads = _authority(s, ctx, product_id, rows, read)
            retained, plan = _execution(s, ctx, product_id, read, structure, rows)
            numerical = _numerical(s, ctx, product_id, read, structure)
            extra = [authority_reads]
            if retained is not None:
                extra.append(retained["required_source_read_set"])
            if plan is not None:
                extra.append(plan.required_source_read_set)
            if numerical is not None:
                extra.append(numerical.required_source_read_set)
            sources = _source_read(s, ctx, product_id, read, rows, *extra)
            # ALL byte I/O has finished. Independently refresh original numerical
            # owner, retained ledger, saved signers, source basis and real Current.
            if numerical is not None:
                fresh = result_owner.recheck_fixed_failure_result(s, ctx, product_id, numerical)
                _require(_numerical_material(fresh) == _numerical_material(numerical))
            fresh_retained, fresh_plan = _execution(s, ctx, product_id, read, structure, rows)
            if retained is not None:
                _require(
                    results._retained_stamp(fresh_retained) == results._retained_stamp(retained)
                )
            if plan is not None:
                _require(fresh_plan.facts_revision == plan.facts_revision)
            fresh_authorities, fresh_reads = _authority(s, ctx, product_id, rows, read)
            _require(fresh_authorities == authorities and fresh_reads == authority_reads)
            fresh_rows = _rows(s, ctx, product_id, read)
            _require(_stored_digest(fresh_rows) == stored)
            _fixed_source_basis(s, ctx, product_id, fresh_rows)
            basis, private = evidence.source_basis(
                s, ctx, product_id, [_wire(v) for v in sources.required_source_read_set]
            )
            _require(
                basis == sources.source_basis
                and (
                    sources.sources is not None
                    and (
                        not private
                        or any(row.visibility == "private" for row in fresh_rows.values())
                    )
                )
            )
            current = self._storage.refresh(s, ctx, product_id, read, at=_now(), write=write)
            _require(current is not None and current == read)
            _require(
                anchor_storage._project(s, ctx, product_id, read.binding.scope.project_id)
                == project
            )
            final_caller = _caller(s, ctx, product_id)
            _require(final_caller == caller)
            self._bound(s, ctx, read, write)
            # Last IO is before this true clock. Never reuse the input `at` as a
            # current permission/expiry clock, including the final caller reads.
            checked = _now()
            bounds = [
                sources.valid_until,
                *sources.time_constraints,
                caller["expires_at"],
                *(plan.expiry_boundaries if plan is not None else ()),
            ]
            if plan is not None and plan.valid_until is not None:
                bounds.append(plan.valid_until)
            time_constraints = tuple(value for value in bounds if value is not None)
            _require(
                all(v.tzinfo is not None and checked < v for v in time_constraints)
                and (plan is None or not resources.expired(plan, checked)),
                "PAIR_LIVE_PROOF_EXPIRED",
            )
            paired_storage._guard_uow(s, state.uow, ctx, state.caller_sha256)
            _require(result_owner._runtime_stamp(s) == state.runtime_sha256)
            materials = {
                "acl": {"caller": caller, "project": _wire(project)},
                "sources": {
                    "basis": sources.source_basis,
                    "reads": _wire(sources.required_source_read_set),
                },
                "professional": {"assessments": authorities},
                "original_bytes": {
                    "sources": sources.byte_material,
                    "measurement": _numerical_material(numerical),
                },
                "semantic": {"common": _wire(read.material.common_material), "rows": stored},
                "runtime": state.runtime_sha256,
            }
            if retained is not None:
                materials["retained"] = results._retained_stamp(retained)
            if numerical is not None:
                materials["numerical_rules"] = _numerical_material(numerical)
            return paired.HostGateProof(
                self,
                s,
                state.uow[0],
                s.get_nested_transaction(),
                ctx.requester_id,
                read.binding.scope,
                structure.material_sha256,
                tuple(
                    paired.GateStamp(kind, digest(_wire(value)))
                    for kind, value in materials.items()
                ),
                checked,
                None,
                time_constraints=time_constraints,
                needs_review=any(
                    value.get("needs_review") is True for value in authorities.values()
                ),
            )
