"""Versioned Case requirement relations; legacy primary links remain authoritative."""

from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import Connection, Engine, func, or_, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import Digest, Text
from app.db.schema import tables
from app.domain.opportunity_requirements import requirement_snapshot
from app.domain.product_workspace import (
    Input,
    ProductWorkAccessError,
    ProductWorkError,
    _plain,
    _role,
    digest,
)
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class CaseRequirementCommand(Input):
    request_id: UUID
    expected_sequence: int = Field(ge=0)
    case_digest: Digest
    requirement_id: UUID
    requirement_digest: Digest
    action: Literal["attach", "refresh", "release"]
    rationale: Text


def _case(
    connection: Connection, context: AuthContext, case_id: UUID, *, lock: bool = False
) -> Any:
    table = tables.development_cases
    statement = select(table).where(table.c.tenant_id == context.tenant.id, table.c.id == case_id)
    row = (
        connection.execute(statement.with_for_update() if lock else statement)
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkAccessError("开发案例不存在或不可访问")
    return row


def _latest(connection: Connection, context: AuthContext, case_id: UUID) -> Any:
    table = tables.case_requirement_links
    return (
        connection.execute(
            select(table)
            .where(table.c.tenant_id == context.tenant.id, table.c.case_id == case_id)
            .order_by(table.c.sequence.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )


def _relations(connection: Connection, context: AuthContext, case: Any) -> list[dict[str, Any]]:
    table = tables.case_requirement_links
    ranked = (
        select(
            table,
            func.row_number()
            .over(partition_by=table.c.requirement_id, order_by=table.c.sequence.desc())
            .label("position"),
        )
        .where(table.c.tenant_id == context.tenant.id, table.c.case_id == case["id"])
        .subquery()
    )
    links = {
        row["requirement_id"]: row
        for row in connection.execute(
            select(ranked).where(ranked.c.position == 1, ranked.c.action != "release")
        ).mappings()
    }
    ids = set(links) | {case["requirement_id"]}
    rows = connection.execute(
        select(tables.requirements)
        .where(
            tables.requirements.c.tenant_id == context.tenant.id, tables.requirements.c.id.in_(ids)
        )
        .order_by(tables.requirements.c.code)
    ).mappings()
    result = []
    for row in rows:
        current = requirement_snapshot(row)
        link = links.get(row["id"])
        result.append(
            {
                "requirement_id": str(row["id"]),
                "primary": row["id"] == case["requirement_id"],
                "snapshot": link["requirement_snapshot"] if link else current,
                "current": current,
                "current_digest": digest(current),
                "has_changed": link is not None and link["requirement_digest"] != digest(current),
                "pinned": link is not None,
                "rationale": link["rationale"]
                if link
                else "原主需求转化关联；尚未固定补充引用快照",
                "linked_at": link["created_at"].isoformat() if link else None,
            }
        )
    return sorted(result, key=lambda item: (not item["primary"], item["snapshot"]["code"]))


class CaseRequirementService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def _detail(self, connection: Connection, context: AuthContext, case: Any) -> dict[str, Any]:
        latest = _latest(connection, context, case["id"])
        return {
            "case_id": str(case["id"]),
            "case_digest": digest(_plain(case)),
            "sequence": latest["sequence"] if latest else 0,
            "can_edit": is_allowed(context.user.role, Action.DEVELOPMENT_CASE_EDIT)
            and case["status"] in {"draft", "evaluating"},
            "items": _relations(connection, context, case),
        }

    def detail(self, context: AuthContext, case_id: UUID) -> dict[str, Any]:
        _role(context, Action.DEVELOPMENT_CASE_VIEW)
        _role(context, Action.REQUIREMENT_VIEW)
        with self.engine.connect() as connection:
            return self._detail(connection, context, _case(connection, context, case_id))

    def options(self, context: AuthContext, case_id: UUID, query: str) -> dict[str, Any]:
        _role(context, Action.DEVELOPMENT_CASE_VIEW)
        _role(context, Action.REQUIREMENT_VIEW)
        with self.engine.connect() as connection:
            _case(connection, context, case_id)
            table = tables.requirements
            statement = select(table).where(table.c.tenant_id == context.tenant.id)
            if query.strip():
                statement = statement.where(
                    or_(
                        table.c.code.icontains(query.strip(), autoescape=True),
                        table.c.title.icontains(query.strip(), autoescape=True),
                    )
                )
            rows = list(
                connection.execute(
                    statement.order_by(table.c.updated_at.desc(), table.c.id).limit(101)
                ).mappings()
            )
            return {
                "items": [
                    {
                        "snapshot": requirement_snapshot(row),
                        "payload_digest": digest(requirement_snapshot(row)),
                    }
                    for row in rows[:100]
                ],
                "has_more": len(rows) > 100,
            }

    def history(self, context: AuthContext, case_id: UUID) -> dict[str, Any]:
        _role(context, Action.DEVELOPMENT_CASE_VIEW)
        _role(context, Action.REQUIREMENT_VIEW)
        with self.engine.connect() as connection:
            _case(connection, context, case_id)
            table = tables.case_requirement_links
            rows = list(
                connection.execute(
                    select(table)
                    .where(table.c.tenant_id == context.tenant.id, table.c.case_id == case_id)
                    .order_by(table.c.sequence.desc())
                    .limit(201)
                ).mappings()
            )
            return {"items": [_plain(row) for row in rows[:200]], "has_more": len(rows) > 200}

    def change(
        self, context: AuthContext, case_id: UUID, command: CaseRequirementCommand
    ) -> dict[str, Any]:
        _role(context, Action.DEVELOPMENT_CASE_EDIT)
        _role(context, Action.REQUIREMENT_VIEW)
        with self.engine.begin() as connection:
            case = _case(connection, context, case_id, lock=True)
            table = tables.case_requirement_links
            fingerprint = digest(command.model_dump(mode="json"))
            existing = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.case_id == case_id,
                        table.c.actor_user_id == context.user.id,
                        table.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                if existing["request_digest"] != fingerprint:
                    raise ProductWorkError("同一请求编号不能用于不同关联内容")
                return self._detail(connection, context, case)
            if case["status"] not in {"draft", "evaluating"}:
                raise ProductWorkError("仅草稿或评估中的案例可调整需求范围")
            previous = _latest(connection, context, case_id)
            if command.expected_sequence != (
                previous["sequence"] if previous else 0
            ) or command.case_digest != digest(_plain(case)):
                raise ProductWorkError("案例或关联范围已变化，请刷新后再办理")
            row = (
                connection.execute(
                    select(tables.requirements)
                    .where(
                        tables.requirements.c.tenant_id == context.tenant.id,
                        tables.requirements.c.id == command.requirement_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ProductWorkAccessError("需求不存在或不可访问")
            snapshot = requirement_snapshot(row)
            if digest(snapshot) != command.requirement_digest:
                raise ProductWorkError("需求已发生变化，请查看当前内容后重新选择")
            current = (
                connection.execute(
                    select(table)
                    .where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.case_id == case_id,
                        table.c.requirement_id == command.requirement_id,
                    )
                    .order_by(table.c.sequence.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            primary = command.requirement_id == case["requirement_id"]
            active = primary or (current is not None and current["action"] != "release")
            if (command.action == "attach" and active) or (
                command.action in {"refresh", "release"} and not active
            ):
                raise ProductWorkError("关联状态已变化，请刷新需求范围")
            if command.action == "release" and primary:
                raise ProductWorkError("原主需求关联不可解除")
            if command.action != "release" and row["status"] == "rejected":
                raise ProductWorkError("已拒绝需求不能纳入或更新引用")
            after = (
                connection.execute(
                    table.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        case_id=case_id,
                        requirement_id=command.requirement_id,
                        previous_id=previous["id"] if previous else None,
                        sequence=(previous["sequence"] if previous else 0) + 1,
                        action=command.action,
                        requirement_snapshot=snapshot,
                        requirement_digest=digest(snapshot),
                        rationale=command.rationale,
                        actor_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=fingerprint,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            EventAuditWriter(
                connection, tenant_id=context.tenant.id, actor_user_id=context.user.id
            ).record(
                EventDraft(
                    event_id=f"case-requirements:{after['id']}",
                    event_type="DEVELOPMENT_CASE_UPDATED",
                    source="development_case_service",
                    entity_id=case_id,
                    payload={"changed_fields": ["requirement_links"], "status": case["status"]},
                ),
                AuditDraft(
                    action="development_case.requirement_link",
                    before_snapshot=_plain(current) if current else None,
                    after_snapshot=_plain(after),
                    context={"reason": command.rationale},
                ),
            )
            return self._detail(connection, context, case)

    def backlinks(self, context: AuthContext, requirement_id: UUID) -> dict[str, Any]:
        _role(context, Action.DEVELOPMENT_CASE_VIEW)
        _role(context, Action.REQUIREMENT_VIEW)
        with self.engine.connect() as connection:
            if (
                connection.execute(
                    select(tables.requirements.c.id).where(
                        tables.requirements.c.tenant_id == context.tenant.id,
                        tables.requirements.c.id == requirement_id,
                    )
                ).first()
                is None
            ):
                raise ProductWorkAccessError("需求不存在或不可访问")
            table, case = tables.case_requirement_links, tables.development_cases
            ranked = (
                select(
                    table.c.case_id,
                    table.c.action,
                    func.row_number()
                    .over(partition_by=table.c.case_id, order_by=table.c.sequence.desc())
                    .label("position"),
                )
                .where(
                    table.c.tenant_id == context.tenant.id, table.c.requirement_id == requirement_id
                )
                .subquery()
            )
            statement = select(case).where(
                case.c.tenant_id == context.tenant.id,
                or_(
                    case.c.requirement_id == requirement_id,
                    case.c.id.in_(
                        select(ranked.c.case_id).where(
                            ranked.c.position == 1, ranked.c.action != "release"
                        )
                    ),
                ),
            )
            cases = list(
                connection.execute(
                    statement.order_by(case.c.updated_at.desc(), case.c.id).limit(201)
                ).mappings()
            )
            return {
                "items": [
                    {
                        "id": str(row["id"]),
                        "code": row["code"],
                        "title": row["title"],
                        "status": row["status"],
                        "primary": row["requirement_id"] == requirement_id,
                    }
                    for row in cases[:200]
                ],
                "has_more": len(cases) > 200,
            }


class CaseRequirementReadinessError(ValueError):
    """The human-selected scope contains unapproved or changed requirements."""


def require_case_requirements_ready(connection: Connection, tenant_id: UUID, case: Any) -> None:
    table = tables.case_requirement_links
    # Existing primary-only cases keep their historical conversion semantics.
    if (
        connection.execute(
            select(table.c.id)
            .where(table.c.tenant_id == tenant_id, table.c.case_id == case["id"])
            .limit(1)
        ).first()
        is None
    ):
        return
    ranked = (
        select(
            table,
            func.row_number()
            .over(partition_by=table.c.requirement_id, order_by=table.c.sequence.desc())
            .label("position"),
        )
        .where(table.c.tenant_id == tenant_id, table.c.case_id == case["id"])
        .subquery()
    )
    links = {
        row["requirement_id"]: row
        for row in connection.execute(
            select(ranked).where(ranked.c.position == 1, ranked.c.action != "release")
        ).mappings()
    }
    ids = set(links) | {case["requirement_id"]}
    rows = connection.execute(
        select(tables.requirements)
        .where(tables.requirements.c.tenant_id == tenant_id, tables.requirements.c.id.in_(ids))
        .order_by(tables.requirements.c.id)
        .with_for_update()
    ).mappings()
    from app.domain.case_reviews import scope_revalidated

    reviewed = scope_revalidated(connection, tenant_id, case)
    blockers = []
    for row in rows:
        if row["status"] not in {"approved", "converted"}:
            blockers.append(f"{row['code']}尚未批准")
        if (
            not reviewed
            and row["id"] in links
            and digest(requirement_snapshot(row)) != links[row["id"]]["requirement_digest"]
        ):
            blockers.append(f"{row['code']}已变化，需重新审阅引用")
    if blockers:
        raise CaseRequirementReadinessError("需求范围尚未就绪：" + "；".join(blockers))
