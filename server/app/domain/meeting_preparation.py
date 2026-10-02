"""Project-bound meeting templates, live exceptions, agenda and roster preparation."""

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, case, delete, select

from app.auth.roles import Action
from app.db.schema import tables
from app.domain import meeting_forecasts
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.knowledge_push import KnowledgeVersionError
from app.domain.meetings import (
    ACTIVE_STATUSES,
    MeetingNotFoundError,
    MeetingScopeError,
    MeetingService,
    MeetingStateError,
)
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.task_preparation import project_link

TEMPLATES: dict[str, dict[str, Any]] = {
    "weekly": {
        "label": "周会",
        "topics": ["上次行动执行复查", "本周逾期与阻塞", "待决策事项与责任确认"],
        "disciplines": ["项目负责人", "相关任务负责人"],
    },
    "material": {
        "label": "物料会",
        "topics": ["物料相关问题复查", "替代方案与证据缺项", "供应风险与责任确认"],
        "disciplines": ["采购", "SQE", "工程负责人"],
    },
    "special": {
        "label": "专项会",
        "topics": ["专项范围与当前证据", "未解决问题与方案", "决定、行动与复查条件"],
        "disciplines": ["专题负责人", "相关专业"],
    },
    "technical_review": {
        "label": "技术评审",
        "topics": ["设计输入与版本核对", "技术风险与验证缺项", "结论边界及后续行动"],
        "disciplines": ["ID", "MD", "EE", "FW", "DQE"],
    },
    "decision_checkpoint": {
        "label": "决策检查点",
        "topics": ["关卡条件与未闭环事项", "方案及取舍依据", "待批准事项与执行责任"],
        "disciplines": ["产品负责人", "项目负责人", "DQE"],
    },
    "pilot_review": {
        "label": "试制复盘",
        "topics": ["试制问题与实际结果", "工艺、质量与供应缺项", "下一批改进及验证责任"],
        "disciplines": ["IE", "DQE", "SQE", "制造负责人"],
    },
    "project_retrospective": {
        "label": "项目复盘",
        "topics": ["目标与实际结果对照", "有效做法、失败及适用条件", "改进行动与可复用经验"],
        "disciplines": ["产品负责人", "项目负责人", "相关专业"],
    },
}
SOURCE_TABLES = {
    "task": (tables.tasks, "title", "work-items"),
    "issue": (tables.issues, "title", "work-items"),
    "risk": (tables.risks, "title", "work-items"),
    "decision": (tables.decisions, "title", "decisions"),
    "gate": (tables.gates, "name", "gates"),
    "change_request": (tables.engineering_change_requests, "title", "engineering"),
    "finding": (tables.findings, "title", "overview"),
    "test_run": (tables.test_runs, "run_number", "quality"),
}


def source_record(
    connection: Connection,
    tenant_id: UUID,
    project_id: UUID,
    kind: str,
    source_id: UUID,
    *,
    lock: bool = False,
) -> dict[str, Any] | None:
    if kind == "forecast":
        return meeting_forecasts.source_record(connection, tenant_id, project_id, source_id)
    spec = SOURCE_TABLES.get(kind)
    if spec is None:
        return None
    table = spec[0]
    query = select(table).where(
        table.c.tenant_id == tenant_id, table.c.project_id == project_id, table.c.id == source_id
    )
    if kind == "issue" and lock:
        query = query.where(table.c.withdrawn_at.is_(None))
    if kind == "risk":
        query = query.where(table.c.draft_state == "confirmed")
    row = connection.execute(query.with_for_update() if lock else query).mappings().one_or_none()
    if row is None:
        return None
    value = _source_value(row, kind, project_id)
    if kind == "issue":
        from app.domain.material_schedule import meeting_summary

        material = meeting_summary(connection, tenant_id, project_id, [source_id]).get(source_id)
        if material:
            value = _material_value(value, material)
    return value


