"""Batch human responsibility acknowledgments bound to immutable plan candidates."""

from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, func, select

from app.auth.repository import AuthContext
from app.contracts.common_objects import Contract, Digest, Key, Text
from app.db.schema import tables
from app.domain.initial_plan_candidates import (
    _record,
    _source,
    _source_selector,
    candidate_snapshot,
)
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _member,
    _plain,
    digest,
)
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class ResponseTarget(Contract):
    node_key: Key
    slot: Literal["owner", "receiver"]
    previous_response_id: UUID | None


class ResponsibilityResponse(Contract):
    request_id: UUID
    candidate_digest: Digest
    targets: tuple[ResponseTarget, ...] = Field(min_length=1, max_length=2000)
    outcome: Literal["confirmed", "changes_requested", "withdrawn"]
    reason: Text

    @model_validator(mode="after")
    def unique_targets(self) -> Self:
        if len({(item.node_key, item.slot) for item in self.targets}) != len(self.targets):
            raise ValueError("同一节点职责不能重复选择")
        return self


def _candidate(
    connection: Connection, context: AuthContext, candidate_id: UUID, *, lock: bool = False
) -> Any:
    table = tables.initial_plan_candidates
    statement = select(table).where(
        table.c.tenant_id == context.tenant.id, table.c.id == candidate_id
    )
    row = (
        connection.execute(statement.with_for_update() if lock else statement)
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkAccessError("计划候选不存在或不可访问")
    _source(connection, context, row["market_space_id"], _source_selector(row))
    return row


def _participant(
    connection: Connection, context: AuthContext, candidate: Any, user_id: UUID
) -> None:
    if candidate["market_space_id"]:
        _member(
            connection, context, candidate["market_space_id"], user_id, candidate["product_line_id"]
        )
    elif (
        connection.execute(
            select(tables.users.c.id).where(
                tables.users.c.tenant_id == context.tenant.id,
                tables.users.c.id == user_id,
                tables.users.c.is_active.is_(True),
                tables.users.c.role.in_(
                    ("owner", "admin", "project_manager", "engineer", "quality")
                ),
            )
        ).first()
        is None
    ):
        raise ProductWorkError("职责参与人已不具备当前有效内部身份")


def _latest(
    connection: Connection, context: AuthContext, candidate_id: UUID
) -> dict[tuple[str, str], Any]:
    table = tables.plan_responsibility_responses
    ranked = (
        select(
            table,
            func.row_number()
            .over(partition_by=(table.c.node_key, table.c.slot), order_by=table.c.sequence.desc())
            .label("position"),
        )
        .where(table.c.tenant_id == context.tenant.id, table.c.candidate_id == candidate_id)
        .subquery()
    )
    return {
        (row["node_key"], row["slot"]): row
        for row in connection.execute(select(ranked).where(ranked.c.position == 1)).mappings()
    }


def responsibility_state(
    connection: Connection, context: AuthContext, candidate: Any
) -> dict[str, Any]:
    latest = _latest(connection, context, candidate["id"])
    assigned_ids = {
        UUID(node[key])
        for node in candidate["plan"]["nodes"]
        for key in ("owner_user_id", "receiver_user_id")
        if node[key]
    }
    people = {
        row["id"]: row["display_name"]
        for row in connection.execute(
            select(tables.users.c.id, tables.users.c.display_name).where(
                tables.users.c.tenant_id == context.tenant.id, tables.users.c.id.in_(assigned_ids)
            )
        ).mappings()
    }
    eligibility = {}
    user_id: UUID | None
    for user_id in assigned_ids:
        try:
            _participant(connection, context, candidate, user_id)
            eligibility[user_id] = True
        except (ProductWorkError, ProductWorkAccessError):
            eligibility[user_id] = False
    assignments = []
    for node in candidate["plan"]["nodes"]:
        for slot, field in (("owner", "owner_user_id"), ("receiver", "receiver_user_id")):
            user_id = UUID(node[field]) if node[field] else None
            response = latest.get((node["node_key"], slot))
            assignments.append(
                {
                    "node_key": node["node_key"],
                    "title": node["title"],
                    "slot": slot,
                    "user_id": str(user_id) if user_id else None,
                    "display_name": people.get(user_id, "待指定") if user_id else "待指定",
                    "eligible": eligibility.get(user_id, False) if user_id else False,
                    "mine": user_id == context.user.id,
                    "response": _plain(response) if response else None,
                }
            )
    record = _record(connection, context, candidate)
    is_latest = (
        connection.execute(
            select(tables.initial_plan_candidates.c.id).where(
                tables.initial_plan_candidates.c.tenant_id == context.tenant.id,
                tables.initial_plan_candidates.c.supersedes_id == candidate["id"],
            )
        ).first()
        is None
    )
    all_confirmed = all(
        item["eligible"]
        and item["response"] is not None
        and item["response"]["outcome"] == "confirmed"
        for item in assignments
    )
    return {
        "candidate_id": str(candidate["id"]),
        "candidate_digest": digest(candidate_snapshot(candidate)),
        "version": candidate["version"],
        "assignments": assignments,
        "all_confirmed": all_confirmed,
        "is_latest": is_latest,
        "source_is_current": record["source_is_current"],
        "template_is_current": record["template_is_current"],
        "current_missing": record["missing"],
        "ready_for_plan_review": all_confirmed
        and is_latest
        and record["source_is_current"]
        and record["template_is_current"]
        and not record["missing"],
    }


class PlanResponsibilityService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(self, context: AuthContext, candidate_id: UUID) -> dict[str, Any]:
        with self.engine.connect() as connection:
            candidate = _candidate(connection, context, candidate_id)
            table = tables.plan_responsibility_responses
            history = list(
                connection.execute(
                    select(table)
                    .where(
                        table.c.tenant_id == context.tenant.id, table.c.candidate_id == candidate_id
                    )
                    .order_by(table.c.sequence.desc())
                    .limit(201)
                ).mappings()
            )
            return {
                **responsibility_state(connection, context, candidate),
                "history": [_plain(row) for row in history[:200]],
                "has_more_history": len(history) > 200,
            }

    def respond(
        self, context: AuthContext, candidate_id: UUID, command: ResponsibilityResponse
    ) -> dict[str, Any]:
        with self.engine.begin() as connection:
            candidate = _candidate(connection, context, candidate_id, lock=True)
            _participant(connection, context, candidate, context.user.id)
            table = tables.plan_responsibility_responses
            fingerprint = digest(command.model_dump(mode="json"))
            prior = (
                connection.execute(
                    select(table)
                    .where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.candidate_id == candidate_id,
                        table.c.actor_user_id == context.user.id,
                        table.c.request_id == command.request_id,
                    )
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != fingerprint:
                    raise ProductWorkError("请求编号不能用于不同职责答复")
                return responsibility_state(connection, context, candidate)
            if command.candidate_digest != digest(candidate_snapshot(candidate)):
                raise ProductWorkError("所确认内容与本候选版本不一致")
            state = responsibility_state(connection, context, candidate)
            if command.outcome == "confirmed" and not (
                state["is_latest"] and state["source_is_current"] and state["template_is_current"]
            ):
                raise ProductWorkError("计划、来源或模板已修订，请确认新的候选版本")
            assignments = {(item["node_key"], item["slot"]): item for item in state["assignments"]}
            for target in command.targets:
                item = assignments.get((target.node_key, target.slot))
                if item is None or not item["mine"] or not item["eligible"]:
                    raise ProductWorkAccessError("只能办理自己实际承担且仍有效的职责")
                previous = item["response"]
                if (str(target.previous_response_id) if target.previous_response_id else None) != (
                    previous["id"] if previous else None
                ):
                    raise ProductWorkError("所选职责已有新答复，请刷新后办理")
                if command.outcome == "withdrawn" and (
                    previous is None or previous["outcome"] != "confirmed"
                ):
                    raise ProductWorkError("只能撤回本人当前有效的确认")
            sequence = (
                connection.execute(
                    select(func.max(table.c.sequence)).where(
                        table.c.tenant_id == context.tenant.id, table.c.candidate_id == candidate_id
                    )
                ).scalar_one()
                or 0
            )
            records = []
            for offset, target in enumerate(command.targets, 1):
                row = (
                    connection.execute(
                        table.insert()
                        .values(
                            id=uuid4(),
                            tenant_id=context.tenant.id,
                            candidate_id=candidate_id,
                            node_key=target.node_key,
                            slot=target.slot,
                            sequence=sequence + offset,
                            previous_response_id=target.previous_response_id,
                            outcome=command.outcome,
                            reason=command.reason,
                            candidate_digest=command.candidate_digest,
                            actor_user_id=context.user.id,
                            request_id=command.request_id,
                            request_digest=fingerprint,
                        )
                        .returning(table)
                    )
                    .mappings()
                    .one()
                )
                records.append(_plain(row))
            EventAuditWriter(
                connection, tenant_id=context.tenant.id, actor_user_id=context.user.id
            ).record(
                EventDraft(
                    # Three UUIDs plus this prefix fit the 128-character event key.
                    event_id=f"plan-resp:{candidate_id}:{context.user.id}:{command.request_id}",
                    event_type="PLAN_RESPONSIBILITY_RESPONDED",
                    source="planning_service",
                    entity_id=candidate_id,
                    payload={
                        "candidate_id": str(candidate_id),
                        "outcome": command.outcome,
                        "assignment_count": len(records),
                    },
                ),
                AuditDraft(
                    action="plan_responsibility.responded",
                    after_snapshot={"responses": records},
                    context={"reason": command.reason},
                ),
            )
            return responsibility_state(connection, context, candidate)
