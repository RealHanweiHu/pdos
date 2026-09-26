"""Explicit reconciliation of legacy project allocations, without rewriting history."""

from contextlib import nullcontext
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import Connection, Engine, func, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import Contract, Digest, Quantity, Text
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError, _plain, _role, digest
from app.domain.resource_capacity import _intervals
from app.domain.resource_reservations import _project
from app.domain.working_time import CalendarDefinition, WorkingTime
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class ReconciliationDraft(Contract):
    request_id: UUID
    legacy_resource_id: UUID
    expected_sequence: int = Field(ge=0)
    source_digest: Digest
    disposition: Literal["mapped", "retained_released"]
    resource_id: UUID | None = None
    calendar_version_id: UUID | None = None
    window_start: AwareDatetime | None = None
    window_end: AwareDatetime | None = None
    parallel_units: Quantity | None = Field(default=None, gt=0, le=1000)
    occupancy_policy: Literal["working_only", "through_waiting"] | None = None
    basis: Text

    @model_validator(mode="after")
    def complete_mapping(self) -> Self:
        values = (
            self.resource_id,
            self.calendar_version_id,
            self.window_start,
            self.window_end,
            self.parallel_units,
            self.occupancy_policy,
        )
        if self.disposition == "retained_released":
            if any(value is not None for value in values):
                raise ValueError("已释放历史不附加新占用")
        else:
            if any(value is None for value in values):
                raise ValueError("归并须明确资源、日历、完整窗口、单位和占用方式")
            assert self.window_start is not None and self.window_end is not None
            start, end = self.window_start.astimezone(UTC), self.window_end.astimezone(UTC)
            if not timedelta(0) < end - start <= timedelta(days=3660) or any(
                value.second or value.microsecond for value in (start, end)
            ):
                raise ValueError("占用窗口按整分钟填写且不超过十年")
        return self


def lock_inventory(connection: Connection, tenant_id: UUID) -> None:
    connection.execute(select(func.cehub_project.lock_resource_inventory(tenant_id)))


