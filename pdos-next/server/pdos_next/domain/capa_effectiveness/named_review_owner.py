"""Actual named-review assembly; missing live pair/applicability owners reject.

Only a trusted startup owner invokes this reader. It neither creates a saved
review/atom nor certifies effectiveness/close. Human selections are compared to
actual candidate, Rule, ordered Observations, current pairs and participants.
"""

# Common registry must initialize before its domain children.
# ruff: noqa: I001
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID
from typing import Literal
from pdos_next.domain.configurations.schemas import DefinitionReference

from pdos_next.service import Context, digest
from pdos_next.errors import DomainError
from pdos_next.domain.quality_execution import evidence, policy
from pdos_next.domain.verification_front.models import FormalVerificationCurrent
from pdos_next.domain.verification_launch.models import VerificationRunVersion
from pdos_next.schemas.verification.contracts import TestRun
from . import anchor as a
from . import fact_atom_storage as guards
from . import fact_commands as commands
from . import paired
from .candidate_storage import CandidateSemanticOwner, read_candidate
from .fact_registry_storage import read_stored_fact
from .fact_sources_owner import read_source_closure, _wire, _deadline
from .fact_write import FactWriteMaterial
from .facts import (
    ActionFulfillment,
    PairApplicability,
    _action_bindings,
)
from .participants_owner import _Read, read_participants, refresh_participants


def require(value, code="FACT_REVIEW_OWNER_REQUIRED", status=503):
    if not value:
        raise DomainError(code, "具名复核须真实固定输出、参与者、来源与当前专业依据。", status)


def instant(value):
    at = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    require(at.tzinfo is not None and at.utcoffset() is not None, "FACT_TIME_INVALID", 422)
    return at.astimezone(UTC)


@dataclass(frozen=True)
class ActualReviewApplicability:
    """Material from configured actual owner, never a client conclusion/flag."""

    session: object
    caller: Context
    product_id: UUID
    anchor_sha256: str
    candidate_ref: object
    conclusion: Literal["applicable", "not_applicable", "unknown"]
    pairs: tuple[PairApplicability, ...]
    actions: tuple[ActionFulfillment, ...]
    owner_material: dict
    sources: tuple
    reads: tuple
    checked_at: datetime
    valid_until: datetime | None
    time_constraints: tuple[datetime, ...] = ()


def _checked_refs(s, ctx, pid, value):
    value = _wire(value)
    if isinstance(value, dict):
        if {"id", "revision", "kind", "position"} <= value.keys():
            return (a.SourceRef.model_validate(value),)
        if {"artifact_id", "expected_revision", "line", "quote"} <= value.keys():
            # Quote can be only part of the actual whole line. Never hash the
            # client quote and pretend it is the complete line's locator.
            return evidence.refs_from_exact(
                s, ctx, pid, (DefinitionReference.model_validate(value),)
            )
        return tuple(ref for child in value.values() for ref in _checked_refs(s, ctx, pid, child))
    if isinstance(value, list):
        return tuple(ref for child in value for ref in _checked_refs(s, ctx, pid, child))
    return ()


def _coverage(payload, candidate, saved):
    require(
        tuple(v.mapping for v in payload.pair_applicability) == candidate.binding.mappings,
        "FACT_REVIEW_PAIR_COVERAGE_MISMATCH",
        409,
    )
    required = _action_bindings(saved)
    require(
        {v.action_id for v in payload.action_fulfillment} == {v.action_id for v in required},
        "FACT_REVIEW_ACTION_COVERAGE_MISMATCH",
        409,
    )
    require(
        {v.failure_id for v in candidate.binding.mappings}
        == {v.identity for v in saved.origin.issue.failures},
        "FACT_REVIEW_FAILURE_COVERAGE_MISMATCH",
        409,
    )


def _independent(ctx, participants):
    require(
        ctx.actor_id not in {v.id for v in participants.participants},
        "INDEPENDENT_REVIEWER_REQUIRED",
        403,
    )


def _source(value):
    """Normalize compatible typed source subclasses, preserving every field."""
    if value is None:
        return None
    require(isinstance(value, a.SourceRef), "FACT_TYPED_SOURCE_REQUIRED")
    return a.SourceRef.model_validate(value.model_dump(mode="json"))


