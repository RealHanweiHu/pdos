"""Retained proofs and exact Current binding in ordinary project scope."""

from sqlalchemy import select

from pdos_next.change_implementation_owner import common_group
from pdos_next.domain.preproject.models import ProjectOpenItem
from pdos_next.domain.work_management.models import BINDING
from pdos_next.domain.work_management.rules import require
from pdos_next.service import digest

from .models import EVENT, OPERATION, ProjectRiskFollowup, ProjectRiskFollowupCurrent


def retained(s, ctx, pid, row):
    require(
        row is not None
        and (row.tenant_id, row.category_id, row.product_id)
        == (ctx.tenant_id, ctx.category_id, pid),
        "风险跟进记录不在当前受众内。",
        "FORBIDDEN_SCOPE",
        403,
    )
    require(digest(row.body) == row.body_sha256, "风险跟进摘要无法核对。", "INTEGRITY_MISMATCH")
    require(
        row.body
        == {
            "risk_id": str(row.risk_id),
            "decision_id": str(row.g0_decision_id),
            "revision": row.revision,
            "state": row.state,
            "summary": row.body.get("summary"),
        }
        and isinstance(row.body.get("summary"), str)
        and row.body["summary"].strip(),
        "风险跟进快照与实际记录不一致。",
        "INTEGRITY_MISMATCH",
    )
    common_group(s, ctx, pid, row, operation=OPERATION, event=EVENT, key_binding="project_work")
    return row


def current(s, ctx, pid, project, risk_id, *, lock=False):
    query = select(ProjectRiskFollowupCurrent).where(
        ProjectRiskFollowupCurrent.tenant_id == ctx.tenant_id,
        ProjectRiskFollowupCurrent.risk_id == risk_id,
    )
    pointer = s.scalar(query.with_for_update() if lock else query)
    if pointer is None:
        return None, None
    row = retained(s, ctx, pid, s.get(ProjectRiskFollowup, pointer.version_id))
    require(
        all(getattr(pointer, field) == getattr(row, field) for field in BINDING)
        and (pointer.product_id, pointer.project_id, pointer.owner_id, pointer.visibility)
        == (pid, project.id, project.owner_id, project.visibility)
        and (pointer.risk_id, pointer.g0_decision_id, pointer.revision, pointer.state)
        == (row.risk_id, row.g0_decision_id, row.revision, row.state),
        "风险跟进 Current 无法核对。",
        "INTEGRITY_MISMATCH",
    )
    return row, pointer


def legacy_status(s, ctx, pid, project_id, risk_id):
    return s.scalar(
        select(ProjectOpenItem.status).where(
            ProjectOpenItem.tenant_id == ctx.tenant_id,
            ProjectOpenItem.category_id == ctx.category_id,
            ProjectOpenItem.product_id == pid,
            ProjectOpenItem.project_id == project_id,
            ProjectOpenItem.id == risk_id,
            ProjectOpenItem.kind == "risk",
        )
    )
