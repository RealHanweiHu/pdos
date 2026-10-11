"""Unregistered Rule/Observation/Review material and same-UOW host protocol.

This module neither publishes facts nor constructs VerificationEvidence. Hashes,
saved conclusions, participant lists and structural receipts are input material.
Only explicitly installed real owner callbacks may attest current source,
professional, participant, applicability, observation and transaction facts.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue, model_validator
from sqlalchemy.orm import Session, SessionTransaction

from pdos_next.domain.capa_verification.schemas import ActionBinding, FailurePairMapping
from pdos_next.domain.quality_issues.rules import digest
from pdos_next.errors import DomainError
from pdos_next.schemas.quality_issues.contracts import FailureRef
from pdos_next.schemas.verification.contracts import EventTime, Scope, SourceRef

from .anchor import (
    SourceSafety,
    StableCapaAnchor,
    canonical_basis,
    canonical_reads,
    canonical_sources,
    json_value,
    source_closure,
)
from .paired import (
    Closed,
    FixedRef,
    Missing,
    PairBinding,
    PairedMaterial,
    Revision,
    Sha256,
    SourceRead,
    StructuralPairProof,
    Text,
    verify_paired_material,
)

Nature = Literal["real", "synthetic"]
Applicability = Literal["applicable", "not_applicable", "unknown"]
Count = Annotated[int, Field(strict=True, ge=1)]


class FactOperations(Closed):
    """Host injects actual registry names; no names or authority default here."""

    rule_import: Text
    rule_tier: Literal["host_import"]
    rule_event: Text
    rule_subject_type: Text
    observation: Text
    observation_tier: Literal["T1"]
    observation_event: Text
    observation_subject_type: Text
    review: Text
    review_tier: Literal["T2"]
    review_event: Text
    review_subject_type: Text

    @model_validator(mode="after")
    def distinct(self):
        if len({self.rule_import, self.observation, self.review}) != 3:
            raise ValueError("Fact operations must be distinct actual registry entries")
        return self


class FactRef(FixedRef):
    sha256: Sha256


class IssuerRef(Closed):
    key: Text
    version: Text
    epoch: Revision
    nature: Nature


class AuditBinding(Closed):
    id: UUID
    receipt_id: UUID
    actor_id: UUID
    operation: Text


class OutboxBinding(Closed):
    id: UUID
    receipt_id: UUID
    correlation_id: UUID
    effect: Text


class FactAtom(Closed):
    """Saved group, NOT evidence of same-UOW consumption without host callback."""

    scope: Scope
    operation: Text
    tier: Literal["host_import", "T1", "T2"]
    fact: FixedRef
    actor_id: UUID
    requester_id: UUID
    actor_kind: Literal["human"]
    command_id: UUID
    receipt_id: UUID
    receipt_subject: FixedRef
    receipt_subject_type: Text
    receipt_operation: Text
    receipt_actor_id: UUID
    payload_sha256: Sha256
    read_set_sha256: Sha256
    proof_id: UUID | None
    invocation_decision_id: UUID | None
    token_sha256: Sha256 | None
    material_sha256: Sha256 | None
    consumed_at: AwareDatetime | None
    transaction_proof_id: UUID
    transaction_proof_sha256: Sha256
    audit: AuditBinding
    outbox: OutboxBinding
    received_at: AwareDatetime

    @model_validator(mode="after")
    def group(self):
        if (
            self.actor_id != self.requester_id
            or self.receipt_actor_id != self.actor_id
            or self.receipt_operation != self.operation
            or self.receipt_subject != self.fact
            or self.audit.receipt_id != self.receipt_id
            or self.audit.actor_id != self.actor_id
            or self.audit.operation != self.operation
            or self.outbox.receipt_id != self.receipt_id
            or self.outbox.correlation_id != self.command_id
        ):
            raise ValueError("Exact named Receipt/Audit/Outbox group is required")
        proof = (self.proof_id, self.token_sha256, self.material_sha256, self.consumed_at)
        if self.tier == "host_import":
            if any(v is not None for v in (*proof, self.invocation_decision_id)):
                raise ValueError("Trusted publication is not a fabricated public approval")
        elif any(v is None for v in proof):
            raise ValueError("Saved T1/T2 needs actual consumed proof material")
        elif self.tier == "T2" and self.invocation_decision_id != self.proof_id:
            raise ValueError("T2 actual proof UUID must equal Invocation.decision_id")
        elif self.tier == "T1" and self.invocation_decision_id is not None:
            raise ValueError("T1 cannot masquerade as a named T2 decision")
        if self.consumed_at and self.consumed_at > self.received_at:
            raise ValueError("Consumption cannot postdate the actual saved atom")
        return self


class FactBase(Closed):
    ref: FactRef
    previous: FactRef | None
    scope: Scope
    issue_id: UUID
    capa_id: UUID
    purpose: Text
    anchor_sha256: Sha256
    requirement_sha256: Sha256
    nature: Nature
    owner_id: UUID
    visibility: Literal["private", "category", "audience"]
    created_at: AwareDatetime
    sources: tuple[SourceRef, ...] = Field(min_length=1)
    required_source_read_set: tuple[SourceRead, ...] = Field(min_length=1)
    source_basis: tuple[SourceSafety, ...] = Field(min_length=1)
    provenance: FactAtom

    @model_validator(mode="after")
    def exact(self):
        if self.purpose != self.purpose.strip():
            raise ValueError("Purpose preserves the exact server string")
        if self.previous is None and self.ref.revision != 1:
            raise ValueError("First version must be v1")
        if self.previous and (
            self.previous.id == self.ref.id or self.previous.revision + 1 != self.ref.revision
        ):
            raise ValueError("Successor has a distinct immutable row and consecutive version")
        source_closure(self.sources, self.required_source_read_set, self.source_basis)
        if self.visibility == "category" and any(
            b.visibility == "private" for b in self.source_basis
        ):
            raise ValueError("Shared fact cannot enlarge private source audience")
        p = self.provenance
        if (
            p.scope != self.scope
            or p.fact != FixedRef(id=self.ref.id, revision=self.ref.revision)
            or p.payload_sha256 != fact_payload_sha256(self)
            or p.read_set_sha256
            != digest([json_value(r) for r in canonical_reads(self.required_source_read_set)])
            or p.received_at != self.created_at
            or self.ref.sha256 != fact_sha256(self)
        ):
            raise ValueError("Fact digest/provenance must bind all fixed material and sources")
        return self


class ObservationTarget(Closed):
    key: Text
    kind: Literal["sample", "lot", "population"]
    ref: FixedRef
    actual_configuration: FixedRef | None
    identity_sources: tuple[SourceRef, ...] = Field(min_length=1)


class SamplingRequirement(Closed):
    targets: tuple[ObservationTarget, ...] = Field(min_length=1)
    minimum_records: Count
    sampling_method: SourceRef
    acceptance: SourceRef
    observation_from: AwareDatetime
    observation_until: AwareDatetime
    require_named_review: Literal[True] = True
    require_run_review: Annotated[bool, Field(strict=True)]
    require_disposition: Annotated[bool, Field(strict=True)]

    @model_validator(mode="after")
    def interval(self):
        if self.observation_until <= self.observation_from:
            raise ValueError("Rule observation interval must increase")
        if len({t.key for t in self.targets}) != len(self.targets):
            raise ValueError("Observation target keys are unique actual identities")
        return self


class RuleVersion(FactBase):
    kind: Literal["rule"] = "rule"
    issuer: IssuerRef
    policy_ref: SourceRef
    policy_sha256: Sha256
    failures: tuple[FailureRef, ...] = Field(min_length=1)
    actions: tuple[ActionBinding, ...] = Field(min_length=1)
    method: SourceRef
    criterion: SourceRef
    sampling: SamplingRequirement
    # Explicit published policy material; no parsing acceptance text into limits.
    rule_material: dict[str, JsonValue]
    independence_material: dict[str, JsonValue]
    valid_from: AwareDatetime
    valid_until: AwareDatetime

    @model_validator(mode="after")
    def validity(self):
        if self.valid_until <= self.valid_from or self.issuer.nature != self.nature:
            raise ValueError("Publication has a fixed valid interval and exact issuer nature")
        return self


class ObservationRecord(Closed):
    target_key: Text
    occurred_at: AwareDatetime
    original_timezone: Text
    sources: tuple[SourceRef, ...] = Field(min_length=1)
    raw_material: dict[str, JsonValue]
    missing_fields: tuple[Text, ...]

    @model_validator(mode="after")
    def timezone(self):
        # Reuse actual EventTime's IANA validation without inventing an event clock.
        EventTime(
            occurred_at=self.occurred_at,
            original_timezone=self.original_timezone,
            source=self.sources[0],
        )
        return self


class ObservationVersion(FactBase):
    kind: Literal["observation"] = "observation"
    rule: FactRef
    issuer: IssuerRef
    targets: tuple[ObservationTarget, ...] = Field(min_length=1)
    executor_id: UUID
    observed_from: AwareDatetime
    observed_until: AwareDatetime
    at: EventTime
    records: tuple[ObservationRecord, ...] = Field(min_length=1)
    coverage_sources: tuple[SourceRef, ...] = Field(min_length=1)
    # An original owner supplies sampling evidence. No complete/result boolean.
    sampling_material: dict[str, JsonValue]

    @model_validator(mode="after")
    def interval(self):
        if not self.observed_from < self.observed_until <= self.at.occurred_at <= self.created_at:
            raise ValueError("Observation clocks must be actual, increasing and already received")
        if self.executor_id != self.provenance.actor_id or self.issuer.nature != self.nature:
            raise ValueError("Named observation executor and issuer nature are exact")
        keys = [t.key for t in self.targets]
        if len(set(keys)) != len(keys) or any(
            r.target_key not in keys
            or not self.observed_from <= r.occurred_at <= self.observed_until
            for r in self.records
        ):
            raise ValueError("Records belong to exact observed targets and actual interval")
        return self


class Participant(Closed):
    id: UUID
    roles: tuple[
        Literal[
            "original_test",
            "root_cause",
            "containment",
            "completion",
            "new_test",
            "measurement",
            "observation",
        ],
        ...,
    ] = Field(min_length=1)
    owner_sources: tuple[SourceRef, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def roles_unique(self):
        if len(self.roles) != len(set(self.roles)):
            raise ValueError("Participant roles must be distinct owner facts")
        return self


class ActionFulfillment(Closed):
    action: ActionBinding
    classification: Literal["investigation", "formal_change", "unknown"]
    conclusion: Applicability
    reason: Text
    owner_refs: tuple[SourceRef, ...]
    # Complete actual owner material stays bound; existence does not imply fulfillment.
    owner_material: dict[str, JsonValue]


class PairApplicability(Closed):
    mapping: FailurePairMapping
    method: SourceRef | None
    criterion: SourceRef | None
    conclusion: Applicability
    reason: Text
    sources: tuple[SourceRef, ...] = Field(min_length=1)


class NamedReview(FactBase):
    kind: Literal["review"] = "review"
    candidate: FactRef
    candidate_sha256: Sha256
    rule: FactRef
    observations: tuple[FactRef, ...] = Field(min_length=1)
    reviewer_id: UUID
    at: EventTime
    pair_applicability: tuple[PairApplicability, ...] = Field(min_length=1)
    action_fulfillment: tuple[ActionFulfillment, ...] = Field(min_length=1)
    participants: tuple[Participant, ...] = Field(min_length=1)
    participant_owner_material: dict[str, JsonValue]
    conclusion: Applicability
    reason: Text
    authority_snapshot: dict[str, JsonValue]
    policy_snapshot: dict[str, JsonValue]
    valid_until: AwareDatetime | None = None

    @model_validator(mode="after")
    def reviewer(self):
        if self.reviewer_id != self.provenance.actor_id or self.at.occurred_at > self.created_at:
            raise ValueError("Review retains actual named human and original received clock")
        if len({p.id for p in self.participants}) != len(self.participants):
            raise ValueError("Participants have distinct owner identities")
        if self.candidate.sha256 != self.candidate_sha256:
            raise ValueError("Fixed candidate material hash must match its actual version ref")
        if self.valid_until is not None and self.valid_until <= self.created_at:
            raise ValueError("Saved review needs a fixed positive validity interval")
        return self


def fact_payload_sha256(value):
    """Pure canonical payload; no actual fact publication or provenance is issued."""
    raw = json_value(value)
    raw.pop("provenance", None)
    raw["ref"].pop("sha256", None)
    return digest(raw)


def fact_sha256(value):
    raw = json_value(value)
    raw["ref"].pop("sha256", None)
    return digest(raw)


class SavedPair(Closed):
    binding: PairBinding
    material: PairedMaterial


class FactMaterial(Closed):
    anchor: StableCapaAnchor
    rule: RuleVersion
    observations: tuple[ObservationVersion, ...] = Field(min_length=1)
    review: NamedReview
    pairs: tuple[SavedPair, ...] = Field(min_length=1)


class StructuralFactProof(Closed):
    structural_only: Literal[True] = True
    scope: Scope
    issue_id: UUID
    capa_id: UUID
    purpose: Text
    nature: Nature
    anchor_sha256: Sha256
    review: FactRef
    rule: FactRef
    observations: tuple[FactRef, ...]
    pair_proofs: tuple[StructuralPairProof, ...]
    required_source_read_set: tuple[SourceRead, ...] = Field(min_length=1)
    source_basis: tuple[SourceSafety, ...] = Field(min_length=1)
    material_sha256: Sha256


class FactInspection(Closed):
    proof: StructuralFactProof | None = None
    missing: tuple[Missing, ...] = ()


def _require(condition, code, detail):
    if not condition:
        raise DomainError(code, detail, 409)


def _instant(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise DomainError("INVALID_TIME", "Actual aware server clock is required.", 422)
    return value.astimezone(UTC)


def _all_source_refs(value):
    if isinstance(value, dict):
        if {"id", "revision", "kind", "position"} <= value.keys():
            return [SourceRef.model_validate(value)]
        if {"artifact_id", "expected_revision", "line", "quote"} <= value.keys():
            from hashlib import sha256

            return [
                SourceRef(
                    id=value["artifact_id"],
                    revision=value["expected_revision"],
                    kind="artifact",
                    position=f"line:{value['line']};quote_sha256:{sha256(value['quote'].encode()).hexdigest()}",
                )
            ]
        return [r for child in value.values() for r in _all_source_refs(child)]
    if isinstance(value, (list, tuple)):
        return [r for child in value for r in _all_source_refs(child)]
    return []


def _action_bindings(anchor):
    return tuple(
        ActionBinding(
            action_id=a.id,
            executor_id=a.executor_id,
            action_sha256=digest(a.model_dump(mode="json", exclude={"completion"})),
            completion_sha256=digest(json_value(a.completion)),
            completed_at=a.completion.at,
        )
        for a in anchor.origin.issue.capa.actions
    )


def inspect_fact_material(material, operations, *, at) -> FactInspection:
    """Structural relationships only; never independent/qualified/effective evidence."""
    if operations is None:
        return FactInspection(
            missing=(
                Missing(
                    code="FACT_REGISTRY_MISSING",
                    detail="Host must supply registered exact operation names and tiers.",
                ),
            )
        )
    ops = FactOperations.model_validate(json_value(operations))
    m = FactMaterial.model_validate(json_value(material))
    at = _instant(at)
    a, rule, review = m.anchor, m.rule, m.review
    origin = a.origin
    actions = _action_bindings(a)
    required = digest(json_value(origin.issue.capa.requirement))
    missing = []
    for f in (rule, *m.observations, review):
        _require(
            (
                f.scope,
                f.issue_id,
                f.capa_id,
                f.purpose,
                f.anchor_sha256,
                f.requirement_sha256,
                f.nature,
            )
            == (
                origin.scope,
                origin.issue_id,
                origin.issue.capa.id,
                origin.purpose,
                a.anchor_sha256,
                required,
                origin.nature,
            ),
            "FACT_SCOPE_MISMATCH",
            "Fact binds exact scope, CAPA, purpose, nature, anchor and requirement.",
        )
        _require(
            f.created_at <= at,
            "FACT_TIME_INVALID",
            "Saved fact cannot have a future received clock.",
        )
        if origin.visibility == "private":
            _require(
                f.visibility == "private" and f.owner_id == origin.owner_id,
                "FORBIDDEN_SCOPE",
                "Private original investigation cannot be widened or assigned to a peer.",
            )
        name, tier = {
            "rule": (ops.rule_import, "host_import"),
            "observation": (ops.observation, "T1"),
            "review": (ops.review, "T2"),
        }[f.kind]
        _require(
            (f.provenance.operation, f.provenance.tier) == (name, tier),
            "FACT_OPERATION_MISMATCH",
            "Actual published/saved operation and tier must match host registry exactly.",
        )
        stem = "rule" if f.kind == "rule" else f.kind
        _require(
            f.provenance.outbox.effect == getattr(ops, stem + "_event")
            and f.provenance.receipt_subject_type == getattr(ops, stem + "_subject_type"),
            "FACT_OPERATION_MISMATCH",
            "Saved effect/subject family must match exact host registry.",
        )
        sources = canonical_sources(_all_source_refs(json_value(f)))
        _require(
            set(sources) <= set(canonical_sources(f.sources)),
            "MISSING_REQUIRED_EVIDENCE",
            "Every nested method, clock, target and participant ref remains in sources.",
        )
    atoms = [v.provenance for v in (rule, *m.observations, review)]
    _require(
        len({p.command_id for p in atoms}) == len(atoms)
        and len({p.receipt_id for p in atoms}) == len(atoms)
        and len({p.proof_id for p in atoms if p.proof_id is not None})
        == sum(p.proof_id is not None for p in atoms),
        "FACT_PROVENANCE_MISMATCH",
        "Distinct publications, observations and review need distinct commands/receipts/proofs.",
    )
    _require(
        rule.failures == origin.issue.failures and rule.actions == actions,
        "FACT_FIXED_MATERIAL_CHANGED",
        "Rule retains every exact original failure and completed action, without extras.",
    )
    _require(
        review.rule == rule.ref and tuple(o.ref for o in m.observations) == review.observations,
        "FACT_REFERENCE_MISMATCH",
        "Review must retain the exact Rule and ordered Observation versions.",
    )
    _require(
        len({o.ref.id for o in m.observations}) == len(m.observations),
        "FACT_REFERENCE_MISMATCH",
        "Duplicate observations cannot pretend to complete coverage.",
    )
    _require(
        rule.sampling.observation_until >= origin.issue.capa.requirement.observation_until,
        "FACT_TIME_INVALID",
        "Published window cannot shorten actual CAPA requirement.",
    )
    earliest = max(v.completed_at.occurred_at for v in actions)
    _require(
        rule.sampling.observation_from >= earliest,
        "FACT_TIME_INVALID",
        "Observation requirement cannot precede actual completed actions.",
    )
    for observation in m.observations:
        _require(
            observation.rule == rule.ref and observation.targets == rule.sampling.targets,
            "FACT_REFERENCE_MISMATCH",
            "Observation targets/rule cannot be client relabelled.",
        )
        _require(
            observation.observed_from >= earliest,
            "FACT_TIME_INVALID",
            "Actual observation cannot predate completed actions.",
        )
        if (
            observation.observed_from > rule.sampling.observation_from
            or observation.observed_until < rule.sampling.observation_until
        ):
            missing.append(
                Missing(
                    code="OBSERVATION_WINDOW_INCOMPLETE",
                    detail="Actual observation does not cover the published full interval.",
                )
            )
        if (
            len(observation.records) < rule.sampling.minimum_records
            or {r.target_key for r in observation.records} != {t.key for t in rule.sampling.targets}
            or any(r.missing_fields for r in observation.records)
        ):
            missing.append(
                Missing(
                    code="OBSERVATION_RECORDS_INCOMPLETE",
                    detail="Actual records have explicit omissions; owner must verify sampling.",
                )
            )
    _require(
        max(o.at.occurred_at for o in m.observations) <= review.at.occurred_at,
        "FACT_TIME_INVALID",
        "Named review cannot predate actual observation report.",
    )
    ids = [p.mapping.failure_id for p in review.pair_applicability]
    _require(
        len(set(ids)) == len(ids) and set(ids) == {f.identity for f in rule.failures},
        "FACT_FAILURE_COVERAGE_MISMATCH",
        "Review maps every exact original failure once, with no omitted or extra failure.",
    )
    _require(
        tuple(v.action for v in review.action_fulfillment) == actions,
        "FACT_ACTION_COVERAGE_MISMATCH",
        "Fulfillment retains the complete original action and completion mapping.",
    )
    if review.conclusion != "applicable" or any(
        v.conclusion != "applicable" for v in review.pair_applicability
    ):
        missing.append(
            Missing(
                code="APPLICABILITY_UNCONFIRMED",
                detail="Unknown/not-applicable saved review remains a missing applicability fact.",
            )
        )
    if any(
        v.conclusion != "applicable"
        or v.classification == "unknown"
        or not v.owner_refs
        or not v.owner_material
        for v in review.action_fulfillment
    ):
        missing.append(
            Missing(
                code="ACTION_FULFILLMENT_UNCONFIRMED",
                detail="Action existence/completion is not actual fulfillment classification.",
            )
        )
    if (
        not rule.valid_from <= at < rule.valid_until
        or not review.created_at <= at
        or (review.valid_until is not None and at >= review.valid_until)
    ):
        missing.append(
            Missing(
                code="FACT_EXPIRED",
                detail="Current rule/review must be valid at the final real server instant.",
            )
        )
    pair_proofs = []
    mapped_failures = set()
    for saved in m.pairs:
        _require(
            saved.binding.scope == origin.scope and saved.binding.purpose == origin.purpose,
            "FACT_SCOPE_MISMATCH",
            "Paired owner input cannot substitute scope or purpose.",
        )
        checked = verify_paired_material(saved.binding, saved.material, at=at)
        missing.extend(checked.missing)
        if checked.proof is not None:
            pair_proofs.append(checked.proof)
        run = saved.material.run_after
        _require(
            run.snapshot.id not in {f.run.id for f in rule.failures},
            "ORIGINAL_FAILURE_RUN_FORBIDDEN",
            "New verification cannot reuse an original failing logical Run.",
        )
        _require(
            run.snapshot.actual_start is not None
            and run.snapshot.actual_start.occurred_at >= earliest
            and all(
                v.observed_at is None or v.observed_at >= earliest
                for v in run.snapshot.measurements
            ),
            "FACT_TIME_INVALID",
            "Actual new execution/observations cannot predate completed actions.",
        )
        _require(
            run.created_at <= review.created_at
            and (
                run.snapshot.final_result is None
                or run.snapshot.final_result.occurred_at <= review.at.occurred_at
            ),
            "FACT_TIME_INVALID",
            "Named verification review cannot predate its actual saved new output.",
        )
        if (
            run.snapshot.status not in {"results_pending", "reviewed", "disposed"}
            or (rule.sampling.require_disposition and run.snapshot.status != "disposed")
            or (
                rule.sampling.require_run_review
                and run.snapshot.status not in {"reviewed", "disposed"}
            )
        ):
            missing.append(
                Missing(
                    code="NEW_RUN_NOT_FINAL",
                    detail="Real new Run must meet published final review/disposition stage.",
                )
            )
        if run.snapshot.result == "indeterminate":
            missing.append(
                Missing(
                    code="NEW_RUN_RESULT_UNKNOWN",
                    detail="Actual new result has unknown original values or coverage.",
                )
            )
        for p in review.pair_applicability:
            v = p.mapping
            if v.run.id != run.ref.id:
                continue
            sample = next((s for s in run.snapshot.samples if s.id == v.sample_id), None)
            item = next((i for i in run.snapshot.items if i.id == v.item_id), None)
            measurement = next(
                (t for t in run.snapshot.measurements if t.id == v.measurement_id), None
            )
            projection = saved.material.projection
            _require(
                v.run.revision == run.ref.revision
                and sample is not None
                and item is not None
                and (
                    sample.revision,
                    sample.actual_configuration.id,
                    sample.actual_configuration.revision,
                )
                == (v.sample_revision, v.actual_configuration_id, v.actual_configuration_revision)
                and measurement is not None
                and (measurement.coverage.sample_id, measurement.coverage.item_id)
                == (v.sample_id, v.item_id)
                and projection is not None
                and projection.ref.id == v.projection_id
                and p.method == item.method
                and p.criterion == (item.criterion.source if item.criterion else None),
                "FACT_PAIR_MAPPING_MISMATCH",
                "Pair/config/method/criterion/measurement/projection bind real saved rows.",
            )
            mapped_failures.add(v.failure_id)
    _require(
        mapped_failures == set(ids),
        "FACT_PAIR_MAPPING_MISMATCH",
        "Every failure mapping needs an exact actually saved paired output.",
    )
    _require(
        len({s.material.run_after.ref.id for s in m.pairs}) == len(m.pairs),
        "FACT_PAIR_MAPPING_MISMATCH",
        "Paired rows are unique, never duplicated coverage.",
    )
    groups = (
        a.origin_required_source_read_set,
        rule.required_source_read_set,
        *(o.required_source_read_set for o in m.observations),
        review.required_source_read_set,
        *(p.required_source_read_set for p in pair_proofs),
    )
    reads = canonical_reads(r for group in groups for r in group)
    basis_by_id = {}
    for entry in (
        *a.origin_source_basis,
        *rule.source_basis,
        *(b for o in m.observations for b in o.source_basis),
        *review.source_basis,
    ):
        _require(
            entry.id not in basis_by_id or basis_by_id[entry.id] == entry,
            "SOURCE_STALE",
            "All fixed sources retain exact current safety/hash/owner/security epochs.",
        )
        basis_by_id[entry.id] = entry
    basis = canonical_basis(basis_by_id.values(), reads)
    return FactInspection(
        proof=StructuralFactProof(
            scope=origin.scope,
            issue_id=origin.issue_id,
            capa_id=origin.issue.capa.id,
            purpose=origin.purpose,
            nature=origin.nature,
            anchor_sha256=a.anchor_sha256,
            review=review.ref,
            rule=rule.ref,
            observations=review.observations,
            pair_proofs=tuple(pair_proofs),
            required_source_read_set=tuple(SourceRead.model_validate(json_value(r)) for r in reads),
            source_basis=basis,
            material_sha256=digest(json_value(m)),
        ),
        missing=tuple(missing),
    )


GateKind = Literal[
    "registry", "sources", "participants", "applicability", "observation", "provenance", "authority"
]
GATES = (
    "registry",
    "sources",
    "participants",
    "applicability",
    "observation",
    "provenance",
    "authority",
)


@dataclass(frozen=True)
class HostFactProof:
    """Opaque real reader result, never a caller JSON or a saved consumed boolean.

    A host must independently verify real bytes, source ACL/epochs, named roles,
    actual complete participant owners, Rule applicability/observation and saved
    T1/T2 reciprocal atoms/Invocation IDs. Stamps are not standalone authority.
    """

    issued_by: object
    session: object
    transaction: object
    nested_transaction: object
    scope: Scope
    caller_id: UUID
    material_sha256: str
    kind: GateKind
    basis_sha256: str
    nature: Nature
    checked_at: datetime
    valid_until: datetime | None
    time_constraints: tuple[datetime, ...] = ()


@dataclass(frozen=True)
class FactReadOutcome:
    structure: StructuralFactProof | None
    host_proofs: tuple[HostFactProof, ...]
    missing: tuple[Missing, ...]


class FactReader(Protocol):
    """Actual same-Session owner reader; methods must not commit/create a UOW.

    Each named gate returns a current opaque proof, not the DTO's own claims.
    Independent refresh and a second full gate pass occur after initial owner IO.
    Every later proof must include the complete relevant registry/runtime epochs
    so a later owner's IO cannot revoke an earlier proof without changing stamps.
    Caller permissions/TTL are gate material, not stable CAPA/fact digests.
    """

    def read(self, s, ctx, product_id, review_ref, *, at) -> FactMaterial | None: ...
    def refresh(self, s, ctx, product_id, previous, *, at) -> FactMaterial | None: ...
    def registry(self, s, ctx, product_id, material, operations, *, at) -> HostFactProof | None: ...
    def sources(self, s, ctx, product_id, material, operations, *, at) -> HostFactProof | None: ...
    def participants(
        self, s, ctx, product_id, material, operations, *, at
    ) -> HostFactProof | None: ...
    def applicability(
        self, s, ctx, product_id, material, operations, *, at
    ) -> HostFactProof | None: ...
    def observation(
        self, s, ctx, product_id, material, operations, *, at
    ) -> HostFactProof | None: ...
    def provenance(
        self, s, ctx, product_id, material, operations, *, at
    ) -> HostFactProof | None: ...
    def authority(
        self, s, ctx, product_id, material, operations, *, at
    ) -> HostFactProof | None: ...
    def refresh_proofs(
        self, s, ctx, product_id, material, operations, proofs, *, at
    ) -> tuple[HostFactProof, ...] | None:
        """After ALL owner IO, independently refresh the complete current closure.

        No original bytes cache across phases. Real host must reread current
        source/ACL/safety/issuer/participant/applicability/observation/atom state
        and final all-registry runtime epochs after its own owner IO as well.
        """
        ...


def _uow(s):
    # Identity alone is insufficient: an object placeholder or a closed /
    # partial-rollback SQLAlchemy transaction is not an actual caller UOW.
    # These are in-memory state reads, never connect or begin a transaction.
    if not isinstance(s, Session) or not s.is_active:
        return None, None
    transaction, nested = s.get_transaction(), s.get_nested_transaction()
    if (
        not isinstance(transaction, SessionTransaction)
        or transaction.session is not s
        or not transaction.is_active
        or transaction.nested
        or transaction.parent is not None
    ):
        return None, None
    ancestor, seen = nested, set()
    while ancestor is not None and ancestor is not transaction:
        if (
            not isinstance(ancestor, SessionTransaction)
            or ancestor.session is not s
            or not ancestor.is_active
            or not ancestor.nested
            or id(ancestor) in seen
        ):
            return None, None
        seen.add(id(ancestor))
        ancestor = ancestor.parent
    if nested is not None and ancestor is not transaction:
        return None, None
    return transaction, nested


def _check_uow(s, transaction, nested):
    current, savepoint = _uow(s)
    _require(
        current is transaction and savepoint is nested and current is not None,
        "CALLER_UOW_CHANGED",
        "All IO stays in the same active SQLAlchemy transaction and SAVEPOINT.",
    )


def _gate(reader, s, ctx, structure, gate, kind, transaction, nested, start, at):
    if not isinstance(gate, HostFactProof):
        return Missing(
            code="FACT_OWNER_PROOF_MISSING",
            detail=f"Actual {kind} owner proof is unconfigured or incomplete.",
        )
    _require(
        gate.issued_by is reader
        and gate.session is s
        and gate.transaction is transaction
        and gate.nested_transaction is nested
        and gate.scope == structure.scope
        and gate.caller_id == ctx.requester_id
        and gate.material_sha256 == structure.material_sha256
        and gate.kind == kind
        and gate.nature == structure.nature,
        "FACT_OWNER_PROOF_UNBOUND",
        "Owner proof must bind actual reader/UOW/caller/scope/material/kind/nature.",
    )
    _require(
        isinstance(gate.basis_sha256, str)
        and len(gate.basis_sha256) == 64
        and all(c in "0123456789abcdef" for c in gate.basis_sha256),
        "FACT_OWNER_PROOF_UNBOUND",
        "Real complete owner fingerprint is required.",
    )
    _require(
        start <= _instant(gate.checked_at) <= at
        and (gate.valid_until is None or at < _instant(gate.valid_until))
        and all(at < _instant(value) for value in gate.time_constraints),
        "FACT_OWNER_PROOF_EXPIRED",
        "Qualification/source/owner proof expired or has a future evaluation during IO.",
    )
    return None


def load_verification_facts(
    s,
    ctx,
    product_id,
    review_ref,
    *,
    operations=None,
    reader=None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> FactReadOutcome:
    """Explicit missing by default; structural material never grants effectiveness.

    This is read-only, phase-local and returns no VerificationEvidence or writer.
    The actual host is responsible for legitimate source/participant/policy
    decisions and complete final refresh; the pure wrapper only enforces binding.
    """
    if (
        operations is None
        or reader is None
        or not all(
            callable(getattr(reader, name, None))
            for name in ("read", "refresh", "refresh_proofs", *GATES)
        )
    ):
        return FactReadOutcome(
            None,
            (),
            (
                Missing(
                    code="INTEGRATION_REQUIRED",
                    detail="Exact host registry and all live owner callbacks are required.",
                ),
            ),
        )
    ops = FactOperations.model_validate(json_value(operations))
    selected = FactRef.model_validate(json_value(review_ref))
    transaction, nested = _uow(s)
    if transaction is None:
        return FactReadOutcome(
            None,
            (),
            (
                Missing(
                    code="CALLER_UOW_REQUIRED",
                    detail="Actual active SQLAlchemy caller-owned transaction is required.",
                ),
            ),
        )
    material = reader.read(s, ctx, product_id, selected, at=_instant(clock()))
    baseline = None
    final_proofs = ()
    for phase in range(2):
        _check_uow(s, transaction, nested)
        if material is None:
            return FactReadOutcome(
                None,
                (),
                (
                    Missing(
                        code="FACT_OWNER_MATERIAL_MISSING",
                        detail="Actual persisted fact owner material is missing.",
                    ),
                ),
            )
        material = FactMaterial.model_validate(json_value(material))
        _require(
            material.anchor.origin.scope.tenant_id == ctx.tenant_id
            and material.anchor.origin.scope.product_id == product_id
            and material.review.ref == selected,
            "FACT_SCOPE_MISMATCH",
            "Host cannot substitute selected immutable review/tenant/product.",
        )
        _require(
            all(p.binding.caller_id == ctx.requester_id for p in material.pairs),
            "FACT_SCOPE_MISMATCH",
            "Paired inputs use the actual current consumer, never another owner Context.",
        )
        if material.anchor.origin.visibility == "private":
            _require(
                ctx.requester_id == material.anchor.origin.owner_id,
                "FORBIDDEN_SCOPE",
                "Private origin is owner-only; a peer Grant cannot expand it.",
            )
        checked = inspect_fact_material(material, ops, at=_instant(clock()))
        if checked.missing:
            return FactReadOutcome(checked.proof, (), checked.missing)
        proofs = []
        for name in GATES:
            start = _instant(clock())
            proof = getattr(reader, name)(s, ctx, product_id, material, ops, at=start)
            _check_uow(s, transaction, nested)
            missing = _gate(
                reader,
                s,
                ctx,
                checked.proof,
                proof,
                name,
                transaction,
                nested,
                start,
                _instant(clock()),
            )
            if missing:
                return FactReadOutcome(checked.proof, (), (missing,))
            proofs.append(proof)
        final_proofs = tuple(proofs)
        fingerprint = (
            checked.proof.material_sha256,
            tuple(
                (p.kind, p.basis_sha256, p.valid_until, p.time_constraints) for p in final_proofs
            ),
        )
        if phase:
            _require(
                fingerprint == baseline,
                "SOURCE_STALE",
                "Post-IO current source/owner/authority/registry facts drifted.",
            )
        else:
            baseline = fingerprint
            material = reader.refresh(s, ctx, product_id, material, at=_instant(clock()))
    # A later owner can revoke an earlier proof, even in the second pass. The
    # final narrow live refresh must happen after all of that IO, not merely
    # compare hashes of the already-observed proof objects.
    start = _instant(clock())
    refreshed = reader.refresh_proofs(s, ctx, product_id, material, ops, final_proofs, at=start)
    _check_uow(s, transaction, nested)
    final_at = _instant(clock())
    if not isinstance(refreshed, tuple) or len(refreshed) != len(GATES):
        return FactReadOutcome(
            checked.proof,
            (),
            (
                Missing(
                    code="FACT_OWNER_PROOF_MISSING",
                    detail="Independent post-all-owner-IO current closure is required.",
                ),
            ),
        )
    final_check = inspect_fact_material(material, ops, at=final_at)
    if final_check.missing:
        return FactReadOutcome(final_check.proof, (), final_check.missing)
    for name, proof in zip(GATES, refreshed, strict=True):
        missing = _gate(
            reader, s, ctx, final_check.proof, proof, name, transaction, nested, start, final_at
        )
        if missing:
            return FactReadOutcome(final_check.proof, (), (missing,))
    _require(
        tuple((p.kind, p.basis_sha256, p.valid_until, p.time_constraints) for p in refreshed)
        == tuple((p.kind, p.basis_sha256, p.valid_until, p.time_constraints) for p in final_proofs),
        "SOURCE_STALE",
        "Final current closure changed after a later owner IO.",
    )
    return FactReadOutcome(final_check.proof, refreshed, ())
