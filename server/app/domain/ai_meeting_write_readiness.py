"""Read actual generation provenance before considering direct meeting-draft capture.

The draft has not been inserted. Its identity comes from the trusted generation
transaction, never HTTP qualification candidates. This reader selects only from
operator-pinned evaluations and reproduces the original gateway suite pin via the
trial collector. It does not grant qualification, write, call models, authorize
scope or substitute for current rollout, content/source and monitoring gates.
Database errors propagate so the owning transaction can roll back safely.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, TypeAdapter, ValidationError
from sqlalchemy import Connection, Select, func, select

from app.ai.application_domain_context import bundle
from app.ai.observations import digest
from app.ai.write_evaluation_publication import (
    WriteEvaluationPublicationError,
    configured_write_evaluation_publication,
    select_write_evaluation,
)
from app.contracts.ai_write_qualification import DraftOperation, QualificationBinding
from app.db.schema import tables
from app.domain.ai_write_qualification_state import read_qualification_state
from app.domain.ai_write_trial_collection import _object, _verify


def generated_provenance_query(draft: dict[str, Any]) -> Select[Any]:
    """One original-call read with outer joins: absent evidence cannot disappear."""
    c, p = tables.model_invocations, tables.ai_write_policies
    o, r = tables.application_context_observations, tables.application_result_checkpoints
    m, b = tables.application_context_manifests, tables.budget_journal
    sources = (
        c.outerjoin(p, (p.c.tenant_id == c.c.tenant_id) & (p.c.id == draft["policy_id"]))
        .outerjoin(
            o,
            (o.c.tenant_id == c.c.tenant_id)
            & (o.c.run_id == c.c.run_id)
            & (o.c.model_call_id == c.c.budget_call_id),
        )
        .outerjoin(
            r,
            (r.c.tenant_id == c.c.tenant_id)
            & (r.c.run_id == c.c.run_id)
            & (r.c.model_call_id == c.c.budget_call_id)
            & (r.c.invocation_id == c.c.id),
        )
        .outerjoin(
            m,
            (m.c.tenant_id == c.c.tenant_id)
            & (m.c.run_id == c.c.run_id)
            & (m.c.id == r.c.manifest_id),
        )
        .outerjoin(
            b,
            (b.c.tenant_id == c.c.tenant_id)
            & (b.c.run_id == c.c.run_id)
            & (b.c.id == m.c.admission_id),
        )
    )
    return (
        select(
            *(
                func.to_jsonb(table.table_valued()).label(label)
                for table, label in (
                    (c, "call"),
                    (p, "policy"),
                    (o, "observation"),
                    (r, "checkpoint"),
                    (m, "manifest"),
                    (b, "admission"),
                )
            )
        )
        .select_from(sources)
        .where(
            c.c.tenant_id == draft["tenant_id"],
            c.c.project_id == draft["project_id"],
            c.c.run_id == draft["run_id"],
            c.c.id == draft["model_invocation_id"],
        )
        # A second match is sufficient to reject ambiguity; never take the first.
        .limit(2)
    )


def _matches_actual(candidate: QualificationBinding, row: dict[str, Any]) -> bool:
    call, policy = _object(row.get("call")), _object(row.get("policy"))
    manifest = _object(_object(row.get("manifest")).get("body"))
    compiled = _object(_object(_object(row.get("observation")).get("bundle")).get("compiled"))
    return (
        candidate.operation_key == "meeting." + row["draft"]["draft_kind"] + ".draft"
        and candidate.provider == call.get("provider")
        and candidate.model == call.get("model")
        and candidate.model_version == call.get("model_version")
        and candidate.release_bundle_version == manifest.get("release_bundle_version")
        and candidate.adapter_version == compiled.get("reader")
        and candidate.policy_version == policy.get("contract_version")
        and candidate.policy_revision == policy.get("revision")
    )


def assess_generated_write(
    connection: Connection, *, draft: dict[str, Any], as_of: datetime
) -> dict[str, Any]:
    """Assess materials in the caller's transaction; current is not a write grant.

    Unavailable means missing/unreadable materials; blocked means a concrete
    mismatch. qualification_state is the full original reader JSON once bound,
    otherwise None. reasons retain machine codes and safe human explanations.
    """
    result: dict[str, Any] = {
        "state": "unavailable",
        "binding": None,
        "qualification_state": None,
        "reasons": [],
        "qualification_granted": False,
        "source_receipt_digest": None,
        "evaluation_publication": None,
    }

    def stop(state: str, codes: tuple[str, ...]) -> dict[str, Any]:
        result["state"] = state
        result["reasons"] = [
            {"code": code, "message": "本次生成的原始依据或当前资格材料未通过核对。"}
            for code in sorted(set(codes))
        ]
        return result

    try:
        now = TypeAdapter(AwareDatetime).validate_python(as_of)
        created = TypeAdapter(AwareDatetime).validate_python(draft["created_at"])
        ids = {
            key: UUID(str(draft[key]))
            for key in (
                "id",
                "tenant_id",
                "project_id",
                "run_id",
                "model_invocation_id",
                "principal_id",
                "policy_id",
            )
        }
        operation: DraftOperation = TypeAdapter(DraftOperation).validate_python(
            "meeting." + draft["draft_kind"] + ".draft"
        )
        if created > now or draft.get("origin") != "ai":
            return stop("blocked", ("generated_draft_identity_invalid",))
    except (ValidationError, KeyError, ValueError, TypeError):
        return stop("blocked", ("generated_draft_identity_invalid",))
    original = dict(draft, **ids, created_at=created)
    rows = connection.execute(generated_provenance_query(original)).mappings().all()
    if not rows:
        return stop("unavailable", ("generated_call_missing",))
    if len(rows) != 1:
        return stop("blocked", ("generated_provenance_ambiguous",))
    row = dict(rows[0], draft=original, confirmed_at=None, edited_at=None, withdrawn_at=None)
    try:
        loaded = configured_write_evaluation_publication(
            os.environ, tenant_id=ids["tenant_id"], as_of=now
        )
    except WriteEvaluationPublicationError as error:
        return stop("unavailable", ("evaluation_publication_unavailable", error.code))
    if loaded is None:
        return stop("unavailable", ("evaluation_publication_missing",))
    candidates = [
        entry.evaluation.binding
        for entry in loaded.publication.evaluations
        if _matches_actual(entry.evaluation.binding, row)
    ]
    if not candidates:
        return stop("blocked", ("actual_call_evaluation_binding_missing",))
    verified = []
    blockers: set[str] = set()
    for candidate in candidates:
        try:
            evidence, reasons = _verify(row, candidate, "real_business")
        except (ValidationError, ValueError, KeyError, TypeError):
            evidence, reasons = None, ("generated_provenance_invalid",)
        if evidence is not None and not reasons:
            verified.append((candidate, evidence))
        else:
            blockers.update(reasons)
    if not verified:
        return stop("blocked", tuple(blockers or {"generated_provenance_unverified"}))
    if len(verified) != 1:
        return stop("blocked", ("generated_binding_ambiguous",))
    binding, evidence = verified[0]
    selected = select_write_evaluation(loaded, expected_binding=binding)
    result.update(
        binding=binding.model_dump(mode="json"),
        source_receipt_digest=evidence.receipt_digest,
        evaluation_publication=selected.model_dump(mode="json"),
    )
    try:
        current_bundle = bundle("meeting_" + original["draft_kind"])
        if (
            binding.release_bundle_version != "sha256:" + digest(current_bundle)
            or binding.adapter_version != current_bundle["compiled"]["reader"]
        ):
            return stop("blocked", ("runtime_bundle_changed",))
    except (OSError, ValueError, KeyError, TypeError):
        return stop("unavailable", ("runtime_bundle_unavailable",))
    try:
        state = read_qualification_state(
            connection,
            tenant_id=ids["tenant_id"],
            project_id=ids["project_id"],
            operation_key=operation,
            binding=binding,
            as_of=now,
        )
        result["qualification_state"] = state.model_dump(mode="json")
    except (ValidationError, ValueError, KeyError, TypeError):
        return stop("unavailable", ("qualification_material_unavailable",))
    if (
        state.binding != binding
        or state.tenant_id != ids["tenant_id"]
        or state.project_id != ids["project_id"]
        or state.operation_key != operation
        or state.checked_at != now
        or state.policy_id != ids["policy_id"]
    ):
        return stop("blocked", ("qualification_material_binding_changed",))
    if state.publication is not None and (
        state.publication.publication_sha256 != selected.publication_sha256
        or state.publication.publication_id != selected.publication_id
        or state.publication.evaluation_id != selected.evaluation.evaluation_id
    ):
        return stop("blocked", ("evaluation_publication_changed_during_check",))
    if state.state == "current" and (
        state.publication is None or selected.evaluation.outcome != "passed"
    ):
        return stop("blocked", ("passing_evaluation_material_missing",))
    result["state"] = state.state
    result["reasons"] = [reason.model_dump(mode="json") for reason in state.reasons]
    return result
