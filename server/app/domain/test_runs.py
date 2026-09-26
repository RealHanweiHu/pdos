"""Structured test-run execution use cases (vNext V1-B3, D29/G28).

A test run is one execution of a test case: conditions, structured metrics,
equipment, operator, and evidence. Long-running tests stay `in_progress` with
an expected completion time so the wait is visible; a terminal result syncs
the parent test case and, on failure, auto-links (or auto-creates) a
`test_failure` Issue in its staging `open` state.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, Table, func, select
from sqlalchemy.engine import RowMapping

from app.db.schema import tables
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.sample_configuration_revisions import pin_current_configuration, run_selection
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

TERMINAL_RUN_STATUSES = frozenset({"passed", "failed", "aborted"})
_ISSUE_SEVERITY_BY_CASE = {"minor": "medium", "major": "high", "critical": "critical"}


class TestRunNotFoundError(LookupError):
    """Raised when a test run or its test case is absent from the Project."""


class TestRunScopeError(ValueError):
    """Raised when a related sample, document, or operator is outside scope."""


class TestRunStateError(ValueError):
    """Raised on invalid run status usage (e.g. completing a terminal run)."""


@dataclass(frozen=True)
class TestRunRecord:
    id: UUID
    project_id: UUID
    test_case_id: UUID
    sample_id: UUID | None
    operator_user_id: UUID | None
    evidence_document_id: UUID | None
    run_number: int
    status: str
    draft_state: str
    conditions: dict[str, object]
    metrics: tuple[dict[str, object], ...]
    equipment: str | None
    environment: str | None
    result_notes: str | None
    started_at: datetime | None
    expected_completion_at: datetime | None
    executed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    related_issue_id: UUID | None = None
    sample_configuration_revision_id: UUID | None = None
    configuration_revision: dict[str, Any] | None = None
    import_successor_batch_id: UUID | None = None
    import_batch_id: UUID | None = None
    execution_time_precision: str = "unknown"
    execution_time_source: str = "legacy_unknown"
    operator_name: str | None = None
    source_field_capture_id: UUID | None = None
    test_preparation_id: UUID | None = None
    test_preparation: dict[str, Any] | None = None


@dataclass(frozen=True)
class TestRunDraft:
    status: str
    sample_id: UUID | None = None
    conditions: dict[str, object] = field(default_factory=dict)
    metrics: tuple[dict[str, object], ...] = field(default_factory=tuple)
    equipment: str | None = None
    environment: str | None = None
    result_notes: str | None = None
    expected_completion_at: datetime | None = None
    evidence_document_id: UUID | None = None
    executed_at: datetime | None = None
    execution_time_precision: str = "unknown"
    execution_time_reason: str | None = None
    configuration_mode: str = "current"
    configuration_revision_id: UUID | None = None
    configuration_reason: str | None = None


class TestRunFactError(ValueError):
    """Human-entered execution facts or configuration selection need correction."""


def _execution_fact(
    *,
    status: str,
    executed_at: datetime | None,
    precision: str,
    reason: str | None,
    now: datetime,
) -> tuple[datetime | None, str, str]:
    if executed_at is None:
        if precision != "unknown" or reason:
            raise TestRunFactError("请同时填写实际测试日期、精度和登记依据")
        return (
            (now, "instant", "system_completion")
            if status in TERMINAL_RUN_STATUSES
            else (None, "unknown", "unknown")
        )
    if (
        status not in TERMINAL_RUN_STATUSES
        or executed_at.tzinfo is None
        or executed_at > now
        or precision not in {"day", "instant"}
        or not reason
        or not 1 <= len(reason.strip()) <= 2000
        or (precision == "day" and executed_at.astimezone(UTC).time().isoformat() != "00:00:00")
    ):
        raise TestRunFactError("请填写已发生的真实测试日期或带时区的时间，并说明登记依据")
    return executed_at.astimezone(UTC), precision, "human"


def _validate_sample_execution_date(
    c: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    sample_id: UUID | None,
    executed_at: datetime | None,
    precision: str,
) -> None:
    if sample_id is None or executed_at is None:
        return
    sample = (
        c.execute(
            select(tables.samples).where(
                tables.samples.c.tenant_id == tenant_id,
                tables.samples.c.project_id == project_id,
                tables.samples.c.id == sample_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if sample is None:
        raise TestRunScopeError
    if sample["built_at_precision"] == "unknown":
        return
    built_at = sample["built_at"]
    if built_at is not None and (
        executed_at.date() < built_at.date()
        if precision == "day" or sample["built_at_precision"] == "day"
        else executed_at < built_at
    ):
        raise TestRunFactError("实际测试日期早于已确认装机日期，请核对实际样机及时间")


def _selected_configuration(
    c: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    actor_user_id: UUID,
    draft: TestRunDraft,
    occurred_at: datetime,
) -> UUID | None:
    if draft.configuration_mode not in {"current", "revision", "unknown"}:
        raise TestRunFactError("请选择当次配置版本或明确未知")
    if draft.configuration_mode == "current":
        if draft.executed_at is not None or draft.configuration_revision_id is not None:
            raise TestRunFactError("补录已发生测试时，请核对具体历史配置版本；无法还原时选择未知")
        return pin_current_configuration(
            c,
            tenant_id=tenant_id,
            project_id=project_id,
            sample_id=draft.sample_id,
            actor_user_id=actor_user_id,
            occurred_at=occurred_at,
        )
    if not draft.configuration_reason or not 1 <= len(draft.configuration_reason.strip()) <= 2000:
        raise TestRunFactError("请说明当次配置版本的选择依据或无法还原的原因")
    if draft.configuration_mode == "unknown":
        if draft.configuration_revision_id is not None:
            raise TestRunFactError("未知配置不能同时绑定版本")
        return None
    if draft.sample_id is None or draft.configuration_revision_id is None:
        raise TestRunFactError("请选择实际样机及其当次配置版本")
    r = tables.sample_configuration_revisions
    revision = (
        c.execute(
            select(r).where(
                r.c.tenant_id == tenant_id,
                r.c.project_id == project_id,
                r.c.sample_id == draft.sample_id,
                r.c.id == draft.configuration_revision_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if revision is None:
        raise TestRunScopeError
    if (
        revision["source"] == "report_extract"
        and revision["source_document_id"] != draft.evidence_document_id
    ):
        raise TestRunFactError("报告提取的配置版本需要绑定同一原报告证据")
    return draft.configuration_revision_id


def _record_from_row(row: RowMapping, *, related_issue_id: UUID | None = None) -> TestRunRecord:
    return TestRunRecord(
        id=row["id"],
        project_id=row["project_id"],
        test_case_id=row["test_case_id"],
        sample_id=row["sample_id"],
        operator_user_id=row["operator_user_id"],
        evidence_document_id=row["evidence_document_id"],
        run_number=row["run_number"],
        status=row["status"],
        draft_state=row["draft_state"],
        conditions=dict(row["conditions"]),
        metrics=tuple(dict(item) for item in row["metrics"]),
        equipment=row["equipment"],
        environment=row["environment"],
        result_notes=row["result_notes"],
        started_at=row["started_at"],
        expected_completion_at=row["expected_completion_at"],
        executed_at=row["executed_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        related_issue_id=related_issue_id
        if related_issue_id is not None
        else row.get("case_related_issue_id"),
        operator_name=row.get("operator_name"),
        source_field_capture_id=row.get("source_field_capture_id"),
        test_preparation_id=row.get("test_preparation_id"),
        test_preparation={
            "id": str(row["test_preparation_id"]),
            "revision_number": row["preparation_revision"],
            "snapshot": row["preparation_snapshot"],
        }
        if row.get("preparation_snapshot")
        else None,
        sample_configuration_revision_id=row["sample_configuration_revision_id"],
        execution_time_precision=row["execution_time_precision"],
        execution_time_source=row["execution_time_source"],
        import_successor_batch_id=row.get("import_successor_batch_id"),
        import_batch_id=row.get("import_batch_id"),
        configuration_revision={
            "id": str(row["configuration_id"]),
            "revision_number": row["revision_number"],
            "source": row["configuration_source"],
            "snapshot": row["snapshot"],
            "source_document_id": str(row["configuration_document_id"])
            if row["configuration_document_id"]
            else None,
            "content_digest": row["content_digest"],
        }
        if row.get("configuration_id")
        else None,
    )


def _run_snapshot(record: TestRunRecord) -> dict[str, object]:
    return {
        "project_id": str(record.project_id),
        "test_case_id": str(record.test_case_id),
        "sample_id": str(record.sample_id) if record.sample_id else None,
        "sample_configuration_revision_id": str(record.sample_configuration_revision_id)
        if record.sample_configuration_revision_id
        else None,
        "execution_time_precision": record.execution_time_precision,
        "test_preparation_id": str(record.test_preparation_id)
        if record.test_preparation_id
        else None,
        "execution_time_source": record.execution_time_source,
        "conditions": record.conditions,
        "evidence_document_id": str(record.evidence_document_id)
        if record.evidence_document_id
        else None,
        "operator_user_id": str(record.operator_user_id) if record.operator_user_id else None,
        "result_notes": record.result_notes,
        "run_number": record.run_number,
        "status": record.status,
        "metrics": [dict(item) for item in record.metrics],
        "equipment": record.equipment,
        "environment": record.environment,
        "expected_completion_at": (
            record.expected_completion_at.isoformat() if record.expected_completion_at else None
        ),
        "started_at": record.started_at.isoformat() if record.started_at else None,
        "executed_at": record.executed_at.isoformat() if record.executed_at else None,
    }


class TestRunService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _case_row(
        connection: Connection, *, tenant_id: UUID, project_id: UUID, test_case_id: UUID
    ) -> RowMapping:
        row = (
            connection.execute(
                select(tables.test_cases)
                .where(
                    tables.test_cases.c.tenant_id == tenant_id,
                    tables.test_cases.c.project_id == project_id,
                    tables.test_cases.c.id == test_case_id,
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise TestRunNotFoundError
        return row

    @staticmethod
    def _validate_scoped(
        connection: Connection,
        table: Table,
        *,
        tenant_id: UUID,
        project_id: UUID,
        row_id: UUID | None,
    ) -> None:
        if row_id is None:
            return
        found = connection.execute(
            select(table.c.id).where(
                table.c.tenant_id == tenant_id,
                table.c.project_id == project_id,
                table.c.id == row_id,
            )
        ).scalar_one_or_none()
        if found is None:
            raise TestRunScopeError

    def list_runs(
        self, *, tenant_id: UUID, project_id: UUID, test_case_id: UUID
    ) -> list[TestRunRecord]:
        with self._engine.connect() as connection:
            return [
                _record_from_row(row)
                for row in connection.execute(
                    run_selection()
                    .where(
                        tables.test_runs.c.tenant_id == tenant_id,
                        tables.test_runs.c.project_id == project_id,
                        tables.test_runs.c.test_case_id == test_case_id,
                    )
                    .order_by(tables.test_runs.c.run_number.desc())
                ).mappings()
            ]

    def record_run(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        test_case_id: UUID,
        draft: TestRunDraft,
        connection: Connection | None = None,
    ) -> TestRunRecord:
        if draft.status not in {"in_progress", "passed", "failed", "aborted"}:
            raise TestRunStateError
        run_id = uuid4()
        occurred_at = datetime.now(UTC)
        execution_at, precision, time_source = _execution_fact(
            status=draft.status,
            executed_at=draft.executed_at,
            precision=draft.execution_time_precision,
            reason=draft.execution_time_reason,
            now=occurred_at,
        )
        with (
            nullcontext(connection) if connection is not None else self._engine.begin()
        ) as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise TestRunNotFoundError
            case = self._case_row(
                connection, tenant_id=tenant_id, project_id=project_id, test_case_id=test_case_id
            )
            self._validate_scoped(
                connection,
                tables.samples,
                tenant_id=tenant_id,
                project_id=project_id,
                row_id=draft.sample_id,
            )
            self._validate_scoped(
                connection,
                tables.documents,
                tenant_id=tenant_id,
                project_id=project_id,
                row_id=draft.evidence_document_id,
            )
            next_number = connection.execute(
                select(func.coalesce(func.max(tables.test_runs.c.run_number), 0) + 1).where(
                    tables.test_runs.c.tenant_id == tenant_id,
                    tables.test_runs.c.test_case_id == test_case_id,
                )
            ).scalar_one()
            revision_id = _selected_configuration(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                draft=draft,
                occurred_at=occurred_at,
            )
            if time_source == "human":
                _validate_sample_execution_date(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    sample_id=draft.sample_id,
                    executed_at=execution_at,
                    precision=precision,
                )
            conditions = dict(draft.conditions)
            conditions.pop("execution_time_input", None)
            conditions["manual_configuration_selection"] = {
                "mode": draft.configuration_mode,
                "reason": draft.configuration_reason,
                "revision_id": str(revision_id) if revision_id else None,
                "recorded_by_user_id": str(actor_user_id),
                "recorded_at": occurred_at.isoformat(),
            }
            if time_source == "human":
                conditions["execution_time_input"] = {
                    "reason": draft.execution_time_reason,
                    "precision": precision,
                    "recorded_by_user_id": str(actor_user_id),
                    "recorded_at": occurred_at.isoformat(),
                }
            from app.domain.test_execution_preparations import latest

            preparation = (
                latest(connection, tenant_id, project_id, test_case_id)
                if draft.executed_at is None
                else None
            )
            if preparation and any(
                preparation["snapshot"]["case"].get(key)
                != (str(case[key]) if isinstance(case[key], UUID) else case[key])
                for key in ("specification_id", "method", "acceptance_criteria")
            ):
                raise TestRunFactError(
                    "测试方法、判据或规格关联已变化，请先重新核对并保存执行工作包"
                )
            terminal = draft.status in TERMINAL_RUN_STATUSES
            row = (
                connection.execute(
                    tables.test_runs.insert()
                    .values(
                        id=run_id,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        test_case_id=test_case_id,
                        sample_id=draft.sample_id,
                        sample_configuration_revision_id=revision_id,
                        test_preparation_id=preparation["id"] if preparation else None,
                        execution_time_precision=precision,
                        execution_time_source=time_source,
                        operator_user_id=actor_user_id,
                        evidence_document_id=draft.evidence_document_id,
                        run_number=next_number,
                        status=draft.status,
                        conditions=conditions,
                        metrics=[dict(item) for item in draft.metrics],
                        equipment=draft.equipment,
                        environment=draft.environment,
                        result_notes=draft.result_notes,
                        started_at=None if time_source == "human" else occurred_at,
                        expected_completion_at=draft.expected_completion_at,
                        executed_at=execution_at,
                        created_at=occurred_at,
                        updated_at=occurred_at,
                    )
                    .returning(tables.test_runs)
                )
                .mappings()
                .one()
            )
            related_issue_id = case["related_issue_id"]
            if terminal:
                related_issue_id = self._sync_case_and_side_effects(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    actor_user_id=actor_user_id,
                    case=case,
                    run_status=draft.status,
                    executed_at=execution_at,
                    occurred_at=occurred_at,
                )
            record = _record_from_row(row, related_issue_id=related_issue_id)
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"npi:test_run:{run_id}:recorded:{uuid4()}",
                    event_type="NPI_RECORD_CHANGED",
                    source="npi_service",
                    entity_id=run_id,
                    payload={"record_type": "test_run", "action": f"recorded_{draft.status}"},
                    occurred_at=occurred_at,
                ),
                AuditDraft(action="test_run.record", after_snapshot=_run_snapshot(record)),
            )
            return record

    def complete_run(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        test_case_id: UUID,
        run_id: UUID,
        status: str,
        metrics: tuple[dict[str, object], ...] = (),
        result_notes: str | None = None,
        evidence_document_id: UUID | None = None,
        executed_at: datetime | None = None,
        execution_time_precision: str = "unknown",
        execution_time_reason: str | None = None,
    ) -> TestRunRecord:
        if status not in TERMINAL_RUN_STATUSES:
            raise TestRunStateError
        occurred_at = datetime.now(UTC)
        execution_at, precision, time_source = _execution_fact(
            status=status,
            executed_at=executed_at,
            precision=execution_time_precision,
            reason=execution_time_reason,
            now=occurred_at,
        )
        with self._engine.begin() as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise TestRunNotFoundError
            case = self._case_row(
                connection, tenant_id=tenant_id, project_id=project_id, test_case_id=test_case_id
            )
            before = (
                connection.execute(
                    select(tables.test_runs)
                    .where(
                        tables.test_runs.c.tenant_id == tenant_id,
                        tables.test_runs.c.project_id == project_id,
                        tables.test_runs.c.test_case_id == test_case_id,
                        tables.test_runs.c.id == run_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if before is None:
                raise TestRunNotFoundError
            if before["status"] != "in_progress" or before["draft_state"] != "confirmed":
                raise TestRunStateError
            self._validate_scoped(
                connection,
                tables.documents,
                tenant_id=tenant_id,
                project_id=project_id,
                row_id=evidence_document_id,
            )
            if before["sample_configuration_revision_id"] is not None:
                revision = (
                    connection.execute(
                        select(tables.sample_configuration_revisions).where(
                            tables.sample_configuration_revisions.c.tenant_id == tenant_id,
                            tables.sample_configuration_revisions.c.project_id == project_id,
                            tables.sample_configuration_revisions.c.sample_id
                            == before["sample_id"],
                            tables.sample_configuration_revisions.c.id
                            == before["sample_configuration_revision_id"],
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if revision is None:
                    raise TestRunScopeError
                if revision["source"] == "report_extract" and revision["source_document_id"] != (
                    evidence_document_id
                    if evidence_document_id is not None
                    else before["evidence_document_id"]
                ):
                    raise TestRunFactError("本次固定配置来自报告，请保留同一原报告证据")
            if time_source == "human":
                _validate_sample_execution_date(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    sample_id=before["sample_id"],
                    executed_at=execution_at,
                    precision=precision,
                )
                if (
                    execution_at is not None
                    and before["started_at"] is not None
                    and (
                        execution_at.date() < before["started_at"].date()
                        if precision == "day"
                        else execution_at < before["started_at"]
                    )
                ):
                    raise TestRunFactError("测试完成日期早于本次测试开始登记，请核对实际完成时间")
            values: dict[str, Any] = {
                "status": status,
                "executed_at": execution_at,
                "execution_time_precision": precision,
                "execution_time_source": time_source,
                "updated_at": occurred_at,
            }
            if time_source == "human":
                values["conditions"] = {
                    **before["conditions"],
                    "execution_time_input": {
                        "reason": execution_time_reason,
                        "precision": precision,
                        "recorded_by_user_id": str(actor_user_id),
                        "recorded_at": occurred_at.isoformat(),
                    },
                }
            if metrics:
                values["metrics"] = [dict(item) for item in metrics]
            if result_notes is not None:
                values["result_notes"] = result_notes
            if evidence_document_id is not None:
                values["evidence_document_id"] = evidence_document_id
            from app.domain.schedule_execution import guard_source_action

            guard_source_action(
                connection,
                tenant_id,
                project_id,
                run_id,
                "test_run",
                "test_run.complete",
                {
                    "status": status,
                    "started_at": before["started_at"].isoformat()
                    if before["started_at"]
                    else None,
                    "executed_at": execution_at.isoformat() if execution_at else None,
                },
                occurred_at,
            )
            row = (
                connection.execute(
                    tables.test_runs.update()
                    .where(
                        tables.test_runs.c.tenant_id == tenant_id,
                        tables.test_runs.c.id == run_id,
                    )
                    .values(**values)
                    .returning(tables.test_runs)
                )
                .mappings()
                .one()
            )
            related_issue_id = self._sync_case_and_side_effects(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                case=case,
                run_status=status,
                executed_at=execution_at,
                occurred_at=occurred_at,
            )
            record = _record_from_row(row, related_issue_id=related_issue_id)
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"npi:test_run:{run_id}:completed:{uuid4()}",
                    event_type="NPI_RECORD_CHANGED",
                    source="npi_service",
                    entity_id=run_id,
                    payload={"record_type": "test_run", "action": f"completed_{status}"},
                    occurred_at=occurred_at,
                ),
                AuditDraft(action="test_run.complete", after_snapshot=_run_snapshot(record)),
            )
            return record

    def _sync_case_and_side_effects(
        self,
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        case: RowMapping,
        run_status: str,
        occurred_at: datetime,
        executed_at: datetime | None = None,
    ) -> UUID | None:
        return sync_case_with_run_result(
            connection,
            tenant_id=tenant_id,
            project_id=project_id,
            actor_user_id=actor_user_id,
            case=case,
            run_status=run_status,
            occurred_at=occurred_at,
            executed_at=executed_at,
        )


def sync_case_with_run_result(
    connection: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    actor_user_id: UUID,
    case: RowMapping,
    run_status: str,
    occurred_at: datetime,
    executed_at: datetime | None = None,
) -> UUID | None:
    related_issue_id: UUID | None = case["related_issue_id"]
    case_status = {"passed": "passed", "failed": "failed", "aborted": "blocked"}[run_status]
    if run_status == "failed" and related_issue_id is None:
        related_issue_id = uuid4()
        severity = _ISSUE_SEVERITY_BY_CASE.get(case["severity"], "high")
        connection.execute(
            tables.issues.insert(),
            {
                "id": related_issue_id,
                "tenant_id": tenant_id,
                "project_id": project_id,
                "reported_by_user_id": actor_user_id,
                "title": f"测试失败:{case['title']}"[:512],
                "issue_type": "test_failure",
                "status": "open",
                "severity": severity,
                "created_at": occurred_at,
                "updated_at": occurred_at,
            },
        )
        EventAuditWriter(
            connection,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            project_id=project_id,
        ).record(
            EventDraft(
                event_id=f"issue:{related_issue_id}:created",
                event_type="ISSUE_CREATED",
                source="issue_service",
                entity_id=related_issue_id,
                payload={"issue_id": str(related_issue_id), "severity": severity},
                occurred_at=occurred_at,
            ),
            AuditDraft(
                action="issue.create",
                after_snapshot={
                    "project_id": str(project_id),
                    "title": f"测试失败:{case['title']}"[:512],
                    "issue_type": "test_failure",
                    "status": "open",
                    "severity": severity,
                    "source": "test_run_failure",
                },
            ),
        )
    connection.execute(
        tables.test_cases.update()
        .where(
            tables.test_cases.c.tenant_id == tenant_id,
            tables.test_cases.c.id == case["id"],
        )
        .values(
            status=case_status,
            related_issue_id=related_issue_id,
            executed_by_user_id=actor_user_id,
            executed_at=executed_at or occurred_at,
            updated_at=occurred_at,
        )
    )
    if run_status == "failed":
        EventAuditWriter(
            connection,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            project_id=project_id,
        ).record(
            EventDraft(
                event_id=f"test:{case['id']}:failed:{uuid4()}",
                event_type="TEST_FAILED",
                source="quality_service",
                entity_id=case["id"],
                payload={
                    "test_record_id": str(case["id"]),
                    "severity": case["severity"],
                },
                occurred_at=occurred_at,
            ),
            AuditDraft(
                action="npi.test_case.failed",
                before_snapshot={"status": case["status"]},
                after_snapshot={
                    "status": case_status,
                    "related_issue_id": (str(related_issue_id) if related_issue_id else None),
                },
            ),
        )
    return related_issue_id
