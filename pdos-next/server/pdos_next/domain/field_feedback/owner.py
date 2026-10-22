"""Ordinary-caller ownership of actual feedback and native physical location."""

from copy import deepcopy

from sqlalchemy import select

from pdos_next.domain.configurations import service as configurations
from pdos_next.domain.knowledge import provenance
from pdos_next.domain.knowledge.service import _target_content
from pdos_next.domain.projects.models import ProjectProductLink
from pdos_next.domain.work_management.owner import project
from pdos_next.domain.work_management.rules import require
from pdos_next.errors import DomainError
from pdos_next.models import Receipt
from pdos_next.service import digest, require_access

from .models import FieldFeedbackCurrent, FieldFeedbackVersion
from .schemas import LocatePayload


def retained(s, ctx, row):
    require(
        row is not None and (row.tenant_id, row.category_id) == (ctx.tenant_id, ctx.category_id),
        "反馈不存在或不可读。",
        "FORBIDDEN_SCOPE",
        403,
    )
    require_access(s, ctx, row.product_id)
    require(digest(row.body) == row.body_sha256, "反馈内容摘要不一致。", "INTEGRITY_MISMATCH")
    receipt = s.get(Receipt, row.receipt_id)
    require(
        receipt is not None
        and (
            receipt.subject_id,
            receipt.subject_revision,
            receipt.command_id,
            receipt.operation,
            receipt.product_id,
            receipt.category_id,
            receipt.actor_id,
            receipt.requester_id,
            receipt.request_digest,
            receipt.intent_digest,
            receipt.confirmation_id,
        )
        == (
            row.id,
            row.revision,
            row.command_id,
            row.operation,
            row.product_id,
            row.category_id,
            row.actor_id,
            row.requester_id,
            row.request_digest,
            row.intent_digest,
            row.confirmation_id,
        ),
        "反馈共同回执无法核对。",
        "INTEGRITY_MISMATCH",
    )
    return row


def current(s, ctx, identity, revision=None, *, lock=False):
    query = select(FieldFeedbackCurrent).where(
        FieldFeedbackCurrent.tenant_id == ctx.tenant_id,
        FieldFeedbackCurrent.category_id == ctx.category_id,
        FieldFeedbackCurrent.feedback_id == identity,
    )
    pointer = s.scalar(query.with_for_update() if lock else query)
    require(pointer is not None, "反馈不存在或不可读。", "FORBIDDEN_SCOPE", 403)
    require(
        revision is None or pointer.revision == revision,
        "反馈已变化，请重新核对。",
        "VERSION_CONFLICT",
    )
    row = retained(s, ctx, s.get(FieldFeedbackVersion, pointer.version_id))
    require(
        all(
            getattr(pointer, key) == getattr(row, key)
            for key in (
                "tenant_id",
                "category_id",
                "product_id",
                "project_id",
                "owner_id",
                "visibility",
                "feedback_id",
                "revision",
            )
        ),
        "反馈 Current 与实际版本不一致。",
        "INTEGRITY_MISMATCH",
    )
    return row, pointer


