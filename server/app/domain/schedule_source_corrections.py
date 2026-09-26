"""Append corrections to business Actual while retaining immutable source observations."""

from datetime import UTC, datetime
from typing import Any, Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, model_validator
from sqlalchemy import Connection, Engine, func, select
from sqlalchemy.exc import IntegrityError

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError, _plain, digest
from app.domain.project_execution import _person
from app.domain.resource_reservations import _project
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

WRITE_ACTIONS = {
    "build": Action.PRODUCT_ENGINEERING_EDIT,
    "gate": Action.GATE_MANAGE,
    "test_run": Action.TEST_RUN_RECORD,
    "certification": Action.QUALITY_MANAGE,
    "tooling": Action.PRODUCT_ENGINEERING_EDIT,
    "milestone": Action.WORK_ITEM_EDIT,
}


def may_correct(
    context: AuthContext, kind: str, node_id: UUID, formal: dict[str, Any] | None
) -> bool:
    if not is_allowed(context.user.role, WRITE_ACTIONS[kind]):
        return False
    if kind != "milestone" or is_allowed(context.user.role, Action.PROJECT_EDIT):
        return True
    if formal is None:
        return False
    binding = next((node for node in formal["nodes"] if node["id"] == node_id), None)
    if binding is None:
        return False
    plan_node = next(
        node for node in formal["plan"]["nodes"] if node["node_key"] == binding["node_key"]
    )
    return str(context.user.id) in (
        plan_node.get("owner_user_id"),
        plan_node.get("receiver_user_id"),
    )


class SourceActualCorrection(Contract):
    request_id: UUID
    observation_id: UUID
    expected_digest: Digest
    started_at: AwareDatetime | None
    finished_at: AwareDatetime | None
    reason: Text
    evidence: Text

    @model_validator(mode="after")
    def time_order(self) -> Self:
        if self.started_at and self.finished_at and self.finished_at < self.started_at:
            raise ValueError("实际结束不能早于开始")
        return self


