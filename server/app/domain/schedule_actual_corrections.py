"""Human corrections append evidence; effective Actual is rebuilt without altering events."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime
from sqlalchemy import Connection, Engine, func, select
from sqlalchemy.exc import IntegrityError

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError, _plain, digest
from app.domain.resource_reservations import _project
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class ActualCorrection(Contract):
    request_id: UUID
    task_id: UUID
    point: Literal["start", "finish"]
    expected_digest: Digest
    observed_at: AwareDatetime
    reason: Text
    evidence: Text


def effective_observations(
    connection: Connection, tenant_id: UUID, project_id: UUID
) -> list[dict[str, Any]]:
    original = tables.scheduled_task_observations
    corrections = tables.schedule_actual_corrections
    rows = [
        dict(row)
        for row in connection.execute(
            select(original)
            .where(original.c.tenant_id == tenant_id, original.c.project_id == project_id)
            .order_by(original.c.node_id, original.c.point)
        ).mappings()
    ]
    latest = {}
    for row in connection.execute(
        select(corrections)
        .where(corrections.c.tenant_id == tenant_id, corrections.c.project_id == project_id)
        .order_by(corrections.c.version)
    ).mappings():
        latest[(row["node_id"], row["point"])] = row
    for record in rows:
        record.update(
            original_observed_at=record["observed_at"],
            original_event_row_id=record["event_row_id"],
            correction_id=None,
            correction_version=0,
        )
        change = latest.get((record["node_id"], record["point"]))
        if change:
            record.update(
                observed_at=change["observed_at"],
                event_row_id=change["event_row_id"],
                audit_row_id=change["audit_row_id"],
                correction_id=change["id"],
                correction_version=change["version"],
            )
        record["digest"] = digest(_plain(record))
    return rows


def can_correct(context: AuthContext, task: Any) -> bool:
    return is_allowed(context.user.role, Action.WORK_ITEM_EDIT) and (
        is_allowed(context.user.role, Action.PROJECT_EDIT)
        or task["assignee_user_id"] == context.user.id
    )


class ActualCorrectionService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(self, context: AuthContext, project_id: UUID) -> dict[str, Any]:
        with self.engine.connect() as connection:
            project = _project(connection, context, project_id)
            tasks = {
                row["id"]: row
                for row in connection.execute(
                    select(tables.tasks).where(
                        tables.tasks.c.tenant_id == context.tenant.id,
                        tables.tasks.c.project_id == project_id,
                    )
                ).mappings()
            }
            corrections = tables.schedule_actual_corrections
            history = list(
                connection.execute(
                    select(corrections, tables.users.c.display_name.label("actor_name"))
                    .join(
                        tables.users,
                        (tables.users.c.tenant_id == corrections.c.tenant_id)
                        & (tables.users.c.id == corrections.c.actor_user_id),
                    )
                    .where(
                        corrections.c.tenant_id == context.tenant.id,
                        corrections.c.project_id == project_id,
                    )
                    .order_by(corrections.c.created_at.desc(), corrections.c.id)
                    .limit(201)
                ).mappings()
            )
            return {
                "points": [
                    {
                        **_plain(row),
                        "title": tasks[row["task_id"]]["title"],
                        "can_correct": project["status"] in ("active", "on_hold", "completed")
                        and can_correct(context, tasks[row["task_id"]]),
                    }
                    for row in effective_observations(connection, context.tenant.id, project_id)
                ],
                "items": [_plain(row) for row in history[:200]],
                "has_more": len(history) > 200,
            }

    def correct(
        self, context: AuthContext, project_id: UUID, command: ActualCorrection
    ) -> dict[str, Any]:
        try:
            return self._correct(context, project_id, command)
        except IntegrityError as error:
            raise ProductWorkError("实际时间纠错未生效，请刷新记录后核对时间与依据") from error

    def _correct(
        self, context: AuthContext, project_id: UUID, command: ActualCorrection
    ) -> dict[str, Any]:
        with self.engine.begin() as connection:
            project = _project(connection, context, project_id, write=True)
            table = tables.schedule_actual_corrections
            fingerprint = digest({"project_id": str(project_id), **command.model_dump(mode="json")})
            prior = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.actor_user_id == context.user.id,
                        table.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != fingerprint:
                    raise ProductWorkError("请求编号已用于另一项实际时间纠错")
                return _plain(prior)
            if project["status"] not in ("active", "on_hold", "completed"):
                raise ProductWorkError("当前项目状态不允许更正实际时间")
            task = (
                connection.execute(
                    select(tables.tasks)
                    .where(
                        tables.tasks.c.tenant_id == context.tenant.id,
                        tables.tasks.c.project_id == project_id,
                        tables.tasks.c.id == command.task_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if task is None or not can_correct(context, task):
                raise ProductWorkAccessError("仅当前任务负责人或有项目编辑权限的成员可更正实际时间")
            points = {
                row["point"]: row
                for row in effective_observations(connection, context.tenant.id, project_id)
                if row["task_id"] == command.task_id
            }
            current = points.get(command.point)
            if current is None:
                raise ProductWorkError("没有原始办理记录，不能通过纠错补造开工或完成")
            if current["digest"] != command.expected_digest:
                raise ProductWorkError("实际时间已变化，请刷新后重新更正")
            now = connection.execute(select(func.clock_timestamp())).scalar_one()
            if command.observed_at > now or command.observed_at == current["observed_at"]:
                raise ProductWorkError("更正时间须与当前值不同，且不能晚于现在")
            start = (
                command.observed_at if command.point == "start" else points["start"]["observed_at"]
            )
            finish = (
                command.observed_at
                if command.point == "finish"
                else points.get("finish", {}).get("observed_at")
            )
            if finish and start > finish:
                raise ProductWorkError("实际完成不能早于实际开工，请先更正对应的另一时间点")
            correction_id = uuid4()
            after = {
                "task_id": str(command.task_id),
                "node_id": str(current["node_id"]),
                "point": command.point,
                "observed_at": command.observed_at.isoformat(),
                "correction_id": str(correction_id),
            }
            written = EventAuditWriter(
                connection,
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"actual-corrected:{correction_id}",
                    event_type="SCHEDULE_ACTUAL_CORRECTED",
                    source="planning_service",
                    entity_id=command.task_id,
                    payload={"correction_id": str(correction_id), "point": command.point},
                    occurred_at=now,
                ),
                AuditDraft(
                    action="schedule_actual.correct",
                    before_snapshot=_plain(current),
                    after_snapshot=after,
                    context={"reason": command.reason, "evidence": command.evidence},
                ),
            )
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        id=correction_id,
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        node_id=current["node_id"],
                        task_id=command.task_id,
                        point=command.point,
                        version=current["correction_version"] + 1,
                        previous_correction_id=current["correction_id"],
                        previous_observed_at=current["observed_at"],
                        observed_at=command.observed_at,
                        reason=command.reason,
                        evidence=command.evidence,
                        actor_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=fingerprint,
                        event_row_id=written.event_row_id,
                        audit_row_id=written.audit_row_id,
                        created_at=now,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            if command.point == "finish" and task["status"] == "done":
                connection.execute(
                    tables.tasks.update()
                    .where(
                        tables.tasks.c.tenant_id == context.tenant.id,
                        tables.tasks.c.id == command.task_id,
                    )
                    .values(completed_at=command.observed_at, updated_at=now)
                )
            from app.domain.schedule_execution import persist_actual_snapshot
            from app.domain.schedule_forecasts import automatic_forecast

            persist_actual_snapshot(connection, context.tenant.id, project_id, context.user.id, now)
            record_corrected_errors(connection, context.tenant.id, project_id, current, row)
            automatic_forecast(
                connection,
                context.tenant.id,
                project_id,
                context.user.id,
                "实际时间纠错后的预测更新",
                now,
            )
            return _plain(row)


def record_corrected_errors(
    connection: Connection,
    tenant_id: UUID,
    project_id: UUID,
    original: dict[str, Any],
    correction: Any,
) -> None:
    from decimal import Decimal

    times = tables.schedule_time_nodes
    records = tables.schedule_time_records
    column = times.c.start if original["point"] == "start" else times.c.end
    rows = connection.execute(
        select(times.c.record_id, column.label("predicted_at"), records.c.contract)
        .join(
            records,
            (records.c.tenant_id == times.c.tenant_id)
            & (records.c.project_id == times.c.project_id)
            & (records.c.id == times.c.record_id),
        )
        .where(
            times.c.tenant_id == tenant_id,
            times.c.project_id == project_id,
            times.c.node_id == original["node_id"],
            records.c.time_kind == "forecast",
            column.is_not(None),
        )
    ).mappings()
    for row in rows:
        as_of = datetime.fromisoformat(row["contract"]["as_of"])
        # Only predictions made before the original observation was recorded are eligible.
        if as_of >= original["original_observed_at"]:
            continue
        delta = correction["observed_at"] - row["predicted_at"]
        connection.execute(
            tables.schedule_forecast_error_corrections.insert().values(
                tenant_id=tenant_id,
                project_id=project_id,
                correction_id=correction["id"],
                forecast_record_id=row["record_id"],
                predicted_at=row["predicted_at"],
                error_seconds=Decimal(delta.days * 86400 + delta.seconds)
                + Decimal(delta.microseconds) / 1000000,
                eligible=as_of < correction["observed_at"],
            )
        )