def location(s, ctx, pid, payload):
    require(pid is not None, "定位须选择实际型号。", "MISSING_REQUIRED_EVIDENCE", 422)
    engineering, eview = configurations.get_engineering(
        s, ctx, pid, payload.engineering_configuration.id
    )
    require(
        engineering.revision == payload.engineering_configuration.revision,
        "工程配置版本不一致。",
        "VERSION_CONFLICT",
    )
    views, rows = [eview], [engineering]
    require(eview["source_status"] == "current", "工程配置来源待核对。", "SOURCE_STALE")
    manufacturing = None
    if payload.manufacturing_configuration:
        manufacturing, mview = configurations.get_process(
            s, ctx, pid, payload.manufacturing_configuration.id
        )
        require(
            manufacturing.revision == payload.manufacturing_configuration.revision
            and manufacturing.engineering_configuration_id == engineering.id,
            "制造配置与实际工程配置不一致。",
            "CONFIGURATION_MISMATCH",
        )
        require(mview["source_status"] == "current", "制造配置来源待核对。", "SOURCE_STALE")
        views.append(mview)
        rows.append(manufacturing)
    project_id = payload.project_id
    if payload.batch:
        from pdos_next.domain.build_execution.service import get_actual_configuration, get_lot

        lot, lview = get_lot(s, ctx, pid, payload.batch.id)
        actual, aview = get_actual_configuration(s, ctx, pid, lot.actual_configuration_id)
        require(
            lot.revision == payload.batch.revision
            and actual.actual_engineering_configuration_id == engineering.id
            and actual.actual_engineering_revision == engineering.revision
            and manufacturing is not None
            and actual.actual_manufacturing_configuration_id == manufacturing.id
            and actual.actual_manufacturing_revision == manufacturing.revision
            and project_id in (None, lot.project_id),
            "批次、实际配置与项目不一致。",
            "CONFIGURATION_MISMATCH",
        )
        project_id = lot.project_id
        views.extend((lview, aview))
        rows.extend((lot, actual))
    if project_id:
        native_project = project(s, ctx, pid, project_id)
        link = s.scalar(
            select(ProjectProductLink).where(
                ProjectProductLink.tenant_id == ctx.tenant_id,
                ProjectProductLink.product_id == pid,
                ProjectProductLink.project_id == project_id,
                ProjectProductLink.definition_id == engineering.definition_id,
                ProjectProductLink.definition_revision == engineering.definition_revision,
            )
        )
        require(link is not None, "配置不属于本项目固定的型号定义。", "FORBIDDEN_SCOPE", 403)
        rows.append(native_project)
    refs, reads = _target_content(s, ctx, pid, views)
    value = {
        "state": "known",
        "product_id": str(pid),
        "project_id": str(project_id) if project_id else None,
        **{
            key: getattr(payload, key).model_dump(mode="json") if getattr(payload, key) else None
            for key in ("engineering_configuration", "manufacturing_configuration", "batch")
        },
        "sources": [ref.model_dump(mode="json") for ref in refs],
    }
    return value, refs, reads, any(row.visibility != "category" for row in rows)


def view(s, ctx, row):
    status = "current"
    try:
        provenance.sources_current(s, ctx, row.source_basis)
    except DomainError:
        status = "needs_recheck"
    return {
        **deepcopy(row.body),
        "id": str(row.feedback_id),
        "feedback_id": str(row.feedback_id),
        "version_id": str(row.id),
        "revision": row.revision,
        "product_id": str(row.product_id) if row.product_id else None,
        "project_id": str(row.project_id) if row.project_id else None,
        "owner_id": str(row.owner_id),
        "visibility": row.visibility,
        "receipt_id": str(row.receipt_id),
        "sources": deepcopy(row.sources),
        "required_source_read_set": deepcopy(row.reads),
        "source_status": status,
        "is_current": True,
    }


def get_feedback_for_change(s, ctx, pid, feedback_id, revision=None, write=False):
    row, _ = current(s, ctx, feedback_id, revision, lock=write)
    require(
        row.product_id == pid and pid is not None and row.project_id is not None,
        "现场反馈须定位到实际型号、项目和配置后再进入变更。",
        "MISSING_REQUIRED_EVIDENCE",
        422,
    )
    value = view(s, ctx, row)
    require(
        value["location"] is not None and value["source_status"] == "current",
        "未定位或来源待核对的反馈不能作为新变更起点。",
        "SOURCE_STALE",
    )
    raw = value["location"]
    location(
        s,
        ctx,
        pid,
        LocatePayload.model_validate(
            {
                "feedback": {"id": str(row.feedback_id), "revision": row.revision},
                "project_id": raw["project_id"],
                "engineering_configuration": raw["engineering_configuration"],
                "manufacturing_configuration": raw["manufacturing_configuration"],
                "batch": raw["batch"],
                "sources": row.sources,
                "reason": "重新核对实际反馈定位",
            }
        ),
    )
    return row, value
