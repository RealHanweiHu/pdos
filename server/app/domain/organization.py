"""Organization structure, leave delegation, and responsibility handover (vNext V1-A11).

Three concerns share this module because they all answer "who may act for whom":

- **Reporting lines** (`departments`, `users.manager_user_id`) give escalation a
  deterministic next hop and let four-eyes checks reason about independence.
- **Leave delegation** lets a principal hand project reach to a delegate for a
  bounded window. A delegate borrows the principal's *project memberships*, never
  their role or their identity — four-eyes still needs two distinct humans, so a
  delegate acting for a principal cannot also close the loop as themselves.
- **Handover** bulk-transfers open Owner/Verifier responsibility off a departing
  person, leaving one audited event with per-object-type counts.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, Row, or_, select, update

from app.db.schema import tables
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

MAX_REPORTING_DEPTH = 12


class DepartmentNotFoundError(LookupError):
    """Raised when a department is absent from the tenant."""


class UserNotFoundError(LookupError):
    """Raised when a referenced user is absent from the tenant."""


class ReportingCycleError(ValueError):
    """Raised when a reporting line or department parent would form a cycle."""


class DelegationNotFoundError(LookupError):
    """Raised when a delegation is absent or already revoked."""


class DelegationWindowError(ValueError):
    """Raised when a delegation window is empty or already past."""


class HandoverTargetError(ValueError):
    """Raised when handover source and target are the same person."""


@dataclass(frozen=True)
class DepartmentRecord:
    id: UUID
    name: str
    parent_department_id: UUID | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class DelegationRecord:
    id: UUID
    principal_user_id: UUID
    delegate_user_id: UUID
    starts_at: datetime
    ends_at: datetime
    reason: str
    created_by_user_id: UUID
    revoked_at: datetime | None
    revoked_by_user_id: UUID | None
    created_at: datetime

    def is_active_at(self, moment: datetime) -> bool:
        return self.revoked_at is None and self.starts_at <= moment < self.ends_at


@dataclass(frozen=True)
class HandoverResult:
    from_user_id: UUID
    to_user_id: UUID
    transferred_counts: dict[str, int]
    deactivated: bool


def _department(row: Row[Any]) -> DepartmentRecord:
    return DepartmentRecord(
        id=row.id,
        name=row.name,
        parent_department_id=row.parent_department_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _delegation(row: Row[Any]) -> DelegationRecord:
    return DelegationRecord(
        id=row.id,
        principal_user_id=row.principal_user_id,
        delegate_user_id=row.delegate_user_id,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        reason=row.reason,
        created_by_user_id=row.created_by_user_id,
        revoked_at=row.revoked_at,
        revoked_by_user_id=row.revoked_by_user_id,
        created_at=row.created_at,
    )


def active_delegated_principals(
    connection: Connection,
    *,
    tenant_id: UUID,
    delegate_user_id: UUID,
    moment: datetime | None = None,
) -> tuple[UUID, ...]:
    """Principals whose project reach `delegate_user_id` currently borrows.

    Read on the authorization path, so it stays a single indexed query and
    returns an empty tuple for the overwhelmingly common no-delegation case.
    """
    now = (moment or datetime.now(UTC)).astimezone(UTC)
    rows = connection.execute(
        select(tables.user_delegations.c.principal_user_id).where(
            tables.user_delegations.c.tenant_id == tenant_id,
            tables.user_delegations.c.delegate_user_id == delegate_user_id,
            tables.user_delegations.c.revoked_at.is_(None),
            tables.user_delegations.c.starts_at <= now,
            tables.user_delegations.c.ends_at > now,
        )
    ).all()
    return tuple(dict.fromkeys(row.principal_user_id for row in rows))


def escalation_chain(
    connection: Connection,
    *,
    tenant_id: UUID,
    user_id: UUID,
) -> tuple[UUID, ...]:
    """Managers above `user_id`, nearest first, bounded and cycle-safe."""
    chain: list[UUID] = []
    seen = {user_id}
    current = user_id
    for _ in range(MAX_REPORTING_DEPTH):
        manager_id = connection.execute(
            select(tables.users.c.manager_user_id).where(
                tables.users.c.tenant_id == tenant_id,
                tables.users.c.id == current,
            )
        ).scalar_one_or_none()
        if manager_id is None or manager_id in seen:
            break
        chain.append(manager_id)
        seen.add(manager_id)
        current = manager_id
    return tuple(chain)


class OrganizationService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # ---- departments and reporting lines -------------------------------

    def list_departments(self, *, tenant_id: UUID) -> list[DepartmentRecord]:
        with self._engine.connect() as connection:
            return [
                _department(row)
                for row in connection.execute(
                    select(tables.departments)
                    .where(tables.departments.c.tenant_id == tenant_id)
                    .order_by(tables.departments.c.name)
                )
            ]

    def create_department(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        name: str,
        parent_department_id: UUID | None = None,
    ) -> DepartmentRecord:
        occurred_at = datetime.now(UTC)
        department_id = uuid4()
        with self._engine.begin() as connection:
            if parent_department_id is not None:
                self._require_department(
                    connection, tenant_id=tenant_id, department_id=parent_department_id
                )
            connection.execute(
                tables.departments.insert(),
                {
                    "id": department_id,
                    "tenant_id": tenant_id,
                    "name": name,
                    "parent_department_id": parent_department_id,
                    "created_at": occurred_at,
                    "updated_at": occurred_at,
                },
            )
            EventAuditWriter(connection, tenant_id=tenant_id, actor_user_id=actor_user_id).record(
                EventDraft(
                    event_id=f"department:{department_id}:created",
                    event_type="DEPARTMENT_CREATED",
                    source="organization_service",
                    entity_id=department_id,
                    payload={"department_id": str(department_id), "name": name},
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="department.create",
                    after_snapshot={
                        "department_id": str(department_id),
                        "name": name,
                        "parent_department_id": (
                            str(parent_department_id) if parent_department_id else None
                        ),
                    },
                ),
            )
            row = connection.execute(
                select(tables.departments).where(
                    tables.departments.c.tenant_id == tenant_id,
                    tables.departments.c.id == department_id,
                )
            ).one()
            return _department(row)

    def assign_placement(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        user_id: UUID,
        department_id: UUID | None,
        manager_user_id: UUID | None,
    ) -> None:
        """Place a user in the org: department plus reporting line."""
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            before = connection.execute(
                select(
                    tables.users.c.department_id,
                    tables.users.c.manager_user_id,
                    tables.users.c.role,
                    tables.users.c.is_active,
                ).where(tables.users.c.tenant_id == tenant_id, tables.users.c.id == user_id)
            ).one_or_none()
            if before is None:
                raise UserNotFoundError
            if department_id is not None:
                self._require_department(
                    connection, tenant_id=tenant_id, department_id=department_id
                )
            if manager_user_id is not None:
                self._require_user(connection, tenant_id=tenant_id, user_id=manager_user_id)
                if manager_user_id == user_id:
                    raise ReportingCycleError
                # Walking up from the proposed manager must not reach the user.
                if user_id in escalation_chain(
                    connection, tenant_id=tenant_id, user_id=manager_user_id
                ):
                    raise ReportingCycleError
            connection.execute(
                update(tables.users)
                .where(tables.users.c.tenant_id == tenant_id, tables.users.c.id == user_id)
                .values(
                    department_id=department_id,
                    manager_user_id=manager_user_id,
                    updated_at=occurred_at,
                )
            )
            EventAuditWriter(connection, tenant_id=tenant_id, actor_user_id=actor_user_id).record(
                EventDraft(
                    event_id=f"user:{user_id}:placement:{uuid4()}",
                    event_type="USER_UPDATED",
                    source="user_administration_service",
                    entity_id=user_id,
                    payload={
                        "changed_fields": ["department_id", "manager_user_id"],
                        "role": before.role,
                        "is_active": before.is_active,
                    },
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="user.placement_change",
                    before_snapshot={
                        "department_id": str(before.department_id)
                        if before.department_id
                        else None,
                        "manager_user_id": (
                            str(before.manager_user_id) if before.manager_user_id else None
                        ),
                    },
                    after_snapshot={
                        "department_id": str(department_id) if department_id else None,
                        "manager_user_id": str(manager_user_id) if manager_user_id else None,
                    },
                ),
            )

    def escalation_chain_for(self, *, tenant_id: UUID, user_id: UUID) -> tuple[UUID, ...]:
        with self._engine.connect() as connection:
            return escalation_chain(connection, tenant_id=tenant_id, user_id=user_id)

    # ---- leave delegation ----------------------------------------------

    def list_delegations(
        self,
        *,
        tenant_id: UUID,
        principal_user_id: UUID | None = None,
        delegate_user_id: UUID | None = None,
    ) -> list[DelegationRecord]:
        statement = select(tables.user_delegations).where(
            tables.user_delegations.c.tenant_id == tenant_id
        )
        if principal_user_id is not None:
            statement = statement.where(
                tables.user_delegations.c.principal_user_id == principal_user_id
            )
        if delegate_user_id is not None:
            statement = statement.where(
                tables.user_delegations.c.delegate_user_id == delegate_user_id
            )
        with self._engine.connect() as connection:
            return [
                _delegation(row)
                for row in connection.execute(
                    statement.order_by(tables.user_delegations.c.starts_at.desc())
                )
            ]

    def grant_delegation(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        principal_user_id: UUID,
        delegate_user_id: UUID,
        starts_at: datetime,
        ends_at: datetime,
        reason: str,
        now: datetime | None = None,
    ) -> DelegationRecord:
        occurred_at = (now or datetime.now(UTC)).astimezone(UTC)
        starts = starts_at.astimezone(UTC)
        ends = ends_at.astimezone(UTC)
        if ends <= starts or ends <= occurred_at:
            raise DelegationWindowError
        if principal_user_id == delegate_user_id:
            raise HandoverTargetError
        delegation_id = uuid4()
        with self._engine.begin() as connection:
            self._require_user(connection, tenant_id=tenant_id, user_id=principal_user_id)
            self._require_user(connection, tenant_id=tenant_id, user_id=delegate_user_id)
            connection.execute(
                tables.user_delegations.insert(),
                {
                    "id": delegation_id,
                    "tenant_id": tenant_id,
                    "principal_user_id": principal_user_id,
                    "delegate_user_id": delegate_user_id,
                    "starts_at": starts,
                    "ends_at": ends,
                    "reason": reason,
                    "created_by_user_id": actor_user_id,
                    "created_at": occurred_at,
                },
            )
            EventAuditWriter(connection, tenant_id=tenant_id, actor_user_id=actor_user_id).record(
                EventDraft(
                    event_id=f"delegation:{delegation_id}:granted",
                    event_type="USER_DELEGATION_GRANTED",
                    source="organization_service",
                    entity_id=delegation_id,
                    payload={
                        "principal_user_id": str(principal_user_id),
                        "delegate_user_id": str(delegate_user_id),
                        "starts_at": starts.isoformat(),
                        "ends_at": ends.isoformat(),
                    },
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="user.delegation_grant",
                    after_snapshot={
                        "delegation_id": str(delegation_id),
                        "principal_user_id": str(principal_user_id),
                        "delegate_user_id": str(delegate_user_id),
                        "reason": reason,
                    },
                ),
            )
            row = connection.execute(
                select(tables.user_delegations).where(
                    tables.user_delegations.c.tenant_id == tenant_id,
                    tables.user_delegations.c.id == delegation_id,
                )
            ).one()
            return _delegation(row)

    def revoke_delegation(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        delegation_id: UUID,
        now: datetime | None = None,
    ) -> DelegationRecord:
        occurred_at = (now or datetime.now(UTC)).astimezone(UTC)
        with self._engine.begin() as connection:
            row = connection.execute(
                select(tables.user_delegations)
                .where(
                    tables.user_delegations.c.tenant_id == tenant_id,
                    tables.user_delegations.c.id == delegation_id,
                )
                .with_for_update()
            ).one_or_none()
            if row is None or row.revoked_at is not None:
                raise DelegationNotFoundError
            connection.execute(
                update(tables.user_delegations)
                .where(
                    tables.user_delegations.c.tenant_id == tenant_id,
                    tables.user_delegations.c.id == delegation_id,
                    tables.user_delegations.c.revoked_at.is_(None),
                )
                .values(revoked_at=occurred_at, revoked_by_user_id=actor_user_id)
            )
            EventAuditWriter(connection, tenant_id=tenant_id, actor_user_id=actor_user_id).record(
                EventDraft(
                    event_id=f"delegation:{delegation_id}:revoked",
                    event_type="USER_DELEGATION_REVOKED",
                    source="organization_service",
                    entity_id=delegation_id,
                    payload={
                        "principal_user_id": str(row.principal_user_id),
                        "delegate_user_id": str(row.delegate_user_id),
                    },
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="user.delegation_revoke",
                    before_snapshot={"revoked_at": None},
                    after_snapshot={"revoked_at": occurred_at.isoformat()},
                ),
            )
            updated = connection.execute(
                select(tables.user_delegations).where(
                    tables.user_delegations.c.tenant_id == tenant_id,
                    tables.user_delegations.c.id == delegation_id,
                )
            ).one()
            return _delegation(updated)

    # ---- departure handover --------------------------------------------

    def preview_handover(
        self,
        *,
        tenant_id: UUID,
        from_user_id: UUID,
        to_user_id: UUID,
    ) -> dict[str, Any]:
        from app.domain.responsibility_handover import inventory

        with self._engine.connect() as connection:
            return inventory(connection, tenant_id, from_user_id, to_user_id, datetime.now(UTC))

    def hand_over(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        from_user_id: UUID,
        to_user_id: UUID,
        deactivate_source: bool = True,
        expected_digest: str | None = None,
        now: datetime | None = None,
    ) -> HandoverResult:
        from sqlalchemy.dialects.postgresql import insert

        from app.domain.responsibility_handover import (
            HandoverConflictError,
            inventory,
            responsibilities,
        )

        occurred_at = (now or datetime.now(UTC)).astimezone(UTC)
        if from_user_id == to_user_id:
            raise HandoverTargetError
        counts: dict[str, int] = {}
        receipt_key = (
            "user:handover:"
            + hashlib.sha256(
                f"{tenant_id}:{from_user_id}:{to_user_id}:{actor_user_id}:"
                f"{expected_digest}:{int(deactivate_source)}".encode()
            ).hexdigest()
            if expected_digest
            else f"user:{from_user_id}:handover:{uuid4()}"
        )
        # A concurrent assignment or role change must fail this application,
        # rather than deactivate a person after an incomplete inventory.
        with (
            self._engine.connect().execution_options(isolation_level="SERIALIZABLE") as connection,
            connection.begin(),
        ):
            connection.execute(
                select(tables.users.c.id)
                .where(
                    tables.users.c.tenant_id == tenant_id,
                    tables.users.c.id.in_((from_user_id, to_user_id)),
                )
                .order_by(tables.users.c.id)
                .with_for_update()
            )
            prior = connection.execute(
                select(tables.audit_log.c.after_snapshot).where(
                    tables.audit_log.c.tenant_id == tenant_id,
                    tables.audit_log.c.actor_user_id == actor_user_id,
                    tables.audit_log.c.event_id == receipt_key,
                    tables.audit_log.c.action == "user.responsibility_handover",
                )
            ).scalar_one_or_none()
            if prior is not None:
                return HandoverResult(
                    from_user_id=from_user_id,
                    to_user_id=to_user_id,
                    transferred_counts=prior["transferred_counts"],
                    deactivated=prior["deactivated"],
                )
            before = inventory(connection, tenant_id, from_user_id, to_user_id, occurred_at)
            if expected_digest is not None and before["basis_digest"] != expected_digest:
                raise HandoverConflictError("在办责任、成员或代理已经变化，请重新准备交接清单")
            if deactivate_source and before["manual_count"]:
                raise HandoverConflictError(
                    "仍有需在原流程办理的责任；可先移交可办理部分并保留原账号"
                )
            specs = {spec.key: spec for spec in responsibilities()}
            moved = []
            for group in before["groups"]:
                if not group["can_transfer"]:
                    continue
                if group["key"] == "successor_reporting_line":
                    manager_id = before["successor_manager_id"]
                    connection.execute(
                        tables.users.update()
                        .where(
                            tables.users.c.tenant_id == tenant_id, tables.users.c.id == to_user_id
                        )
                        .values(
                            manager_user_id=UUID(manager_id) if manager_id else None,
                            updated_at=occurred_at,
                        )
                    )
                    counts[group["key"]] = 1
                    moved.append({"responsibility": group["key"], "object_ids": [str(to_user_id)]})
                    continue
                spec = specs[group["key"]]
                ids = [UUID(item["id"]) for item in group["items"]]
                values: dict[str, Any] = {spec.column: to_user_id}
                if "updated_at" in spec.table.c:
                    values["updated_at"] = occurred_at
                updated = connection.execute(
                    spec.table.update()
                    .where(
                        spec.table.c.tenant_id == tenant_id,
                        spec.table.c.id.in_(ids),
                        spec.table.c[spec.column] == from_user_id,
                        spec.current,
                    )
                    .values(**values)
                )
                if updated.rowcount != group["count"]:
                    raise HandoverConflictError("移交数量与确认清单不一致，已取消本次提交，请刷新")
                counts[spec.key] = updated.rowcount
                moved.append(
                    {"responsibility": spec.key, "object_ids": [str(value) for value in ids]}
                )
            counts["project_memberships_added"] = 0
            for project_id in before["project_ids"]:
                member_added = connection.execute(
                    insert(tables.project_members)
                    .values(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        project_id=UUID(project_id),
                        user_id=to_user_id,
                        added_by_user_id=actor_user_id,
                    )
                    .on_conflict_do_nothing(index_elements=["tenant_id", "project_id", "user_id"])
                    .returning(tables.project_members.c.id)
                ).scalar_one_or_none()
                counts["project_memberships_added"] += int(member_added is not None)
            if counts["project_memberships_added"] != before["project_access_count"]:
                raise HandoverConflictError("项目成员资格与确认清单已不同，请刷新后重试")
            revoked = connection.execute(
                update(tables.user_delegations)
                .where(
                    tables.user_delegations.c.tenant_id == tenant_id,
                    tables.user_delegations.c.revoked_at.is_(None),
                    tables.user_delegations.c.ends_at > occurred_at,
                    or_(
                        tables.user_delegations.c.principal_user_id == from_user_id,
                        tables.user_delegations.c.delegate_user_id == from_user_id,
                    ),
                )
                .values(revoked_at=occurred_at, revoked_by_user_id=actor_user_id)
            ).rowcount
            counts["delegations_revoked"] = int(revoked or 0)
            if deactivate_source:
                connection.execute(
                    update(tables.users)
                    .where(
                        tables.users.c.tenant_id == tenant_id,
                        tables.users.c.id == from_user_id,
                    )
                    .values(is_active=False, updated_at=occurred_at)
                )
            EventAuditWriter(connection, tenant_id=tenant_id, actor_user_id=actor_user_id).record(
                EventDraft(
                    event_id=receipt_key,
                    event_type="USER_RESPONSIBILITY_TRANSFERRED",
                    source="organization_service",
                    entity_id=from_user_id,
                    payload={
                        "from_user_id": str(from_user_id),
                        "to_user_id": str(to_user_id),
                        "transferred_counts": counts,
                    },
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="user.responsibility_handover",
                    before_snapshot={
                        "from_user_id": str(from_user_id),
                        "basis_digest": before["basis_digest"],
                    },
                    after_snapshot={
                        "to_user_id": str(to_user_id),
                        "transferred_counts": counts,
                        "objects": moved,
                        "project_memberships_added": before["project_ids"],
                        "remaining_manual_count": before["manual_count"],
                        "from_name": before["from_name"],
                        "to_name": before["to_name"],
                        "transferred_items": [g for g in before["groups"] if g["can_transfer"]],
                        "remaining_items": [g for g in before["groups"] if not g["can_transfer"]],
                        "deactivated": deactivate_source,
                    },
                ),
            )
        return HandoverResult(
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            transferred_counts=counts,
            deactivated=deactivate_source,
        )

    # ---- helpers --------------------------------------------------------

    @staticmethod
    def _require_department(
        connection: Connection, *, tenant_id: UUID, department_id: UUID
    ) -> None:
        exists = connection.execute(
            select(tables.departments.c.id).where(
                tables.departments.c.tenant_id == tenant_id,
                tables.departments.c.id == department_id,
            )
        ).scalar_one_or_none()
        if exists is None:
            raise DepartmentNotFoundError

    @staticmethod
    def _require_user(connection: Connection, *, tenant_id: UUID, user_id: UUID) -> None:
        exists = connection.execute(
            select(tables.users.c.id).where(
                tables.users.c.tenant_id == tenant_id,
                tables.users.c.id == user_id,
            )
        ).scalar_one_or_none()
        if exists is None:
            raise UserNotFoundError
