"""Project-bound ECR, ECN, effectivity, and frozen ERP handoff governance."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, select
from sqlalchemy.engine import RowMapping

from app.db.schema import tables
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class ChangeNotFoundError(LookupError):
    """Raised when an object is outside the tenant-bound project."""


class ChangeScopeError(ValueError):
    """Raised when a relation crosses a tenant/project or BOM boundary."""


class ChangeTransitionError(ValueError):
    """Raised when the frozen lifecycle rejects a transition."""


class ChangeFourEyesError(PermissionError):
    """Raised when a requester attempts to approve their own ECR."""


class ChangeHandoffNotReadyError(ValueError):
    """Raised while the PVT Gate is not approved."""


def _normalize(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in value.items()}
    return value


def _snapshot(row: RowMapping | dict[str, Any]) -> dict[str, Any]:
    return {
        key: _normalize(value)
        for key, value in dict(row).items()
        if key not in {"created_at", "updated_at"}
    }


class ChangeGovernanceService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _project(
        connection: Connection, *, tenant_id: UUID, project_id: UUID, lock: bool = False
    ) -> RowMapping:
        statement = select(tables.projects).where(
            tables.projects.c.tenant_id == tenant_id,
            tables.projects.c.id == project_id,
        )
        if lock:
            statement = statement.with_for_update()
        row = connection.execute(statement).mappings().one_or_none()
        if row is None:
            raise ChangeNotFoundError
        return row

    @staticmethod
    def _row(
        connection: Connection,
        table: Any,
        *,
        tenant_id: UUID,
        project_id: UUID,
        record_id: UUID,
        lock: bool = False,
    ) -> RowMapping:
        statement = select(table).where(
            table.c.tenant_id == tenant_id,
            table.c.project_id == project_id,
            table.c.id == record_id,
        )
        if lock:
            statement = statement.with_for_update()
        row = connection.execute(statement).mappings().one_or_none()
        if row is None:
            raise ChangeNotFoundError
        return row

    @staticmethod
    def _record(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        record_id: UUID,
        record_type: str,
        action: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> None:
        EventAuditWriter(
            connection,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            project_id=project_id,
        ).record(
            EventDraft(
                event_id=f"change:{record_type}:{record_id}:{action}:{uuid4()}",
                event_type="CHANGE_RECORD_CHANGED",
                source="change_service",
                entity_id=record_id,
                payload={"record_type": record_type, "action": action},
            ),
            AuditDraft(
                action=f"change.{record_type}.{action}",
                before_snapshot=before,
                after_snapshot=after,
            ),
        )

    @staticmethod
    def _changed_row(
        connection: Connection,
        table: Any,
        *,
        tenant_id: UUID,
        record_id: UUID,
        values: dict[str, Any],
    ) -> RowMapping:
        return (
            connection.execute(
                table.update()
                .where(table.c.tenant_id == tenant_id, table.c.id == record_id)
                .values(**values)
                .returning(table)
            )
            .mappings()
            .one()
        )

    def snapshot(self, *, tenant_id: UUID, project_id: UUID) -> dict[str, list[dict[str, Any]]]:
        with self._engine.connect() as connection:
            self._project(connection, tenant_id=tenant_id, project_id=project_id)
            ecrs = [
                dict(row)
                for row in connection.execute(
                    select(tables.engineering_change_requests)
                    .where(
                        tables.engineering_change_requests.c.tenant_id == tenant_id,
                        tables.engineering_change_requests.c.project_id == project_id,
                    )
                    .order_by(
                        tables.engineering_change_requests.c.created_at,
                        tables.engineering_change_requests.c.id,
                    )
                ).mappings()
            ]
            affected: dict[UUID, list[UUID]] = {row["id"]: [] for row in ecrs}
            if affected:
                for relation in connection.execute(
                    select(tables.ecr_affected_boms).where(
                        tables.ecr_affected_boms.c.tenant_id == tenant_id,
                        tables.ecr_affected_boms.c.project_id == project_id,
                    )
                ).mappings():
                    affected[relation["ecr_id"]].append(relation["bom_id"])
            for row in ecrs:
                row["affected_bom_ids"] = affected[row["id"]]

            def rows(table: Any) -> list[dict[str, Any]]:
                return [
                    dict(row)
                    for row in connection.execute(
                        select(table)
                        .where(table.c.tenant_id == tenant_id, table.c.project_id == project_id)
                        .order_by(table.c.created_at, table.c.id)
                    ).mappings()
                ]

            return {
                "ecrs": ecrs,
                "ecns": rows(tables.engineering_change_notices),
                "handoffs": rows(tables.erp_handoffs),
            }

    def create_ecr(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        code: str,
        title: str,
        reason: str,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        record_id = uuid4()
        with self._engine.begin() as connection:
            self._project(connection, tenant_id=tenant_id, project_id=project_id, lock=True)
            row = (
                connection.execute(
                    tables.engineering_change_requests.insert()
                    .values(
                        id=record_id,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        requested_by_user_id=actor_user_id,
                        code=code,
                        title=title,
                        reason=reason,
                        status="request",
                        created_at=now,
                        updated_at=now,
                    )
                    .returning(tables.engineering_change_requests)
                )
                .mappings()
                .one()
            )
            self._record(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                record_id=record_id,
                record_type="ecr",
                action="created",
                before=None,
                after=_snapshot(row),
            )
            return dict(row)

    def start_impact(
        self, *, tenant_id: UUID, project_id: UUID, actor_user_id: UUID, ecr_id: UUID
    ) -> dict[str, Any]:
        return self._transition_ecr(
            tenant_id=tenant_id,
            project_id=project_id,
            actor_user_id=actor_user_id,
            ecr_id=ecr_id,
            expected="request",
            status="impact_analysis",
            action="impact_started",
        )

    def _transition_ecr(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        ecr_id: UUID,
        expected: str,
        status: str,
        action: str,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            self._project(connection, tenant_id=tenant_id, project_id=project_id, lock=True)
            before = self._row(
                connection,
                tables.engineering_change_requests,
                tenant_id=tenant_id,
                project_id=project_id,
                record_id=ecr_id,
                lock=True,
            )
            if before["status"] != expected:
                raise ChangeTransitionError
            row = self._changed_row(
                connection,
                tables.engineering_change_requests,
                tenant_id=tenant_id,
                record_id=ecr_id,
                values={"status": status, "updated_at": now},
            )
            self._record(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                record_id=ecr_id,
                record_type="ecr",
                action=action,
                before=_snapshot(before),
                after=_snapshot(row),
            )
            return dict(row)

    def submit_impact(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        ecr_id: UUID,
        impact_analysis: dict[str, Any],
        affected_bom_ids: list[UUID],
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            self._project(connection, tenant_id=tenant_id, project_id=project_id, lock=True)
            before = self._row(
                connection,
                tables.engineering_change_requests,
                tenant_id=tenant_id,
                project_id=project_id,
                record_id=ecr_id,
                lock=True,
            )
            if before["status"] != "impact_analysis":
                raise ChangeTransitionError
            found = (
                set(
                    connection.execute(
                        select(tables.development_boms.c.id).where(
                            tables.development_boms.c.tenant_id == tenant_id,
                            tables.development_boms.c.project_id == project_id,
                            tables.development_boms.c.id.in_(affected_bom_ids),
                        )
                    ).scalars()
                )
                if affected_bom_ids
                else set()
            )
            if found != set(affected_bom_ids):
                raise ChangeScopeError
            if affected_bom_ids:
                connection.execute(
                    tables.ecr_affected_boms.insert(),
                    [
                        {
                            "tenant_id": tenant_id,
                            "project_id": project_id,
                            "ecr_id": ecr_id,
                            "bom_id": bom_id,
                        }
                        for bom_id in affected_bom_ids
                    ],
                )
            row = self._changed_row(
                connection,
                tables.engineering_change_requests,
                tenant_id=tenant_id,
                record_id=ecr_id,
                values={
                    "status": "approval",
                    "impact_analysis": impact_analysis,
                    "analyzed_by_user_id": actor_user_id,
                    "analyzed_at": now,
                    "updated_at": now,
                },
            )
            self._record(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                record_id=ecr_id,
                record_type="ecr",
                action="impact_submitted",
                before=_snapshot(before),
                after={
                    **_snapshot(row),
                    "affected_bom_ids": [str(value) for value in affected_bom_ids],
                },
            )
            return dict(row)

    def decide_ecr(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        ecr_id: UUID,
        outcome: Literal["approved", "rejected"],
        note: str | None,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            self._project(connection, tenant_id=tenant_id, project_id=project_id, lock=True)
            before = self._row(
                connection,
                tables.engineering_change_requests,
                tenant_id=tenant_id,
                project_id=project_id,
                record_id=ecr_id,
                lock=True,
            )
            if before["status"] != "approval":
                raise ChangeTransitionError
            if before["requested_by_user_id"] == actor_user_id:
                raise ChangeFourEyesError
            decision_id = uuid4()
            connection.execute(
                tables.decisions.insert(),
                {
                    "id": decision_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "decided_by_user_id": actor_user_id,
                    "decision_kind": "ecr_approval",
                    "title": f"ECR {before['code']} approval",
                    "outcome": outcome,
                    "rationale": note,
                    "decided_at": now,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            row = self._changed_row(
                connection,
                tables.engineering_change_requests,
                tenant_id=tenant_id,
                record_id=ecr_id,
                values={
                    "status": outcome,
                    "approval_decision_id": decision_id,
                    "approved_by_user_id": actor_user_id,
                    "approval_note": note,
                    "approved_at": now,
                    "updated_at": now,
                },
            )
            self._record(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                record_id=ecr_id,
                record_type="ecr",
                action=outcome,
                before=_snapshot(before),
                after=_snapshot(row),
            )
            return dict(row)

    def create_ecn(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        ecr_id: UUID,
        code: str,
        title: str,
        implementation_plan: dict[str, Any],
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        record_id = uuid4()
        with self._engine.begin() as connection:
            self._project(connection, tenant_id=tenant_id, project_id=project_id, lock=True)
            ecr = self._row(
                connection,
                tables.engineering_change_requests,
                tenant_id=tenant_id,
                project_id=project_id,
                record_id=ecr_id,
                lock=True,
            )
            if ecr["status"] != "approved":
                raise ChangeTransitionError
            row = (
                connection.execute(
                    tables.engineering_change_notices.insert()
                    .values(
                        id=record_id,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        ecr_id=ecr_id,
                        created_by_user_id=actor_user_id,
                        code=code,
                        title=title,
                        status="ecn",
                        implementation_plan=implementation_plan,
                        created_at=now,
                        updated_at=now,
                    )
                    .returning(tables.engineering_change_notices)
                )
                .mappings()
                .one()
            )
            self._record(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                record_id=record_id,
                record_type="ecn",
                action="created",
                before=None,
                after=_snapshot(row),
            )
            return dict(row)

    def submit_effectivity(
        self, *, tenant_id: UUID, project_id: UUID, actor_user_id: UUID, ecn_id: UUID
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            self._project(connection, tenant_id=tenant_id, project_id=project_id, lock=True)
            before = self._row(
                connection,
                tables.engineering_change_notices,
                tenant_id=tenant_id,
                project_id=project_id,
                record_id=ecn_id,
                lock=True,
            )
            if before["status"] != "ecn":
                raise ChangeTransitionError
            row = self._changed_row(
                connection,
                tables.engineering_change_notices,
                tenant_id=tenant_id,
                record_id=ecn_id,
                values={"status": "effectivity_decision", "updated_at": now},
            )
            self._record(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                record_id=ecn_id,
                record_type="ecn",
                action="effectivity_submitted",
                before=_snapshot(before),
                after=_snapshot(row),
            )
            return dict(row)

    @staticmethod
    def _bom_snapshot(
        connection: Connection, *, tenant_id: UUID, project_id: UUID, bom_id: UUID
    ) -> dict[str, Any]:
        bom = (
            connection.execute(
                select(tables.development_boms).where(
                    tables.development_boms.c.tenant_id == tenant_id,
                    tables.development_boms.c.project_id == project_id,
                    tables.development_boms.c.id == bom_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if bom is None or bom["bom_type"] != "ebom":
            raise ChangeScopeError
        items = [
            _snapshot(row)
            for row in connection.execute(
                select(tables.development_bom_items)
                .where(
                    tables.development_bom_items.c.tenant_id == tenant_id,
                    tables.development_bom_items.c.project_id == project_id,
                    tables.development_bom_items.c.bom_id == bom_id,
                )
                .order_by(tables.development_bom_items.c.line_number)
            ).mappings()
        ]
        return {"header": _snapshot(bom), "items": items}

    def decide_effectivity(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        ecn_id: UUID,
        outcome: Literal["approved", "rejected"],
        effectivity: dict[str, Any],
        released_bom_id: UUID | None,
        target_system: str,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            self._project(connection, tenant_id=tenant_id, project_id=project_id, lock=True)
            before = self._row(
                connection,
                tables.engineering_change_notices,
                tenant_id=tenant_id,
                project_id=project_id,
                record_id=ecn_id,
                lock=True,
            )
            if before["status"] != "effectivity_decision":
                raise ChangeTransitionError
            bom_snapshot: dict[str, Any] | None = None
            if outcome == "approved":
                if released_bom_id is None:
                    raise ChangeScopeError
                bom_snapshot = self._bom_snapshot(
                    connection, tenant_id=tenant_id, project_id=project_id, bom_id=released_bom_id
                )
            decision_id = uuid4()
            connection.execute(
                tables.decisions.insert(),
                {
                    "id": decision_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "decided_by_user_id": actor_user_id,
                    "decision_kind": "ecn_effectivity",
                    "title": f"ECN {before['code']} effectivity",
                    "outcome": outcome,
                    "rationale": effectivity.get("rationale"),
                    "decided_at": now,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            status = "erp_handoff" if outcome == "approved" else "cancelled"
            row = self._changed_row(
                connection,
                tables.engineering_change_notices,
                tenant_id=tenant_id,
                record_id=ecn_id,
                values={
                    "status": status,
                    "effectivity": effectivity,
                    "effectivity_decision_id": decision_id,
                    "effectivity_decided_by_user_id": actor_user_id,
                    "effectivity_decided_at": now,
                    "released_bom_id": released_bom_id,
                    "released_bom_type": "ebom" if released_bom_id else None,
                    "updated_at": now,
                },
            )
            self._record(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                record_id=ecn_id,
                record_type="ecn",
                action=f"effectivity_{outcome}",
                before=_snapshot(before),
                after=_snapshot(row),
            )
            response: dict[str, Any] = {"ecn": dict(row), "handoff": None}
            if outcome == "approved" and bom_snapshot is not None and released_bom_id is not None:
                handoff_id = uuid4()
                handoff = (
                    connection.execute(
                        tables.erp_handoffs.insert()
                        .values(
                            id=handoff_id,
                            tenant_id=tenant_id,
                            project_id=project_id,
                            ecn_id=ecn_id,
                            source_bom_id=released_bom_id,
                            prepared_by_user_id=actor_user_id,
                            status="pending",
                            target_system=target_system,
                            source_bom_snapshot=bom_snapshot,
                            effectivity_snapshot=_normalize(effectivity),
                            created_at=now,
                            updated_at=now,
                        )
                        .returning(tables.erp_handoffs)
                    )
                    .mappings()
                    .one()
                )
                self._record(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    actor_user_id=actor_user_id,
                    record_id=handoff_id,
                    record_type="erp_handoff",
                    action="prepared",
                    before=None,
                    after=_snapshot(handoff),
                )
                response["handoff"] = dict(handoff)
            return response

    def mark_handoff_ready(
        self, *, tenant_id: UUID, project_id: UUID, actor_user_id: UUID, handoff_id: UUID
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            project = self._project(
                connection, tenant_id=tenant_id, project_id=project_id, lock=True
            )
            before = self._row(
                connection,
                tables.erp_handoffs,
                tenant_id=tenant_id,
                project_id=project_id,
                record_id=handoff_id,
                lock=True,
            )
            if before["status"] != "pending":
                raise ChangeTransitionError
            approved = connection.execute(
                select(tables.gates.c.id)
                .select_from(
                    tables.gates.join(
                        tables.stages,
                        (tables.stages.c.tenant_id == tables.gates.c.tenant_id)
                        & (tables.stages.c.id == tables.gates.c.stage_id),
                    )
                )
                .where(
                    tables.gates.c.tenant_id == tenant_id,
                    tables.gates.c.project_id == project_id,
                    tables.gates.c.status == "approved",
                    tables.stages.c.workflow_id == project["workflow_id"],
                    tables.stages.c.code == "pvt",
                )
            ).scalar_one_or_none()
            if approved is None:
                raise ChangeHandoffNotReadyError
            row = self._changed_row(
                connection,
                tables.erp_handoffs,
                tenant_id=tenant_id,
                record_id=handoff_id,
                values={
                    "status": "ready",
                    "ready_by_user_id": actor_user_id,
                    "ready_at": now,
                    "updated_at": now,
                },
            )
            self._record(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                record_id=handoff_id,
                record_type="erp_handoff",
                action="ready",
                before=_snapshot(before),
                after=_snapshot(row),
            )
            return dict(row)
