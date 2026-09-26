"""Evidence-backed completion of independent checkpoints in an approved plan."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import Contract, Text
from app.db.schema import tables
from app.domain.formal_schedule import current_plan
from app.domain.milestone_designations import node_snapshot, records
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError, _plain, digest
from app.domain.project_execution import _person
from app.domain.resource_reservations import _project
from app.domain.schedule_execution import guard_source_execution
from app.domain.schedule_source_actuals import observe_audit
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class MilestoneComplete(Contract):
    request_id: UUID
    expected_baseline_id: UUID
    evidence: Text


def may_complete(context: AuthContext, node: dict[str, Any]) -> bool:
    return is_allowed(context.user.role, Action.PROJECT_EDIT) or str(context.user.id) in (
        node.get("owner_user_id"),
        node.get("receiver_user_id"),
    )


class ScheduleMilestoneService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(self, context: AuthContext, project_id: UUID) -> dict[str, Any]:
        with self.engine.connect() as connection:
            project = _project(connection, context, project_id)
            formal = current_plan(connection, context.tenant.id, project_id)
            table = tables.schedule_milestone_completions
            completions = {
                row["node_id"]: _plain(row)
                for row in connection.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.project_id == project_id,
                    )
                ).mappings()
            }
            if formal is None:
                return {"baseline_id": None, "items": []}
            plan_nodes = {node["node_key"]: node for node in formal["plan"]["nodes"]}
            designations = records(connection, context.tenant.id, project_id)
            person_ids = {
                UUID(value)
                for node in plan_nodes.values()
                for value in (node.get("owner_user_id"), node.get("receiver_user_id"))
                if value
            }
            person_ids.update(UUID(row["actor_user_id"]) for row in completions.values())
            names = {
                str(key): name
                for key, name in connection.execute(
                    select(tables.users.c.id, tables.users.c.display_name).where(
                        tables.users.c.tenant_id == context.tenant.id,
                        tables.users.c.id.in_(person_ids),
                    )
                ).all()
            }
            for row in completions.values():
                row["actor_name"] = names.get(row["actor_user_id"], "历史办理人")
            return {
                "baseline_id": str(formal["baseline_id"]),
                "items": [
                    {
                        "node_id": str(node["id"]),
                        **plan_nodes[node["node_key"]],
                        "owner_name": names.get(
                            plan_nodes[node["node_key"]].get("owner_user_id"), "未指定"
                        ),
                        "receiver_name": names.get(
                            plan_nodes[node["node_key"]].get("receiver_user_id"), "未指定"
                        ),
                        "completion": completions.get(node["id"]),
                        "designation": _plain(designations[node["id"]][0])
                        if node["id"] in designations
                        else None,
                        "designation_source_current": (
                            designations[node["id"]][0]["snapshot"]
                            == node_snapshot(plan_nodes[node["node_key"]])
                        )
                        if node["id"] in designations
                        else None,
                        "can_designate": is_allowed(context.user.role, Action.PROJECT_EDIT),
                        "can_complete": project["status"] == "active"
                        and node["id"] not in completions
                        and may_complete(context, plan_nodes[node["node_key"]]),
                    }
                    for node in formal["nodes"]
                    if node["node_kind"] == "milestone"
                ],
            }

    def complete(
        self, context: AuthContext, project_id: UUID, node_id: UUID, command: MilestoneComplete
    ) -> dict[str, Any]:
        try:
            return self._complete(context, project_id, node_id, command)
        except IntegrityError as error:
            raise ProductWorkError("里程碑完成未生效，请刷新当前基线和办理记录") from error

    def _complete(
        self, context: AuthContext, project_id: UUID, node_id: UUID, command: MilestoneComplete
    ) -> dict[str, Any]:
        tenant_id = context.tenant.id
        with self.engine.begin() as connection:
            _project(connection, context, project_id, write=True)
            _person(connection, context, project_id, context.user.id)
            table = tables.schedule_milestone_completions
            fingerprint = digest(
                {
                    "project_id": str(project_id),
                    "node_id": str(node_id),
                    **command.model_dump(mode="json"),
                }
            )
            prior = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == tenant_id,
                        table.c.actor_user_id == context.user.id,
                        table.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior is not None:
                if prior["request_digest"] != fingerprint:
                    raise ProductWorkError("请求编号已用于另一项里程碑办理")
                return _plain(prior)
            formal = current_plan(connection, tenant_id, project_id)
            node = (
                next(
                    (
                        node
                        for node in formal["nodes"]
                        if node["id"] == node_id and node["node_kind"] == "milestone"
                    ),
                    None,
                )
                if formal
                else None
            )
            if formal is None or node is None:
                raise ProductWorkAccessError("里程碑尚未纳入本项目当前正式计划")
            if formal["baseline_id"] != command.expected_baseline_id:
                raise ProductWorkError("当前基线已变化，请刷新完成判据和前置条件")
            plan_node = next(
                item for item in formal["plan"]["nodes"] if item["node_key"] == node["node_key"]
            )
            if not may_complete(context, plan_node):
                raise ProductWorkAccessError("由当前计划中的负责人、接收人或项目管理人员办理")
            if connection.execute(
                select(table.c.id).where(table.c.tenant_id == tenant_id, table.c.node_id == node_id)
            ).first():
                raise ProductWorkError("里程碑已有完成记录，请查看原始办理依据")
            now = datetime.now(UTC)
            guard_source_execution(
                connection,
                tenant_id,
                project_id,
                node_id,
                "milestone.complete",
                {"started_at": now, "finished_at": now, "successful": True},
                None,
            )
            completion_id = uuid4()
            snapshot = {
                "completion_id": str(completion_id),
                "node_id": str(node_id),
                "baseline_id": str(formal["baseline_id"]),
                "status": "completed",
                "completion_criteria": plan_node["completion_criteria"],
                "evidence": command.evidence,
                "completed_at": now.isoformat(),
                "actor_user_id": str(context.user.id),
            }
            written = EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=context.user.id,
            ).record(
                EventDraft(
                    event_id=f"milestone:{node_id}:completed:{completion_id}",
                    event_type="SCHEDULE_MILESTONE_COMPLETED",
                    source="planning_service",
                    entity_id=node_id,
                    payload={"node_id": str(node_id), "completion_id": str(completion_id)},
                    occurred_at=now,
                ),
                AuditDraft(action="milestone.complete", after_snapshot=snapshot),
            )
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        id=completion_id,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        node_id=node_id,
                        baseline_id=formal["baseline_id"],
                        actor_user_id=context.user.id,
                        completion_criteria=plan_node["completion_criteria"],
                        evidence=command.evidence,
                        completed_at=now,
                        event_row_id=written.event_row_id,
                        audit_row_id=written.audit_row_id,
                        request_id=command.request_id,
                        request_digest=fingerprint,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            observe_audit(connection, tenant_id, project_id, written.audit_row_id)
            return _plain(row)
