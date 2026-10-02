"""Read a complete fixed meeting-draft trial selection without granting qualification.

The caller authorizes every project and supplies a registered protocol's scope
and evidence kind. One SELECT gives a consistent database snapshot; missing
provenance remains in raw totals and blocks completeness. No writes or models.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import Connection, Select, func, select

from app.ai.observations import digest
from app.contracts.ai_write_qualification import (
    DraftOperation,
    DraftTrialEvidence,
    QualificationBinding,
    TrialCohort,
    TrialCounts,
    TrialEvidenceKind,
)
from app.contracts.common_objects import Contract, Key, Nonnegative
from app.contracts.runtime_records import ContextManifest, Observation
from app.db.schema import tables

_KINDS = {
    "meeting.minutes.draft": "minutes",
    "meeting.actions.draft": "actions",
    "meeting.decisions.draft": "decisions",
}
_JSON = TypeAdapter(dict[str, Any])


class TrialCollectionBlocker(Contract):
    draft_id: UUID
    reasons: tuple[Key, ...]


class TrialCollection(Contract):
    version: Literal["dc11-meeting-trial-collection.v1"] = "dc11-meeting-trial-collection.v1"
    project_ids: tuple[UUID, ...]
    cohort: TrialCohort
    raw_counts: TrialCounts
    raw_total: Nonnegative
    verified_total: Nonnegative
    unverified_total: Nonnegative
    original_draft_ids: tuple[UUID, ...]
    blockers: tuple[TrialCollectionBlocker, ...]


def trial_query(
    *,
    tenant_id: UUID,
    project_ids: tuple[UUID, ...],
    operation_key: DraftOperation,
    window_start: datetime,
    window_end: datetime,
    as_of: datetime,
) -> Select[Any]:
    """No success/binding filters, sample limit or inner provenance joins."""
    d, a = tables.ai_meeting_drafts, tables.ai_meeting_draft_actions
    c, p = tables.model_invocations, tables.ai_write_policies
    o, r = tables.application_context_observations, tables.application_result_checkpoints
    m, b = tables.application_context_manifests, tables.budget_journal
    history = (
        select(
            a.c.draft_id,
            *(
                func.min(a.c.created_at).filter(a.c.action == key).label(key + "ed_at")
                for key in ("confirm", "edit")
            ),
            func.min(a.c.created_at).filter(a.c.action == "withdraw").label("withdrawn_at"),
        )
        .where(
            a.c.tenant_id == tenant_id,
            a.c.project_id.in_(project_ids),
            a.c.created_at <= as_of,
        )
        .group_by(a.c.draft_id)
        .subquery()
    )
    sources = (
        d.outerjoin(c, (c.c.tenant_id == d.c.tenant_id) & (c.c.id == d.c.model_invocation_id))
        .outerjoin(p, (p.c.tenant_id == d.c.tenant_id) & (p.c.id == d.c.policy_id))
        .outerjoin(
            o,
            (o.c.tenant_id == d.c.tenant_id)
            & (o.c.run_id == d.c.run_id)
            & (o.c.model_call_id == c.c.budget_call_id),
        )
        .outerjoin(
            r,
            (r.c.tenant_id == d.c.tenant_id)
            & (r.c.run_id == d.c.run_id)
            & (r.c.model_call_id == c.c.budget_call_id)
            & (r.c.invocation_id == c.c.id),
        )
        .outerjoin(
            m,
            (m.c.tenant_id == d.c.tenant_id)
            & (m.c.run_id == d.c.run_id)
            & (m.c.id == r.c.manifest_id),
        )
        .outerjoin(
            b,
            (b.c.tenant_id == d.c.tenant_id)
            & (b.c.run_id == d.c.run_id)
            & (b.c.id == m.c.admission_id),
        )
        .outerjoin(history, history.c.draft_id == d.c.id)
    )
    return (
        select(
            *(
                func.to_jsonb(table.table_valued()).label(label)
                for table, label in (
                    (d, "draft"),
                    (c, "call"),
                    (p, "policy"),
                    (o, "observation"),
                    (r, "checkpoint"),
                    (m, "manifest"),
                    (b, "admission"),
                )
            ),
            history.c.confirmed_at,
            history.c.edited_at,
            history.c.withdrawn_at,
        )
        .select_from(sources)
        .where(
            d.c.tenant_id == tenant_id,
            d.c.project_id.in_(project_ids),
            d.c.draft_kind == _KINDS[operation_key],
            d.c.capture_mode == "trial",
            d.c.created_at >= window_start,
            d.c.created_at < window_end,
        )
        .order_by(d.c.id)
    )


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _same_id(left: Any, right: Any) -> bool:
    return left is not None and right is not None and str(left) == str(right)


def _verify(
    row: Mapping[str, Any], expected: QualificationBinding, evidence_kind: TrialEvidenceKind
) -> tuple[DraftTrialEvidence | None, tuple[str, ...]]:
    d = row["draft"]
    reasons: set[str] = set()
    sources = {
        key: _object(row.get(key))
        for key in ("call", "policy", "observation", "checkpoint", "manifest", "admission")
    }
    for key, source in sources.items():
        if not source.get("id"):
            reasons.add(key + "_missing")
        elif not _same_id(source.get("tenant_id"), d["tenant_id"]):
            reasons.add(key + "_scope_mismatch")
        if key != "policy" and source and not _same_id(source.get("run_id"), d["run_id"]):
            reasons.add(key + "_scope_mismatch")
    if reasons:
        return None, tuple(sorted(reasons))
    c, p, o, r, m, b = (
        sources[key]
        for key in ("call", "policy", "observation", "checkpoint", "manifest", "admission")
    )
    if not _same_id(c.get("project_id"), d["project_id"]) or c.get("agent_key") != "knowledge_lite":
        reasons.add("call_scope_mismatch")
    if (
        c.get("status") != "succeeded"
        or c.get("usage_status") != "known"
        or c.get("input_meter_version") != "normalized_input.v1"
        or type(c.get("structured_attempts")) is not int
        or c["structured_attempts"] < 1
    ):
        reasons.add("provider_call_unverified")
    if any(
        type(c.get(key)) is not int or c[key] < 0
        for key in ("input_tokens", "output_tokens", "total_tokens")
    ) or c.get("total_tokens") != c.get("input_tokens", 0) + c.get("output_tokens", 0):
        reasons.add("usage_totals_unverified")
    if c.get("model_version") is None or str(c["model_version"]).strip().casefold() in {
        "",
        "unknown",
        "unspecified",
        "unavailable",
        "latest",
        "未知",
        "未登记",
    }:
        reasons.add("model_version_unknown")
    if not _same_id(c.get("id"), d.get("model_invocation_id")):
        reasons.add("call_identity_mismatch")
    if (
        not _same_id(o.get("model_call_id"), c.get("budget_call_id"))
        or not _same_id(r.get("invocation_id"), c.get("id"))
        or not _same_id(r.get("model_call_id"), o.get("model_call_id"))
        or not _same_id(r.get("observation_id"), o.get("id"))
        or not _same_id(r.get("manifest_id"), m.get("id"))
        or not _same_id(m.get("observation_id"), o.get("id"))
        or not _same_id(m.get("authorization_id"), o.get("authorization_id"))
        or not _same_id(m.get("admission_id"), b.get("id"))
        or not _same_id(m.get("attempt_id"), b.get("attempt_id"))
    ):
        reasons.add("context_chain_mismatch")
    if (
        p.get("mode") != "tiered"
        or not _same_id(p.get("id"), d.get("policy_id"))
        or not _same_id(p.get("principal_id"), d.get("principal_id"))
        or _object(_object(p.get("operation_settings")).get(expected.operation_key)).get("mode")
        not in {"confirm", "automatic"}
    ):
        reasons.add("original_policy_unverified")
    for source in sources.values():
        try:
            stamp = TypeAdapter(datetime).validate_python(source.get("created_at"))
            created = TypeAdapter(datetime).validate_python(d["created_at"])
            if stamp.utcoffset() is None or stamp > created:
                reasons.add("source_after_draft_or_time_unknown")
        except (ValidationError, TypeError):
            reasons.add("source_after_draft_or_time_unknown")
    bundle = _object(o.get("bundle"))
    compiled = _object(bundle.get("compiled"))
    context = _object(o.get("context_body"))
    manifest = _object(m.get("body"))
    request = _object(b.get("request_binding"))
    result = _object(r.get("body"))
    if (
        result.get("version") != "application-result.v1"
        or result.get("status") != "succeeded"
        or not isinstance(result.get("output"), dict)
        or result.get("structured_attempts") != c.get("structured_attempts")
    ):
        reasons.add("original_result_unverified")
    try:
        observed = Observation.model_validate(o.get("metadata"))
        pinned = ContextManifest.model_validate(manifest)
        if (
            not _same_id(observed.id, o["id"])
            or not _same_id(observed.tenant_id, d["tenant_id"])
            or not _same_id(observed.run_id, d["run_id"])
            or observed.allowed_purpose != "meeting_" + d["draft_kind"]
            or observed.status != "completed"
            or observed.truncated
            or observed.output_digest != digest(o.get("output_body"))
        ):
            reasons.add("observation_unverified")
        if (
            not _same_id(pinned.id, m["id"])
            or not _same_id(pinned.tenant_id, d["tenant_id"])
            or not _same_id(pinned.run_id, d["run_id"])
            or not _same_id(pinned.authorization_id, m.get("authorization_id"))
            or observed.id not in pinned.observation_ids
            or pinned.completeness != "complete"
            or pinned.missing
            or pinned.digest
            != digest({key: value for key, value in manifest.items() if key != "digest"})
        ):
            reasons.add("manifest_unverified")
    except ValidationError:
        reasons.add("context_contract_invalid")
    if (
        not bundle.get("source_sha256")
        or compiled.get("purpose") != "meeting_" + d["draft_kind"]
        or not compiled.get("reader")
        or manifest.get("release_bundle_version") != "sha256:" + digest(bundle)
        or context.get("output_schema_sha256") != digest(compiled.get("schema"))
        or manifest.get("output_schema_version")
        != "sha256:" + str(context.get("output_schema_sha256"))
        or c.get("prompt_version") != context.get("prompt_version")
        or c.get("prompt_version") != manifest.get("prompt_version")
        or c.get("prompt_version") != _object(compiled.get("prompt")).get("version")
    ):
        reasons.add("original_bundle_unverified")
    if (
        not request.get("qualification_ref")
        or not request.get("meter_version")
        or not _same_id(request.get("model_call_id"), o.get("model_call_id"))
        or request.get("provider") != c.get("provider")
        or request.get("model") != c.get("model")
        or request.get("protocol") != c.get("protocol")
        or b.get("call_kind") != "model"
        or b.get("reservation_status") != "reserved"
    ):
        reasons.add("admission_binding_unverified")
    # Suite fields were hashed, not stored in clear in application manifests.
    # A candidate's values become evidence only if they reproduce the old pin.
    qualification = dict(
        provider=c.get("provider"),
        model=c.get("model"),
        status="passed",
        suite_version=expected.suite_version,
        # LoadedGoldenSuite publishes the algorithm prefix; our Digest contract
        # carries the bare SHA256. Reconstruct the actual existing wire format.
        suite_digest="sha256:" + expected.suite_digest,
    )
    qualification_pin = "sha256:" + digest(
        dict(
            qualification=qualification,
            meter_ref=request.get("qualification_ref"),
            meter_version=request.get("meter_version"),
        )
    )
    if manifest.get("model_qualification_version") != qualification_pin:
        reasons.add("suite_binding_unverified")
    try:
        original_binding = QualificationBinding.model_validate(
            dict(
                operation_key="meeting." + d["draft_kind"] + ".draft",
                provider=c["provider"],
                model=c["model"],
                model_version=c.get("model_version"),
                release_bundle_version=manifest.get("release_bundle_version"),
                suite_version=expected.suite_version,
                suite_digest=expected.suite_digest,
                adapter_version=compiled.get("reader"),
                policy_version=p.get("contract_version"),
                policy_revision=p.get("revision"),
            )
        )
        if original_binding != expected:
            reasons.add("expected_binding_mismatch")
        evidence = DraftTrialEvidence(
            draft_id=d["id"],
            tenant_id=d["tenant_id"],
            project_id=d["project_id"],
            run_id=d["run_id"],
            model_invocation_id=c["id"],
            context_observation_id=o["id"],
            receipt_digest=digest(_JSON.dump_python(dict(row), mode="json")),
            evidence_kind=evidence_kind,
            real_provider_call=True,
            binding=original_binding,
            created_at=d["created_at"],
            confirmed_at=row["confirmed_at"],
            edited_at=row["edited_at"],
            withdrawn_at=row["withdrawn_at"],
        )
    except (ValidationError, KeyError):
        reasons.add("draft_evidence_contract_invalid")
        evidence = None
    return (None if reasons else evidence), tuple(sorted(reasons))


def collect_trial(
    connection: Connection,
    *,
    tenant_id: UUID,
    project_ids: tuple[UUID, ...],
    operation_key: DraftOperation,
    window_start: datetime,
    window_end: datetime,
    as_of: datetime,
    expected_binding: QualificationBinding,
    evidence_kind: TrialEvidenceKind,
    cohort_id: UUID,
    evidence_ref: str,
) -> TrialCollection:
    """Collect all selected originals; callers must authorize the whole scope first."""
    operation_key = TypeAdapter(DraftOperation).validate_python(operation_key)
    evidence_kind = TypeAdapter(TrialEvidenceKind).validate_python(evidence_kind)
    project_ids = tuple(sorted(set(project_ids), key=str))
    if not project_ids or operation_key != expected_binding.operation_key:
        raise ValueError("fixed_project_scope_and_matching_operation_required")
    base = TrialCohort(
        cohort_id=cohort_id,
        tenant_id=tenant_id,
        evidence_ref=evidence_ref,
        receipt_digest="0" * 64,
        window_start=window_start,
        window_end=window_end,
        as_of=as_of,
        selection_complete=False,
        drafts=(),
    )
    rows = (
        connection.execute(
            trial_query(
                tenant_id=tenant_id,
                project_ids=project_ids,
                operation_key=operation_key,
                window_start=window_start,
                window_end=window_end,
                as_of=as_of,
            )
        )
        .mappings()
        .all()
    )
    unique: dict[UUID, dict[str, Any]] = {}
    conflicts: set[UUID] = set()
    for raw in rows:
        row = dict(raw)
        key = UUID(str(row["draft"]["id"]))
        if key in unique and unique[key] != row:
            conflicts.add(key)
        else:
            unique[key] = row
    verified, blockers = [], []
    for key in sorted(unique, key=str):
        reasons: tuple[str, ...]
        if key in conflicts:
            evidence, reasons = None, ("ambiguous_original_draft_join",)
        else:
            evidence, reasons = _verify(unique[key], expected_binding, evidence_kind)
        if evidence is not None:
            verified.append(evidence)
        else:
            blockers.append(TrialCollectionBlocker(draft_id=key, reasons=reasons))
    originals = list(unique.values())
    confirmed = sum(row["confirmed_at"] is not None for row in originals)
    withdrawn = sum(row["withdrawn_at"] is not None for row in originals)
    handled = sum(
        row["confirmed_at"] is not None or row["withdrawn_at"] is not None for row in originals
    )
    raw_counts = TrialCounts(
        generated=len(unique),
        confirmed=confirmed,
        edited=sum(row["edited_at"] is not None for row in originals),
        withdrawn=withdrawn,
        handled=handled,
        pending=len(unique) - handled,
        retained_original=sum(
            row["confirmed_at"] is not None
            and row["edited_at"] is None
            and row["withdrawn_at"] is None
            for row in originals
        ),
        withdrawn_after_confirmation=sum(
            row["confirmed_at"] is not None and row["withdrawn_at"] is not None for row in originals
        ),
    )
    receipt = dict(
        selection=base.model_dump(mode="json"),
        project_ids=[str(key) for key in project_ids],
        operation_key=operation_key,
        expected_binding=expected_binding.model_dump(mode="json"),
        evidence_kind=evidence_kind,
        originals=[_JSON.dump_python(unique[key], mode="json") for key in sorted(unique, key=str)],
        blockers=[item.model_dump(mode="json") for item in blockers],
    )
    frozen = TrialCohort.model_validate(
        {
            **base.model_dump(),
            "receipt_digest": digest(receipt),
            "selection_complete": not blockers,
            "drafts": tuple(verified),
        }
    )
    return TrialCollection(
        project_ids=project_ids,
        cohort=frozen,
        raw_counts=raw_counts,
        raw_total=len(unique),
        verified_total=len(verified),
        unverified_total=len(blockers),
        original_draft_ids=tuple(sorted(unique, key=str)),
        blockers=tuple(blockers),
    )
