"""Customer change request chain (vNext V1-B8, G18).

A customer asking for a change and engineering deciding to change something are
different events with different owners, and conflating them is how commitments
get made that nobody costed. This keeps the customer track (CCR) as its own
object: it may *raise* an internal ECR, but it never becomes one.

The chain is: received → impact analysis → quote/lead-time reply → outward
approval (hard gate, four eyes) → customer decision → optional ECR link.

The impact analysis is deterministic: it walks the traceability chain built in
V1-B1 (requirement → specification → test case) rather than asking a model what
might be affected. A commercial answer built on a guess is worse than no answer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, RowMapping, select

from app.db.schema import tables
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

TERMINAL_STATUSES = frozenset({"accepted", "rejected", "cancelled"})


class CustomerChangeNotFoundError(LookupError):
    """Raised when the CCR is absent from the project."""


class CustomerChangeScopeError(ValueError):
    """Raised when a referenced customer, requirement, or ECR is out of scope."""


class CustomerChangeTransitionError(ValueError):
    """Raised when the requested step is not the next one in the chain."""


class CustomerChangeFourEyesError(PermissionError):
    """Raised when the quote drafter tries to approve their own reply."""


@dataclass(frozen=True)
class CustomerChangeRecord:
    id: UUID
    project_id: UUID
    customer_id: UUID
    requirement_id: UUID
    engineering_change_request_id: UUID | None
    code: str
    title: str
    description: str | None
    status: str
    impact_analysis: dict[str, Any] | None
    quote_note: str | None
    lead_time_days: int | None
    customer_decision_note: str | None
    received_by_user_id: UUID
    analyzed_by_user_id: UUID | None
    reply_drafted_by_user_id: UUID | None
    reply_approved_by_user_id: UUID | None
    decision_recorded_by_user_id: UUID | None
    received_at: datetime
    analyzed_at: datetime | None
    reply_drafted_at: datetime | None
    reply_approved_at: datetime | None
    decided_at: datetime | None
    created_at: datetime
    updated_at: datetime


def _record(row: RowMapping) -> CustomerChangeRecord:
    return CustomerChangeRecord(
        id=row["id"],
        project_id=row["project_id"],
        customer_id=row["customer_id"],
        requirement_id=row["requirement_id"],
        engineering_change_request_id=row["engineering_change_request_id"],
        code=row["code"],
        title=row["title"],
        description=row["description"],
        status=row["status"],
        impact_analysis=row["impact_analysis"],
        quote_note=row["quote_note"],
        lead_time_days=row["lead_time_days"],
        customer_decision_note=row["customer_decision_note"],
        received_by_user_id=row["received_by_user_id"],
        analyzed_by_user_id=row["analyzed_by_user_id"],
        reply_drafted_by_user_id=row["reply_drafted_by_user_id"],
        reply_approved_by_user_id=row["reply_approved_by_user_id"],
        decision_recorded_by_user_id=row["decision_recorded_by_user_id"],
        received_at=row["received_at"],
        analyzed_at=row["analyzed_at"],
        reply_drafted_at=row["reply_drafted_at"],
        reply_approved_at=row["reply_approved_at"],
        decided_at=row["decided_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _snapshot(record: CustomerChangeRecord) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "code": record.code,
        "status": record.status,
        "requirement_id": str(record.requirement_id),
        "lead_time_days": record.lead_time_days,
        "engineering_change_request_id": (
            str(record.engineering_change_request_id)
            if record.engineering_change_request_id
            else None
        ),
    }


def analyze_impact(
    connection: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    requirement_id: UUID,
) -> dict[str, Any]:
    """Walk requirement → child requirements → specifications → test cases.

    Every number here is counted from links that already exist, so the reply to
    the customer can be reconciled against the database at any later date.
    """
    requirement_ids = [requirement_id]
    child_rows = connection.execute(
        select(tables.requirements.c.id).where(
            tables.requirements.c.tenant_id == tenant_id,
            tables.requirements.c.parent_requirement_id == requirement_id,
        )
    ).all()
    requirement_ids.extend(row.id for row in child_rows)

    spec_rows = connection.execute(
        select(
            tables.specifications.c.id,
            tables.specifications.c.code,
            tables.specifications.c.title,
        ).where(
            tables.specifications.c.tenant_id == tenant_id,
            tables.specifications.c.project_id == project_id,
            tables.specifications.c.requirement_id.in_(requirement_ids),
        )
    ).all()
    specification_ids = [row.id for row in spec_rows]

    test_rows = (
        connection.execute(
            select(
                tables.test_cases.c.id,
                tables.test_cases.c.title,
                tables.test_cases.c.status,
            ).where(
                tables.test_cases.c.tenant_id == tenant_id,
                tables.test_cases.c.project_id == project_id,
                tables.test_cases.c.specification_id.in_(specification_ids),
            )
        ).all()
        if specification_ids
        else []
    )

    open_tasks = connection.execute(
        select(tables.tasks.c.id).where(
            tables.tasks.c.tenant_id == tenant_id,
            tables.tasks.c.project_id == project_id,
            tables.tasks.c.status.notin_(("done", "cancelled")),
        )
    ).all()

    return {
        "requirements": [str(item) for item in requirement_ids],
        "specifications": [
            {"id": str(row.id), "code": row.code, "title": row.title} for row in spec_rows
        ],
        "test_cases": [
            {"id": str(row.id), "title": row.title, "status": row.status} for row in test_rows
        ],
        "counts": {
            "requirements": len(requirement_ids),
            "specifications": len(spec_rows),
            "test_cases": len(test_rows),
            "passed_test_cases": sum(1 for row in test_rows if row.status == "passed"),
            "open_tasks": len(open_tasks),
        },
        # Re-testing what already passed is the schedule cost this change buys.
        "retest_required": sum(1 for row in test_rows if row.status == "passed"),
    }


class CustomerChangeService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def list(self, *, tenant_id: UUID, project_id: UUID) -> list[CustomerChangeRecord]:
        with self._engine.connect() as connection:
            return [
                _record(row)
                for row in connection.execute(
                    select(tables.customer_change_requests)
                    .where(
                        tables.customer_change_requests.c.tenant_id == tenant_id,
                        tables.customer_change_requests.c.project_id == project_id,
                    )
                    .order_by(tables.customer_change_requests.c.created_at.desc())
                ).mappings()
            ]

    def create(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        customer_id: UUID,
        requirement_id: UUID,
        code: str,
        title: str,
        description: str | None,
        now: datetime | None = None,
    ) -> CustomerChangeRecord:
        occurred_at = (now or datetime.now(UTC)).astimezone(UTC)
        change_id = uuid4()
        with self._engine.begin() as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise CustomerChangeNotFoundError
            self._require_scope(
                connection,
                tenant_id=tenant_id,
                customer_id=customer_id,
                requirement_id=requirement_id,
            )
            connection.execute(
                tables.customer_change_requests.insert(),
                {
                    "id": change_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "customer_id": customer_id,
                    "requirement_id": requirement_id,
                    "received_by_user_id": actor_user_id,
                    "code": code,
                    "title": title,
                    "description": description,
                    "status": "received",
                    "received_at": occurred_at,
                    "created_at": occurred_at,
                    "updated_at": occurred_at,
                },
            )
            record = self._get(connection, tenant_id=tenant_id, change_id=change_id)
            self._emit(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                record=record,
                action="created",
                before=None,
                occurred_at=occurred_at,
            )
            return record

    def analyze(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        change_id: UUID,
        now: datetime | None = None,
    ) -> CustomerChangeRecord:
        return self._advance(
            tenant_id=tenant_id,
            project_id=project_id,
            actor_user_id=actor_user_id,
            change_id=change_id,
            from_statuses={"received", "impact_analyzed"},
            action="impact_analyzed",
            now=now,
            build_values=lambda connection, before, at: {
                "status": "impact_analyzed",
                "impact_analysis": analyze_impact(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    requirement_id=before.requirement_id,
                ),
                "analyzed_by_user_id": actor_user_id,
                "analyzed_at": at,
            },
        )

    def draft_reply(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        change_id: UUID,
        quote_note: str,
        lead_time_days: int,
        now: datetime | None = None,
    ) -> CustomerChangeRecord:
        return self._advance(
            tenant_id=tenant_id,
            project_id=project_id,
            actor_user_id=actor_user_id,
            change_id=change_id,
            from_statuses={"impact_analyzed", "reply_drafted"},
            action="reply_drafted",
            now=now,
            build_values=lambda connection, before, at: {
                "status": "reply_drafted",
                "quote_note": quote_note,
                "lead_time_days": lead_time_days,
                "reply_drafted_by_user_id": actor_user_id,
                "reply_drafted_at": at,
            },
        )

    def approve_reply(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        change_id: UUID,
        now: datetime | None = None,
    ) -> CustomerChangeRecord:
        """Hard gate: committing a price and a date outward needs a second person."""

        def values(
            connection: Connection, before: CustomerChangeRecord, at: datetime
        ) -> dict[str, Any]:
            if before.reply_drafted_by_user_id == actor_user_id:
                raise CustomerChangeFourEyesError
            return {
                "status": "reply_approved",
                "reply_approved_by_user_id": actor_user_id,
                "reply_approved_at": at,
            }

        return self._advance(
            tenant_id=tenant_id,
            project_id=project_id,
            actor_user_id=actor_user_id,
            change_id=change_id,
            from_statuses={"reply_drafted"},
            action="reply_approved",
            now=now,
            build_values=values,
        )

    def record_customer_decision(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        change_id: UUID,
        accepted: bool,
        note: str | None,
        now: datetime | None = None,
    ) -> CustomerChangeRecord:
        status = "accepted" if accepted else "rejected"
        return self._advance(
            tenant_id=tenant_id,
            project_id=project_id,
            actor_user_id=actor_user_id,
            change_id=change_id,
            from_statuses={"reply_approved"},
            action=status,
            now=now,
            build_values=lambda connection, before, at: {
                "status": status,
                "customer_decision_note": note,
                "decision_recorded_by_user_id": actor_user_id,
                "decided_at": at,
            },
        )

    def link_engineering_change(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        change_id: UUID,
        engineering_change_request_id: UUID,
        now: datetime | None = None,
    ) -> CustomerChangeRecord:
        """Attach the internal ECR the accepted change spawned.

        The two objects stay separate; this only records that one caused the
        other, so the engineering track keeps its own approval trail.
        """

        def values(
            connection: Connection, before: CustomerChangeRecord, at: datetime
        ) -> dict[str, Any]:
            exists = connection.execute(
                select(tables.engineering_change_requests.c.id).where(
                    tables.engineering_change_requests.c.tenant_id == tenant_id,
                    tables.engineering_change_requests.c.project_id == project_id,
                    tables.engineering_change_requests.c.id == engineering_change_request_id,
                )
            ).scalar_one_or_none()
            if exists is None:
                raise CustomerChangeScopeError
            return {"engineering_change_request_id": engineering_change_request_id}

        return self._advance(
            tenant_id=tenant_id,
            project_id=project_id,
            actor_user_id=actor_user_id,
            change_id=change_id,
            from_statuses={"accepted"},
            action="ecr_linked",
            now=now,
            build_values=values,
        )

    # ---- internals ------------------------------------------------------

    def _advance(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        change_id: UUID,
        from_statuses: set[str],
        action: str,
        build_values: Callable[[Connection, CustomerChangeRecord, datetime], dict[str, Any]],
        now: datetime | None,
    ) -> CustomerChangeRecord:
        occurred_at = (now or datetime.now(UTC)).astimezone(UTC)
        with self._engine.begin() as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise CustomerChangeNotFoundError
            before = self._get(
                connection, tenant_id=tenant_id, change_id=change_id, project_id=project_id
            )
            if before.status not in from_statuses:
                raise CustomerChangeTransitionError
            values = build_values(connection, before, occurred_at)
            values["updated_at"] = occurred_at
            connection.execute(
                tables.customer_change_requests.update()
                .where(
                    tables.customer_change_requests.c.tenant_id == tenant_id,
                    tables.customer_change_requests.c.id == change_id,
                )
                .values(**values)
            )
            after = self._get(connection, tenant_id=tenant_id, change_id=change_id)
            self._emit(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                record=after,
                action=action,
                before=before,
                occurred_at=occurred_at,
            )
            return after

    @staticmethod
    def _emit(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        record: CustomerChangeRecord,
        action: str,
        before: CustomerChangeRecord | None,
        occurred_at: datetime,
    ) -> None:
        EventAuditWriter(
            connection,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            project_id=project_id,
        ).record(
            EventDraft(
                event_id=f"customer-change:{record.id}:{action}:{uuid4()}",
                event_type="CHANGE_RECORD_CHANGED",
                source="change_service",
                entity_id=record.id,
                payload={"record_type": "customer_change_request", "action": action},
                occurred_at=occurred_at,
            ),
            AuditDraft(
                action=f"customer_change.{action}",
                before_snapshot=_snapshot(before) if before else None,
                after_snapshot=_snapshot(record),
            ),
        )

    @staticmethod
    def _get(
        connection: Connection,
        *,
        tenant_id: UUID,
        change_id: UUID,
        project_id: UUID | None = None,
    ) -> CustomerChangeRecord:
        statement = select(tables.customer_change_requests).where(
            tables.customer_change_requests.c.tenant_id == tenant_id,
            tables.customer_change_requests.c.id == change_id,
        )
        if project_id is not None:
            statement = statement.where(tables.customer_change_requests.c.project_id == project_id)
        row = connection.execute(statement).mappings().one_or_none()
        if row is None:
            raise CustomerChangeNotFoundError
        return _record(row)

    @staticmethod
    def _require_scope(
        connection: Connection,
        *,
        tenant_id: UUID,
        customer_id: UUID,
        requirement_id: UUID,
    ) -> None:
        customer = connection.execute(
            select(tables.customers.c.id).where(
                tables.customers.c.tenant_id == tenant_id,
                tables.customers.c.id == customer_id,
            )
        ).scalar_one_or_none()
        requirement = connection.execute(
            select(tables.requirements.c.id).where(
                tables.requirements.c.tenant_id == tenant_id,
                tables.requirements.c.id == requirement_id,
            )
        ).scalar_one_or_none()
        if customer is None or requirement is None:
            raise CustomerChangeScopeError
