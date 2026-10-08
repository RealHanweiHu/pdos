"""Unregistered pure CAPA anchor DTOs; host evidence is required, never self-granted.

Only three EXACT bridge observation paths are excluded from the stable failure
material: result.retained.checked_at, result.retained.execution_window_elapsed,
result.source_basis.runtime_stamp. Their original values remain in the full proof
and full-proof digest. All fixed Run/Start/effects/source/issuer epochs survive.
There is no recursive field-name stripping, DB, source read or Current mutation.
"""

from copy import deepcopy
from datetime import UTC
from typing import Annotated, Literal
from uuid import UUID

from pdos_next.domain.quality_execution.ports import FixedQualityResult
from pdos_next.domain.quality_execution.schemas import Revision, Sha256, SourceRead
from pdos_next.domain.quality_issues.ports import Authority
from pdos_next.domain.quality_issues.rules import digest, failure_ref, issue_sources
from pdos_next.errors import DomainError
from pdos_next.schemas.quality_issues.contracts import FailureRef, Issue
from pdos_next.schemas.verification.contracts import DTO, Scope, SourceRef
from pydantic import AwareDatetime, Field, JsonValue, field_validator, model_validator

Text = Annotated[str, Field(min_length=1, max_length=2000)]
Nature = Literal["real", "synthetic"]


def reject(message, code="RECHECK_REQUIRED"):
    raise DomainError(code, message, 409)


def json_value(value):
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else deepcopy(value)


def canonical_sources(values):
    refs = {}
    for value in values:
        source = SourceRef.model_validate(json_value(value))
        refs[(str(source.id), source.revision, source.kind, source.position)] = source
    return tuple(refs[key] for key in sorted(refs))


def canonical_reads(values):
    refs = {}
    for value in values:
        read = SourceRead.model_validate(json_value(value))
        if read.artifact_id in refs and refs[read.artifact_id] != read.expected_revision:
            reject("One artifact cannot have conflicting source revisions.")
        refs[read.artifact_id] = read.expected_revision
    if not 1 <= len(refs) <= 20:
        reject("Complete source closure requires 1..20 artifacts; never truncate.")
    return tuple(
        SourceRead(artifact_id=k, expected_revision=refs[k]) for k in sorted(refs, key=str)
    )


class VersionRef(DTO):
    id: UUID  # immutable QualityIssueVersion row, not logical Issue UUID
    revision: Revision
    snapshot_sha256: Sha256


class NativeRegistration(DTO):
    receipt_id: UUID
    actor_id: UUID
    requester_id: UUID
    run_id: UUID | None

    @model_validator(mode="after")
    def human_or_run(self):
        if self.run_id is None and self.actor_id != self.requester_id:
            raise ValueError("Native provenance requires exact author/run binding")
        return self


class OriginalSafety(DTO):
    id: UUID
    epoch: Revision
    source_state: Literal["active"]
    disposition: Literal["active"]


class SourceSafety(DTO):
    """Exact existing quality_execution.evidence.source_basis entry shape."""

    id: UUID
    revision: Revision
    hash: Sha256
    status: Literal["active"]
    owner_id: UUID
    visibility: Literal["private", "product"]
    source_kind: Literal["registered_native_text", "uploaded_original"]
    registration: NativeRegistration | None = None
    original: OriginalSafety | None = None

    @model_validator(mode="after")
    def origin(self):
        if self.source_kind == "registered_native_text":
            if self.registration is None or self.original is not None:
                raise ValueError("Native source requires only exact registration provenance")
            if self.registration.requester_id != self.owner_id:
                raise ValueError("Native registration requester must be the original owner")
        elif self.original is None or self.registration is not None:
            raise ValueError("Uploaded source requires only current exact OriginalSafety")
        return self


def canonical_basis(values, reads):
    entries = {}
    for raw in values:
        value = SourceSafety.model_validate(json_value(raw))
        if value.id in entries:
            reject("Duplicate source-basis identity is not a complete closure.")
        entries[value.id] = value
    wanted = {r.artifact_id: r.expected_revision for r in canonical_reads(reads)}
    if {k: v.revision for k, v in entries.items()} != wanted:
        reject("Source safety must cover the full exact read set, no extras or omissions.")
    return tuple(entries[k] for k in sorted(entries, key=str))


def source_closure(sources, reads, basis):
    sources = canonical_sources(sources)
    reads = canonical_reads(reads)
    basis = canonical_basis(basis, reads)
    read_map = {r.artifact_id: r.expected_revision for r in reads}
    for source in sources:
        if source.kind == "artifact" and read_map.get(source.id) != source.revision:
            reject("An exact artifact SourceRef is absent from the complete read set.")
    return sources, reads, basis


