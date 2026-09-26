"""Atomic, same-project and same-type Finding decisions with durable replay."""

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, RowMapping, select, text

from app.ai.rollout_guard import require_live_finding
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.findings import (
    FindingGroundTruthConflictError,
    FindingInvalidTransitionError,
    FindingNotFoundError,
    FindingPayloadInvalidError,
    FindingRecord,
    FindingReview,
    FindingService,
)


class BatchItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    finding_id: UUID
    expected_updated_at: AwareDatetime
    edited_payload: dict[str, Any] | None = None


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    action: Literal["accepted", "rejected", "applied", "review_undone"]
    comment: str = Field(min_length=1, max_length=3000)
    items: list[BatchItem] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def valid_items(self) -> Self:
        self.comment = self.comment.strip()
        if not self.comment or len({i.finding_id for i in self.items}) != len(self.items):
            raise ValueError("请填写共同办理说明，每个候选只能选择一次")
        if self.action != "accepted" and any(i.edited_payload is not None for i in self.items):
            raise ValueError("只有接受候选时可以保存人工修改")
        return self


@dataclass(frozen=True)
class BatchResult:
    receipt: dict[str, Any]
    items: tuple[FindingRecord, ...]
    replayed: bool


def _receipt(
    c: Connection, service: FindingService, row: RowMapping, actor: UUID, replayed: bool
) -> BatchResult:
    records = []
    for result in row["results"]:
        record = service._get(c, tenant_id=row["tenant_id"], finding_id=UUID(result["finding_id"]))
        from app.domain.change_notice_disclosure import require

        require(c, record, actor)
        service._authorize_user(
            c,
            tenant_id=row["tenant_id"],
            project_id=record.project_id,
            user_id=actor,
            action=Action.FINDING_VIEW,
        )
        if record.status != "applied":
            require_live_finding(record.agent_key, record.finding_type)
        records.append(record)
    return BatchResult(dict(row), tuple(records), replayed)


def read(engine: Engine, tenant: UUID, actor: UUID, request_id: UUID) -> BatchResult:
    with engine.connect() as c:
        t = tables.finding_batches
        row = (
            c.execute(
                select(t).where(
                    t.c.tenant_id == tenant,
                    t.c.actor_user_id == actor,
                    t.c.request_id == request_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise FindingNotFoundError
        return _receipt(c, FindingService(engine), row, actor, True)


def execute(engine: Engine, tenant: UUID, actor: UUID, body: BatchRequest) -> BatchResult:
    payload = body.model_dump(mode="json")
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    service = FindingService(engine)
    with engine.begin() as c:
        c.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"finding-batch:{tenant}:{actor}:{body.request_id}"},
        )
        t = tables.finding_batches
        existing = (
            c.execute(
                select(t).where(
                    t.c.tenant_id == tenant,
                    t.c.actor_user_id == actor,
                    t.c.request_id == body.request_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if existing is not None:
            if existing["request_digest"] != digest:
                raise FindingGroundTruthConflictError
            return _receipt(c, service, existing, actor, True)
        records = [
            service._get(c, tenant_id=tenant, finding_id=item.finding_id) for item in body.items
        ]
        first = records[0]
        for record in records:
            service._authorize_user(
                c,
                tenant_id=tenant,
                project_id=record.project_id,
                user_id=actor,
                action=Action.FINDING_APPLY if body.action == "applied" else Action.FINDING_REVIEW,
            )
            if (record.project_id, record.finding_type) != (first.project_id, first.finding_type):
                raise FindingInvalidTransitionError
        # Reuse the original action lock order; lock the selected set in UUID
        # order before any update, then run every original validator/adapter.
        for item in sorted(body.items, key=lambda item: str(item.finding_id)):
            record = service._get_for_action(c, tenant_id=tenant, finding_id=item.finding_id)
            if record.updated_at != item.expected_updated_at or record.superseded_by:
                raise FindingGroundTruthConflictError
            allowed = (
                {"accepted", "rejected"}
                if body.action == "review_undone"
                else {"accepted" if body.action == "applied" else "pending_review"}
            )
            if record.status not in allowed:
                raise FindingInvalidTransitionError
        results = []
        for item, original in zip(body.items, records, strict=True):
            if body.action == "review_undone":
                result = service.undo_review(
                    tenant_id=tenant,
                    actor_user_id=actor,
                    finding_id=item.finding_id,
                    expected_updated_at=item.expected_updated_at,
                    comment=body.comment,
                    shared_connection=c,
                )
            elif body.action == "applied":
                result = service.apply(
                    tenant_id=tenant,
                    actor_user_id=actor,
                    finding_id=item.finding_id,
                    shared_connection=c,
                    expected_updated_at=item.expected_updated_at,
                ).finding
            else:
                try:
                    edited = (
                        service._validated_payload(original.finding_type, item.edited_payload)
                        if item.edited_payload is not None
                        else None
                    )
                except ValueError as error:
                    raise FindingPayloadInvalidError from error
                result = service.review(
                    tenant_id=tenant,
                    actor_user_id=actor,
                    finding_id=item.finding_id,
                    shared_connection=c,
                    expected_updated_at=item.expected_updated_at,
                    review=FindingReview(
                        decision=body.action, edited_payload=edited, comment=body.comment
                    ),
                )
            results.append(
                {
                    "finding_id": str(result.id),
                    "status": result.status,
                    "updated_at": result.updated_at.isoformat(),
                    "applied_entity_type": result.applied_entity_type,
                    "applied_entity_id": str(result.applied_entity_id)
                    if result.applied_entity_id
                    else None,
                }
            )
        row = (
            c.execute(
                t.insert()
                .values(
                    id=uuid4(),
                    tenant_id=tenant,
                    project_id=first.project_id,
                    actor_user_id=actor,
                    request_id=body.request_id,
                    request_digest=digest,
                    action=body.action,
                    finding_type=first.finding_type,
                    request=payload,
                    results=results,
                )
                .returning(t)
            )
            .mappings()
            .one()
        )
        return _receipt(c, service, row, actor, False)
