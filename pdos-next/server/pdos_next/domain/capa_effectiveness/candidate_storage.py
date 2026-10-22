"""Read an exact stored candidate/common group, without any live owner gate.

Not registered or mounted. The candidate writer/strict payload is a required
host dependency; old inspection hashes and historical consumed flags are not
substitutes for a full candidate reference or same-UOW consumption evidence.
"""

# Common registry initialization precedes domain children.
# ruff: noqa: I001
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import re
from types import ModuleType, SimpleNamespace
from typing import Literal
from collections.abc import Callable
from uuid import UUID

from pdos_next.service import Context, digest

from . import anchor
from . import anchor_storage
from . import fact_atom_storage as guards
from .fact_registry_storage import CandidateRegistryRead
from .facts import FactRef
from pdos_next.domain.capa_verification.models import CapaVerificationEvidence
from pdos_next.domain.capa_verification.schemas import CandidateBinding, CandidateInspect
from pdos_next.domain.capa_verification.service import basis_from_issue
from pdos_next.errors import DomainError
from pdos_next.models import Audit, Confirmation, Outbox, Principal, Receipt, RequestKey
from pdos_next.receipt_request_binding import readable_receipt_request_bound
from pdos_next.schemas.verification.contracts import DTO
from pydantic import AwareDatetime, BaseModel, JsonValue, ValidationError
from sqlalchemy import select

OPERATION = "quality.capa.verification.candidate.record"
SUBJECT = "capa_verification_candidate"
EVENT = "CapaVerificationCandidateRecorded"
DELIVERY_FIELDS = frozenset({"delivered_at", "lease_id", "lease_until", "attempts", "last_error"})


def _require(condition, code="CANDIDATE_STORED_BINDING_MISMATCH", status=503):
    if not condition:
        raise DomainError(code, "候选固定材料、实际共同组或当前读取范围尚不能精确核对。", status)


@dataclass(frozen=True)
class CandidateSemanticOwner:
    """Server configuration of the actual strict payload and module callback.

    The future registered candidate module supplies this object at startup.
    It is not a client payload or a generic JSON identity semantic adapter.
    """

    payload_type: type[BaseModel]
    module: ModuleType
    semantic: Callable[[BaseModel], dict]

    def check(self):
        _require(
            isinstance(self.payload_type, type)
            and issubclass(self.payload_type, BaseModel)
            and self.payload_type.model_config.get("extra") == "forbid"
            and isinstance(self.module, ModuleType)
            and getattr(self.module, "OPERATION", None) == OPERATION
            and getattr(self.module, "semantic", None) is self.semantic
            and callable(self.semantic),
            "CANDIDATE_SEMANTIC_OWNER_REQUIRED",
        )
        field = self.payload_type.model_fields.get("confirmation_token")
        _require(
            field is not None and not field.is_required() and field.default is None,
            "CANDIDATE_SEMANTIC_OWNER_REQUIRED",
        )


class SharedProof(DTO):
    id: UUID
    tier: Literal["T1"]


class CandidateInput(DTO):
    semantic: dict[str, JsonValue]
    shared_proof: SharedProof
    proof_consumed_at: AwareDatetime
    stable_anchor: anchor.StableCapaAnchor


@dataclass(frozen=True)
class StoredCandidateRead:
    ref: FactRef
    candidate: dict
    body: CandidateInput
    binding: CandidateBinding
    inspection: CandidateInspect
    group: dict
    origin: anchor_storage.StoredOriginRead
    registry: CandidateRegistryRead
    registry_observed_at: datetime
    missing: tuple[str, ...]
    # Even an origin currently at the same row needs the actual lineage owner
    # before use in a live seven-gate evidence decision.
    needs_lineage_owner: Literal[True] = True
    current_evidence_authorized: Literal[False] = False
    source_bytes_verified: Literal[False] = False
    original_failures_verified: Literal[False] = False
    same_uow_consumption_attested: Literal[False] = False


