"""Evidence for framework outputs comes from actual task and definition facts."""

from uuid import UUID

from sqlalchemy import select

from pdos_next.domain.projects.models import ProjectTask
from pdos_next.domain.projects.work.models import WorkTaskCurrent, WorkTaskVersion
from pdos_next.domain.projects.work.owner import sources_current
from pdos_next.errors import DomainError


def evaluate(s, ctx, project, stage, definition):
    evidence_plan_id = stage.get("evidence_plan_id")
    plan_id = UUID(evidence_plan_id) if evidence_plan_id else project.current_plan_id
    tasks = {
        str(identity): forecast
        for identity, forecast in s.execute(
            select(ProjectTask.id, ProjectTask.forecast).where(
                ProjectTask.project_id == project.id, ProjectTask.plan_id == plan_id
            )
        )
    }
    accepted = {}
    rows = s.scalars(
        select(WorkTaskVersion)
        .join(
            WorkTaskCurrent,
            WorkTaskCurrent.version_id == WorkTaskVersion.id,
        )
        .where(
            WorkTaskVersion.project_id == project.id,
            WorkTaskCurrent.state == "completed",
        )
    )
    for row in rows:
        task_ref = row.body.get("plan_task") or {}
        task = tasks.get(task_ref.get("id"))
        if task is None:
            continue
        try:
            sources_current(s, ctx, project.product_id, row.source_basis)
        except DomainError as error:
            if error.code not in {
                "FORBIDDEN_SCOPE",
                "SOURCE_UNAVAILABLE",
                "SOURCE_STALE",
                "VERSION_CONFLICT",
                "RECHECK_REQUIRED",
            }:
                raise
            continue
        review = row.body.get("review") or {}
        for result in review.get("checks", ()):
            outcome = result.get("key")
            if result.get("decision") == "accepted" and outcome in task.get("outcome_keys", ()):
                accepted[outcome] = {
                    "task_id": str(row.task_id),
                    "revision": row.revision,
                    "receipt_id": str(row.receipt_id),
                }
    if definition["status"] == "published" and definition["source_status"] == "current":
        accepted["specification_freeze"] = {
            "definition_id": definition["id"],
            "revision": definition["revision"],
            "receipt_id": definition["publication_receipt_id"],
        }
    return [
        {
            "key": outcome["key"],
            "label": outcome["name"],
            "state": "READY" if outcome["key"] in accepted else "UNKNOWN",
            "detail": "已有当前验收或规格冻结记录"
            if outcome["key"] in accepted
            else "尚缺当前成果依据",
            "ref": accepted.get(outcome["key"]),
        }
        for outcome in stage["outcomes"]
    ]