def _material_value(value: dict[str, Any], material: dict[str, Any]) -> dict[str, Any]:
    return {
        **value,
        "summary": material["summary"],
        "material_review_ready": material["material_review_ready"],
        "digest": digest({"business": value["digest"], "material": material["digest"]}),
    }


def _source_value(row: Any, kind: str, project_id: UUID) -> dict[str, Any]:
    _, title_column, tab = SOURCE_TABLES[kind]
    source_id = row["id"]
    value = _plain(dict(row))
    return {
        "kind": kind,
        "id": str(source_id),
        "title": f"测试执行 #{row['run_number']}"
        if kind == "test_run"
        else str(row.get(title_column) or kind),
        "status": str(row.get("status", "")),
        "execution_kind": row.get("kind") if kind == "task" else None,
        "completion_evidence_ref": row.get("completion_evidence_ref") if kind == "task" else None,
        "priority": str(row.get("severity") or row.get("priority") or ""),
        "expertise": (
            {
                "engineering": ["相关工程专业"],
                "quality": ["DQE"],
                "supplier": ["SQE"],
                "test_failure": ["DQE", "相关工程专业"],
                "certification": ["认证负责人", "DQE"],
            }.get(row.get("issue_type"), [])
            + (["项目负责人"] if row.get("severity") in {"high", "critical"} else [])
        )
        if kind == "issue"
        else [],
        "digest": digest(value),
        "href": project_link(project_id, tab, source_id),
        "owner_user_id": str(row.get("assignee_user_id") or row.get("owner_user_id"))
        if row.get("assignee_user_id") or row.get("owner_user_id")
        else None,
    }


def preparation_digest(connection: Connection, tenant_id: UUID, meeting_id: UUID) -> str:
    meeting = MeetingService._get(connection, tenant_id=tenant_id, meeting_id=meeting_id)
    participants = [
        dict(row)
        for row in connection.execute(
            select(tables.meeting_participants)
            .where(
                tables.meeting_participants.c.tenant_id == tenant_id,
                tables.meeting_participants.c.meeting_id == meeting_id,
            )
            .order_by(tables.meeting_participants.c.user_id)
        ).mappings()
    ]
    agenda = [
        asdict(item)
        for item in MeetingService._agenda(connection, tenant_id=tenant_id, meeting_id=meeting_id)
    ]
    return digest(
        _plain({"meeting": asdict(meeting), "participants": participants, "agenda": agenda})
    )


