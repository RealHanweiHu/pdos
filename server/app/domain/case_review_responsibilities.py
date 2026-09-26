"""Current DCP/TR policy and unfinished-round obligations for personnel handover."""

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Select, exists, or_, select
from sqlalchemy.dialects.postgresql import JSONB

from app.db.schema import tables
from app.domain.product_workspace import _plain, digest


def statements(tenant: UUID, user: UUID) -> tuple[Select[Any], Select[Any]]:
    policy, review, case, project, stage = (
        tables.case_review_policies,
        tables.case_reviews,
        tables.development_cases,
        tables.projects,
        tables.stages,
    )
    newer_policy = policy.alias("handover_newer_case_policy")
    newer_review = review.alias("handover_newer_case_review")
    current_stage = stage.alias("handover_case_current_stage")
    current_policy = ~exists(
        select(newer_policy.c.id).where(
            newer_policy.c.tenant_id == policy.c.tenant_id,
            newer_policy.c.case_id == policy.c.case_id,
            newer_policy.c.review_kind == policy.c.review_kind,
            newer_policy.c.stage_code == policy.c.stage_code,
            newer_policy.c.version > policy.c.version,
        )
    )
    active_scope = or_(
        (policy.c.stage_code == "charter") & case.c.status.in_(("draft", "evaluating", "approved")),
        (policy.c.stage_code != "charter")
        & exists(
            select(project.c.id)
            .select_from(
                project.join(
                    stage,
                    (stage.c.tenant_id == project.c.tenant_id)
                    & (stage.c.workflow_id == project.c.workflow_id)
                    & (stage.c.code == policy.c.stage_code),
                ).join(
                    current_stage,
                    (current_stage.c.tenant_id == project.c.tenant_id)
                    & (current_stage.c.id == project.c.current_stage_id),
                )
            )
            .where(
                project.c.tenant_id == case.c.tenant_id,
                project.c.development_case_id == case.c.id,
                project.c.status.not_in(("completed", "archived")),
                stage.c.sequence >= current_stage.c.sequence,
            )
        ),
    )
    assigned = or_(
        policy.c.chair_user_id == user,
        policy.c.reviewer_ids.cast(JSONB).contains([str(user)]),
    )
    policies = (
        select(policy, case.c.title)
        .join(case, (case.c.tenant_id == policy.c.tenant_id) & (case.c.id == policy.c.case_id))
        .where(policy.c.tenant_id == tenant, current_policy, active_scope, assigned)
    )
    signoff = tables.case_review_signoffs
    unsigned = ~exists(
        select(signoff.c.id).where(
            signoff.c.tenant_id == review.c.tenant_id,
            signoff.c.review_id == review.c.id,
            signoff.c.reviewer_user_id == user,
        )
    )
    rounds = (
        select(review)
        .join(
            policy, (policy.c.tenant_id == review.c.tenant_id) & (policy.c.id == review.c.policy_id)
        )
        .join(case, (case.c.tenant_id == review.c.tenant_id) & (case.c.id == review.c.case_id))
        .where(
            review.c.tenant_id == tenant,
            review.c.state.in_(("draft", "in_review")),
            active_scope,
            ~exists(
                select(newer_review.c.id).where(
                    newer_review.c.tenant_id == review.c.tenant_id,
                    newer_review.c.case_id == review.c.case_id,
                    newer_review.c.review_kind == review.c.review_kind,
                    newer_review.c.stage_code == review.c.stage_code,
                    newer_review.c.round_no > review.c.round_no,
                )
            ),
            or_(
                review.c.created_by_user_id == user,
                current_policy & or_(policy.c.chair_user_id == user, assigned & unsigned),
            ),
        )
    )
    return policies, rounds


def groups(connection: Connection, tenant: UUID, source: UUID) -> list[dict[str, Any]]:
    result = []
    for query, key, label, parameter, reason in zip(
        statements(tenant, source),
        ("case_review_policies", "pending_case_reviews"),
        ("DCP/TR 当前具名评审政策", "DCP/TR 未完成评审责任"),
        ("policy", "review"),
        (
            "在原案例发布新具名政策；在办评审按新政策重新准备、送审和签核，原人员意见保留",
            "原准备人或批准人可撤回；其他有权准备人员可按当前政策另起新轮次，重新核对材料与签核",
        ),
        strict=True,
    ):
        items = [
            {
                "id": str(row["id"]),
                "title": f"{row['title']} · {row['review_kind']} / {row['stage_code']}",
                "href": f"/cases/{row['case_id']}/reviews?{parameter}={row['id']}",
                "basis": digest(_plain(row)),
            }
            for row in connection.execute(query.order_by(query.selected_columns.id)).mappings()
        ]
        if items:
            result.append(
                dict(
                    key=key,
                    label=label,
                    count=len(items),
                    can_transfer=False,
                    reasons=[reason],
                    items=items,
                )
            )
    return result