def _sources(values):
    return tuple(_source(v) for v in values)


def _port(owner, name):
    value = getattr(owner, name, None)
    return id(getattr(value, "__func__", value))


class ActualNamedReviewOwner:
    """Trusted startup composition. Raw StoragePairReader cannot satisfy it."""

    def __init__(
        self, fact_owner, *, candidate_semantic_owner, paired_owner=None, applicability_owner=None
    ):
        self.fact_owner = fact_owner
        self.candidate_semantic_owner = candidate_semantic_owner
        self.paired_owner = paired_owner
        self.applicability_owner = applicability_owner

    def runtime_stamp(self, s):
        owner = self.fact_owner
        require(
            all(
                callable(getattr(owner, k, None))
                for k in ("_rule", "_anchor", "_authority", "runtime_stamp")
            )
        )
        return digest(
            {
                "fact_owner": [id(owner), owner.runtime_stamp(s)],
                "candidate": [id(self.candidate_semantic_owner), id(read_candidate)],
                "paired_owner": [
                    id(self.paired_owner),
                    getattr(self.paired_owner, "epoch", None),
                    *(_port(self.paired_owner, v) for v in ("read", "refresh", "attest")),
                ],
                "applicability_owner": [
                    id(self.applicability_owner),
                    getattr(self.applicability_owner, "epoch", None),
                    *(_port(self.applicability_owner, v) for v in ("read", "refresh")),
                ],
                "ports": [
                    id(read_stored_fact),
                    id(read_participants),
                    id(refresh_participants),
                    id(read_source_closure),
                    id(policy.assess),
                    id(paired.read_paired_formal_output),
                ],
            }
        )

    def _phase(self, s, ctx, captured, caller, stamp):
        guards._same_uow(s, captured, ctx, caller)
        require(self.runtime_stamp(s) == stamp, "SOURCE_STALE", 409)

    def _candidate(self, s, ctx, pid, payload):
        require(
            type(self.candidate_semantic_owner) is CandidateSemanticOwner,
            "CANDIDATE_SEMANTIC_OWNER_REQUIRED",
        )
        return read_candidate(
            s,
            ctx,
            pid,
            payload.candidate.id,
            payload.candidate,
            semantic_owner=self.candidate_semantic_owner,
        )

    def _pair(self, s, ctx, pid, binding):
        reader = self.paired_owner
        require(
            reader is not None
            and all(callable(getattr(reader, k, None)) for k in ("read", "refresh", "attest")),
            "LIVE_PAIRED_OWNER_REQUIRED",
        )
        # Capture actual material before the live wrapper's independent late
        # refresh, then compare its complete structural SHA. A raw DTO is never
        # the live-gate substitute.
        raw = reader.read(s, ctx, pid, binding.output_ref, at=datetime.now(UTC), write=False)
        require(
            type(raw) is paired.ServerPairRead and raw.binding == binding,
            "FACT_REVIEW_PAIR_SCOPE_MISMATCH",
            409,
        )
        inspected = paired.verify_paired_material(binding, raw.material, at=datetime.now(UTC))
        require(inspected.proof is not None, "FACT_REVIEW_PAIRED_MATERIAL_MISSING")
        live = paired.read_paired_formal_output(
            s,
            ctx,
            pid,
            binding.output_ref,
            at=datetime.now(UTC),
            reader=reader,
            write=False,
        )
        require(
            live.structure is not None and live.host_gate is not None and not live.missing,
            "LIVE_PAIRED_OWNER_REQUIRED",
        )
        require(
            live.structure == inspected.proof and live.structure.meaning == "performed",
            "FACT_REVIEW_PAIR_NOT_PERFORMED",
            409,
        )
        require(not live.host_gate.needs_review, "PAIR_PROFESSIONAL_STALE", 409)
        return raw, live

    def _mapping_pairs(self, candidate, pairs):
        by_run = {
            (v[0].material.run_after.ref.id, v[0].material.run_after.ref.revision): v[0]
            for v in pairs
        }
        for mapping in candidate.binding.mappings:
            read = by_run.get((mapping.run.id, mapping.run.revision))
            require(read is not None, "FACT_REVIEW_PAIR_CURRENT_MISMATCH", 409)
            run = read.material.run_after.snapshot
            sample = next((v for v in run.samples if v.id == mapping.sample_id), None)
            require(
                sample is not None
                and sample.revision == mapping.sample_revision
                and (sample.actual_configuration.id, sample.actual_configuration.revision)
                == (mapping.actual_configuration_id, mapping.actual_configuration_revision)
                and any(
                    v.id == mapping.item_id for v in read.material.request_after.snapshot.items
                ),
                "FACT_REVIEW_PAIR_SCOPE_MISMATCH",
                409,
            )
            if mapping.measurement_id is not None:
                require(
                    any(
                        v.id == mapping.measurement_id
                        and v.coverage.sample_id == mapping.sample_id
                        and v.coverage.item_id == mapping.item_id
                        for v in run.measurements
                    ),
                    "FACT_REVIEW_PAIR_MEASUREMENT_MISMATCH",
                    409,
                )
            if mapping.projection_id is not None:
                require(
                    read.material.projection is not None
                    and read.material.projection.ref.id == mapping.projection_id,
                    "FACT_REVIEW_PAIR_PROJECTION_MISMATCH",
                    409,
                )

    def _bindings(self, s, ctx, pid, saved, candidate):
        raw = _Read(s, ctx, pid, saved.origin)
        result = {}
        for mapping in candidate.binding.mappings:
            row = raw.one(
                VerificationRunVersion.__table__, id=mapping.run.id, revision=mapping.run.revision
            )
            run = TestRun.model_validate(row["run_snapshot"])
            require(
                digest(row["run_snapshot"]) == row["snapshot_sha256"]
                and run.scope == saved.origin.scope
                and (run.id, run.revision, run.request_id)
                == (row["run_id"], row["revision"], row["request_id"])
                and (run.build.id, run.build.revision, run.build.product_id, run.build.project_id)
                == (row["build_id"], row["build_revision"], pid, saved.origin.scope.project_id),
                "FACT_REVIEW_PAIR_SCOPE_MISMATCH",
                409,
            )
            current = raw.one(FormalVerificationCurrent.__table__, request_id=row["request_id"])
            binding = paired.PairBinding(
                scope=saved.origin.scope,
                build=run.build,
                request_id=row["request_id"],
                run_id=row["run_id"],
                purpose=saved.origin.purpose,
                caller_id=ctx.actor_id,
                output_ref={
                    "id": current["request_version_id"],
                    "revision": current["request_revision"],
                },
            )
            result[(row["id"], row["revision"])] = binding
        raw.finish()
        return tuple(result.values())

    def _applicability(self, s, ctx, pid, saved, candidate, payload, pairs, observations):
        positive = payload.conclusion != "unknown" or any(
            v.conclusion != "unknown"
            for v in (*payload.pair_applicability, *payload.action_fulfillment)
        )
        if not positive:
            actions = {v.action_id: v for v in _action_bindings(saved)}
            return (
                None,
                tuple(
                    PairApplicability.model_validate(v.model_dump(mode="json"))
                    for v in payload.pair_applicability
                ),
                tuple(
                    ActionFulfillment(
                        action=actions[v.action_id],
                        classification="unknown",
                        conclusion="unknown",
                        reason=v.reason,
                        owner_refs=v.sources,
                        owner_material={
                            "actual_candidate": payload.candidate.model_dump(mode="json"),
                            "classification": None,
                            "fulfillment": None,
                        },
                    )
                    for v in payload.action_fulfillment
                ),
            )
        owner = self.applicability_owner
        require(
            owner is not None
            and all(callable(getattr(owner, k, None)) for k in ("read", "refresh")),
            "FACT_APPLICABILITY_OWNER_REQUIRED",
        )
        actual = owner.read(
            s,
            ctx,
            pid,
            payload,
            anchor=saved,
            candidate=candidate,
            pairs=pairs,
            observations=observations,
        )
        self._check_applicability(s, ctx, pid, saved, candidate, payload, actual)
        return actual, actual.pairs, actual.actions

    def _check_applicability(self, s, ctx, pid, saved, candidate, payload, actual):
        require(
            type(actual) is ActualReviewApplicability
            and actual.session is s
            and actual.caller is ctx
            and actual.product_id == pid
            and actual.anchor_sha256 == saved.anchor_sha256
            and actual.candidate_ref == candidate.ref,
            "FACT_APPLICABILITY_OWNER_REQUIRED",
        )
        require(actual.conclusion == payload.conclusion, "FACT_APPLICABILITY_MISMATCH", 409)
        require(
            tuple(v.mapping for v in actual.pairs)
            == tuple(v.mapping for v in payload.pair_applicability)
            and {v.action.action_id for v in actual.actions}
            == {v.action_id for v in payload.action_fulfillment},
            "FACT_REVIEW_PAIR_COVERAGE_MISMATCH",
            409,
        )
        for actual_pair, requested in zip(actual.pairs, payload.pair_applicability, strict=True):
            require(
                (
                    _source(actual_pair.method),
                    _source(actual_pair.criterion),
                    actual_pair.conclusion,
                    actual_pair.reason,
                    _sources(actual_pair.sources),
                )
                == (
                    _source(requested.method),
                    _source(requested.criterion),
                    requested.conclusion,
                    requested.reason,
                    _sources(requested.sources),
                ),
                "FACT_APPLICABILITY_MISMATCH",
                409,
            )
        fixed = {v.action_id: v for v in _action_bindings(saved)}
        requested_actions = {v.action_id: v for v in payload.action_fulfillment}
        for actual_action in actual.actions:
            selected = requested_actions[actual_action.action.action_id]
            require(
                actual_action.action == fixed[selected.action_id]
                and (actual_action.conclusion, actual_action.reason)
                == (selected.conclusion, selected.reason)
                and _sources(actual_action.owner_refs) == _sources(selected.sources),
                "FACT_APPLICABILITY_MISMATCH",
                409,
            )
        at = datetime.now(UTC)
        require(
            actual.checked_at <= at
            and (actual.valid_until is None or at < actual.valid_until)
            and all(at < value for value in actual.time_constraints),
            "SOURCE_STALE",
            409,
        )

    def read(self, s, ctx, pid, payload, *, previous=None, new_write=True):
        require(type(payload) is commands.NamedReviewPayload, "FACT_TYPED_PAYLOAD_REQUIRED")
        payload = commands.payload_for("review", payload)
        require(
            isinstance(ctx, Context) and ctx.actor_id == ctx.requester_id and ctx.run_id is None,
            "FORBIDDEN_SCOPE",
            403,
        )
        captured, caller, stamp = guards._uow(s), digest(vars(ctx)), self.runtime_stamp(s)
        with s.no_autoflush:
            guards._acl(s, ctx, pid)
            rule, saved = self.fact_owner._rule(s, ctx, pid, payload)
            require(previous is None or saved == previous.anchor, "SOURCE_STALE", 409)
            current = self.fact_owner._anchor(s, ctx, pid, saved)
            origin = saved.origin
            require(
                (origin.scope.tenant_id, origin.scope.product_id) == (ctx.tenant_id, pid)
                and (origin.issue_id, origin.issue.capa.id, origin.visibility)
                == (payload.issue_id, payload.capa_id, payload.visibility),
                "FORBIDDEN_SCOPE",
                403,
            )
            require(
                not new_write or current.revision == payload.expected_issue_revision,
                "VERSION_CONFLICT",
                409,
            )
            require(payload.at.occurred_at <= datetime.now(UTC), "FACT_TIME_INVALID", 409)
            candidate = self._candidate(s, ctx, pid, payload)
            require(
                candidate.body.stable_anchor == saved and candidate.origin.current.ref == current,
                "SOURCE_STALE",
                409,
            )
            _coverage(payload, candidate, saved)
            observations = []
            for selected in payload.observations:
                stored = read_stored_fact(s, ctx, pid, "observation", selected)
                value = stored.fact
                require(
                    stored.registry.state == "current_registered"
                    and value.rule == rule.ref
                    and value.anchor_sha256 == saved.anchor_sha256
                    and value.scope == origin.scope
                    and value.purpose == origin.purpose
                    and value.capa_id == origin.issue.capa.id,
                    "SOURCE_STALE",
                    409,
                )
                observations.append(stored)
            bindings = self._bindings(s, ctx, pid, saved, candidate)
            participants = read_participants(
                s, ctx, pid, anchor=saved, pairs=bindings, observations=payload.observations
            )
            _independent(ctx, participants)
            pairs = tuple(self._pair(s, ctx, pid, v) for v in bindings)
            self._mapping_pairs(candidate, pairs)
            applicability, reviewed_pairs, reviewed_actions = self._applicability(
                s,
                ctx,
                pid,
                saved,
                candidate,
                payload,
                pairs,
                observations,
            )
            authority, authority_sources = self.fact_owner._authority(
                s,
                ctx,
                pid,
                origin,
                commands.REVIEW_OPERATION,
            )
            policy_value = deepcopy(
                policy.assess(s, ctx, pid, origin.scope.project_id, origin.purpose)
            )
            require(
                policy_value.get("nature") == origin.nature
                and policy.policy_time_current(policy_value, datetime.now(UTC)),
                "CURRENT_POLICY_OWNER_REQUIRED",
            )
            bounds = [
                rule.valid_until,
                participants.valid_until,
                *participants.time_constraints,
                *(v[1].host_gate.valid_until for v in pairs),
                *(value for _, live in pairs for value in live.host_gate.time_constraints),
            ]
            sources = a.canonical_sources(
                (
                    *saved.origin_sources,
                    *rule.sources,
                    *payload.sources,
                    *authority_sources,
                    *_checked_refs(s, ctx, pid, payload),
                    *_checked_refs(s, ctx, pid, [v[0].material for v in pairs]),
                    *(ref for v in participants.participants for ref in v.owner_sources),
                    *(ref for v in observations for ref in v.fact.sources),
                    *(a.SourceRef.model_validate(v) for v in policy_value["sources"]),
                    *(applicability.sources if applicability else ()),
                )
            )
            reads = a.canonical_reads(
                (
                    *saved.origin_required_source_read_set,
                    *rule.required_source_read_set,
                    *candidate.inspection.required_source_read_set,
                    *participants.required_source_read_set,
                    *authority["required_source_read_set"],
                    *policy_value["required_source_read_set"],
                    *(read for v in observations for read in v.fact.required_source_read_set),
                    *(read for v in pairs for read in v[1].structure.required_source_read_set),
                    *(applicability.reads if applicability else ()),
                    *(
                        a.SourceRead(artifact_id=v.id, expected_revision=v.revision)
                        for v in sources
                        if v.kind == "artifact"
                    ),
                )
            )
            if applicability:
                bounds.append(applicability.valid_until)
                bounds.extend(applicability.time_constraints)
            closure = read_source_closure(
                s,
                ctx,
                pid,
                scope=origin.scope,
                owner_id=origin.owner_id,
                visibility=origin.visibility,
                sources=sources,
                reads=reads,
                expected_basis=saved.origin_source_basis,
                boundaries=bounds,
            )
            # Every owner callback and byte IO is followed by independent actual
            # source/participant/pair/candidate/rule/current/professional checks.
            late_participants = refresh_participants(
                s,
                ctx,
                pid,
                participants,
                anchor=saved,
                pairs=bindings,
                observations=payload.observations,
            )
            _independent(ctx, late_participants)
            for selected, old in zip(payload.observations, observations, strict=True):
                actual = read_stored_fact(s, ctx, pid, "observation", selected)
                require(
                    actual.fact == old.fact
                    and actual.registry == old.registry
                    and actual.group_sha256 == old.group_sha256,
                    "SOURCE_STALE",
                    409,
                )
            for binding, (_raw, old) in zip(bindings, pairs, strict=True):
                _last, actual = self._pair(s, ctx, pid, binding)
                require(
                    actual.structure == old.structure
                    and tuple((v.kind, v.basis_sha256) for v in actual.host_gate.stamps)
                    == tuple((v.kind, v.basis_sha256) for v in old.host_gate.stamps)
                    and actual.host_gate.valid_until == old.host_gate.valid_until,
                    "SOURCE_STALE",
                    409,
                )
            if applicability:
                actual = self.applicability_owner.refresh(
                    s,
                    ctx,
                    pid,
                    payload,
                    applicability,
                    anchor=saved,
                    candidate=candidate,
                    pairs=pairs,
                    observations=observations,
                )
                self._check_applicability(s, ctx, pid, saved, candidate, payload, actual)
                require(
                    _wire(actual.owner_material) == _wire(applicability.owner_material)
                    and actual.pairs == applicability.pairs
                    and actual.actions == applicability.actions
                    and actual.sources == applicability.sources
                    and actual.reads == applicability.reads
                    and actual.valid_until == applicability.valid_until,
                    "SOURCE_STALE",
                    409,
                )
            late_candidate = self._candidate(s, ctx, pid, payload)
            require(
                late_candidate.ref == candidate.ref
                and late_candidate.binding == candidate.binding
                and late_candidate.group == candidate.group,
                "SOURCE_STALE",
                409,
            )
            late_rule, late_saved = self.fact_owner._rule(s, ctx, pid, payload)
            require(
                late_rule == rule
                and late_saved == saved
                and self.fact_owner._anchor(s, ctx, pid, saved) == current,
                "SOURCE_STALE",
                409,
            )
            late_authority, late_sources = self.fact_owner._authority(
                s, ctx, pid, origin, commands.REVIEW_OPERATION
            )
            require(
                late_authority == authority
                and late_sources == authority_sources
                and policy.assess(s, ctx, pid, origin.scope.project_id, origin.purpose)
                == policy_value,
                "SOURCE_STALE",
                409,
            )
            final = read_source_closure(
                s,
                ctx,
                pid,
                scope=origin.scope,
                owner_id=origin.owner_id,
                visibility=origin.visibility,
                sources=sources,
                reads=reads,
                expected_basis=a.canonical_basis(closure.source_basis, reads),
                boundaries=bounds,
            )
            require(final.material_sha256 == closure.material_sha256, "SOURCE_STALE", 409)
            self._phase(s, ctx, captured, caller, stamp)
            checked, time_constraints = _deadline(
                s, ctx, pid, (*bounds, final.valid_until, *final.time_constraints)
            )
            require(payload.at.occurred_at <= checked, "FACT_TIME_INVALID", 409)
            body = {
                "kind": "review",
                "previous": None,
                "scope": origin.scope.model_dump(mode="json"),
                "issue_id": str(origin.issue_id),
                "capa_id": str(origin.issue.capa.id),
                "purpose": origin.purpose,
                "anchor_sha256": saved.anchor_sha256,
                "requirement_sha256": digest(origin.issue.capa.requirement.model_dump(mode="json")),
                "nature": origin.nature,
                "owner_id": str(origin.owner_id),
                "visibility": origin.visibility,
                "sources": _wire(sources),
                "required_source_read_set": _wire(reads),
                "source_basis": final.source_basis,
                "candidate": payload.candidate.model_dump(mode="json"),
                "candidate_sha256": payload.candidate.sha256,
                "rule": payload.rule.model_dump(mode="json"),
                "observations": _wire(payload.observations),
                "reviewer_id": str(ctx.actor_id),
                "at": payload.at.model_dump(mode="json"),
                "pair_applicability": _wire(reviewed_pairs),
                "action_fulfillment": _wire(reviewed_actions),
                "participants": _wire(participants.participants),
                "participant_owner_material": participants.owner_material,
                "conclusion": payload.conclusion,
                "reason": payload.reason,
                "authority_snapshot": authority,
                "policy_snapshot": policy_value,
                "valid_until": None,
            }
            value = FactWriteMaterial(
                body_material=body,
                anchor=saved,
                current_issue_version_id=current.id,
                current_issue_revision=current.revision,
                series=None,
                authority_snapshot=authority,
                policy_snapshot=policy_value,
                inspection={
                    "candidate": _wire(payload.candidate),
                    "pairs": [v[1].structure.model_dump(mode="json") for v in pairs],
                    "participant_material_sha256": participants.material_sha256,
                    "source_material_sha256": final.material_sha256,
                    "missing": sorted(set(participants.missing) | set(final.missing)),
                    "applicable": None,
                    "independently_verified": None,
                    "observation_complete": None,
                    "effectiveness": "indeterminate",
                    "close": False,
                },
                time_constraints=time_constraints,
            )
            # Construction is pure; recheck its real deadline/UOW/runtime after it.
            from .fact_write import _time_current

            require(_time_current(value, datetime.now(UTC)), "SOURCE_STALE", 409)
            self._phase(s, ctx, captured, caller, stamp)
            return value
