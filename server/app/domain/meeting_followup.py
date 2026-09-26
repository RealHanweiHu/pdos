"""Human meeting follow-up bound to real tasks and later meeting review."""

from contextlib import nullcontext
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.sql.selectable import CTE

from app.auth.roles import Action, Role, is_allowed
from app.db.schema import tables
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.knowledge_push import KnowledgeVersionError
from app.domain.meeting_preparation import MeetingPreparationService, source_record
from app.domain.meetings import MeetingNotFoundError, MeetingService, MeetingStateError
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.task_preparation import project_link
from app.domain.tasks import TaskDraft, TaskService


def _agenda(connection: Connection, tenant_id: UUID, meeting_id: UUID, agenda_id: UUID) -> Any:
    row = (
        connection.execute(
            select(tables.meeting_agenda_items).where(
                tables.meeting_agenda_items.c.tenant_id == tenant_id,
                tables.meeting_agenda_items.c.meeting_id == meeting_id,
                tables.meeting_agenda_items.c.id == agenda_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise MeetingNotFoundError
    return row


def _represented(tenant_id: UUID, project_id: UUID, meeting_id: UUID) -> CTE:
    """Map each target agenda to its carry family, including sibling branches.

    UNION terminates even for historical cycles. Both directions stay inside
    the same tenant and project; a task shared by separate topics is not lineage.
    """
    agenda = tables.meeting_agenda_items
    scoped = (
        select(agenda.c.id, agenda.c.meeting_id, agenda.c.carried_from_item_id)
        .join(
            tables.meetings,
            (tables.meetings.c.tenant_id == agenda.c.tenant_id)
            & (tables.meetings.c.id == agenda.c.meeting_id),
        )
        .where(agenda.c.tenant_id == tenant_id, tables.meetings.c.project_id == project_id)
        .cte("project_agenda")
    )
    family = (
        select(scoped.c.id.label("target_id"), scoped.c.id, scoped.c.carried_from_item_id)
        .where(scoped.c.meeting_id == meeting_id)
        .cte("represented_agenda", recursive=True)
    )
    return family.union(
        select(family.c.target_id, scoped.c.id, scoped.c.carried_from_item_id).join(
            scoped,
            or_(
                scoped.c.id == family.c.carried_from_item_id,
                scoped.c.carried_from_item_id == family.c.id,
            ),
        )
    )


def _basis(
    connection: Connection, tenant_id: UUID, project_id: UUID, agenda: Any
) -> dict[str, Any]:
    actions = [
        dict(row)
        for row in connection.execute(
            select(tables.tasks)
            .join(
                tables.meeting_agenda_actions,
                (tables.tasks.c.tenant_id == tables.meeting_agenda_actions.c.tenant_id)
                & (tables.tasks.c.id == tables.meeting_agenda_actions.c.task_id),
            )
            .where(
                tables.meeting_agenda_actions.c.tenant_id == tenant_id,
                tables.meeting_agenda_actions.c.agenda_item_id == agenda["id"],
                tables.tasks.c.project_id == project_id,
            )
            .order_by(tables.tasks.c.id)
        ).mappings()
    ]
    source = (
        source_record(
            connection, tenant_id, project_id, agenda["source_kind"], agenda["source_entity_id"]
        )
        if agenda["source_kind"] and agenda["source_entity_id"]
        else None
    )
    source_ready = agenda["source_kind"] is None
    if source is not None:
        source_ready = source["status"] in {
            "task": {"done"},
            "issue": {"closed"},
            "risk": {"closed"},
            "gate": {"approved"},
            "change_request": {"rejected", "cancelled"},
            "finding": {"applied", "rejected"},
            "test_run": {"passed"},
        }.get(agenda["source_kind"], set())
        if agenda["source_kind"] == "task":
            source_ready = source_ready and bool(
                source.get("execution_kind") == "task"
                or (source.get("completion_evidence_ref") or "").strip()
            )
        if agenda["source_kind"] == "decision":
            state = connection.execute(
                select(tables.decisions.c.follow_up_state).where(
                    tables.decisions.c.tenant_id == tenant_id,
                    tables.decisions.c.project_id == project_id,
                    tables.decisions.c.id == agenda["source_entity_id"],
                    tables.decisions.c.historical_source.is_(None),
                )
            ).scalar_one_or_none()
            source_ready = state in {"none", "completed"}
        if agenda["source_kind"] == "forecast":
            # A forecast is discussion evidence, not an executable business object.
            # Explicit closure still requires the reviewed basis, completed actions
            # (or a reasoned no-action confirmation) and the original actor checks.
            source_ready = True
    carried_from = None
    if agenda["carried_from_item_id"]:
        parent = (
            connection.execute(
                select(tables.meeting_agenda_items.c.id, tables.meeting_agenda_items.c.meeting_id)
                .join(
                    tables.meetings,
                    (tables.meetings.c.tenant_id == tables.meeting_agenda_items.c.tenant_id)
                    & (tables.meetings.c.id == tables.meeting_agenda_items.c.meeting_id),
                )
                .where(
                    tables.meetings.c.tenant_id == tenant_id,
                    tables.meetings.c.project_id == project_id,
                    tables.meeting_agenda_items.c.id == agenda["carried_from_item_id"],
                )
            )
            .mappings()
            .one_or_none()
        )
        if parent:
            carried_from = {
                "agenda_id": str(parent["id"]),
                "meeting_id": str(parent["meeting_id"]),
                "href": project_link(project_id, "decisions") + f"&meeting={parent['meeting_id']}",
            }
    plain_agenda = {key: value for key, value in dict(agenda).items() if key != "resolution_status"}
    basis = digest(_plain({"agenda": plain_agenda, "actions": actions, "source": source}))
    reviewed = (
        connection.execute(
            select(
                tables.audit_log.c.context,
                tables.audit_log.c.timestamp,
                tables.users.c.display_name.label("confirmed_by"),
            )
            .join(
                tables.users,
                (tables.users.c.tenant_id == tables.audit_log.c.tenant_id)
                & (tables.users.c.id == tables.audit_log.c.actor_user_id),
            )
            .where(
                tables.audit_log.c.tenant_id == tenant_id,
                tables.audit_log.c.project_id == project_id,
                tables.audit_log.c.entity_id == agenda["meeting_id"],
                tables.audit_log.c.action.in_(("meeting.agenda_closed", "meeting.agenda_reopened")),
                tables.audit_log.c.context["agenda_id"].as_string() == str(agenda["id"]),
            )
            .order_by(tables.audit_log.c.id.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    incomplete = [
        str(task["id"])
        for task in actions
        if task["status"] != "done"
        or (task["kind"] != "task" and not (task["completion_evidence_ref"] or "").strip())
    ]
    closure_current = (
        agenda["resolution_status"] == "closed"
        and reviewed is not None
        and reviewed["context"].get("basis_digest") == basis
        and not incomplete
        and source_ready
    )
    return _plain(
        {
            "agenda": dict(agenda),
            "carried_from": carried_from,
            "basis_digest": basis,
            "source": source,
            "source_ready": source_ready,
            "actions": [
                {**task, "href": project_link(project_id, "work-items", task["id"])}
                for task in actions
            ],
            "incomplete_action_ids": incomplete,
            "closure_current": closure_current,
            "review": {
                "reason": reviewed["context"].get("reason"),
                "basis_digest": reviewed["context"].get("basis_digest"),
                "timestamp": reviewed["timestamp"],
                "confirmed_by": reviewed["confirmed_by"],
            }
            if reviewed
            else None,
        }
    )


def responsibility_history_statement(
    tenant_id: UUID,
    project_id: UUID,
    meeting_id: UUID,
    agenda_id: UUID,
    before_id: int | None = None,
) -> Any:
    a = tables.audit_log
    statement = select(a.c.id, a.c.timestamp, a.c.context).where(
        a.c.tenant_id == tenant_id,
        a.c.project_id == project_id,
        a.c.entity_id == meeting_id,
        a.c.action == "meeting.agenda_reassign",
        a.c.context["agenda_id"].as_string() == str(agenda_id),
    )
    if before_id is not None:
        statement = statement.where(a.c.id < before_id)
    return statement.order_by(a.c.id.desc()).limit(21)


def responsibility_members(c: Connection, tenant: UUID, project: UUID) -> list[dict[str, Any]]:
    return [
        m
        for m in MeetingPreparationService.members(c, tenant, project)
        if is_allowed(Role(m["role"]), Action.MEETING_VIEW)
    ]


class MeetingFollowupService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def responsibility_history(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        meeting_id: UUID,
        agenda_id: UUID,
        actor_id: UUID,
        before_id: int | None = None,
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            KnowledgeCorrectionService._authorize(
                c, tenant_id, actor_id, project_id, Action.MEETING_VIEW
            )
            MeetingService._get(
                c, tenant_id=tenant_id, project_id=project_id, meeting_id=meeting_id
            )
            _agenda(c, tenant_id, meeting_id, agenda_id)
            rows = (
                c.execute(
                    responsibility_history_statement(
                        tenant_id, project_id, meeting_id, agenda_id, before_id
                    )
                )
                .mappings()
                .all()
            )
            return _plain(
                {
                    "items": [dict(row) for row in rows[:20]],
                    "next_before_id": rows[19]["id"] if len(rows) > 20 else None,
                }
            )

    def review_candidates(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        meeting_id: UUID,
        actor_id: UUID,
        cursor: UUID | None = None,
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(
                isolation_level="REPEATABLE READ"
            ) as connection,
            connection.begin(),
        ):
            KnowledgeCorrectionService._authorize(
                connection, tenant_id, actor_id, project_id, Action.MEETING_VIEW
            )
            target = MeetingService._get(
                connection, tenant_id=tenant_id, project_id=project_id, meeting_id=meeting_id
            )
            agenda = tables.meeting_agenda_items
            meetings = tables.meetings
            eligible = (
                select(
                    agenda,
                    meetings.c.title.label("meeting_title"),
                    meetings.c.scheduled_start_at.label("meeting_start"),
                )
                .join(
                    meetings,
                    (meetings.c.tenant_id == agenda.c.tenant_id)
                    & (meetings.c.id == agenda.c.meeting_id),
                )
                .where(
                    agenda.c.tenant_id == tenant_id,
                    meetings.c.project_id == project_id,
                    meetings.c.id != meeting_id,
                    meetings.c.scheduled_start_at <= target.scheduled_start_at,
                    meetings.c.status.in_(("in_progress", "completed")),
                    meetings.c.deleted_at.is_(None),
                    meetings.c.archived_at.is_(None),
                )
            )
            query = eligible
            if cursor is not None:
                anchor = (
                    connection.execute(eligible.where(agenda.c.id == cursor))
                    .mappings()
                    .one_or_none()
                )
                if anchor is None:
                    raise KnowledgeVersionError("历史会议已变化，请重新刷新待复查事项")
                query = query.where(
                    tuple_(agenda.c.created_at, agenda.c.id)
                    < tuple_(anchor["created_at"], anchor["id"])
                )
            represented = _represented(tenant_id, project_id, meeting_id)
            rows = (
                connection.execute(
                    query.order_by(agenda.c.created_at.desc(), agenda.c.id.desc()).limit(26)
                )
                .mappings()
                .all()
            )
            targets: dict[UUID, UUID] = {}
            for match in connection.execute(
                select(represented.c.id, represented.c.target_id)
                .where(represented.c.id.in_([row["id"] for row in rows[:25]]))
                .order_by(represented.c.target_id)
            ):
                targets.setdefault(match.id, match.target_id)
            target_tasks: dict[UUID, set[str]] = {}
            for linked in connection.execute(
                select(
                    tables.meeting_agenda_actions.c.agenda_item_id,
                    tables.meeting_agenda_actions.c.task_id,
                ).where(
                    tables.meeting_agenda_actions.c.tenant_id == tenant_id,
                    tables.meeting_agenda_actions.c.project_id == project_id,
                    tables.meeting_agenda_actions.c.agenda_item_id.in_(set(targets.values())),
                )
            ):
                target_tasks.setdefault(linked.agenda_item_id, set()).add(str(linked.task_id))
            items = []
            for row in rows[:25]:
                basis = _basis(
                    connection,
                    tenant_id,
                    project_id,
                    {column.name: row[column.name] for column in agenda.columns},
                )
                if basis["closure_current"]:
                    continue
                represented_target = targets.get(row["id"])
                inherited_tasks = (
                    target_tasks.get(represented_target, set())
                    if represented_target is not None
                    else set()
                )
                missing_actions = [
                    task["id"] for task in basis["actions"] if task["id"] not in inherited_tasks
                ]
                if represented_target is not None and not missing_actions:
                    continue
                reasons = []
                if represented_target is not None:
                    reasons.append(f"已有承接议题，另有{len(missing_actions)}项行动尚未同步")
                if row["resolution_status"] == "closed":
                    reasons.append("原闭环依据已变化")
                if basis["incomplete_action_ids"]:
                    reasons.append(f"还有{len(basis['incomplete_action_ids'])}项行动未完成")
                if not basis["source_ready"]:
                    reasons.append("业务来源仍需核对完成条件")
                if not reasons:
                    reasons.append("尚未具名确认本议题闭环")
                items.append(
                    {
                        **basis,
                        "meeting_title": row["meeting_title"],
                        "meeting_start": row["meeting_start"],
                        "reasons": reasons,
                        "represented_agenda_id": represented_target,
                        "href": project_link(project_id, "decisions")
                        + f"&meeting={row['meeting_id']}",
                    }
                )
            return _plain(
                {
                    "items": items,
                    "scanned_count": min(25, len(rows)),
                    "next_cursor": rows[24]["id"] if len(rows) > 25 else None,
                    "editable": target.status in {"scheduled", "in_progress"}
                    and target.archived_at is None
                    and target.deleted_at is None,
                }
            )

    def get(
        self, *, tenant_id: UUID, project_id: UUID, meeting_id: UUID, actor_id: UUID
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(
                isolation_level="REPEATABLE READ"
            ) as connection,
            connection.begin(),
        ):
            KnowledgeCorrectionService._authorize(
                connection, tenant_id, actor_id, project_id, Action.MEETING_VIEW
            )
            meeting = MeetingService._get(
                connection, tenant_id=tenant_id, project_id=project_id, meeting_id=meeting_id
            )
            agendas = connection.execute(
                select(tables.meeting_agenda_items)
                .where(
                    tables.meeting_agenda_items.c.tenant_id == tenant_id,
                    tables.meeting_agenda_items.c.meeting_id == meeting_id,
                )
                .order_by(tables.meeting_agenda_items.c.position)
            ).mappings()
            items = [_basis(connection, tenant_id, project_id, item) for item in agendas]
            owner_ids = [
                UUID(item["agenda"]["owner_user_id"])
                for item in items
                if item["agenda"]["owner_user_id"]
            ]
            owner_names = {
                str(r.id): r.display_name
                for r in connection.execute(
                    select(tables.users.c.id, tables.users.c.display_name).where(
                        tables.users.c.tenant_id == tenant_id, tables.users.c.id.in_(owner_ids)
                    )
                )
            }
            for item in items:
                item["owner_name"] = owner_names.get(item["agenda"]["owner_user_id"])
            # Display candidate origin after closure comparison; keep old basis digests stable.
            action_ids = [UUID(a["id"]) for item in items for a in item["actions"]]
            origins = dict(
                connection.execute(
                    select(
                        tables.meeting_agenda_actions.c.task_id,
                        tables.meeting_agenda_actions.c.source_finding_id,
                    ).where(
                        tables.meeting_agenda_actions.c.tenant_id == tenant_id,
                        tables.meeting_agenda_actions.c.project_id == project_id,
                        tables.meeting_agenda_actions.c.task_id.in_(action_ids),
                        tables.meeting_agenda_actions.c.source_finding_id.is_not(None),
                    )
                )
                .tuples()
                .all()
            )
            for item in items:
                for task in item["actions"]:
                    task["source_finding_id"] = origins.get(UUID(task["id"]))

            targets = [
                dict(row)
                for row in connection.execute(
                    select(tables.meetings.c.id, tables.meetings.c.title)
                    .where(
                        tables.meetings.c.tenant_id == tenant_id,
                        tables.meetings.c.project_id == project_id,
                        tables.meetings.c.id != meeting_id,
                        tables.meetings.c.scheduled_start_at >= meeting.scheduled_start_at,
                        tables.meetings.c.status.in_(("scheduled", "in_progress")),
                        tables.meetings.c.deleted_at.is_(None),
                        tables.meetings.c.archived_at.is_(None),
                    )
                    .order_by(tables.meetings.c.scheduled_start_at)
                ).mappings()
            ]
            tasks = [
                dict(row)
                for row in connection.execute(
                    select(tables.tasks.c.id, tables.tasks.c.title, tables.tasks.c.status)
                    .where(
                        tables.tasks.c.tenant_id == tenant_id,
                        tables.tasks.c.project_id == project_id,
                    )
                    .order_by(tables.tasks.c.updated_at.desc())
                    .limit(200)
                ).mappings()
            ]
            orphan = [
                dict(row)
                for row in connection.execute(
                    select(tables.tasks.c.id, tables.tasks.c.title).where(
                        tables.tasks.c.tenant_id == tenant_id,
                        tables.tasks.c.project_id == project_id,
                        tables.tasks.c.kind == "meeting_action",
                        tables.tasks.c.source_entity == "meetings",
                        tables.tasks.c.source_entity_id == meeting_id,
                        ~select(tables.meeting_agenda_actions.c.id)
                        .where(
                            tables.meeting_agenda_actions.c.tenant_id == tenant_id,
                            tables.meeting_agenda_actions.c.task_id == tables.tasks.c.id,
                        )
                        .exists(),
                    )
                ).mappings()
            ]
            return _plain(
                {
                    "editable": meeting.status in {"in_progress", "completed"}
                    and not meeting.archived_at
                    and not meeting.deleted_at,
                    "items": items,
                    "responsibility_members": responsibility_members(
                        connection, tenant_id, project_id
                    ),
                    "targets": targets,
                    "tasks": tasks,
                    "unassigned_actions": orphan,
                    "members": [
                        member
                        for member in MeetingPreparationService.members(
                            connection, tenant_id, project_id
                        )
                        if member["role"]
                        in {"owner", "admin", "project_manager", "engineer", "quality"}
                    ],
                }
            )

    def act(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        meeting_id: UUID,
        agenda_id: UUID,
        actor_id: UUID,
        request_id: UUID,
        expected_basis: str,
        action: str,
        reason: str,
        task_id: UUID | None = None,
        target_meeting_id: UUID | None = None,
        title: str | None = None,
        assignee_id: UUID | None = None,
        due_date: date | None = None,
        expected_output: str | None = None,
        no_action_required: bool = False,
        connection: Connection | None = None,
        source_finding_id: UUID | None = None,
        owner_user_id: UUID | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if (
            action not in {"create_action", "link_action", "close", "reopen", "carry", "reassign"}
            or not 1 <= len(reason.strip()) <= 3000
        ):
            raise MeetingStateError("请选择办理方式并填写理由")
        signature = digest(
            _plain(
                dict(
                    action=action,
                    agenda_id=agenda_id,
                    expected_basis=expected_basis,
                    reason=reason.strip(),
                    task_id=task_id,
                    target_meeting_id=target_meeting_id,
                    title=title,
                    assignee_id=assignee_id,
                    due_date=due_date,
                    expected_output=expected_output,
                    no_action_required=no_action_required,
                    **({"owner_user_id": owner_user_id} if owner_user_id else {}),
                    **({"source_finding_id": source_finding_id} if source_finding_id else {}),
                )
            )
        )
        with (
            nullcontext(connection) if connection is not None else self.engine.begin()
        ) as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise MeetingNotFoundError
            KnowledgeCorrectionService._authorize(
                connection, tenant_id, actor_id, project_id, Action.MEETING_MANAGE
            )
            if action in {"create_action", "link_action"}:
                KnowledgeCorrectionService._authorize(
                    connection, tenant_id, actor_id, project_id, Action.WORK_ITEM_EDIT
                )
            meeting = MeetingService._get(
                connection, tenant_id=tenant_id, project_id=project_id, meeting_id=meeting_id
            )
            event_id = f"meeting:{meeting_id}:followup:{request_id}"
            receipt = (
                connection.execute(
                    select(tables.audit_log).where(
                        tables.audit_log.c.tenant_id == tenant_id,
                        tables.audit_log.c.event_id == event_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if receipt:
                if (
                    receipt["actor_user_id"] != actor_id
                    or receipt["context"].get("request_digest") != signature
                ):
                    raise KnowledgeVersionError("本请求已用于其他会后办理")
                return dict(receipt["context"]["result"])
            if (
                meeting.status not in {"in_progress", "completed"}
                or meeting.archived_at
                or meeting.deleted_at
            ):
                raise MeetingStateError("仅已开始或已结束且未归档的会议可办理会后事项")
            agenda = _agenda(connection, tenant_id, meeting_id, agenda_id)
            basis = _basis(connection, tenant_id, project_id, agenda)
            if basis["basis_digest"] != expected_basis:
                raise KnowledgeVersionError("议题、来源或行动已变化，请刷新后核对")
            now = now or datetime.now(UTC)
            result: dict[str, Any] = {"action": action, "agenda_id": str(agenda_id)}
            event_action = "agenda_" + action
            responsibility_receipt: dict[str, Any] = {}
            if action == "reassign":
                if agenda["resolution_status"] != "open":
                    raise MeetingStateError(
                        "仅开放议题可调整负责人；已转后续会议的议题请在承接会议办理"
                    )
                if owner_user_id is None or owner_user_id == agenda["owner_user_id"]:
                    raise MeetingStateError("请选择不同的具名议题负责人")
                if owner_user_id not in {
                    m["id"] for m in responsibility_members(connection, tenant_id, project_id)
                }:
                    raise MeetingStateError("接手人须为可读取会议的有效项目成员")
                names = {
                    str(r.id): r.display_name
                    for r in connection.execute(
                        select(tables.users.c.id, tables.users.c.display_name).where(
                            tables.users.c.tenant_id == tenant_id,
                            tables.users.c.id.in_(
                                [actor_id, owner_user_id, agenda["owner_user_id"]]
                            ),
                        )
                    )
                }
                connection.execute(
                    tables.meeting_agenda_items.update()
                    .where(
                        tables.meeting_agenda_items.c.tenant_id == tenant_id,
                        tables.meeting_agenda_items.c.meeting_id == meeting_id,
                        tables.meeting_agenda_items.c.id == agenda_id,
                    )
                    .values(owner_user_id=owner_user_id)
                )
                after = _agenda(connection, tenant_id, meeting_id, agenda_id)
                responsibility_receipt = {
                    "before_agenda": _plain(agenda),
                    "after_agenda": _plain(after),
                    "people": names,
                    "actor_user_id": str(actor_id),
                    "request_id": str(request_id),
                }
                result["owner_user_id"] = str(owner_user_id)
            elif action in {"create_action", "link_action"}:
                if basis["closure_current"]:
                    raise MeetingStateError("请先重新打开议题，再添加行动")
                if action == "create_action":
                    if (
                        not title
                        or not title.strip()
                        or len(title) > 512
                        or assignee_id is None
                        or due_date is None
                        or not (expected_output or "").strip()
                    ):
                        raise MeetingStateError("请核对行动标题、具名负责人、日期和完成标准")
                    task = TaskService(self.engine).create(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        actor_user_id=actor_id,
                        draft=TaskDraft(
                            stage_id=None,
                            parent_task_id=None,
                            assignee_user_id=assignee_id,
                            title=title.strip(),
                            description=reason.strip(),
                            priority="medium",
                            start_date=None,
                            due_date=due_date,
                            dependency_task_ids=(),
                            kind="meeting_action",
                            source_entity_id=meeting_id,
                            expected_output=expected_output,
                        ),
                        connection=connection,
                    )
                    task_id = task.id
                else:
                    if (
                        task_id is None
                        or not connection.execute(
                            select(tables.tasks.c.id).where(
                                tables.tasks.c.tenant_id == tenant_id,
                                tables.tasks.c.project_id == project_id,
                                tables.tasks.c.id == task_id,
                            )
                        ).first()
                    ):
                        raise MeetingStateError("请选择当前项目的实际任务")
                existing = connection.execute(
                    select(tables.meeting_agenda_actions.c.id).where(
                        tables.meeting_agenda_actions.c.tenant_id == tenant_id,
                        tables.meeting_agenda_actions.c.agenda_item_id == agenda_id,
                        tables.meeting_agenda_actions.c.task_id == task_id,
                    )
                ).scalar_one_or_none()
                if existing is None:
                    connection.execute(
                        tables.meeting_agenda_actions.insert().values(
                            id=uuid4(),
                            tenant_id=tenant_id,
                            project_id=project_id,
                            meeting_id=meeting_id,
                            agenda_item_id=agenda_id,
                            task_id=task_id,
                            created_by_user_id=actor_id,
                            request_id=request_id,
                            relation_kind="created" if action == "create_action" else "linked",
                            source_finding_id=source_finding_id,
                            created_at=now,
                        )
                    )
                result["task_id"] = str(task_id)
            elif action == "close":
                if basis["incomplete_action_ids"] or not basis["source_ready"]:
                    raise MeetingStateError("关联行动或业务来源仍有未办事项，不能确认本议题闭环")
                if not basis["actions"] and not no_action_required:
                    raise MeetingStateError(
                        "没有关联行动时，请明确确认本议题无需新增行动并填写依据"
                    )
                connection.execute(
                    tables.meeting_agenda_items.update()
                    .where(
                        tables.meeting_agenda_items.c.id == agenda_id,
                        tables.meeting_agenda_items.c.tenant_id == tenant_id,
                    )
                    .values(resolution_status="closed")
                )
                event_action = "agenda_closed"
            elif action == "reopen":
                connection.execute(
                    tables.meeting_agenda_items.update()
                    .where(
                        tables.meeting_agenda_items.c.id == agenda_id,
                        tables.meeting_agenda_items.c.tenant_id == tenant_id,
                    )
                    .values(resolution_status="open")
                )
                event_action = "agenda_reopened"
            else:
                if (
                    target_meeting_id is None
                    or target_meeting_id == meeting_id
                    or basis["closure_current"]
                ):
                    raise MeetingStateError("请选择后续会议及仍需复查的议题")
                target = MeetingService._get(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    meeting_id=target_meeting_id,
                )
                if (
                    target.status not in {"scheduled", "in_progress"}
                    or target.archived_at
                    or target.deleted_at
                ):
                    raise MeetingStateError("后续会议已不可修改")
                if target.scheduled_start_at < meeting.scheduled_start_at:
                    raise MeetingStateError("承接会议不能早于原会议")
                represented = _represented(tenant_id, project_id, target_meeting_id)
                prior = connection.execute(
                    select(represented.c.target_id)
                    .where(represented.c.id == agenda_id)
                    .order_by(represented.c.target_id)
                    .limit(1)
                ).scalar_one_or_none()
                if prior is None:
                    target_items = (
                        connection.execute(
                            select(tables.meeting_agenda_items.c.position).where(
                                tables.meeting_agenda_items.c.tenant_id == tenant_id,
                                tables.meeting_agenda_items.c.meeting_id == target_meeting_id,
                            )
                        )
                        .scalars()
                        .all()
                    )
                    if len(target_items) >= 100:
                        raise MeetingStateError("后续会议议程已满，请选择其他会议")
                    prior = uuid4()
                    members = {
                        row["id"]
                        for row in MeetingPreparationService.members(
                            connection, tenant_id, project_id
                        )
                    }
                    connection.execute(
                        tables.meeting_agenda_items.insert().values(
                            id=prior,
                            tenant_id=tenant_id,
                            meeting_id=target_meeting_id,
                            position=max(target_items, default=0) + 1,
                            title=agenda["title"],
                            item_kind="review",
                            detail=reason.strip(),
                            owner_user_id=agenda["owner_user_id"]
                            if agenda["owner_user_id"] in members
                            else None,
                            source_kind=agenda["source_kind"],
                            source_entity_id=agenda["source_entity_id"],
                            source_digest=agenda["source_digest"],
                            carried_from_item_id=agenda_id,
                            resolution_status="open",
                            created_at=now,
                        )
                    )
                for task in basis["actions"]:
                    connection.execute(
                        insert(tables.meeting_agenda_actions)
                        .values(
                            id=uuid4(),
                            tenant_id=tenant_id,
                            project_id=project_id,
                            meeting_id=target_meeting_id,
                            agenda_item_id=prior,
                            task_id=UUID(task["id"]),
                            created_by_user_id=actor_id,
                            request_id=uuid4(),
                            relation_kind="carried",
                            created_at=now,
                        )
                        .on_conflict_do_nothing(constraint="uq_meeting_agenda_task")
                    )
                MeetingService._emit(
                    connection,
                    tenant_id=tenant_id,
                    actor_user_id=actor_id,
                    record=target,
                    action="agenda_carried_in",
                    before=target,
                    occurred_at=now,
                    event_id=event_id + ":target",
                    audit_context={
                        "source_meeting_id": str(meeting_id),
                        "source_agenda_id": str(agenda_id),
                        "target_agenda_id": str(prior),
                        "reason": reason.strip(),
                        "basis_digest": expected_basis,
                    },
                )
                connection.execute(
                    tables.meeting_agenda_items.update()
                    .where(
                        tables.meeting_agenda_items.c.tenant_id == tenant_id,
                        tables.meeting_agenda_items.c.id == agenda_id,
                    )
                    .values(resolution_status="carried_over")
                )
                result.update(target_meeting_id=str(target_meeting_id), target_agenda_id=str(prior))
            MeetingService._emit(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_id,
                record=meeting,
                action=event_action,
                before=meeting,
                occurred_at=now,
                event_id=event_id,
                audit_context={
                    "agenda_id": str(agenda_id),
                    "request_digest": signature,
                    "basis_digest": expected_basis,
                    "reason": reason.strip(),
                    "no_action_required": no_action_required,
                    "result": result,
                    "reviewed_basis": basis,
                    **responsibility_receipt,
                },
            )
            return result