class IssueVersionEvidence(DTO):
    ref: VersionRef
    previous_ref: VersionRef | None
    scope: Scope
    issue_id: UUID  # logical identity
    purpose: Text
    owner_id: UUID
    writer_id: UUID
    visibility: Literal["private", "product"]
    nature: Nature
    operation: Text
    domain_intent_sha256: Sha256
    created_at: AwareDatetime
    issue: Issue
    sources: tuple[SourceRef, ...]
    required_source_read_set: tuple[SourceRead, ...] = Field(min_length=1, max_length=20)
    source_basis: tuple[SourceSafety, ...] = Field(min_length=1, max_length=20)
    # Complete original persisted provenance remains opaque, untouched and hashed.
    input_snapshot: dict[str, JsonValue]
    authority_snapshot: dict[str, JsonValue]
    policy_snapshot: dict[str, JsonValue]
    persisted_source_basis: dict[str, JsonValue]

    @field_validator("created_at")
    @classmethod
    def utc(cls, value):
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def bound(self):
        if (self.issue.id, self.issue.revision, self.issue.scope) != (
            self.issue_id,
            self.ref.revision,
            self.scope,
        ) or digest(self.issue.model_dump(mode="json")) != self.ref.snapshot_sha256:
            raise ValueError("Issue version ref must bind the complete exact snapshot")
        audience = (
            f"private:{self.owner_id}"
            if self.visibility == "private"
            else f"product:{self.scope.product_id}",
        )
        if self.issue.audience != audience:
            raise ValueError("Audience must retain the actual private owner/product scope")
        if self.previous_ref and self.previous_ref.revision + 1 != self.ref.revision:
            raise ValueError("A persisted predecessor is exactly one version earlier")
        source_closure(self.sources, self.required_source_read_set, self.source_basis)
        saved = self.persisted_source_basis.get("artifact_sources")
        if not isinstance(saved, list) or canonical_basis(
            saved, self.required_source_read_set
        ) != canonical_basis(self.source_basis, self.required_source_read_set):
            raise ValueError("Typed safety must match the complete actual persisted source basis")
        if self.visibility == "product" and any(
            b.visibility == "private" for b in self.source_basis
        ):
            raise ValueError("Shared investigation cannot expand a private source audience")
        return self


class OriginalFailureProof(DTO):
    failure: FailureRef
    result: FixedQualityResult

    @model_validator(mode="after")
    def exact(self):
        result = self.result
        if result.run_revision < 3:
            raise ValueError("Original failure cannot be a planned/Start-only host Run version")
        if not result.current or result.reasons or result.retained.get("current") is not True:
            raise ValueError("Original failure requires current byte-verified retained proof")
        if failure_ref(result.verified, result.measurement_id) != self.failure:
            raise ValueError("Never replace an original FailureRef by a later Run Current")
        if result.purpose.strip() != result.purpose:
            raise ValueError("Failure purpose is exact")
        retained = result.retained
        required = {
            "original_start_intent",
            "original_start_version_id",
            "original_start_revision",
            "saved_start_at",
            "actual_start",
            "plan_binding",
            "reservation",
            "occupancy",
            "sample_usage",
            "facts_revision",
            "source_basis",
            "source_nature",
        }
        if not required <= retained.keys() or any(retained[k] is None for k in required):
            raise ValueError("Retained proof must preserve original Start, plan and all effects")
        if retained["source_nature"] != result.verified.nature:
            raise ValueError("Retained execution cannot promote synthetic to real")
        if retained["original_start_revision"] != 2 or retained[
            "actual_start"
        ] != result.verified.run.actual_start.model_dump(mode="json"):
            raise ValueError("Retained original Start must match the fixed Run's real actual_start")
        return self


def stable_failure_material(proof):
    """Only exact top-level bridge observation paths; full proof is retained too."""
    raw = json_value(proof)
    result = raw["result"]
    result["retained"].pop("checked_at", None)
    result["retained"].pop("execution_window_elapsed", None)
    result["source_basis"].pop("runtime_stamp", None)
    return raw


