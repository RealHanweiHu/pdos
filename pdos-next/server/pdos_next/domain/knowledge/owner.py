"""Resolve native versions and their current ordinary caller scope."""

from copy import deepcopy

from sqlalchemy import select

from pdos_next.domain.configurations import service as configurations
from pdos_next.domain.preproject.access import human
from pdos_next.domain.projects.models import ProjectProductLink
from pdos_next.domain.work_management.owner import project
from pdos_next.models import Receipt
from pdos_next.service import digest, require_access

from .models import (
    DesignRuleCurrent,
    DesignRuleVersion,
    KnowledgeCandidateCurrent,
    KnowledgeCandidateVersion,
)
from .rules import require


def retained(s, ctx, row):
    require(
        row is not None and (row.tenant_id, row.category_id) == (ctx.tenant_id, ctx.category_id),
        "知识版本不在当前可读范围。",
        "FORBIDDEN_SCOPE",
        403,
    )
    require_access(s, ctx, row.product_id)
    require(digest(row.body) == row.body_sha256, "知识版本摘要不一致。", "INTEGRITY_MISMATCH")
    receipt = s.get(Receipt, row.receipt_id)
    require(
        receipt is not None
        and (
            receipt.subject_id,
            receipt.subject_revision,
            receipt.operation,
            receipt.product_id,
            receipt.category_id,
            receipt.command_id,
            receipt.actor_id,
            receipt.requester_id,
            receipt.request_digest,
            receipt.intent_digest,
            receipt.confirmation_id,
        )
        == (
            row.id,
            row.revision,
            row.operation,
            row.product_id,
            row.category_id,
            row.command_id,
            row.actor_id,
            row.requester_id,
            row.request_digest,
            row.intent_digest,
            row.confirmation_id,
        ),
        "知识版本共同回执无法核对。",
        "INTEGRITY_MISMATCH",
    )
    return row


def current(s, ctx, ref, *, rule=False, lock=False):
    model, pointer_model, key = (
        (DesignRuleVersion, DesignRuleCurrent, "rule_id")
        if rule
        else (KnowledgeCandidateVersion, KnowledgeCandidateCurrent, "candidate_id")
    )
    query = select(pointer_model).where(
        pointer_model.tenant_id == ctx.tenant_id,
        pointer_model.category_id == ctx.category_id,
        getattr(pointer_model, key) == ref.id,
    )
    pointer = s.scalar(query.with_for_update() if lock else query)
    require(pointer is not None, "知识对象不存在或不可读。", "FORBIDDEN_SCOPE", 403)
    require(pointer.revision == ref.revision, "知识对象已续版，请重新核对。", "VERSION_CONFLICT")
    row = retained(s, ctx, s.get(model, pointer.version_id))
    require(
        all(
            getattr(pointer, field) == getattr(row, field)
            for field in (
                "category_id",
                "product_id",
                "project_id",
                "owner_id",
                "visibility",
                key,
                "revision",
            )
        ),
        "知识 Current 与实际版本不一致。",
        "INTEGRITY_MISMATCH",
    )
    return row, pointer


def target(s, ctx, pid, project_id, ref, *, lock=False):
    human(s, ctx)
    native_project = project(s, ctx, pid, project_id, lock=lock)
    getter = (
        configurations.get_engineering
        if ref.kind == "engineering_configuration"
        else configurations.get_process
    )
    row, view = getter(s, ctx, pid, ref.id)
    require(row.revision == ref.revision, "适用配置版本已变化。", "VERSION_CONFLICT")
    require(view["source_status"] == "current", "适用配置来源需要重新核对。", "SOURCE_STALE")
    engineering_id = (
        row.id if ref.kind == "engineering_configuration" else row.engineering_configuration_id
    )
    engineering = (
        row
        if ref.kind == "engineering_configuration"
        else configurations.get_engineering(s, ctx, pid, engineering_id)[0]
    )
    link = s.scalar(
        select(ProjectProductLink).where(
            ProjectProductLink.tenant_id == ctx.tenant_id,
            ProjectProductLink.product_id == pid,
            ProjectProductLink.project_id == native_project.id,
            ProjectProductLink.definition_id == engineering.definition_id,
            ProjectProductLink.definition_revision == engineering.definition_revision,
        )
    )
    require(link is not None, "适用配置须属于本项目固定的实际型号定义。", "FORBIDDEN_SCOPE", 403)
    metadata = {
        **ref.model_dump(mode="json"),
        "product_id": str(pid),
        "owner_id": str(row.owner_id),
        "visibility": row.visibility,
        "sources": deepcopy(row.sources),
        "required_source_read_set": deepcopy(row.required_source_read_set),
    }
    return native_project, row, view, metadata
