"""Actual source/byte closure for CAPA facts; no professional gate is issued.

Source selections are independently checked under the actual caller. Stored
source declarations and booleans never replace current ACL/security or bytes.
Commands hold source locks in their UOW; GET uses its actual read snapshot.
"""

from pdos_next.database import category_for_product


# Initialize the common registry before domain children.
# ruff: noqa: I001
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID


from pdos_next.service import Context, digest, source_for
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Principal
from pdos_next.original_security import require_safe
from pdos_next.originals import object_reference, read_registered_bytes, require_original
from pdos_next.object_storage import StorageFailure
from pdos_next.domain.quality_execution import evidence, policy
from pdos_next.domain.professional_authority import service as professional
from pdos_next.domain.professional_authority.models import ProfessionalFact
from pdos_next.domain.professional_authority.schemas import DefinitionReference
from pdos_next.schemas.verification.contracts import SourceRef
from . import anchor as a
from . import anchor_storage
from . import fact_atom_storage as guards
from .candidate_prepare import _runtime
from .facts import FactMaterial
from .fact_registry_storage import read_stored_fact

MAX_BYTES = 8_388_608


@dataclass(frozen=True)
class FactSourcesRead:
    scope: a.Scope
    sources: tuple[SourceRef, ...]
    required_source_read_set: tuple[a.SourceRead, ...]
    source_basis: list  # Sparse real source_basis JSON, never typed-null padding.
    byte_material: tuple[dict, ...]
    authority_material: dict
    policy_material: dict
    material_sha256: str
    checked_at: datetime
    valid_until: datetime | None
    missing: tuple[str, ...]
    current_evidence_authorized: bool = False
    same_uow_consumption_attested: bool = False
    time_constraints: tuple[datetime, ...] = ()


def _require(value, code="SOURCE_STALE", status=409):
    if not value:
        raise DomainError(code, "完整来源、原件或当前调用范围需重新核对。", status)


