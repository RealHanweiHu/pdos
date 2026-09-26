"""Periodic risk and reminder reconciliation using durable domain idempotency."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Engine, select, text, tuple_

from app.db.schema import tables
from app.domain.findings import FindingService
from app.domain.reminders import ReminderService
from app.domain.risk_candidates import RiskCandidateService
from app.integrations.reminder_delivery import ReminderDeliveryDispatcher
from app.settings import Settings

logger = logging.getLogger(__name__)
SCHEDULER_LOCK = "pdos:reminder_scheduler:v1"
PROJECT_BATCH_SIZE = 100


@dataclass
class CycleOutcome:
    skipped_locked: bool = False
    interrupted: bool = False
    projects: int = 0
    failed_projects: int = 0
    candidates_created: int = 0
    candidates_reactivated: int = 0
    candidates_cleared: int = 0
    findings_archived: int = 0
    scheduled: int = 0
    cancelled: int = 0
    fired: int = 0
    enqueued: int = 0
    already_enqueued: int = 0
    skipped_unbound: int = 0
    deferred_quiet_hours: int = 0
    capped_recipients: int = 0


class ReminderScheduler:
    def __init__(self, engine: Engine, settings: Settings) -> None:
        self._engine = engine
        self._archive_findings = settings.finding_auto_archive_enabled
        self._findings = FindingService(engine)
        self._risks = RiskCandidateService(engine)
        self._reminders = ReminderService(engine)
        self._delivery = ReminderDeliveryDispatcher(engine, settings)

    def run_once(
        self,
        *,
        as_of: datetime | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> CycleOutcome:
        effective = as_of or datetime.now(UTC)
        if effective.tzinfo is None or effective.utcoffset() is None:
            raise ValueError("Reminder scheduler clock must include a timezone")
        effective = effective.astimezone(UTC)
        outcome = CycleOutcome()
        # A transaction-scoped lock is released on crash/rollback as well as success.
        # Domain writes use their own short transactions; a later failure therefore
        # cannot undo earlier projects and a restart can safely replay the whole scan.
        with self._engine.begin() as connection:
            acquired = connection.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtextextended(:scope, 0))"),
                {"scope": SCHEDULER_LOCK},
            ).scalar_one()
            if not acquired:
                outcome.skipped_locked = True
                return outcome
            cursor: tuple[UUID, UUID] | None = None
            while True:
                statement = (
                    select(tables.projects.c.tenant_id, tables.projects.c.id)
                    .join(tables.tenants, tables.tenants.c.id == tables.projects.c.tenant_id)
                    .where(
                        tables.tenants.c.status == "active",
                        tables.projects.c.status != "archived",
                    )
                    .order_by(tables.projects.c.tenant_id, tables.projects.c.id)
                    .limit(PROJECT_BATCH_SIZE)
                )
                if cursor is not None:
                    statement = statement.where(
                        tuple_(tables.projects.c.tenant_id, tables.projects.c.id) > cursor
                    )
                projects = connection.execute(statement).all()
                if not projects:
                    break
                for project in projects:
                    if should_stop is not None and should_stop():
                        outcome.interrupted = True
                        return outcome
                    outcome.projects += 1
                    self._scan_project(
                        tenant_id=project.tenant_id,
                        project_id=project.id,
                        as_of=effective,
                        outcome=outcome,
                    )
                cursor = (projects[-1].tenant_id, projects[-1].id)
        return outcome

    def _scan_project(
        self, *, tenant_id: UUID, project_id: UUID, as_of: datetime, outcome: CycleOutcome
    ) -> None:
        failed = False
        if self._archive_findings:
            try:
                outcome.findings_archived += len(
                    self._findings.archive_stale(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        actor_user_id=None,
                        automatic=True,
                        now=as_of,
                    )
                )
            except Exception as error:
                failed = True
                self._log_failure(tenant_id, project_id, "finding_archive", error)
        try:
            risks = self._risks.scan(
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=None,
                today=as_of.date(),
                automatic=True,
            )
            outcome.candidates_created += risks.created
            outcome.candidates_reactivated += risks.reactivated
            outcome.candidates_cleared += risks.cleared
        except Exception as error:
            failed = True
            self._log_failure(tenant_id, project_id, "risks", error)
        try:
            reminders = self._reminders.scan(
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=None,
                as_of=as_of,
                automatic=True,
            )
            outcome.scheduled += reminders.scheduled
            outcome.cancelled += reminders.cancelled
            outcome.fired += reminders.fired
        except Exception as error:
            # Do not dispatch stale state when reminder reconciliation failed.
            outcome.failed_projects += 1
            self._log_failure(tenant_id, project_id, "reminders", error)
            return
        try:
            delivery = self._delivery.dispatch(
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=None,
                now=as_of,
                automatic=True,
            )
            outcome.enqueued += delivery.enqueued
            outcome.already_enqueued += delivery.already_enqueued
            outcome.skipped_unbound += delivery.skipped_unbound
            outcome.deferred_quiet_hours += delivery.deferred_quiet_hours
            outcome.capped_recipients += delivery.capped_recipients
        except Exception as error:
            failed = True
            self._log_failure(tenant_id, project_id, "delivery", error)
        outcome.failed_projects += int(failed)

    @staticmethod
    def _log_failure(tenant_id: UUID, project_id: UUID, stage: str, error: Exception) -> None:
        # Database/provider exception messages may contain SQL or credentials.
        logger.error(
            "reminder_project_failed tenant_id=%s project_id=%s stage=%s error_type=%s",
            tenant_id,
            project_id,
            stage,
            type(error).__name__,
        )
