"""Finite, explicitly verified local synthetic investigation classification.

This does not classify from keywords, grant professional authority, verify an
actual completion event, or enable formal Change implementation. Root injects
the returned callback explicitly; default quality_followup assessment is None.
"""

import json
from dataclasses import dataclass
from datetime import UTC
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, ConfigDict, Field, field_validator, model_validator

from pdos_next.domain.quality_execution.evidence import (
    POSITION,
    check_source,
    merge_reads,
)
from pdos_next.domain.quality_execution.policy import policy_time_current
from pdos_next.domain.quality_execution.schemas import Revision, Sha256, Text
from pdos_next.domain.quality_followup.evidence import _constant, _pairs
from pdos_next.domain.quality_followup.schemas import (
    CompletionAssessment,
    CompletionFact,
    ExactSource,
)
from pdos_next.errors import DomainError
from pdos_next.models import now
from pdos_next.safety import verify_test_target
from pdos_next.schemas.verification.contracts import DTO
from pdos_next.service import digest, source_for


class CompletionProfileEntry(DTO):
    issue_id: UUID
    capa_id: UUID
    action_id: UUID
    executor_id: UUID
    purpose: Text
    action_sha256: Sha256
    classification: Literal["investigation"]
    nature: Literal["synthetic"]
    source: ExactSource
    valid_until: AwareDatetime

    @field_validator("valid_until")
    @classmethod
    def utc(cls, value):
        return value.astimezone(UTC)

    @field_validator("source")
    @classmethod
    def exact_artifact(cls, value):
        if value.kind != "artifact" or not POSITION.fullmatch(value.position):
            raise ValueError("Controlled classification requires an exact registered artifact line")
        return value


