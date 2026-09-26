"""Combine durable reservations with unbound traces without inventing old usage.

No model/API permission is granted here. Legacy resolutions require a current
active tenant owner/admin and externally verified normalized usage evidence.
Old unreserved providers in flight still require a coordinated adoption fence;
this accounting does not claim to reserve calls made by old code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, RowMapping, select, text

from app.db.schema import tables


class BudgetAccountingError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class LegacyUsageEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence_ref: str = Field(min_length=1)
    input_tokens: int = Field(strict=True, ge=0)
    output_tokens: int = Field(strict=True, ge=0)
    cache_read_tokens: int = Field(default=0, strict=True, ge=0)
    cache_creation_tokens: int = Field(default=0, strict=True, ge=0)

    @model_validator(mode="after")
    def normalized(self) -> Self:
        if (
            not self.evidence_ref.strip()
            or self.cache_read_tokens + self.cache_creation_tokens > self.input_tokens
        ):
            raise ValueError("verified normalized usage evidence required")
        return self

    @property
    def digest(self) -> str:
        return sha256(
            json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


@dataclass(frozen=True)
class UnboundUsage:
    additional_tokens: int
    unresolved_invocation_ids: tuple[UUID, ...]


def latest_resolutions(connection: Connection, tenant: UUID) -> dict[UUID, RowMapping]:
    rows = connection.execute(
        select(tables.legacy_usage_resolutions)
        .where(tables.legacy_usage_resolutions.c.tenant_id == tenant)
        .distinct(tables.legacy_usage_resolutions.c.invocation_id)
        .order_by(
            tables.legacy_usage_resolutions.c.invocation_id,
            tables.legacy_usage_resolutions.c.revision.desc(),
        )
    ).mappings()
    return {row["invocation_id"]: row for row in rows}


def unbound_usage(
    connection: Connection,
    *,
    tenant: UUID,
    now: datetime,
    journal: list[RowMapping],
) -> UnboundUsage:
    # The database reads all latest revisions under the caller's tenant lock.
    # Do not trust a caller-supplied, potentially incomplete journal projection.
    del journal
    row = (
        connection.execute(
            text("SELECT * FROM cehub_ai.unbound_model_usage(:tenant, :now)"),
            dict(tenant=tenant, now=now),
        )
        .mappings()
        .one()
    )
    return UnboundUsage(int(row["additional_tokens"]), tuple(row["unresolved_invocation_ids"]))


class LegacyUsageReconciler:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def reconcile(
        self,
        *,
        tenant_id: UUID,
        invocation_id: UUID,
        reviewer_user_id: UUID,
        evidence: LegacyUsageEvidence,
        expected_revision: int = 0,
    ) -> UUID:
        if type(expected_revision) is not int or expected_revision < 0:
            raise BudgetAccountingError("LEGACY_USAGE_REVISION_INVALID")
        with self._engine.begin() as connection:
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                {"scope": f"pdos-budget:{tenant_id}"},
            )
            reviewer = connection.execute(
                select(tables.users.c.id)
                .where(
                    tables.users.c.tenant_id == tenant_id,
                    tables.users.c.id == reviewer_user_id,
                    tables.users.c.is_active.is_(True),
                    tables.users.c.role.in_(["owner", "admin"]),
                )
                .with_for_update(read=True)
            ).first()
            if reviewer is None:
                raise BudgetAccountingError("LEGACY_USAGE_REVIEW_FORBIDDEN")
            trace = (
                connection.execute(
                    select(tables.model_invocations).where(
                        tables.model_invocations.c.tenant_id == tenant_id,
                        tables.model_invocations.c.id == invocation_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if (
                trace is None
                or trace["budget_call_id"] is not None
                or trace["usage_status"] in {"known", "not_invoked"}
            ):
                raise BudgetAccountingError("LEGACY_USAGE_TARGET_INVALID")
            latest = latest_resolutions(connection, tenant_id).get(invocation_id)
            if (
                latest
                and latest["evidence_digest"] == evidence.digest
                and latest["reviewer_user_id"] == reviewer_user_id
            ):
                return UUID(str(latest["id"]))
            if expected_revision != (latest["revision"] if latest else 0):
                raise BudgetAccountingError("LEGACY_USAGE_REVISION_CONFLICT")
            resolution_id = uuid4()
            row: dict[str, Any] = {
                **evidence.model_dump(),
                "id": resolution_id,
                "tenant_id": tenant_id,
                "invocation_id": invocation_id,
                "reviewer_user_id": reviewer_user_id,
                "revision": expected_revision + 1,
                "evidence_digest": evidence.digest,
                "created_at": connection.execute(text("SELECT clock_timestamp()")).scalar_one(),
            }
            connection.execute(tables.legacy_usage_resolutions.insert(), row)
            return resolution_id
