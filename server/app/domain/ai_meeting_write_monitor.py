"""Deterministic sampling and latched retraction stops for automatic originals."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, func, select

from app.contracts.ai_write_qualification import QualificationConfiguration
from app.db.schema import tables
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


def sampled_draft(draft_id: UUID, configuration: QualificationConfiguration) -> bool:
    # Server-generated immutable draft IDs: replay never redraws the sample.
    value = sha256(f"{configuration.configuration_id}:{draft_id}".encode()).digest()
    return int.from_bytes(value, "big") % 10_000 < configuration.sampling_basis_points


def retraction_exceeded(total: int, withdrawn: int, maximum_basis_points: int) -> bool:
    if not 0 <= withdrawn <= total or not 0 <= maximum_basis_points <= 500:
        raise ValueError("invalid_automatic_retraction_counts")
    return total > 0 and withdrawn * 10_000 > maximum_basis_points * total


def quality_monitor(
    c: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    policy_id: UUID,
    operation_key: str,
    binding_digest: str,
    configuration: QualificationConfiguration,
    as_of: datetime,
) -> dict[str, Any]:
    """Caller holds the project write lock; stop and business action commit together.

    T0 retractions use all direct original drafts as denominator, not sampled
    reviews, revisions or trial confirmations. A stop stays latched for this
    project/policy/operation/binding. New policy requires a new qualified trial;
    changing a cohort or merely lowering the observed ratio never auto-recovers.
    """
    stops, d, a = (
        tables.ai_write_runtime_stops,
        tables.ai_meeting_drafts,
        tables.ai_meeting_draft_actions,
    )
    scope = (
        (stops.c.tenant_id == tenant_id)
        & (stops.c.project_id == project_id)
        & (stops.c.policy_id == policy_id)
        & (stops.c.operation_key == operation_key)
        & (stops.c.binding_digest == binding_digest)
    )
    old = c.execute(select(stops).where(scope)).mappings().one_or_none()
    if old is not None:
        return {"stopped": True, "stop_id": str(old["id"]), "receipt": old["receipt"]}
    withdrawn = (
        select(a.c.id)
        .where(
            a.c.tenant_id == tenant_id,
            a.c.project_id == project_id,
            a.c.draft_id == d.c.id,
            a.c.action == "withdraw",
            a.c.created_at <= as_of,
        )
        .exists()
    )
    counts = c.execute(
        select(func.count().label("generated"), func.count().filter(withdrawn).label("withdrawn"))
        .select_from(d)
        .where(
            d.c.tenant_id == tenant_id,
            d.c.project_id == project_id,
            d.c.policy_id == policy_id,
            d.c.capture_mode == "direct",
            d.c.draft_kind == operation_key.split(".")[1],
            d.c.write_receipt["binding_digest"].as_string() == binding_digest,
            d.c.created_at <= as_of,
        )
    ).one()
    receipt = {
        "as_of": as_of.isoformat(),
        "denominator": "all_direct_originals_in_project_policy_binding",
        "generated": counts.generated,
        "withdrawn": counts.withdrawn,
        "maximum_retraction_basis_points": configuration.maximum_retraction_basis_points,
        "configuration_id": str(configuration.configuration_id),
        "recovery_protocol_version": configuration.recovery_protocol_version,
        "recovery_conditions": configuration.recovery_conditions,
        "automatic_recovery": False,
    }
    if not retraction_exceeded(
        counts.generated, counts.withdrawn, configuration.maximum_retraction_basis_points
    ):
        return {"stopped": False, "stop_id": None, "receipt": receipt}
    stop_id = uuid4()
    c.execute(
        stops.insert().values(
            id=stop_id,
            tenant_id=tenant_id,
            project_id=project_id,
            policy_id=policy_id,
            operation_key=operation_key,
            binding_digest=binding_digest,
            receipt=receipt,
            created_at=as_of,
        )
    )
    EventAuditWriter(c, tenant_id=tenant_id, project_id=project_id, actor_user_id=None).record(
        EventDraft(
            event_id=f"ai-write-stop:{stop_id}",
            event_type="AI_WRITE_AUTOMATIC_STOPPED",
            source="ai_meeting_write_service",
            entity_id=stop_id,
            occurred_at=as_of,
            payload={"stop_id": str(stop_id), "operation_key": operation_key},
        ),
        AuditDraft(
            action="ai_write.automatic_stop",
            after_snapshot=receipt,
            context={"policy_id": str(policy_id), "binding_digest": binding_digest},
        ),
    )
    return {"stopped": True, "stop_id": str(stop_id), "receipt": receipt}
