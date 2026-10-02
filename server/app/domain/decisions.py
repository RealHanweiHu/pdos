"""Project-scoped first-class Decision use cases (vNext V1-B4, D30).

A Decision keeps the "why" of a choice: context, considered options,
trade-offs, evidence references, and the accountable people. Decisions that
trigger a hard-gate action carry a follow-up state so the pending action is
visible until the gate-side execution reports back.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, Table, select
from sqlalchemy.engine import RowMapping

from app.db.schema import tables
from app.domain.decision_execution import execution_choices, execution_receipt
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

MANUAL_DECISION_KINDS = frozenset(
    {
        "technical_choice",
        "supplier_choice",
        "process_decision",
        "rebaseline",
        "definition_release",
        "ccr_response",
    }
)


class DecisionNotFoundError(LookupError):
    """Raised when a Decision is absent from the tenant-bound Project."""


class DecisionScopeError(ValueError):
    """Raised when a related Issue, Gate, or person is outside the Project."""


class DecisionContentError(ValueError):
    """A manual Decision must preserve its full rationale and accountable approver."""


class DecisionFollowUpError(ValueError):
    """Raised on an invalid follow-up state transition."""


@dataclass(frozen=True)
class DecisionRecord:
    id: UUID
    project_id: UUID
    gate_id: UUID | None
    issue_id: UUID | None
    decided_by_user_id: UUID | None
    owner_user_id: UUID | None
    approver_user_id: UUID | None
    decision_kind: str
    title: str
    context: str | None
    options: tuple[str, ...]
    trade_offs: str | None
    outcome: str
    rationale: str | None
    consequence: str | None
    evidence_refs: tuple[str, ...]
    follow_up_state: str
    follow_up_note: str | None
    follow_up_task_id: UUID | None
    follow_up_audit_id: int | None
    execution_evidence: dict[str, object] | None
    decided_at: datetime
    created_at: datetime
    updated_at: datetime
    source_finding_id: UUID | None = None
    historical_source: dict[str, Any] | None = None
    historical_origin_state: dict[str, Any] | None = None


@dataclass(frozen=True)
class DecisionDraft:
    decision_kind: str
    title: str
    outcome: str
    context: str | None = None
    options: tuple[str, ...] = field(default_factory=tuple)
    trade_offs: str | None = None
    rationale: str | None = None
    consequence: str | None = None
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    issue_id: UUID | None = None
    gate_id: UUID | None = None
    owner_user_id: UUID | None = None
    approver_user_id: UUID | None = None
    follow_up_pending: bool = False
    follow_up_note: str | None = None
    follow_up_task_id: UUID | None = None


def _decision_statement() -> Any:
    columns = tables.decisions.c
    return select(
        columns.id,
        columns.project_id,
        columns.gate_id,
        columns.issue_id,
        columns.decided_by_user_id,
        columns.owner_user_id,
        columns.approver_user_id,
        columns.decision_kind,
        columns.title,
        columns.context,
        columns.options,
        columns.trade_offs,
        columns.outcome,
        columns.rationale,
        columns.consequence,
        columns.evidence_refs,
        columns.follow_up_state,
        columns.follow_up_note,
        columns.follow_up_task_id,
        columns.follow_up_audit_id,
        columns.decided_at,
        columns.created_at,
        columns.updated_at,
        columns.source_finding_id,
        columns.historical_source,
    )


def _record_from_row(row: RowMapping) -> DecisionRecord:
    return DecisionRecord(
        id=row["id"],
        project_id=row["project_id"],
        gate_id=row["gate_id"],
        issue_id=row["issue_id"],
        decided_by_user_id=row["decided_by_user_id"],
        owner_user_id=row["owner_user_id"],
        approver_user_id=row["approver_user_id"],
        decision_kind=row["decision_kind"],
        title=row["title"],
        context=row["context"],
        options=tuple(str(item) for item in row["options"]),
        trade_offs=row["trade_offs"],
        outcome=row["outcome"],
        rationale=row["rationale"],
        consequence=row["consequence"],
        evidence_refs=tuple(str(item) for item in row["evidence_refs"]),
        follow_up_state=row["follow_up_state"],
        follow_up_note=row["follow_up_note"],
        follow_up_task_id=row["follow_up_task_id"],
        follow_up_audit_id=row["follow_up_audit_id"],
        execution_evidence=None,
        decided_at=row["decided_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        source_finding_id=row["source_finding_id"],
        historical_source=row.get("historical_source"),
    )


def _decision_snapshot(record: DecisionRecord) -> dict[str, object]:
    return {
        "project_id": str(record.project_id),
        **({"historical_source": record.historical_source} if record.historical_source else {}),
        "source_finding_id": str(record.source_finding_id) if record.source_finding_id else None,
        "issue_id": str(record.issue_id) if record.issue_id is not None else None,
        "gate_id": str(record.gate_id) if record.gate_id is not None else None,
        "decision_kind": record.decision_kind,
        "title": record.title,
        "context": record.context,
        "options": list(record.options),
        "trade_offs": record.trade_offs,
        "outcome": record.outcome,
        "rationale": record.rationale,
        "consequence": record.consequence,
        "evidence_refs": list(record.evidence_refs),
        "follow_up_state": record.follow_up_state,
        "follow_up_note": record.follow_up_note,
        "follow_up_task_id": str(record.follow_up_task_id) if record.follow_up_task_id else None,
        "follow_up_audit_id": record.follow_up_audit_id,
        "execution_evidence": record.execution_evidence,
    }


class DecisionService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _validate_in_project(
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
                *([table.c.withdrawn_at.is_(None)] if table is tables.issues else []),
            )
        ).scalar_one_or_none()
        if found is None:
            raise DecisionScopeError

    @staticmethod
    def _validate_member(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        user_id: UUID | None,
    ) -> None:
        if user_id is None:
            return
        found = connection.execute(
            select(tables.project_members.c.id).where(
                tables.project_members.c.tenant_id == tenant_id,
                tables.project_members.c.project_id == project_id,
                tables.project_members.c.user_id == user_id,
            )
        ).scalar_one_or_none()
        if found is None:
            raise DecisionScopeError

    def _get_record(
        self,
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        decision_id: UUID,
    ) -> DecisionRecord:
        row = (
            connection.execute(
                _decision_statement().where(
                    tables.decisions.c.tenant_id == tenant_id,
                    tables.decisions.c.project_id == project_id,
                    tables.decisions.c.id == decision_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise DecisionNotFoundError
        return self._origins(
            connection,
            tenant_id,
            [self._with_execution(connection, tenant_id, _record_from_row(row))],
        )[0]

    @staticmethod
    def _with_execution(
        connection: Connection, tenant_id: UUID, record: DecisionRecord
    ) -> DecisionRecord:
        if record.follow_up_state != "completed":
            return record
        receipt = (
            execution_receipt(
                connection,
                tenant_id=tenant_id,
                project_id=record.project_id,
                decision=record,
                audit_id=record.follow_up_audit_id,
            )
            if record.follow_up_audit_id is not None
            else None
        )
        return replace(
            record,
            follow_up_state="completed" if receipt else "pending",
            execution_evidence=receipt,
        )

    def execution_choices(
        self, *, tenant_id: UUID, project_id: UUID, decision_id: UUID
    ) -> list[dict[str, object]]:
        with self._engine.connect() as connection:
            record = self._get_record(
                connection, tenant_id=tenant_id, project_id=project_id, decision_id=decision_id
            )
            return execution_choices(
                connection, tenant_id=tenant_id, project_id=project_id, decision=record
            )

    @staticmethod
    def _origins(
        c: Connection, tenant: UUID, records: list[DecisionRecord]
    ) -> list[DecisionRecord]:
        from app.domain.decision_intake_state import source_states

        identities = [
            UUID(row.historical_source["source_row_id"]) for row in records if row.historical_source
        ]
        if not identities:
            return records
        states = source_states(c, tenant, [{"id": identity} for identity in identities])
        result = []
        for row in records:
            state = (
                states.get(UUID(row.historical_source["source_row_id"]))
                if row.historical_source
                else None
            )
            if state is not None:
                state = {
                    key: value for key, value in state.items() if key != "association_snapshot"
                }
                state["on_this_decision"] = state["current_decision_id"] == str(row.id)
            result.append(replace(row, historical_origin_state=state))
        return result

    def list(self, *, tenant_id: UUID, project_id: UUID) -> list[DecisionRecord]:
        with self._engine.connect() as connection:
            records = [
                self._with_execution(connection, tenant_id, _record_from_row(row))
                for row in connection.execute(
                    _decision_statement()
                    .where(
                        tables.decisions.c.tenant_id == tenant_id,
                        tables.decisions.c.project_id == project_id,
                    )
                    .order_by(tables.decisions.c.decided_at.desc(), tables.decisions.c.id.desc())
                ).mappings()
            ]

            return self._origins(connection, tenant_id, records)

    def record_history(
        self,
        *,
        connection: Connection,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        draft: DecisionDraft,
        historical_source: dict[str, Any],
    ) -> DecisionRecord:
        """Register reviewed source facts; the current actor is not a historical approver."""
        if not draft.title.strip() or not draft.outcome.strip():
            raise DecisionContentError("历史决策需要原文标题和结论")
        if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
            raise DecisionNotFoundError
        identity, now = uuid4(), datetime.now(UTC)
        connection.execute(
            tables.decisions.insert().values(
                id=identity,
                tenant_id=tenant_id,
                project_id=project_id,
                decision_kind="historical_record",
                title=draft.title,
                outcome=draft.outcome,
                context=draft.context,
                options=list(draft.options),
                trade_offs=draft.trade_offs,
                rationale=draft.rationale,
                consequence=draft.consequence,
                evidence_refs=list(draft.evidence_refs),
                historical_source=historical_source,
                follow_up_state="none",
                decided_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        record = self._get_record(
            connection, tenant_id=tenant_id, project_id=project_id, decision_id=identity
        )
        EventAuditWriter(
            connection, tenant_id=tenant_id, actor_user_id=actor_user_id, project_id=project_id
        ).record(
            EventDraft(
                event_id=f"decision:{identity}:recorded",
                event_type="DECISION_RECORDED",
                source="development_case_service",
                entity_id=identity,
                payload={"decision_kind": record.decision_kind, "outcome": record.outcome},
                occurred_at=now,
            ),
            AuditDraft(
                action="decision.history_register", after_snapshot=_decision_snapshot(record)
            ),
        )
        return record

    def create(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        draft: DecisionDraft,
        connection: Connection | None = None,
        source_finding_id: UUID | None = None,
        now: datetime | None = None,
    ) -> DecisionRecord:
        if not all(
            (
                draft.context,
                draft.options,
                draft.trade_offs,
                draft.rationale,
                draft.consequence,
                draft.evidence_refs,
                draft.approver_user_id,
            )
        ):
            raise DecisionContentError("请补齐背景、选项、权衡、理由、后果、证据及批准人")
        if draft.follow_up_pending and (not draft.follow_up_note or not draft.owner_user_id):
            raise DecisionContentError("需要跟进的决策须指定负责人并说明目标动作")
        if draft.follow_up_task_id is not None and draft.gate_id is not None:
            raise DecisionContentError("请选择一个明确的执行目标")
        if draft.follow_up_task_id is not None and not draft.follow_up_pending:
            raise DecisionContentError("关联执行任务时必须开启跟进")
        decision_id = uuid4()
        occurred_at = now or datetime.now(UTC)
        with (
            nullcontext(connection) if connection is not None else self._engine.begin()
        ) as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise DecisionNotFoundError
            self._validate_in_project(
                connection,
                tables.tasks,
                tenant_id=tenant_id,
                project_id=project_id,
                row_id=draft.follow_up_task_id,
            )
            self._validate_in_project(
                connection,
                tables.issues,
                tenant_id=tenant_id,
                project_id=project_id,
                row_id=draft.issue_id,
            )
            self._validate_in_project(
                connection,
                tables.gates,
                tenant_id=tenant_id,
                project_id=project_id,
                row_id=draft.gate_id,
            )
            self._validate_member(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                user_id=draft.owner_user_id,
            )
            self._validate_member(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                user_id=draft.approver_user_id,
            )
            connection.execute(
                tables.decisions.insert(),
                {
                    "id": decision_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "gate_id": draft.gate_id,
                    "source_finding_id": source_finding_id,
                    "issue_id": draft.issue_id,
                    "decided_by_user_id": actor_user_id,
                    "owner_user_id": draft.owner_user_id,
                    "approver_user_id": draft.approver_user_id,
                    "decision_kind": draft.decision_kind,
                    "title": draft.title,
                    "context": draft.context,
                    "options": list(draft.options),
                    "trade_offs": draft.trade_offs,
                    "outcome": draft.outcome,
                    "rationale": draft.rationale,
                    "consequence": draft.consequence,
                    "evidence_refs": list(draft.evidence_refs),
                    "follow_up_state": "pending" if draft.follow_up_pending else "none",
                    "follow_up_note": draft.follow_up_note if draft.follow_up_pending else None,
                    "follow_up_task_id": draft.follow_up_task_id
                    if draft.follow_up_pending
                    else None,
                    "decided_at": occurred_at,
                    "created_at": occurred_at,
                    "updated_at": occurred_at,
                },
            )
            record = self._get_record(
                connection, tenant_id=tenant_id, project_id=project_id, decision_id=decision_id
            )
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"decision:{decision_id}:recorded",
                    event_type="DECISION_RECORDED",
                    source="development_case_service",
                    entity_id=decision_id,
                    payload={
                        "decision_kind": record.decision_kind,
                        "outcome": record.outcome,
                    },
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="decision.record",
                    after_snapshot=_decision_snapshot(record),
                ),
            )
            return record

    def bind_execution_task(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        decision_id: UUID,
        task_id: UUID,
    ) -> DecisionRecord:
        with self._engine.begin() as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise DecisionNotFoundError
            before = self._get_record(
                connection, tenant_id=tenant_id, project_id=project_id, decision_id=decision_id
            )
            if (
                before.follow_up_state != "pending"
                or before.gate_id is not None
                or before.decision_kind
                not in {"technical_choice", "supplier_choice", "process_decision", "ccr_response"}
            ):
                raise DecisionFollowUpError("此决策不能用普通任务替代其目标动作")
            task = connection.execute(
                select(tables.tasks.c.status).where(
                    tables.tasks.c.tenant_id == tenant_id,
                    tables.tasks.c.project_id == project_id,
                    tables.tasks.c.id == task_id,
                )
            ).scalar_one_or_none()
            if task is None:
                raise DecisionScopeError
            if task in {"done", "skipped"}:
                raise DecisionFollowUpError("请选择待执行任务，完成后再关联其执行凭据")
            connection.execute(
                tables.decisions.update()
                .where(
                    tables.decisions.c.tenant_id == tenant_id,
                    tables.decisions.c.project_id == project_id,
                    tables.decisions.c.id == decision_id,
                )
                .values(
                    follow_up_task_id=task_id,
                    follow_up_state="pending",
                    follow_up_audit_id=None,
                    updated_at=datetime.now(UTC),
                )
            )
            after = self._get_record(
                connection, tenant_id=tenant_id, project_id=project_id, decision_id=decision_id
            )
            EventAuditWriter(
                connection, tenant_id=tenant_id, actor_user_id=actor_user_id, project_id=project_id
            ).record(
                EventDraft(
                    event_id=f"decision:{decision_id}:target:{uuid4()}",
                    event_type="DECISION_RECORDED",
                    source="development_case_service",
                    entity_id=decision_id,
                    payload={"decision_kind": after.decision_kind, "outcome": after.outcome},
                ),
                AuditDraft(
                    action="decision.execution_target",
                    before_snapshot=_decision_snapshot(before),
                    after_snapshot=_decision_snapshot(after),
                ),
            )
            return after

    def complete_follow_up(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        project_id: UUID,
        decision_id: UUID,
        note: str,
        execution_audit_id: int | None = None,
    ) -> DecisionRecord:
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise DecisionNotFoundError
            before = self._get_record(
                connection, tenant_id=tenant_id, project_id=project_id, decision_id=decision_id
            )
            if before.follow_up_state != "pending":
                raise DecisionFollowUpError
            if (
                execution_audit_id is None
                or execution_receipt(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    decision=before,
                    audit_id=execution_audit_id,
                )
                is None
            ):
                raise DecisionFollowUpError("需要当前有效的关联目标执行凭据；备注不能证明执行完成")
            connection.execute(
                tables.decisions.update()
                .where(
                    tables.decisions.c.tenant_id == tenant_id,
                    tables.decisions.c.id == decision_id,
                )
                .values(
                    follow_up_state="completed",
                    follow_up_note=note,
                    follow_up_audit_id=execution_audit_id,
                    updated_at=occurred_at,
                )
            )
            after = self._get_record(
                connection, tenant_id=tenant_id, project_id=project_id, decision_id=decision_id
            )
            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                project_id=project_id,
            ).record(
                EventDraft(
                    event_id=f"decision:{decision_id}:follow-up:{uuid4()}",
                    event_type="DECISION_RECORDED",
                    source="development_case_service",
                    entity_id=decision_id,
                    payload={
                        "decision_kind": after.decision_kind,
                        "outcome": after.outcome,
                    },
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="decision.follow_up_complete",
                    before_snapshot=_decision_snapshot(before),
                    after_snapshot=_decision_snapshot(after),
                ),
            )
            return after
