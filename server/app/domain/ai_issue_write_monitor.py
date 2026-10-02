"""Deterministic direct-Issue sampling and policy/binding-latched withdrawal stops."""

from datetime import datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Select, String, cast, func, select

from app.ai.issue_event_proposal import OPERATION
from app.db.schema import tables
from app.domain.ai_meeting_write_monitor import retraction_exceeded
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


def sampled_run(protocol_id: UUID, run_id: UUID, sampling_basis_points: int) -> bool:
    if type(sampling_basis_points) is not int or not 1 <= sampling_basis_points <= 10000:
        raise ValueError("invalid_issue_sampling_ratio")
    value = sha256(f"{protocol_id}:{run_id}".encode()).digest()
    return int.from_bytes(value, "big") % 10000 < sampling_basis_points


def monitor_query(
    *, tenant_id: UUID, project_id: UUID, policy_id: UUID, binding_digest: str, as_of: datetime
) -> Select[Any]:
    a, i, w = tables.ai_issue_applications, tables.issues, tables.ai_issue_withdrawal_receipts
    # Containment tests one exact successful item, including run-batch receipts.
    withdrawn = (
        select(w.c.id)
        .join(
            i,
            (i.c.tenant_id == w.c.tenant_id)
            & (i.c.project_id == w.c.project_id)
            & (i.c.ai_withdrawal_id == w.c.id),
        )
        .where(
            w.c.tenant_id == a.c.tenant_id,
            w.c.project_id == a.c.project_id,
            w.c.run_id == a.c.run_id,
            w.c.created_at <= as_of,
            i.c.id == a.c.issue_id,
            i.c.withdrawn_at.is_not(None),
            i.c.withdrawn_at <= as_of,
            w.c["items"].op("@>")(
                func.jsonb_build_array(
                    func.jsonb_build_object(
                        "application_id",
                        cast(a.c.id, String),
                        "issue_id",
                        cast(a.c.issue_id, String),
                        "status",
                        "withdrawn",
                    )
                )
            ),
        )
        .correlate(a)
        .exists()
    )
    return (
        select(func.count().label("generated"), func.count().filter(withdrawn).label("withdrawn"))
        .select_from(a)
        .where(
            a.c.tenant_id == tenant_id,
            a.c.project_id == project_id,
            a.c.policy_id == policy_id,
            a.c.capture_mode == "direct",
            a.c.disposition == "created",
            a.c.created_at <= as_of,
            a.c.receipt["write_receipt"]["binding_digest"].as_string() == binding_digest,
        )
    )


def quality_monitor(
    c: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    policy_id: UUID,
    binding_digest: str,
    protocol_id: UUID,
    configuration: dict[str, Any],
    as_of: datetime,
) -> dict[str, Any]:
    """Caller holds tenant/project locks; no protocol/scope change clears a stop."""
    t = tables.ai_write_runtime_stops
    previous = (
        c.execute(
            select(t).where(
                t.c.tenant_id == tenant_id,
                t.c.project_id == project_id,
                t.c.policy_id == policy_id,
                t.c.operation_key == OPERATION,
                t.c.binding_digest == binding_digest,
            )
        )
        .mappings()
        .one_or_none()
    )
    if previous is not None:
        return {"stopped": True, "stop_id": str(previous["id"]), "receipt": previous["receipt"]}
    maximum = configuration["maximum_retraction_basis_points"]
    if type(maximum) is not int or not 0 <= maximum <= 500:
        raise ValueError("invalid_issue_retraction_threshold")
    counts = c.execute(
        monitor_query(
            tenant_id=tenant_id,
            project_id=project_id,
            policy_id=policy_id,
            binding_digest=binding_digest,
            as_of=as_of,
        )
    ).one()
    receipt = {
        "as_of": as_of.isoformat(),
        "denominator": "all_direct_created_issues_in_project_policy_binding",
        "generated": counts.generated,
        "withdrawn": counts.withdrawn,
        "maximum_retraction_basis_points": maximum,
        "protocol_id": str(protocol_id),
        "recovery_protocol_version": configuration["recovery_protocol_version"],
        "recovery_conditions": configuration["recovery_conditions"],
        "automatic_recovery": False,
    }
    if not retraction_exceeded(counts.generated, counts.withdrawn, maximum):
        return {"stopped": False, "stop_id": None, "receipt": receipt}
    identity = uuid4()
    c.execute(
        t.insert().values(
            id=identity,
            tenant_id=tenant_id,
            project_id=project_id,
            policy_id=policy_id,
            operation_key=OPERATION,
            binding_digest=binding_digest,
            receipt=receipt,
            created_at=as_of,
        )
    )
    EventAuditWriter(c, tenant_id=tenant_id, project_id=project_id, actor_user_id=None).record(
        EventDraft(
            event_id=f"ai-write-stop:{identity}",
            event_type="AI_WRITE_AUTOMATIC_STOPPED",
            source="ai_meeting_write_service",
            entity_id=identity,
            occurred_at=as_of,
            payload={"stop_id": str(identity), "operation_key": OPERATION},
        ),
        AuditDraft(
            action="ai_write.automatic_stop",
            after_snapshot=receipt,
            context={"policy_id": str(policy_id), "binding_digest": binding_digest},
        ),
    )
    return {"stopped": True, "stop_id": str(identity), "receipt": receipt}
