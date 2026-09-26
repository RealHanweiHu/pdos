"""Cross-project personal work aggregation (vNext V1-A2, My Work).

Read-only: one query per collection (plus one count), no per-item fan-out.
Visibility follows the object-permission boundary — non-admin roles only see
items inside projects they are members of, even when directly assigned.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import (
    ColumnElement,
    Engine,
    Row,
    Select,
    Text,
    case,
    exists,
    func,
    literal,
    or_,
    select,
)
from sqlalchemy import cast as sql_cast
from sqlalchemy.dialects.postgresql import aggregate_order_by

from app.ai.rollout_guard import employee_finding_visibility
from app.auth.roles import Action, Role, is_allowed
from app.db.schema import tables
from app.domain.gates import GateSlot, may_sign_gate_slot
from app.domain.my_work_filters import WorkFocus, filter_queue

WorkCollection = Literal[
    "tasks",
    "issues",
    "risks",
    "capa_actions",
    "gate_signoffs",
    "findings",
    "cross_schedule_approvals",
    "id_design_actions",
    "change_execution_confirmations",
    "risk_followup_actions",
    "task_takeover_actions",
    "cost_freeze_approvals",
]
WORK_COLLECTIONS: tuple[WorkCollection, ...] = (
    "tasks",
    "issues",
    "risks",
    "capa_actions",
    "gate_signoffs",
    "findings",
    "cross_schedule_approvals",
    "id_design_actions",
    "change_execution_confirmations",
    "risk_followup_actions",
    "task_takeover_actions",
    "cost_freeze_approvals",
)


class MyWorkQueueChanged(Exception):
    """A page belongs to an earlier personal queue ordering or membership."""


@dataclass(frozen=True)
class MyWorkPage:
    offset: int
    next_offset: int | None
    revision: str


def _page_summary(statement: Select[Any], order_by: tuple[ColumnElement[Any], ...]) -> Select[Any]:
    # Hash only the already-authorized queue projection, including its exact order.
    # The database returns a count and compact revision, not every work item.
    rows = statement.add_columns(
        func.row_number().over(order_by=order_by).label("queue_position")
    ).subquery("work_page_scope")
    row_digest = func.md5(sql_cast(func.to_jsonb(rows.table_valued()), Text))
    ordered_digest = func.string_agg(
        row_digest, aggregate_order_by(literal(""), rows.c.queue_position)
    )
    return select(func.count(), func.md5(func.coalesce(ordered_digest, ""))).select_from(rows)


OPEN_TASK_STATUSES = ("todo", "in_progress", "blocked", "pending_approval")
GATE_SLOTS: tuple[GateSlot, ...] = ("product", "engineering", "quality")


@dataclass(frozen=True)
class MyWorkProject:
    id: UUID
    code: str
    name: str


@dataclass(frozen=True)
class MyWorkTask:
    id: UUID
    project: MyWorkProject
    title: str
    status: str
    priority: str
    due_date: date | None


@dataclass(frozen=True)
class MyWorkIssue:
    id: UUID
    project: MyWorkProject
    title: str
    status: str
    severity: str
    target_date: date | None


@dataclass(frozen=True)
class MyWorkRisk:
    id: UUID
    project: MyWorkProject
    title: str
    status: str
    likelihood: int
    impact: int
    target_date: date | None


@dataclass(frozen=True)
class MyWorkCapaAction:
    id: UUID
    project: MyWorkProject
    ncr_id: UUID
    action_type: str
    description: str
    status: str
    due_date: date


@dataclass(frozen=True)
class MyWorkGateSignoff:
    id: UUID
    project: MyWorkProject
    gate_id: UUID
    gate_code: str
    gate_name: str
    slot: str
    requirement: str
    round_number: int
    review_due_at: datetime | None


@dataclass(frozen=True)
class MyWorkFinding:
    id: UUID
    project: MyWorkProject
    finding_type: str
    title: str
    created_at: datetime
    status: str = "pending_review"


@dataclass(frozen=True)
class MyWorkCrossSchedule:
    id: UUID
    project: MyWorkProject
    title: str
    operation: str
    created_at: datetime


@dataclass(frozen=True)
class MyWorkIdDesign:
    id: UUID
    project: MyWorkProject
    kind: str
    revision_id: UUID
    freeze_id: UUID | None
    title: str
    created_at: datetime


@dataclass(frozen=True)
class MyWorkChangeExecution:
    id: UUID
    project: MyWorkProject
    binding_id: UUID
    ecr_id: UUID
    task_id: UUID
    ecr_code: str
    title: str
    action: str
    revision_number: int
    created_at: datetime


@dataclass(frozen=True)
class MyWorkRiskFollowup:
    id: UUID
    project: MyWorkProject
    risk_id: UUID
    task_id: UUID
    title: str
    mode: str
    created_at: datetime


@dataclass(frozen=True)
class MyWorkTaskTakeover:
    id: UUID
    project: MyWorkProject
    task_id: UUID
    title: str
    mode: str
    revision: int
    due_date: date | None
    priority: str
    status: str
    created_at: datetime


@dataclass(frozen=True)
class MyWorkCostFreeze:
    id: UUID
    project: MyWorkProject
    title: str
    created_at: datetime


@dataclass(frozen=True)
class MyWorkCounts:
    tasks: int
    issues: int
    risks: int
    capa_actions: int
    gate_signoffs: int
    findings: int
    cross_schedule_approvals: int = 0
    id_design_actions: int = 0
    change_execution_confirmations: int = 0
    risk_followup_actions: int = 0
    task_takeover_actions: int = 0
    cost_freeze_approvals: int = 0


@dataclass(frozen=True)
class MyWorkSnapshot:
    tasks: tuple[MyWorkTask, ...]
    issues: tuple[MyWorkIssue, ...]
    risks: tuple[MyWorkRisk, ...]
    capa_actions: tuple[MyWorkCapaAction, ...]
    gate_signoffs: tuple[MyWorkGateSignoff, ...]
    findings: tuple[MyWorkFinding, ...]
    counts: MyWorkCounts
    cross_schedule_approvals: tuple[MyWorkCrossSchedule, ...] = ()
    id_design_actions: tuple[MyWorkIdDesign, ...] = ()
    change_execution_confirmations: tuple[MyWorkChangeExecution, ...] = ()
    risk_followup_actions: tuple[MyWorkRiskFollowup, ...] = ()
    task_takeover_actions: tuple[MyWorkTaskTakeover, ...] = ()
    cost_freeze_approvals: tuple[MyWorkCostFreeze, ...] = ()
    pages: dict[WorkCollection, MyWorkPage] = field(default_factory=dict)


def _project_columns() -> tuple[ColumnElement[UUID], ColumnElement[str], ColumnElement[str]]:
    return (
        tables.projects.c.id.label("project_id"),
        tables.projects.c.code.label("project_code"),
        tables.projects.c.name.label("project_name"),
    )


def _project_ref(row: Row[Any]) -> MyWorkProject:
    mapping = cast(dict[str, object], row._mapping)
    return MyWorkProject(
        id=cast(UUID, mapping["project_id"]),
        code=cast(str, mapping["project_code"]),
        name=cast(str, mapping["project_name"]),
    )


class MyWorkService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def load(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        role: Role,
        limit: int,
        collection: WorkCollection | None = None,
        offset: int = 0,
        expected_revision: str | None = None,
        project_id: UUID | None = None,
        search: str = "",
        focus: WorkFocus = "all",
        as_of_date: date | None = None,
    ) -> MyWorkSnapshot:
        as_of = as_of_date or datetime.now(UTC).astimezone(ZoneInfo("Asia/Shanghai")).date()
        search = search.strip()
        filter_scope = (
            f"{project_id}:{search}:{focus}:{as_of if focus in ('today', 'overdue') else ''}"
        )
        membership: Select[tuple[UUID]] | None = None
        if role not in (Role.OWNER, Role.ADMIN):
            membership = select(tables.project_members.c.project_id).where(
                tables.project_members.c.tenant_id == tenant_id,
                tables.project_members.c.user_id == user_id,
            )
        my_slots = tuple(slot for slot in GATE_SLOTS if may_sign_gate_slot(role, slot))
        include_findings = is_allowed(role, Action.FINDING_REVIEW)

        pages = {
            key: MyWorkPage(
                offset=offset, next_offset=None, revision="d41d8cd98f00b204e9800998ecf8427e"
            )
            for key in WORK_COLLECTIONS
            if collection is None or key == collection
        }
        # Counts/revisions and page rows must describe the same database snapshot.
        with self._engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection:

            def fetch(
                name: WorkCollection,
                statement: Select[Any],
                order_by: tuple[ColumnElement[Any], ...],
            ) -> tuple[list[Row[Any]], int]:
                if collection is not None and name != collection:
                    return [], 0
                statement = filter_queue(
                    statement, name, project_id=project_id, search=search, focus=focus, as_of=as_of
                )
                summary = connection.execute(_page_summary(statement, order_by)).one()
                total = int(summary[0])
                revision = hashlib.sha256(
                    f"{filter_scope}:{name}:{summary[1]}".encode()
                ).hexdigest()[:32]
                if expected_revision is not None and revision != expected_revision:
                    raise MyWorkQueueChanged
                rows = connection.execute(
                    statement.order_by(*order_by).offset(offset).limit(limit)
                ).all()
                following = offset + len(rows)
                pages[name] = MyWorkPage(
                    offset=offset,
                    next_offset=following if following < total else None,
                    revision=revision,
                )
                return list(rows), total

            def scoped(statement: Select[Any], project_column: ColumnElement[UUID]) -> Select[Any]:
                if membership is None:
                    return statement
                return statement.where(project_column.in_(membership))

            tasks_stmt = scoped(
                select(
                    tables.tasks.c.id,
                    tables.tasks.c.title,
                    tables.tasks.c.status,
                    tables.tasks.c.priority,
                    tables.tasks.c.due_date,
                    tables.tasks.c.created_at,
                    *_project_columns(),
                )
                .join(
                    tables.projects,
                    (tables.projects.c.tenant_id == tables.tasks.c.tenant_id)
                    & (tables.projects.c.id == tables.tasks.c.project_id),
                )
                .where(
                    tables.tasks.c.tenant_id == tenant_id,
                    tables.tasks.c.assignee_user_id == user_id,
                    tables.tasks.c.status.in_(OPEN_TASK_STATUSES),
                ),
                tables.tasks.c.project_id,
            )
            task_rows, task_total = fetch(
                "tasks",
                tasks_stmt,
                (
                    tables.tasks.c.due_date.asc().nulls_last(),
                    case((tables.tasks.c.status == "blocked", 0), else_=1),
                    case(
                        {"critical": 0, "high": 1, "medium": 2, "low": 3},
                        value=tables.tasks.c.priority,
                        else_=4,
                    ),
                    tables.tasks.c.created_at.asc(),
                    tables.tasks.c.id,
                ),
            )

            issues_stmt = scoped(
                select(
                    tables.issues.c.id,
                    tables.issues.c.title,
                    tables.issues.c.status,
                    tables.issues.c.severity,
                    tables.issues.c.target_date,
                    tables.issues.c.created_at,
                    *_project_columns(),
                )
                .join(
                    tables.projects,
                    (tables.projects.c.tenant_id == tables.issues.c.tenant_id)
                    & (tables.projects.c.id == tables.issues.c.project_id),
                )
                .where(
                    tables.issues.c.tenant_id == tenant_id,
                    or_(
                        tables.issues.c.owner_user_id == user_id,
                        (tables.issues.c.verifier_user_id == user_id)
                        & (tables.issues.c.status == "verification"),
                    ),
                    tables.issues.c.status != "closed",
                ),
                tables.issues.c.project_id,
            )
            issue_rows, issue_total = fetch(
                "issues",
                issues_stmt,
                (
                    tables.issues.c.target_date.asc().nulls_last(),
                    case(
                        {"critical": 0, "high": 1, "medium": 2, "low": 3},
                        value=tables.issues.c.severity,
                        else_=4,
                    ),
                    tables.issues.c.created_at.asc(),
                    tables.issues.c.id,
                ),
            )

            risks_stmt = scoped(
                select(
                    tables.risks.c.id,
                    tables.risks.c.title,
                    tables.risks.c.status,
                    tables.risks.c.likelihood,
                    tables.risks.c.impact,
                    tables.risks.c.target_date,
                    tables.risks.c.created_at,
                    *_project_columns(),
                )
                .join(
                    tables.projects,
                    (tables.projects.c.tenant_id == tables.risks.c.tenant_id)
                    & (tables.projects.c.id == tables.risks.c.project_id),
                )
                .where(
                    tables.risks.c.tenant_id == tenant_id,
                    tables.risks.c.owner_user_id == user_id,
                    tables.risks.c.draft_state == "confirmed",
                    tables.risks.c.status != "closed",
                ),
                tables.risks.c.project_id,
            )
            risk_rows, risk_total = fetch(
                "risks",
                risks_stmt,
                (
                    tables.risks.c.target_date.asc().nulls_last(),
                    (tables.risks.c.likelihood * tables.risks.c.impact).desc(),
                    tables.risks.c.created_at.asc(),
                    tables.risks.c.id,
                ),
            )

            capa_stmt = scoped(
                select(
                    tables.capa_actions.c.id,
                    tables.capa_actions.c.ncr_id,
                    tables.capa_actions.c.action_type,
                    tables.capa_actions.c.description,
                    tables.capa_actions.c.status,
                    tables.capa_actions.c.due_date,
                    tables.capa_actions.c.created_at,
                    *_project_columns(),
                )
                .join(
                    tables.projects,
                    (tables.projects.c.tenant_id == tables.capa_actions.c.tenant_id)
                    & (tables.projects.c.id == tables.capa_actions.c.project_id),
                )
                .where(
                    tables.capa_actions.c.tenant_id == tenant_id,
                    tables.capa_actions.c.owner_user_id == user_id,
                    tables.capa_actions.c.status != "completed",
                ),
                tables.capa_actions.c.project_id,
            )
            capa_rows, capa_total = fetch(
                "capa_actions",
                capa_stmt,
                (
                    tables.capa_actions.c.due_date.asc(),
                    tables.capa_actions.c.created_at.asc(),
                    tables.capa_actions.c.id,
                ),
            )

            signoff_rows: list[Row[Any]] = []
            signoff_total = 0
            if my_slots:
                signoff_stmt = scoped(
                    select(
                        tables.gate_signoffs.c.id,
                        tables.gate_signoffs.c.gate_id,
                        tables.gate_signoffs.c.slot,
                        tables.gate_signoffs.c.requirement,
                        tables.gate_signoff_rounds.c.round_number,
                        tables.gates.c.code.label("gate_code"),
                        tables.gates.c.name.label("gate_name"),
                        tables.gates.c.review_due_at,
                        tables.gate_signoffs.c.created_at,
                        *_project_columns(),
                    )
                    .join(
                        tables.gate_signoff_rounds,
                        (tables.gate_signoff_rounds.c.tenant_id == tables.gate_signoffs.c.tenant_id)
                        & (tables.gate_signoff_rounds.c.id == tables.gate_signoffs.c.round_id),
                    )
                    .join(
                        tables.gates,
                        (tables.gates.c.tenant_id == tables.gate_signoffs.c.tenant_id)
                        & (tables.gates.c.id == tables.gate_signoffs.c.gate_id),
                    )
                    .join(
                        tables.projects,
                        (tables.projects.c.tenant_id == tables.gate_signoffs.c.tenant_id)
                        & (tables.projects.c.id == tables.gate_signoffs.c.project_id),
                    )
                    .where(
                        tables.gate_signoffs.c.tenant_id == tenant_id,
                        tables.gate_signoffs.c.status == "pending",
                        tables.gate_signoffs.c.slot.in_(my_slots),
                        or_(
                            tables.gate_signoff_rounds.c.routing_snapshot["assignment"]["signers"][
                                tables.gate_signoffs.c.slot
                            ]["user_id"]
                            .as_string()
                            .is_(None),
                            tables.gate_signoff_rounds.c.routing_snapshot["assignment"]["signers"][
                                tables.gate_signoffs.c.slot
                            ]["user_id"].as_string()
                            == str(user_id),
                        ),
                        tables.gate_signoff_rounds.c.status == "open",
                        tables.gates.c.status == "reviewing",
                        tables.gates.c.stage_id == tables.projects.c.current_stage_id,
                    ),
                    tables.gate_signoffs.c.project_id,
                )
                signoff_rows, signoff_total = fetch(
                    "gate_signoffs",
                    signoff_stmt,
                    (
                        tables.gates.c.review_due_at.asc().nulls_last(),
                        tables.gate_signoffs.c.created_at.asc(),
                        tables.gate_signoffs.c.id,
                    ),
                )

            finding_rows: list[Row[Any]] = []
            finding_total = 0
            if include_findings:
                findings_stmt = scoped(
                    select(
                        tables.findings.c.id,
                        tables.findings.c.finding_type,
                        tables.findings.c.status,
                        tables.findings.c.title,
                        tables.findings.c.created_at,
                        *_project_columns(),
                    )
                    .join(
                        tables.projects,
                        (tables.projects.c.tenant_id == tables.findings.c.tenant_id)
                        & (tables.projects.c.id == tables.findings.c.project_id),
                    )
                    .where(
                        tables.findings.c.tenant_id == tenant_id,
                        tables.findings.c.status.in_(("pending_review", "accepted")),
                        employee_finding_visibility(),
                    ),
                    tables.findings.c.project_id,
                )
                finding_rows, finding_total = fetch(
                    "findings",
                    findings_stmt,
                    (
                        case((tables.findings.c.status == "accepted", 0), else_=1),
                        tables.findings.c.created_at.asc(),
                        tables.findings.c.id,
                    ),
                )

            cross_rows: list[Row[Any]] = []
            cross_total = 0
            if is_allowed(role, Action.WORK_ITEM_EDIT):
                proposals, policies = (
                    tables.cross_project_schedule_proposals,
                    tables.baseline_change_policies,
                )
                decisions = tables.cross_project_schedule_decisions
                newer = policies.alias("newer_cross_policy")
                own_is_predecessor = tables.projects.c.id == proposals.c.predecessor_project_id
                own_policy_id = case(
                    (own_is_predecessor, proposals.c.predecessor_policy_id),
                    else_=proposals.c.successor_policy_id,
                )
                own_title = case(
                    (
                        own_is_predecessor,
                        proposals.c.snapshot["predecessor"]["node"]["title"].as_string(),
                    ),
                    else_=proposals.c.snapshot["successor"]["node"]["title"].as_string(),
                ).label("title")
                statement = scoped(
                    select(
                        proposals.c.id,
                        proposals.c.operation,
                        proposals.c.created_at,
                        own_title,
                        *_project_columns(),
                    )
                    .join(
                        tables.projects,
                        (tables.projects.c.tenant_id == proposals.c.tenant_id)
                        & or_(
                            tables.projects.c.id == proposals.c.predecessor_project_id,
                            tables.projects.c.id == proposals.c.successor_project_id,
                        ),
                    )
                    .join(
                        policies,
                        (policies.c.tenant_id == proposals.c.tenant_id)
                        & (policies.c.project_id == tables.projects.c.id)
                        & (policies.c.id == own_policy_id),
                    )
                    .where(
                        proposals.c.tenant_id == tenant_id,
                        policies.c.approver_user_id == user_id,
                        proposals.c.snapshot["sharing"]["version"].as_string()
                        == "cross_schedule_approval.v1",
                        or_(
                            policies.c.four_eyes.is_(False),
                            proposals.c.created_by_user_id != user_id,
                        ),
                        ~exists(
                            select(newer.c.id).where(
                                newer.c.tenant_id == policies.c.tenant_id,
                                newer.c.project_id == policies.c.project_id,
                                newer.c.version > policies.c.version,
                            )
                        ),
                        ~exists(
                            select(decisions.c.id).where(
                                decisions.c.tenant_id == proposals.c.tenant_id,
                                decisions.c.proposal_id == proposals.c.id,
                                or_(
                                    decisions.c.project_id == tables.projects.c.id,
                                    decisions.c.action != "approve",
                                ),
                            )
                        ),
                    ),
                    tables.projects.c.id,
                )
                cross_rows, cross_total = fetch(
                    "cross_schedule_approvals",
                    statement,
                    (proposals.c.created_at.asc(), proposals.c.id, tables.projects.c.id),
                )

            from app.domain.id_design_inbox import inbox_statement

            id_rows: list[Row[Any]] = []
            id_total = 0
            id_statement = inbox_statement(tenant_id, user_id, role)
            if id_statement is not None:
                columns = id_statement.selected_columns
                id_rows, id_total = fetch(
                    "id_design_actions",
                    id_statement,
                    (columns.created_at.asc(), columns.id, columns.kind),
                )

            from app.domain.change_execution_inbox import inbox_statement as execution_statement

            execution_rows: list[Row[Any]] = []
            execution_total = 0
            execution_query = execution_statement(tenant_id, user_id, role)
            if execution_query is not None:
                execution_columns = execution_query.selected_columns
                execution_rows, execution_total = fetch(
                    "change_execution_confirmations",
                    execution_query,
                    (execution_columns.created_at.asc(), execution_columns.id),
                )

            from app.domain.risk_followup_results import inbox_statement as risk_statement

            risk_result_rows: list[Row[Any]] = []
            risk_result_total = 0
            if collection is None or collection == "risk_followup_actions":
                risk_query = risk_statement(connection, tenant_id, user_id, role)
                if risk_query is not None:
                    columns = risk_query.selected_columns
                    risk_result_rows, risk_result_total = fetch(
                        "risk_followup_actions", risk_query, (columns.created_at, columns.id)
                    )

            from app.domain.task_takeover_inbox import inbox_statement as takeover_statement

            takeover_rows: list[Row[Any]] = []
            takeover_total = 0
            if collection is None or collection == "task_takeover_actions":
                takeover_query = takeover_statement(connection, tenant_id, user_id, role)
                if takeover_query is not None:
                    columns = takeover_query.selected_columns
                    takeover_rows, takeover_total = fetch(
                        "task_takeover_actions",
                        takeover_query,
                        (columns.due_date.asc().nulls_last(), columns.created_at, columns.id),
                    )

            cost_rows: list[Row[Any]] = []
            cost_total = 0
            if is_allowed(role, Action.COST_APPROVE):
                r, d, calculation = (
                    tables.cost_freeze_requests,
                    tables.cost_freeze_decisions,
                    tables.cost_rollups,
                )
                cost_query = scoped(
                    select(r.c.id, r.c.created_at, calculation.c.title, *_project_columns())
                    .select_from(
                        r.join(
                            calculation,
                            (calculation.c.tenant_id == r.c.tenant_id)
                            & (calculation.c.project_id == r.c.project_id)
                            & (calculation.c.id == r.c.rollup_id),
                        ).join(
                            tables.projects,
                            (tables.projects.c.tenant_id == r.c.tenant_id)
                            & (tables.projects.c.id == r.c.project_id),
                        )
                    )
                    .where(
                        r.c.tenant_id == tenant_id,
                        r.c.approver_user_id == user_id,
                        ~exists(
                            select(d.c.id).where(
                                d.c.tenant_id == r.c.tenant_id, d.c.freeze_request_id == r.c.id
                            )
                        ),
                    ),
                    r.c.project_id,
                )
                cost_rows, cost_total = fetch(
                    "cost_freeze_approvals", cost_query, (r.c.created_at.asc(), r.c.id)
                )

        if (
            collection is not None
            and expected_revision is not None
            and pages[collection].revision != expected_revision
        ):
            raise MyWorkQueueChanged
        return MyWorkSnapshot(
            pages=pages,
            tasks=tuple(
                MyWorkTask(
                    id=row.id,
                    project=_project_ref(row),
                    title=row.title,
                    status=row.status,
                    priority=row.priority,
                    due_date=row.due_date,
                )
                for row in task_rows
            ),
            issues=tuple(
                MyWorkIssue(
                    id=row.id,
                    project=_project_ref(row),
                    title=row.title,
                    status=row.status,
                    severity=row.severity,
                    target_date=row.target_date,
                )
                for row in issue_rows
            ),
            risks=tuple(
                MyWorkRisk(
                    id=row.id,
                    project=_project_ref(row),
                    title=row.title,
                    status=row.status,
                    likelihood=row.likelihood,
                    impact=row.impact,
                    target_date=row.target_date,
                )
                for row in risk_rows
            ),
            capa_actions=tuple(
                MyWorkCapaAction(
                    id=row.id,
                    project=_project_ref(row),
                    ncr_id=row.ncr_id,
                    action_type=row.action_type,
                    description=row.description,
                    status=row.status,
                    due_date=row.due_date,
                )
                for row in capa_rows
            ),
            gate_signoffs=tuple(
                MyWorkGateSignoff(
                    id=row.id,
                    project=_project_ref(row),
                    gate_id=row.gate_id,
                    gate_code=row.gate_code,
                    gate_name=row.gate_name,
                    slot=row.slot,
                    requirement=row.requirement,
                    round_number=row.round_number,
                    review_due_at=row.review_due_at,
                )
                for row in signoff_rows
            ),
            findings=tuple(
                MyWorkFinding(
                    id=row.id,
                    project=_project_ref(row),
                    finding_type=row.finding_type,
                    status=row.status,
                    title=row.title,
                    created_at=row.created_at,
                )
                for row in finding_rows
            ),
            cross_schedule_approvals=tuple(
                MyWorkCrossSchedule(
                    id=row.id,
                    project=_project_ref(row),
                    title=row.title,
                    operation=row.operation,
                    created_at=row.created_at,
                )
                for row in cross_rows
            ),
            id_design_actions=tuple(
                MyWorkIdDesign(
                    id=row.id,
                    project=_project_ref(row),
                    kind=row.kind,
                    revision_id=row.revision_id,
                    freeze_id=row.freeze_id,
                    title=row.title,
                    created_at=row.created_at,
                )
                for row in id_rows
            ),
            change_execution_confirmations=tuple(
                MyWorkChangeExecution(
                    id=row.id,
                    project=_project_ref(row),
                    binding_id=row.binding_id,
                    ecr_id=row.ecr_id,
                    task_id=row.task_id,
                    ecr_code=row.ecr_code,
                    title=row.title,
                    action=row.action,
                    revision_number=row.revision_number,
                    created_at=row.created_at,
                )
                for row in execution_rows
            ),
            risk_followup_actions=tuple(
                MyWorkRiskFollowup(
                    id=row.id,
                    project=_project_ref(row),
                    risk_id=row.risk_id,
                    task_id=row.task_id,
                    title=row.title,
                    mode=row.mode,
                    created_at=row.created_at,
                )
                for row in risk_result_rows
            ),
            task_takeover_actions=tuple(
                MyWorkTaskTakeover(
                    id=row.id,
                    project=_project_ref(row),
                    task_id=row.task_id,
                    title=row.title,
                    mode=row.mode,
                    revision=row.revision,
                    due_date=row.due_date,
                    priority=row.priority,
                    status=row.status,
                    created_at=row.created_at,
                )
                for row in takeover_rows
            ),
            cost_freeze_approvals=tuple(
                MyWorkCostFreeze(
                    id=row.id, project=_project_ref(row), title=row.title, created_at=row.created_at
                )
                for row in cost_rows
            ),
            counts=MyWorkCounts(
                tasks=task_total,
                issues=issue_total,
                risks=risk_total,
                capa_actions=capa_total,
                gate_signoffs=signoff_total,
                findings=finding_total,
                cross_schedule_approvals=cross_total,
                id_design_actions=id_total,
                change_execution_confirmations=execution_total,
                risk_followup_actions=risk_result_total,
                task_takeover_actions=takeover_total,
                cost_freeze_approvals=cost_total,
            ),
        )
