"""Upcoming adopted stage dates from the still-applicable approved baseline.

These dates are frozen estimates, never promises, actual completion or gate
decisions. Reads stay in the subscriber's ordinary Human RR/RLS transaction.
"""

from datetime import datetime, timedelta
from itertools import islice

from sqlalchemy import String, and_, cast, literal, or_, select
from sqlalchemy.orm import load_only

from pdos_next.domain.project_governance.models import GovernanceEvent
from pdos_next.domain.projects.models import Project
from pdos_next.personal_summary import LIMIT, _categories, _item, _time, _url
from pdos_next.personal_summary_schemas import Coverage, NextStep, ObjectRef, Person, Relationship

KIND = "upcoming_stage_gate"
WINDOW = timedelta(days=7)


def query(ctx, selection, *, product_id=None):
    p, e = Project, GovernanceEvent
    latest = (
        select(e.id)
        .where(
            e.tenant_id == p.tenant_id,
            e.category_id == p.category_id,
            e.product_id == p.product_id,
            e.project_id == p.id,
        )
        .order_by(e.revision.desc())
        .limit(1)
        .correlate(p)
        .scalar_subquery()
    )
    base = (
        select(p, e)
        .join(
            e,
            and_(
                e.id == latest,
                e.tenant_id == p.tenant_id,
                e.category_id == p.category_id,
                e.product_id == p.product_id,
                e.project_id == p.id,
            ),
        )
        .where(
            p.tenant_id == ctx.tenant_id,
            p.current_plan_id.is_not(None),
            e.body["baseline"]["plan"]["id"].astext == cast(p.current_plan_id, String),
            or_(
                p.owner_id == ctx.requester_id if "action" in selection.groups else literal(False),
                p.id.in_(selection.followed_project_ids)
                if "following" in selection.groups
                else literal(False),
            ),
        )
    )
    return _categories(base, p.category_id, selection, product=p.product_id, product_id=product_id)


def _date(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return _time(parsed) if parsed.utcoffset() is not None else None


def items(project, event, ctx, at, selection):
    """Only actual project owner or explicit subscription creates relevance."""
    mine = project.owner_id == ctx.requester_id and "action" in selection.groups
    followed = project.id in selection.followed_project_ids and "following" in selection.groups
    if not mine and not followed:
        return []
    body = event.body
    baseline = body.get("baseline")
    if (
        not baseline
        or not project.current_plan_id
        or baseline.get("plan", {}).get("id") != str(project.current_plan_id)
        or not baseline.get("approved_by")
        or not baseline.get("at")
    ):
        return []
    tasks = {task["key"]: task for task in baseline.get("forecast", {}).get("tasks", [])}
    at = _time(at)
    rows = []
    for index, stage in enumerate(body.get("stages", [])):
        if index < body["position"]:
            continue
        task_key = body.get("bindings", {}).get(stage["id"], {}).get("task_key")
        date = tasks.get(task_key, {}).get("latest_finish")
        finish = _date(date)
        if finish is None or not at <= finish <= at + WINDOW:
            continue
        rows.append(
            _item(
                identity=f"upcoming_stage_gate:{project.id}:{stage['id']}",
                kind=KIND,
                group="action" if mine else "following",
                title=f"临近门禁 · {project.name} · {stage['name']}",
                source=ObjectRef(
                    kind="project_governance",
                    id=project.id,
                    version_id=event.id,
                    revision=event.revision,
                    category_id=project.category_id,
                    product_id=project.product_id,
                    project_id=project.id,
                ),
                recorded_at=event.created_at,
                state="approved_baseline_estimate_in_window",
                relationship=Relationship(
                    kind="project_owner" if mine else "subscriber",
                    text="你是这个项目的当前具名负责人。" if mine else "这是你显式选择关注的项目。",
                ),
                next_step=NextStep(
                    kind="navigation",
                    responsible=Person(id=project.owner_id),
                    text=(
                        "请项目负责人在原阶段核对准备安排及出口依据；"
                        "日期仅为已批准基线预计，不代表承诺、实际完成或门禁通过。"
                    ),
                ),
                url=_url(project.category_id, project.id),
                facts={
                    "stage_id": stage["id"],
                    "stage_key": stage["key"],
                    "stage_name": stage["name"],
                    "stage_position_as_recorded": "current"
                    if index == body["position"]
                    else "upcoming",
                    "task_key": task_key,
                    "baseline_ref": {"id": baseline["id"], "revision": baseline["revision"]},
                    "plan_as_approved": baseline["plan"],
                    "baseline_approved_by": baseline["approved_by"],
                    "baseline_approved_at_as_recorded": baseline["at"],
                    "baseline_latest_finish_as_recorded": date,
                    "date_kind": "approved_baseline_estimate",
                },
            )
        )
    return rows


def read(s, ctx, selection, at, *, product_id=None):
    if KIND in selection.excluded_kinds or not set(selection.groups) & {"action", "following"}:
        return [], []
    p, e = Project, GovernanceEvent
    found = s.execute(
        query(ctx, selection, product_id=product_id)
        .options(
            load_only(
                p.id,
                p.tenant_id,
                p.category_id,
                p.product_id,
                p.owner_id,
                p.name,
                p.current_plan_id,
            ),
            load_only(e.id, e.revision, e.body, e.created_at),
        )
        .order_by(e.created_at.desc(), e.id.desc())
        .limit(LIMIT + 1)
    ).all()
    rows = list(
        islice(
            (
                item
                for project, event in found[:LIMIT]
                for item in items(project, event, ctx, at, selection)
            ),
            LIMIT + 1,
        )
    )
    return rows[:LIMIT], [
        Coverage(
            source=KIND,
            returned=min(len(rows), LIMIT),
            has_more=len(found) > LIMIT or len(rows) > LIMIT,
        )
    ]
