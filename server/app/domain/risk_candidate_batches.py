"""Same-project rule confirmations with immutable receipts and request replay."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, RowMapping, select, text

from app.db.schema import tables
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.risk_candidates import RiskCandidateService, _active_specs
from app.domain.risks import (
    RiskNotFoundError,
    RiskVersionConflictError,
    _record_from_row,
    _risk_statement,
)


class RiskCandidateSourceChangedError(RiskVersionConflictError):
    pass


class BatchItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    risk_id: UUID
    expected_updated_at: AwareDatetime


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    items: list[BatchItem] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_items(self) -> Self:
        if len({item.risk_id for item in self.items}) != len(self.items):
            raise ValueError("每条风险候选只能选择一次")
        return self


def _receipt(c: Connection, row: RowMapping, replayed: bool) -> dict[str, Any]:
    # Separate immutable confirmation snapshots from today's state.
    current = (
        c.execute(
            select(
                tables.risks.c.id,
                tables.risks.c.draft_state,
                tables.risks.c.status,
                tables.risks.c.updated_at,
            ).where(
                tables.risks.c.tenant_id == row["tenant_id"],
                tables.risks.c.project_id == row["project_id"],
                tables.risks.c.id.in_([UUID(item["risk_id"]) for item in row["results"]]),
            )
        )
        .mappings()
        .all()
    )
    return {
        "request_id": row["request_id"],
        "project_id": row["project_id"],
        "actor_user_id": row["actor_user_id"],
        "created_at": row["created_at"],
        "results": row["results"],
        "current": [dict(item) for item in current],
        "replayed": replayed,
    }


def read(
    engine: Engine, tenant: UUID, actor: UUID, project: UUID, request_id: UUID
) -> dict[str, Any]:
    with engine.connect() as c:
        t = tables.risk_candidate_batches
        row = (
            c.execute(
                select(t).where(
                    t.c.tenant_id == tenant,
                    t.c.project_id == project,
                    t.c.actor_user_id == actor,
                    t.c.request_id == request_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise RiskNotFoundError
        return _receipt(c, row, True)


def execute(
    engine: Engine, tenant: UUID, actor: UUID, project: UUID, body: BatchRequest
) -> dict[str, Any]:
    payload = body.model_dump(mode="json")
    digest = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    with engine.begin() as c:
        c.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"risk-candidate-batch:{tenant}:{actor}:{body.request_id}"},
        )
        t = tables.risk_candidate_batches
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
            if existing["project_id"] != project or existing["request_digest"] != digest:
                raise RiskVersionConflictError
            return _receipt(c, existing, True)
        if not lock_project_write_scope(c, tenant_id=tenant, project_id=project):
            raise RiskNotFoundError
        specs = {
            spec.origin_key: spec
            for spec in _active_specs(
                c,
                tenant_id=tenant,
                project_id=project,
                today=datetime.now(UTC).date(),
            )
        }
        results = []
        service = RiskCandidateService(engine)
        for item in body.items:
            row = (
                c.execute(
                    _risk_statement().where(
                        tables.risks.c.tenant_id == tenant,
                        tables.risks.c.project_id == project,
                        tables.risks.c.id == item.risk_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise RiskNotFoundError
            before = _record_from_row(row)
            if before.draft_state != "draft" or before.updated_at != item.expected_updated_at:
                raise RiskVersionConflictError
            spec = specs.get(before.origin_key or "")
            if spec is None or (
                before.rule_key,
                before.source_entity,
                before.source_entity_id,
                before.title,
                before.description,
                before.likelihood,
                before.impact,
            ) != (
                spec.rule_key,
                spec.source_entity,
                spec.source_entity_id,
                spec.title,
                spec.description,
                spec.likelihood,
                spec.impact,
            ):
                raise RiskCandidateSourceChangedError
            after = service.confirm(
                tenant_id=tenant,
                actor_user_id=actor,
                project_id=project,
                risk_id=item.risk_id,
                expected_updated_at=item.expected_updated_at,
                shared_connection=c,
            )
            results.append(
                {
                    "risk_id": str(after.id),
                    "title": after.title,
                    "description": after.description,
                    "likelihood": after.likelihood,
                    "impact": after.impact,
                    "score": after.score,
                    "origin_key": after.origin_key,
                    "rule_key": after.rule_key,
                    "source_entity": after.source_entity,
                    "source_entity_id": str(after.source_entity_id),
                    "before_updated_at": before.updated_at.isoformat(),
                    "updated_at": after.updated_at.isoformat(),
                    "draft_state": after.draft_state,
                }
            )
        receipt = (
            c.execute(
                t.insert()
                .values(
                    id=uuid4(),
                    tenant_id=tenant,
                    project_id=project,
                    actor_user_id=actor,
                    request_id=body.request_id,
                    request_digest=digest,
                    request=payload,
                    results=results,
                )
                .returning(t)
            )
            .mappings()
            .one()
        )
        return _receipt(c, receipt, False)
