"""Formal-change completion classification from actual approved execution owners.

This does not replace the existing exact nine-field actual completion verifier.
Missing/invalid formal implementation never falls back to investigation.
"""

import hashlib
import json
from datetime import datetime

from sqlalchemy import select

from pdos_next import change_controlled_owner as controlled
from pdos_next import change_order_store as store
from pdos_next.change_implementation_owner import (
    ApprovedImplementationOwner,
    Occurrence,
    original_occurrence,
)
from pdos_next.change_order_service import _one, current_fixed
from pdos_next.clock import deadline_current, earliest_deadline
from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow, _uow
from pdos_next.domain.change_execution import service as change
from pdos_next.domain.quality_execution import policy
from pdos_next.domain.quality_execution.evidence import merge_reads, union_sources
from pdos_next.domain.quality_followup.evidence import _constant, _pairs
from pdos_next.domain.quality_followup.schemas import CompletionAssessment
from pdos_next.errors import DomainError
from pdos_next.service import digest, source_for

SCHEMA = "pdos-change-implementation-occurrence-v2"


def _runtime(s):
    engine = s.get_bind()
    issuers = getattr(engine, "_pdos_quality_policy_issuers", {})
    return digest(
        {
            "change": change._runtime_stamp(s),
            "quality_issuers": {k: [id(v), v.epoch] for k, v in issuers.items()},
            "quality_epochs": getattr(engine, "_pdos_quality_policy_epochs", {}),
            "followup": id(getattr(engine, "_pdos_quality_followup", None)),
            "order_owner": id(getattr(engine, "_pdos_change_order_runtime", None)),
        }
    )


def _is_occurrence(s, ctx, pid, source):
    """Discriminator only. Positive classification always uses real full owners."""
    if source.kind != "artifact":
        return False
    artifact = source_for(s, ctx, pid, source.id, source.revision)
    match = change.POSITION.fullmatch(source.position)
    controlled.require(match is not None, "MISSING_REQUIRED_EVIDENCE", 422)
    lines = artifact.content.splitlines()
    number = int(match[1])
    controlled.require(0 < number <= len(lines), "MISSING_REQUIRED_EVIDENCE", 422)
    line = lines[number - 1]
    controlled.require(hashlib.sha256(line.encode()).hexdigest() == match[2], "SOURCE_STALE")
    try:
        value = json.loads(line, object_pairs_hook=_pairs, parse_constant=_constant)
    except (ValueError, TypeError) as error:
        if SCHEMA in line:
            raise DomainError("MISSING_REQUIRED_EVIDENCE", "正式实施原行结构无效。", 422) from error
        return False  # Unstructured investigation material is not a formal-owner claim.
    return isinstance(value, dict) and value.get("schema_version") == SCHEMA


def _matches(observed, basis, binding, completion, ctx):
    controlled.require(type(observed) is Occurrence, "IMPLEMENTATION_OWNER_REQUIRED", 503)
    controlled.require(
        observed.scope == basis.scope
        and observed.issue_id == basis.issue_id
        and observed.capa_id == basis.capa_id
        and observed.action_id == binding.action_id
        and observed.action_sha256 == binding.action_sha256
        and observed.executor_id == binding.executor_id == ctx.requester_id
        and observed.purpose == basis.purpose
        and observed.nature == basis.nature
        and observed.outcome == "succeeded"
        and observed.occurred_at <= completion.at.occurred_at,
        "ACTION_IMPLEMENTATION_MISMATCH",
    )