def _canonical(value):
    """Canonical actual column material; JSON values are otherwise unchanged."""
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        _require(
            value.tzinfo is not None and value.utcoffset() is not None, "CANDIDATE_CLOCK_INVALID"
        )
        return value.astimezone(UTC).isoformat()
    if isinstance(value, dict):
        _require(all(isinstance(k, str) for k in value), "CANDIDATE_JSON_INVALID")
        return {k: _canonical(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(v) for v in value]
    _require(value is None or type(value) in {str, bool, int, float}, "CANDIDATE_JSON_INVALID")
    # Reject non-finite numbers rather than inventing a canonical JSON value.
    try:
        json.dumps(value, allow_nan=False)
    except ValueError:
        raise DomainError("CANDIDATE_JSON_INVALID", "候选保存JSON不是有限精确材料。", 503) from None
    return deepcopy(value)


def _columns(row, *, exclude=frozenset()):
    material = {}
    for column in row.__table__.columns:
        # Audience dependencies are a DB-owned RLS projection, outside the
        # immutable business atom. Live RLS/ACL checks remain independent.
        if column.key in exclude or column.key == "audience_dependencies":
            continue
        value = getattr(row, column.key)
        _require(column.nullable or value is not None, "CANDIDATE_ACTUAL_COLUMN_MISSING")
        material[column.key] = _canonical(value)
    return material


def _typed(model, value):
    try:
        return model.model_validate(deepcopy(value))
    except (ValidationError, TypeError, ValueError):
        raise DomainError(
            "CANDIDATE_TYPED_MATERIAL_INVALID", "候选保存结构或摘要格式无效。", 503
        ) from None


def _owner(owner):
    _require(type(owner) is CandidateSemanticOwner, "CANDIDATE_SEMANTIC_OWNER_REQUIRED")
    owner.check()
    return owner


def _semantic(body, owner):
    _require(
        not {"confirmation_token", "approval_token"} & body.semantic.keys(),
        "CANDIDATE_SEMANTIC_HAS_TOKEN",
    )
    payload = _typed(owner.payload_type, body.semantic)
    _require(
        payload.confirmation_token is None and owner.semantic(payload) == body.semantic,
        "CANDIDATE_ACTUAL_SEMANTIC_MISMATCH",
    )
    return payload


def _row(s, ctx, pid, candidate_id):
    row = guards._one(
        s,
        CapaVerificationEvidence,
        CapaVerificationEvidence.tenant_id == ctx.tenant_id,
        CapaVerificationEvidence.product_id == pid,
        CapaVerificationEvidence.id == candidate_id,
    )
    _require(
        row.visibility in {"private", "category", "audience"}
        and (row.visibility != "private" or row.owner_id == ctx.requester_id),
        "FORBIDDEN_SCOPE",
        403,
    )
    _require(
        type(row.revision) is int
        and row.revision == 1
        and row.status == "candidate"
        and row.result == "indeterminate"
        and row.applicable is row.independently_verified is row.observation_complete is None,
        "CANDIDATE_RESULT_NOT_UNKNOWN",
    )
    _require(
        isinstance(row.sources, list)
        and isinstance(row.required_source_read_set, list)
        and isinstance(row.source_basis, dict),
        "CANDIDATE_SOURCE_BASIS_REQUIRED",
    )
    project = anchor_storage._project(s, ctx, pid, row.project_id)
    return row, _columns(row), project


def _raw_safety(row, reads):
    raw = row.source_basis.get("artifact_sources")
    _require(isinstance(raw, list), "CANDIDATE_SOURCE_BASIS_REQUIRED")
    # Parse for binding safety but hash the original raw JSON. Native/uploaded
    # entries omit different optional keys; model_dump must not add null keys.
    anchor.canonical_basis(raw, row.required_source_read_set)
    wanted = {r.artifact_id: r.expected_revision for r in anchor.canonical_reads(reads)}
    subset = [v for v in raw if UUID(v["id"]) in wanted]
    anchor.canonical_basis(subset, reads)
    return deepcopy(subset)


def _materials(s, ctx, pid, row, owner):
    # Missing legacy wrapper is an integration gap, not a made-up consumption
    # timestamp or an inferred stable anchor.
    _require(
        isinstance(row.input_snapshot, dict)
        and set(row.input_snapshot)
        == {"semantic", "shared_proof", "proof_consumed_at", "stable_anchor"},
        "CANDIDATE_NEW_WRAPPER_REQUIRED",
    )
    body = _typed(CandidateInput, row.input_snapshot)
    payload = _semantic(body, owner)
    binding = _typed(CandidateBinding, row.candidate_binding)
    inspection = _typed(CandidateInspect, row.candidate_snapshot)
    basis = binding.basis
    origin = anchor_storage.read_origin_descriptor(
        s, ctx, pid, row.issue_id, body.stable_anchor.origin.ref
    )
    _require(origin.origin == body.stable_anchor.origin, "CANDIDATE_ACTUAL_ORIGIN_MISMATCH")
    _require(
        (
            basis.scope.tenant_id,
            basis.scope.product_id,
            basis.scope.project_id,
            basis.issue_id,
            basis.issue_version_id,
            basis.issue_revision,
            basis.capa_id,
            basis.owner_id,
            basis.visibility,
            basis.nature,
            basis.purpose,
        )
        == (
            row.tenant_id,
            row.product_id,
            row.project_id,
            row.issue_id,
            row.issue_version_id,
            row.issue_revision,
            row.capa_id,
            row.owner_id,
            row.visibility,
            row.nature,
            row.purpose,
        )
        and basis.issue_version_id == origin.origin.ref.id
        and basis.issue_revision == origin.origin.ref.revision
        and basis.model_dump(mode="json") == row.basis_snapshot,
        "CANDIDATE_FIXED_BASIS_SCOPE_MISMATCH",
    )
    projected = basis_from_issue(
        SimpleNamespace(
            issue_id=row.issue_id,
            id=row.issue_version_id,
            revision=row.issue_revision,
            tenant_id=row.tenant_id,
            product_id=row.product_id,
            project_id=row.project_id,
            purpose=origin.origin.purpose,
            owner_id=origin.origin.owner_id,
            visibility=origin.origin.visibility,
            snapshot_sha256=origin.origin.ref.snapshot_sha256,
        ),
        origin.origin.issue,
        sources=basis.sources,
        reads=basis.required_source_read_set,
        source_basis=_raw_safety(row, basis.required_source_read_set),
    )
    _require(
        projected == basis and row.basis_sha256 == basis.basis_sha256,
        "CANDIDATE_BASIS_SHA_MISMATCH",
    )
    _require(
        digest(binding.model_dump(mode="json")) == row.binding_sha256
        and inspection.binding == binding
        and inspection.inspection_sha256 == row.inspection_sha256
        and digest(
            inspection.model_dump(mode="json", exclude={"inspection_sha256", "candidate_ref"})
        )
        == row.inspection_sha256
        and (
            inspection.candidate_ref is None
            or (inspection.candidate_ref.id, inspection.candidate_ref.revision) == (row.id, 1)
        ),
        "CANDIDATE_BINDING_INSPECTION_SHA_MISMATCH",
    )
    reads = anchor.canonical_reads(row.required_source_read_set)
    sources = anchor.canonical_sources(row.sources)
    anchor.source_closure(sources, reads, row.source_basis["artifact_sources"])
    _require(
        reads == anchor.canonical_reads(inspection.required_source_read_set)
        and set(basis.required_source_read_set) <= set(reads)
        and set(body.stable_anchor.origin_required_source_read_set) <= set(reads)
        and set(body.stable_anchor.origin_sources) <= set(sources)
        and set(basis.sources) <= set(sources)
        and digest(_raw_safety(row, inspection.required_source_read_set))
        == inspection.source_basis_sha256,
        "CANDIDATE_COMPLETE_SOURCE_BINDING_MISMATCH",
    )
    return body, payload, binding, inspection, origin


def _group(s, ctx, pid, row, body, payload, owner):
    writer = guards._one(
        s, Principal, Principal.tenant_id == ctx.tenant_id, Principal.id == row.writer_id
    )
    _require(writer.kind == "human", "CANDIDATE_NAMED_WRITER_REQUIRED")
    receipt = guards._one(
        s,
        Receipt,
        Receipt.tenant_id == ctx.tenant_id,
        Receipt.product_id == pid,
        Receipt.operation == OPERATION,
        Receipt.subject_type == SUBJECT,
        Receipt.subject_id == row.id,
        Receipt.subject_revision == 1,
    )
    expected_intent = digest(
        {
            "operation": OPERATION,
            "category": ctx.category_id,
            "product": pid,
            "payload": owner.semantic(payload),
            "named_actor": row.writer_id,
            "source_revision": None,
            "private_owner": row.writer_id
            if getattr(payload, "visibility", "private") == "private"
            else None,
        }
    )
    _require(
        receipt.actor_id == receipt.requester_id == row.writer_id
        and receipt.run_id is None
        and receipt.visibility == row.visibility
        and receipt.intent_digest == row.intent_digest == expected_intent
        and receipt.result
        == {
            "id": str(row.id),
            "revision": 1,
            "status": "candidate",
            "candidate_binding_sha256": row.binding_sha256,
            "inspection_sha256": row.inspection_sha256,
        }
        and type(receipt.result["revision"]) is int
        and re.fullmatch(r"[0-9a-f]{64}", receipt.request_digest or "") is not None,
        "CANDIDATE_RECEIPT_BINDING_MISMATCH",
    )
    keys = list(
        s.scalars(
            select(RequestKey)
            .where(
                RequestKey.tenant_id == ctx.tenant_id,
                RequestKey.actor_id == row.writer_id,
                RequestKey.receipt_id == receipt.id,
                RequestKey.digest == receipt.request_digest,
            )
            .limit(1)
            .execution_options(populate_existing=True, autoflush=False)
        )
    )
    key_bound = bool(keys)
    if not key_bound and receipt.actor_id != ctx.actor_id:
        key_bound = readable_receipt_request_bound(s, ctx, pid, receipt.id)
    _require(key_bound, "CANDIDATE_ORIGINAL_REQUEST_KEY_MISSING")
    audit = guards._one(s, Audit, Audit.tenant_id == ctx.tenant_id, Audit.receipt_id == receipt.id)
    outbox = guards._one(
        s, Outbox, Outbox.tenant_id == ctx.tenant_id, Outbox.receipt_id == receipt.id
    )
    proof = guards._one(
        s,
        Confirmation,
        Confirmation.tenant_id == ctx.tenant_id,
        Confirmation.product_id == pid,
        Confirmation.id == body.shared_proof.id,
    )
    # Validate actual aware clocks/non-null columns before comparing timestamps;
    # corrupt stored clocks must yield an explicit gap, not a Python TypeError.
    receipt_columns = _columns(receipt)
    audit_columns = _columns(audit)
    outbox_columns = _columns(outbox, exclude=DELIVERY_FIELDS)
    proof_columns = _columns(proof)
    material = digest(
        {
            "tenant": ctx.tenant_id,
            "actor": row.writer_id,
            "requester": row.writer_id,
            "operation": OPERATION,
            "category": ctx.category_id,
            "product": pid,
            "expected_revision": proof.revision,
            "read_set": sorted(
                row.required_source_read_set,
                key=lambda r: (r["artifact_id"], r["expected_revision"]),
            ),
            "payload": owner.semantic(payload),
        }
    )
    _require(
        type(proof.revision) is int
        and proof.revision > 0
        and proof.actor_id == row.writer_id
        and proof.subject_id == pid
        and proof.operation == OPERATION
        and proof.consumed is True
        and proof.payload_digest == material
        and re.fullmatch(r"[0-9a-f]{64}", proof.token_hash or "") is not None
        and isinstance(proof.snapshot, dict)
        and bool(proof.snapshot)
        and audit.actor_id == row.writer_id
        and audit.operation == OPERATION
        and outbox.actor_id == row.writer_id
        and outbox.type == EVENT
        and outbox.subject_id == row.id
        and type(outbox.subject_revision) is int
        and outbox.subject_revision == 1
        and outbox.schema_version == 1
        and outbox.correlation_id == receipt.command_id,
        "CANDIDATE_SAVED_COMMON_GROUP_MISMATCH",
    )
    _require(
        proof.created_at <= body.proof_consumed_at <= row.created_at < proof.expires_at
        and row.created_at <= receipt.created_at
        and row.created_at <= audit.created_at
        and row.created_at <= outbox.created_at,
        "CANDIDATE_SAVED_CLOCK_INVALID",
    )
    return {
        "schema_version": "pdos-capa-candidate-common-group-v1",
        "receipt": receipt_columns,
        "audit": audit_columns,
        "outbox": outbox_columns,
        "confirmation": proof_columns,
        "proof_consumed_at": _canonical(body.proof_consumed_at),
        # Existence is rechecked but alias-dependent row IDs, keys and timestamps
        # are excluded from the stable original common group.
        "original_request_digest": receipt.request_digest,
    }


def read_candidate(s, ctx, product_id, candidate_id, expected_ref=None, *, semantic_owner=None):
    """Read immutable candidate/full group under the exact active named caller."""
    _require(isinstance(ctx, Context), "FACT_ACTUAL_NAMED_CALLER_REQUIRED")
    captured, caller = guards._uow(s), digest(vars(ctx))
    guards._acl(s, ctx, product_id)
    owner = _owner(semantic_owner)
    _require(isinstance(candidate_id, UUID), "CANDIDATE_EXACT_ID_REQUIRED")
    if expected_ref is not None:
        expected_ref = _typed(FactRef, expected_ref)
        _require(
            expected_ref.id == candidate_id and expected_ref.revision == 1,
            "CANDIDATE_FULL_REF_MISMATCH",
        )
    with s.no_autoflush:
        row, raw, project = _row(s, ctx, product_id, candidate_id)
        body, payload, binding, inspection, origin = _materials(s, ctx, product_id, row, owner)
        group = _group(s, ctx, product_id, row, body, payload, owner)
        ref = FactRef(
            id=candidate_id,
            revision=1,
            sha256=digest(
                {
                    "schema_version": "pdos-capa-candidate-full-v1",
                    "candidate": raw,
                    "group": group,
                }
            ),
        )
        _require(expected_ref is None or expected_ref == ref, "CANDIDATE_FULL_REF_MISMATCH")
        # All IO precedes the final fresh caller/Project/UOW/clock checks. Re-read
        # originals rather than treating populate_existing identity as a proof.
        last_row, last_raw, last_project = _row(s, ctx, product_id, candidate_id)
        last_origin = anchor_storage.read_origin_descriptor(
            s, ctx, product_id, row.issue_id, body.stable_anchor.origin.ref
        )
        last_group = _group(s, ctx, product_id, last_row, body, payload, owner)
        _require(
            raw == last_raw
            and group == last_group
            and origin == last_origin
            and project == last_project,
            "CANDIDATE_POST_IO_CHANGED",
        )
        final_project = anchor_storage._project(s, ctx, product_id, row.project_id)
        _require(project == final_project, "CANDIDATE_PROJECT_CHANGED")
        guards._acl(s, ctx, product_id)
        owner.check()
        guards._same_uow(s, captured, ctx, caller)
        at = guards.datetime.now(UTC)
        _require(
            all(
                datetime.fromisoformat(v["created_at"]) <= at
                for v in (
                    raw,
                    group["receipt"],
                    group["audit"],
                    group["outbox"],
                    group["confirmation"],
                )
            ),
            "CANDIDATE_FUTURE_STORED_CLOCK",
        )
    registry = CandidateRegistryRead(
        session=s,
        caller=ctx,
        product_id=product_id,
        ref=ref,
        scope=binding.basis.scope,
        issue_id=row.issue_id,
        capa_id=row.capa_id,
        purpose=row.purpose,
        owner_id=row.owner_id,
        visibility=row.visibility,
        nature=row.nature,
        anchor_sha256=body.stable_anchor.anchor_sha256,
        requirement_sha256=binding.basis.requirement_sha256,
    )
    return StoredCandidateRead(
        ref=ref,
        candidate=raw,
        body=body,
        binding=binding,
        inspection=inspection,
        group=group,
        origin=origin,
        registry=registry,
        registry_observed_at=at,
        missing=(
            "actual_source_bytes_security",
            "original_failure_owner",
            "limited_lineage_owner",
            "candidate_applicability_owner",
            "participant_independence_owner",
            "current_professional_policy_issuer",
            "same_uow_false_to_true_consumption",
            "seven_live_fact_reader_gates",
        ),
    )


def candidate_owner(semantic_owner):
    """Server-only registry callback factory; default missing is never positive."""
    owner = _owner(semantic_owner)

    def read(s, ctx, product_id, ref):
        ref = _typed(FactRef, ref)
        return read_candidate(s, ctx, product_id, ref.id, ref, semantic_owner=owner).registry

    return read
