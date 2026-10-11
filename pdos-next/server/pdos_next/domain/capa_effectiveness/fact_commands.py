"""Strict fact selections; scope, qualification and provenance belong to hosts.

These DTOs do not register commands. Rule publication is host-only. Original
record JSON is input material to be checked against exact real source bytes;
it is never a statement of complete coverage or a participant/authority proof.
"""

import json
from copy import deepcopy
from types import MappingProxyType
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from pdos_next import models as _model_registry  # noqa: F401
from pdos_next.domain.capa_verification.schemas import FailurePairMapping
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import EventTime, SourceRef

from .anchor import VersionRef
from .candidate_commands import _attributes
from .facts import FactRef, ObservationTarget, SamplingRequirement
from .paired import Closed, Revision, Text

Token = Annotated[str, Field(strict=True, min_length=20, max_length=128)]
ExternalId = Annotated[str, Field(strict=True, min_length=1, max_length=200)]
Conclusion = Literal["applicable", "not_applicable", "unknown"]
OBSERVATION_OPERATION = "quality.capa.observation.record"
REVIEW_OPERATION = "quality.capa.verification.review"
RULE_OPERATION = "quality.capa.verification.rule.import"
SPECS = MappingProxyType(
    {
        "rule": (
            RULE_OPERATION,
            "host_import",
            "capa_verification_rule",
            "CapaVerificationRulePublished",
        ),
        "observation": (OBSERVATION_OPERATION, "T1", "capa_observation", "CapaObservationRecorded"),
        "review": (
            REVIEW_OPERATION,
            "T2",
            "capa_named_verification_review",
            "CapaVerificationReviewed",
        ),
    }
)


class ExactSource(SourceRef):
    """Retain original SourceRef identity/position with a strict revision."""

    revision: Revision


class ActualEventTime(EventTime):
    source: ExactSource

    @model_validator(mode="after")
    def occurred_only(self):
        if self.effective_at is not None:
            raise ValueError("Fact event retains actual occurrence, not a proposed effective clock")
        return self


class ExactObservationTarget(ObservationTarget):
    identity_sources: tuple[ExactSource, ...] = Field(min_length=1)


class ExactSamplingRequirement(SamplingRequirement):
    targets: tuple[ExactObservationTarget, ...] = Field(min_length=1)
    sampling_method: ExactSource
    acceptance: ExactSource


def _sources_unique(values):
    keys = {(v.id, v.revision, v.kind, v.position) for v in values}
    if len(keys) != len(values):
        raise ValueError("Exact source selections cannot repeat")


class ObservationRecordInput(Closed):
    target_key: Text
    occurred_at: AwareDatetime
    original_timezone: Text
    sources: tuple[ExactSource, ...] = Field(min_length=1)
    raw_material: dict[str, JsonValue]

    @model_validator(mode="after")
    def actual(self):
        _sources_unique(self.sources)
        ActualEventTime(
            occurred_at=self.occurred_at,
            original_timezone=self.original_timezone,
            source=self.sources[0],
        )
        return self


class FactTarget(Closed):
    issue_id: UUID
    expected_issue_revision: Revision
    capa_id: UUID
    sources: tuple[ExactSource, ...] = Field(min_length=1)
    reason: Text
    visibility: Literal["private", "category", "audience"] = "private"

    @model_validator(mode="after")
    def exact_sources(self):
        _sources_unique(self.sources)
        return self