class FormalChangeCompletionOwner:
    """Explicit startup object; no client JSON or product Grant creates its proof."""

    def __init__(self, engine, *, investigation=None):
        if investigation is not None and not callable(investigation):
            raise TypeError("Investigation callback must be explicit trusted startup configuration")
        self.engine = engine
        self.investigation = investigation
        self.implementation = ApprovedImplementationOwner(engine)
        self.action_intent = controlled.ApprovedActionIntentOwner()

    def __call__(
        self, s, ctx, pid, basis, action, completion, *, policy_snapshot, observation, write=False
    ):
        controlled.require(s.get_bind() is self.engine, "INTEGRATION_REQUIRED", 503)
        uow, stamp = _uow(s), _runtime(s)
        caller, caller_until = controlled._caller(s, ctx, pid, write=write)
        _, project = controlled._project(s, ctx, basis.scope)
        binding = next((v for v in basis.actions if v.action_id == action.id), None)
        controlled.require(binding is not None, "ACTION_CONFLICT")
        matches = [source for source in completion.evidence if _is_occurrence(s, ctx, pid, source)]
        if not matches:
            if self.investigation is None:
                raise DomainError("INTEGRATION_REQUIRED", "缺受控实际完成分类owner。", 503)
            return self.investigation(
                s,
                ctx,
                pid,
                basis,
                action,
                completion,
                policy_snapshot=policy_snapshot,
                observation=observation,
                write=write,
            )
        controlled.require(len(matches) == 1, "AMBIGUOUS_IMPLEMENTATION_OWNER", 503)
        occurrence, _ = original_occurrence(s, ctx, pid, matches[0])
        _matches(occurrence, basis, binding, completion, ctx)
        captures = list(
            s.scalars(
                select(store.ImplementationCapture)
                .where(
                    store.ImplementationCapture.tenant_id == ctx.tenant_id,
                    store.ImplementationCapture.product_id == pid,
                    store.ImplementationCapture.project_id == basis.scope.project_id,
                    store.ImplementationCapture.change_id == occurrence.change_id,
                    store.ImplementationCapture.order_id == occurrence.order_id,
                    store.ImplementationCapture.item_id == occurrence.item_id,
                    store.ImplementationCapture.fact_id == occurrence.implementation_id,
                    store.ImplementationCapture.executor_id == ctx.requester_id,
                )
                .limit(2)
                .execution_options(populate_existing=True, autoflush=False)
            )
        )
        controlled.require(len(captures) == 1, "IMPLEMENTATION_OWNER_REQUIRED", 503)
        capture = captures[0]
        controlled.require(
            capture.occurrence_snapshot == occurrence.model_dump(mode="json")
            and matches[0].model_dump(mode="json") in capture.sources,
            "IMPLEMENTATION_OWNER_MISMATCH",
        )
        atom = _one(
            s,
            store.ChangeImplementationRecord,
            store.ChangeImplementationRecord.tenant_id == ctx.tenant_id,
            store.ChangeImplementationRecord.product_id == pid,
            store.ChangeImplementationRecord.project_id == basis.scope.project_id,
            store.ChangeImplementationRecord.capture_id == capture.id,
        )
        executed = self.implementation.read(
            s, ctx, pid, implementation_version_id=atom.change_version_id
        )
        selected = self.action_intent.read(
            s,
            ctx,
            pid,
            change_id=occurrence.change_id,
            order_id=occurrence.order_id,
            item_id=occurrence.item_id,
            action_id=binding.action_id,
        )
        controlled.require(
            executed.occurrence == occurrence
            and selected.action_sha256 == binding.action_sha256
            and selected.executor_id == binding.executor_id
            and selected.intent_id == occurrence.intent_id,
            "ACTION_IMPLEMENTATION_MISMATCH",
        )
        pointer, current = current_fixed(s, ctx, pid, occurrence.change_id)
        current_stamp = (pointer.id, current.id, current.request_sha256)
        authority, authority_until = controlled.authority(
            s, ctx, pid, basis.scope, "quality.capa.actions.complete", basis.purpose, write=write
        )
        controlled.require(
            basis.nature != "real" or authority.get("synthetic") is False, "NATURE_MISMATCH", 403
        )
        fresh_policy = policy.assess(s, ctx, pid, basis.scope.project_id, basis.purpose)
        controlled.require(fresh_policy == policy_snapshot, "SOURCE_STALE")
        sources = union_sources(
            basis.sources,
            completion.evidence,
            (completion.at.source,),
            tuple(executed.version.sources),
            selected.selection.sources,
            fresh_policy["sources"],
        )
        reads = merge_reads(
            basis.required_source_read_set,
            executed.version.required_source_read_set,
            selected.selection.required_source_read_set,
            fresh_policy["required_source_read_set"],
            authority["required_source_read_set"],
            change._source_reads(sources),
        )
        safety = controlled._source_guard(
            s, ctx, pid, basis.visibility, basis.owner_id, reads, sources
        )
        executed = self.implementation.refresh(s, ctx, pid, executed)
        selected = self.action_intent.refresh(s, ctx, pid, selected)
        proof = self.implementation.attest(s, ctx, pid, executed)
        # All byte/owner IO is complete. Independently recheck every current closure
        # and runtime before the final real clock; never reuse a prior phase permit.
        selected = self.action_intent.refresh(s, ctx, pid, selected)
        final_auth, final_until = controlled.authority(
            s, ctx, pid, basis.scope, "quality.capa.actions.complete", basis.purpose, write=write
        )
        controlled.require(
            final_auth == authority
            and policy.assess(s, ctx, pid, basis.scope.project_id, basis.purpose) == fresh_policy,
            "SOURCE_STALE",
        )
        controlled.require(
            controlled.same(
                controlled._source_guard(
                    s, ctx, pid, basis.visibility, basis.owner_id, reads, sources, io=False
                ),
                safety,
            ),
            "SOURCE_STALE",
        )
        last_pointer, last = current_fixed(s, ctx, pid, occurrence.change_id)
        controlled.require(
            (last_pointer.id, last.id, last.request_sha256) == current_stamp, "SOURCE_STALE"
        )
        controlled.require(
            controlled._project(s, ctx, basis.scope)[1] == project
            and controlled._caller(s, ctx, pid, write=write)[0] == caller
            and _runtime(s) == stamp,
            "SOURCE_STALE",
        )
        _same_uow(s, uow, ctx, digest(vars(ctx)))
        action_target = controlled.models.ActionTarget(
            issue_id=basis.issue_id,
            expected_issue_revision=basis.issue_revision,
            capa_id=basis.capa_id,
            action_id=binding.action_id,
        )
        latest_basis, latest_binding = controlled.action_basis(
            s, ctx, pid, action_target, basis.scope, basis.purpose
        )
        controlled.require(latest_basis == basis and latest_binding == binding, "SOURCE_STALE")
        latest_pointer, latest_change = current_fixed(s, ctx, pid, occurrence.change_id)
        controlled.require(
            (latest_pointer.id, latest_change.id, latest_change.request_sha256) == current_stamp,
            "SOURCE_STALE",
        )
        request = controlled.snapshot(latest_change)
        saved_order = next(v for v in request.orders if v.id == occurrence.order_id)
        approval_until = controlled.approved_order(s, ctx, pid, request, saved_order)
        final_auth, last_authority_until = controlled.authority(
            s, ctx, pid, basis.scope, "quality.capa.actions.complete", basis.purpose, write=write
        )
        controlled.require(
            final_auth == authority
            and policy.assess(s, ctx, pid, basis.scope.project_id, basis.purpose) == fresh_policy,
            "SOURCE_STALE",
        )
        controlled.require(
            controlled.same(
                controlled._source_guard(
                    s, ctx, pid, basis.visibility, basis.owner_id, reads, sources, io=False
                ),
                safety,
            ),
            "SOURCE_STALE",
        )
        controlled.require(
            controlled._project(s, ctx, basis.scope)[1] == project
            and controlled._caller(s, ctx, pid, write=write)[0] == caller
            and _runtime(s) == stamp,
            "SOURCE_STALE",
        )
        _same_uow(s, uow, ctx, digest(vars(ctx)))
        deadline = earliest_deadline(
            caller_until,
            authority_until,
            final_until,
            last_authority_until,
            approval_until,
            executed.valid_until,
            selected.selection.valid_until,
            datetime.fromisoformat(fresh_policy["valid_until"].replace("Z", "+00:00"))
            if fresh_policy.get("valid_until")
            else None,
        )
        controlled.require(deadline_current(deadline), "SOURCE_STALE")
        values = dict(
            scope=basis.scope,
            issue_id=basis.issue_id,
            capa_id=basis.capa_id,
            action_id=binding.action_id,
            executor_id=ctx.requester_id,
            purpose=basis.purpose,
            basis_sha256=basis.basis_sha256,
            action_sha256=binding.action_sha256,
            completion_sha256=digest(completion.model_dump(mode="json")),
            event_source=completion.at.source,
            policy_basis_sha256=digest(policy_snapshot),
            allowed=True,
            current=True,
            classification="formal_change",
            nature=basis.nature,
            reason_codes=(),
            # Quality sources are exact original lines. Native change-owner
            # references stay bound by the full implementation material in
            # owner_proofs; all sources above still pass the unchanged owner
            # refreshes and source guards before this projection.
            sources=[v.model_dump(mode="json") for v in sources if v.kind == "artifact"],
            owner_proofs=(proof,),
            required_source_read_set=reads,
            valid_until=deadline,
        )
        # Actual existing CompletionAssessment DTO normalizes the fields before its
        # self digest; no transaction/full FactRef SHA is invented here.
        result = CompletionAssessment.model_validate({**values, "proof_sha256": "0" * 64})
        return result.model_copy(
            update={
                "proof_sha256": digest(result.model_dump(mode="json", exclude={"proof_sha256"}))
            }
        )
