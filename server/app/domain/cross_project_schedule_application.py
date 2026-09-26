"""Independent human application of a bilateral approved schedule dependency."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.cross_project_schedule import SIDES, _decisions, _event, _pair, endpoint
from app.domain.cross_project_schedule_runtime import (
    application_heads,
    execution_constraints,
    incoming_sources,
)
from app.domain.formal_schedule import current_plan, current_states
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _plain,
    _role,
    digest,
)
from app.domain.resource_reservations import _project
from app.domain.task_dependency_graph import dependency_graph_has_cycle
from app.domain.working_time import CalendarDefinition, WorkingTime


class CrossProjectApply(Contract):
    request_id: UUID
    expected_digest: Digest
    expected_previous_application_id: UUID | None = None
    expected_destination_application_id: UUID | None = None
    reason: Text


class CrossProjectApplicationService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def apply(
        self, context: AuthContext, project_id: UUID, proposal_id: UUID, command: CrossProjectApply
    ) -> dict[str, Any]:
        _role(context, Action.PROJECT_EDIT)
        tenant_id = context.tenant.id
        fingerprint = digest(
            {
                "project_id": str(project_id),
                "proposal_id": str(proposal_id),
                "command": command.model_dump(mode="json"),
            }
        )
        with self.engine.begin() as connection:
            _project(connection, context, project_id)
            proposals = tables.cross_project_schedule_proposals
            proposal = (
                connection.execute(
                    select(proposals).where(
                        proposals.c.tenant_id == tenant_id, proposals.c.id == proposal_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            if proposal is None or project_id not in (
                proposal["predecessor_project_id"],
                proposal["successor_project_id"],
            ):
                raise ProductWorkAccessError("申请不存在或不可访问")
            _pair(connection, context, proposal, write=True)
            apps = tables.cross_project_schedule_applications
            prior = (
                connection.execute(
                    select(apps).where(
                        apps.c.tenant_id == tenant_id,
                        apps.c.actor_user_id == context.user.id,
                        apps.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != fingerprint:
                    raise ProductWorkError("请求编号已用于另一项跨项目应用")
                return _plain(prior)
            if connection.execute(
                select(apps.c.id).where(
                    apps.c.tenant_id == tenant_id, apps.c.proposal_id == proposal_id
                )
            ).first():
                raise ProductWorkError("该申请已应用，请刷新查看原回执")
            if proposal["payload_digest"] != command.expected_digest:
                raise ProductWorkError("待应用内容与批准版本不一致")
            decisions = _decisions(connection, context, proposal_id)
            if len(decisions) != 2 or any(
                row["action"] != "approve"
                or row["approved_payload_digest"] != command.expected_digest
                for row in decisions
            ):
                raise ProductWorkError("必须先取得双方对同一版本的具名批准")
            for side in SIDES:
                current = endpoint(connection, context, proposal[f"{side}_project_id"])
                if (
                    not current["ready"]
                    or current["payload_digest"] != proposal["snapshot"][side]["endpoint_digest"]
                ):
                    raise ProductWorkError("双方基线、节点或批准政策已变化，请重新申请")
            has_cycle = dependency_graph_has_cycle(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                cross_edge=(proposal["successor_node_id"], proposal["predecessor_node_id"])
                if proposal["operation"] != "remove"
                else None,
                exclude_cross_application_id=proposal["target_application_id"]
                if proposal["operation"] == "replace"
                else None,
            )
            if has_cycle and proposal["operation"] != "remove":
                raise ProductWorkError("该跨项目关系与现有正式/手工依赖构成循环")
            heads = application_heads(connection, tenant_id)
            destination = next(
                (
                    head
                    for head in heads
                    if head["predecessor_node_id"] == proposal["predecessor_node_id"]
                    and head["successor_node_id"] == proposal["successor_node_id"]
                    and head["relation"] == proposal["relation"]
                ),
                None,
            )
            previous = (
                next(
                    (head for head in heads if head["id"] == proposal["target_application_id"]),
                    None,
                )
                if proposal["operation"] == "replace"
                else destination
            )
            displaced = (
                destination
                if proposal["operation"] == "replace"
                and destination
                and (not previous or destination["id"] != previous["id"])
                else None
            )
            if (previous["id"] if previous else None) != command.expected_previous_application_id:
                raise ProductWorkError("当前关系已变化，请刷新后重新审阅")
            if proposal["operation"] != "add" and (
                previous is None
                or previous["id"] != proposal["target_application_id"]
                or previous["operation"] == "remove"
            ):
                raise ProductWorkError("原关系已变化，请重新申请")
            if (
                (displaced["id"] if displaced else None)
                != command.expected_destination_application_id
                or (displaced["id"] if displaced else None)
                != proposal["destination_application_id"]
                or (displaced and displaced["operation"] != "remove")
            ):
                raise ProductWorkError("目标关系历史已变化，请重新申请")
            row = (
                connection.execute(
                    apps.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        proposal_id=proposal_id,
                        **{
                            f"{side}_{kind}_id": proposal[f"{side}_{kind}_id"]
                            for side in SIDES
                            for kind in ("project", "node")
                        },
                        relation=proposal["relation"],
                        operation=proposal["operation"],
                        replaces_application_id=previous["id"] if previous else None,
                        displaces_application_id=displaced["id"] if displaced else None,
                        actor_user_id=context.user.id,
                        reason=command.reason,
                        approved_payload_digest=command.expected_digest,
                        request_id=command.request_id,
                        request_digest=fingerprint,
                    )
                    .returning(apps)
                )
                .mappings()
                .one()
            )
            # Adding an edge cannot retroactively certify already performed work.
            target_project = proposal["successor_project_id"]
            formal = current_plan(connection, tenant_id, target_project)
            if formal is None:
                raise ProductWorkError("目标项目缺少当前正式计划，请重新准备依赖申请")
            states, _ = current_states(connection, tenant_id, target_project, formal)
            target = next(
                state for state in states if state["node_id"] == str(proposal["successor_node_id"])
            )
            actual_field = "actual_start" if proposal["relation"][1] == "s" else "actual_finish"
            if proposal["operation"] != "remove" and target[actual_field]:
                calendar_id = UUID(formal["allocations"][target["node_key"]]["calendar_version_id"])
                definition = connection.execute(
                    select(tables.work_calendar_versions.c.definition).where(
                        tables.work_calendar_versions.c.tenant_id == tenant_id,
                        tables.work_calendar_versions.c.id == calendar_id,
                    )
                ).scalar_one()
                constraints = execution_constraints(
                    incoming_sources(connection, tenant_id, target_project),
                    proposal["successor_node_id"],
                    WorkingTime(CalendarDefinition.model_validate(definition)),
                    datetime.fromisoformat(target[actual_field]),
                )
                if any(
                    c["application_id"] == str(row["id"]) and not c["satisfied"]
                    for c in constraints
                ):
                    raise ProductWorkError(
                        "新依赖与已发生的后序实际时间冲突，不能用申请追认既成事实"
                    )
            for side in SIDES:
                _event(
                    connection,
                    context,
                    proposal[f"{side}_project_id"],
                    proposal_id,
                    "application",
                    _plain(row),
                )
            from app.domain.schedule_forecasts import automatic_forecast

            affected = {target_project}
            if previous:
                affected.add(previous["successor_project_id"])
            for affected_project in sorted(affected, key=str):
                automatic_forecast(
                    connection,
                    tenant_id,
                    affected_project,
                    context.user.id,
                    "双方批准的跨项目依赖变更已生效",
                    datetime.now(UTC),
                )
            return _plain(row)
