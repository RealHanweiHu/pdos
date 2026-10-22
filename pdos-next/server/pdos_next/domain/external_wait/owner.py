"""Scoped immutable waiting records and current source proof in the caller's UOW."""

from sqlalchemy import select

from pdos_next.change_implementation_owner import common_group
from pdos_next.domain.work_management.owner import project as project
from pdos_next.domain.work_management.owner import sources_current as artifact_sources_current
from pdos_next.service import digest

from . import calendar_owner
from .models import EVENT, OPERATION, ExternalWaitCurrent, ExternalWaitVersion
from .rules import require
from .schemas import Snapshot


def retained(s, ctx, pid, row):
    require(
        row is not None
        and (row.tenant_id, row.category_id, row.product_id)
        == (ctx.tenant_id, ctx.category_id, pid),
        "固定等待不存在或不可读。",
        "FORBIDDEN_SCOPE",
        403,
    )
    require(digest(row.body) == row.body_sha256, "固定等待摘要无法核对。", "INTEGRITY_MISMATCH")
    common_group(s, ctx, pid, row, operation=OPERATION, event=EVENT, key_binding="project_work")
    snapshot = Snapshot.model_validate(row.body)
    require(
        (snapshot.wait_id, snapshot.revision, snapshot.state)
        == (row.wait_id, row.revision, row.state),
        "等待快照与版本不一致。",
        "INTEGRITY_MISMATCH",
    )
    return snapshot


def waiting(s, ctx, pid, wait_id, *, revision=None, lock=False, fixed=False):
    query = select(ExternalWaitCurrent).where(
        ExternalWaitCurrent.tenant_id == ctx.tenant_id,
        ExternalWaitCurrent.category_id == ctx.category_id,
        ExternalWaitCurrent.product_id == pid,
        ExternalWaitCurrent.wait_id == wait_id,
    )
    pointer = s.scalar(query.with_for_update() if lock else query)
    require(pointer is not None, "等待不存在或不可读。", "FORBIDDEN_SCOPE", 403)
    if fixed:
        row = s.scalar(
            select(ExternalWaitVersion).where(
                ExternalWaitVersion.tenant_id == ctx.tenant_id,
                ExternalWaitVersion.product_id == pid,
                ExternalWaitVersion.wait_id == wait_id,
                ExternalWaitVersion.revision == revision,
            )
        )
    else:
        require(
            revision is None or revision == pointer.revision,
            "等待已续版，请重新核对。",
            "VERSION_CONFLICT",
        )
        row = s.get(ExternalWaitVersion, pointer.version_id)
    return row, retained(s, ctx, pid, row), pointer


def sources_current(s, ctx, pid, project_id, basis):
    artifact_sources_current(s, ctx, pid, basis)
    if basis.get("calendar") is not None:
        calendar_owner.recheck(s, ctx, pid, project_id, basis["calendar"])
    return True
