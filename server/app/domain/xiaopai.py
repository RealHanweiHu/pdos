"""Durable, permission-bound project follow-up. No model calls in scheduling or recovery."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Connection, Engine, select
from sqlalchemy.dialects.postgresql import insert

from app.auth.repository import AuthContext, AuthRepository
from app.auth.roles import Action
from app.contracts.common_objects import WorkCalendar
from app.db.schema import tables
from app.domain.conversations import ConversationAccessError, ConversationError, ConversationService
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.work_calendars import WorkCalendarCalculator


class DelegationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    conversation_id: UUID
    goal: str = Field(min_length=1, max_length=2000)
    calendar_version_id: UUID | None = None
    timezone: str
    working_weekdays: tuple[Annotated[int, Field(ge=0, le=6)], ...] = (0, 1, 2, 3, 4)
    digest_hour: int = Field(default=9, ge=0, le=23)
    expires_at: AwareDatetime | None = None

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (KeyError, ValueError) as error:
            raise ValueError("请使用有效的项目时区") from error
        return value

    @field_validator("working_weekdays")
    @classmethod
    def valid_weekdays(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if not value or len(set(value)) != len(value):
            raise ValueError("请选择不重复的工作日")
        return value


class DelegationState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_version: int = Field(ge=1)
    status: Literal["active", "paused", "stopped"]


class FollowupReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    body: str = Field(min_length=1, max_length=2000)
    checkpoint_at: AwareDatetime | None = None


def next_workday(moment: datetime, calendar: dict[str, Any]) -> datetime:
    definition = WorkCalendar.model_validate(calendar)
    if not definition.working_weekdays:
        raise ConversationError("委托日历必须包含工作日")
    local = moment.astimezone(ZoneInfo(definition.timezone))
    day = WorkCalendarCalculator(definition).shift_workdays(local.date(), 1)
    return datetime.combine(day, local.timetz()).astimezone(UTC)


def progress_digest(task: Any) -> str:
    # Editing a label, date or reminder acknowledgement is not business progress.
    return digest(
        _plain(
            {
                k: task[k]
                for k in (
                    "assignee_user_id",
                    "status",
                    "blocked_reason",
                    "completion_evidence_ref",
                    "completed_at",
                )
            }
        )
    )


def receipt(
    c: Connection, delegation: Any, kind: str, key: str, content: Any, now: datetime
) -> None:
    c.execute(
        insert(tables.xiaopai_receipts)
        .values(
            id=uuid5(delegation["id"], key),
            tenant_id=delegation["tenant_id"],
            project_id=delegation["project_id"],
            delegation_id=delegation["id"],
            kind=kind,
            request_key=key,
            content=_plain(content),
            created_at=now,
        )
        .on_conflict_do_nothing(index_elements=["delegation_id", "request_key"])
    )


class XiaopaiService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def authorize(self, c: Connection, context: AuthContext, project_id: UUID) -> Any:
        ConversationService(self.engine)._authorize(c, context, project_id)
        KnowledgeCorrectionService._authorize(
            c, context.tenant.id, context.user.id, project_id, Action.WORK_ITEM_VIEW
        )
        return (
            c.execute(
                select(tables.projects).where(
                    tables.projects.c.tenant_id == context.tenant.id,
                    tables.projects.c.id == project_id,
                )
            )
            .mappings()
            .one()
        )

    def create(
        self, context: AuthContext, project_id: UUID, command: DelegationCreate
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        if not command.goal.strip() or command.expires_at and command.expires_at <= now:
            raise ConversationError("请填写跟进目标并选择未来的结束时间")
        with self.engine.begin() as c:
            self.authorize(c, context, project_id)
            c.execute(
                select(tables.projects.c.id)
                .where(tables.projects.c.id == project_id)
                .with_for_update()
            )
            conversation = ConversationService(self.engine)._conversation(
                c, context, command.conversation_id
            )
            if (
                conversation["project_id"] != project_id
                or conversation["visibility"] != "project"
                or conversation["archived_at"] is not None
            ):
                raise ConversationError("持续委托需要当前项目的有效共享会话")
            delegation_id = uuid5(context.user.id, "xiaopai:" + str(command.request_id))
            old = (
                c.execute(
                    select(tables.xiaopai_delegations).where(
                        tables.xiaopai_delegations.c.id == delegation_id,
                        tables.xiaopai_delegations.c.tenant_id == context.tenant.id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            request = command.model_dump(mode="json")
            if old:
                original = c.execute(
                    select(tables.xiaopai_receipts.c.content).where(
                        tables.xiaopai_receipts.c.delegation_id == delegation_id,
                        tables.xiaopai_receipts.c.request_key == "created",
                    )
                ).scalar_one()
                if original["request"] != request or old["project_id"] != project_id:
                    raise ConversationError("此请求号已用于不同委托，请先查看原回执")
                return _plain(dict(old))
            if c.execute(
                select(tables.xiaopai_delegations.c.id).where(
                    tables.xiaopai_delegations.c.tenant_id == context.tenant.id,
                    tables.xiaopai_delegations.c.project_id == project_id,
                    tables.xiaopai_delegations.c.status.in_(("active", "paused", "blocked")),
                )
            ).first():
                raise ConversationError("此项目已有持续跟进委托，请在共享委托中继续，避免重复催问")
            if command.calendar_version_id:
                definition = c.execute(
                    select(tables.work_calendar_versions.c.definition).where(
                        tables.work_calendar_versions.c.tenant_id == context.tenant.id,
                        tables.work_calendar_versions.c.id == command.calendar_version_id,
                    )
                ).scalar_one_or_none()
                if definition is None:
                    raise ConversationError("所选工作日历不可用")
                calendar = WorkCalendar.model_validate(definition["calendar"])
            else:
                calendar = WorkCalendar(
                    id=uuid4(),
                    tenant_id=context.tenant.id,
                    version=1,
                    timezone=command.timezone,
                    working_weekdays=command.working_weekdays,
                    hours_per_workday=Decimal(8),
                )
            if not calendar.working_weekdays:
                raise ConversationError("请至少选择一个工作日")
            row = (
                c.execute(
                    tables.xiaopai_delegations.insert()
                    .values(
                        id=delegation_id,
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        conversation_id=command.conversation_id,
                        created_by_user_id=context.user.id,
                        request_id=command.request_id,
                        goal=command.goal.strip(),
                        calendar=calendar.model_dump(mode="json"),
                        digest_hour=command.digest_hour,
                        expires_at=command.expires_at,
                        created_at=now,
                        updated_at=now,
                    )
                    .returning(tables.xiaopai_delegations)
                )
                .mappings()
                .one()
            )
            receipt(
                c,
                row,
                "created",
                "created",
                {"request": request, "actor_user_id": str(context.user.id)},
                now,
            )
            return _plain(dict(row))

    def view(self, context: AuthContext, project_id: UUID) -> dict[str, Any]:
        with self.engine.connect() as c:
            project = self.authorize(c, context, project_id)
            delegations = (
                c.execute(
                    select(tables.xiaopai_delegations)
                    .where(
                        tables.xiaopai_delegations.c.tenant_id == context.tenant.id,
                        tables.xiaopai_delegations.c.project_id == project_id,
                    )
                    .order_by(tables.xiaopai_delegations.c.created_at.desc())
                    .limit(30)
                )
                .mappings()
                .all()
            )
            followups = (
                c.execute(
                    select(tables.xiaopai_followups, tables.tasks.c.title)
                    .join(
                        tables.tasks,
                        tables.tasks.c.id == tables.xiaopai_followups.c.task_id,
                    )
                    .where(
                        tables.xiaopai_followups.c.tenant_id == context.tenant.id,
                        tables.xiaopai_followups.c.project_id == project_id,
                    )
                    .order_by(tables.xiaopai_followups.c.updated_at.desc())
                    .limit(100)
                )
                .mappings()
                .all()
            )
            receipts = (
                c.execute(
                    select(tables.xiaopai_receipts)
                    .where(
                        tables.xiaopai_receipts.c.tenant_id == context.tenant.id,
                        tables.xiaopai_receipts.c.project_id == project_id,
                    )
                    .order_by(tables.xiaopai_receipts.c.created_at.desc())
                    .limit(30)
                )
                .mappings()
                .all()
            )
            calendars = (
                c.execute(
                    select(
                        tables.work_calendar_versions.c.id,
                        tables.work_calendar_versions.c.definition,
                    )
                    .where(
                        tables.work_calendar_versions.c.tenant_id == context.tenant.id,
                    )
                    .limit(100)
                )
                .mappings()
                .all()
            )
            return _plain(
                {
                    "delegations": [
                        dict(r)
                        | {
                            "can_manage": context.user.id
                            in {
                                r["created_by_user_id"],
                                project["owner_user_id"],
                            }
                        }
                        for r in delegations
                    ],
                    "followups": [dict(r) for r in followups],
                    "receipts": [dict(r) for r in receipts],
                    "calendars": [dict(r) for r in calendars],
                }
            )

    def state(
        self, context: AuthContext, project_id: UUID, delegation_id: UUID, command: DelegationState
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        with self.engine.begin() as c:
            project = self.authorize(c, context, project_id)
            row = (
                c.execute(
                    select(tables.xiaopai_delegations)
                    .where(
                        tables.xiaopai_delegations.c.id == delegation_id,
                        tables.xiaopai_delegations.c.tenant_id == context.tenant.id,
                        tables.xiaopai_delegations.c.project_id == project_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ConversationAccessError("委托当前不可用")
            if context.user.id not in {row["created_by_user_id"], project["owner_user_id"]}:
                raise ConversationAccessError("仅委托人或项目负责人可调整持续委托")
            previous = c.execute(
                select(tables.xiaopai_receipts.c.content).where(
                    tables.xiaopai_receipts.c.delegation_id == delegation_id,
                    tables.xiaopai_receipts.c.request_key == str(command.request_id),
                )
            ).scalar_one_or_none()
            request = command.model_dump(mode="json")
            if previous:
                if previous["request"] != request or previous["actor_user_id"] != str(
                    context.user.id
                ):
                    raise ConversationError("此请求号已用于不同的调整")
                return _plain(dict(row))
            if row["version"] != command.expected_version or row["status"] in {
                "completed",
                "stopped",
            }:
                raise ConversationError("委托状态已变化，请刷新；结束的委托不能重新启用")
            if command.status == "active" and row["expires_at"] and row["expires_at"] <= now:
                raise ConversationError("委托已到期，请创建新的委托")
            updated = (
                c.execute(
                    tables.xiaopai_delegations.update()
                    .where(
                        tables.xiaopai_delegations.c.id == delegation_id,
                    )
                    .values(status=command.status, version=row["version"] + 1, updated_at=now)
                    .returning(tables.xiaopai_delegations)
                )
                .mappings()
                .one()
            )
            receipt(
                c,
                row,
                "state",
                str(command.request_id),
                {"request": request, "actor_user_id": str(context.user.id)},
                now,
            )
            return _plain(dict(updated))

    def reply(
        self, context: AuthContext, project_id: UUID, followup_id: UUID, command: FollowupReply
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        with self.engine.begin() as c:
            self.authorize(c, context, project_id)
            # Always lock delegation before its follow-ups, matching the scheduler.
            delegation_id = c.execute(
                select(tables.xiaopai_followups.c.delegation_id).where(
                    tables.xiaopai_followups.c.id == followup_id,
                    tables.xiaopai_followups.c.tenant_id == context.tenant.id,
                    tables.xiaopai_followups.c.project_id == project_id,
                )
            ).scalar_one_or_none()
            if delegation_id is None:
                raise ConversationAccessError("询问当前不可用")
            delegation = (
                c.execute(
                    select(tables.xiaopai_delegations)
                    .where(
                        tables.xiaopai_delegations.c.id == delegation_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            row = (
                c.execute(
                    select(tables.xiaopai_followups)
                    .where(
                        tables.xiaopai_followups.c.id == followup_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            if row["recipient_user_id"] != context.user.id:
                raise ConversationAccessError("请由被询问的负责人回复进展")
            key = "reply:" + str(command.request_id)
            old = c.execute(
                select(tables.xiaopai_receipts.c.content).where(
                    tables.xiaopai_receipts.c.delegation_id == delegation_id,
                    tables.xiaopai_receipts.c.request_key == key,
                )
            ).scalar_one_or_none()
            payload = {
                "followup_id": str(followup_id),
                "actor_user_id": str(context.user.id),
                "request": command.model_dump(mode="json"),
            }
            if old:
                if old != payload:
                    raise ConversationError("原回复请求内容不一致")
                return _plain(dict(row))
            if delegation["status"] != "active" or row["status"] in {"resolved", "cancelled"}:
                raise ConversationError("此跟进已停止或解决，请刷新")
            if not command.body.strip():
                raise ConversationError("请填写进展或阻塞说明")
            checkpoint = command.checkpoint_at or next_workday(now, delegation["calendar"])
            if checkpoint <= now:
                raise ConversationError("下一检查点必须晚于当前时间")
            # Acknowledging repeatedly cannot postpone an already agreed check point.
            if row["checkpoint_at"]:
                checkpoint = min(checkpoint, row["checkpoint_at"])
            updated = (
                c.execute(
                    tables.xiaopai_followups.update()
                    .where(
                        tables.xiaopai_followups.c.id == followup_id,
                    )
                    .values(
                        reply=command.body.strip(),
                        replied_at=now,
                        reply_request_id=command.request_id,
                        checkpoint_at=checkpoint,
                        status="waiting_progress",
                        updated_at=now,
                    )
                    .returning(tables.xiaopai_followups)
                )
                .mappings()
                .one()
            )
            receipt(c, delegation, "reply", key, payload, now)
            return _plain(dict(updated))

    def scan_project(self, tenant_id: UUID, project_id: UUID, now: datetime) -> None:
        with self.engine.connect() as c:
            ids = (
                c.execute(
                    select(tables.xiaopai_delegations.c.id).where(
                        tables.xiaopai_delegations.c.tenant_id == tenant_id,
                        tables.xiaopai_delegations.c.project_id == project_id,
                        tables.xiaopai_delegations.c.status == "active",
                    )
                )
                .scalars()
                .all()
            )
        for delegation_id in ids:
            try:
                self._scan(delegation_id, now)
            except Exception:
                with self.engine.begin() as c:
                    row = (
                        c.execute(
                            select(tables.xiaopai_delegations)
                            .where(
                                tables.xiaopai_delegations.c.id == delegation_id,
                            )
                            .with_for_update()
                        )
                        .mappings()
                        .one()
                    )
                    result = {
                        "completed": [],
                        "in_progress": [],
                        "unfinished": [
                            "本次后台检查失败，未完成本次跟进；原业务记录保留，后台将重新核对后恢复。"
                        ],
                        "checked_at": now.isoformat(),
                    }
                    if row["status"] == "active":
                        c.execute(
                            tables.xiaopai_delegations.update()
                            .where(
                                tables.xiaopai_delegations.c.id == delegation_id,
                            )
                            .values(result=result, updated_at=now)
                        )
                        receipt(c, row, "observation", "failure:" + now.isoformat(), result, now)
                raise

    def _scan(self, delegation_id: UUID, now: datetime) -> None:
        with self.engine.begin() as c:
            d = (
                c.execute(
                    select(tables.xiaopai_delegations)
                    .where(
                        tables.xiaopai_delegations.c.id == delegation_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            if d["status"] != "active":
                return
            context = AuthRepository(self.engine).find_user_context(d["created_by_user_id"])
            try:
                if context is None or context.tenant.id != d["tenant_id"]:
                    raise ConversationAccessError("原委托人当前无权继续")
                project = self.authorize(c, context, d["project_id"])
            except PermissionError:
                c.execute(
                    tables.xiaopai_delegations.update()
                    .where(tables.xiaopai_delegations.c.id == d["id"])
                    .values(
                        status="blocked",
                        result={
                            "completed": [],
                            "unfinished": ["原委托权限已变化，需恢复权限后重新启用"],
                        },
                        updated_at=now,
                        version=d["version"] + 1,
                    )
                )
                return
            if (
                project["status"] in {"completed", "archived"}
                or d["expires_at"]
                and d["expires_at"] <= now
            ):
                c.execute(
                    tables.xiaopai_delegations.update()
                    .where(tables.xiaopai_delegations.c.id == d["id"])
                    .values(status="completed", updated_at=now, version=d["version"] + 1)
                )
                receipt(
                    c,
                    d,
                    "state",
                    "ended",
                    {"reason": "项目结束或委托到期；未完成业务项不自动关闭"},
                    now,
                )
                return
            result: dict[str, Any] = {
                "completed": [],
                "in_progress": [],
                "unfinished": [],
                "forecast": None,
            }
            from app.domain.schedule_forecasts import (
                ForecastDraft,
                RemainingEstimate,
                capture_basis,
                persist_forecast,
            )
            from app.domain.schedule_network import latest_human_estimates

            predicted: dict[UUID, dict[str, Any]] = {}
            try:
                with c.begin_nested():
                    basis = capture_basis(c, d["tenant_id"], d["project_id"])
                    local_basis = {
                        key: value
                        for key, value in basis["basis"].items()
                        if key not in {"external_dependencies", "external_input_digest"}
                    }
                    estimates = latest_human_estimates(
                        c, d["tenant_id"], d["project_id"], local_basis
                    )
                    forecast = persist_forecast(
                        c,
                        d["tenant_id"],
                        d["project_id"],
                        None,
                        ForecastDraft(
                            request_id=uuid5(
                                d["id"],
                                "forecast:"
                                + basis["basis_digest"]
                                + ":"
                                + digest(estimates)
                                + ":"
                                + now.date().isoformat(),
                            ),
                            expected_basis_digest=basis["basis_digest"],
                            estimates={
                                key: RemainingEstimate.model_validate(value)
                                for key, value in estimates.items()
                            },
                            reason="小Pai持续跟进：依据当前事实自动重算预计排程",
                        ),
                        basis,
                        as_of=now,
                        trigger="propagation",
                    )
                    result["forecast"] = {
                        "record_id": forecast["record_id"],
                        "complete": forecast["result"]["complete"],
                        "project_finish": forecast["result"].get("project_finish"),
                        "href": f"/projects?project={d['project_id']}&tab=plan#schedule-forecasts",
                    }
                    nodes = {n["node_key"]: n for n in forecast["result"]["nodes"]}
                    predicted = {
                        UUID(t["task_id"]): nodes[t["node_key"]]
                        for t in basis["basis"]["tasks"]
                        if t.get("task_id") and t["node_key"] in nodes
                    }
                    if not forecast["result"]["complete"]:
                        result["unfinished"].append(
                            "预计排程仍有缺失输入，不能认定全部后置任务已重排"
                        )
                    result["completed"].append("已核对预计排程；原批准计划、承诺与实际日期保持")
            except ProductWorkError as error:
                result["unfinished"].append("预计排程未重算：" + str(error))
            tasks = (
                c.execute(
                    select(tables.tasks).where(
                        tables.tasks.c.tenant_id == d["tenant_id"],
                        tables.tasks.c.project_id == d["project_id"],
                    )
                )
                .mappings()
                .all()
            )
            current = {t["id"]: t for t in tasks}
            followups = (
                c.execute(
                    select(tables.xiaopai_followups).where(
                        tables.xiaopai_followups.c.delegation_id == d["id"],
                        tables.xiaopai_followups.c.status.not_in(("resolved", "cancelled")),
                    )
                )
                .mappings()
                .all()
            )
            active_tasks = set()
            for f in followups:
                task = current.get(f["task_id"])
                status = f["status"]
                changes: dict[str, Any] = {}
                if task is None or task["assignee_user_id"] != f["recipient_user_id"]:
                    status = "cancelled"
                elif task["status"] in {"done", "skipped"}:
                    status = "resolved"
                elif progress_digest(task) != f["source_digest"]:
                    # Changed evidence ends this observation, never the underlying task.
                    status = "resolved"
                else:
                    active_tasks.add(task["id"])
                    if f["delivered_at"] is None:
                        delivered = c.execute(
                            select(tables.reminders.c.fired_at)
                            .where(
                                tables.reminders.c.tenant_id == d["tenant_id"],
                                tables.reminders.c.target_entity_id == f["task_id"],
                                tables.reminders.c.policy_key == "xiaopai_ask",
                                tables.reminders.c.dedupe_key.like(
                                    "xiaopai:" + str(f["id"]) + ":ask%"
                                ),
                                tables.reminders.c.fired_at.is_not(None),
                            )
                            .order_by(tables.reminders.c.fired_at)
                            .limit(1)
                        ).scalar_one_or_none()
                        if delivered:
                            changes = {
                                "delivered_at": delivered,
                                "reply_due_at": next_workday(delivered, d["calendar"]),
                            }
                            status = "waiting_progress" if f["replied_at"] else "waiting_reply"
                    deadline = f["checkpoint_at"] if f["replied_at"] else f["reply_due_at"]
                    if deadline and now >= deadline:
                        status = "no_progress" if f["replied_at"] else "no_reply"
                if changes or status != f["status"]:
                    c.execute(
                        tables.xiaopai_followups.update()
                        .where(tables.xiaopai_followups.c.id == f["id"])
                        .values(**changes, status=status, updated_at=now)
                    )
                if status in {"no_reply", "no_progress"}:
                    result["unfinished"].append(
                        {
                            "task_id": str(f["task_id"]),
                            "reason": "未回复" if status == "no_reply" else "未有效推进",
                            "escalation": "转项目负责人"
                            if project["owner_user_id"]
                            and project["owner_user_id"] != f["recipient_user_id"]
                            else "缺少不同的升级接收人，待配置",
                        }
                    )
                elif status not in {"resolved", "cancelled"} and task is not None:
                    result["in_progress"].append(
                        {
                            "task_id": str(f["task_id"]),
                            "title": task["title"],
                            "action": "等待下一检查点"
                            if status == "waiting_progress"
                            else "等待负责人回复进展与阻塞",
                        }
                    )
            today = now.astimezone(ZoneInfo(d["calendar"]["timezone"])).date()
            for task in tasks:
                if task["status"] in {"done", "skipped"}:
                    continue
                overdue = task["due_date"] is not None and task["due_date"] < today
                node = predicted.get(task["id"], {})
                finish = datetime.fromisoformat(node["finish"]) if node.get("finish") else None
                predicted_late = bool(
                    finish
                    and task["due_date"]
                    and finish.astimezone(ZoneInfo(d["calendar"]["timezone"])).date()
                    > task["due_date"]
                )
                critical_unknown = node.get("critical") is True and bool(
                    node.get("unknown_reasons")
                )
                if (
                    not overdue
                    and task["status"] != "blocked"
                    and not predicted_late
                    and not critical_unknown
                ):
                    continue
                if task["assignee_user_id"] is None:
                    result["unfinished"].append(
                        {"task_id": str(task["id"]), "reason": "缺少负责人，无法询问"}
                    )
                    continue
                from app.domain.xiaopai_reminders import recipient_allowed

                if not c.execute(
                    select(
                        recipient_allowed(task["assignee_user_id"], d["tenant_id"], d["project_id"])
                    )
                ).scalar_one():
                    result["unfinished"].append(
                        {
                            "task_id": str(task["id"]),
                            "title": task["title"],
                            "reason": "负责人当前无项目访问权限，无法询问；请核对成员和责任归属",
                        }
                    )
                    continue
                result["unfinished"].append(
                    {
                        "task_id": str(task["id"]),
                        "title": task["title"],
                        "reason": "任务已延期，原到期日仍需处理"
                        if overdue
                        else "任务阻塞，需协助解除"
                        if task["status"] == "blocked"
                        else "预计晚于原到期日，已提前询问"
                        if predicted_late
                        else "关键任务预计日期未知，需补齐依据",
                    }
                )
                if task["id"] in active_tasks:
                    continue
                source = progress_digest(task)
                fid = uuid5(d["id"], str(task["id"]) + ":" + source)
                c.execute(
                    insert(tables.xiaopai_followups)
                    .values(
                        id=fid,
                        tenant_id=d["tenant_id"],
                        project_id=d["project_id"],
                        delegation_id=d["id"],
                        task_id=task["id"],
                        recipient_user_id=task["assignee_user_id"],
                        source_digest=source,
                        status="pending",
                        requested_at=now,
                        updated_at=now,
                    )
                    .on_conflict_do_nothing(
                        index_elements=["delegation_id", "task_id", "source_digest"]
                    )
                )
                result["in_progress"].append(
                    {
                        "task_id": str(task["id"]),
                        "title": task["title"],
                        "action": "询问负责人进展与阻塞",
                    }
                )
            result["checked_at"] = now.isoformat()
            stable = digest(
                {k: v for k, v in result.items() if k not in {"checked_at", "forecast"}}
            )
            receipt(c, d, "observation", "observation:" + stable, result, now)
            local = now.astimezone(ZoneInfo(d["calendar"]["timezone"]))
            if local.hour >= d["digest_hour"]:
                receipt(c, d, "daily_digest", "daily:" + local.date().isoformat(), result, now)
            c.execute(
                tables.xiaopai_delegations.update()
                .where(tables.xiaopai_delegations.c.id == d["id"])
                .values(result=_plain(result), checked_at=now, updated_at=now)
            )
