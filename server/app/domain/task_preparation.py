"""Read-only, task-bound takeover preparation from current business records."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.formal_schedule import current_plan
from app.domain.id_handoff_runtime import acceptance_conditions
from app.domain.product_workspace import _plain, digest
from app.domain.resource_reservations import _project
from app.domain.schedule_execution import schedule_state
from app.domain.task_dependency_graph import active_dependencies
from app.domain.tasks import ACTION_SOURCE_TABLES, TERMINAL_TASK_STATUSES, TaskNotFoundError


def project_link(project_id: UUID, tab: str, entity_id: UUID | str | None = None) -> str:
    return f"/projects?project={project_id}&tab={tab}" + (
        f"&entity_id={entity_id}" if entity_id else ""
    )


class TaskPreparationService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(self, context: AuthContext, project_id: UUID, task_id: UUID) -> dict[str, Any]:
        # One consistent read; opening/refreshing always rechecks current scope.
        with (
            self.engine.connect().execution_options(
                isolation_level="REPEATABLE READ"
            ) as connection,
            connection.begin(),
        ):
            return self.snapshot(context, project_id, task_id, connection)

    def snapshot(
        self, context: AuthContext, project_id: UUID, task_id: UUID, connection: Connection
    ) -> dict[str, Any]:
        project = _project(connection, context, project_id)
        tenant_id = context.tenant.id
        task = (
            connection.execute(
                select(tables.tasks).where(
                    tables.tasks.c.tenant_id == tenant_id,
                    tables.tasks.c.project_id == project_id,
                    tables.tasks.c.id == task_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if task is None:
            raise TaskNotFoundError
        now = datetime.now(UTC)
        formal = current_plan(connection, tenant_id, project_id)
        schedule_node = (
            connection.execute(
                select(tables.schedule_nodes).where(
                    tables.schedule_nodes.c.tenant_id == tenant_id,
                    tables.schedule_nodes.c.project_id == project_id,
                    tables.schedule_nodes.c.task_id == task_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        node = (
            next((item for item in formal["nodes"] if item["task_id"] == task_id), None)
            if formal
            else None
        )
        plan_node = (
            next(
                (item for item in formal["plan"]["nodes"] if item["node_key"] == node["node_key"]),
                None,
            )
            if node is not None and formal is not None
            else None
        )
        execution = schedule_state(connection, tenant_id, project_id, now)
        conditions = (
            acceptance_conditions(connection, tenant_id, project_id, formal).get(
                schedule_node["id"], []
            )
            if schedule_node
            else []
        )
        readiness = next(
            (
                item
                for item in execution["items"]
                if schedule_node and item["node_id"] == str(schedule_node["id"])
            ),
            None,
        )
        dependencies = [
            {
                "id": str(row["id"]),
                "title": row["title"],
                "status": row["status"],
                "satisfied": row["status"] in TERMINAL_TASK_STATUSES,
                "href": project_link(project_id, "work-items", row["id"]),
            }
            for row in connection.execute(
                select(tables.tasks)
                .join(
                    tables.task_dependencies,
                    (tables.task_dependencies.c.tenant_id == tables.tasks.c.tenant_id)
                    & (tables.task_dependencies.c.project_id == tables.tasks.c.project_id)
                    & (tables.task_dependencies.c.depends_on_task_id == tables.tasks.c.id),
                )
                .where(
                    tables.task_dependencies.c.tenant_id == tenant_id,
                    tables.task_dependencies.c.project_id == project_id,
                    tables.task_dependencies.c.task_id == task_id,
                    active_dependencies(tenant_id, project_id),
                )
                .distinct()
                .order_by(tables.tasks.c.id)
            ).mappings()
        ]
        source = None
        source_name = ACTION_SOURCE_TABLES.get(task["kind"])
        if source_name and task["source_entity_id"]:
            table = getattr(tables, source_name)
            original = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == tenant_id,
                        table.c.project_id == project_id,
                        table.c.id == task["source_entity_id"],
                    )
                )
                .mappings()
                .one_or_none()
            )
            if original:
                tab = (
                    "gates"
                    if task["kind"] == "gate_action"
                    else "engineering"
                    if task["kind"] == "change_action"
                    else "work-items"
                )
                source = {
                    "id": str(original["id"]),
                    "kind": task["kind"],
                    "title": original.get("title") or original.get("name") or str(original["id"]),
                    "status": original.get("status"),
                    "href": project_link(project_id, tab, original["id"]),
                }
        handoff_ids = [UUID(item["handoff_id"]) for item in conditions if item.get("handoff_id")]
        handoffs = {
            _plain(row)["id"]: row
            for row in connection.execute(
                select(tables.id_design_handoffs).where(
                    tables.id_design_handoffs.c.tenant_id == tenant_id,
                    tables.id_design_handoffs.c.project_id == project_id,
                    tables.id_design_handoffs.c.id.in_(handoff_ids),
                )
            ).mappings()
        }
        deliveries = []
        for row in connection.execute(
            select(tables.id_design_handoff_items)
            .where(
                tables.id_design_handoff_items.c.tenant_id == tenant_id,
                tables.id_design_handoff_items.c.project_id == project_id,
                tables.id_design_handoff_items.c.handoff_id.in_(handoff_ids),
            )
            .order_by(
                tables.id_design_handoff_items.c.created_at, tables.id_design_handoff_items.c.id
            )
        ).mappings():
            handoff = handoffs[str(row["handoff_id"])]
            condition = next(
                item for item in conditions if item.get("handoff_id") == str(row["handoff_id"])
            )
            deliveries.append(
                {
                    "id": str(row["id"]),
                    "title": row["title"],
                    "criteria": row["criteria"],
                    "receiver_user_id": str(handoff["receiver_user_id"]),
                    "handoff_id": str(handoff["id"]),
                    "handoff_version": handoff["version"],
                    "accepted": condition["accepted"],
                    "reason": condition["reason"],
                    "artifact": row["artifact_snapshot"],
                    "residuals": row["residuals"],
                    "document_href": project_link(project_id, "documents", row["document_id"]),
                    "handoff_href": project_link(project_id, "overview", handoff["id"]),
                }
            )
        decisions = [
            {
                "id": str(row["id"]),
                "title": row["title"],
                "rationale": row["rationale"],
                "outcome": row["outcome"],
                "follow_up_state": row["follow_up_state"],
                "href": project_link(project_id, "decisions", row["id"]),
            }
            for row in connection.execute(
                select(tables.decisions)
                .where(
                    tables.decisions.c.tenant_id == tenant_id,
                    tables.decisions.c.project_id == project_id,
                    tables.decisions.c.follow_up_task_id == task_id,
                )
                .order_by(tables.decisions.c.decided_at, tables.decisions.c.id)
            ).mappings()
        ]
        people_ids = {task["assignee_user_id"], project["owner_user_id"]}
        if plan_node:
            people_ids.update(
                UUID(plan_node[field])
                for field in ("owner_user_id", "receiver_user_id")
                if plan_node.get(field)
            )
        for item in deliveries:
            people_ids.add(UUID(item["receiver_user_id"]))
            people_ids.update(UUID(residual["owner_user_id"]) for residual in item["residuals"])
        people_ids.discard(None)
        people = [
            _plain(row)
            for row in connection.execute(
                select(tables.users.c.id, tables.users.c.display_name, tables.users.c.is_active)
                .where(
                    tables.users.c.tenant_id == tenant_id,
                    tables.users.c.id.in_(people_ids),
                )
                .order_by(tables.users.c.id)
            ).mappings()
        ]
        start_blockers = [
            item["reason"]
            for item in (readiness or {}).get("start_blockers", [])
            if item.get("reason")
        ]
        finish_blockers = [
            item["reason"]
            for item in (readiness or {}).get("finish_blockers", [])
            if item.get("reason")
        ]
        start_blockers.extend(
            f"前置任务尚未结束：{item['title']}" for item in dependencies if not item["satisfied"]
        )
        if task["status"] == "blocked":
            start_blockers.append(f"任务已阻塞：{task['blocked_reason']}")
        if task["status"] == "pending_approval":
            start_blockers.append("任务尚待批准")
        if not readiness:
            finish_blockers.extend(
                item["reason"] for item in conditions if not item["accepted"] and item.get("reason")
            )
        expected_output = plan_node["expected_output"] if plan_node else task["expected_output"]
        from app.domain.firmware_package_tasks import task_package as firmware_task_package

        firmware = firmware_task_package(connection, tenant_id, project_id, task_id)
        from app.domain.issue_intake_compensations import bindings as intake_task_bindings

        intake_compensations = intake_task_bindings(
            connection, tenant_id, project_id, [], task_id=task_id
        )

        criteria = (
            plan_node["completion_criteria"]
            if plan_node
            else firmware["binding"]["snapshot"]["completion_criteria"]
            if firmware
            else intake_compensations[0]["snapshot"]["completion_criteria"]
            if intake_compensations
            else None
        )
        gaps = []
        if any(item["source_changed"] for item in intake_compensations):
            gaps.append("导入来源已有后续纠错，请核对本任务是否仍覆盖当前影响")
        if firmware and firmware["latest_package_id"] != firmware["package"]["id"]:
            gaps.append("固件工作包已有新资料版本，请核对是否需要承接原任务")
        if firmware and any(s["changed"] for s in firmware["sources"]):
            gaps.append("固件工作包引用来源已变化，请核对最新问题和测试记录")
        if not expected_output:
            gaps.append("尚未记录预期输出，请与负责人确认后补入任务")
        if not criteria:
            gaps.append("当前任务没有正式验收标准，请确认完成判据")
        if task["assignee_user_id"] is None:
            gaps.append("尚未指定当前任务负责人")
        elif not any(
            person["id"] == str(task["assignee_user_id"]) and person["is_active"]
            for person in people
        ):
            gaps.append("当前任务负责人已停用，请办理责任移交")
        if task["kind"] != "task" and source is None:
            gaps.append("来源记录尚未连接到此准备清单，请从原任务核对来源")
        from app.domain.test_execution_preparations import task_package

        verification = task_package(connection, tenant_id, project_id, task_id)
        from app.domain.engineering_review_packages import task_context

        engineering_reviews = task_context(connection, tenant_id, project_id, task_id)
        from app.domain.change_execution_tasks import task_context as change_context

        change_execution = change_context(connection, tenant_id, project_id, task_id)
        plain_task = _plain(task)
        snapshot = {
            "project": {
                "id": str(project_id),
                "code": project["code"],
                "name": project["name"],
                "status": project["status"],
                "owner_user_id": str(project["owner_user_id"])
                if project["owner_user_id"]
                else None,
            },
            "task": {
                **{
                    key: plain_task[key]
                    for key in (
                        "id",
                        "title",
                        "description",
                        "status",
                        "assignee_user_id",
                        "due_date",
                        "blocked_reason",
                        "completion_evidence_ref",
                        "expected_output",
                        "updated_at",
                    )
                },
                "href": project_link(project_id, "work-items", task_id),
            },
            "plan": {
                "baseline_id": str(formal["baseline_id"]),
                "baseline_version": formal["baseline_version"],
                "node_key": node["node_key"],
                "receiver_user_id": plan_node["receiver_user_id"],
            }
            if plan_node is not None and formal is not None and node is not None
            else None,
            "expected_output": expected_output,
            "completion_criteria": criteria,
            "source": source,
            "verification_workpackage": verification,
            "firmware_workpackage": firmware,
            "engineering_reviews": engineering_reviews,
            "change_execution": change_execution,
            "intake_compensations": intake_compensations,
            "decisions": decisions,
            "dependencies": dependencies,
            "deliveries": deliveries,
            "people": people,
            "gaps": gaps,
            "start_blockers": list(dict.fromkeys(start_blockers)),
            "finish_blockers": list(dict.fromkeys(finish_blockers)),
            "conditions": conditions,
        }
        intake, intake_versions = tables.project_intake_work, tables.project_intake_proposals
        initialization = (
            connection.execute(
                select(
                    intake.c.id.label("binding_id"),
                    intake.c.proposal_id,
                    intake.c.work_key,
                    intake.c.work_snapshot,
                    intake.c.created_at,
                    intake_versions.c.revision,
                    intake_versions.c.purpose,
                    intake_versions.c.draft,
                )
                .join(
                    intake_versions,
                    (intake_versions.c.tenant_id == intake.c.tenant_id)
                    & (intake_versions.c.project_id == intake.c.project_id)
                    & (intake_versions.c.id == intake.c.proposal_id),
                )
                .where(
                    intake.c.tenant_id == tenant_id,
                    intake.c.project_id == project_id,
                    intake.c.task_id == task_id,
                )
                .order_by(intake.c.created_at.desc(), intake.c.id.desc())
                .limit(21)
            )
            .mappings()
            .all()
        )
        if initialization:
            from app.domain.conversations import ConversationError
            from app.domain.project_intake_work import IntakeBusinessRef, freeze_context

            initialization_sources = {}
            for initialization_item in initialization[:20]:
                raw_source = initialization_item["work_snapshot"].get("source")
                if not raw_source:
                    continue
                original = (
                    initialization_item["draft"]
                    .get("work_context", {})
                    .get(str(initialization_item["work_key"]), {})
                    .get("source")
                )
                try:
                    live = freeze_context(
                        connection,
                        context,
                        project_id,
                        IntakeBusinessRef.model_validate(raw_source),
                        [],
                    )
                    is_current = original == live.get("source")
                except ConversationError:
                    is_current = False
                initialization_sources[initialization_item["work_key"]] = {
                    "source": original,
                    "source_current": is_current,
                }
                if not is_current:
                    gaps.append("初始化工作的业务记录或历史来源关联已变化，请重新核对办理依据")
            snapshot["intake_initialization"] = [
                {
                    "binding_id": str(item["binding_id"]),
                    "proposal_id": str(item["proposal_id"]),
                    "work_key": str(item["work_key"]),
                    "revision": item["revision"],
                    "purpose": item["purpose"],
                    "basis_note": item["work_snapshot"]["basis_note"],
                    "created_at": item["created_at"].isoformat(),
                    **initialization_sources.get(item["work_key"], {}),
                }
                for item in initialization[:20]
            ]
            snapshot["intake_initialization_more"] = len(initialization) > 20
        a = tables.audit_log
        followup_risk = connection.execute(
            select(a.c.context["risk_followup"]["basis"]["risk"]["id"].as_string()).where(
                a.c.tenant_id == tenant_id,
                a.c.project_id == project_id,
                a.c.entity_id == task_id,
                a.c.action == "task.create",
                a.c.context["risk_followup"]["basis"]["risk"]["id"].as_string().is_not(None),
            )
        ).scalar_one_or_none()
        snapshot["risk_followup_risk_id"] = followup_risk
        return {
            **snapshot,
            "prepared_at": now.isoformat(),
            "basis_digest": digest(snapshot),
            "preparation_kind": "business_records",
        }
