"""Project-bound NPI build, sample, test, and certification service."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError

from app.auth.roles import Role
from app.db.schema import tables
from app.domain.test_templates import (
    TemplateError,
    TemplateSelection,
    instantiate_cases,
    plan_coverage,
    project_template_snapshot,
)
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

NPI_PHASES = frozenset({"evt", "dvt", "pvt"})


class NpiNotFoundError(LookupError):
    """Raised when an NPI object is outside the tenant-bound project."""


class NpiScopeError(ValueError):
    """Raised when a relation or phase crosses its project boundary."""


class NpiTransitionError(ValueError):
    """Raised when a frozen lifecycle rejects an update."""


class NpiAudienceError(PermissionError):
    """Raised when a Sample signoff audience does not match the actor."""


class NpiConflictError(ValueError):
    """Raised when a unique NPI identity conflicts."""


def _plain(row: RowMapping) -> dict[str, Any]:
    return dict(row)


def _snapshot(values: dict[str, Any]) -> dict[str, Any]:
    def normalize(value: Any) -> Any:
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, dict):
            return {str(key): normalize(item) for key, item in value.items()}
        return value

    result: dict[str, Any] = {}
    for key, value in values.items():
        if key in {"created_at", "updated_at"}:
            continue
        result[key] = normalize(value)
    return result


class NpiExecutionService:
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
            raise NpiNotFoundError
        return row

    @staticmethod
    def _phase_stage(
        connection: Connection,
        *,
        tenant_id: UUID,
        workflow_id: UUID,
        stage_id: UUID,
        phase: str,
    ) -> None:
        if phase not in NPI_PHASES:
            raise NpiScopeError
        code = connection.execute(
            select(tables.stages.c.code).where(
                tables.stages.c.tenant_id == tenant_id,
                tables.stages.c.workflow_id == workflow_id,
                tables.stages.c.id == stage_id,
            )
        ).scalar_one_or_none()
        if code != phase:
            raise NpiScopeError

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
            raise NpiNotFoundError
        return row

    @staticmethod
    def _record_change(
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
                event_id=f"npi:{record_type}:{record_id}:{action}:{uuid4()}",
                event_type="NPI_RECORD_CHANGED",
                source="npi_service",
                entity_id=record_id,
                payload={"record_type": record_type, "action": action},
            ),
            AuditDraft(
                action=f"npi.{record_type}.{action}",
                before_snapshot=before,
                after_snapshot=after,
            ),
        )

    @staticmethod
    def _list(
        connection: Connection, table: Any, *, tenant_id: UUID, project_id: UUID
    ) -> list[dict[str, Any]]:
        return [
            _plain(row)
            for row in connection.execute(
                select(table)
                .where(table.c.tenant_id == tenant_id, table.c.project_id == project_id)
                .order_by(table.c.created_at, table.c.id)
            ).mappings()
        ]

    def snapshot(
        self, *, tenant_id: UUID, project_id: UUID, role: Role
    ) -> dict[str, list[dict[str, Any]]]:
        with self._engine.connect() as connection:
            self._project(connection, tenant_id=tenant_id, project_id=project_id)
            signoff_statement = select(tables.sample_signoffs).where(
                tables.sample_signoffs.c.tenant_id == tenant_id,
                tables.sample_signoffs.c.project_id == project_id,
            )
            if role in {Role.SUPPLIER, Role.CUSTOMER}:
                signoff_statement = signoff_statement.where(
                    tables.sample_signoffs.c.audience == role.value
                )
            signoffs = [
                _plain(signoff_row)
                for signoff_row in connection.execute(
                    signoff_statement.order_by(
                        tables.sample_signoffs.c.created_at, tables.sample_signoffs.c.id
                    )
                ).mappings()
            ]
            signoff_ids = [row["id"] for row in signoffs]
            signoff_samples: dict[UUID, list[UUID]] = {signoff_id: [] for signoff_id in signoff_ids}
            if signoff_ids:
                for relation_row in connection.execute(
                    select(
                        tables.sample_signoff_samples.c.signoff_id,
                        tables.sample_signoff_samples.c.sample_id,
                    ).where(
                        tables.sample_signoff_samples.c.tenant_id == tenant_id,
                        tables.sample_signoff_samples.c.signoff_id.in_(signoff_ids),
                    )
                ):
                    signoff_samples[relation_row.signoff_id].append(relation_row.sample_id)
            for signoff in signoffs:
                signoff["sample_ids"] = signoff_samples[signoff["id"]]
            if role in {Role.SUPPLIER, Role.CUSTOMER}:
                return {
                    "builds": [],
                    "samples": [],
                    "sample_signoffs": signoffs,
                    "test_plans": [],
                    "test_cases": [],
                    "test_reports": [],
                    "certifications": [],
                    "certification_alerts": [],
                }
            test_cases = self._list(
                connection,
                tables.test_cases,
                tenant_id=tenant_id,
                project_id=project_id,
            )
            test_case_ids = [row["id"] for row in test_cases]
            test_case_samples: dict[UUID, list[UUID]] = {
                test_case_id: [] for test_case_id in test_case_ids
            }
            if test_case_ids:
                for relation_row in connection.execute(
                    select(
                        tables.test_case_samples.c.test_case_id,
                        tables.test_case_samples.c.sample_id,
                    ).where(
                        tables.test_case_samples.c.tenant_id == tenant_id,
                        tables.test_case_samples.c.test_case_id.in_(test_case_ids),
                    )
                ):
                    test_case_samples[relation_row.test_case_id].append(relation_row.sample_id)
            for test_case in test_cases:
                test_case["sample_ids"] = test_case_samples[test_case["id"]]
            plans = self._list(
                connection, tables.test_plans, tenant_id=tenant_id, project_id=project_id
            )
            item_order = {
                (plan["id"], item["key"]): index
                for plan in plans
                for index, item in enumerate((plan["template_snapshot"] or {}).get("items", []))
            }
            plan_order = {plan["id"]: index for index, plan in enumerate(plans)}
            test_cases.sort(
                key=lambda case: (
                    plan_order[case["plan_id"]],
                    item_order.get((case["plan_id"], case["template_item_key"]), 10_000),
                )
            )
            return {
                "builds": self._list(
                    connection, tables.build_batches, tenant_id=tenant_id, project_id=project_id
                ),
                "samples": self._list(
                    connection, tables.samples, tenant_id=tenant_id, project_id=project_id
                ),
                "sample_signoffs": signoffs,
                "test_plans": [
                    {
                        **plan,
                        "coverage": plan_coverage(
                            connection, tenant_id=tenant_id, project_id=project_id, plan=plan
                        ),
                    }
                    for plan in plans
                ],
                "test_cases": test_cases,
                "test_reports": self._list(
                    connection, tables.test_reports, tenant_id=tenant_id, project_id=project_id
                ),
                "certifications": self._list(
                    connection, tables.certifications, tenant_id=tenant_id, project_id=project_id
                ),
                "certification_alerts": self._list(
                    connection,
                    tables.certification_expiry_alerts,
                    tenant_id=tenant_id,
                    project_id=project_id,
                ),
            }

    def build_options(self, *, tenant_id: UUID, project_id: UUID) -> dict[str, Any]:
        with self._engine.connect() as connection:
            project = self._project(connection, tenant_id=tenant_id, project_id=project_id)
            stages = (
                connection.execute(
                    select(tables.stages.c.id, tables.stages.c.code, tables.stages.c.name)
                    .where(
                        tables.stages.c.tenant_id == tenant_id,
                        tables.stages.c.workflow_id == project["workflow_id"],
                        tables.stages.c.code.in_(["evt", "dvt", "pvt"]),
                    )
                    .order_by(tables.stages.c.code, tables.stages.c.id)
                )
                .mappings()
                .all()
            )
            return {"stages": [_plain(row) for row in stages]}

    def create_build(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        stage_id: UUID,
        phase: str,
        code: str,
        planned_quantity: int,
        notes: str | None,
        purpose: str = "engineering_build",
    ) -> dict[str, Any]:
        if (
            not code.strip()
            or len(code.strip()) > 64
            or purpose
            not in {
                "engineering_build",
                "certification_sample",
                "customer_sample",
                "reliability_test",
                "production_trial",
            }
        ):
            raise NpiConflictError
        code = code.strip()
        record_id = uuid4()
        try:
            with self._engine.begin() as connection:
                project = self._project(
                    connection, tenant_id=tenant_id, project_id=project_id, lock=True
                )
                self._phase_stage(
                    connection,
                    tenant_id=tenant_id,
                    workflow_id=project["workflow_id"],
                    stage_id=stage_id,
                    phase=phase,
                )
                row = (
                    connection.execute(
                        tables.build_batches.insert()
                        .values(
                            id=record_id,
                            tenant_id=tenant_id,
                            project_id=project_id,
                            workflow_id=project["workflow_id"],
                            stage_id=stage_id,
                            created_by_user_id=actor_user_id,
                            phase=phase,
                            purpose=purpose,
                            code=code,
                            planned_quantity=planned_quantity,
                            notes=notes,
                        )
                        .returning(tables.build_batches)
                    )
                    .mappings()
                    .one()
                )
                record = _plain(row)
                self._record_change(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    actor_user_id=actor_user_id,
                    record_id=record_id,
                    record_type="build",
                    action="created",
                    before=None,
                    after=_snapshot(record),
                )
                return record
        except IntegrityError as error:
            raise NpiConflictError from error

    def update_build(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        build_id: UUID,
        status: str,
        completed_quantity: int,
    ) -> dict[str, Any]:
        with self._engine.begin() as connection:
            self._project(connection, tenant_id=tenant_id, project_id=project_id, lock=True)
            before_row = self._row(
                connection,
                tables.build_batches,
                tenant_id=tenant_id,
                project_id=project_id,
                record_id=build_id,
                lock=True,
            )
            allowed = {
                "planned": {"in_progress", "completed", "cancelled"},
                "in_progress": {"completed", "cancelled"},
            }
            if status not in allowed.get(before_row["status"], set()):
                raise NpiTransitionError
            if status == "completed":
                sample_count = connection.execute(
                    select(func.count())
                    .select_from(tables.samples)
                    .where(
                        tables.samples.c.tenant_id == tenant_id,
                        tables.samples.c.project_id == project_id,
                        tables.samples.c.build_batch_id == build_id,
                        tables.samples.c.status != "scrapped",
                    )
                ).scalar_one()
                if completed_quantity != sample_count:
                    raise NpiTransitionError
            if before_row["status"] == "planned" and status in {"in_progress", "completed"}:
                from app.domain.material_admission import enforce

                enforce(connection, tenant_id, project_id, actor_user_id, "build", build_id)
            now = datetime.now(UTC)
            values: dict[str, Any] = {
                "status": status,
                "completed_quantity": completed_quantity,
                "updated_at": now,
            }
            if status in {"in_progress", "completed"}:
                values["started_at"] = before_row["started_at"] or now
            if status == "completed":
                values["completed_at"] = now
            from app.domain.schedule_execution import guard_source_action

            guard_source_action(
                connection,
                tenant_id,
                project_id,
                build_id,
                "build",
                "npi.build.updated",
                _snapshot({**dict(before_row), **values}),
                now,
            )
            row = (
                connection.execute(
                    tables.build_batches.update()
                    .where(
                        tables.build_batches.c.id == build_id,
                        tables.build_batches.c.tenant_id == tenant_id,
                    )
                    .values(**values)
                    .returning(tables.build_batches)
                )
                .mappings()
                .one()
            )
            record = _plain(row)
            self._record_change(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                record_id=build_id,
                record_type="build",
                action="updated",
                before=_snapshot(_plain(before_row)),
                after=_snapshot(record),
            )
            return record

    def create_sample(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        build_id: UUID,
        serial_number: str,
        parent_sample_id: UUID | None,
        prototype_bom_id: UUID | None,
        notes: str | None,
    ) -> dict[str, Any]:
        try:
            with self._engine.begin() as connection:
                return self.create_sample_in_connection(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    actor_user_id=actor_user_id,
                    build_id=build_id,
                    serial_number=serial_number,
                    parent_sample_id=parent_sample_id,
                    prototype_bom_id=prototype_bom_id,
                    notes=notes,
                )
        except IntegrityError as error:
            raise NpiConflictError from error

    def create_sample_in_connection(
        self,
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        build_id: UUID,
        serial_number: str,
        parent_sample_id: UUID | None,
        prototype_bom_id: UUID | None,
        notes: str | None,
        built_at: datetime | None = None,
        built_at_precision: str = "unknown",
    ) -> dict[str, Any]:
        record_id = uuid4()
        self._project(connection, tenant_id=tenant_id, project_id=project_id, lock=True)
        build = self._row(
            connection,
            tables.build_batches,
            tenant_id=tenant_id,
            project_id=project_id,
            record_id=build_id,
            lock=True,
        )
        if build["status"] not in {"planned", "in_progress"}:
            raise NpiTransitionError
        sample_count = connection.execute(
            select(func.count())
            .select_from(tables.samples)
            .where(
                tables.samples.c.tenant_id == tenant_id,
                tables.samples.c.project_id == project_id,
                tables.samples.c.build_batch_id == build_id,
            )
        ).scalar_one()
        if sample_count >= build["planned_quantity"]:
            raise NpiConflictError
        if parent_sample_id is not None:
            self._row(
                connection,
                tables.samples,
                tenant_id=tenant_id,
                project_id=project_id,
                record_id=parent_sample_id,
            )
        if prototype_bom_id is not None:
            bom = self._row(
                connection,
                tables.development_boms,
                tenant_id=tenant_id,
                project_id=project_id,
                record_id=prototype_bom_id,
            )
            if bom["bom_type"] != "prototype":
                raise NpiScopeError
        row = (
            connection.execute(
                tables.samples.insert()
                .values(
                    id=record_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    build_batch_id=build_id,
                    parent_sample_id=parent_sample_id,
                    prototype_bom_id=prototype_bom_id,
                    created_by_user_id=actor_user_id,
                    serial_number=serial_number,
                    notes=notes,
                    **(
                        {"built_at": built_at, "built_at_precision": built_at_precision}
                        if built_at is not None
                        else {}
                    ),
                )
                .returning(tables.samples)
            )
            .mappings()
            .one()
        )
        record = _plain(row)
        self._record_change(
            connection,
            tenant_id=tenant_id,
            project_id=project_id,
            actor_user_id=actor_user_id,
            record_id=record_id,
            record_type="sample",
            action="created",
            before=None,
            after=_snapshot(record),
        )
        return record

    def create_signoff(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        phase: str,
        title: str,
        signoff_type: str,
        audience: str,
        sample_ids: list[UUID],
        due_date: date | None,
    ) -> dict[str, Any]:
        record_id = uuid4()
        with self._engine.begin() as connection:
            self._project(connection, tenant_id=tenant_id, project_id=project_id, lock=True)
            for sample_id in sample_ids:
                sample = self._row(
                    connection,
                    tables.samples,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    record_id=sample_id,
                )
                build_phase = connection.execute(
                    select(tables.build_batches.c.phase).where(
                        tables.build_batches.c.tenant_id == tenant_id,
                        tables.build_batches.c.id == sample["build_batch_id"],
                    )
                ).scalar_one()
                if build_phase != phase:
                    raise NpiScopeError
            row = (
                connection.execute(
                    tables.sample_signoffs.insert()
                    .values(
                        id=record_id,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        requested_by_user_id=actor_user_id,
                        phase=phase,
                        title=title,
                        signoff_type=signoff_type,
                        audience=audience,
                        due_date=due_date,
                    )
                    .returning(tables.sample_signoffs)
                )
                .mappings()
                .one()
            )
            connection.execute(
                tables.sample_signoff_samples.insert(),
                [
                    {
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "signoff_id": record_id,
                        "sample_id": sample_id,
                    }
                    for sample_id in sample_ids
                ],
            )
            record = _plain(row)
            record["sample_ids"] = sample_ids
            self._record_change(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                record_id=record_id,
                record_type="sample_signoff",
                action="created",
                before=None,
                after=_snapshot(record),
            )
            return record

    def respond_signoff(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        actor_role: Role,
        signoff_id: UUID,
        status: str,
        note: str | None,
    ) -> dict[str, Any]:
        with self._engine.begin() as connection:
            self._project(connection, tenant_id=tenant_id, project_id=project_id, lock=True)
            before_row = self._row(
                connection,
                tables.sample_signoffs,
                tenant_id=tenant_id,
                project_id=project_id,
                record_id=signoff_id,
                lock=True,
            )
            if before_row["status"] != "pending":
                raise NpiTransitionError
            if (
                actor_role in {Role.SUPPLIER, Role.CUSTOMER}
                and before_row["audience"] != actor_role.value
            ):
                raise NpiAudienceError
            if actor_role not in {
                Role.OWNER,
                Role.ADMIN,
                Role.PROJECT_MANAGER,
                Role.QUALITY,
                Role.SUPPLIER,
                Role.CUSTOMER,
            }:
                raise NpiAudienceError
            if actor_role in {Role.SUPPLIER, Role.CUSTOMER} and status == "waived":
                raise NpiAudienceError
            row = (
                connection.execute(
                    tables.sample_signoffs.update()
                    .where(
                        tables.sample_signoffs.c.id == signoff_id,
                        tables.sample_signoffs.c.tenant_id == tenant_id,
                    )
                    .values(
                        status=status,
                        response_note=note,
                        responded_by_user_id=actor_user_id,
                        responded_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                    )
                    .returning(tables.sample_signoffs)
                )
                .mappings()
                .one()
            )
            record = _plain(row)
            self._record_change(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                record_id=signoff_id,
                record_type="sample_signoff",
                action="responded",
                before=_snapshot(_plain(before_row)),
                after=_snapshot(record),
            )
            return record

    def create_test_plan(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        stage_id: UUID,
        phase: str,
        title: str,
        scope: str | None,
        sample_size: int,
        status: str,
        template: TemplateSelection | None = None,
    ) -> dict[str, Any]:
        record_id = uuid4()
        with self._engine.begin() as connection:
            project = self._project(
                connection, tenant_id=tenant_id, project_id=project_id, lock=True
            )
            baseline = (
                project_template_snapshot(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    selection=template,
                    actor_user_id=actor_user_id,
                )
                if template
                else None
            )
            self._phase_stage(
                connection,
                tenant_id=tenant_id,
                workflow_id=project["workflow_id"],
                stage_id=stage_id,
                phase=phase,
            )
            row = (
                connection.execute(
                    tables.test_plans.insert()
                    .values(
                        id=record_id,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        workflow_id=project["workflow_id"],
                        stage_id=stage_id,
                        created_by_user_id=actor_user_id,
                        phase=phase,
                        title=title,
                        scope=scope,
                        sample_size=sample_size,
                        status=status,
                        template_snapshot=baseline,
                    )
                    .returning(tables.test_plans)
                )
                .mappings()
                .one()
            )
            record = _plain(row)
            if baseline is not None:
                instantiate_cases(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    plan_id=record_id,
                    actor_user_id=actor_user_id,
                    snapshot=baseline,
                )
            self._record_change(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                record_id=record_id,
                record_type="test_plan",
                action="created",
                before=None,
                after=_snapshot(record),
            )
            return record

    def bind_test_template(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        plan_id: UUID,
        selection: TemplateSelection,
    ) -> dict[str, Any]:
        with self._engine.begin() as connection:
            self._project(connection, tenant_id=tenant_id, project_id=project_id, lock=True)
            baseline = project_template_snapshot(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                selection=selection,
                actor_user_id=actor_user_id,
            )
            plan = self._row(
                connection,
                tables.test_plans,
                tenant_id=tenant_id,
                project_id=project_id,
                record_id=plan_id,
                lock=True,
            )
            exists = connection.execute(
                select(tables.test_cases.c.id)
                .where(
                    tables.test_cases.c.tenant_id == tenant_id,
                    tables.test_cases.c.plan_id == plan_id,
                )
                .limit(1)
            ).first()
            if plan["template_snapshot"] is not None or exists or plan["status"] == "completed":
                raise TemplateError("仅空白计划可绑定模板；换版请创建新计划，保留原计划和结果")
            connection.execute(
                tables.test_plans.update()
                .where(
                    tables.test_plans.c.tenant_id == tenant_id,
                    tables.test_plans.c.id == plan_id,
                )
                .values(template_snapshot=baseline, updated_at=datetime.now(UTC))
            )
            instantiate_cases(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                plan_id=plan_id,
                actor_user_id=actor_user_id,
                snapshot=baseline,
            )
            self._record_change(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                record_id=plan_id,
                record_type="test_plan",
                action="template_bound",
                before=_snapshot(dict(plan)),
                after=_snapshot({**dict(plan), "template_snapshot": baseline}),
            )
            return {"plan_id": plan_id, "template_snapshot": baseline}

    def create_test_case(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        plan_id: UUID,
        title: str,
        category: str,
        acceptance_criteria: str,
        method: str | None,
        severity: str,
        sample_ids: list[UUID],
    ) -> dict[str, Any]:
        record_id = uuid4()
        with self._engine.begin() as connection:
            self._project(connection, tenant_id=tenant_id, project_id=project_id, lock=True)
            plan = self._row(
                connection,
                tables.test_plans,
                tenant_id=tenant_id,
                project_id=project_id,
                record_id=plan_id,
            )
            for sample_id in sample_ids:
                sample = self._row(
                    connection,
                    tables.samples,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    record_id=sample_id,
                )
                phase = connection.execute(
                    select(tables.build_batches.c.phase).where(
                        tables.build_batches.c.tenant_id == tenant_id,
                        tables.build_batches.c.id == sample["build_batch_id"],
                    )
                ).scalar_one()
                if phase != plan["phase"]:
                    raise NpiScopeError
            row = (
                connection.execute(
                    tables.test_cases.insert()
                    .values(
                        id=record_id,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        plan_id=plan_id,
                        created_by_user_id=actor_user_id,
                        title=title,
                        category=category,
                        acceptance_criteria=acceptance_criteria,
                        method=method,
                        severity=severity,
                    )
                    .returning(tables.test_cases)
                )
                .mappings()
                .one()
            )
            connection.execute(
                tables.test_case_samples.insert(),
                [
                    {
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "test_case_id": record_id,
                        "sample_id": sample_id,
                    }
                    for sample_id in sample_ids
                ],
            )
            record = _plain(row)
            record["sample_ids"] = sample_ids
            self._record_change(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                record_id=record_id,
                record_type="test_case",
                action="created",
                before=None,
                after=_snapshot(record),
            )
            return record

    def record_test_result(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        test_case_id: UUID,
        status: str,
        result_notes: str | None,
        related_issue_id: UUID | None,
    ) -> dict[str, Any]:
        with self._engine.begin() as connection:
            self._project(connection, tenant_id=tenant_id, project_id=project_id, lock=True)
            before_row = self._row(
                connection,
                tables.test_cases,
                tenant_id=tenant_id,
                project_id=project_id,
                record_id=test_case_id,
                lock=True,
            )
            if status == before_row["status"] or status not in {
                "planned",
                "passed",
                "failed",
                "blocked",
                "waived",
            }:
                raise NpiTransitionError
            if before_row["status"] == "planned" and status == "planned":
                raise NpiTransitionError
            if related_issue_id is not None:
                self._row(
                    connection,
                    tables.issues,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    record_id=related_issue_id,
                )
            now = datetime.now(UTC)
            values: dict[str, Any] = {
                "status": status,
                "result_notes": result_notes,
                "related_issue_id": related_issue_id,
                "updated_at": now,
            }
            if status == "planned":
                values.update(executed_by_user_id=None, executed_at=None)
            else:
                values.update(executed_by_user_id=actor_user_id, executed_at=now)
            row = (
                connection.execute(
                    tables.test_cases.update()
                    .where(
                        tables.test_cases.c.id == test_case_id,
                        tables.test_cases.c.tenant_id == tenant_id,
                    )
                    .values(**values)
                    .returning(tables.test_cases)
                )
                .mappings()
                .one()
            )
            record = _plain(row)
            if status == "failed":
                EventAuditWriter(
                    connection,
                    tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                    project_id=project_id,
                ).record(
                    EventDraft(
                        event_id=f"test:{test_case_id}:failed:{uuid4()}",
                        event_type="TEST_FAILED",
                        source="quality_service",
                        entity_id=test_case_id,
                        payload={
                            "test_record_id": str(test_case_id),
                            "severity": record["severity"],
                        },
                    ),
                    AuditDraft(
                        action="npi.test_case.failed",
                        before_snapshot=_snapshot(_plain(before_row)),
                        after_snapshot=_snapshot(record),
                    ),
                )
            else:
                self._record_change(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    actor_user_id=actor_user_id,
                    record_id=test_case_id,
                    record_type="test_case",
                    action="result_recorded",
                    before=_snapshot(_plain(before_row)),
                    after=_snapshot(record),
                )
            return record

    def create_test_report(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        plan_id: UUID,
        report_number: str,
        title: str,
        result: str,
        summary: str,
    ) -> dict[str, Any]:
        record_id = uuid4()
        with self._engine.begin() as connection:
            self._project(connection, tenant_id=tenant_id, project_id=project_id, lock=True)
            self._row(
                connection,
                tables.test_plans,
                tenant_id=tenant_id,
                project_id=project_id,
                record_id=plan_id,
            )
            row = (
                connection.execute(
                    tables.test_reports.insert()
                    .values(
                        id=record_id,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        plan_id=plan_id,
                        created_by_user_id=actor_user_id,
                        report_number=report_number,
                        title=title,
                        result=result,
                        summary=summary,
                    )
                    .returning(tables.test_reports)
                )
                .mappings()
                .one()
            )
            record = _plain(row)
            self._record_change(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                record_id=record_id,
                record_type="test_report",
                action="created",
                before=None,
                after=_snapshot(record),
            )
            return record

    def review_test_report(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        report_id: UUID,
        review_status: str,
        note: str | None,
    ) -> dict[str, Any]:
        with self._engine.begin() as connection:
            self._project(connection, tenant_id=tenant_id, project_id=project_id, lock=True)
            before_row = self._row(
                connection,
                tables.test_reports,
                tenant_id=tenant_id,
                project_id=project_id,
                record_id=report_id,
                lock=True,
            )
            if before_row["review_status"] != "pending":
                raise NpiTransitionError
            row = (
                connection.execute(
                    tables.test_reports.update()
                    .where(
                        tables.test_reports.c.id == report_id,
                        tables.test_reports.c.tenant_id == tenant_id,
                    )
                    .values(
                        review_status=review_status,
                        review_note=note,
                        reviewed_by_user_id=actor_user_id,
                        reviewed_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                    )
                    .returning(tables.test_reports)
                )
                .mappings()
                .one()
            )
            record = _plain(row)
            self._record_change(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                record_id=report_id,
                record_type="test_report",
                action="reviewed",
                before=_snapshot(_plain(before_row)),
                after=_snapshot(record),
            )
            return record

    def create_certification(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        owner_user_id: UUID,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        record_id = uuid4()
        with self._engine.begin() as connection:
            self._project(connection, tenant_id=tenant_id, project_id=project_id, lock=True)
            owner = connection.execute(
                select(tables.users.c.id).where(
                    tables.users.c.tenant_id == tenant_id,
                    tables.users.c.id == owner_user_id,
                    tables.users.c.is_active.is_(True),
                )
            ).scalar_one_or_none()
            if owner is None:
                raise NpiScopeError
            row = (
                connection.execute(
                    tables.certifications.insert()
                    .values(
                        id=record_id,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        created_by_user_id=actor_user_id,
                        owner_user_id=owner_user_id,
                        **values,
                    )
                    .returning(tables.certifications)
                )
                .mappings()
                .one()
            )
            record = _plain(row)
            self._record_change(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                record_id=record_id,
                record_type="certification",
                action="created",
                before=None,
                after=_snapshot(record),
            )
            return record

    def scan_certifications(
        self, *, tenant_id: UUID, project_id: UUID, actor_user_id: UUID, as_of: date
    ) -> dict[str, int]:
        alerts_created = 0
        expired_count = 0
        with self._engine.begin() as connection:
            self._project(connection, tenant_id=tenant_id, project_id=project_id, lock=True)
            rows = tuple(
                connection.execute(
                    select(tables.certifications)
                    .where(
                        tables.certifications.c.tenant_id == tenant_id,
                        tables.certifications.c.project_id == project_id,
                        tables.certifications.c.status == "valid",
                    )
                    .with_for_update()
                ).mappings()
            )
            for row in rows:
                valid_until = row["valid_until"]
                if valid_until < as_of:
                    connection.execute(
                        tables.certifications.update()
                        .where(
                            tables.certifications.c.id == row["id"],
                            tables.certifications.c.tenant_id == tenant_id,
                        )
                        .values(status="expired", updated_at=datetime.now(UTC))
                    )
                    expired_count += 1
                    self._record_change(
                        connection,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        actor_user_id=actor_user_id,
                        record_id=row["id"],
                        record_type="certification",
                        action="expired",
                        before=_snapshot(_plain(row)),
                        after={**_snapshot(_plain(row)), "status": "expired"},
                    )
                remaining = (valid_until - as_of).days
                lead = next(
                    (candidate for candidate in (0, 30, 90) if remaining == candidate), None
                )
                if lead is not None:
                    alert_id = uuid4()
                    inserted = connection.execute(
                        pg_insert(tables.certification_expiry_alerts)
                        .values(
                            id=alert_id,
                            tenant_id=tenant_id,
                            project_id=project_id,
                            certification_id=row["id"],
                            valid_until=valid_until,
                            lead_days=lead,
                            recipient_user_id=row["owner_user_id"],
                        )
                        .on_conflict_do_nothing(
                            index_elements=[
                                "tenant_id",
                                "certification_id",
                                "valid_until",
                                "lead_days",
                            ]
                        )
                        .returning(tables.certification_expiry_alerts.c.id)
                    ).scalar_one_or_none()
                    alerts_created += int(inserted is not None)
                    if inserted is not None:
                        self._record_change(
                            connection,
                            tenant_id=tenant_id,
                            project_id=project_id,
                            actor_user_id=actor_user_id,
                            record_id=alert_id,
                            record_type="certification_expiry_alert",
                            action="created",
                            before=None,
                            after={
                                "certification_id": str(row["id"]),
                                "valid_until": valid_until.isoformat(),
                                "lead_days": lead,
                                "recipient_user_id": str(row["owner_user_id"]),
                            },
                        )
            return {"expired_count": expired_count, "alerts_created": alerts_created}
