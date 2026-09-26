"""Typed project ScheduleNodes backed by existing business records and pinned calendars."""

from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import model_validator
from sqlalchemy import Connection, Engine, select
from sqlalchemy.exc import IntegrityError

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import Contract, Digest, ScheduleNode, ScheduleSource, Text
from app.db.schema import tables
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _plain,
    _role,
    digest,
)
from app.domain.schedule_node_state import certification_status
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

NodeKind = Literal["task", "gate", "build", "test_run", "certification", "tooling", "milestone"]
# Server-owned table, column and policy mapping; never interpolate client table names.
SOURCES = {
    "task": (tables.tasks, "task_id", Action.WORK_ITEM_VIEW),
    "gate": (tables.gates, "gate_id", Action.GATE_VIEW),
    "build": (tables.build_batches, "build_id", Action.PRODUCT_ENGINEERING_VIEW),
    "test_run": (tables.test_runs, "test_run_id", Action.QUALITY_VIEW),
    "certification": (tables.certifications, "certification_id", Action.QUALITY_VIEW),
    "tooling": (tables.tooling_rounds, "tooling_id", Action.PRODUCT_ENGINEERING_VIEW),
}


class NodeDraft(Contract):
    request_id: UUID
    node_kind: NodeKind
    source_id: UUID | None = None
    expected_source_digest: Digest | None = None
    calendar_version_id: UUID
    title: Text | None = None
    completion_criteria: Text | None = None

    @model_validator(mode="after")
    def source_fields(self) -> Self:
        if self.node_kind == "milestone":
            if (
                self.source_id is not None
                or self.expected_source_digest is not None
                or not self.title
                or not self.completion_criteria
            ):
                raise ValueError("独立里程碑须填写名称和完成判据，不绑定其他业务对象")
        elif (
            self.source_id is None
            or self.expected_source_digest is None
            or self.title is not None
            or self.completion_criteria is not None
        ):
            raise ValueError("业务节点须选择实际对象及其当前版本；名称来自原对象")
        return self


def source_title(kind: str, row: Any, test_titles: dict[UUID, str] | None = None) -> str:
    if kind == "task":
        return str(row["title"])
    if kind == "gate":
        return f"{row['code']} · {row['name']}"
    if kind == "build":
        return f"{row['code']} · {row['phase']}"
    if kind == "tooling":
        return f"{row['code']} · {row['round_label']} · {row['title']}"
    if kind == "test_run":
        test_title = (test_titles or {}).get(row["test_case_id"], str(row["test_case_id"]))
        return f"测试 {test_title} · 第 {row['run_number']} 轮"
    return str(row["certificate_number"] or row["certificate_type"])


def project_test_titles(
    connection: Connection, context: AuthContext, project_id: UUID
) -> dict[UUID, str]:
    if not is_allowed(context.user.role, Action.QUALITY_VIEW):
        return {}
    return dict(
        connection.execute(
            select(tables.test_cases.c.id, tables.test_cases.c.title).where(
                tables.test_cases.c.tenant_id == context.tenant.id,
                tables.test_cases.c.project_id == project_id,
            )
        )
        .tuples()
        .all()
    )


def source_executable(kind: str, row: Any) -> bool:
    states = {
        "task": ("todo", "in_progress", "blocked"),
        "gate": ("preparing", "reviewing", "hold"),
        "build": ("planned", "in_progress"),
        "test_run": ("planned", "in_progress"),
        "certification": ("draft",),
        "tooling": ("planned", "in_progress"),
    }
    return row["status"] in states[kind] and (
        kind != "test_run" or row["draft_state"] == "confirmed"
    )