def _source(
    connection: Connection, context: AuthContext, project_id: UUID, resource_id: UUID
) -> tuple[dict[str, Any], str]:
    table = tables.resources
    row = (
        connection.execute(
            select(
                table,
                func.cehub_project.legacy_resource_stamp(context.tenant.id, table.c.id).label(
                    "source_stamp"
                ),
            ).where(
                table.c.tenant_id == context.tenant.id,
                table.c.project_id == project_id,
                table.c.id == resource_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkError("旧资源不存在或不属于当前项目")
    data = dict(row)
    stamp = data.pop("source_stamp")
    return data, stamp


class ResourceInventoryService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def list(self, context: AuthContext, project_id: UUID) -> dict[str, Any]:
        with self.engine.connect() as connection:
            _project(connection, context, project_id)
            table = tables.resources
            rows = list(
                connection.execute(
                    select(
                        table,
                        func.cehub_project.legacy_resource_stamp(
                            context.tenant.id, table.c.id
                        ).label("source_stamp"),
                    )
                    .where(table.c.tenant_id == context.tenant.id, table.c.project_id == project_id)
                    .order_by(table.c.code)
                    .limit(1001)
                ).mappings()
            )
            history = tables.legacy_resource_reconciliations
            records = list(
                connection.execute(
                    select(history)
                    .where(
                        history.c.tenant_id == context.tenant.id, history.c.project_id == project_id
                    )
                    .order_by(history.c.legacy_resource_id, history.c.sequence.desc())
                ).mappings()
            )
            latest: dict[UUID, Any] = {}
            for row in records:
                latest.setdefault(row["legacy_resource_id"], row)
            resources = {
                row["id"]: row["name"]
                for row in connection.execute(
                    select(tables.planning_resources.c.id, tables.planning_resources.c.name).where(
                        tables.planning_resources.c.tenant_id == context.tenant.id,
                        tables.planning_resources.c.id.in_(
                            {row["resource_id"] for row in records if row["resource_id"]}
                        ),
                    )
                ).mappings()
            }
            items = []
            for row in rows[:1000]:
                source = dict(row)
                stamp = source.pop("source_stamp")
                reconciliation = latest.get(row["id"])
                items.append(
                    {
                        "source": _plain(source),
                        "source_digest": stamp,
                        "sequence": reconciliation["sequence"] if reconciliation else 0,
                        "current": reconciliation is not None
                        and reconciliation["source_digest"] == stamp,
                        "reconciliation": {
                            **_plain(reconciliation),
                            "resource_name": resources.get(reconciliation["resource_id"]),
                        }
                        if reconciliation
                        else None,
                    }
                )
            return {
                "items": items,
                "has_more": len(rows) > 1000,
                "can_manage": is_allowed(context.user.role, Action.TENANT_MANAGE),
                "history": [
                    {**_plain(row), "resource_name": resources.get(row["resource_id"])}
                    for row in records
                ],
            }

    def reconcile(
        self,
        context: AuthContext,
        project_id: UUID,
        draft: ReconciliationDraft,
        *,
        connection: Connection | None = None,
        audit_draft: AuditDraft | None = None,
    ) -> dict[str, Any]:
        _role(context, Action.TENANT_MANAGE)
        with (
            nullcontext(connection) if connection is not None else self.engine.begin() as connection
        ):
            _project(connection, context, project_id, write=True)
            lock_inventory(connection, context.tenant.id)
            table = tables.legacy_resource_reconciliations
            fingerprint = digest(draft.model_dump(mode="json"))
            prior = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.project_id == project_id,
                        table.c.actor_user_id == context.user.id,
                        table.c.request_id == draft.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != fingerprint:
                    raise ProductWorkError("请求编号已用于其他资源归并")
                return _plain(prior)
            source, stamp = _source(connection, context, project_id, draft.legacy_resource_id)
            latest = (
                connection.execute(
                    select(table)
                    .where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.legacy_resource_id == draft.legacy_resource_id,
                    )
                    .order_by(table.c.sequence.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if (
                stamp != draft.source_digest
                or (latest["sequence"] if latest else 0) != draft.expected_sequence
            ):
                raise ProductWorkError("旧记录或盘点版本已变化，请刷新后核对")
            locked_ids = {
                value
                for value in (draft.resource_id, latest["resource_id"] if latest else None)
                if value
            }
            list(
                connection.execute(
                    select(tables.planning_resources.c.id)
                    .where(
                        tables.planning_resources.c.tenant_id == context.tenant.id,
                        tables.planning_resources.c.id.in_(locked_ids),
                    )
                    .order_by(tables.planning_resources.c.id)
                    .with_for_update()
                ).scalars()
            )
            evidence = None
            spans: list[tuple[datetime, datetime]] = []
            if draft.disposition == "retained_released":
                if source["status"] != "released":
                    raise ProductWorkError("只有原记录实际已释放时才能按释放历史保留")
            else:
                if source["status"] == "released":
                    raise ProductWorkError("已释放旧记录不能产生新占用")
                resource = (
                    connection.execute(
                        select(tables.planning_resources).where(
                            tables.planning_resources.c.tenant_id == context.tenant.id,
                            tables.planning_resources.c.id == draft.resource_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if resource is None:
                    raise ProductWorkError("请选择实际共享资源")
                compatible = {
                    "person": {"person"},
                    "equipment": {"equipment", "bench", "mold", "fixture"},
                    "facility": {"laboratory", "bench", "pilot_line"},
                    "capability": {"skill_group"},
                }
                if resource["kind"] not in compatible[source["resource_type"]]:
                    raise ProductWorkError("旧资源类型与共享资源类型不匹配")
                if (
                    source["assigned_user_id"]
                    and resource["kind"] == "person"
                    and source["assigned_user_id"] != resource["user_id"]
                ):
                    raise ProductWorkError("旧记录人员与共享资源的实际人员不同")
                if resource["kind"] == "person" and draft.parallel_units != source[
                    "allocation_percent"
                ] / Decimal(100):
                    raise ProductWorkError(
                        "人员占用单位须与旧记录的分配比例一致；原记录更正后再重新归并"
                    )
                calendar = (
                    connection.execute(
                        select(tables.work_calendar_versions).where(
                            tables.work_calendar_versions.c.tenant_id == context.tenant.id,
                            tables.work_calendar_versions.c.id == draft.calendar_version_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if calendar is None:
                    raise ProductWorkError("请选择实际日历版本")
                engine = WorkingTime(CalendarDefinition.model_validate(calendar["definition"]))
                assert draft.window_start is not None and draft.window_end is not None
                start, end = draft.window_start.astimezone(UTC), draft.window_end.astimezone(UTC)
                if (
                    source["start_date"]
                    and start.astimezone(engine.zone).date() > source["start_date"]
                ):
                    raise ProductWorkError("占用窗口不能遗漏旧记录的开始日期")
                if source["end_date"] and end.astimezone(engine.zone).date() <= source["end_date"]:
                    raise ProductWorkError("占用窗口须覆盖旧结束日期整天（结束取次日零时或更晚）")
                spans = (
                    _intervals(engine, start, end)
                    if draft.occupancy_policy == "working_only"
                    else [(start, end)]
                )
                if not spans:
                    raise ProductWorkError("映射窗口没有实际占用时段，请核对日历或原记录状态")
                evidence = _plain(asdict(engine.evidence))
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        legacy_resource_id=source["id"],
                        sequence=draft.expected_sequence + 1,
                        source_digest=stamp,
                        source_snapshot=_plain(source),
                        resource_id=draft.resource_id,
                        calendar_version_id=draft.calendar_version_id,
                        window_start=draft.window_start,
                        window_end=draft.window_end,
                        parallel_units=draft.parallel_units,
                        occupancy_policy=draft.occupancy_policy,
                        disposition=draft.disposition,
                        basis=draft.basis,
                        calendar_evidence=evidence,
                        actor_user_id=context.user.id,
                        request_id=draft.request_id,
                        request_digest=fingerprint,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            for start, end in spans:
                connection.execute(
                    tables.legacy_resource_intervals.insert().values(
                        tenant_id=context.tenant.id,
                        reconciliation_id=row["id"],
                        start=start,
                        end=end,
                    )
                )
            EventAuditWriter(
                connection,
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"legacy-resource:{row['id']}",
                    event_type="LEGACY_RESOURCE_RECONCILED",
                    source="planning_service",
                    entity_id=source["id"],
                    payload={
                        "legacy_resource_id": str(source["id"]),
                        "sequence": row["sequence"],
                        "disposition": draft.disposition,
                    },
                ),
                replace(
                    audit_draft
                    or AuditDraft(
                        action="legacy_resource.reconciled", context={"reason": draft.basis}
                    ),
                    after_snapshot=_plain(row),
                ),
            )
            return _plain(row)