def write_agenda(
    connection: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    meeting_id: UUID,
    items: list[dict[str, Any]],
    now: datetime,
) -> None:
    if len(items) > 100:
        raise MeetingStateError("议程最多100项，请按主题拆分会议")
    existing = {
        row["id"]: row
        for row in connection.execute(
            select(tables.meeting_agenda_items).where(
                tables.meeting_agenda_items.c.tenant_id == tenant_id,
                tables.meeting_agenda_items.c.meeting_id == meeting_id,
            )
        ).mappings()
    }
    chosen: set[UUID] = set()
    MeetingService._require_project_members(
        connection,
        tenant_id=tenant_id,
        project_id=project_id,
        user_ids=[item["owner_user_id"] for item in items if item.get("owner_user_id")],
    )
    values = []
    seen_sources: set[tuple[str, UUID]] = set()
    for position, item in enumerate(items, 1):
        item_id = UUID(str(item["id"])) if item.get("id") else uuid4()
        if item_id in chosen or (item.get("id") and item_id not in existing):
            raise KnowledgeVersionError("议题标识已变化，请刷新议程")
        chosen.add(item_id)
        kind, source_id = item.get("source_kind"), item.get("source_entity_id")
        source = None
        if (kind is None) != (source_id is None):
            raise MeetingScopeError("议题来源类型与对象须同时提供")
        if kind:
            source_id = UUID(str(source_id))
            if (kind, source_id) in seen_sources:
                raise MeetingStateError("同一来源不要重复列为议题")
            seen_sources.add((kind, source_id))
            source = source_record(connection, tenant_id, project_id, kind, source_id, lock=True)
            if source is None:
                raise MeetingScopeError("议题来源不存在于当前项目，或该来源类型尚未接入")
            expected = item.get("source_digest")
            if (kind == "forecast" or "material_review_ready" in source) and expected is None:
                raise KnowledgeVersionError("请先读取并核对所选来源版本，再保存议程")
            if expected is not None and expected != source["digest"]:
                raise KnowledgeVersionError("议题来源已变化，请刷新核对后重新装配")
        carried = item.get("carried_from_item_id")
        if carried:
            parent = connection.execute(
                select(tables.meeting_agenda_items.c.id)
                .join(
                    tables.meetings,
                    (tables.meetings.c.tenant_id == tables.meeting_agenda_items.c.tenant_id)
                    & (tables.meetings.c.id == tables.meeting_agenda_items.c.meeting_id),
                )
                .where(
                    tables.meetings.c.tenant_id == tenant_id,
                    tables.meetings.c.project_id == project_id,
                    tables.meeting_agenda_items.c.id == carried,
                    tables.meeting_agenda_items.c.meeting_id != meeting_id,
                )
            ).scalar_one_or_none()
            if parent is None:
                raise MeetingScopeError("上次议题不属于本项目的其他会议")
        if item_id in existing and (kind, source_id, carried) != (
            existing[item_id]["source_kind"],
            existing[item_id]["source_entity_id"],
            existing[item_id]["carried_from_item_id"],
        ):
            linked = connection.execute(
                select(tables.meeting_agenda_actions.c.id)
                .where(
                    tables.meeting_agenda_actions.c.tenant_id == tenant_id,
                    tables.meeting_agenda_actions.c.agenda_item_id == item_id,
                )
                .limit(1)
            ).first()
            inherited = connection.execute(
                select(tables.meeting_agenda_items.c.id)
                .where(
                    tables.meeting_agenda_items.c.tenant_id == tenant_id,
                    tables.meeting_agenda_items.c.carried_from_item_id == item_id,
                )
                .limit(1)
            ).first()
            if linked or inherited:
                raise MeetingStateError(
                    "议题已进入执行或后续复查，不能改写原始出处；请另列修正议题"
                )
        title = str(item.get("title", "")).strip()
        detail = item.get("detail")
        if not 1 <= len(title) <= 256 or (detail is not None and len(detail) > 10000):
            raise MeetingStateError("请填写有效的议题标题与说明")
        values.append(
            dict(
                id=item_id,
                tenant_id=tenant_id,
                meeting_id=meeting_id,
                position=position,
                title=title,
                item_kind=item.get("item_kind", "topic"),
                detail=detail,
                owner_user_id=item.get("owner_user_id"),
                source_kind=kind,
                source_entity_id=source_id,
                source_digest=source["digest"] if source else None,
                carried_from_item_id=carried,
                resolution_status=existing[item_id]["resolution_status"]
                if item_id in existing
                else "open",
                created_at=existing[item_id]["created_at"] if item_id in existing else now,
            )
        )
    removed = set(existing) - chosen
    if removed:
        if connection.execute(
            select(tables.meeting_agenda_actions.c.id)
            .where(
                tables.meeting_agenda_actions.c.tenant_id == tenant_id,
                tables.meeting_agenda_actions.c.agenda_item_id.in_(removed),
            )
            .limit(1)
        ).first():
            raise MeetingStateError("议题已有实际行动关联，请保留执行出处")
        if connection.execute(
            select(tables.meeting_agenda_items.c.id)
            .where(
                tables.meeting_agenda_items.c.tenant_id == tenant_id,
                tables.meeting_agenda_items.c.carried_from_item_id.in_(removed),
            )
            .limit(1)
        ).first():
            raise MeetingStateError("部分议题已被后续会议引用，请保留其历史记录")
        connection.execute(
            delete(tables.meeting_agenda_items).where(
                tables.meeting_agenda_items.c.tenant_id == tenant_id,
                tables.meeting_agenda_items.c.meeting_id == meeting_id,
                tables.meeting_agenda_items.c.id.in_(removed),
            )
        )
    # Move the current positions out of the final range before reordering.
    connection.execute(
        tables.meeting_agenda_items.update()
        .where(
            tables.meeting_agenda_items.c.tenant_id == tenant_id,
            tables.meeting_agenda_items.c.meeting_id == meeting_id,
        )
        .values(position=tables.meeting_agenda_items.c.position + 1000)
    )
    for row in values:
        if row["id"] in existing:
            connection.execute(
                tables.meeting_agenda_items.update()
                .where(
                    tables.meeting_agenda_items.c.tenant_id == tenant_id,
                    tables.meeting_agenda_items.c.id == row["id"],
                )
                .values(**row)
            )
        else:
            connection.execute(tables.meeting_agenda_items.insert().values(**row))


