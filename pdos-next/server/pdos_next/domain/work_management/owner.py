"""Actual project, immutable work and direct-source metadata in the caller's UOW."""

from uuid import UUID

from sqlalchemy import select

from pdos_next.change_implementation_owner import common_group
from pdos_next.domain.projects.models import Project
from pdos_next.models import Artifact, OriginalSecurity
from pdos_next.service import digest, require_access

from .constants import OPERATIONS
from .models import WorkCommitmentCurrent, WorkCommitmentVersion, WorkTaskCurrent, WorkTaskVersion
from .rules import require
from .schemas import CommitmentSnapshot, TaskSnapshot


def project(s, ctx, pid, identity, *, lock=False):
    require_access(s, ctx, pid, write=lock, lock=lock)
    query = select(Project).where(
        Project.tenant_id == ctx.tenant_id,
        Project.category_id == ctx.category_id,
        Project.product_id == pid,
        Project.id == identity,
    )
    row = s.scalar(query.with_for_update() if lock else query)
    require(row is not None, "项目不存在或不在当前受众内。", "FORBIDDEN_SCOPE", 403)
    return row


def retained(s, ctx, pid, row):
    require(
        row is not None
        and (row.tenant_id, row.category_id, row.product_id)
        == (ctx.tenant_id, ctx.category_id, pid),
        "固定工作记录不可读。",
        "FORBIDDEN_SCOPE",
        403,
    )
    require(digest(row.body) == row.body_sha256, "工作记录摘要无法核对。", "INTEGRITY_MISMATCH")
    common_group(
        s,
        ctx,
        pid,
        row,
        operation=row.operation,
        event=OPERATIONS[row.operation][1],
        key_binding="project_work",
    )
    return row


def task(s, ctx, pid, task_id, *, revision=None, lock=False, fixed=False):
    pointer = s.scalar(
        select(WorkTaskCurrent)
        .where(
            WorkTaskCurrent.tenant_id == ctx.tenant_id,
            WorkTaskCurrent.product_id == pid,
            WorkTaskCurrent.task_id == task_id,
        )
        .with_for_update()
        if lock
        else select(WorkTaskCurrent).where(
            WorkTaskCurrent.tenant_id == ctx.tenant_id,
            WorkTaskCurrent.product_id == pid,
            WorkTaskCurrent.task_id == task_id,
        )
    )
    require(pointer is not None, "任务不存在或不可读。", "FORBIDDEN_SCOPE", 403)
    if fixed:
        row = s.scalar(
            select(WorkTaskVersion).where(
                WorkTaskVersion.tenant_id == ctx.tenant_id,
                WorkTaskVersion.product_id == pid,
                WorkTaskVersion.task_id == task_id,
                WorkTaskVersion.revision == revision,
            )
        )
    else:
        require(
            revision is None or revision == pointer.revision,
            "任务已续版，请重新核对。",
            "VERSION_CONFLICT",
        )
        row = s.get(WorkTaskVersion, pointer.version_id)
    retained(s, ctx, pid, row)
    snapshot = TaskSnapshot.model_validate(row.body)
    require(
        snapshot.task_id == row.task_id
        and snapshot.revision == row.revision
        and snapshot.state == row.state,
        "任务快照与固定记录不一致。",
        "INTEGRITY_MISMATCH",
    )
    return row, snapshot, pointer


def commitment(s, ctx, pid, task_id, actor_id, recipient_id, *, lock=False):
    query = select(WorkCommitmentCurrent).where(
        WorkCommitmentCurrent.tenant_id == ctx.tenant_id,
        WorkCommitmentCurrent.product_id == pid,
        WorkCommitmentCurrent.task_id == task_id,
        WorkCommitmentCurrent.promisor_id == actor_id,
        WorkCommitmentCurrent.recipient_id == recipient_id,
    )
    pointer = s.scalar(query.with_for_update() if lock else query)
    if pointer is None:
        return None, None, None
    row = retained(s, ctx, pid, s.get(WorkCommitmentVersion, pointer.version_id))
    snapshot = CommitmentSnapshot.model_validate(row.body)
    require(snapshot.revision == row.revision, "承诺快照与版本不一致。", "INTEGRITY_MISMATCH")
    return row, snapshot, pointer


def sources_current(s, ctx, pid, basis):
    """Recheck retained direct metadata, never reload historical source bodies."""
    if basis.get("g0_open_item") is not None:
        from .g0_sources import sources_current as g0_current

        g0_current(s, ctx, pid, basis["g0_open_item"])
    for expected in basis.get("artifacts", []):
        actual = s.execute(
            select(
                Artifact.id,
                Artifact.revision,
                Artifact.status,
                Artifact.content_hash,
                Artifact.owner_id,
                Artifact.visibility,
                Artifact.original_id,
                Artifact.product_id,
            ).where(
                Artifact.tenant_id == ctx.tenant_id,
                Artifact.category_id == ctx.category_id,
                Artifact.id == UUID(expected["id"]),
            )
        ).first()
        require(actual is not None, "固定原件不在当前受众内。", "SOURCE_UNAVAILABLE", 403)
        require(actual.status == "active", "固定原件已撤回。", "SOURCE_UNAVAILABLE")
        require(
            (actual.revision, actual.content_hash, str(actual.owner_id), actual.visibility)
            == (
                expected["revision"],
                expected["hash"],
                expected["owner_id"],
                expected["visibility"],
            ),
            "固定原件版本或受众已变化。",
            "SOURCE_STALE",
        )
        if "original" in expected:
            original = expected["original"]
            state = s.scalar(
                select(OriginalSecurity).where(
                    OriginalSecurity.tenant_id == ctx.tenant_id,
                    OriginalSecurity.original_id == actual.original_id,
                    OriginalSecurity.product_id.is_not_distinct_from(actual.product_id),
                )
            )
            require(
                state is not None
                and str(actual.original_id) == original["id"]
                and state.epoch == original["epoch"]
                and state.source_state == state.disposition == "active",
                "固定原件的安全或撤回状态已变化。",
                "SOURCE_UNAVAILABLE",
            )
    return True
