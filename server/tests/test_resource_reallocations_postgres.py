"""Real PostgreSQL reallocation transactions; execution belongs to the coordinator.

Requires explicit TEST_DATABASE_URL and PDOS_SCHEDULE_TEST_ISOLATED=1. This module
never loads .env, migrates, truncates, or cleans another tenant. All business
operations use real domain services with database guards enabled. Only the two
deliberate transaction failure points are monkeypatched.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from queue import Queue
from threading import Barrier
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, Engine, Table, create_engine, func, select, text
from sqlalchemy.engine import make_url

from app.auth.repository import AuthContext, TenantRecord, UserRecord
from app.auth.roles import Role
from app.db.schema import tables
from app.db.test_safety import UnsafeTestDatabaseError, require_test_database_url
from app.db.url import psycopg_database_url
from app.domain.plan_scenarios import CalendarDraft, PlanScenarioService
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError, _plain, digest
from app.domain.resource_capacity import CapacityDraft, ResourceCapacityService, ResourceDraft
from app.domain.resource_priorities import PriorityDraft, ResourcePriorityService
from app.domain.resource_reallocation_inputs import (
    ReallocationApply,
    ReallocationDecision,
    ReallocationDraft,
    ReallocationItem,
    ReallocationReview,
    ReallocationSubmit,
)
from app.domain.resource_reallocations import ResourceReallocationService
from app.domain.resource_reservations import (
    ReservationAction,
    ReservationDraft,
    ResourceReservationService,
)
from app.domain.schedule_nodes import NodeDraft, ScheduleNodeService
from app.domain.tasks import TaskDraft, TaskService
from app.domain.working_time import WorkInterval
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft, WrittenEventAudit

PROTECTED_PORTS = frozenset({57432, 57433, 57434, 57439})
# These are the only rows created by this fixture or the exercised services.
# Append-only histories require trigger suppression strictly during own-tenant
# teardown; core tests always assert session_replication_role=origin.
SCOPED_TABLES = (
    tables.resource_reallocation_applications,
    tables.resource_reallocation_decisions,
    tables.resource_reallocation_items,
    tables.resource_reallocation_projects,
    tables.resource_reallocations,
    tables.resource_reservation_replacements,
    tables.resource_reservation_receipts,
    tables.resource_priority_bindings,
    tables.resource_reservation_intervals,
    tables.resource_reservations,
    tables.resource_capacity_intervals,
    tables.resource_capacity_versions,
    tables.resource_priority_versions,
    tables.planning_resources,
    tables.schedule_nodes,
    tables.work_calendar_versions,
    tables.tasks,
    tables.events,
    tables.audit_log,
    tables.project_members,
    tables.projects,
    tables.workflows,
    tables.users,
)


def isolated_url() -> str:
    value = os.environ.get("TEST_DATABASE_URL")
    if not value:
        raise UnsafeTestDatabaseError("Set explicit TEST_DATABASE_URL; .env is never used")
    require_test_database_url(value)
    url = make_url(value)
    if (
        os.environ.get("PDOS_SCHEDULE_TEST_ISOLATED") != "1"
        or url.drivername not in {"postgres", "postgresql", "postgresql+psycopg"}
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or url.port is None
        or url.port in PROTECTED_PORTS
        or url.query
    ):
        raise UnsafeTestDatabaseError(
            "Coordinator must confirm an isolated local PostgreSQL pdos_test endpoint; "
            "protected ports and URL routing overrides are forbidden"
        )
    return psycopg_database_url(value)


def database_engine(url: str) -> Engine:
    return create_engine(
        url,
        isolation_level="READ COMMITTED",
        pool_size=1,
        max_overflow=2,
        connect_args={"options": "-c statement_timeout=15000 -c lock_timeout=10000"},
    )


@dataclass(frozen=True)
class ProjectSource:
    project_id: UUID
    owner: AuthContext
    task_id: UUID
    node_id: UUID


class Scope:
    def __init__(self, engine: Engine, url: str):
        self.engine, self.url = engine, url
        self.tenant = TenantRecord(uuid4(), f"schedule-pg-{uuid4().hex}", "Schedule PG", "active")
        self.start = (datetime.now(UTC) + timedelta(days=3)).replace(
            hour=9, minute=0, second=0, microsecond=0
        )
        self.resource_id, self.calendar_id, self.capacity_id = uuid4(), uuid4(), uuid4()
        self.sources: list[ProjectSource] = []

    def seed(self) -> None:
        with self.engine.begin() as c:
            c.execute(
                tables.tenants.insert().values(
                    id=self.tenant.id,
                    slug=self.tenant.slug,
                    name=self.tenant.name,
                )
            )
        self.admin = self.person("resource-owner", Role.OWNER)
        self.outsider = self.person("unassigned-pm", Role.PROJECT_MANAGER)
        calendar = PlanScenarioService(self.engine).publish_calendar(
            self.admin,
            CalendarDraft(
                request_id=uuid4(),
                expected_version=0,
                name="PG all-day UTC",
                timezone="UTC",
                working_weekdays=tuple(range(7)),
                intervals=(WorkInterval(start_minute=0, end_minute=1440),),
                reason="Own-tenant integration calendar",
            ),
        )
        self.calendar_id = UUID(calendar["id"])
        resource = ResourceCapacityService(self.engine).create(
            self.admin,
            ResourceDraft(
                request_id=uuid4(),
                name="Own-tenant shared bench",
                kind="bench",
            ),
        )
        self.resource_id = UUID(resource["id"])
        self.capacity_id = UUID(self.publish_capacity(0)["id"])
        for index in range(2):
            owner = self.person(f"project-owner-{index}", Role.PROJECT_MANAGER)
            project, workflow = uuid4(), uuid4()
            with self.engine.begin() as c:
                c.execute(
                    tables.workflows.insert().values(
                        id=workflow,
                        tenant_id=self.tenant.id,
                        code=f"WF-{index}",
                        name="Resource test",
                    )
                )
                # A minimal legacy active project boundary, with actual owners and
                # memberships. This seed does not claim G1/initial-plan approval.
                c.execute(
                    tables.projects.insert().values(
                        id=project,
                        tenant_id=self.tenant.id,
                        workflow_id=workflow,
                        owner_user_id=owner.user.id,
                        code=f"PG-{index}",
                        name=f"Project {index}",
                        status="active",
                    )
                )
                for user in (owner.user.id, self.admin.user.id):
                    c.execute(
                        tables.project_members.insert().values(
                            id=uuid4(),
                            tenant_id=self.tenant.id,
                            project_id=project,
                            user_id=user,
                            added_by_user_id=self.admin.user.id,
                        )
                    )
            task = TaskService(self.engine).create(
                tenant_id=self.tenant.id,
                actor_user_id=owner.user.id,
                project_id=project,
                draft=TaskDraft(
                    stage_id=None,
                    parent_task_id=None,
                    assignee_user_id=owner.user.id,
                    title=f"Bench test {index}",
                    description="Real test task source",
                    priority="medium",
                    start_date=None,
                    due_date=None,
                    dependency_task_ids=(),
                ),
            )
            with self.engine.connect() as c:
                row = (
                    c.execute(
                        select(tables.tasks).where(
                            tables.tasks.c.tenant_id == self.tenant.id,
                            tables.tasks.c.id == task.id,
                        )
                    )
                    .mappings()
                    .one()
                )
                source_digest = digest(_plain(row))
            node = ScheduleNodeService(self.engine).register(
                owner,
                project,
                NodeDraft(
                    request_id=uuid4(),
                    node_kind="task",
                    source_id=task.id,
                    expected_source_digest=source_digest,
                    calendar_version_id=self.calendar_id,
                ),
            )
            self.sources.append(ProjectSource(project, owner, task.id, UUID(node["id"])))
        self.publish_priority(0)

    def person(self, name: str, role: Role) -> AuthContext:
        identity = uuid4()
        with self.engine.begin() as c:
            c.execute(
                tables.users.insert().values(
                    id=identity,
                    tenant_id=self.tenant.id,
                    username=name,
                    display_name=name,
                    role=role,
                )
            )
        return AuthContext(
            self.tenant,
            UserRecord(
                identity,
                self.tenant.id,
                name,
                name,
                role,
                None,
                None,
                1,
                True,
            ),
        )

    def publish_capacity(self, version: int) -> dict[str, Any]:
        return ResourceCapacityService(self.engine).publish(
            self.admin,
            CapacityDraft(
                request_id=uuid4(),
                resource_id=self.resource_id,
                expected_version=version,
                calendar_version_id=self.calendar_id,
                window_start=self.start - timedelta(days=1),
                window_end=self.start + timedelta(days=10),
                parallel_units=Decimal(1),
                basis="Real bench capacity for isolated test",
            ),
        )

    def publish_priority(self, version: int, *, suspended: bool = False) -> dict[str, Any]:
        return ResourcePriorityService(self.engine).save(
            self.admin,
            PriorityDraft(
                request_id=uuid4(),
                resource_id=self.resource_id,
                expected_version=version,
                status="suspended" if suspended else "active",
                valid_from=datetime.now(UTC) - timedelta(days=1),
                valid_until=self.start + timedelta(days=20),
                default_rank=1,
                ranks=[],
                reason="Named same-priority order for both actual projects",
            ),
        )

    def reservations(self, *, confirmed: bool = True) -> list[dict[str, Any]]:
        service = ResourceReservationService(self.engine)
        result = []
        for index, source in enumerate(self.sources):
            start = self.start + timedelta(hours=index * 2)
            value = service.propose(
                source.owner,
                source.project_id,
                ReservationDraft(
                    request_id=uuid4(),
                    node_id=source.node_id,
                    capacity_version_id=self.capacity_id,
                    window_start=start,
                    window_end=start + timedelta(hours=1),
                    parallel_units=Decimal(1),
                    occupancy_policy="working_only",
                    basis="Original bench use",
                ),
            )
            if confirmed:
                value = service.act(
                    self.admin,
                    source.project_id,
                    UUID(value["id"]),
                    ReservationAction(
                        request_id=uuid4(),
                        expected_digest=value["payload_digest"],
                        action="reserve",
                        reason="Resource owner confirms actual original reservation",
                    ),
                )
            result.append(value)
        return result

    def proposal(self, original: list[dict[str, Any]]) -> ReallocationSubmit:
        draft = ReallocationDraft(
            request_id=uuid4(),
            title="Two-project bench adjustment",
            reason="Named test recovery",
            items=tuple(
                ReallocationItem(
                    reservation_id=UUID(row["id"]),
                    expected_digest=row["payload_digest"],
                    impact="Project owner reviews one-day delay with no commitment rewrite",
                    target=ReservationDraft(
                        request_id=uuid4(),
                        node_id=UUID(row["node_id"]),
                        capacity_version_id=self.capacity_id,
                        window_start=datetime.fromisoformat(row["window_start"])
                        + (timedelta(days=1) if row["state"] == "reserved" else timedelta(0)),
                        window_end=datetime.fromisoformat(row["window_end"])
                        + (timedelta(days=1) if row["state"] == "reserved" else timedelta(0)),
                        parallel_units=Decimal(row["parallel_units"]),
                        occupancy_policy=row["occupancy_policy"],
                        basis=row["basis"],
                    ),
                )
                for row in original
            ),
        )
        preview = ResourceReallocationService(self.engine).preview(
            self.admin,
            self.sources[0].project_id,
            draft,
        )
        assert preview["snapshot"]["capacity_clear"] is True
        return ReallocationSubmit.model_validate(
            {
                **draft.model_dump(mode="json"),
                "expected_preview_digest": preview["preview_digest"],
            }
        )

    def save(self, command: ReallocationSubmit) -> tuple[UUID, str]:
        value = ResourceReallocationService(self.engine).submit(
            self.admin, self.sources[0].project_id, command
        )
        return UUID(value["id"]), command.expected_preview_digest

    def decision(
        self, allocation: UUID, payload: str, *, action: str = "approve"
    ) -> ReallocationDecision:
        return ReallocationDecision.model_validate(
            {
                "request_id": str(uuid4()),
                "allocation_id": str(allocation),
                "expected_digest": payload,
                "action": action,
                "reason": "Named project impact confirmation",
            }
        )

    def approve(self, allocation: UUID, payload: str) -> None:
        service = ResourceReallocationService(self.engine)
        for source in self.sources:
            service.decide(source.owner, source.project_id, self.decision(allocation, payload))

    def application(self, allocation: UUID, payload: str) -> ReallocationApply:
        return ReallocationApply(
            request_id=uuid4(),
            allocation_id=allocation,
            expected_digest=payload,
            reason="Independent resource owner application",
        )

    def rows(self, table: Table) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            assert c.execute(text("SHOW session_replication_role")).scalar_one() == "origin"
            values = [
                _plain(dict(row))
                for row in c.execute(
                    select(table).where(table.c.tenant_id == self.tenant.id)
                ).mappings()
            ]
        return sorted(values, key=digest)

    def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        return {table.fullname: self.rows(table) for table in SCOPED_TABLES}

    def assert_applied(self, receipt: dict[str, Any], original: list[dict[str, Any]]) -> None:
        assert receipt["receipt"]["baseline_changed"] is False
        assert receipt["receipt"]["commitments_changed"] is False
        assert len(receipt["receipt"]["items"]) == 2
        assert len(self.rows(tables.resource_reallocation_applications)) == 1
        reservations = {r["id"]: r for r in self.rows(tables.resource_reservations)}
        for item in receipt["receipt"]["items"]:
            old = next(r for r in original if r["id"] == item["previous_reservation_id"])
            target = reservations[item["reservation_id"]]
            assert target["state"] == "reserved"
            assert target["node_id"] == old["node_id"]
            assert target["parallel_units"] == old["parallel_units"]
            if old["state"] == "reserved":
                assert reservations[old["id"]]["state"] == "released"
                assert datetime.fromisoformat(target["window_start"]) == (
                    datetime.fromisoformat(old["window_start"]) + timedelta(days=1)
                )
            else:
                assert target["id"] == old["id"]
        assert len(self.rows(tables.resource_reservation_replacements)) == sum(
            r["state"] == "reserved" for r in original
        )
        # Independent real-ledger check: only the two intended units remain active
        # and their one-hour intervals are disjoint on a one-unit bench.
        active = [r for r in reservations.values() if r["state"] == "reserved"]
        assert len(active) == 2
        intervals = self.rows(tables.resource_reservation_intervals)
        windows = sorted(
            (i["start"], i["end"])
            for i in intervals
            if i["reservation_id"] in {r["id"] for r in active}
        )
        assert len(windows) == 2 and windows[0][1] <= windows[1][0]

    def cleanup(self) -> None:
        # No TRUNCATE, sequence reset or whole-tenant cleanup helper. Replica is
        # transaction-local only so immutable test rows can be removed by tenant.
        with self.engine.begin() as c:
            assert c.execute(text("SHOW session_replication_role")).scalar_one() == "origin"
            c.execute(text("SET LOCAL session_replication_role = replica"))
            for table in SCOPED_TABLES:
                c.execute(table.delete().where(table.c.tenant_id == self.tenant.id))
            c.execute(tables.tenants.delete().where(tables.tenants.c.id == self.tenant.id))
        with self.engine.connect() as c:
            assert c.execute(text("SHOW session_replication_role")).scalar_one() == "origin"
            assert (
                c.execute(
                    select(tables.tenants.c.id).where(tables.tenants.c.id == self.tenant.id)
                ).first()
                is None
            )


@pytest.fixture
def scope() -> Iterator[Scope]:
    url = isolated_url()  # Validate all endpoint conditions before create_engine.
    engine = database_engine(url)
    built = Scope(engine, url)
    try:
        with engine.connect() as c:
            assert c.execute(text("SELECT current_database()")).scalar_one() == "pdos_test"
            assert c.execute(text("SHOW transaction_isolation")).scalar_one() == "read committed"
            assert c.execute(text("SHOW session_replication_role")).scalar_one() == "origin"
            assert c.execute(
                text(
                    "SELECT has_parameter_privilege(current_user, "
                    "'session_replication_role', 'SET')"
                )
            ).scalar_one(), "Isolated test user needs own-tenant append-only teardown permission"
        try:
            built.seed()
            yield built
        finally:
            built.cleanup()
    finally:
        engine.dispose()


@dataclass(frozen=True)
class Outcome:
    backend_pid: int
    value: dict[str, Any] | None
    error: Exception | None


def locked_race(
    scope: Scope,
    operations: tuple[Callable[[Engine], dict[str, Any]], Callable[[Engine], dict[str, Any]]],
    *,
    submit_request: UUID | None = None,
) -> list[Outcome]:
    """Force both real sessions to wait before allowing either transaction to win."""
    barrier, pids = Barrier(3), Queue[int]()

    def worker(operation: Callable[[Engine], dict[str, Any]]) -> Outcome:
        engine = database_engine(scope.url)
        try:
            with engine.connect() as c:
                pid = int(c.execute(select(func.pg_backend_pid())).scalar_one())
                assert c.execute(text("SHOW session_replication_role")).scalar_one() == "origin"
            pids.put(pid)
            barrier.wait(timeout=8)
            try:
                return Outcome(pid, operation(engine), None)
            except Exception as error:
                return Outcome(pid, None, error)
        finally:
            engine.dispose()

    with scope.engine.connect() as blocker, ThreadPoolExecutor(max_workers=2) as executor:
        transaction = blocker.begin()
        if submit_request is None:
            first = min(source.project_id for source in scope.sources)
            blocker.execute(
                select(tables.projects.c.id)
                .where(
                    tables.projects.c.tenant_id == scope.tenant.id,
                    tables.projects.c.id == first,
                )
                .with_for_update()
            )
        else:
            blocker.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {
                    "key": f"resource-reallocation:{scope.tenant.id}:"
                    f"{scope.admin.user.id}:{submit_request}",
                },
            )
        futures = [executor.submit(worker, operation) for operation in operations]
        try:
            backend_pids = [pids.get(timeout=8) for _ in range(2)]
            assert len(set(backend_pids)) == 2
            barrier.wait(timeout=8)
            deadline = time.monotonic() + 6
            waiting: list[int] = []
            with scope.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as monitor:
                while time.monotonic() < deadline:
                    waiting = list(
                        monitor.execute(
                            text(
                                "SELECT pid FROM pg_stat_activity WHERE pid=ANY(:pids) "
                                "AND wait_event_type='Lock'"
                            ),
                            {"pids": backend_pids},
                        )
                        .scalars()
                        .all()
                    )
                    if len(waiting) == 2:
                        break
                    time.sleep(0.02)
                assert len(waiting) == 2, "Both real sessions must reach a PostgreSQL lock wait"
        finally:
            transaction.rollback()  # Releases the observation-only blocker lock.
        return [future.result(timeout=20) for future in futures]


@pytest.mark.parametrize("confirmed", [True, False])
def test_two_projects_save_named_approve_and_apply_real_reservations(
    scope: Scope, confirmed: bool
) -> None:
    original = scope.reservations(confirmed=confirmed)
    command = scope.proposal(original)
    before = scope.snapshot()
    allocation, payload = scope.save(command)
    service = ResourceReallocationService(scope.engine)
    assert len(scope.rows(tables.resource_reallocations)) == 1
    assert len(scope.rows(tables.resource_reallocation_projects)) == 2
    assert len(scope.rows(tables.events)) == len(before[tables.events.fullname]) + 2
    assert len(scope.rows(tables.audit_log)) == len(before[tables.audit_log.fullname]) + 2
    # Saving and approval do not move or occupy a reservation.
    saved_reservations = scope.rows(tables.resource_reservations)
    with pytest.raises(ProductWorkError, match="全部具名同意"):
        service.apply(
            scope.admin, scope.sources[0].project_id, scope.application(allocation, payload)
        )
    scope.approve(allocation, payload)
    assert scope.rows(tables.resource_reservations) == saved_reservations
    for source in scope.sources:
        own = service.list(source.owner, source.project_id)["items"][0]
        assert len(own["parts"]) == 1 and own["parts"][0]["project_id"] == str(source.project_id)
    with pytest.raises(ProductWorkAccessError):
        service.decide(
            scope.outsider, scope.sources[0].project_id, scope.decision(allocation, payload)
        )
    ready = scope.snapshot()
    receipt = service.apply(
        scope.admin, scope.sources[0].project_id, scope.application(allocation, payload)
    )
    scope.assert_applied(receipt, original)
    event_delta = 8 if confirmed else 4
    assert len(scope.rows(tables.events)) == len(ready[tables.events.fullname]) + event_delta
    assert len(scope.rows(tables.audit_log)) == len(ready[tables.audit_log.fullname]) + event_delta


def test_waiting_two_connection_submit_and_approval_are_idempotent(scope: Scope) -> None:
    command = scope.proposal(scope.reservations())
    before_submit = scope.snapshot()

    def submit(engine: Engine) -> dict[str, Any]:
        return ResourceReallocationService(engine).submit(
            scope.admin, scope.sources[0].project_id, command
        )

    result = locked_race(scope, (submit, submit), submit_request=command.request_id)
    assert all(outcome.error is None for outcome in result), result
    assert result[0].value == result[1].value
    assert result[0].value is not None
    allocation = UUID(result[0].value["id"])
    assert len(scope.rows(tables.resource_reallocations)) == 1
    assert len(scope.rows(tables.resource_reallocation_items)) == 2
    assert len(scope.rows(tables.events)) == len(before_submit[tables.events.fullname]) + 2
    assert len(scope.rows(tables.audit_log)) == len(before_submit[tables.audit_log.fullname]) + 2
    source = scope.sources[0]
    decision = scope.decision(allocation, command.expected_preview_digest)

    def decide(engine: Engine) -> dict[str, Any]:
        return ResourceReallocationService(engine).decide(source.owner, source.project_id, decision)

    before = scope.snapshot()
    result = locked_race(scope, (decide, decide))
    assert all(outcome.error is None for outcome in result), result
    assert result[0].value == result[1].value
    assert len(scope.rows(tables.resource_reallocation_decisions)) == 1
    assert len(scope.rows(tables.events)) == len(before[tables.events.fullname]) + 1
    assert len(scope.rows(tables.audit_log)) == len(before[tables.audit_log.fullname]) + 1
    with pytest.raises(ProductWorkError, match="请求编号"):
        ResourceReallocationService(scope.engine).submit(
            scope.admin,
            source.project_id,
            command.model_copy(update={"title": "different content"}),
        )
    with pytest.raises(ProductWorkError, match="请求编号"):
        ResourceReallocationService(scope.engine).decide(
            source.owner,
            source.project_id,
            decision.model_copy(update={"reason": "different content"}),
        )


@pytest.mark.parametrize(
    "drift",
    [
        "original_release",
        "priority_version",
        "priority_suspended",
        "capacity_version",
        "competing_occupancy",
    ],
)
def test_drift_refuses_saved_approved_content_without_partial_application(
    scope: Scope, drift: str
) -> None:
    original = scope.reservations(confirmed=drift != "capacity_version")
    allocation, payload = scope.save(scope.proposal(original))
    scope.approve(allocation, payload)
    if drift == "original_release":
        ResourceReservationService(scope.engine).act(
            scope.admin,
            scope.sources[0].project_id,
            UUID(original[0]["id"]),
            ReservationAction(
                request_id=uuid4(),
                expected_digest=original[0]["payload_digest"],
                action="release",
                reason="Real original source changed",
            ),
        )
    elif drift.startswith("priority"):
        scope.publish_priority(1, suspended=drift == "priority_suspended")
    elif drift == "capacity_version":
        scope.publish_capacity(1)
    else:
        source = scope.sources[0]
        reservation_service = ResourceReservationService(scope.engine)
        competitor = reservation_service.propose(
            source.owner,
            source.project_id,
            ReservationDraft(
                request_id=uuid4(),
                node_id=source.node_id,
                capacity_version_id=scope.capacity_id,
                window_start=scope.start + timedelta(days=1),
                window_end=scope.start + timedelta(days=1, hours=1),
                parallel_units=Decimal(1),
                occupancy_policy="working_only",
                basis="Real conflicting reservation after named approval",
            ),
        )
        reservation_service.act(
            scope.admin,
            source.project_id,
            UUID(competitor["id"]),
            ReservationAction(
                request_id=uuid4(),
                expected_digest=competitor["payload_digest"],
                action="reserve",
                reason="Resource owner confirms intervening actual occupancy",
            ),
        )
    before = scope.snapshot()
    service = ResourceReallocationService(scope.engine)
    review = ReallocationReview(allocation_id=allocation, expected_digest=payload)
    assert (
        service.review(scope.admin, scope.sources[0].project_id, review)["sources_current"] is False
    )
    participant = service.review(scope.sources[0].owner, scope.sources[0].project_id, review)
    assert participant["blockers"] == [
        "整批调整的来源或容量条件已变化，请由资源管理员核对并重新提出"
    ]
    with pytest.raises(ProductWorkError):
        service.apply(
            scope.admin, scope.sources[0].project_id, scope.application(allocation, payload)
        )
    assert scope.snapshot() == before


def test_ended_actual_task_source_refuses_application_and_keeps_original_reservations(
    scope: Scope,
) -> None:
    original = scope.reservations()
    allocation, payload = scope.save(scope.proposal(original))
    scope.approve(allocation, payload)
    source = scope.sources[0]
    # Use the actual task transition rather than directly changing a SQL source row.
    TaskService(scope.engine).transition(
        tenant_id=scope.tenant.id,
        actor_user_id=source.owner.user.id,
        project_id=source.project_id,
        task_id=source.task_id,
        to_status="skipped",
        blocked_reason=None,
    )
    before = scope.snapshot()
    with pytest.raises(ProductWorkError, match="排程来源已结束"):
        ResourceReallocationService(scope.engine).apply(
            scope.admin,
            source.project_id,
            scope.application(allocation, payload),
        )
    assert scope.snapshot() == before


def test_two_connection_application_race_has_one_receipt_and_no_double_occupancy(
    scope: Scope,
) -> None:
    original = scope.reservations()
    allocation, payload = scope.save(scope.proposal(original))
    scope.approve(allocation, payload)
    command = scope.application(allocation, payload)

    def apply(engine: Engine) -> dict[str, Any]:
        return ResourceReallocationService(engine).apply(
            scope.admin, scope.sources[0].project_id, command
        )

    before = scope.snapshot()
    result = locked_race(scope, (apply, apply))
    assert all(outcome.error is None for outcome in result), result
    assert result[0].value == result[1].value and result[0].value is not None
    scope.assert_applied(result[0].value, original)
    assert len(scope.rows(tables.events)) == len(before[tables.events.fullname]) + 8
    assert len(scope.rows(tables.audit_log)) == len(before[tables.audit_log.fullname]) + 8
    saved = scope.snapshot()
    assert (
        ResourceReallocationService(scope.engine).apply(
            scope.admin, scope.sources[0].project_id, command
        )
        == result[0].value
    )
    assert scope.snapshot() == saved


def test_application_and_withdrawal_race_have_exactly_one_terminal_winner(scope: Scope) -> None:
    original = scope.reservations()
    allocation, payload = scope.save(scope.proposal(original))
    scope.approve(allocation, payload)
    command = scope.application(allocation, payload)
    withdraw = scope.decision(allocation, payload, action="withdraw")
    result = locked_race(
        scope,
        (
            lambda engine: ResourceReallocationService(engine).apply(
                scope.admin, scope.sources[0].project_id, command
            ),
            lambda engine: ResourceReallocationService(engine).decide(
                scope.admin, scope.sources[0].project_id, withdraw
            ),
        ),
    )
    assert sum(outcome.error is None for outcome in result) == 1, result
    assert isinstance(
        next(outcome.error for outcome in result if outcome.error is not None), ProductWorkError
    )
    if result[0].value is not None:
        scope.assert_applied(result[0].value, original)
        assert not any(
            d["action"] == "withdraw" for d in scope.rows(tables.resource_reallocation_decisions)
        )
    else:
        assert not scope.rows(tables.resource_reallocation_applications)
        assert {r["id"]: r["state"] for r in scope.rows(tables.resource_reservations)} == {
            r["id"]: "reserved" for r in original
        }


class InjectedFailure(RuntimeError):
    pass


@pytest.mark.parametrize("point", ["second_confirmation", "application_audit"])
def test_real_transaction_rolls_back_all_reservations_receipts_and_audits_then_recovers(
    scope: Scope,
    monkeypatch: pytest.MonkeyPatch,
    point: str,
) -> None:
    original = scope.reservations()
    allocation, payload = scope.save(scope.proposal(original))
    scope.approve(allocation, payload)
    command = scope.application(allocation, payload)
    before = scope.snapshot()
    confirmations = 0
    recorded_audits = 0
    real_act = ResourceReservationService._act_in_transaction
    real_record = EventAuditWriter.record

    def fail_second(
        service: ResourceReservationService,
        c: Connection,
        caller: AuthContext,
        project: UUID,
        reservation: UUID,
        action: ReservationAction,
    ) -> dict[str, Any]:
        nonlocal confirmations
        if action.action == "reserve":
            confirmations += 1
            if confirmations == 2:
                # The first new reservation was truly confirmed in this DB transaction.
                assert (
                    c.execute(
                        select(func.count())
                        .select_from(tables.resource_reservations)
                        .where(
                            tables.resource_reservations.c.tenant_id == scope.tenant.id,
                            tables.resource_reservations.c.state == "reserved",
                        )
                    ).scalar_one()
                    == 1
                )
                raise InjectedFailure("second confirmation")
        return real_act(service, c, caller, project, reservation, action)

    def fail_audit(
        writer: EventAuditWriter, event: EventDraft, audit: AuditDraft
    ) -> WrittenEventAudit:
        nonlocal recorded_audits
        result = real_record(writer, event, audit)
        if audit.action == "resource_reallocation.applied":
            recorded_audits += 1
            # Fail after the real event AND audit SQL, including the application row.
            raise InjectedFailure("application audit after real write")
        return result

    with monkeypatch.context() as fault:
        if point == "second_confirmation":
            fault.setattr(ResourceReservationService, "_act_in_transaction", fail_second)
        else:
            fault.setattr(EventAuditWriter, "record", fail_audit)
        with pytest.raises(InjectedFailure):
            ResourceReallocationService(scope.engine).apply(
                scope.admin, scope.sources[0].project_id, command
            )
    if point == "second_confirmation":
        assert confirmations == 2
    else:
        assert recorded_audits == 1
    assert scope.snapshot() == before
    receipt = ResourceReallocationService(scope.engine).apply(
        scope.admin, scope.sources[0].project_id, command
    )
    scope.assert_applied(receipt, original)
    applied = scope.snapshot()
    assert (
        ResourceReallocationService(scope.engine).apply(
            scope.admin, scope.sources[0].project_id, command
        )
        == receipt
    )
    assert scope.snapshot() == applied