class MeetingPreparationService:
    def __init__(self, engine: Engine):
        self.engine = engine

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
            members = self.members(connection, tenant_id, project_id)
            agenda = []
            existing_agenda = MeetingService._agenda(
                connection, tenant_id=tenant_id, meeting_id=meeting_id
            )
            current_sources: dict[tuple[str, UUID], dict[str, Any]] = {}
            forecast_sources, latest_forecast = meeting_forecasts.sources(
                connection,
                tenant_id,
                project_id,
                [
                    item.source_entity_id
                    for item in existing_agenda
                    if item.source_kind == "forecast" and item.source_entity_id is not None
                ],
            )
            current_sources.update(
                (("forecast", record_id), value) for record_id, value in forecast_sources.items()
            )
            for kind, (table, _, _) in SOURCE_TABLES.items():
                ids = [
                    item.source_entity_id
                    for item in existing_agenda
                    if item.source_kind == kind and item.source_entity_id is not None
                ]
                if ids:
                    for row in connection.execute(
                        select(table).where(
                            table.c.tenant_id == tenant_id,
                            table.c.project_id == project_id,
                            table.c.id.in_(ids),
                        )
                    ).mappings():
                        current_sources[(kind, row["id"])] = _source_value(row, kind, project_id)
            for item in existing_agenda:
                source = (
                    current_sources.get((item.source_kind, item.source_entity_id))
                    if item.source_kind and item.source_entity_id
                    else None
                )
                agenda.append(
                    {
                        **asdict(item),
                        "source": source,
                        "source_current": source is not None
                        and item.source_digest == source["digest"]
                        if item.source_kind
                        else None,
                    }
                )
            now = datetime.now(UTC)
            sources: list[dict[str, Any]] = []
            selections = [
                (
                    "task",
                    select(tables.tasks)
                    .where(
                        tables.tasks.c.status.not_in(("done", "skipped")),
                        tables.tasks.c.due_date < now.date(),
                    )
                    .order_by(tables.tasks.c.due_date, tables.tasks.c.id),
                ),
                (
                    "issue",
                    select(tables.issues)
                    .where(
                        tables.issues.c.status != "closed", tables.issues.c.withdrawn_at.is_(None)
                    )
                    .order_by(
                        case(
                            (tables.issues.c.severity == "critical", 0),
                            (tables.issues.c.severity == "high", 1),
                            (tables.issues.c.severity == "medium", 2),
                            else_=3,
                        ),
                        tables.issues.c.target_date.asc().nulls_last(),
                        tables.issues.c.id,
                    ),
                ),
                (
                    "gate",
                    select(tables.gates)
                    .where(tables.gates.c.status != "approved")
                    .order_by(tables.gates.c.review_due_at.asc().nulls_last()),
                ),
            ]
            for kind, query in selections:
                table = SOURCE_TABLES[kind][0]
                records = (
                    connection.execute(
                        query.where(
                            table.c.tenant_id == tenant_id, table.c.project_id == project_id
                        ).limit(51)
                    )
                    .mappings()
                    .all()
                )
                rows = [_source_value(row, kind, project_id) for row in records[:50]]
                sources.append({"kind": kind, "items": rows, "has_more": len(records) > 50})
            sources.append(
                {
                    "kind": "forecast",
                    "items": [latest_forecast] if latest_forecast else [],
                    "has_more": False,
                }
            )
            from app.domain.material_schedule import meeting_summary

            material_rows = list(
                connection.execute(
                    select(tables.issues)
                    .join(
                        tables.material_exceptions,
                        (tables.material_exceptions.c.tenant_id == tables.issues.c.tenant_id)
                        & (tables.material_exceptions.c.issue_id == tables.issues.c.id),
                    )
                    .where(
                        tables.issues.c.tenant_id == tenant_id,
                        tables.issues.c.project_id == project_id,
                        tables.issues.c.withdrawn_at.is_(None),
                    )
                    .order_by(
                        tables.material_exceptions.c.created_at.desc(),
                        tables.material_exceptions.c.id,
                    )
                    .limit(51)
                ).mappings()
            )
            sources.append(
                {
                    "kind": "material",
                    "items": [
                        _source_value(row, "issue", project_id) for row in material_rows[:50]
                    ],
                    "has_more": len(material_rows) > 50,
                }
            )
            issue_ids = {
                UUID(value["id"])
                for group in sources
                for value in group["items"]
                if value["kind"] == "issue"
            }
            issue_ids.update(
                UUID(item["source"]["id"])
                for item in agenda
                if item["source"] and item["source"]["kind"] == "issue"
            )
            summaries = meeting_summary(connection, tenant_id, project_id, list(issue_ids))
            for group in sources:
                group["items"] = [
                    _material_value(value, summaries[UUID(value["id"])])
                    if value["kind"] == "issue" and UUID(value["id"]) in summaries
                    else value
                    for value in group["items"]
                ]
            for agenda_item in agenda:
                value = agenda_item["source"]
                if value and value["kind"] == "issue" and UUID(value["id"]) in summaries:
                    agenda_item["source"] = _material_value(value, summaries[UUID(value["id"])])
                    agenda_item["source_current"] = (
                        agenda_item["source_digest"] == agenda_item["source"]["digest"]
                    )
            roster = [
                dict(row)
                for row in connection.execute(
                    select(tables.meeting_participants).where(
                        tables.meeting_participants.c.tenant_id == tenant_id,
                        tables.meeting_participants.c.meeting_id == meeting_id,
                    )
                ).mappings()
            ]
            return _plain(
                {
                    "meeting": asdict(meeting),
                    "template": TEMPLATES[meeting.meeting_type],
                    "digest": preparation_digest(connection, tenant_id, meeting_id),
                    "members": members,
                    "participants": roster,
                    "agenda": agenda,
                    "sources": sources,
                    "unavailable": (
                        []
                        if latest_forecast
                        else ["尚未生成正式排程预测；请先应用正式计划并生成预测。"]
                    ),
                }
            )

    @staticmethod
    def members(connection: Connection, tenant_id: UUID, project_id: UUID) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in connection.execute(
                select(tables.users.c.id, tables.users.c.display_name, tables.users.c.role)
                .join(
                    tables.project_members,
                    (tables.project_members.c.tenant_id == tables.users.c.tenant_id)
                    & (tables.project_members.c.user_id == tables.users.c.id),
                )
                .where(
                    tables.users.c.tenant_id == tenant_id,
                    tables.project_members.c.project_id == project_id,
                    tables.users.c.is_active.is_(True),
                )
                .order_by(tables.users.c.display_name)
            ).mappings()
        ]

    def save(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        meeting_id: UUID,
        actor_id: UUID,
        expected_digest: str,
        request_id: UUID,
        organizer_id: UUID,
        participants: list[dict[str, Any]],
        items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        signature = digest(
            _plain(
                dict(
                    expected_digest=expected_digest,
                    organizer_id=organizer_id,
                    participants=participants,
                    items=items,
                )
            )
        )
        with self.engine.begin() as connection:
            if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
                raise MeetingNotFoundError
            KnowledgeCorrectionService._authorize(
                connection, tenant_id, actor_id, project_id, Action.MEETING_MANAGE
            )
            record = MeetingService._get(
                connection, tenant_id=tenant_id, project_id=project_id, meeting_id=meeting_id
            )
            event_id = f"meeting:{meeting_id}:preparation:{request_id}"
            receipt = (
                connection.execute(
                    select(tables.audit_log.c.context, tables.audit_log.c.actor_user_id).where(
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
                    raise KnowledgeVersionError("本请求已用于另一份会前资料")
                return {"replayed": True}
            if record.status not in ACTIVE_STATUSES or record.archived_at or record.deleted_at:
                raise MeetingStateError("会议已经结束、取消或归档，不能再改会前资料")
            if preparation_digest(connection, tenant_id, meeting_id) != expected_digest:
                raise KnowledgeVersionError("会议资料已被修改，请刷新核对后保存")
            before = self._state(connection, tenant_id, meeting_id)
            roster = {item["user_id"]: item["participation"] for item in participants}
            if len(roster) != len(participants) or any(
                value not in {"required", "optional"} for value in roster.values()
            ):
                raise MeetingStateError("请为每位参会人选择必需或可选，组织者单独指定")
            roster[organizer_id] = "organizer"
            if len(roster) > 100:
                raise MeetingStateError("本次参会名单最多100人")
            MeetingService._require_project_members(
                connection, tenant_id=tenant_id, project_id=project_id, user_ids=roster
            )
            now = datetime.now(UTC)
            write_agenda(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                meeting_id=meeting_id,
                items=items,
                now=now,
            )
            table = tables.meeting_participants
            existing = {
                row["user_id"]: row
                for row in connection.execute(
                    select(table).where(
                        table.c.tenant_id == tenant_id, table.c.meeting_id == meeting_id
                    )
                ).mappings()
            }
            connection.execute(
                delete(table).where(
                    table.c.tenant_id == tenant_id,
                    table.c.meeting_id == meeting_id,
                    table.c.user_id.not_in(roster),
                )
            )
            for user_id, participation in roster.items():
                if user_id in existing:
                    connection.execute(
                        table.update()
                        .where(table.c.id == existing[user_id]["id"])
                        .values(participation=participation)
                    )
                else:
                    connection.execute(
                        table.insert().values(
                            id=uuid4(),
                            tenant_id=tenant_id,
                            meeting_id=meeting_id,
                            user_id=user_id,
                            participation=participation,
                            attendance="unknown",
                            added_at=now,
                        )
                    )
            connection.execute(
                tables.meetings.update()
                .where(tables.meetings.c.tenant_id == tenant_id, tables.meetings.c.id == meeting_id)
                .values(organizer_user_id=organizer_id, updated_at=now)
            )
            after = MeetingService._get(connection, tenant_id=tenant_id, meeting_id=meeting_id)
            MeetingService._emit(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_id,
                record=after,
                action="preparation_saved",
                before=record,
                occurred_at=now,
                event_id=event_id,
                audit_context={
                    "request_digest": signature,
                    "before_preparation": before,
                    "after_preparation": self._state(connection, tenant_id, meeting_id),
                },
            )
            return {"replayed": False}

    @staticmethod
    def _state(connection: Connection, tenant_id: UUID, meeting_id: UUID) -> dict[str, Any]:
        return _plain(
            {
                "agenda": [
                    asdict(item)
                    for item in MeetingService._agenda(
                        connection, tenant_id=tenant_id, meeting_id=meeting_id
                    )
                ],
                "participants": [
                    dict(row)
                    for row in connection.execute(
                        select(tables.meeting_participants).where(
                            tables.meeting_participants.c.tenant_id == tenant_id,
                            tables.meeting_participants.c.meeting_id == meeting_id,
                        )
                    ).mappings()
                ],
            }
        )
