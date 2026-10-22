"""Read-only eligibility for one explicitly selected CAPA review candidate.

This projection is neither a review payload nor an effectiveness decision.
The common preview/write owner independently repeats all actual checks.
"""

# Common registry initializes before domain children.
# ruff: noqa: I001
from dataclasses import dataclass
from datetime import UTC, datetime

from pdos_next.service import digest
from pdos_next.errors import DomainError
from pdos_next.domain.quality_execution import policy
from pdos_next.domain.professional_authority.service import authority_time_current
from pdos_next.domain.capa_effectiveness import anchor as a
from pdos_next.domain.capa_effectiveness import fact_atom_storage as guards
from pdos_next.domain.capa_effectiveness import fact_commands as commands
from pdos_next.domain.capa_effectiveness.fact_registry_storage import read_stored_fact
from pdos_next.domain.capa_effectiveness.fact_sources_owner import read_source_closure, _wire
from pdos_next.domain.capa_effectiveness.named_review_owner import (
    ActualNamedReviewOwner,
    _checked_refs,
    _independent,
    require,
)
from pdos_next.domain.capa_effectiveness.participants_owner import read_participants


@dataclass(frozen=True)
class ReviewSelectionRead:
    choices: tuple[dict, ...]
    sources: tuple
    reads: tuple
    basis_sha256: str
    valid_until: datetime | None
    time_constraints: tuple[datetime, ...] = ()


