"""Unresolved actor-owned Issue work, filtered before stable history pagination."""

from typing import Any
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select

from app.ai.issue_event_runs import history_query
from app.db.schema import tables


def attention_query(tenant: UUID, actor: UUID, project: UUID) -> Select[Any]:
    run, result, application, review = (
        tables.agent_runs,
        tables.ai_issue_event_results,
        tables.ai_issue_applications,
        tables.ai_issue_proposal_reviews,
    )
    newer = run.alias("newer_issue_run")
    later = (
        select(newer.c.id)
        .where(
            newer.c.tenant_id == run.c.tenant_id,
            newer.c.project_id == run.c.project_id,
            newer.c.requested_by_user_id == run.c.requested_by_user_id,
            newer.c.context_version == run.c.context_version,
            newer.c.agent_key == run.c.agent_key,
            newer.c.run_context["issue_event_event_row_id"]
            == run.c.run_context["issue_event_event_row_id"],
            or_(
                newer.c.created_at > run.c.created_at,
                and_(newer.c.created_at == run.c.created_at, newer.c.id > run.c.id),
            ),
        )
        .correlate(run)
        .exists()
    )
    applied = (
        select(application.c.id)
        .where(
            application.c.tenant_id == run.c.tenant_id,
            application.c.project_id == run.c.project_id,
            application.c.source_key
            == run.c.run_context["issue_event_source"]["source_key"].as_string(),
        )
        .correlate(run)
        .exists()
    )
    decision = (
        select(review.c.action)
        .where(
            review.c.tenant_id == run.c.tenant_id,
            review.c.project_id == run.c.project_id,
            review.c.result_id == result.c.id,
        )
        .order_by(review.c.version.desc())
        .limit(1)
        .correlate(run, result)
        .scalar_subquery()
    )
    return (
        history_query(tenant, actor, project)
        .outerjoin(
            result,
            (result.c.tenant_id == run.c.tenant_id)
            & (result.c.run_id == run.c.id)
            & (result.c.project_id == run.c.project_id),
        )
        .where(
            run.c.status.in_(("failed", "degraded", "succeeded")),
            ~later,
            ~applied,
            func.coalesce(decision, "unreviewed") != "decline",
            or_(run.c.status != "succeeded", result.c.id.is_not(None)),
        )
    )