def corrected_observations(
    connection: Connection, tenant_id: UUID, project_id: UUID, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    table = tables.schedule_source_corrections
    ranked = (
        select(
            table,
            func.row_number()
            .over(partition_by=table.c.node_id, order_by=table.c.version.desc())
            .label("position"),
        )
        .where(
            table.c.tenant_id == tenant_id,
            table.c.project_id == project_id,
        )
        .subquery()
    )
    latest = {
        row["node_id"]: row
        for row in connection.execute(select(ranked).where(ranked.c.position == 1)).mappings()
    }
    result = []
    for raw in rows:
        correction = latest.get(raw["node_id"])
        effective = dict(raw)
        if correction is not None:
            original = correction["original_snapshot"]
            original_start = (
                datetime.fromisoformat(original["started_at"])
                if original.get("started_at")
                else None
            )
            same_round = raw["node_kind"] != "gate" or raw["started_at"] == original_start
            changed_fields = []
            for field in ("started_at", "finished_at"):
                prior = datetime.fromisoformat(original[field]) if original.get(field) else None
                if same_round and raw[field] == prior:
                    effective[field] = correction[field]
                    changed_fields.append(field)
            if changed_fields:
                # A new real source point can supersede one half of the old
                # correction. Never combine the remaining half into reversed time.
                if (
                    effective["started_at"]
                    and effective["finished_at"]
                    and effective["finished_at"] < effective["started_at"]
                ):
                    effective = {
                        **raw,
                        "started_at": None,
                        "finished_at": None,
                        "raw_observation": dict(raw),
                        "actual_correction": {
                            "id": str(correction["id"]),
                            "version": correction["version"],
                            "fields": changed_fields,
                            "event_row_id": correction["event_row_id"],
                        },
                        "correction_conflict": "后续实际记录与旧更正时间冲突，请核对本轮实际依据",
                    }
                else:
                    effective["raw_observation"] = dict(raw)
                    effective["actual_correction"] = {
                        "id": str(correction["id"]),
                        "version": correction["version"],
                        "fields": changed_fields,
                        "event_row_id": correction["event_row_id"],
                    }
        result.append(effective)
    return result


class SourceActualCorrectionService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(self, context: AuthContext, project_id: UUID) -> dict[str, Any]:
        from app.domain.formal_schedule import current_plan
        from app.domain.schedule_nodes import list_nodes

        with self.engine.connect() as connection:
            project = _project(connection, context, project_id)
            formal = current_plan(connection, context.tenant.id, project_id)
            nodes = [
                node
                for node in list_nodes(connection, context, project_id)
                if node["node_kind"] in WRITE_ACTIONS and node["actual"]
            ]
            table = tables.schedule_source_corrections
            rows = list(
                connection.execute(
                    select(table)
                    .where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.project_id == project_id,
                        table.c.node_id.in_([UUID(node["id"]) for node in nodes]),
                    )
                    .order_by(table.c.created_at.desc(), table.c.id)
                    .limit(501)
                ).mappings()
            )
            names = dict(
                connection.execute(
                    select(tables.users.c.id, tables.users.c.display_name).where(
                        tables.users.c.tenant_id == context.tenant.id,
                        tables.users.c.id.in_({row["actor_user_id"] for row in rows[:500]}),
                    )
                )
                .tuples()
                .all()
            )
            return {
                "items": [
                    {
                        "node_id": node["id"],
                        "node_kind": node["node_kind"],
                        "title": node["title"],
                        "actual": node["actual"],
                        "expected_digest": digest(node["actual"]),
                        "can_correct": may_correct(
                            context, node["node_kind"], UUID(node["id"]), formal
                        )
                        and project["status"] in ("active", "on_hold", "completed"),
                    }
                    for node in nodes
                ],
                "history": [
                    {**_plain(row), "actor_name": names.get(row["actor_user_id"], "历史办理人")}
                    for row in rows[:500]
                ],
                "has_more": len(rows) > 500,
            }

    def correct(
        self, context: AuthContext, project_id: UUID, node_id: UUID, command: SourceActualCorrection
    ) -> dict[str, Any]:
        try:
            return self._correct(context, project_id, node_id, command)
        except IntegrityError as error:
            raise ProductWorkError("实际时间更正未生效，请刷新当前观察及更正记录") from error

    def _correct(
        self, context: AuthContext, project_id: UUID, node_id: UUID, command: SourceActualCorrection
    ) -> dict[str, Any]:
        from app.domain.formal_schedule import current_plan
        from app.domain.schedule_execution import persist_actual_snapshot
        from app.domain.schedule_forecasts import automatic_forecast
        from app.domain.schedule_source_actuals import latest_observations

        tenant_id = context.tenant.id
        with self.engine.begin() as connection:
            project = _project(connection, context, project_id, write=True)
            _person(connection, context, project_id, context.user.id)
            table = tables.schedule_source_corrections
            fingerprint = digest(
                {
                    "project_id": str(project_id),
                    "node_id": str(node_id),
                    **command.model_dump(mode="json"),
                }
            )
            prior = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == tenant_id,
                        table.c.actor_user_id == context.user.id,
                        table.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior is not None:
                if prior["request_digest"] != fingerprint:
                    raise ProductWorkError("请求编号已用于另一项实际时间更正")
                return _plain(prior)
            if project["status"] not in ("active", "on_hold", "completed"):
                raise ProductWorkError("当前项目状态不允许实际时间更正")
            observation = next(
                (
                    row
                    for row in latest_observations(connection, tenant_id, project_id)
                    if row["node_id"] == node_id
                ),
                None,
            )
            if observation is None or observation["id"] != command.observation_id:
                raise ProductWorkError("业务观察已变化，请重新核对当前实际依据")
            kind = observation["node_kind"]
            formal = current_plan(connection, tenant_id, project_id)
            if not may_correct(context, kind, node_id, formal):
                raise ProductWorkAccessError("当前角色没有此业务对象的实际时间更正权限")
            if digest(_plain(observation)) != command.expected_digest:
                raise ProductWorkError("实际时间或更正版本已变化，请刷新")
            now = datetime.now(UTC)
            if any(value and value > now for value in (command.started_at, command.finished_at)):
                raise ProductWorkError("实际时间不能填写未来时间")
            if (command.started_at, command.finished_at) == (
                observation["started_at"],
                observation["finished_at"],
            ):
                raise ProductWorkError("填写时间与当前实际时间相同")
            if kind == "milestone" and (
                command.started_at is None or command.started_at != command.finished_at
            ):
                raise ProductWorkError("里程碑为同一时刻的完成检查点，请填写相同的开始和结束时间")
            status = observation["source_status"]
            if (
                command.started_at
                and not observation["started_at"]
                and status
                not in (
                    "in_progress",
                    "completed",
                    "passed",
                    "failed",
                    "aborted",
                    "approved",
                    "conditional",
                    "hold",
                    "rejected",
                    "valid",
                    "expired",
                    "revoked",
                )
            ):
                raise ProductWorkError("原业务尚无已开始依据，请在业务入口办理开工")
            if (
                command.finished_at
                and not observation["finished_at"]
                and status
                not in (
                    "completed",
                    "passed",
                    "failed",
                    "aborted",
                    "approved",
                    "conditional",
                    "hold",
                    "rejected",
                    "valid",
                    "expired",
                    "revoked",
                )
            ):
                raise ProductWorkError("原业务尚无结束结论，时间更正不能代替完成办理")
            version = (
                connection.execute(
                    select(func.max(table.c.version)).where(
                        table.c.tenant_id == tenant_id, table.c.node_id == node_id
                    )
                ).scalar_one()
                or 0
            ) + 1
            correction_id = uuid4()
            original = observation.get("raw_observation", observation)
            snapshot = {
                "id": str(correction_id),
                "node_id": str(node_id),
                "observation_id": str(observation["id"]),
                "version": version,
                "started_at": command.started_at.isoformat() if command.started_at else None,
                "finished_at": command.finished_at.isoformat() if command.finished_at else None,
                "reason": command.reason,
                "evidence": command.evidence,
            }
            written = EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=context.user.id,
            ).record(
                EventDraft(
                    event_id=f"source-actual:{node_id}:correction:{correction_id}",
                    event_type="SCHEDULE_SOURCE_ACTUAL_CORRECTED",
                    source="planning_service",
                    entity_id=node_id,
                    payload={"node_id": str(node_id), "correction_id": str(correction_id)},
                    occurred_at=now,
                ),
                AuditDraft(
                    action="schedule_source_actual.correct",
                    before_snapshot=_plain(observation),
                    after_snapshot=snapshot,
                ),
            )
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        id=correction_id,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        node_id=node_id,
                        observation_id=observation["id"],
                        version=version,
                        original_snapshot=_plain(original),
                        previous_snapshot=_plain(observation),
                        started_at=command.started_at,
                        finished_at=command.finished_at,
                        reason=command.reason,
                        evidence=command.evidence,
                        actor_user_id=context.user.id,
                        event_row_id=written.event_row_id,
                        audit_row_id=written.audit_row_id,
                        request_id=command.request_id,
                        request_digest=fingerprint,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            persist_actual_snapshot(connection, tenant_id, project_id, context.user.id, now)
            formal = current_plan(connection, tenant_id, project_id)
            if formal and any(node["id"] == node_id for node in formal["nodes"]):
                automatic_forecast(
                    connection,
                    tenant_id,
                    project_id,
                    context.user.id,
                    "业务实际时间更正后的预测更新",
                    now,
                )
            return _plain(row)
