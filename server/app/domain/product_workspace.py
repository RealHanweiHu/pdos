"""Human-owned product research before a Project exists."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Connection, Engine, func, or_, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError

from app.auth.repository import AuthContext
from app.auth.roles import Action, Role, is_allowed
from app.contracts.common_objects import ScopeRef, SourceRef
from app.contracts.object_operations import (
    CommandPrecondition,
    ResearchConcludeRequest,
    ResearchStartRequest,
)
from app.contracts.product_records import ResearchTask
from app.db.schema import tables
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class ProductWorkError(ValueError):
    pass


class ProductWorkAccessError(PermissionError):
    pass


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("*", mode="after")
    @classmethod
    def nonblank_list_entries(cls, value: Any) -> Any:
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            if any(not item.strip() or len(item) > 2048 for item in value):
                raise ValueError("列表内容不能为空或超过2048字符")
            return [item.strip() for item in value]
        return value


class MarketSpaceDraft(Input):
    request_id: UUID
    code: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_.:-]+$")
    title: str = Field(min_length=1, max_length=512)
    user_groups: list[str] = Field(min_length=1, max_length=30)
    regions: list[str] = Field(min_length=1, max_length=30)
    use_scenarios: list[str] = Field(min_length=1, max_length=50)
    research_questions: list[str] = Field(min_length=1, max_length=50)


class ResearchDraft(Input):
    request_id: UUID
    product_line_id: UUID | None = None
    owner_user_id: UUID
    question: str = Field(min_length=1, max_length=2048)
    user_groups: list[str] = Field(min_length=1, max_length=30)
    regions: list[str] = Field(min_length=1, max_length=30)
    time_scope: str = Field(min_length=1, max_length=2048)
    method: str = Field(min_length=1, max_length=2048)
    expected_decision: str = Field(min_length=1, max_length=2048)
    stop_conditions: list[str] = Field(min_length=1, max_length=30)


class WorkDraft(Input):
    request_id: UUID
    product_line_id: UUID | None = None
    title: str = Field(min_length=1, max_length=512)
    action_type: Literal[
        "evidence_collection",
        "discipline_review",
        "constraint_review",
        "experiment_preparation",
        "handoff_preparation",
    ]
    owner_user_id: UUID | None = None
    receiver_user_id: UUID | None = None
    expected_output: str = Field(min_length=1, max_length=2048)
    completion_criteria: str = Field(min_length=1, max_length=2048)
    due_at: AwareDatetime | None = None


class WorkAction(CommandPrecondition):
    action: Literal["start", "submit", "accept", "return", "cancel"]
    note: str = Field(min_length=1, max_length=2048)
    evidence: tuple[SourceRef, ...] = ()


class AssignWork(CommandPrecondition):
    owner_user_id: UUID
    receiver_user_id: UUID | None = None


class CancelResearch(CommandPrecondition):
    reason: str = Field(min_length=1, max_length=2048)


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def _plain(row: Any) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(
        json.dumps(
            dict(row),
            default=lambda value: value.isoformat() if isinstance(value, datetime) else str(value),
        )
    )
    return result


def _scope_ref(row: Any) -> ScopeRef:
    line_id = row.get("product_line_id")
    return ScopeRef(
        kind="product_line" if line_id else "market_space", ref_id=line_id or row["market_space_id"]
    )


def _line_filter(table: Any, context: AuthContext) -> Any:
    if context.user.role in {Role.OWNER, Role.ADMIN}:
        return table.c.tenant_id == context.tenant.id
    grants = tables.product_line_members
    return or_(
        table.c.product_line_id.is_(None),
        table.c.product_line_id.in_(
            select(grants.c.product_line_id).where(
                grants.c.tenant_id == context.tenant.id, grants.c.user_id == context.user.id
            )
        ),
    )


def _line(
    connection: Connection,
    context: AuthContext,
    space_id: UUID,
    line_id: UUID | None,
    *,
    access: str = "viewer",
    writable: bool = False,
) -> Any:
    if line_id is None:
        return None
    table = tables.product_nodes
    row = (
        connection.execute(
            select(table).where(
                table.c.tenant_id == context.tenant.id,
                table.c.market_space_id == space_id,
                table.c.id == line_id,
                table.c.level == "line",
            )
        )
        .mappings()
        .one_or_none()
    )
    grants = tables.product_line_members
    level = (
        "manager"
        if context.user.role in {Role.OWNER, Role.ADMIN}
        else connection.execute(
            select(grants.c.access).where(
                grants.c.tenant_id == context.tenant.id,
                grants.c.product_line_id == line_id,
                grants.c.user_id == context.user.id,
            )
        ).scalar_one_or_none()
    )
    levels = {"viewer": 1, "contributor": 2, "manager": 3}
    if row is None or levels.get(level or "", 0) < levels[access]:
        raise ProductWorkAccessError("产品线不存在或无权访问")
    if writable and row["lifecycle"] == "retired":
        raise ProductWorkError("已退役产品线只读，请先恢复产品线")
    return row


def _record(row: Any) -> dict[str, Any]:
    value = _plain(row)
    value["scope"] = _scope_ref(row).model_dump(mode="json")
    value["payload_digest"] = digest(_plain(row))
    return value


def _research(row: Any) -> dict[str, Any]:
    contract = ResearchTask(
        id=row["id"],
        tenant_id=row["tenant_id"],
        scope=_scope_ref(row),
        version=row["version"],
        owner_user_id=row["owner_user_id"],
        sources=tuple(SourceRef.model_validate(item) for item in row["sources"]),
        **{
            key: row[key]
            for key in (
                "question",
                "user_groups",
                "regions",
                "time_scope",
                "method",
                "expected_decision",
                "stop_conditions",
                "state",
                "findings",
                "unresolved",
                "conclusion",
                "completed_at",
                "cancellation_reason",
            )
        },
    )
    return {**_record(row), **contract.model_dump(mode="json")}


def _role(context: AuthContext, action: Action) -> None:
    if not is_allowed(context.user.role, action):
        raise ProductWorkAccessError("当前角色不能办理此项产品工作")


def _space(
    connection: Connection,
    context: AuthContext,
    space_id: UUID,
    *,
    access: str = "viewer",
    lock: bool = False,
    allow_archived: bool = False,
) -> Any:
    _role(context, Action.PRODUCT_WORK_VIEW)
    statement = select(tables.market_spaces).where(
        tables.market_spaces.c.tenant_id == context.tenant.id, tables.market_spaces.c.id == space_id
    )
    if lock:
        statement = statement.with_for_update()
    row = connection.execute(statement).mappings().one_or_none()
    if row is None:
        raise ProductWorkAccessError("市场空间不存在或无权访问")
    level = (
        "manager"
        if context.user.role in {Role.OWNER, Role.ADMIN}
        else connection.execute(
            select(tables.market_space_members.c.access).where(
                tables.market_space_members.c.tenant_id == context.tenant.id,
                tables.market_space_members.c.market_space_id == space_id,
                tables.market_space_members.c.user_id == context.user.id,
            )
        ).scalar_one_or_none()
    )
    if {"viewer": 1, "contributor": 2, "manager": 3}.get(level or "", 0) < {
        "viewer": 1,
        "contributor": 2,
        "manager": 3,
    }[access]:
        raise ProductWorkAccessError("市场空间不存在或无权访问")
    if lock and row["lifecycle"] == "archived" and not allow_archived:
        raise ProductWorkError("已归档市场空间只读")
    return row


def _member(
    connection: Connection,
    context: AuthContext,
    space_id: UUID,
    user_id: UUID | None,
    line_id: UUID | None = None,
) -> None:
    if user_id is None:
        return
    found = connection.execute(
        select(tables.users.c.id)
        .join(
            tables.market_space_members,
            (tables.market_space_members.c.tenant_id == tables.users.c.tenant_id)
            & (tables.market_space_members.c.user_id == tables.users.c.id),
        )
        .where(
            tables.users.c.tenant_id == context.tenant.id,
            tables.users.c.id == user_id,
            tables.users.c.is_active.is_(True),
            tables.users.c.role.in_(("owner", "admin", "project_manager", "engineer", "quality")),
            tables.market_space_members.c.market_space_id == space_id,
            tables.market_space_members.c.access.in_(("contributor", "manager")),
        )
    ).scalar_one_or_none()
    if found is None:
        raise ProductWorkError("负责人或接收人须为当前空间有效协作成员")
    if line_id is not None:
        grants = tables.product_line_members
        granted = connection.execute(
            select(grants.c.user_id).where(
                grants.c.tenant_id == context.tenant.id,
                grants.c.product_line_id == line_id,
                grants.c.user_id == user_id,
                grants.c.access.in_(("contributor", "manager")),
            )
        ).scalar_one_or_none()
        if granted is None:
            raise ProductWorkError("负责人或接收人须为该产品线有效协作成员")


def _sources(
    connection: Connection, context: AuthContext, refs: tuple[SourceRef, ...]
) -> list[dict[str, Any]]:
    result = []
    for ref in refs:
        if (
            ref.tenant_id != context.tenant.id
            or ref.project_id is not None
            or ref.kind != "evidence_snapshot"
        ):
            raise ProductWorkError("请选择共享证据库中的来源快照；受限项目来源需要单独授权")
        row = (
            connection.execute(
                select(tables.evidence_snapshots)
                .join(
                    tables.research_sources,
                    (tables.research_sources.c.tenant_id == tables.evidence_snapshots.c.tenant_id)
                    & (tables.research_sources.c.id == tables.evidence_snapshots.c.source_id),
                )
                .where(
                    tables.evidence_snapshots.c.tenant_id == context.tenant.id,
                    tables.evidence_snapshots.c.id == ref.ref_id,
                    tables.research_sources.c.status == "active",
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None or ref.digest != row["content_digest"] or ref.as_of != row["captured_at"]:
            raise ProductWorkError("来源快照不存在、已停用或引用版本不匹配")
        result.append(
            SourceRef(
                tenant_id=context.tenant.id,
                kind="evidence_snapshot",
                ref_id=row["id"],
                as_of=row["captured_at"],
                digest=row["content_digest"],
                locator=ref.locator,
            ).model_dump(mode="json")
        )
    return result


def _emit(
    connection: Connection,
    context: AuthContext,
    space_id: UUID,
    kind: str,
    action: str,
    row: Any,
    *,
    before: Any = None,
    operation: CommandPrecondition | None = None,
    research_event: bool = False,
) -> None:
    operation_id = uuid4()
    event_id = (
        f"preproject:{row['id']}:{digest(operation.idempotency_key) if operation else operation_id}"
    )
    if research_event:
        event = EventDraft(
            event_id=event_id,
            event_type="RESEARCH_TASK_CHANGED",
            source="research_service",
            entity_id=row["id"],
            payload={
                "schema_version": 1,
                "object_id": str(row["id"]),
                "object_version": row["version"],
                "operation_id": str(operation_id),
                "correlation_id": str(row["id"]),
                "causation_event_row_id": None,
                "from_state": before["state"],
                "to_state": row["state"],
            },
        )
    else:
        event = EventDraft(
            event_id=event_id,
            event_type="PREPROJECT_RECORD_CHANGED",
            source="product_workspace_service",
            entity_id=row["id"],
            payload={
                "market_space_id": str(space_id),
                "record_kind": kind,
                "action": action,
                "object_version": row["version"],
            },
        )
    EventAuditWriter(
        connection, tenant_id=context.tenant.id, actor_user_id=context.user.id, project_id=None
    ).record(
        event,
        AuditDraft(
            action=f"{kind}.{action}",
            before_snapshot=_plain(before) if before else None,
            after_snapshot=_plain(row),
            context={
                "market_space_id": str(space_id),
                "command_digest": digest(operation.model_dump(mode="json")) if operation else None,
                "reason": getattr(operation, "reason", None),
            },
        ),
    )


def _precondition(
    connection: Connection, context: AuthContext, row: Any, command: CommandPrecondition
) -> bool:
    receipt = connection.execute(
        select(tables.audit_log.c.context).where(
            tables.audit_log.c.tenant_id == context.tenant.id,
            tables.audit_log.c.entity_id == row["id"],
            tables.audit_log.c.event_id
            == f"preproject:{row['id']}:{digest(command.idempotency_key)}",
        )
    ).scalar_one_or_none()
    if receipt is not None:
        if receipt.get("command_digest") != digest(command.model_dump(mode="json")):
            raise ProductWorkError("同一请求编号不能用于不同内容")
        return False
    if row["version"] != command.expected_version or digest(_plain(row)) != command.payload_digest:
        raise ProductWorkError("工作内容或状态已变化，请刷新后办理")
    return True


def create_work_in_connection(
    connection: Connection, context: AuthContext, space_id: UUID, draft: WorkDraft
) -> dict[str, Any]:
    _role(context, Action.PRODUCT_WORK_CONTRIBUTE)
    _space(connection, context, space_id, access="contributor", lock=True)
    _line(
        connection,
        context,
        space_id,
        draft.product_line_id,
        access="contributor",
        writable=True,
    )
    _member(connection, context, space_id, draft.owner_user_id, draft.product_line_id)
    _member(connection, context, space_id, draft.receiver_user_id, draft.product_line_id)
    acceptance = draft.action_type != "evidence_collection"
    state = (
        "ready"
        if draft.owner_user_id and (not acceptance or draft.receiver_user_id)
        else "pending_assignment"
    )
    table = tables.scoped_work_items
    request_digest = digest(draft.model_dump(mode="json"))
    existing = (
        connection.execute(
            select(table).where(
                table.c.tenant_id == context.tenant.id,
                table.c.market_space_id == space_id,
                table.c.request_id == draft.request_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if existing:
        if existing["request_digest"] != request_digest:
            raise ProductWorkError("同一请求编号不能用于不同内容")
        return _record(existing)
    row = (
        connection.execute(
            table.insert()
            .values(
                **draft.model_dump(),
                id=uuid4(),
                tenant_id=context.tenant.id,
                market_space_id=space_id,
                created_by_user_id=context.user.id,
                request_digest=request_digest,
                acceptance_required=acceptance,
                state=state,
            )
            .returning(table)
        )
        .mappings()
        .one()
    )
    _emit(connection, context, space_id, "scoped_work_item", "created", row)
    return _record(row)


class ProductWorkspaceService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list_spaces(self, context: AuthContext) -> list[dict[str, Any]]:
        _role(context, Action.PRODUCT_WORK_VIEW)
        table = tables.market_spaces
        statement = select(table).where(table.c.tenant_id == context.tenant.id)
        if context.user.role not in {Role.OWNER, Role.ADMIN}:
            statement = statement.where(
                table.c.id.in_(
                    select(tables.market_space_members.c.market_space_id).where(
                        tables.market_space_members.c.tenant_id == context.tenant.id,
                        tables.market_space_members.c.user_id == context.user.id,
                    )
                )
            )
        with self.engine.connect() as connection:
            return [
                _plain(row)
                for row in connection.execute(
                    statement.order_by(table.c.updated_at.desc())
                ).mappings()
            ]

    def create_space(self, context: AuthContext, draft: MarketSpaceDraft) -> dict[str, Any]:
        _role(context, Action.PRODUCT_WORK_MANAGE)
        payload = draft.model_dump(mode="json")
        try:
            with self.engine.begin() as connection:
                existing = (
                    connection.execute(
                        select(tables.market_spaces).where(
                            tables.market_spaces.c.tenant_id == context.tenant.id,
                            tables.market_spaces.c.request_id == draft.request_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing:
                    _space(connection, context, existing["id"])
                    if existing["request_digest"] != digest(payload):
                        raise ProductWorkError("同一请求编号不能用于不同内容")
                    return _plain(existing)
                values = draft.model_dump(exclude={"request_id"})
                row = (
                    connection.execute(
                        tables.market_spaces.insert()
                        .values(
                            **values,
                            id=uuid4(),
                            tenant_id=context.tenant.id,
                            owner_user_id=context.user.id,
                            request_id=draft.request_id,
                            request_digest=digest(payload),
                        )
                        .returning(tables.market_spaces)
                    )
                    .mappings()
                    .one()
                )
                connection.execute(
                    tables.market_space_members.insert().values(
                        tenant_id=context.tenant.id,
                        market_space_id=row["id"],
                        user_id=context.user.id,
                        access="manager",
                        added_by_user_id=context.user.id,
                    )
                )
                _emit(connection, context, row["id"], "market_space", "created", row)
                return _plain(row)
        except IntegrityError as error:
            raise ProductWorkError("市场空间编号或请求编号已存在，请刷新列表") from error

    def detail(self, context: AuthContext, space_id: UUID) -> dict[str, Any]:
        with self.engine.connect() as connection:
            space = _space(connection, context, space_id)
            membership = connection.execute(
                select(tables.market_space_members.c.access).where(
                    tables.market_space_members.c.tenant_id == context.tenant.id,
                    tables.market_space_members.c.market_space_id == space_id,
                    tables.market_space_members.c.user_id == context.user.id,
                )
            ).scalar_one_or_none()
            manager = context.user.role in {Role.OWNER, Role.ADMIN} or membership == "manager"
            members = connection.execute(
                select(
                    tables.users.c.id,
                    tables.users.c.display_name,
                    tables.market_space_members.c.access,
                )
                .join(
                    tables.market_space_members,
                    (tables.market_space_members.c.tenant_id == tables.users.c.tenant_id)
                    & (tables.market_space_members.c.user_id == tables.users.c.id),
                )
                .where(
                    tables.users.c.tenant_id == context.tenant.id,
                    tables.users.c.is_active.is_(True),
                    tables.users.c.role.in_(
                        ("owner", "admin", "project_manager", "engineer", "quality")
                    ),
                    tables.market_space_members.c.market_space_id == space_id,
                )
            ).mappings()
            research = connection.execute(
                select(tables.research_tasks)
                .where(
                    tables.research_tasks.c.tenant_id == context.tenant.id,
                    tables.research_tasks.c.market_space_id == space_id,
                    _line_filter(tables.research_tasks, context),
                )
                .order_by(tables.research_tasks.c.created_at.desc())
            ).mappings()
            work = connection.execute(
                select(tables.scoped_work_items)
                .where(
                    tables.scoped_work_items.c.tenant_id == context.tenant.id,
                    tables.scoped_work_items.c.market_space_id == space_id,
                    _line_filter(tables.scoped_work_items, context),
                )
                .order_by(tables.scoped_work_items.c.created_at.desc())
            ).mappings()
            available: Iterable[RowMapping] = (
                connection.execute(
                    select(tables.users.c.id, tables.users.c.display_name).where(
                        tables.users.c.tenant_id == context.tenant.id,
                        tables.users.c.is_active.is_(True),
                        tables.users.c.role.in_(
                            ("owner", "admin", "project_manager", "engineer", "quality")
                        ),
                    )
                ).mappings()
                if manager
                else []
            )
            return {
                "space": {**_plain(space), "payload_digest": digest(_plain(space))},
                "members": [_plain(row) for row in members],
                "available_members": [_plain(row) for row in available],
                "research": [_research(row) for row in research],
                "work_items": [_record(row) for row in work],
                "can_manage": space["lifecycle"] != "archived"
                and manager
                and is_allowed(context.user.role, Action.PRODUCT_WORK_MANAGE),
                "can_collect": space["lifecycle"] != "archived"
                and (manager or membership == "contributor")
                and is_allowed(context.user.role, Action.EVIDENCE_CAPTURE),
                "can_manage_sources": space["lifecycle"] != "archived"
                and manager
                and is_allowed(context.user.role, Action.RESEARCH_SOURCE_MANAGE),
                "can_restore": manager
                and is_allowed(context.user.role, Action.PRODUCT_WORK_MANAGE),
                "can_contribute": space["lifecycle"] != "archived"
                and (manager or membership == "contributor")
                and is_allowed(context.user.role, Action.PRODUCT_WORK_CONTRIBUTE),
                "current_user_id": str(context.user.id),
            }

    def set_member(
        self, context: AuthContext, space_id: UUID, user_id: UUID, access: str | None
    ) -> None:
        _role(context, Action.PRODUCT_WORK_MANAGE)
        with self.engine.begin() as connection:
            space = _space(connection, context, space_id, access="manager", lock=True)
            if user_id == space["owner_user_id"] and access != "manager":
                raise ProductWorkError("空间负责人须保留管理权限")
            user = connection.execute(
                select(tables.users.c.id).where(
                    tables.users.c.tenant_id == context.tenant.id,
                    tables.users.c.id == user_id,
                    tables.users.c.is_active.is_(True),
                    tables.users.c.role.in_(
                        ("owner", "admin", "project_manager", "engineer", "quality")
                    ),
                )
            ).scalar_one_or_none()
            if user is None and access is not None:
                raise ProductWorkError("只能添加租户内有效内部成员")
            table = tables.market_space_members
            conditions = (
                table.c.tenant_id == context.tenant.id,
                table.c.market_space_id == space_id,
                table.c.user_id == user_id,
            )
            old = connection.execute(select(table).where(*conditions)).mappings().one_or_none()
            if access is None:
                connection.execute(table.delete().where(*conditions))
            elif old:
                connection.execute(table.update().where(*conditions).values(access=access))
            else:
                connection.execute(
                    table.insert().values(
                        tenant_id=context.tenant.id,
                        market_space_id=space_id,
                        user_id=user_id,
                        access=access,
                        added_by_user_id=context.user.id,
                    )
                )
            after = (
                connection.execute(
                    tables.market_spaces.update()
                    .where(tables.market_spaces.c.id == space_id)
                    .values(version=space["version"] + 1, updated_at=datetime.now(UTC))
                    .returning(tables.market_spaces)
                )
                .mappings()
                .one()
            )
            _emit(
                connection,
                context,
                space_id,
                "market_space",
                "membership_changed",
                {**dict(after), "member_user_id": user_id, "member_access": access},
                before=space,
            )

    def create_research(
        self, context: AuthContext, space_id: UUID, draft: ResearchDraft
    ) -> dict[str, Any]:
        _role(context, Action.PRODUCT_WORK_CONTRIBUTE)
        with self.engine.begin() as connection:
            _space(connection, context, space_id, access="contributor", lock=True)
            _line(
                connection,
                context,
                space_id,
                draft.product_line_id,
                access="contributor",
                writable=True,
            )
            _member(connection, context, space_id, draft.owner_user_id, draft.product_line_id)
            table = tables.research_tasks
            request_digest = digest(draft.model_dump(mode="json"))
            existing = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.market_space_id == space_id,
                        table.c.request_id == draft.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing:
                if existing["request_digest"] != request_digest:
                    raise ProductWorkError("同一请求编号不能用于不同内容")
                return _research(existing)
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        **draft.model_dump(),
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        market_space_id=space_id,
                        created_by_user_id=context.user.id,
                        request_digest=request_digest,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            _research(row)
            _emit(connection, context, space_id, "research_task", "created", row)
            return _research(row)

    def research_action(
        self,
        context: AuthContext,
        space_id: UUID,
        task_id: UUID,
        command: ResearchStartRequest | ResearchConcludeRequest | CancelResearch,
    ) -> dict[str, Any]:
        _role(context, Action.PRODUCT_WORK_CONTRIBUTE)
        with self.engine.begin() as connection:
            _space(connection, context, space_id, access="contributor", lock=True)
            table = tables.research_tasks
            row = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.market_space_id == space_id,
                        table.c.id == task_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ProductWorkAccessError("研究任务不存在或不可访问")
            _line(
                connection,
                context,
                space_id,
                row["product_line_id"],
                access="contributor",
                writable=True,
            )
            if row["owner_user_id"] != context.user.id:
                raise ProductWorkAccessError("请由研究负责人办理")
            if not _precondition(connection, context, row, command):
                return _research(row)
            now = datetime.now(UTC)
            values: dict[str, Any] = {"version": row["version"] + 1, "updated_at": now}
            if isinstance(command, ResearchStartRequest):
                if command.research_task_id != task_id or row["state"] != "draft":
                    raise ProductWorkError("仅草稿研究可开始")
                values["state"] = "active"
                action = "start"
            elif isinstance(command, ResearchConcludeRequest):
                if command.research_task_id != task_id or row["state"] != "active":
                    raise ProductWorkError("仅进行中的研究可提交结论")
                sources = _sources(connection, context, command.source_refs)
                values.update(
                    state="completed",
                    conclusion=command.conclusion,
                    findings=list(command.findings),
                    unresolved=list(command.unresolved),
                    sources=sources,
                    completed_at=now,
                )
                action = "conclude"
            else:
                if row["state"] not in {"draft", "active"}:
                    raise ProductWorkError("研究已结束")
                values.update(state="cancelled", cancellation_reason=command.reason)
                action = "cancel"
            after = (
                connection.execute(
                    table.update().where(table.c.id == task_id).values(**values).returning(table)
                )
                .mappings()
                .one()
            )
            _research(after)
            _emit(
                connection,
                context,
                space_id,
                "research_task",
                action,
                after,
                before=row,
                operation=command,
                research_event=action in {"start", "conclude"},
            )
            return _research(after)

    def create_work(self, context: AuthContext, space_id: UUID, draft: WorkDraft) -> dict[str, Any]:
        with self.engine.begin() as connection:
            return create_work_in_connection(connection, context, space_id, draft)

    def work_action(
        self, context: AuthContext, space_id: UUID, item_id: UUID, command: WorkAction | AssignWork
    ) -> dict[str, Any]:
        _role(context, Action.PRODUCT_WORK_CONTRIBUTE)
        with self.engine.begin() as connection:
            _space(connection, context, space_id, access="contributor", lock=True)
            table = tables.scoped_work_items
            row = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.market_space_id == space_id,
                        table.c.id == item_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ProductWorkAccessError("工作项不存在或不可访问")
            _line(
                connection,
                context,
                space_id,
                row["product_line_id"],
                access="contributor",
                writable=True,
            )
            if isinstance(command, AssignWork):
                _line(connection, context, space_id, row["product_line_id"], access="manager")
                _role(context, Action.PRODUCT_WORK_MANAGE)
                _space(connection, context, space_id, access="manager")
            elif command.action in {"accept", "return"}:
                if row["receiver_user_id"] != context.user.id:
                    raise ProductWorkAccessError("请由指定接收人办理")
            elif row["owner_user_id"] != context.user.id:
                if command.action != "cancel":
                    raise ProductWorkAccessError("请由工作项负责人办理")
                _role(context, Action.PRODUCT_WORK_MANAGE)
                _space(connection, context, space_id, access="manager")
                _line(connection, context, space_id, row["product_line_id"], access="manager")
            if not _precondition(connection, context, row, command):
                return _record(row)
            now = datetime.now(UTC)
            values: dict[str, Any] = {"version": row["version"] + 1, "updated_at": now}
            if isinstance(command, AssignWork):
                if row["state"] not in {"pending_assignment", "ready"}:
                    raise ProductWorkError("工作开始后不能直接改派；请先处置原工作")
                _member(
                    connection, context, space_id, command.owner_user_id, row["product_line_id"]
                )
                _member(
                    connection, context, space_id, command.receiver_user_id, row["product_line_id"]
                )
                if row["acceptance_required"] and command.receiver_user_id is None:
                    raise ProductWorkError("此专业工作需要指定接收人")
                values.update(
                    owner_user_id=command.owner_user_id,
                    receiver_user_id=command.receiver_user_id,
                    state="ready",
                )
                action = "assign"
            else:
                action = command.action
                edges = {
                    "start": ("ready", "in_progress"),
                    "submit": (
                        "in_progress",
                        "submitted" if row["acceptance_required"] else "completed",
                    ),
                    "accept": ("submitted", "completed"),
                    "return": ("submitted", "in_progress"),
                }
                if action == "cancel":
                    if row["state"] in {"completed", "cancelled"}:
                        raise ProductWorkError("工作项已结束")
                    values.update(state="cancelled", cancellation_reason=command.note)
                else:
                    source, target = edges[action]
                    if row["state"] != source:
                        raise ProductWorkError("工作项状态已变化，请刷新")
                    values["state"] = target
                values["result_note"] = command.note
                if action == "submit":
                    evidence = _sources(connection, context, command.evidence)
                    if not evidence:
                        raise ProductWorkError("请关联输出证据后提交")
                    values["evidence"] = evidence
                elif action == "accept":
                    _sources(
                        connection,
                        context,
                        tuple(SourceRef.model_validate(item) for item in row["evidence"]),
                    )
                    values.update(accepted_by_user_id=context.user.id, accepted_at=now)
                elif action == "return":
                    values.update(evidence=[], accepted_by_user_id=None, accepted_at=None)
            after = (
                connection.execute(
                    table.update().where(table.c.id == item_id).values(**values).returning(table)
                )
                .mappings()
                .one()
            )
            _emit(
                connection,
                context,
                space_id,
                "scoped_work_item",
                action,
                after,
                before=row,
                operation=command,
            )
            return _record(after)

    def work_history(
        self, context: AuthContext, space_id: UUID, item_id: UUID, *, before_id: int | None = None
    ) -> dict[str, Any]:
        _role(context, Action.PRODUCT_WORK_VIEW)
        with self.engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection:
            _space(connection, context, space_id)
            table = tables.scoped_work_items
            row = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.market_space_id == space_id,
                        table.c.id == item_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ProductWorkAccessError("工作项不存在或不可访问")
            _line(connection, context, space_id, row["product_line_id"])
            audit = tables.audit_log
            users = tables.users
            statement = (
                select(audit, users.c.display_name.label("actor_display_name"))
                .outerjoin(
                    users,
                    (users.c.tenant_id == audit.c.tenant_id)
                    & (users.c.id == audit.c.actor_user_id),
                )
                .where(
                    audit.c.tenant_id == context.tenant.id,
                    audit.c.entity_id == item_id,
                    audit.c.action.in_(
                        [
                            f"scoped_work_item.{action}"
                            for action in (
                                "created",
                                "assign",
                                "start",
                                "submit",
                                "return",
                                "accept",
                                "cancel",
                            )
                        ]
                    ),
                    audit.c.context["market_space_id"].as_string() == str(space_id),
                )
            )
            if before_id is not None:
                statement = statement.where(audit.c.id < before_id)
            rows = (
                connection.execute(statement.order_by(audit.c.id.desc()).limit(21)).mappings().all()
            )
            snapshot_fields = (
                "version",
                "state",
                "owner_user_id",
                "receiver_user_id",
                "result_note",
                "evidence",
                "accepted_by_user_id",
                "accepted_at",
                "cancellation_reason",
            )

            def snapshot(value: Any) -> dict[str, Any] | None:
                return (
                    {key: value.get(key) for key in snapshot_fields}
                    if isinstance(value, dict)
                    else None
                )

            return {
                "work_id": str(item_id),
                "current_version": row["version"],
                "items": [
                    {
                        "id": item["id"],
                        "event_id": item["event_id"],
                        "action": item["action"].removeprefix("scoped_work_item."),
                        "actor_user_id": str(item["actor_user_id"])
                        if item["actor_user_id"]
                        else None,
                        "actor_display_name": item["actor_display_name"],
                        "timestamp": item["timestamp"].isoformat(),
                        "before": snapshot(item["before_snapshot"]),
                        "after": snapshot(item["after_snapshot"]),
                    }
                    for item in rows[:20]
                ],
                "next_before_id": rows[19]["id"] if len(rows) > 20 else None,
            }

    def evidence_options(self, context: AuthContext, space_id: UUID) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            _space(connection, context, space_id)
            rows = connection.execute(
                select(
                    tables.evidence_snapshots, tables.research_sources.c.name.label("source_name")
                )
                .join(
                    tables.research_sources,
                    (tables.research_sources.c.tenant_id == tables.evidence_snapshots.c.tenant_id)
                    & (tables.research_sources.c.id == tables.evidence_snapshots.c.source_id),
                )
                .where(
                    tables.evidence_snapshots.c.tenant_id == context.tenant.id,
                    tables.research_sources.c.status == "active",
                )
                .order_by(tables.evidence_snapshots.c.captured_at.desc())
                .limit(200)
            ).mappings()
            now = datetime.now(UTC)
            return [
                {
                    "id": str(row["id"]),
                    "name": row["source_name"],
                    "url": row["url"],
                    "captured_at": row["captured_at"].isoformat(),
                    "source_version": row["source_version"],
                    "taint": row["taint"],
                    "is_stale": row["freshness_expires_at"] is not None
                    and row["freshness_expires_at"] <= now,
                    "superseded": row["superseded_by_id"] is not None,
                    "has_conflict": row["conflicts_with_id"] is not None,
                    "reference": SourceRef(
                        tenant_id=context.tenant.id,
                        kind="evidence_snapshot",
                        ref_id=row["id"],
                        as_of=row["captured_at"],
                        digest=row["content_digest"],
                    ).model_dump(mode="json"),
                }
                for row in rows
            ]

    def my_work(
        self,
        context: AuthContext,
        *,
        collection: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        _role(context, Action.PRODUCT_WORK_VIEW)
        if (
            collection
            not in {None, "research", "work_items", "experiments", "strategies", "definitions"}
            or not 0 <= offset <= 1000000
            or not 1 <= limit <= 100
        ):
            raise ProductWorkError("工作分类或分页范围无效")
        with self.engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection:
            membership = select(tables.market_space_members.c.market_space_id).where(
                tables.market_space_members.c.tenant_id == context.tenant.id,
                tables.market_space_members.c.user_id == context.user.id,
            )
            result: dict[str, Any] = {
                "research": [],
                "work_items": [],
                "experiments": [],
                "strategies": [],
                "definitions": [],
                "pages": {},
            }
            for key, table in (
                ("research", tables.research_tasks),
                ("work_items", tables.scoped_work_items),
                ("experiments", tables.experiments),
                ("strategies", tables.product_strategies),
                ("definitions", tables.product_definitions),
            ):
                if collection is not None and collection != key:
                    continue
                assignment = table.c.owner_user_id == context.user.id
                if key == "work_items":
                    assignment = or_(
                        assignment,
                        (table.c.receiver_user_id == context.user.id)
                        & (table.c.state == "submitted"),
                    )
                if key in {"experiments", "strategies", "definitions"} and is_allowed(
                    context.user.role, Action.PRODUCT_WORK_MANAGE
                ):
                    elevated = context.user.role in {Role.OWNER, Role.ADMIN}
                    space_manager = (
                        table.c.tenant_id == context.tenant.id
                        if elevated
                        else table.c.market_space_id.in_(
                            select(tables.market_space_members.c.market_space_id).where(
                                tables.market_space_members.c.tenant_id == context.tenant.id,
                                tables.market_space_members.c.user_id == context.user.id,
                                tables.market_space_members.c.access == "manager",
                            )
                        )
                    )
                    line_manager = (
                        table.c.tenant_id == context.tenant.id
                        if elevated
                        else or_(
                            table.c.product_line_id.is_(None),
                            table.c.product_line_id.in_(
                                select(tables.product_line_members.c.product_line_id).where(
                                    tables.product_line_members.c.tenant_id == context.tenant.id,
                                    tables.product_line_members.c.user_id == context.user.id,
                                    tables.product_line_members.c.access == "manager",
                                )
                            ),
                        )
                    )
                    assignment = or_(
                        assignment,
                        (table.c.state == ("draft" if key == "experiments" else "in_review"))
                        & space_manager
                        & line_manager,
                    )
                if key == "definitions":
                    review_table = tables.definition_reviews
                    pending_review = []
                    for discipline in ("id", "md", "ee", "fw", "dqe"):
                        reviewed = (
                            select(review_table.c.id)
                            .where(
                                review_table.c.tenant_id == table.c.tenant_id,
                                review_table.c.definition_id == table.c.id,
                                review_table.c.review_round == table.c.review_round,
                                review_table.c.discipline == discipline,
                            )
                            .exists()
                        )
                        pending_review.append(
                            (
                                table.c.content["reviewers"][discipline].as_string()
                                == str(context.user.id)
                            )
                            & ~reviewed
                        )
                    assignment = or_(
                        assignment, (table.c.state == "in_review") & or_(*pending_review)
                    )
                statement = (
                    select(
                        table,
                        tables.market_spaces.c.title.label("space_title"),
                        tables.product_nodes.c.name.label("product_line_name"),
                    )
                    .join(
                        tables.market_spaces,
                        (tables.market_spaces.c.tenant_id == table.c.tenant_id)
                        & (tables.market_spaces.c.id == table.c.market_space_id),
                    )
                    .outerjoin(
                        tables.product_nodes,
                        (tables.product_nodes.c.tenant_id == table.c.tenant_id)
                        & (tables.product_nodes.c.market_space_id == table.c.market_space_id)
                        & (tables.product_nodes.c.id == table.c.product_line_id),
                    )
                    .where(
                        table.c.tenant_id == context.tenant.id,
                        assignment,
                        _line_filter(table, context),
                        table.c.state.not_in(("completed", "concluded", "cancelled", "published")),
                        tables.market_spaces.c.lifecycle != "archived",
                    )
                )
                if context.user.role not in {Role.OWNER, Role.ADMIN}:
                    statement = statement.where(table.c.market_space_id.in_(membership))
                total = connection.execute(
                    select(func.count()).select_from(statement.subquery())
                ).scalar_one()
                result[key] = [
                    _record(row)
                    for row in connection.execute(
                        statement.order_by(table.c.updated_at.desc(), table.c.id.desc())
                        .offset(offset)
                        .limit(limit)
                    ).mappings()
                ]
                result["pages"][key] = {
                    "total": total,
                    "offset": offset,
                    "limit": limit,
                    "next_offset": offset + limit if offset + limit < total else None,
                }
            return result
