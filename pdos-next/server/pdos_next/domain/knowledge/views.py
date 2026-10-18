"""Readable current knowledge, fixed version history and explicit new-use status."""

from sqlalchemy import or_, select

from pdos_next.domain.configurations.models import EngineeringConfiguration, ProcessRevision
from pdos_next.domain.professional_authority import service as authority
from pdos_next.domain.projects.models import Project
from pdos_next.errors import DomainError
from pdos_next.models import Principal, now
from pdos_next.service import require_access

from . import owner, provenance, rules
from .models import (
    DesignRuleCurrent,
    DesignRuleVersion,
    KnowledgeCandidateCurrent,
    KnowledgeCandidateVersion,
)
from .schemas import RULE_OP, TargetConfiguration


def _history(rows):
    return [
        {
            "id": str(row.id),
            "revision": row.revision,
            "actor_id": str(row.actor_id),
            "created_at": row.created_at.isoformat(),
            "receipt_id": str(row.receipt_id),
        }
        for row in rows
    ]


def _usability(s, ctx, row, at):
    reasons = []
    for check in (provenance.sources_current, provenance.results_current):
        try:
            check(s, ctx, row.source_basis)
        except DomainError as failure:
            reasons.append(failure.code)
    try:
        target = TargetConfiguration.model_validate(row.body["applicability"]["target"])
        owner.target(s, ctx, row.product_id, row.project_id, target)
    except DomainError as failure:
        reasons.append(failure.code)
    checked = authority.recheck_snapshot(
        s, ctx, row.product_id, row.project_id, row.source_basis["professional"], at
    )
    if not checked["current"]:
        reasons.extend(checked["reason_codes"])
    return rules.usability(at, row.valid_from, row.valid_until, reasons)


def workspace(s, ctx, pid, project_id=None):
    product = require_access(s, ctx, pid)
    if project_id is not None:
        owner.project(s, ctx, pid, project_id)
    at = now()
    candidates, published = [], []
    for pointer_model, version_model, key, output in (
        (KnowledgeCandidateCurrent, KnowledgeCandidateVersion, "candidate_id", candidates),
        (DesignRuleCurrent, DesignRuleVersion, "rule_id", published),
    ):
        query = select(pointer_model).where(
            pointer_model.tenant_id == ctx.tenant_id, pointer_model.category_id == ctx.category_id
        )
        if pid is None:
            query = query.where(pointer_model.product_id.is_(None))
        elif key == "candidate_id":
            query = query.where(
                or_(pointer_model.product_id == pid, pointer_model.product_id.is_(None))
            )
        else:
            query = query.where(pointer_model.product_id == pid)
        if project_id is not None:
            query = query.where(
                or_(pointer_model.project_id == project_id, pointer_model.project_id.is_(None))
            )
        for pointer in s.scalars(
            query.order_by(pointer_model.created_at.desc(), pointer_model.id).limit(100)
        ):
            row = owner.retained(s, ctx, s.get(version_model, pointer.version_id))
            histories = list(
                s.scalars(
                    select(version_model)
                    .where(
                        version_model.tenant_id == ctx.tenant_id,
                        version_model.category_id == ctx.category_id,
                        getattr(version_model, key) == getattr(row, key),
                    )
                    .order_by(version_model.revision)
                )
            )
            author = s.get(Principal, row.actor_id)
            value = {
                **row.body,
                "id": str(getattr(row, key)),
                "version_id": str(row.id),
                "project_id": str(row.project_id) if row.project_id else None,
                "owner_id": str(row.owner_id),
                "visibility": row.visibility,
                "author_id": str(row.actor_id),
                "origin": "ai" if author and author.kind == "agent" else "human",
                "created_at": row.created_at.isoformat(),
                "sources": row.sources,
                "history": _history(histories),
            }
            if key == "candidate_id":
                value["can_revise"] = row.owner_id == ctx.requester_id and row.product_id == pid
            else:
                assessed = authority.assess(
                    s,
                    ctx,
                    row.product_id,
                    row.project_id,
                    RULE_OP,
                    row.body["applicability"]["purpose"],
                    at,
                )
                value["can_revise"] = assessed["authorized"] and assessed["qualified"]
                value["usability"] = _usability(s, ctx, row, at)
            output.append(value)
    projects, configurations = [], []
    if pid is not None:
        projects = [
            {
                "id": str(row.id),
                "revision": row.revision,
                "name": row.name,
                "owner_id": str(row.owner_id),
                "visibility": row.visibility,
            }
            for row in s.scalars(
                select(Project)
                .where(Project.tenant_id == ctx.tenant_id, Project.product_id == pid)
                .order_by(Project.created_at.desc(), Project.id)
                .limit(100)
            )
        ]
        for kind, model in (
            ("engineering_configuration", EngineeringConfiguration),
            ("process_revision", ProcessRevision),
        ):
            configurations.extend(
                {"kind": kind, "id": str(row.id), "revision": row.revision, "name": row.name}
                for row in s.scalars(
                    select(model)
                    .where(model.tenant_id == ctx.tenant_id, model.product_id == pid)
                    .order_by(model.created_at.desc(), model.id)
                    .limit(100)
                )
            )
    return {
        "product_revision": product.revision,
        "projects": projects,
        "configurations": configurations,
        "candidates": candidates,
        "rules": published,
        "as_of": at.isoformat(),
    }
