"""Deterministic reconciliation of projects affected by applied cross-project edges."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import Engine, exists, or_, select, tuple_

from app.db.schema import tables
from app.domain.schedule_forecasts import (
    ForecastDraft,
    RemainingEstimate,
    capture_basis,
    persist_forecast,
)
from app.domain.schedule_network import latest_human_estimates

logger = logging.getLogger(__name__)


@dataclass
class SchedulePropagationOutcome:
    scanned: int = 0
    updated: int = 0
    unchanged: int = 0
    locked: int = 0
    failed: int = 0
    interrupted: bool = False


class SchedulePropagation:
    def __init__(self, engine: Engine):
        self.engine = engine

    def run_once(
        self, *, as_of: datetime | None = None, should_stop: Callable[[], bool] | None = None
    ) -> SchedulePropagationOutcome:
        now = as_of or datetime.now(UTC)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("传播计算时间必须包含时区")
        now = now.astimezone(UTC)
        result = SchedulePropagationOutcome()
        cursor = None
        # Scan durable current applications, not a sequence cursor that can skip late commits.
        # Each target owns one short transaction; no source transaction locks another project.
        while True:
            apps = tables.cross_project_schedule_applications
            newer = apps.alias("newer")
            project = tables.projects
            statement = (
                select(project.c.tenant_id, project.c.id)
                .join(tables.tenants, tables.tenants.c.id == project.c.tenant_id)
                .where(
                    tables.tenants.c.status == "active",
                    project.c.status.in_(("approved", "active", "on_hold")),
                    exists(
                        select(apps.c.id).where(
                            apps.c.tenant_id == project.c.tenant_id,
                            apps.c.successor_project_id == project.c.id,
                            apps.c.operation != "remove",
                            ~exists(
                                select(newer.c.id).where(
                                    newer.c.tenant_id == apps.c.tenant_id,
                                    or_(
                                        newer.c.replaces_application_id == apps.c.id,
                                        newer.c.displaces_application_id == apps.c.id,
                                    ),
                                )
                            ),
                        )
                    ),
                )
                .order_by(project.c.tenant_id, project.c.id)
                .limit(100)
            )
            if cursor:
                statement = statement.where(tuple_(project.c.tenant_id, project.c.id) > cursor)
            with self.engine.connect() as connection:
                batch = connection.execute(statement).all()
            if not batch:
                break
            for tenant_id, project_id in batch:
                if should_stop and should_stop():
                    result.interrupted = True
                    return result
                result.scanned += 1
                try:
                    status = self.refresh(tenant_id, project_id, now)
                    setattr(result, status, getattr(result, status) + 1)
                except Exception as error:
                    result.failed += 1
                    logger.error(
                        "schedule_propagation_failed tenant=%s project=%s error_type=%s",
                        tenant_id,
                        project_id,
                        type(error).__name__,
                    )
            cursor = (batch[-1].tenant_id, batch[-1].id)
        return result

    def refresh(self, tenant_id: UUID, project_id: UUID, now: datetime) -> str:
        with self.engine.begin() as connection:
            if not connection.execute(
                select(tables.projects.c.id)
                .where(
                    tables.projects.c.tenant_id == tenant_id,
                    tables.projects.c.id == project_id,
                    tables.projects.c.status.in_(("approved", "active", "on_hold")),
                )
                .with_for_update(skip_locked=True)
            ).first():
                return "locked"
            capture = capture_basis(connection, tenant_id, project_id)
            if not capture.get("network"):
                return "unchanged"
            runs, records = tables.schedule_forecast_runs, tables.schedule_time_records
            previous = (
                connection.execute(
                    select(runs)
                    .join(
                        records,
                        (records.c.tenant_id == runs.c.tenant_id)
                        & (records.c.id == runs.c.record_id),
                    )
                    .where(
                        runs.c.tenant_id == tenant_id,
                        runs.c.project_id == project_id,
                    )
                    .order_by(records.c.version.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            stale_clock = bool(
                previous
                and datetime.fromisoformat(previous["result"]["as_of"]).replace(
                    second=0, microsecond=0
                )
                < now.replace(second=0, microsecond=0)
                and any(
                    node.get(point)
                    and not node.get("actual_" + point)
                    and datetime.fromisoformat(node[point]) < now
                    for node in previous["result"]["nodes"]
                    for point in ("start", "finish")
                )
            )
            if previous and previous["basis_digest"] == capture["basis_digest"] and not stale_clock:
                return "unchanged"
            local = {
                key: value
                for key, value in capture["basis"].items()
                if key not in ("external_dependencies", "external_input_digest")
            }
            estimates = latest_human_estimates(connection, tenant_id, project_id, local)
            request_id = uuid5(
                NAMESPACE_URL,
                f"pdos:schedule-propagation:{tenant_id}:{project_id}:{capture['basis_digest']}:"
                f"{previous['record_id'] if previous else 'initial'}:"
                f"{now.replace(second=0, microsecond=0).isoformat()}",
            )
            persist_forecast(
                connection,
                tenant_id,
                project_id,
                None,
                ForecastDraft(
                    request_id=request_id,
                    expected_basis_digest=capture["basis_digest"],
                    estimates={
                        key: RemainingEstimate.model_validate(value)
                        for key, value in estimates.items()
                    },
                    reason="跨项目前置变化后的确定性预测传播",
                ),
                capture,
                as_of=now,
                trigger="propagation",
            )
            return "updated"