class StableCapaAnchor(DTO):
    schema_version: Literal["capa-semantic-anchor-v1"] = "capa-semantic-anchor-v1"
    origin: IssueVersionEvidence
    failures: tuple[OriginalFailureProof, ...] = Field(min_length=1)
    origin_sources: tuple[SourceRef, ...]
    origin_required_source_read_set: tuple[SourceRead, ...] = Field(min_length=1, max_length=20)
    origin_source_basis: tuple[SourceSafety, ...] = Field(min_length=1, max_length=20)
    material_sha256: Sha256
    full_failure_proofs_sha256: Sha256
    stable_failure_material_sha256: Sha256
    origin_source_basis_sha256: Sha256
    anchor_sha256: Sha256

    @model_validator(mode="after")
    def integrity(self):
        _check_origin(self.origin, self.failures)
        sources, reads, basis = source_closure(
            self.origin_sources, self.origin_required_source_read_set, self.origin_source_basis
        )
        expected_sources = canonical_sources(
            (*self.origin.sources, *(s for f in self.failures for s in f.result.sources))
        )
        expected_reads = canonical_reads(
            (
                *self.origin.required_source_read_set,
                *(r for f in self.failures for r in f.result.required_source_read_set),
            )
        )
        if sources != expected_sources or reads != expected_reads:
            raise ValueError("Anchor includes original row plus ALL fixed failure sources/reads")
        if not set(self.origin.source_basis) <= set(basis):
            # Pydantic source DTOs have no mutable mappings and are hashable.
            raise ValueError("Original row safety must remain in the full anchor closure")
        expected = _digests(self.origin, self.failures, sources, reads, basis)
        if any(getattr(self, name) != value for name, value in expected.items()):
            raise ValueError("Anchor digest does not bind its complete immutable contents")
        return self


def _check_origin(origin, failures):
    issue = origin.issue
    if (
        issue.status != "awaiting_verification"
        or issue.merged_into
        or issue.needs_recheck
        or issue.recheck_reasons
        or issue.root_cause is None
        or issue.capa is None
        or any(a.completion is None for a in issue.capa.actions)
        or issue.capa.effectiveness is not None
        or issue.capa.effectiveness_history
        or issue.closure
    ):
        reject("Anchor starts only at a genuinely completed, unmerged, unrechecked investigation.")
    if (
        origin.operation != "quality.capa.actions.complete"
        or not issue.history
        or issue.history[-1].operation != origin.operation
        or issue.history[-1].actor_kind != "human"
        or issue.history[-1].actor_id != origin.writer_id
        or issue.history[-1].at > origin.created_at
        or any(
            a.completion.id != a.id
            or a.completion.executor_id != a.executor_id
            or a.completion.at.occurred_at > origin.created_at
            for a in issue.capa.actions
        )
        or set(issue.capa.requirement.required_failure_ids) != {f.identity for f in issue.failures}
    ):
        reject(
            "Origin must retain the actual named final completion and exact failure requirement."
        )
    if {f.failure.identity for f in failures} != {f.identity for f in issue.failures} or len(
        failures
    ) != len(issue.failures):
        reject("Every original failure needs one exact full proof, without duplicates.")
    if tuple(f.failure for f in failures) != issue.failures:
        reject("Original business failure/proof order must be preserved.")
    mapped = {f.failure.identity: f for f in failures}
    for failure in issue.failures:
        proof = mapped[failure.identity]
        if (
            proof.failure != failure
            or proof.result.scope != issue.scope
            or proof.result.purpose != origin.purpose
        ):
            reject("Original failure scope/purpose/value/identity does not match.")
        if proof.result.verified.nature != origin.nature:
            reject("No synthetic/real promotion or mixed failure basis.")
        if origin.visibility == "product" and proof.result.visibility == "private":
            reject("Private original result cannot be expanded into a shared investigation.")
    required_sources = (
        *issue_sources(issue),
        *(s for f in issue.failures for s in (f.source, f.method, f.criterion)),
    )
    if not set(canonical_sources(required_sources)) <= set(
        canonical_sources((*origin.sources, *(s for f in failures for s in f.result.sources)))
    ):
        reject("Full root/actions/completion/containment/failure source closure is required.")


def _digests(origin, failures, sources, reads, basis):
    materials = origin.issue.model_dump(mode="json")  # includes original full history
    values = {
        "material_sha256": digest(materials),
        "full_failure_proofs_sha256": digest([json_value(f) for f in failures]),
        "stable_failure_material_sha256": digest([stable_failure_material(f) for f in failures]),
        "origin_source_basis_sha256": digest([json_value(b) for b in basis]),
    }
    values["anchor_sha256"] = digest(
        {
            "schema_version": "capa-semantic-anchor-v1",
            "origin": json_value(origin),
            "failures": [json_value(f) for f in failures],
            "origin_sources": [json_value(s) for s in sources],
            "origin_required_source_read_set": [json_value(r) for r in reads],
            "origin_source_basis": [json_value(b) for b in basis],
            **values,
        }
    )
    return values


