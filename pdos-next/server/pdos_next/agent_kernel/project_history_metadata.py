"""Batch current project pointers for frozen history, without reading fact bodies."""

from uuid import UUID

from sqlalchemy import func, literal, select, union_all

from pdos_next.service import digest

LIMIT = 20


def statement(identities):
    from pdos_next.domain.project_governance.models import GovernanceEvent
    from pdos_next.domain.projects.models import Project
    from pdos_next.domain.work_management.models import (
        ProjectStatusUpdate,
        WorkCommitmentCurrent,
        WorkTaskCurrent,
    )

    projects = select(Project.id, Project.tenant_id, Project.category_id, Project.product_id,
                      Project.revision, Project.current_plan_id).where(
                          Project.id.in_(identities)).cte("history_project_scopes")
    queries = [select(literal("project").label("kind"), projects.c.id.label("project_id"),
                      func.jsonb_build_object(
                          "project_revision", projects.c.revision,
                          "current_plan_id", projects.c.current_plan_id).label("metadata"),
                      literal(0).label("position"))]

    def members(model, kind, fields, order, maximum, *, task_ids=None):
        rank = func.row_number().over(partition_by=model.project_id, order_by=order)
        query = select(literal(kind).label("kind"), model.project_id,
                       func.jsonb_build_object(*[part for key, column in fields
                                                for part in (key, column)]).label("metadata"),
                       rank.label("position")).join(projects, (
                           model.project_id == projects.c.id)
                           & (model.tenant_id == projects.c.tenant_id)
                           & (model.category_id == projects.c.category_id)
                           & (model.product_id == projects.c.product_id))
        if task_ids is not None:
            query = query.where(model.task_id.in_(task_ids))
        query = query.subquery()
        queries.append(select(query).where(query.c.position <= maximum))

    members(WorkTaskCurrent, "tasks", (
        ("task_id", WorkTaskCurrent.task_id), ("version_id", WorkTaskCurrent.version_id),
        ("revision", WorkTaskCurrent.revision)), (WorkTaskCurrent.task_id,), LIMIT + 1)
    task_scope = select(WorkTaskCurrent.task_id, func.row_number().over(
        partition_by=WorkTaskCurrent.project_id,
        order_by=WorkTaskCurrent.task_id).label("position")).join(projects, (
            WorkTaskCurrent.project_id == projects.c.id)
            & (WorkTaskCurrent.tenant_id == projects.c.tenant_id)
            & (WorkTaskCurrent.category_id == projects.c.category_id)
            & (WorkTaskCurrent.product_id == projects.c.product_id)).subquery()
    members(WorkCommitmentCurrent, "task_commitments", (
        ("task_id", WorkCommitmentCurrent.task_id), ("series_id", WorkCommitmentCurrent.series_id),
        ("promisor_id", WorkCommitmentCurrent.promisor_id),
        ("recipient_id", WorkCommitmentCurrent.recipient_id),
        ("version_id", WorkCommitmentCurrent.version_id),
        ("revision", WorkCommitmentCurrent.revision)),
        (WorkCommitmentCurrent.task_id, WorkCommitmentCurrent.series_id), LIMIT + 1,
        task_ids=select(task_scope.c.task_id).where(task_scope.c.position <= LIMIT))
    members(ProjectStatusUpdate, "named_status", (
        ("id", ProjectStatusUpdate.id), ("revision", ProjectStatusUpdate.revision)),
        (ProjectStatusUpdate.created_at.desc(), ProjectStatusUpdate.id.desc()), 1)
    members(GovernanceEvent, "governance", (
        ("id", GovernanceEvent.id), ("revision", GovernanceEvent.revision)),
        (GovernanceEvent.revision.desc(), GovernanceEvent.id.desc()), 1)
    queries[0] = queries[0].prefix_with("/* conversation_project_metadata */")
    return union_all(*queries)


def states(session, contexts):
    """Current visible pointers annotate changes; fixed dependency ACL owns hiding."""
    if not contexts:
        return {}
    values = {}
    for row in session.execute(statement({UUID(item["project_id"])
                                          for item in contexts})).mappings():
        identity = str(row["project_id"])
        value = values.setdefault(identity, {"members": {}})
        if row["kind"] == "project":
            value.update(row["metadata"])
        else:
            value["members"].setdefault(row["kind"], []).append(
                (row["position"], row["metadata"]))
    result = {}
    for context in contexts:
        expected = context["metadata_snapshot"]
        actual = values.get(context["project_id"])
        if actual is None or "project_revision" not in actual:
            result[digest(context)] = "hidden"
            continue
        changed = any(actual[key] != expected[key]
                      for key in ("project_revision", "current_plan_id"))
        task_scope_changed = False
        for key in ("tasks", "task_commitments"):
            if key == "task_commitments" and task_scope_changed:
                continue  # This fixed task set already differs from today's bounded set.
            members = [item for _position, item in sorted(actual["members"].get(key, []))]
            different = (members[:LIMIT] != expected[key]["items"]
                         or (len(members) > LIMIT) != expected[key]["has_more"])
            if key == "tasks":
                task_scope_changed = different
            changed |= different
        for key in ("named_status", "governance"):
            # New snapshots distinguish a confirmed empty record set from an
            # unavailable read. Old null pointers remain unknown.
            if expected.get(key + "_known", expected.get(key) is not None):
                members = actual["members"].get(key, [])
                pointer = members[0][1] if members else None
                changed |= pointer != expected[key]
        result[digest(context)] = "updated" if changed else "current"
    return result
