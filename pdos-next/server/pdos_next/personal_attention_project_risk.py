"""Native G0 risk follow-up responsibility, projected without business writes.

A linked task's progress is independent of this risk's follow-up state. The G0
arrangement date remains a date; this reader never invents a promise or timezone.
"""

from sqlalchemy import String, and_, case, cast, func, literal, or_, select
from sqlalchemy.orm import aliased

from pdos_next import models as registered_models  # noqa: F401 -- ordinary native registry
from pdos_next.domain.preproject.models import ProjectOpenItem
from pdos_next.domain.project_risk.models import ProjectRiskFollowup, ProjectRiskFollowupCurrent
from pdos_next.domain.projects.models import Project
from pdos_next.domain.work_management.models import BINDING, SCOPE
from pdos_next.models import Grant
from pdos_next.personal_attention_common import columns


def queries(ctx, queue=None):
    """Read this actual G0 follow-up person's open risks in the decide queue."""
    if queue is not None and queue != "decide":
        return ()

    item, current, version = ProjectOpenItem, ProjectRiskFollowupCurrent, ProjectRiskFollowup
    any_current = aliased(ProjectRiskFollowupCurrent, name="native_risk_any_current")
    no_current = (
        ~select(any_current.id)
        .where(
            any_current.tenant_id == item.tenant_id,
            any_current.risk_id == item.id,
        )
        .exists()
    )
    initial = current.id.is_(None)
    current_open = and_(current.id.is_not(None), version.id.is_not(None), current.state == "open")
    query = (
        select(
            *columns(
                key=literal("project_risk:") + cast(item.id, String),
                kind="project_risk",
                queue="decide",
                tenant_id=item.tenant_id,
                source_id=item.id,
                version_id=case((initial, item.id), else_=version.id),
                revision=version.revision,
                category_id=item.category_id,
                product_id=item.product_id,
                project_id=item.project_id,
                owner_id=Project.owner_id,
                visibility=Project.visibility,
                recorded_at=case((initial, item.created_at), else_=version.created_at),
                title=item.title,
                reason="你是 G0 安排的风险跟进人；原安排期限不构成个人承诺，内部跟进不作专业审批。",
                state=case((initial, literal("open")), else_=version.state),
                responsible_id=item.owner_id,
                responsibility="g0_risk_followup",
                target="project",
                due_at=None,
                details=func.jsonb_build_object(
                    "view",
                    "work",
                    "g0_due_date",
                    cast(item.due_date, String),
                    "decision_id",
                    cast(item.g0_decision_id, String),
                    "internal_followup_only",
                    True,
                ),
                blocked_code=case((Grant.can_write.is_(True), None), else_="READ_ONLY"),
                blocked_message=case(
                    (Grant.can_write.is_(True), None),
                    else_="当前只有读取权限；请在原项目核对办理权限。",
                ),
                valid_until=Grant.expires_at,
            )
        )
        .select_from(item)
        .join(
            Project,
            and_(
                Project.tenant_id == item.tenant_id,
                Project.category_id == item.category_id,
                Project.product_id == item.product_id,
                Project.id == item.project_id,
                Project.g0_decision_id == item.g0_decision_id,
            ),
        )
        .outerjoin(
            current,
            and_(
                *(getattr(current, key) == getattr(item, key) for key in SCOPE),
                current.owner_id == Project.owner_id,
                current.visibility == Project.visibility,
                current.risk_id == item.id,
                current.g0_decision_id == item.g0_decision_id,
            ),
        )
        .outerjoin(
            version,
            and_(
                *(getattr(current, key) == getattr(version, key) for key in BINDING),
                current.version_id == version.id,
                current.risk_id == version.risk_id,
                current.g0_decision_id == version.g0_decision_id,
                current.revision == version.revision,
                current.state == version.state,
                version.g0_decision_id == item.g0_decision_id,
            ),
        )
        .outerjoin(
            Grant,
            and_(
                Grant.tenant_id == item.tenant_id,
                Grant.category_id == item.category_id,
                Grant.principal_id == ctx.requester_id,
                or_(
                    Grant.expires_at.is_(None),
                    Grant.expires_at > func.transaction_timestamp(),
                ),
            ),
        )
        .where(
            item.tenant_id == ctx.tenant_id,
            item.kind == "risk",
            item.status == "open",
            item.owner_id == ctx.requester_id,
            or_(and_(initial, no_current), current_open),
        )
    )
    return (query,)
