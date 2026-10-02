"""Current meeting-draft qualification material, not an execution grant.

Trusted callers supply the actual runtime binding, authorized project and clock,
and own the transaction snapshot. This reader never writes, resolves an HTTP
boolean, enables T0, or replaces the caller's current scope/rollout/source gates.
Historical receipts remain immutable; a fresh collection detects later handling.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, TypeAdapter, ValidationError
from sqlalchemy import Connection, Select, cast, select
from sqlalchemy.dialects.postgresql import JSONB

from app.ai.write_evaluation_publication import (
    PublishedWriteEvaluation,
    WriteEvaluationPublicationError,
    configured_write_evaluation,
)
from app.contracts.ai_write_qualification import (
    DraftOperation,
    EvaluationEvidence,
    QualificationBinding,
    QualificationConfiguration,
    QualificationInput,
    QualificationResult,
    TrialCounts,
    evaluate_qualification,
)
from app.contracts.ai_write_trial_protocol import TrialProtocol
from app.contracts.common_objects import Contract, Digest, Key, Nonnegative, Text
from app.db.schema import tables
from app.domain.ai_write_policy import _current
from app.domain.ai_write_trial_collection import (
    TrialCollection,
    TrialCollectionBlocker,
    collect_trial,
)


class QualificationReason(Contract):
    code: Key
    message: Text


class QualificationPublicationRef(Contract):
    publication_id: UUID
    publication_sha256: Digest
    evaluation_id: UUID
    evidence_ref: Text
    golden_publication_ref: Text
    published_at: AwareDatetime
    valid_from: AwareDatetime
    valid_until: AwareDatetime


class FreshQualificationCheck(Contract):
    as_of: AwareDatetime
    collection_digest: Digest
    raw_total: Nonnegative
    verified_total: Nonnegative
    unverified_total: Nonnegative
    raw_counts: TrialCounts
    blockers: tuple[TrialCollectionBlocker, ...]
    qualification: QualificationResult


class QualificationState(Contract):
    state: Literal["current", "blocked", "unavailable"]
    checked_at: AwareDatetime
    tenant_id: UUID
    project_id: UUID
    operation_key: DraftOperation
    binding: QualificationBinding
    policy_id: UUID | None = None
    configuration: QualificationConfiguration | None = None
    protocol_id: UUID | None = None
    protocol_digest: Digest | None = None
    receipt_id: UUID | None = None
    receipt_digest: Digest | None = None
    receipt_as_of: AwareDatetime | None = None
    checked_receipt_count: Nonnegative = 0
    reasons: tuple[QualificationReason, ...] = ()
    publication: QualificationPublicationRef | None = None
    fresh_check: FreshQualificationCheck | None = None
    qualification_granted: Literal[False] = False


_MESSAGES = {
    "operation_binding_mismatch": "实际操作与运行绑定不一致。",
    "current_policy_mismatch": "当前分级政策与实际运行绑定不一致。",
    "operation_disabled": "当前政策已停用这类草稿。",
    "evaluation_unavailable": "当前独立评测发布原件无法核实或已失效。",
    "real_business_trial_missing": "没有覆盖本项目及实际版本的真实业务试运行回执。",
    "protocol_invalid": "原试运行登记的内容、范围或摘要无法核实。",
    "protocol_policy_mismatch": "原试运行未绑定当前政策。",
    "thresholds_changed": "原试运行门槛与当前政策不一致。",
    "receipt_invalid": "最新采集回执的内容、时间或摘要无法核实。",
    "receipt_cutoff_regressed": "最新采集采用了更早截点，请按当前记录重新采集。",
    "latest_collection_incomplete": "最新采集未完整核实全部原稿。",
    "latest_receipt_not_met": "最新固定采集尚未满足候选条件，不能沿用旧通过记录。",
    "evaluation_publication_changed": "独立评测已与原回执不同，请重新核对并采集。",
    "fresh_collection_unavailable": "当前原稿依据无法完整回读。",
    "fresh_collection_incomplete": "当前原稿依据存在缺项，不能沿用旧采集结论。",
    "fresh_criteria_not_met": "截至本次核对，确认、修改或撤回后的条件已不满足。",
}


def _digest(value: Any) -> str:
    # Same canonical encoding as the immutable protocol/receipt writer.
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def qualification_history_query(
    *, tenant_id: UUID, project_id: UUID, binding: QualificationBinding, as_of: datetime
) -> Select[Any]:
    p, r = tables.ai_write_trial_protocols, tables.ai_write_trial_receipts
    return (
        select(
            p.c.id.label("protocol_record_id"),
            p.c.tenant_id,
            p.c.policy_id,
            p.c.created_at.label("protocol_created_at"),
            p.c.protocol,
            r.c.id.label("receipt_record_id"),
            r.c.created_at.label("receipt_created_at"),
            r.c.as_of.label("receipt_as_of"),
            r.c.receipt,
        )
        .select_from(
            p.outerjoin(
                r,
                (r.c.tenant_id == p.c.tenant_id)
                & (r.c.protocol_id == p.c.id)
                & (r.c.created_at <= as_of),
            )
        )
        .where(
            p.c.tenant_id == tenant_id,
            p.c.created_at <= as_of,
            cast(p.c.protocol, JSONB).contains(
                {
                    "project_ids": [str(project_id)],
                    "binding": binding.model_dump(mode="json"),
                    "evidence_kind": "real_business",
                }
            ),
        )
        # Never select passing rows first: a later failure supersedes an old pass.
        .order_by(r.c.created_at.desc().nulls_last(), r.c.id.desc().nulls_last(), p.c.id.desc())
    )


def _complete_collection(collection: TrialCollection, protocol: TrialProtocol) -> bool:
    cohort = collection.cohort
    ids = {draft.draft_id for draft in cohort.drafts}
    return (
        cohort.selection_complete
        and not collection.blockers
        and collection.unverified_total == 0
        and collection.raw_total == collection.verified_total == len(cohort.drafts)
        and collection.raw_counts.generated == collection.raw_total
        and set(collection.original_draft_ids) == ids
        and len(collection.original_draft_ids) == len(ids)
        and collection.project_ids == protocol.project_ids
        and cohort.tenant_id == protocol.tenant_id
        and cohort.window_start == protocol.window_start
        and cohort.window_end == protocol.window_end
        and all(
            d.project_id in protocol.project_ids
            and d.evidence_kind == "real_business"
            and d.binding == protocol.binding
            and d.real_provider_call
            for d in cohort.drafts
        )
    )


def read_qualification_state(
    connection: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    operation_key: DraftOperation,
    binding: QualificationBinding,
    as_of: datetime,
) -> QualificationState:
    """Read all matching receipts, check the latest, then re-read its fixed window.

    New uncollected declarations do not revoke evidence. Any later collected
    failure, unknown chain or changed publication blocks reuse of an older pass.
    The caller must authorize the selected protocol's entire project scope before
    disclosing fresh detail; direct execution must independently check its scope.
    """
    operation_key = TypeAdapter(DraftOperation).validate_python(operation_key)
    as_of = TypeAdapter(AwareDatetime).validate_python(as_of)
    data: dict[str, Any] = dict(
        checked_at=as_of,
        tenant_id=tenant_id,
        project_id=project_id,
        operation_key=operation_key,
        binding=binding,
    )
    reasons: set[str] = set()

    def finish() -> QualificationState:
        return QualificationState(
            **data,
            state="current"
            if not reasons
            else "unavailable"
            if reasons <= {"evaluation_unavailable", "real_business_trial_missing"}
            else "blocked",
            reasons=tuple(
                QualificationReason(code=key, message=_MESSAGES[key]) for key in sorted(reasons)
            ),
        )

    if operation_key != binding.operation_key:
        reasons.add("operation_binding_mismatch")
        return finish()
    policy = _current(connection, tenant_id)
    if policy is None:
        reasons.add("current_policy_mismatch")
        return finish()
    data["policy_id"] = policy["id"]
    if (
        policy["mode"] != "tiered"
        or policy["revision"] != binding.policy_revision
        or policy["contract_version"] != binding.policy_version
    ):
        reasons.add("current_policy_mismatch")
        return finish()
    setting = policy["operation_settings"].get(operation_key, {})
    if setting.get("mode") not in {"confirm", "automatic"}:
        reasons.add("operation_disabled")
        return finish()
    published: PublishedWriteEvaluation | None = None
    try:
        published = configured_write_evaluation(
            os.environ, tenant_id=tenant_id, expected_binding=binding, as_of=as_of
        )
    except WriteEvaluationPublicationError:
        published = None
    if published is None:
        reasons.add("evaluation_unavailable")
    else:
        data["publication"] = QualificationPublicationRef(
            publication_id=published.publication_id,
            publication_sha256=published.publication_sha256,
            evaluation_id=published.evaluation.evaluation_id,
            evidence_ref=published.evaluation.evidence_ref,
            golden_publication_ref=published.evaluation.golden_publication_ref,
            published_at=published.published_at,
            valid_from=published.valid_from,
            valid_until=published.valid_until,
        )
    rows = (
        connection.execute(
            qualification_history_query(
                tenant_id=tenant_id, project_id=project_id, binding=binding, as_of=as_of
            )
        )
        .mappings()
        .all()
    )
    collected = [row for row in rows if row["receipt_record_id"] is not None]
    data["checked_receipt_count"] = len(collected)
    if not collected:
        reasons.add("real_business_trial_missing")
        return finish()
    row = collected[0]
    data.update(
        protocol_id=row["protocol_record_id"],
        receipt_id=row["receipt_record_id"],
        receipt_as_of=row["receipt_as_of"],
    )
    try:
        protocol = TrialProtocol.model_validate(row["protocol"])
        if (
            protocol.id != row["protocol_record_id"]
            or protocol.tenant_id != tenant_id
            or protocol.created_at != row["protocol_created_at"]
            or protocol.binding != binding
            or project_id not in protocol.project_ids
            or protocol.evidence_kind != "real_business"
            or protocol.protocol_digest
            != _digest(
                {key: value for key, value in row["protocol"].items() if key != "protocol_digest"}
            )
            or protocol.configuration.configuration_digest
            != _digest(
                protocol.configuration.model_dump(mode="json", exclude={"configuration_digest"})
            )
        ):
            raise ValueError("protocol_identity_or_digest")
    except (ValidationError, ValueError, KeyError):
        reasons.add("protocol_invalid")
        return finish()
    data.update(protocol_digest=protocol.protocol_digest, configuration=protocol.configuration)
    if protocol.policy_id != policy["id"] or protocol.policy_id != row["policy_id"]:
        reasons.add("protocol_policy_mismatch")
    config = protocol.configuration
    if config.minimum_confirmation_basis_points != setting.get(
        "minimum_confirmation_basis_points"
    ) or config.maximum_retraction_basis_points != setting.get("maximum_retraction_basis_points"):
        reasons.add("thresholds_changed")
    try:
        receipt = row["receipt"]
        saved_as_of = TypeAdapter(AwareDatetime).validate_python(receipt["as_of"])
        if (
            UUID(receipt["id"]) != row["receipt_record_id"]
            or UUID(receipt["protocol_id"]) != protocol.id
            or receipt["protocol_digest"] != protocol.protocol_digest
            or saved_as_of != row["receipt_as_of"]
            or saved_as_of > as_of
            or not protocol.window_end <= saved_as_of <= row["receipt_created_at"] <= as_of
            or TypeAdapter(AwareDatetime).validate_python(receipt["created_at"])
            != row["receipt_created_at"]
            or receipt["receipt_digest"]
            != _digest({key: value for key, value in receipt.items() if key != "receipt_digest"})
        ):
            raise ValueError("receipt_identity_or_digest")
        data["receipt_digest"] = receipt["receipt_digest"]
        if any(other["receipt_as_of"] > saved_as_of for other in collected):
            reasons.add("receipt_cutoff_regressed")
        original = TrialCollection.model_validate(receipt["collection"])
        if (
            original.cohort.cohort_id != row["receipt_record_id"]
            or original.cohort.as_of != saved_as_of
        ):
            raise ValueError("cohort_receipt_identity")
        if not _complete_collection(original, protocol):
            reasons.add("latest_collection_incomplete")
        old_evaluation = (
            EvaluationEvidence.model_validate(receipt["evaluation"])
            if receipt.get("evaluation") is not None
            else None
        )
        recomputed = evaluate_qualification(
            QualificationInput(
                tenant_id=tenant_id,
                binding=binding,
                configuration=config,
                evaluation=old_evaluation,
                cohort=original.cohort,
                as_of=saved_as_of,
            )
        )
        if QualificationResult.model_validate(receipt["qualification"]) != recomputed:
            raise ValueError("saved_qualification_does_not_recompute")
        if original.raw_counts != recomputed.counts:
            reasons.add("latest_collection_incomplete")
        if recomputed.status != "meets_candidate_criteria":
            reasons.add("latest_receipt_not_met")
        old_pub = receipt.get("evaluation_publication") or {}
        if published is not None and (
            old_pub.get("status") != "verified"
            or old_pub.get("publication_sha256") != published.publication_sha256
            or old_pub.get("publication_id") != str(published.publication_id)
            or old_evaluation != published.evaluation
        ):
            reasons.add("evaluation_publication_changed")
    except (ValidationError, ValueError, KeyError, TypeError):
        reasons.add("receipt_invalid")
        return finish()
    try:
        fresh = collect_trial(
            connection,
            tenant_id=tenant_id,
            project_ids=protocol.project_ids,
            operation_key=operation_key,
            window_start=protocol.window_start,
            window_end=protocol.window_end,
            as_of=as_of,
            expected_binding=binding,
            evidence_kind="real_business",
            cohort_id=row["receipt_record_id"],
            evidence_ref=f"ai-write-trial-current-check:{row['receipt_record_id']}",
        )
        fresh_result = evaluate_qualification(
            QualificationInput(
                tenant_id=tenant_id,
                binding=binding,
                configuration=config,
                evaluation=published.evaluation if published is not None else None,
                cohort=fresh.cohort,
                as_of=as_of,
            )
        )
        data["fresh_check"] = FreshQualificationCheck(
            as_of=as_of,
            collection_digest=fresh.cohort.receipt_digest,
            raw_total=fresh.raw_total,
            verified_total=fresh.verified_total,
            unverified_total=fresh.unverified_total,
            raw_counts=fresh.raw_counts,
            blockers=fresh.blockers,
            qualification=fresh_result,
        )
        if not _complete_collection(fresh, protocol) or fresh.raw_counts != fresh_result.counts:
            reasons.add("fresh_collection_incomplete")
        if fresh_result.status != "meets_candidate_criteria":
            reasons.add("fresh_criteria_not_met")
    except (ValidationError, ValueError, KeyError, TypeError):
        reasons.add("fresh_collection_unavailable")
    return finish()
