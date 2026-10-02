"""Read-only, operator-pinned independent event-Issue evaluation publications.

The operator must verify human identity, frozen independent golden originals and
actual provider invocation/report originals before installing the file and its
SHA in trusted server configuration. References and booleans are not proof by
themselves. HTTP clients must never supply this environment or write this file.
This loader neither fetches originals nor calls a model nor grants T0 authority.

IssueEvaluationEvidence.binding identifies the evaluated runtime, including its gateway
admission suite. capability_suite_* identifies the separate capability golden
suite; gateway admission cannot substitute for that independent evaluation.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime
from hashlib import sha256
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, ValidationError, model_validator

from app.ai.model_catalog import ProviderName
from app.ai.write_evaluation_publication import (
    WriteEvaluationPublicationError as WriteEvaluationPublicationError,
)
from app.ai.write_evaluation_publication import (
    _read_bounded_file,
    _unique_json_object,
)
from app.contracts.ai_issue_evaluation import IssueEvaluationBinding
from app.contracts.ai_write_qualification import EvaluationExecutionSource
from app.contracts.common_objects import Contract, Digest, Key, Text

ISSUE_EVALUATION_PUBLICATION_PATH = "PDOS_AI_ISSUE_EVALUATION_PUBLICATION_PATH"
ISSUE_EVALUATION_PUBLICATION_SHA256 = "PDOS_AI_ISSUE_EVALUATION_PUBLICATION_SHA256"
_UNKNOWN_MODEL_VALUES = frozenset(
    {"unknown", "unspecified", "unavailable", "latest", "default", "未知", "未登记"}
)


class IssueEvaluationEvidence(Contract):
    """Live execution provenance; controlled golden cases are not trial samples."""

    evaluation_id: UUID
    execution_source: EvaluationExecutionSource
    evidence_ref: Text
    receipt_digest: Digest
    golden_publication_ref: Text
    golden_publication_digest: Digest
    binding: IssueEvaluationBinding
    real_provider_call: bool = Field(strict=True)
    completed_at: AwareDatetime
    outcome: Literal["passed", "failed", "incomplete"]


class IssueOriginalEvaluationCall(Contract):
    invocation_id: UUID
    tenant_id: UUID
    invocation_ref: Text
    receipt_digest: Digest
    binding: IssueEvaluationBinding
    execution_source: Literal["live_model_evaluation"]
    real_provider_call: bool = Field(strict=True)
    started_at: AwareDatetime
    completed_at: AwareDatetime

    @model_validator(mode="after")
    def actual_call(self) -> Self:
        if not self.real_provider_call:
            raise ValueError("original_call_requires_real_provider")
        if self.started_at > self.completed_at:
            raise ValueError("original_call_time_order")
        return self


class IssueEvaluationPublicationEntry(Contract):
    evaluation: IssueEvaluationEvidence
    operation_key: Literal["event.issue.create"]
    capability_suite_version: Key
    capability_suite_digest: Digest
    golden_fixed_at: AwareDatetime
    # Original human review of the independent golden/report/provider receipts.
    golden_external_review_ref: Text
    golden_external_review_digest: Digest
    original_calls: Annotated[
        tuple[IssueOriginalEvaluationCall, ...], Field(min_length=1, max_length=2000)
    ]

    @model_validator(mode="after")
    def complete_independent_evaluation(self) -> Self:
        evidence = self.evaluation
        binding = evidence.binding
        ProviderName(binding.provider)
        for value in (binding.model, binding.model_version):
            if value is None or value.casefold() in _UNKNOWN_MODEL_VALUES:
                raise ValueError("evaluation_requires_known_model_revision")
        if self.operation_key != binding.operation_key:
            raise ValueError("capability_suite_operation_mismatch")
        if self.capability_suite_digest == binding.suite_digest:
            raise ValueError("capability_suite_cannot_be_gateway_admission_suite")
        if evidence.execution_source != "live_model_evaluation" or not evidence.real_provider_call:
            raise ValueError("evaluation_requires_live_provider_execution")
        if evidence.outcome not in {"passed", "failed"}:
            raise ValueError("evaluation_must_be_complete")
        for call in self.original_calls:
            if call.binding != binding:
                raise ValueError("original_call_binding_mismatch")
            if (
                not self.golden_fixed_at
                <= call.started_at
                <= call.completed_at
                <= evidence.completed_at
            ):
                raise ValueError("golden_and_original_call_time_order")
        return self


class IssueEvaluationPublication(Contract):
    version: Literal["dc11-issue-write-evaluation-publication.v1"]
    publication_id: UUID
    tenant_id: UUID
    published_by: UUID
    actor_kind: Literal["human"]
    actor_identity_source: Literal["operator_verified_identity"]
    actor_identity_ref: Text
    actor_identity_digest: Digest
    published_at: AwareDatetime
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    evaluations: Annotated[
        tuple[IssueEvaluationPublicationEntry, ...], Field(min_length=1, max_length=64)
    ]

    @model_validator(mode="after")
    def original_identity_and_scope(self) -> Self:
        if not self.published_at <= self.valid_from < self.valid_until:
            raise ValueError("publication_time_order")
        evaluation_ids: set[UUID] = set()
        bindings: set[str] = set()
        invocation_ids: set[UUID] = set()
        invocation_refs: set[str] = set()
        golden_originals: dict[str, tuple[str, str, str, datetime, str]] = {}
        for entry in self.evaluations:
            evidence = entry.evaluation
            binding_key = evidence.binding.model_dump_json()
            if evidence.evaluation_id in evaluation_ids or binding_key in bindings:
                raise ValueError("duplicate_evaluation_identity_or_binding")
            evaluation_ids.add(evidence.evaluation_id)
            bindings.add(binding_key)
            if evidence.completed_at > self.published_at:
                raise ValueError("evaluation_after_publication")
            original = (
                evidence.golden_publication_digest,
                entry.capability_suite_version,
                entry.capability_suite_digest,
                entry.golden_fixed_at,
                entry.operation_key,
            )
            previous = golden_originals.setdefault(evidence.golden_publication_ref, original)
            if previous != original:
                raise ValueError("golden_publication_identity_mismatch")
            for call in entry.original_calls:
                if call.tenant_id != self.tenant_id:
                    raise ValueError("original_call_tenant_mismatch")
                if call.invocation_id in invocation_ids or call.invocation_ref in invocation_refs:
                    raise ValueError("duplicate_original_call")
                invocation_ids.add(call.invocation_id)
                invocation_refs.add(call.invocation_ref)
        return self


class LoadedIssueEvaluationPublication(Contract):
    publication_sha256: Digest
    publication: IssueEvaluationPublication
    qualification_granted: Literal[False] = False


class PublishedIssueEvaluation(Contract):
    publication_sha256: Digest
    publication_id: UUID
    published_at: AwareDatetime
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    evaluation: IssueEvaluationEvidence
    qualification_granted: Literal[False] = False


def configured_issue_evaluation_publication(
    environment: Mapping[str, str], *, tenant_id: UUID, as_of: datetime
) -> LoadedIssueEvaluationPublication | None:
    """Read all entries in a currently valid tenant publication; never publish it.

    Only absent configuration returns None. Partial, stale, wrong-tenant or
    otherwise invalid configured publications fail closed with a stable code.
    Both passed and failed completed evaluations are returned for honest history.
    """
    path = environment.get(ISSUE_EVALUATION_PUBLICATION_PATH, "")
    expected = environment.get(ISSUE_EVALUATION_PUBLICATION_SHA256, "")
    if not path and not expected:
        return None
    if not path or not expected:
        raise WriteEvaluationPublicationError("publication_configuration_incomplete")
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise WriteEvaluationPublicationError("publication_invalid_sha256_pin")
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise WriteEvaluationPublicationError("publication_requires_aware_cutoff")
    body = _read_bounded_file(path)
    digest = sha256(body).hexdigest()
    if digest != expected:
        raise WriteEvaluationPublicationError("publication_digest_mismatch")
    try:
        document = json.loads(body, object_pairs_hook=_unique_json_object)
        publication = IssueEvaluationPublication.model_validate(document)
    except (ValidationError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise WriteEvaluationPublicationError("publication_invalid_document") from exc
    if publication.tenant_id != tenant_id:
        raise WriteEvaluationPublicationError("publication_tenant_mismatch")
    if not publication.valid_from <= as_of < publication.valid_until:
        raise WriteEvaluationPublicationError("publication_outside_validity_window")
    return LoadedIssueEvaluationPublication(publication_sha256=digest, publication=publication)


def select_issue_evaluation(
    loaded: LoadedIssueEvaluationPublication, *, expected_binding: IssueEvaluationBinding
) -> PublishedIssueEvaluation:
    """Select by every runtime binding field; never fall back to another model."""
    publication = loaded.publication
    matches = [
        entry.evaluation
        for entry in publication.evaluations
        if entry.evaluation.binding == expected_binding
    ]
    if len(matches) != 1:
        raise WriteEvaluationPublicationError("publication_binding_not_found")
    return PublishedIssueEvaluation(
        publication_sha256=loaded.publication_sha256,
        publication_id=publication.publication_id,
        published_at=publication.published_at,
        valid_from=publication.valid_from,
        valid_until=publication.valid_until,
        evaluation=matches[0],
    )


def configured_issue_evaluation(
    environment: Mapping[str, str],
    *,
    tenant_id: UUID,
    expected_binding: IssueEvaluationBinding,
    as_of: datetime,
) -> PublishedIssueEvaluation | None:
    loaded = configured_issue_evaluation_publication(environment, tenant_id=tenant_id, as_of=as_of)
    return (
        None
        if loaded is None
        else select_issue_evaluation(loaded, expected_binding=expected_binding)
    )
