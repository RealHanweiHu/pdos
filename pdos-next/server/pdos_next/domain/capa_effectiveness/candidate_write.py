"""Unregistered same-UOW candidate append; real host proof and prepare required.

Only s.add(candidate) is performed. No confirmation assignment, flush, commit,
Issue pointer change, Receipt creation or current-effectiveness permission.
"""

# Initialize the common registry before domain dependencies.
# ruff: noqa: I001
from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

from pdos_next.service import Context, digest

from . import anchor
from . import candidate_commands as commands
from . import candidate_prepare as preparation
from . import fact_atom_storage as guards
from . import fact_consumption as consumption
from .fact_consumption import ConsumptionHost, LiveConsumption
from pdos_next.contracts import Command
from pdos_next.domain.capa_verification.models import CapaVerificationEvidence
from pdos_next.errors import DomainError
from pdos_next.models import Product
from pdos_next.schemas.verification.contracts import DTO
from sqlalchemy import inspect

OPERATION = commands.OPERATION
TIER = commands.TIER
SUBJECT = commands.SUBJECT
EVENT = commands.EVENT
semantic = commands.semantic


class CandidateReceiptHashes(DTO):
    """Extra flattened common Receipt.result fields, never a full candidate SHA."""

    candidate_binding_sha256: anchor.Sha256
    inspection_sha256: anchor.Sha256


def _require(condition, code="CANDIDATE_WRITE_BINDING_REQUIRED", status=503):
    if not condition:
        raise DomainError(code, "缺本次候选实际准备、共同消费或完整保存材料。", status)


def reviewed_prepared_candidate(phase):
    """Actual server preview material; no new IO or authorization is inferred."""
    review = preparation.reviewed_candidate(phase)
    _require(isinstance(review, dict) and "operation" not in review)
    return {"operation": OPERATION, **review}


def _product(s, ctx, command, product):
    _require(isinstance(product, Product), "CANDIDATE_ACTUAL_PRODUCT_REQUIRED")
    state = inspect(product)
    _require(
        state.persistent is True
        and state.session is s
        and not state.deleted
        and product not in s.deleted
        and not {"id", "tenant_id", "revision"} & state.unloaded,
        "CANDIDATE_LOADED_PRODUCT_REQUIRED",
    )
    _require(
        (product.id, product.tenant_id) == (command.product_id, ctx.tenant_id),
        "FORBIDDEN_SCOPE",
        403,
    )
    _require(
        type(product.revision) is int and product.revision == command.expected_revision,
        "VERSION_CONFLICT",
        409,
    )
    return (product.id, product.tenant_id, product.revision)


def _binding(s, ctx, command, product, payload, phase, module):
    _require(
        isinstance(ctx, Context)
        and isinstance(command, Command)
        and ctx.actor_id == ctx.requester_id
        and ctx.run_id is None
        and command.operation == OPERATION,
        "FORBIDDEN_SCOPE",
        403,
    )
    checked = commands._payload(payload)
    _require(
        commands._payload(command.payload) == checked
        and callable(getattr(module, "semantic", None))
        and module.semantic(checked) == commands.semantic(checked),
        "CANDIDATE_ACTUAL_SEMANTIC_REQUIRED",
    )
    review = reviewed_prepared_candidate(phase)  # Reject unregistered/copy DTO phases.
    _require(
        phase.session is s
        and phase.payload_semantic == semantic(checked)
        and phase.binding.basis.scope.tenant_id == ctx.tenant_id
        and phase.binding.basis.scope.product_id == command.product_id
        and anchor.canonical_reads(command.source_read_set)
        == anchor.canonical_reads(phase.required_source_read_set),
        "CANDIDATE_COMMAND_MATERIAL_MISMATCH",
    )
    commands.check_candidate_request(
        checked, phase.binding, current_issue_revision=phase.current_issue_revision
    )
    basis, origin = phase.binding.basis, phase.anchor.origin
    _require(
        (
            basis.scope,
            basis.issue_id,
            basis.issue_version_id,
            basis.issue_revision,
            basis.capa_id,
            basis.purpose,
            basis.nature,
        )
        == (
            origin.scope,
            origin.issue_id,
            origin.ref.id,
            origin.ref.revision,
            origin.issue.capa.id,
            origin.purpose,
            origin.nature,
        ),
        "CANDIDATE_ORIGIN_MATERIAL_MISMATCH",
    )
    _require(
        phase.inspection.binding == phase.binding
        and phase.inspection.candidate_ref is None
        and phase.inspection.required_source_read_set == phase.required_source_read_set
        and phase.owner_id == phase.anchor.origin.owner_id == phase.binding.basis.owner_id
        and phase.visibility == phase.anchor.origin.visibility == phase.binding.basis.visibility
        and checked.visibility == phase.visibility,
        "CANDIDATE_SOURCE_AUDIENCE_MISMATCH",
    )
    anchor.source_closure(phase.sources, phase.required_source_read_set, phase.raw_source_basis)
    _require(
        phase.inspection.source_basis_sha256 == digest(phase.raw_source_basis)
        and phase.inspection.inspection_sha256
        == digest(
            phase.inspection.model_dump(mode="json", exclude={"inspection_sha256", "candidate_ref"})
        ),
        "CANDIDATE_INSPECTION_MATERIAL_MISMATCH",
    )
    return (
        digest(vars(ctx)),
        digest(command.model_dump(mode="json")),  # Original key/token/readset order included.
        semantic(checked),
        _product(s, ctx, command, product),
        digest(review),
    )