class CompletionProfile(DTO):
    tenant_id: UUID
    product_id: UUID
    project_id: UUID
    entries: tuple[CompletionProfileEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_actions(self):
        keys = [
            (e.issue_id, e.capa_id, e.action_id, e.executor_id, e.purpose) for e in self.entries
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("A controlled action cannot have ambiguous classification entries")
        return self


class ClassificationFact(DTO):
    # No trimming of observed text. An ordinary completion line is not this fact.
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)
    tenant_id: UUID
    product_id: UUID
    project_id: UUID
    issue_id: UUID
    capa_id: UUID
    action_id: UUID
    executor_id: UUID
    purpose: Text
    action_sha256: Sha256
    classification: Literal["investigation"]
    nature: Literal["synthetic"]
    valid_until: AwareDatetime

    @field_validator("valid_until", mode="before")
    @classmethod
    def observed_iso(cls, value):
        if not isinstance(value, str):
            raise ValueError("Observed classification expiry must be an aware ISO string")
        return value

    @field_validator("valid_until")
    @classmethod
    def utc(cls, value):
        return value.astimezone(UTC)


class NativeRegistration(DTO):
    receipt_id: UUID
    actor_id: UUID
    requester_id: UUID
    run_id: UUID | None


class ClassificationSourceBasis(DTO):
    """Current native immutable text provenance, not instrument measurement bytes."""

    id: UUID
    revision: Revision
    hash: Sha256
    status: Literal["active"]
    owner_id: UUID
    visibility: Literal["private", "category", "audience"]
    source_kind: Literal["registered_native_text"]
    registration: NativeRegistration


class SyntheticCompletionAssessment(CompletionAssessment):
    """Host-only additive fields retained by A's isinstance/full model_dump path."""

    classification_source_basis: tuple[ClassificationSourceBasis, ...] = Field(min_length=1)
    profile_epoch: Revision
    profile_sha256: Sha256


@dataclass(frozen=True)
class _Profile:
    data: CompletionProfile
    epoch: int


def _scope(data):
    return data.tenant_id, data.product_id, data.project_id


def _active(engine, configured):
    if getattr(engine, "_pdos_quality_completion_profiles", {}).get(
        _scope(configured.data)
    ) is not (configured):
        raise DomainError("SOURCE_STALE", "受控合成调查分类配置已撤回或替换。")


def disable_local_profile(engine, *, tenant_id, product_id, project_id):
    key = tenant_id, product_id, project_id
    registry = dict(getattr(engine, "_pdos_quality_completion_profiles", {}))
    registry.pop(key, None)
    epochs = dict(getattr(engine, "_pdos_quality_completion_profile_epochs", {}))
    epochs[key] = epochs.get(key, 0) + 1
    engine._pdos_quality_completion_profiles = registry
    engine._pdos_quality_completion_profile_epochs = epochs


def _classification(s, ctx, product_id, entry, configured):
    reads, raw_basis, _private = check_source(s, ctx, product_id, entry.source)
    # Native controlled publications have an actual artifact-register Receipt.
    # Uploaded classification documents await a dedicated physical-byte reader;
    # parsed text/security alone is not silently claimed as original verification.
    if any(value.get("source_kind") != "registered_native_text" for value in raw_basis):
        raise DomainError("INTEGRATION_REQUIRED", "分类原件真实字节核对入口尚未接入。", 503)
    try:
        basis = tuple(ClassificationSourceBasis.model_validate(value) for value in raw_basis)
    except ValueError as exc:
        raise DomainError("SOURCE_UNAVAILABLE", "受控分类须有实际精确原生登记证明。") from exc
    if len(basis) != 1 or (basis[0].id, basis[0].revision) != (
        entry.source.id,
        entry.source.revision,
    ):
        raise DomainError("INTEGRITY_MISMATCH", "分类来源身份与完整登记依据不一致。")
    row = source_for(s, ctx, product_id, entry.source.id, entry.source.revision)
    index = int(POSITION.fullmatch(entry.source.position)[1]) - 1
    try:
        raw = json.loads(
            row.content.splitlines()[index], object_pairs_hook=_pairs, parse_constant=_constant
        )
        fact = ClassificationFact.model_validate(raw)
    except (ValueError, TypeError, IndexError) as exc:
        raise DomainError(
            "MISSING_REQUIRED_EVIDENCE", "调查分类须为独立精确结构化出处。", 422
        ) from exc
    expected = {
        "tenant_id": configured.data.tenant_id,
        "product_id": configured.data.product_id,
        "project_id": configured.data.project_id,
        **entry.model_dump(exclude={"source"}),
    }
    if fact.model_dump() != expected or row.content_hash != basis[0].hash:
        raise DomainError("MISSING_REQUIRED_EVIDENCE", "调查分类出处未匹配全部固定措施绑定。", 422)
    return merge_reads(reads), basis


def _assess(configured, engine, s, ctx, product_id, basis, action, completion, policy, observation):
    _active(engine, configured)
    if s.get_bind() is not engine or ctx.run_id is not None or ctx.actor_id != ctx.requester_id:
        raise DomainError("FORBIDDEN_SCOPE", "合成调查核对仅在具名本人受控宿主范围。", 403)
    if (
        _scope(configured.data)
        != (
            ctx.tenant_id,
            product_id,
            basis.scope.project_id,
        )
        or basis.scope.tenant_id != ctx.tenant_id
        or basis.scope.product_id != product_id
    ):
        raise DomainError("FORBIDDEN_SCOPE", "调查分类不能跨租户、产品或项目。", 403)
    if basis.nature != "synthetic":
        raise DomainError("INTEGRATION_REQUIRED", "合成调查入口不授真实实施资格。", 503)
    entries = [
        value
        for value in configured.data.entries
        if (
            value.issue_id,
            value.capa_id,
            value.action_id,
            value.executor_id,
            value.purpose,
        )
        == (basis.issue_id, basis.capa_id, action.id, ctx.requester_id, basis.purpose)
    ]
    if len(entries) != 1:
        raise DomainError("INTEGRATION_REQUIRED", "此确切措施没有受控合成调查分类。", 503)
    entry = entries[0]
    binding = next((value for value in basis.actions if value.action_id == action.id), None)
    if (
        binding is None
        or entry.action_sha256 != binding.action_sha256
        or entry.action_sha256 != digest(action.model_dump(mode="json", exclude={"completion"}))
        or action.executor_id != ctx.requester_id
        or completion.id != action.id
        or completion.executor_id != ctx.requester_id
        or action.completion is not None
    ):
        raise DomainError("ACTION_COMPLETION_UNVERIFIED", "固定措施或本人执行范围无法核对。")
    if not isinstance(observation, CompletionFact) or (
        observation.issue_id,
        observation.capa_id,
        observation.action_id,
        observation.executor_id,
        observation.purpose,
        observation.text,
        observation.occurred_at,
        observation.original_timezone,
    ) != (
        basis.issue_id,
        basis.capa_id,
        action.id,
        ctx.requester_id,
        basis.purpose,
        completion.text,
        completion.at.occurred_at,
        completion.at.original_timezone,
    ):
        raise DomainError("ACTION_COMPLETION_UNVERIFIED", "分类不能替代本人真实完成九字段事件。")
    reads, actual = _classification(s, ctx, product_id, entry, configured)
    final_reads, final_actual = _classification(s, ctx, product_id, entry, configured)
    _active(engine, configured)
    if final_actual != actual or final_reads != reads:
        raise DomainError("SOURCE_STALE", "分类核对期间登记/安全/生命周期依据改变。")
    at = now()
    if policy.get("nature") != "synthetic" or not policy_time_current(policy, at):
        raise DomainError("RECHECK_REQUIRED", "当前完整合成风险政策条件不能核对。")
    if entry.valid_until <= at or observation.occurred_at > at:
        raise DomainError("ACTION_COMPLETION_UNVERIFIED", "分类已过固定期限或完成事件为未来。")
    result = SyntheticCompletionAssessment(
        scope=basis.scope,
        issue_id=basis.issue_id,
        capa_id=basis.capa_id,
        action_id=action.id,
        executor_id=ctx.requester_id,
        purpose=basis.purpose,
        basis_sha256=basis.basis_sha256,
        action_sha256=binding.action_sha256,
        completion_sha256=digest(completion.model_dump(mode="json")),
        event_source=completion.at.source.model_dump(mode="json"),
        policy_basis_sha256=digest(policy),
        allowed=True,
        current=True,
        classification="investigation",
        nature="synthetic",
        reason_codes=("EXACT_HOST_SYNTHETIC_INVESTIGATION_CLASSIFICATION",),
        sources=(entry.source,),
        owner_proofs=(),
        required_source_read_set=reads,
        time_constraints=(entry.valid_until,),
        classification_source_basis=actual,
        profile_epoch=configured.epoch,
        profile_sha256=digest(configured.data.model_dump(mode="json")),
        proof_sha256="0" * 64,
    )
    return result.model_copy(
        update={"proof_sha256": digest(result.model_dump(mode="json", exclude={"proof_sha256"}))}
    )


def configure_local_profile(engine, profile):
    """Verify the target itself; return callback without touching professional/runtime grants."""
    data = CompletionProfile.model_validate(
        profile.model_dump(mode="json") if isinstance(profile, CompletionProfile) else profile
    )
    verify_test_target(engine)
    key = _scope(data)
    epochs = dict(getattr(engine, "_pdos_quality_completion_profile_epochs", {}))
    epochs[key] = epochs.get(key, 0) + 1
    configured = _Profile(data, epochs[key])
    registry = dict(getattr(engine, "_pdos_quality_completion_profiles", {}))
    registry[key] = configured
    engine._pdos_quality_completion_profiles = registry
    engine._pdos_quality_completion_profile_epochs = epochs

    def assess(
        s, ctx, product_id, basis, action, completion, *, policy_snapshot, observation, write=False
    ):
        return _assess(
            configured,
            engine,
            s,
            ctx,
            product_id,
            basis,
            action,
            completion,
            policy_snapshot,
            observation,
        )

    return assess