def build_anchor(origin, failures, *, source_basis):
    """All inputs come from exact host reads; this function reads no real source."""
    origin = IssueVersionEvidence.model_validate(json_value(origin))
    mapped = [OriginalFailureProof.model_validate(json_value(f)) for f in failures]
    order = {f.identity: n for n, f in enumerate(origin.issue.failures)}
    mapped.sort(key=lambda f: order.get(f.failure.identity, len(order)))
    failures = tuple(mapped)
    _check_origin(origin, failures)
    sources = canonical_sources((*origin.sources, *(s for f in failures for s in f.result.sources)))
    reads = canonical_reads(
        (
            *origin.required_source_read_set,
            *(r for f in failures for r in f.result.required_source_read_set),
        )
    )
    basis = canonical_basis(source_basis, reads)
    return StableCapaAnchor(
        origin=origin,
        failures=failures,
        origin_sources=sources,
        origin_required_source_read_set=reads,
        origin_source_basis=basis,
        **_digests(origin, failures, sources, reads, basis),
    )


class CurrentAuthorizationClosure(DTO):
    """Full fresh HOST proof input, never a client authorization or grant."""

    scope: Scope
    purpose: Text
    audience: tuple[Text, ...] = Field(min_length=1)
    authority: Authority
    sources: tuple[SourceRef, ...]
    required_source_read_set: tuple[SourceRead, ...] = Field(min_length=1, max_length=20)
    source_basis: tuple[SourceSafety, ...] = Field(min_length=1, max_length=20)
    # Exact complete host snapshots, not lossy bool/has_ref summaries.
    professional_proof: dict[str, JsonValue] = Field(min_length=1)
    policy_proof: dict[str, JsonValue] = Field(min_length=1)
    source_acl_proof: dict[str, JsonValue] = Field(min_length=1)
    runtime_proof: dict[str, JsonValue] = Field(min_length=1)
    checked_at: AwareDatetime
    valid_until: AwareDatetime

    @model_validator(mode="after")
    def bound(self):
        if (
            self.authority.scope != self.scope
            or not self.authority.authorized
            or not self.authority.qualified
            or self.authority.cancelled
            or self.authority.actor_kind != "human"
            or self.checked_at >= self.valid_until
            or self.authority.now.tzinfo is None
            or self.authority.now.utcoffset() is None
            or self.authority.now > self.checked_at
        ):
            raise ValueError("Closure requires exact current qualified named host authority")
        if not set(self.audience) <= set(self.authority.audience):
            raise ValueError("Actual current reader cannot expand the original audience")
        source_closure(self.sources, self.required_source_read_set, self.source_basis)
        return self


def closure_material(closure):
    raw = json_value(closure)
    raw.pop("checked_at")  # ONLY assessment clock; expiry and full authority/proofs remain.
    raw["authority"].pop("now")  # exact typed Authority evaluation clock only
    return raw


def verify_closure(anchor, closure, *, at):
    closure = CurrentAuthorizationClosure.model_validate(json_value(closure))
    if at.tzinfo is None or at.utcoffset() is None:
        reject("Host evaluation time must be aware.")
    if not closure.checked_at <= at < closure.valid_until:
        reject("Current authorization closure is future or expired.", "SOURCE_STALE")
    if (closure.scope, closure.purpose, closure.audience) != (
        anchor.origin.scope,
        anchor.origin.purpose,
        anchor.origin.issue.audience,
    ):
        reject("Current closure cannot cross scope, purpose or audience.")
    if (
        anchor.origin.visibility == "private"
        and closure.authority.actor_id != anchor.origin.owner_id
    ):
        reject(
            "Peer ProductGrant cannot make another person's private Issue readable.",
            "FORBIDDEN_SCOPE",
        )
    if not set(anchor.origin_sources) <= set(canonical_sources(closure.sources)):
        reject("Current closure omits original sources.")
    current = {
        b.id: b for b in canonical_basis(closure.source_basis, closure.required_source_read_set)
    }
    if any(
        b.visibility == "private" and b.owner_id != closure.authority.actor_id
        for b in current.values()
    ):
        reject("Current reader does not own a private source.", "FORBIDDEN_SCOPE")
    if any(current.get(old.id) != old for old in anchor.origin_source_basis):
        reject("Original source registration/hash/owner/security epoch changed.")
    return closure