def _reviewed_proof(proof, phase, review):
    # require_live already established the actual persistent Confirmation and
    # its original immutable fields. This is the narrow owner-material check.
    _require(
        isinstance(proof.snapshot, dict) and isinstance(proof.snapshot.get("stable_anchor"), dict),
        "INTEGRATION_REQUIRED",
    )
    _require(
        proof.snapshot["stable_anchor"] == phase.anchor.model_dump(mode="json"),
        # A later independently read anchor cannot substitute the real original
        # preview anchor. Root must restore that original from this persistent
        # proof through a trusted owner; that public seam is not implemented here.
        "INTEGRATION_REQUIRED",
    )
    _require(proof.snapshot == review, "CANDIDATE_REVIEW_MATERIAL_CHANGED", 409)


def _live(s, ctx, command, payload, module, proof, host, binding, marker):
    _require(type(host) is ConsumptionHost, "FACT_ACTUAL_CONSUMPTION_HOST_REQUIRED")
    live = host.require_live(
        s, ctx, command, payload, module, proof, binding=binding, marker=marker
    )
    _require(type(live) is LiveConsumption and live is marker and live.tier == TIER)
    expected = consumption._material(ctx, command, payload, module)
    _require(
        (
            live.proof_id,
            live.proof_revision,
            live.expires_at,
            live.token_sha256,
            live.material_sha256,
            live.read_set_sha256,
            live.common_intent_sha256,
        )
        == (
            proof.id,
            proof.revision,
            proof.expires_at,
            expected[5],
            expected[2],
            expected[4],
            expected[3],
        ),
        "FACT_CONSUMPTION_MATERIAL_CHANGED",
    )
    return live