def _wire(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, (UUID, datetime)):
        return value.isoformat() if isinstance(value, datetime) else str(value)
    if isinstance(value, dict):
        return {str(k): _wire(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_wire(v) for v in value]
    return deepcopy(value)


def _collect(value, sources, reads):
    value = _wire(value)
    if isinstance(value, dict):
        if {"id", "revision", "kind", "position"} <= value.keys():
            sources.append(SourceRef.model_validate(value))
        elif set(value) == {"artifact_id", "expected_revision"}:
            reads.append(a.SourceRead.model_validate(value))
        for item in value.values():
            _collect(item, sources, reads)
    elif isinstance(value, list):
        for item in value:
            _collect(item, sources, reads)


def _phase(s, ctx, uow, caller, runtime, store):
    guards._same_uow(s, uow, ctx, caller)
    _require(_runtime(s) == runtime and getattr(s.get_bind(), "_pdos_results_store", None) is store)


def _row(s, ctx, pid, read):
    # Existing locks/security gate cannot be replaced with a snapshot claim.
    row = source_for(s, ctx, pid, read.artifact_id, read.expected_revision)
    _require(
        row.tenant_id == ctx.tenant_id
        and row.product_id in (None, pid)
        and row.content_hash == digest(row.content),
        "INTEGRITY_MISMATCH",
    )
    return row


def _deadline(s, ctx, pid, extra):
    person = guards._one(
        s, Principal, Principal.tenant_id == ctx.tenant_id, Principal.id == ctx.actor_id
    )
    grant = guards._one(
        s,
        Grant,
        Grant.tenant_id == ctx.tenant_id,
        Grant.category_id == category_for_product(pid),
        Grant.principal_id == ctx.actor_id,
    )
    at = datetime.now(UTC)
    if (
        person.kind != "human"
        or person.active is not True
        or (grant.expires_at is not None and grant.expires_at <= at)
    ):
        raise DomainError("FORBIDDEN_SCOPE", "末端真实本人读取期限已失效。", 403)
    bounds = [value for value in (grant.expires_at, *extra) if value is not None]
    _require(
        all(
            isinstance(v, datetime) and v.tzinfo is not None and v.utcoffset() is not None
            for v in bounds
        ),
        "INVALID_TIME",
    )
    _require(all(v > at for v in bounds), "SOURCE_STALE")
    return at, tuple(bounds)


def read_source_closure(
    s,
    ctx: Context,
    product_id: UUID,
    *,
    scope: a.Scope,
    owner_id: UUID,
    visibility: str,
    sources,
    reads,
    expected_basis=(),
    boundaries=(),
) -> FactSourcesRead:
    """Actual source subset owner. Public host must derive the FULL required set.

    Native text is never an instrument report. Uploaded files require the real
    configured store; bytes are consumed internally and never returned.
    Non-artifact domain refs remain explicit missing until their owner is wired.
    """
    _require(isinstance(ctx, Context) and isinstance(product_id, UUID), "INTEGRATION_REQUIRED", 503)
    _require(
        scope.tenant_id == ctx.tenant_id
        and scope.product_id == product_id
        and visibility in ("category", "private", "audience"),
        "FORBIDDEN_SCOPE",
        403,
    )
    if visibility == "private" and owner_id != ctx.requester_id:
        raise DomainError("FORBIDDEN_SCOPE", "不能借原作者读取私有来源闭包。", 403)
    uow, caller = guards._uow(s), digest(vars(ctx))
    runtime, store = _runtime(s), getattr(s.get_bind(), "_pdos_results_store", None)
    sources, reads = a.canonical_sources(sources), a.canonical_reads(reads)
    wanted = {v.artifact_id: v.expected_revision for v in reads}
    _require(
        all(v.kind != "artifact" or wanted.get(v.id) == v.revision for v in sources),
        "MISSING_REQUIRED_EVIDENCE",
    )
    missing, bytes_material = set(), []
    with s.no_autoflush:
        guards._acl(s, ctx, product_id)
        project = anchor_storage._project(s, ctx, product_id, scope.project_id)
        initial, private = evidence.source_basis(
            s, ctx, product_id, [v.model_dump(mode="json") for v in reads]
        )
        initial = deepcopy(initial)
        basis = a.canonical_basis(initial, reads)
        actual = {v.id: v for v in basis}
        _require(all(actual.get(v.id) == v for v in expected_basis), "SOURCE_STALE")
        if visibility == "category" and private:
            raise DomainError("FORBIDDEN_SCOPE", "私有来源不能扩大事实受众。", 403)
        for ref in sources:
            if ref.kind == "artifact":
                evidence.check_source(s, ctx, product_id, ref)
            else:
                missing.add("DOMAIN_SOURCE_OWNER_REQUIRED")
        for read in reads:
            source = _row(s, ctx, product_id, read)
            if source.original_id is None:
                size = len(source.content.encode("utf-8"))
                _require(size <= MAX_BYTES, "SOURCE_LIMIT_EXCEEDED")
                bytes_material.append(
                    {
                        "artifact_id": str(source.id),
                        "revision": source.revision,
                        "source_origin": "registered_native_text",
                        "size": size,
                        "content_hash": source.content_hash,
                    }
                )
                continue
            _require(store is not None, "ORIGINAL_BYTES_OWNER_REQUIRED", 503)
            source_lock = not getattr(s, "info", {}).get("read_snapshot", False)
            original = require_original(
                s,
                ctx,
                product_id,
                source.original_id,
                lock=source_lock,
            )
            epoch, _ = require_safe(s, ctx, original, lock=source_lock)
            reference = object_reference(original)
            _require(
                original.status == "parsed" and reference.size_bytes <= MAX_BYTES,
                "ORIGINAL_BYTES_OWNER_REQUIRED",
                503,
            )
            if visibility == "category" and original.visibility == "private":
                raise DomainError("FORBIDDEN_SCOPE", "私有原件不能扩大事实受众。", 403)
            try:
                content = read_registered_bytes(
                    store, reference, ctx.tenant_id, original.product_id, original.category_id
                )
            except StorageFailure:
                raise DomainError(
                    "ORIGINAL_BYTES_OWNER_REQUIRED", "原件有界字节读取失败。", 503
                ) from None
            _require(
                isinstance(content, bytes)
                and len(content) == reference.size_bytes
                and sha256(content).hexdigest() == reference.content_sha256,
                "INTEGRITY_MISMATCH",
            )
            latest, _ = require_safe(s, ctx, original, lock=source_lock)
            _require(latest == epoch)
            _phase(s, ctx, uow, caller, runtime, store)
            bytes_material.append(
                {
                    "artifact_id": str(source.id),
                    "revision": source.revision,
                    "source_origin": "uploaded_original",
                    "original_id": str(original.id),
                    "sha256": reference.content_sha256,
                    "size": reference.size_bytes,
                    "security_epoch": epoch,
                }
            )
            # Complete actual bytes proof is not a report-value/applicability gate.
        final, private = evidence.source_basis(
            s, ctx, product_id, [v.model_dump(mode="json") for v in reads]
        )
        _require(final == initial and (visibility != "category" or not private))
        _require(anchor_storage._project(s, ctx, product_id, scope.project_id) == project)
        # Final source pass catches a later owner callback changing an earlier source.
        final, private = evidence.source_basis(
            s, ctx, product_id, [v.model_dump(mode="json") for v in reads]
        )
        _require(final == initial and (visibility != "category" or not private))
        _phase(s, ctx, uow, caller, runtime, store)
        material = {
            "scope": scope.model_dump(mode="json"),
            "owner_id": str(owner_id),
            "visibility": visibility,
            "sources": _wire(sources),
            "reads": _wire(reads),
            "source_basis": initial,
            "bytes": bytes_material,
            "project": project.model_dump(mode="json"),
            "runtime": runtime,
        }
        material_hash = digest(material)
        checked, time_constraints = _deadline(s, ctx, product_id, boundaries)
        _phase(s, ctx, uow, caller, runtime, store)
    return FactSourcesRead(
        scope,
        sources,
        reads,
        initial,
        tuple(bytes_material),
        {},
        {},
        material_hash,
        checked,
        None,
        tuple(sorted(missing)),
        time_constraints=time_constraints,
    )


def _current_context(s, ctx, pid, scope, purpose, nature, operations):
    authorities = {}
    policy_value = deepcopy(policy.assess(s, ctx, pid, scope.project_id, purpose))
    _require(policy_value.get("nature") == nature, "SOURCE_FACT_NATURE_MISMATCH")
    _require(
        policy.policy_time_current(policy_value, datetime.now(UTC)),
        "CURRENT_POLICY_OWNER_REQUIRED",
        503,
    )
    for operation in operations:
        at = datetime.now(UTC)
        value = deepcopy(professional.assess(s, ctx, pid, scope.project_id, operation, purpose, at))
        _require(
            value.get("scope") == scope.model_dump(mode="json")
            and value.get("subject_id") == str(ctx.actor_id)
            and value.get("operation") == operation
            and value.get("purpose") == purpose,
            "CURRENT_AUTHORITY_OWNER_REQUIRED",
            503,
        )
        _require(bool(value.get("facts_revision")), "CURRENT_AUTHORITY_OWNER_REQUIRED", 503)
        # A failed assessor clears the reads; it cannot prove complete source closure.
        _require(
            value.get("authorized") is True and value.get("qualified") is True,
            "CURRENT_AUTHORITY_OWNER_REQUIRED",
            503,
        )
        refs = value.get("fact_refs")
        _require(
            isinstance(refs, list) and bool(refs),
            "CURRENT_AUTHORITY_OWNER_REQUIRED",
            503,
        )
        fixed = []
        for ref in refs:
            row = guards._one(
                s,
                ProfessionalFact,
                ProfessionalFact.tenant_id == ctx.tenant_id,
                ProfessionalFact.product_id == pid,
                ProfessionalFact.project_id == scope.project_id,
                ProfessionalFact.subject_id == ctx.actor_id,
                ProfessionalFact.id == UUID(ref["id"]),
                ProfessionalFact.revision == ref["revision"],
            )
            fixed.append(
                {
                    "sources": [
                        v.model_dump(mode="json")
                        for v in evidence.refs_from_exact(
                            s,
                            ctx,
                            pid,
                            tuple(DefinitionReference.model_validate(v) for v in row.sources),
                        )
                    ],
                    "reads": deepcopy(row.required_source_read_set),
                }
            )
        _require(
            professional.authority_time_current(value, datetime.now(UTC)),
            "QUALIFICATION_REQUIRED",
            403,
        )
        # The full real assessment is compared by hash; the raw source reader
        # deliberately exports no qualification/authorization verdict. Root must
        # invoke the professional owner independently to attest that gate.
        visible = {k: deepcopy(v) for k, v in value.items() if k not in {"authorized", "qualified"}}
        authorities[operation] = {
            "assessment_material": visible,
            "assessment_sha256": digest(value),
            "source_material": fixed,
        }
    return authorities, policy_value, ()


def read_fact_sources(
    s,
    ctx: Context,
    product_id: UUID,
    material: FactMaterial,
    *,
    operations: tuple[str, ...],
    candidate_owner=None,
) -> FactSourcesRead:
    """Full fact source union plus current authority/policy declarations.

    This reads actual assessments but does not export qualification booleans or
    issue a HostFactProof. An unavailable assessor remains missing/503.
    """
    _require(
        type(material) is FactMaterial
        and bool(operations)
        and len(set(operations)) == len(operations),
        "SOURCE_FACT_MATERIAL_REQUIRED",
        503,
    )
    origin = material.anchor.origin
    uow, caller, stamp = guards._uow(s), digest(vars(ctx)), _runtime(s)
    with s.no_autoflush:
        guards._acl(s, ctx, product_id)
        descriptor = anchor_storage.read_origin_descriptor(
            s, ctx, product_id, origin.issue_id, origin.ref
        )
        _require(descriptor.origin == origin)
        authority, policy_value, boundaries = _current_context(
            s, ctx, product_id, origin.scope, origin.purpose, origin.nature, operations
        )
        # Client material is only a selector; every saved fact is reread by its
        # actual raw registry owner. Review additionally needs its real candidate
        # owner, never a fabricated full-SHA or an authorized=True DTO.
        registered = []
        for kind, selected in (
            ("rule", material.rule),
            *(("observation", v) for v in material.observations),
            ("review", material.review),
        ):
            stored = read_stored_fact(
                s, ctx, product_id, kind, selected.ref, candidate_owner=candidate_owner
            )
            _require(stored.fact == selected, "SOURCE_FACT_STORAGE_MISMATCH")
            registered.append((kind, selected.ref, stored))
        sources, reads = [], []
        _collect(material, sources, reads)
        _collect(authority, sources, reads)
        _collect(policy_value, sources, reads)
        closure = read_source_closure(
            s,
            ctx,
            product_id,
            scope=origin.scope,
            owner_id=origin.owner_id,
            visibility=origin.visibility,
            sources=sources,
            reads=reads,
            expected_basis=material.anchor.origin_source_basis,
            boundaries=boundaries,
        )
        # Independent late registered-owner pass after every original byte IO.
        for kind, ref, old in registered:
            actual = read_stored_fact(
                s, ctx, product_id, kind, ref, candidate_owner=candidate_owner
            )
            _require(
                actual.fact == old.fact
                and actual.group_sha256 == old.group_sha256
                and actual.registry == old.registry
                and actual.dependencies == old.dependencies
                and actual.candidate == old.candidate,
                "SOURCE_FACT_STORAGE_CHANGED",
            )
        # Independent late complete assessor pass, not a cached positive DTO.
        refreshed, refreshed_policy, late_bounds = _current_context(
            s, ctx, product_id, origin.scope, origin.purpose, origin.nature, operations
        )
        _require(refreshed == authority and refreshed_policy == policy_value)
        final = read_source_closure(
            s,
            ctx,
            product_id,
            scope=origin.scope,
            owner_id=origin.owner_id,
            visibility=origin.visibility,
            sources=sources,
            reads=reads,
            expected_basis=closure.source_basis
            and a.canonical_basis(closure.source_basis, closure.required_source_read_set),
            boundaries=late_bounds,
        )
        _require(final.material_sha256 == closure.material_sha256 and _runtime(s) == stamp)
        _require(
            anchor_storage.read_origin_descriptor(s, ctx, product_id, origin.issue_id, origin.ref)
            == descriptor
        )
        result_hash = digest(
            {
                "source_material": closure.material_sha256,
                "authority": authority,
                "policy": policy_value,
                "origin": descriptor.current.model_dump(mode="json"),
            }
        )
        checked, time_constraints = _deadline(s, ctx, product_id, late_bounds)
        guards._same_uow(s, uow, ctx, caller)
        _require(_runtime(s) == stamp)
    return FactSourcesRead(
        final.scope,
        final.sources,
        final.required_source_read_set,
        final.source_basis,
        final.byte_material,
        authority,
        policy_value,
        result_hash,
        checked,
        None,
        tuple(sorted(set(final.missing) | {"PAIRED_SOURCE_OWNER_REQUIRED"})),
        time_constraints=time_constraints,
    )


def refresh_fact_sources(
    s, ctx, product_id, material, previous: FactSourcesRead, *, operations, candidate_owner=None
):
    actual = read_fact_sources(
        s, ctx, product_id, material, operations=operations, candidate_owner=candidate_owner
    )
    _require(
        actual.material_sha256 == previous.material_sha256
        and actual.source_basis == previous.source_basis
    )
    return actual