def read_source(
    connection: Connection, context: AuthContext, project_id: UUID, kind: str, source_id: UUID
) -> Any:
    table, _, action = SOURCES[kind]
    _role(context, action)
    row = (
        connection.execute(
            select(table).where(
                table.c.tenant_id == context.tenant.id,
                table.c.project_id == project_id,
                table.c.id == source_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkAccessError("排程来源不存在或不属于当前项目")
    return row


def require_reservable_node(
    connection: Connection, context: AuthContext, project_id: UUID, node_id: UUID
) -> Any:
    node = (
        connection.execute(
            select(tables.schedule_nodes).where(
                tables.schedule_nodes.c.tenant_id == context.tenant.id,
                tables.schedule_nodes.c.project_id == project_id,
                tables.schedule_nodes.c.id == node_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if node is None:
        raise ProductWorkAccessError("排程节点不存在或不属于当前项目")
    kind = node["node_kind"]
    if kind == "milestone":
        raise ProductWorkError("里程碑是完成检查点，请为实际工作或业务轮次预约资源")
    source = read_source(connection, context, project_id, kind, node[SOURCES[kind][1]])
    if not source_executable(kind, source):
        raise ProductWorkError("排程来源已结束或尚未具备执行状态，请先办理原业务对象")
    return node


def list_nodes(
    connection: Connection, context: AuthContext, project_id: UUID
) -> list[dict[str, Any]]:
    nodes = list(
        connection.execute(
            select(tables.schedule_nodes)
            .where(
                tables.schedule_nodes.c.tenant_id == context.tenant.id,
                tables.schedule_nodes.c.project_id == project_id,
            )
            .order_by(tables.schedule_nodes.c.created_at, tables.schedule_nodes.c.id)
        ).mappings()
    )
    sources = {}
    for kind, (table, column, action) in SOURCES.items():
        if is_allowed(context.user.role, action):
            sources[kind] = {
                row["id"]: row
                for row in connection.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.project_id == project_id,
                        table.c.id.in_(
                            [node[column] for node in nodes if node["node_kind"] == kind]
                        ),
                    )
                ).mappings()
            }
    from app.domain.schedule_source_actuals import latest_observations

    actuals = {
        row["node_id"]: _plain(row)
        for row in latest_observations(connection, context.tenant.id, project_id)
    }
    test_titles = project_test_titles(connection, context, project_id)
    result = []
    for node in nodes:
        kind = node["node_kind"]
        if kind == "milestone":
            title, status, reservable = (
                node["title"],
                actuals.get(node["id"], {}).get("source_status", "checkpoint"),
                False,
            )
            source_id = None
        else:
            source_id = node[SOURCES[kind][1]]
            source = sources.get(kind, {}).get(source_id)
            if source is None:
                continue
            title, status, reservable = (
                source_title(kind, source, test_titles),
                source["status"],
                source_executable(kind, source),
            )
            if kind == "certification":
                status = certification_status(source)
        result.append(
            {
                **_plain(node),
                "title": title,
                "source_id": str(source_id) if source_id else None,
                "source_status": status,
                "current_source_digest": digest(
                    _plain(node) if kind == "milestone" else _plain(source)
                ),
                "source_draft_state": source.get("draft_state") if source_id and source else None,
                "replaces_certification_id": str(source["replaces_certification_id"])
                if kind == "certification"
                and source is not None
                and source.get("replaces_certification_id")
                else None,
                "reservable": reservable,
                "actual": actuals.get(node["id"]),
            }
        )
    return result


class ScheduleNodeService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(self, context: AuthContext, project_id: UUID) -> dict[str, Any]:
        from app.domain.resource_reservations import _project

        with self.engine.connect() as connection:
            project = _project(connection, context, project_id)
            nodes = list_nodes(connection, context, project_id)
            registered = {(node["node_kind"], node["source_id"]) for node in nodes}
            choices: list[dict[str, Any]] = []
            truncated: list[str] = []
            test_titles = project_test_titles(connection, context, project_id)
            for kind, (table, _, action) in SOURCES.items():
                if not is_allowed(context.user.role, action):
                    continue
                # Existing sources remain available, including completed records for history.
                rows = list(
                    connection.execute(
                        select(table)
                        .where(
                            table.c.tenant_id == context.tenant.id, table.c.project_id == project_id
                        )
                        .order_by(table.c.created_at.desc(), table.c.id)
                        .limit(1001)
                    ).mappings()
                )
                if len(rows) > 1000:
                    truncated.append(kind)
                choices.extend(
                    {
                        "node_kind": kind,
                        "id": str(row["id"]),
                        "title": source_title(kind, row, test_titles),
                        "status": row["status"],
                        "source_digest": digest(_plain(row)),
                    }
                    for row in rows[:1000]
                    if (kind, str(row["id"])) not in registered
                )
            calendars = list(
                connection.execute(
                    select(tables.work_calendar_versions)
                    .where(tables.work_calendar_versions.c.tenant_id == context.tenant.id)
                    .order_by(
                        tables.work_calendar_versions.c.calendar_id,
                        tables.work_calendar_versions.c.version.desc(),
                    )
                ).mappings()
            )
            observations = tables.schedule_source_observations
            observation_rows = list(
                connection.execute(
                    select(observations)
                    .where(
                        observations.c.tenant_id == context.tenant.id,
                        observations.c.project_id == project_id,
                        observations.c.node_id.in_([UUID(node["id"]) for node in nodes]),
                    )
                    .order_by(observations.c.observed_at.desc(), observations.c.audit_row_id.desc())
                    .limit(501)
                ).mappings()
            )
            return {
                "items": nodes,
                "actual_history": [_plain(row) for row in observation_rows[:500]],
                "has_more_actual_history": len(observation_rows) > 500,
                "sources": choices,
                "truncated_source_kinds": truncated,
                "calendars": [_plain(row) for row in calendars],
                "can_register": is_allowed(context.user.role, Action.PROJECT_EDIT)
                and project["status"] not in ("completed", "archived"),
            }

    def register(self, context: AuthContext, project_id: UUID, draft: NodeDraft) -> dict[str, Any]:
        from app.domain.resource_reservations import _project

        _role(context, Action.PROJECT_EDIT)
        try:
            with self.engine.begin() as connection:
                project = _project(connection, context, project_id, write=True)
                table = tables.schedule_nodes
                fingerprint = digest(
                    {"project_id": str(project_id), **draft.model_dump(mode="json")}
                )
                previous = (
                    connection.execute(
                        select(table).where(
                            table.c.tenant_id == context.tenant.id,
                            table.c.created_by_user_id == context.user.id,
                            table.c.request_id == draft.request_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if previous:
                    if previous["request_digest"] != fingerprint:
                        raise ProductWorkError("请求编号已用于其他节点登记")
                    return _plain(previous)
                if project["status"] in ("completed", "archived"):
                    raise ProductWorkError("已结束项目不能增加排程节点")
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
                    raise ProductWorkError("请选择已发布的日历版本")
                source = None
                values = {}
                if draft.node_kind != "milestone":
                    if draft.source_id is None:
                        raise ProductWorkError("业务排程节点必须关联实际来源")
                    actual = read_source(
                        connection, context, project_id, draft.node_kind, draft.source_id
                    )
                    if digest(_plain(actual)) != draft.expected_source_digest:
                        raise ProductWorkError("业务对象已变化，请刷新后确认当前内容")
                    column = SOURCES[draft.node_kind][1]
                    if connection.execute(
                        select(table.c.id).where(
                            table.c.tenant_id == context.tenant.id,
                            table.c[column] == draft.source_id,
                        )
                    ).first():
                        raise ProductWorkError("该业务对象已有排程节点，请使用现有节点及固定日历")
                    values[column] = draft.source_id
                    source = ScheduleSource(
                        kind=draft.node_kind,
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        ref_id=draft.source_id,
                        as_of=actual["updated_at"],
                        digest=draft.expected_source_digest,
                    )
                node_id = uuid4()
                contract = ScheduleNode(
                    id=node_id,
                    tenant_id=context.tenant.id,
                    project_id=project_id,
                    node_kind=draft.node_kind,
                    source=source,
                    calendar_id=calendar["calendar_id"],
                )
                row = (
                    connection.execute(
                        table.insert()
                        .values(
                            id=node_id,
                            tenant_id=context.tenant.id,
                            project_id=project_id,
                            node_kind=draft.node_kind,
                            calendar_version_id=calendar["id"],
                            contract=contract.model_dump(mode="json"),
                            title=draft.title,
                            completion_criteria=draft.completion_criteria,
                            created_by_user_id=context.user.id,
                            request_id=draft.request_id,
                            request_digest=fingerprint,
                            **values,
                        )
                        .returning(table)
                    )
                    .mappings()
                    .one()
                )
                from app.domain.schedule_source_actuals import replay_source

                replay_source(
                    connection,
                    context.tenant.id,
                    project_id,
                    node_id if draft.node_kind == "milestone" else actual["id"],
                    draft.node_kind,
                    context.user.id,
                )
                EventAuditWriter(
                    connection,
                    tenant_id=context.tenant.id,
                    actor_user_id=context.user.id,
                    project_id=project_id,
                ).record(
                    EventDraft(
                        event_id=f"schedule-node:{node_id}",
                        event_type="SCHEDULE_NODE_REGISTERED",
                        source="planning_service",
                        entity_id=node_id,
                        payload={"node_kind": draft.node_kind, "node_id": str(node_id)},
                    ),
                    AuditDraft(action="schedule_node.register", after_snapshot=_plain(row)),
                )
                return _plain(row)
        except IntegrityError as error:
            raise ProductWorkError("节点登记未生效，请刷新后核对来源、项目和日历") from error
