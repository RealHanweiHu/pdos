"""At most effect then close, with complete host provenance and exact mutations.

These pure validators cannot establish a real Receipt/consumption/ACL by themselves.
The optional host protocol must read genuine immutable records and fresh complete
closure; a missing host is INTEGRATION_REQUIRED. No DB, commit, reserve or Current.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal, Protocol
from uuid import UUID

from anchor import (
    CurrentAuthorizationClosure,
    IssueVersionEvidence,
    OriginalFailureProof,
    Revision,
    Sha256,
    SourceRead,
    StableCapaAnchor,
    VersionRef,
    canonical_basis,
    canonical_reads,
    canonical_sources,
    closure_material,
    json_value,
    reject,
    stable_failure_material,
    verify_closure,
)
from pdos_next.domain.quality_issues.handlers import QualityIssueHandler
from pdos_next.domain.quality_issues.ports import (
    Authority,
    Currentness,
    Ports,
    QualityPolicy,
    VerificationEvidence,
)
from pdos_next.domain.quality_issues.rules import digest, semantic_digest
from pdos_next.errors import DomainError
from pdos_next.schemas.quality_issues.contracts import EffectivenessDecide, History, IssueClose
from pdos_next.schemas.verification.contracts import DTO, SourceRef
from pydantic import AwareDatetime, Field, JsonValue

EFFECT = "quality.capa.effectiveness.decide"
CLOSE = "quality.issue.close"
Operation = Literal["quality.capa.effectiveness.decide", "quality.issue.close"]


class SourceDelta(DTO):
    """HOST-classified additional evidence, never guessed by source-kind keywords."""

    verification: tuple[SourceRef, ...]
    policy: tuple[SourceRef, ...]
    professional: tuple[SourceRef, ...]
    approval: tuple[SourceRef, ...]
    required_source_read_set: tuple[SourceRead, ...] = Field(min_length=1, max_length=20)

    def sources(self):
        return canonical_sources(
            (*self.verification, *self.policy, *self.professional, *self.approval)
        )


class ConsumedApproval(DTO):
    id: UUID
    tier: Literal["T2"]
    tenant_id: UUID
    product_id: UUID
    actor_id: UUID
    subject_id: UUID  # common Confirmation subject is Product, not Issue
    operation: Operation
    product_revision: Revision
    consumed: Annotated[bool, Field(strict=True)]
    evaluated_at: AwareDatetime
    expires_at: AwareDatetime
    material_sha256: Sha256  # actual common Confirmation material_digest
    read_set_sha256: Sha256
    approved_delta_sha256: Sha256
    # Host attests the actual reciprocal persisted group / same-UOW provenance.
    transaction_proof_id: UUID
    transaction_proof_sha256: Sha256


class ReceiptEvidence(DTO):
    id: UUID
    tenant_id: UUID
    product_id: UUID
    command_id: UUID
    actor_id: UUID
    requester_id: UUID
    operation: Operation
    subject_type: Literal["quality_issue"]
    subject_id: UUID  # next immutable version UUID
    subject_revision: Revision
    visibility: Literal["private", "product"]
    request_digest: Sha256
    intent_digest: Sha256  # common intent; never equate it to domain intent
    run_id: None
    result: dict[str, JsonValue]
    created_at: AwareDatetime


class AuditEvidence(DTO):
    id: UUID
    tenant_id: UUID
    receipt_id: UUID
    actor_id: UUID
    operation: Operation


class OutboxEvidence(DTO):
    id: UUID
    tenant_id: UUID
    receipt_id: UUID
    type: Literal["capa.effectiveness_decided", "issue.closed"]
    subject_id: UUID
    subject_revision: Revision
    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    actor_id: UUID
    correlation_id: UUID


class TransitionHostProof(DTO):
    before_ref: VersionRef
    after_ref: VersionRef
    operation: Operation
    command_id: UUID
    writer_id: UUID
    payload: EffectivenessDecide | IssueClose
    payload_sha256: Sha256
    domain_intent_sha256: Sha256
    common_intent_sha256: Sha256
    authority: Authority
    # Full saved qualification/policy/companion sources remain bound by host proof.
    professional_snapshot: dict[str, JsonValue] = Field(min_length=1)
    signer_recheck: dict[str, JsonValue] = Field(min_length=1)
    policy: QualityPolicy
    policy_snapshot: dict[str, JsonValue] = Field(min_length=1)
    verification: tuple[VerificationEvidence, ...] = Field(min_length=1)
    source_delta: SourceDelta
    approval: ConsumedApproval
    receipt: ReceiptEvidence
    audit: AuditEvidence
    outbox: OutboxEvidence
    proof_sha256: Sha256


def transition_delta_material(before, after, proof):
    """Opaque actual common material stays separate; this binds the exact host delta."""
    return {
        "before": json_value(before),
        "after": json_value(after),
        "operation": proof.operation,
        "command_id": str(proof.command_id),
        "writer_id": str(proof.writer_id),
        "payload": json_value(proof.payload),
        "domain_intent_sha256": proof.domain_intent_sha256,
        "common_intent_sha256": proof.common_intent_sha256,
        "source_delta": json_value(proof.source_delta),
        "approval_id": str(proof.approval.id),
    }


def _proof_digest(proof):
    raw = json_value(proof)
    raw.pop("proof_sha256")
    return digest(raw)


def consumption_group_material(after, proof):
    """Structural digest of the real host-read reciprocal group, not a second fact."""
    approval = json_value(proof.approval)
    approval.pop("transaction_proof_sha256")
    return {
        "approval": approval,
        "next_issue_version": json_value(after),
        "receipt": json_value(proof.receipt),
        "audit": json_value(proof.audit),
        "outbox": json_value(proof.outbox),
    }


class _EvidenceInput:
    """Pure kernel adapter over already HOST-verified complete source closure."""

    def __init__(self, sources, scope):
        self.sources, self.scope = set(sources), scope

    def check(self, scope, source, purpose):
        if scope != self.scope or source not in self.sources or purpose != "quality.issue":
            reject("Kernel verification source is outside the full host closure.")

    def currentness(self, scope, source, purpose):
        self.check(scope, source, purpose)
        return Currentness(current=True)


class _PolicyInput:
    def __init__(self, proof):
        self.proof = proof

    def assess(self, authority, failures):
        return self.proof.policy

    def verification(self, authority, evidence_id, issue):
        values = [v for v in self.proof.verification if v.id == evidence_id]
        if len(values) != 1 or authority != self.proof.authority:
            reject("Evidence ID/authority must bind exactly one actual host record.")
        return values[0]


def _kernel_verification(before, proof, closure):
    # Reuse the existing full observation/independence/pass/failure rules unchanged.
    kernel = QualityIssueHandler(
        Ports(policies=_PolicyInput(proof), evidence=_EvidenceInput(closure.sources, before.scope))
    )
    if proof.operation == EFFECT:
        payload = EffectivenessDecide.model_validate(json_value(proof.payload))
    else:
        decision = before.issue.capa.effectiveness
        if (
            decision is None
            or decision.result != "effective"
            or decision.actor_id != proof.writer_id
        ):
            reject("Close follows an effective decision by that same named decision maker.")
        payload = EffectivenessDecide(
            result=decision.result, text=decision.text, evidence_ids=decision.evidence_ids
        )
    evidence, read_digest = kernel._verification(
        proof.authority, before.issue, payload, proof.policy
    )
    if tuple(evidence) != proof.verification:
        reject("Complete evidence list/order must equal the kernel's precise referenced set.")
    return payload, read_digest


def _check_provenance(before, after, proof):
    if _proof_digest(proof) != proof.proof_sha256:
        reject("Host transition proof digest does not bind the complete input.")
    if (
        proof.before_ref,
        proof.after_ref,
        proof.operation,
        proof.writer_id,
        proof.domain_intent_sha256,
    ) != (before.ref, after.ref, after.operation, after.writer_id, after.domain_intent_sha256):
        reject("Host transition is not the exact immutable before/after writer and operation.")
    wanted_payload = EffectivenessDecide if proof.operation == EFFECT else IssueClose
    if (
        type(proof.payload) is not wanted_payload
        or semantic_digest(proof.payload) != proof.payload_sha256
    ):
        reject("Operation must bind the exact typed payload and semantic digest.")
    authority = proof.authority
    if (
        authority.scope != before.scope
        or authority.actor_id != proof.writer_id
        or authority.actor_kind != "human"
        or "quality" not in authority.roles
        or not authority.authorized
        or not authority.qualified
        or authority.cancelled
        or authority.now.tzinfo is None
        or authority.now.utcoffset() is None
        or not set(before.issue.audience) <= set(authority.audience)
    ):
        reject("Transition requires exact named qualified QUALITY host authority.")
    professional = proof.professional_snapshot
    if (
        professional.get("scope") != json_value(before.scope)
        or professional.get("subject_id") != str(proof.writer_id)
        or professional.get("operation") != proof.operation
        or professional.get("purpose") != before.purpose
        or professional.get("authorized") is not True
        or professional.get("qualified") is not True
        or "quality" not in professional.get("roles", [])
    ):
        reject("Full professional snapshot does not bind writer, operation, scope and purpose.")
    if after.authority_snapshot != professional or after.policy_snapshot != proof.policy_snapshot:
        reject("Transition must preserve the exact saved professional and policy snapshots.")
    recheck = proof.signer_recheck
    if (
        recheck.get("current") is not True
        or recheck.get("reason_codes") != []
        or recheck.get("scope") != json_value(before.scope)
        or recheck.get("subject_id") != str(proof.writer_id)
        or recheck.get("operation") != proof.operation
        or recheck.get("purpose") != before.purpose
        or recheck.get("original_snapshot_sha256") != digest(professional)
        or not isinstance(recheck.get("assessment"), dict)
        or not recheck["assessment"]
    ):
        reject("Original professional signer/issuer epochs need a full current host recheck.")
    policy_ref = proof.policy_snapshot.get(
        "ref",
        {"id": proof.policy_snapshot.get("id"), "revision": proof.policy_snapshot.get("revision")},
    )
    if (
        policy_ref != json_value(proof.policy.ref)
        or proof.policy_snapshot.get("risk") != proof.policy.risk
        or proof.policy_snapshot.get("independent_verification")
        is not proof.policy.independent_verification
    ):
        reject("Kernel policy must bind the full actual saved policy version and decision.")
    approval = proof.approval
    if (
        approval.tenant_id,
        approval.product_id,
        approval.actor_id,
        approval.subject_id,
        approval.operation,
        approval.consumed,
    ) != (
        before.scope.tenant_id,
        before.scope.product_id,
        proof.writer_id,
        before.scope.product_id,
        proof.operation,
        True,
    ):
        reject("Consumed T2 UUID must bind common Product/actor/operation, not a caller flag.")
    if approval.transaction_proof_id != approval.id or approval.transaction_proof_sha256 != digest(
        consumption_group_material(after, proof)
    ):
        reject(
            "Reciprocal persisted group must bind the actual consumed UUID and full saved group."
        )
    if not approval.evaluated_at < approval.expires_at or authority.now != approval.evaluated_at:
        reject("Named transition decision must occur while its real approval is valid.")
    if approval.read_set_sha256 != digest(
        [json_value(r) for r in canonical_reads(after.required_source_read_set)]
    ):
        reject("Approval does not bind the complete exact new source read set.")
    if approval.approved_delta_sha256 != digest(transition_delta_material(before, after, proof)):
        reject("Actual host approval attestation must bind the exact saved delta.")
    if after.persisted_source_basis.get("shared_proof") != {"id": str(approval.id), "tier": "T2"}:
        reject("Saved version lacks this exact shared T2 UUID binding.")
    receipt, audit, outbox = proof.receipt, proof.audit, proof.outbox
    if (
        receipt.tenant_id,
        receipt.product_id,
        receipt.command_id,
        receipt.actor_id,
        receipt.requester_id,
        receipt.operation,
        receipt.subject_id,
        receipt.subject_revision,
        receipt.visibility,
        receipt.intent_digest,
    ) != (
        before.scope.tenant_id,
        before.scope.product_id,
        proof.command_id,
        proof.writer_id,
        proof.writer_id,
        proof.operation,
        after.ref.id,
        after.ref.revision,
        after.visibility,
        proof.common_intent_sha256,
    ):
        reject("Common Receipt must bind exact new row, version, action and actual writer.")
    if (
        receipt.result.get("id") != str(after.ref.id)
        or type(receipt.result.get("revision")) is not int
        or receipt.result["revision"] != after.ref.revision
        or receipt.result.get("issue_id") != str(after.issue_id)
        or receipt.result.get("status") != after.issue.status
    ):
        reject("Receipt result must identify exact saved logical Issue/version/status.")
    if (audit.tenant_id, audit.receipt_id, audit.actor_id, audit.operation) != (
        receipt.tenant_id,
        receipt.id,
        receipt.actor_id,
        receipt.operation,
    ):
        reject("Exact Audit must belong to this Receipt and writer.")
    event = "capa.effectiveness_decided" if proof.operation == EFFECT else "issue.closed"
    if (
        outbox.tenant_id,
        outbox.receipt_id,
        outbox.type,
        outbox.subject_id,
        outbox.subject_revision,
        outbox.actor_id,
        outbox.correlation_id,
    ) != (
        receipt.tenant_id,
        receipt.id,
        event,
        after.ref.id,
        after.ref.revision,
        receipt.actor_id,
        receipt.command_id,
    ):
        reject("Exact Outbox must bind canonical event, command and saved Receipt subject.")
    if not authority.now <= after.created_at <= receipt.created_at:
        reject("Saved version/Receipt cannot precede the real decision clock.")


def _check_step(before, after, proof, closure):
    if (
        before.scope,
        before.issue_id,
        before.purpose,
        before.owner_id,
        before.visibility,
        before.nature,
        before.issue.audience,
    ) != (
        after.scope,
        after.issue_id,
        after.purpose,
        after.owner_id,
        after.visibility,
        after.nature,
        after.issue.audience,
    ):
        reject("Successor cannot rebind scope, owner, audience, purpose or nature.")
    if after.previous_ref != before.ref or after.ref.revision != before.ref.revision + 1:
        reject("A successor needs its exact immediate immutable predecessor.")
    _check_provenance(before, after, proof)
    payload, read_digest = _kernel_verification(before, proof, closure)
    expected = before.issue.model_dump(mode="json")
    expected["revision"] += 1
    history = History(
        command_id=proof.command_id,
        operation=proof.operation,
        actor_id=proof.writer_id,
        actor_kind="human",
        at=proof.authority.now,
        note=proof.payload.text,
    )
    expected["history"].append(json_value(history))
    if before.issue.status != "awaiting_verification":
        reject("Only a completed investigation awaits these two decisions.")
    if proof.operation == EFFECT:
        if before.issue.capa.effectiveness or before.issue.capa.effectiveness_history:
            reject("At most one effectiveness decision is allowed in this staged lineage.")
        decision = {
            "text": payload.text,
            "actor_id": str(proof.writer_id),
            "at": json_value(history)["at"],
            "sources": [json_value(s) for e in proof.verification for s in e.sources],
            "result": payload.result,
            "evidence_ids": [str(eid) for eid in payload.evidence_ids],
            "policy": json_value(proof.policy.ref),
            "read_digest": read_digest,
        }
        expected["capa"]["effectiveness"] = decision
        expected["capa"]["effectiveness_history"].append(deepcopy_json(decision))
    else:
        decision = before.issue.capa.effectiveness
        if decision.read_digest != read_digest or decision.policy != proof.policy.ref:
            reject("Close must revalidate exact effectiveness evidence and policy.")
        expected["status"] = "closed"
        expected["closure"] = {
            "text": proof.payload.text,
            "actor_id": str(proof.writer_id),
            "at": json_value(history)["at"],
            "sources": [json_value(s) for s in decision.sources],
        }
    if after.issue.model_dump(mode="json") != expected:
        reject("Non-white-listed field/history mutation or inaccurate effect/closure append.")
    if canonical_sources(proof.source_delta.verification) != canonical_sources(
        tuple(s for e in proof.verification for s in e.sources)
    ):
        reject("Added verification sources must be the exact verified companion evidence.")
    if canonical_sources(after.sources) != canonical_sources(
        (*before.sources, *proof.source_delta.sources())
    ):
        reject("Successor source set is not the exact host-classified lawful addition.")
    if canonical_reads(after.required_source_read_set) != canonical_reads(
        (*before.required_source_read_set, *proof.source_delta.required_source_read_set)
    ):
        reject("Successor must preserve every old read and only exact host-added reads.")
    after_basis = {
        b.id: b for b in canonical_basis(after.source_basis, after.required_source_read_set)
    }
    if any(after_basis.get(b.id) != b for b in before.source_basis):
        reject("Original source hash/scope/provenance/security epoch cannot be replaced.")
    if not set(canonical_sources(after.sources)) <= set(canonical_sources(closure.sources)):
        reject("Current closure must contain every legally added successor source.")
    current_basis = {b.id: b for b in closure.source_basis}
    if any(current_basis.get(b.id) != b for b in after.source_basis):
        reject("Legally added source is not currently the exact safe source.")


def deepcopy_json(value):
    # Canonical JSON round-trip is deliberately unnecessary; preserve exact DTO values.
    from copy import deepcopy

    return deepcopy(value)


class IssueLineageProof(DTO):
    schema_version: Literal["capa-lineage-proof-v1"] = "capa-lineage-proof-v1"
    anchor_sha256: Sha256
    current_ref: VersionRef
    step_proof_sha256s: tuple[Sha256, ...] = Field(max_length=2)
    material_sha256: Sha256
    stable_failure_material_sha256: Sha256
    origin_source_basis_sha256: Sha256
    current_authorization_closure_sha256: Sha256
    proof_sha256: Sha256
    structural_validation_only: Literal[True] = True


def validate_lineage(anchor, versions, steps, closure, *, at):
    anchor = StableCapaAnchor.model_validate(json_value(anchor))
    versions = tuple(IssueVersionEvidence.model_validate(json_value(v)) for v in versions)
    steps = tuple(TransitionHostProof.model_validate(json_value(s)) for s in steps)
    closure = verify_closure(anchor, closure, at=at)
    if (
        not 1 <= len(versions) <= 3
        or len(steps) != len(versions) - 1
        or versions[0] != anchor.origin
    ):
        reject("Exact origin plus no more than two fully proved successors is required.")
    if len({v.ref.id for v in versions}) != len(versions):
        reject("Lineage has a cycle or reused immutable version identity.")
    if any(v.created_at > at for v in versions):
        reject("Current cannot include a future purported saved version.")
    if tuple(p.operation for p in steps) not in {(), (EFFECT,), (EFFECT, CLOSE)}:
        reject("Only one effect followed by one close is permitted; never skip a step.")
    if len({p.command_id for p in steps}) != len(steps):
        reject("Effect and close require distinct actual commands.")
    if len({p.approval.id for p in steps}) != len(steps):
        reject("Effect and close consume distinct actual T2 UUIDs.")
    if len({p.receipt.id for p in steps}) != len(steps):
        reject("Two distinct decisions cannot reuse one Receipt.")
    for before, after, proof in zip(versions, versions[1:], steps, strict=False):
        _check_step(before, after, proof, closure)
    values = {
        "schema_version": "capa-lineage-proof-v1",
        "anchor_sha256": anchor.anchor_sha256,
        "current_ref": json_value(versions[-1].ref),
        "step_proof_sha256s": [p.proof_sha256 for p in steps],
        "material_sha256": anchor.material_sha256,
        "stable_failure_material_sha256": anchor.stable_failure_material_sha256,
        "origin_source_basis_sha256": anchor.origin_source_basis_sha256,
        "current_authorization_closure_sha256": digest(closure_material(closure)),
        "structural_validation_only": True,
    }
    return IssueLineageProof(**values, proof_sha256=digest(values))


class LineageHost(Protocol):
    """Root-only current ACL/real records/bytes/issuer readers, no commit/Receipt."""

    def read_current_ref(self, anchor) -> VersionRef: ...
    def read_version(self, ref: VersionRef) -> IssueVersionEvidence: ...
    def read_transition(self, before, after) -> TransitionHostProof: ...
    def read_original_failures(self, anchor) -> tuple[OriginalFailureProof, ...]: ...
    def read_current_closure(self, anchor, current_ref) -> CurrentAuthorizationClosure: ...


def verify_from_host(
    host: LineageHost | None, anchor, current_ref, *, clock: Callable[[], datetime]
):
    if host is None or any(
        not callable(getattr(host, key, None))
        for key in (
            "read_current_ref",
            "read_version",
            "read_transition",
            "read_original_failures",
            "read_current_closure",
        )
    ):
        raise DomainError(
            "INTEGRATION_REQUIRED", "Exact lineage/bytes/current closure host is missing.", 503
        )
    anchor = StableCapaAnchor.model_validate(json_value(anchor))
    current_ref = VersionRef.model_validate(json_value(current_ref))
    if VersionRef.model_validate(json_value(host.read_current_ref(anchor))) != current_ref:
        reject("Supplied current_ref is not the exact real Current pointer.", "SOURCE_STALE")
    versions = []
    ref = current_ref
    for _ in range(3):
        row = host.read_version(ref)
        row = IssueVersionEvidence.model_validate(json_value(row))
        if row.ref != ref:
            reject("Owner reader returned another immutable version.")
        versions.append(row)
        if row.ref == anchor.origin.ref:
            break
        if row.previous_ref is None:
            reject("Lineage ends before the exact anchor.")
        ref = row.previous_ref
    else:
        reject("Current is outside the two-successor whitelist.")
    versions.reverse()
    steps = tuple(host.read_transition(a, b) for a, b in zip(versions, versions[1:], strict=False))
    current_failures = tuple(
        OriginalFailureProof.model_validate(json_value(f))
        for f in host.read_original_failures(anchor)
    )
    if [stable_failure_material(f) for f in current_failures] != [
        stable_failure_material(f) for f in anchor.failures
    ]:
        reject("Archived failure/Start/effects/source material drifted; do not read latest Run.")
    first = host.read_current_closure(anchor, current_ref)
    proof = validate_lineage(anchor, versions, steps, first, at=clock())
    # Independent fresh read AFTER all record/owner/bytes IO; no cross-phase cache.
    final = host.read_current_closure(anchor, current_ref)
    final_ref = VersionRef.model_validate(json_value(host.read_current_ref(anchor)))
    verify_closure(anchor, final, at=clock())
    if closure_material(first) != closure_material(final) or final_ref != current_ref:
        reject("Source/ACL/qualification/policy/runtime drifted after owner IO.", "SOURCE_STALE")
    return proof