class ObservationPayload(FactTarget):
    rule: FactRef
    previous: FactRef | None = None
    target_keys: tuple[Text, ...] = Field(min_length=1)
    observed_from: AwareDatetime
    observed_until: AwareDatetime
    at: ActualEventTime
    records: tuple[ObservationRecordInput, ...] = Field(min_length=1)
    coverage_sources: tuple[ExactSource, ...] = Field(min_length=1)
    confirmation_token: Token | None = None

    @model_validator(mode="after")
    def observed(self):
        if len(set(self.target_keys)) != len(self.target_keys):
            raise ValueError("Observed target selections cannot repeat")
        _sources_unique(self.coverage_sources)
        if not self.observed_from < self.observed_until <= self.at.occurred_at:
            raise ValueError("Observation retains a complete actual increasing interval")
        if any(
            r.target_key not in self.target_keys
            or not self.observed_from <= r.occurred_at <= self.observed_until
            for r in self.records
        ):
            raise ValueError("Every original record belongs to its selected target and interval")
        if len(
            {
                json.dumps(r.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
                for r in self.records
            }
        ) != len(self.records):
            raise ValueError("The same exact original observation cannot be counted twice")
        return self


class PairReviewInput(Closed):
    mapping: FailurePairMapping
    method: ExactSource | None = None
    criterion: ExactSource | None = None
    conclusion: Conclusion
    reason: Text
    sources: tuple[ExactSource, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def references(self):
        _sources_unique(self.sources)
        return self


class ActionReviewInput(Closed):
    action_id: UUID
    conclusion: Conclusion
    reason: Text
    sources: tuple[ExactSource, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def references(self):
        _sources_unique(self.sources)
        return self


class NamedReviewPayload(FactTarget):
    candidate: FactRef
    rule: FactRef
    observations: tuple[FactRef, ...] = Field(min_length=1)
    at: ActualEventTime
    pair_applicability: tuple[PairReviewInput, ...] = Field(min_length=1)
    action_fulfillment: tuple[ActionReviewInput, ...] = Field(min_length=1)
    conclusion: Conclusion
    approval_token: Token | None = None

    @model_validator(mode="after")
    def exact_review(self):
        if self.candidate.revision != 1:
            raise ValueError("A fixed candidate is an immutable v1 object")
        if len({v.id for v in self.observations}) != len(self.observations):
            raise ValueError("A fixed observation cannot repeat or mix versions")
        keys = {
            (p.mapping.failure_id, p.mapping.run.id, p.mapping.sample_id, p.mapping.item_id)
            for p in self.pair_applicability
        }
        if len(keys) != len(self.pair_applicability):
            raise ValueError("A failure/Run/sample/item review cannot repeat")
        if len({a.action_id for a in self.action_fulfillment}) != len(self.action_fulfillment):
            raise ValueError("An action conclusion cannot repeat")
        return self


class RulePublicationInput(FactTarget):
    """Trusted original policy material; never a public PAYLOADS entry.

    A configured issuer owner supplies issuer/nature/current qualification and
    verifies these exact materials. No issuer or approval boolean is accepted.
    """

    origin: VersionRef
    previous: FactRef | None = None
    external_id: ExternalId
    policy_ref: ExactSource
    method: ExactSource
    criterion: ExactSource
    sampling: ExactSamplingRequirement
    rule_material: dict[str, JsonValue]
    independence_material: dict[str, JsonValue]
    valid_from: AwareDatetime
    valid_until: AwareDatetime

    @model_validator(mode="after")
    def validity(self):
        if self.valid_until <= self.valid_from:
            raise ValueError("Publication retains a fixed increasing validity interval")
        return self


TYPES = MappingProxyType(
    {"rule": RulePublicationInput, "observation": ObservationPayload, "review": NamedReviewPayload}
)


def payload_for(kind, value):
    if kind not in TYPES:
        raise DomainError("FACT_KIND_REQUIRED", "需明确的事实操作类型。", 422)
    return TYPES[kind].model_validate(_attributes(value))


def kind_for_payload(value):
    kinds = [k for k, cls in TYPES.items() if type(value) is cls]
    if len(kinds) != 1:
        raise DomainError(
            "FACT_TYPED_PAYLOAD_REQUIRED", "需真实严格事实载荷，不能用任意JSON冒充。", 422
        )
    return kinds[0]


def semantic(payload):
    """Full typed business semantics, original order; only its proof token omitted."""
    kind = kind_for_payload(payload)
    checked = payload_for(kind, payload)
    token = "approval_token" if kind == "review" else "confirmation_token"
    return deepcopy(checked.model_dump(mode="json", exclude={token}))
