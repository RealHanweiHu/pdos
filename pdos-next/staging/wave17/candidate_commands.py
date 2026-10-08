"""Unregistered candidate payload/semantic boundary; no live write owner.

These functions perform exact structural checks only. They do not read Current,
sources or owner proofs, create an anchor, consume confirmation or save a fact.
"""

# Common registry is initialized before importing its domain children.
# ruff: noqa: I001
from copy import deepcopy
import sys
from typing import Literal
from uuid import UUID

from pdos_next.service import digest  # noqa: F401 -- initialize actual registry first

from pdos_next.domain.capa_verification.schemas import (
    CandidateBinding,
    DefinitionReference,
    FailurePairMapping,
    FixedRef,
)
from pdos_next.domain.quality_execution.schemas import Revision, Text, Token
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import DTO
from pydantic import BaseModel, Field, ValidationError, model_validator

OPERATION = "quality.capa.verification.candidate.record"
TIER = "T1"
SUBJECT = "capa_verification_candidate"
EVENT = "CapaVerificationCandidateRecorded"


class CandidateRecordPayload(DTO):
    """Business selections only; scope/anchor/proof/inspection are host facts."""

    issue_id: UUID
    expected_issue_revision: Revision
    capa_id: UUID
    remediation_link_refs: tuple[FixedRef, ...] = Field(default=(), max_length=20)
    mappings: tuple[FailurePairMapping, ...] = Field(default=(), max_length=10000)
    sources: tuple[DefinitionReference, ...] = Field(default=(), max_length=20)
    reason: Text
    visibility: Literal["private", "product"] = "private"
    confirmation_token: Token | None = None

    @model_validator(mode="after")
    def exact_unique_selections(self):
        if any(value.revision != 1 for value in self.remediation_link_refs):
            raise ValueError("A stored remediation Link has exactly revision 1")
        if len({value.id for value in self.remediation_link_refs}) != len(
            self.remediation_link_refs
        ):
            raise ValueError("A fixed remediation Link cannot repeat")
        keys = {(m.failure_id, m.run.id, m.sample_id, m.item_id) for m in self.mappings}
        if len(keys) != len(self.mappings):
            raise ValueError("A failure/Run/sample/item mapping cannot repeat")
        source_keys = {(s.artifact_id, s.expected_revision, s.line, s.quote) for s in self.sources}
        if len(source_keys) != len(self.sources):
            raise ValueError("An exact source reference cannot repeat")
        return self


def _attributes(value):
    # Inspect native attributes before invoking a serializer: the serializer can
    # silently convert an unvalidated True in an int field to 1. This is a raw
    # parser input, never a generic JSON semantic or an authority assessment.
    if isinstance(value, BaseModel):
        raw = {k: _attributes(v) for k, v in vars(value).items()}
        extras = value.model_extra or {}
        if raw.keys() & extras.keys():
            raise ValueError("Duplicate model attributes are not an actual candidate payload")
        raw.update({k: _attributes(v) for k, v in extras.items()})
        return raw
    if isinstance(value, dict):
        return {k: _attributes(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_attributes(v) for v in value]
    return deepcopy(value)


def _payload(value):
    # Model instances may contain mutated non-frozen children or may have been
    # model_construct'ed; their class or normalized serialized shape is no proof.
    return CandidateRecordPayload.model_validate(_attributes(value))


def semantic(payload):
    """Canonical actual candidate semantics; only the token is excluded.

    Typed defaults and explicit null measurement/projection fields remain.
    Existing DTO parsing applies; this function neither sorts selections nor
    inserts metadata, values, clocks, applicability or participant claims.
    """
    return _payload(payload).model_dump(mode="json", exclude={"confirmation_token"})


def check_candidate_request(payload, actual_binding, *, current_issue_revision):
    """Compare exact server binding/current scalar; returns no authorization.

    The origin basis revision is deliberately not used as the Current CAS.
    Root's actual host must independently read Current/scope/lineage and sources.
    """
    payload = _payload(payload)
    if type(current_issue_revision) is not int or current_issue_revision < 1:
        raise DomainError(
            "CANDIDATE_CURRENT_REVISION_REQUIRED", "需宿主读取的严格当前Issue版本。", 503
        )
    if payload.expected_issue_revision != current_issue_revision:
        raise DomainError("VERSION_CONFLICT", "当前Issue版本已变化，需重新核对候选请求。", 409)
    try:
        raw = _attributes(actual_binding)
        binding = CandidateBinding.model_validate(raw)
    except (ValidationError, TypeError, ValueError):
        raise DomainError(
            "CANDIDATE_ACTUAL_BINDING_REQUIRED", "需宿主已核对的完整typed候选绑定。", 503
        ) from None
    if (
        (binding.basis.issue_id, binding.basis.capa_id) != (payload.issue_id, payload.capa_id)
        or [v.model_dump(mode="json") for v in binding.remediation_link_refs]
        != [v.model_dump(mode="json") for v in payload.remediation_link_refs]
        or [v.model_dump(mode="json") for v in binding.mappings]
        != [v.model_dump(mode="json") for v in payload.mappings]
    ):
        raise DomainError(
            "CANDIDATE_REQUEST_BINDING_MISMATCH", "候选Issue/CAPA或固定选择与原请求不一致。", 409
        )
    return binding


def semantic_owner():
    """Explicit server factory for this module; it does not register a writer."""
    from candidate_storage import CandidateSemanticOwner

    owner = CandidateSemanticOwner(CandidateRecordPayload, sys.modules[__name__], semantic)
    owner.check()
    return owner