def read_review_selection(s, ctx, pid, fact_owner, rule, saved, candidate, observations):
    """Use live owners with the actual caller/UOW, without inventing a decision."""
    owner = fact_owner.review_owner
    require(type(owner) is ActualNamedReviewOwner, "FACT_REVIEW_OWNER_REQUIRED")
    captured, caller, runtime = guards._uow(s), digest(vars(ctx)), owner.runtime_stamp(s)
    with s.no_autoflush:
        guards._acl(s, ctx, pid)
        current = fact_owner._anchor(s, ctx, pid, saved)
        require(
            candidate.body.stable_anchor == saved and candidate.origin.current.ref == current,
            "SOURCE_STALE",
            409,
        )
        require(
            bool(candidate.binding.mappings)
            and {v.failure_id for v in candidate.binding.mappings}
            == {v.identity for v in saved.origin.issue.failures},
            "FACT_REVIEW_FAILURE_COVERAGE_MISMATCH",
            409,
        )
        require(bool(observations), "FACT_REVIEW_OBSERVATION_REQUIRED", 409)
        stored_observations = []
        for ref in observations:
            stored = read_stored_fact(s, ctx, pid, "observation", ref)
            value = stored.fact
            require(
                stored.registry.state == "current_registered"
                and value.rule == rule.ref
                and value.anchor_sha256 == saved.anchor_sha256
                and value.scope == saved.origin.scope
                and value.purpose == saved.origin.purpose
                and value.capa_id == saved.origin.issue.capa.id,
                "SOURCE_STALE",
                409,
            )
            stored_observations.append(stored)
        bindings = owner._bindings(s, ctx, pid, saved, candidate)
        participants = read_participants(
            s, ctx, pid, anchor=saved, pairs=bindings, observations=observations
        )
        _independent(ctx, participants)
        pairs = tuple(owner._pair(s, ctx, pid, binding) for binding in bindings)
        owner._mapping_pairs(candidate, pairs)
        by_run = {
            (raw.material.run_after.ref.id, raw.material.run_after.ref.revision): raw
            for raw, _ in pairs
        }
        choices = []
        for index, mapping in enumerate(candidate.binding.mappings):
            raw = by_run[(mapping.run.id, mapping.run.revision)]
            item = next(
                v for v in raw.material.request_after.snapshot.items if v.id == mapping.item_id
            )
            criterion = (
                item.criterion.source if item.criterion is not None else item.criterion_source
            )
            choices.append(
                {
                    "key": f"{candidate.ref.id}:{index}",
                    "label": f"{item.feature} · 样件 {mapping.sample_id}",
                    "detail": (
                        f"实际测试第 {mapping.run.revision} 版；固定对应失败 {mapping.failure_id}"
                    ),
                    "mapping": mapping.model_dump(mode="json"),
                    "method": item.method.model_dump(mode="json") if item.method else None,
                    "criterion": criterion.model_dump(mode="json") if criterion else None,
                    "visibility": raw.material.run_after.visibility,
                }
            )
        authority, refs = fact_owner._authority(
            s, ctx, pid, saved.origin, commands.REVIEW_OPERATION
        )
        active_policy = policy.assess(
            s, ctx, pid, saved.origin.scope.project_id, saved.origin.purpose
        )
        require(
            authority_time_current(authority, datetime.now(UTC))
            and policy.policy_time_current(active_policy, datetime.now(UTC)),
            "SOURCE_STALE",
            409,
        )
        sources = a.canonical_sources(
            (
                *saved.origin_sources,
                *rule.sources,
                *refs,
                *_checked_refs(s, ctx, pid, [raw.material for raw, _ in pairs]),
                *(ref for person in participants.participants for ref in person.owner_sources),
                *(ref for stored in stored_observations for ref in stored.fact.sources),
                *(a.SourceRef.model_validate(v) for v in active_policy["sources"]),
            )
        )
        reads = a.canonical_reads(
            (
                *saved.origin_required_source_read_set,
                *rule.required_source_read_set,
                *candidate.inspection.required_source_read_set,
                *participants.required_source_read_set,
                *authority["required_source_read_set"],
                *active_policy["required_source_read_set"],
                *(
                    read
                    for stored in stored_observations
                    for read in stored.fact.required_source_read_set
                ),
                *(read for _, live in pairs for read in live.structure.required_source_read_set),
                *(
                    a.SourceRead(artifact_id=ref.id, expected_revision=ref.revision)
                    for ref in sources
                    if ref.kind == "artifact"
                ),
            )
        )
        bounds = (
            rule.valid_until,
            participants.valid_until,
            *participants.time_constraints,
            *(live.host_gate.valid_until for _, live in pairs),
            *(value for _, live in pairs for value in live.host_gate.time_constraints),
        )
        closure = read_source_closure(
            s,
            ctx,
            pid,
            scope=saved.origin.scope,
            owner_id=saved.origin.owner_id,
            visibility=saved.origin.visibility,
            sources=sources,
            reads=reads,
            expected_basis=saved.origin_source_basis,
            boundaries=bounds,
        )
        # Public context repeats this whole read after rendering source options.
        owner._phase(s, ctx, captured, caller, runtime)
        time_constraints = tuple(
            value
            for value in (*bounds, closure.valid_until, *closure.time_constraints)
            if value is not None
        )
        require(all(datetime.now(UTC) < value for value in time_constraints), "SOURCE_STALE", 409)
        material = {
            "candidate": candidate.ref.model_dump(mode="json"),
            "group": candidate.group,
            "current": current.model_dump(mode="json"),
            "rule": rule.model_dump(mode="json"),
            "observations": [
                {"fact": _wire(v.fact), "registry": _wire(v.registry), "group": v.group_sha256}
                for v in stored_observations
            ],
            "participants": _wire(participants.participants),
            "pairs": [
                {
                    "structure": _wire(live.structure),
                    "stamps": [(v.kind, v.basis_sha256) for v in live.host_gate.stamps],
                }
                for _, live in pairs
            ],
            "authority": authority,
            "policy": active_policy,
            "sources": closure.material_sha256,
            "choices": choices,
        }
        return ReviewSelectionRead(
            tuple(choices), sources, reads, digest(material), None, time_constraints
        )


def verify_review_selection(previous, current):
    if (
        previous.basis_sha256 != current.basis_sha256
        or previous.reads != current.reads
        or previous.sources != current.sources
        or previous.valid_until != current.valid_until
        or previous.time_constraints != current.time_constraints
    ):
        raise DomainError("SOURCE_STALE", "读取期间候选、参与者或实际复验依据已变化。", 409)