def apply_prepared_candidate(
    s,
    ctx,
    command,
    product,
    payload,
    phase,
    *,
    consumption_host,
    module,
    proof,
    consumption_binding,
    consumption_marker,
):
    """Append one immutable indeterminate candidate from actual server material.

    Only for a new write after shared dedup and actual confirmation consumption.
    Shared key/semantic replay must retain its own current guards and old Receipt;
    it never enters this phase or consumes a proof again.
    """
    uow = guards._uow(s)
    try:
        reviewed_prepared_candidate(phase)
    except BaseException:
        # A known actual phase is one attempt even if a nested field changed.
        # The public invalidator rejects copied/unregistered DTOs without any
        # registry effect; preserve the original material rejection in that case.
        try:
            preparation.invalidate_prepared_candidate(phase)
        except DomainError:
            pass
        raise
    try:
        # Only the actual host's original binding/marker can enter this attempt.
        live = _live(
            s,
            ctx,
            command,
            payload,
            module,
            proof,
            consumption_host,
            consumption_binding,
            consumption_marker,
        )
        live_fingerprint = digest(vars(live))
        before = _binding(s, ctx, command, product, payload, phase, module)
        with s.no_autoflush:
            _reviewed_proof(proof, phase, reviewed_prepared_candidate(phase))
            # Independent actual all-owner/bytes/source/policy/professional IO.
            # Returns the FIRST actual phase/anchor, never a re-sealed new proof.
            _require(
                preparation.require_prepared_candidate(s, ctx, command.product_id, payload, phase)
                is phase,
                "CANDIDATE_PREPARED_OWNER_REQUIRED",
            )
            _require(
                _binding(s, ctx, command, product, payload, phase, module) == before,
                "CANDIDATE_WRITE_MATERIAL_CHANGED",
                409,
            )
            _reviewed_proof(proof, phase, reviewed_prepared_candidate(phase))
            # Build independent raw row data before the final proof/clock guard;
            # no live DTO nested mapping may change saved material afterwards.
            basis = phase.binding.basis
            values = dict(
                id=uuid4(),
                tenant_id=ctx.tenant_id,
                product_id=command.product_id,
                project_id=basis.scope.project_id,
                issue_id=basis.issue_id,
                issue_version_id=basis.issue_version_id,
                issue_revision=basis.issue_revision,
                capa_id=basis.capa_id,
                owner_id=phase.owner_id,
                writer_id=ctx.actor_id,
                visibility=phase.visibility,
                purpose=basis.purpose,
                nature=basis.nature,
                revision=1,
                basis_snapshot=basis.model_dump(mode="json"),
                basis_sha256=basis.basis_sha256,
                sources=[anchor.json_value(v) for v in phase.sources],
                required_source_read_set=[
                    anchor.json_value(v) for v in phase.required_source_read_set
                ],
                source_basis={
                    "artifact_sources": deepcopy(phase.raw_source_basis),
                    "authority": deepcopy(phase.authority_snapshot),
                    "policy": deepcopy(phase.policy_snapshot),
                },
                input_snapshot={
                    "semantic": deepcopy(before[2]),
                    "shared_proof": {"id": str(live.proof_id), "tier": TIER},
                    "proof_consumed_at": live.consumed_at.isoformat(),
                    "stable_anchor": phase.anchor.model_dump(mode="json"),
                },
                intent_digest=live.common_intent_sha256,
                reason=commands._payload(payload).reason,
                remediation_link_id=phase.binding.remediation_link_refs[0].id
                if len(phase.binding.remediation_link_refs) == 1
                else None,
                candidate_binding=phase.binding.model_dump(mode="json"),
                binding_sha256=digest(phase.binding.model_dump(mode="json")),
                candidate_snapshot=phase.inspection.model_dump(mode="json"),
                inspection_sha256=phase.inspection.inspection_sha256,
                status="candidate",
                result="indeterminate",
                applicable=None,
                independently_verified=None,
                observation_complete=None,
            )
            live_after = _live(
                s,
                ctx,
                command,
                payload,
                module,
                proof,
                consumption_host,
                consumption_binding,
                consumption_marker,
            )
            _require(
                live_after is live and digest(vars(live_after)) == live_fingerprint,
                "FACT_ACTUAL_FALSE_TRUE_REQUIRED",
            )
            saved_at = datetime.now(UTC)
            preparation.require_prepared_candidate_clock(
                s, ctx, command.product_id, payload, phase, saved_at
            )
            _require(
                live.consumed_at <= saved_at < live.expires_at, "FACT_CONSUMPTION_CLOCK_INVALID"
            )
            guards._same_uow(s, uow, ctx, before[0])
            values["created_at"] = saved_at
            subject = CapaVerificationEvidence(**values)
            hashes = CandidateReceiptHashes(
                candidate_binding_sha256=subject.binding_sha256,
                inspection_sha256=subject.inspection_sha256,
            )
            # Nonmapped delivery property intentionally used by actual common
            # append_receipt. It is not a column, a fake Receipt or full row SHA.
            subject.action_result = hashes.model_dump(mode="json")
    finally:
        # Successful preparation is a single write attempt, even if owner IO,
        # proof expiry or later s.add fails. Never reuse it across retry/UOW.
        preparation.invalidate_prepared_candidate(phase)
    s.add(subject)
    return subject, SUBJECT, subject.visibility
