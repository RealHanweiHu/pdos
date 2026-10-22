"""Native Field basis and explicit future intent for the existing T2 selection."""

from copy import deepcopy
from dataclasses import dataclass

from sqlalchemy import and_, or_, select

from pdos_next.change_controlled_schemas import (
    FieldIntentTarget,
    FieldSelectionMaterial,
    SelectionMaterial,
)
from pdos_next.domain.change_control.rules import digest
from pdos_next.domain.change_execution import field_bridge
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Principal, now
from pdos_next.schemas.change_control.contracts import Ref
from pdos_next.schemas.verification.contracts import SourceRef


def require(ok, reason="ACTION_INTENT_SCOPE_MISMATCH", status=409):
    if not ok:
        raise DomainError(reason, "现场反馈、明确计划、具名执行人或当前来源未满足。", status)


def parse_material(raw):
    version = raw.get("schema_version") if isinstance(raw, dict) else None
    if version == "pdos-controlled-change-selection-v1":
        return SelectionMaterial.model_validate(raw)
    if version == "pdos-field-change-selection-v1":
        return FieldSelectionMaterial.model_validate(raw)
    raise ValueError("Unsupported fixed selection material version")


class SelectionMaterialReader:
    """Finite original parser; legacy v1 serialization and digests stay intact."""

    model_validate = staticmethod(parse_material)


def executor_options(s, ctx):
    query = (
        select(Principal.id, Principal.name)
        .join(
            Grant, and_(Grant.tenant_id == Principal.tenant_id, Grant.principal_id == Principal.id)
        )
        .where(
            Principal.tenant_id == ctx.tenant_id,
            Principal.kind == "human",
            Principal.active.is_(True),
            Grant.category_id == ctx.category_id,
            or_(Grant.expires_at.is_(None), Grant.expires_at > now()),
        )
        .order_by(Principal.name, Principal.id)
    )
    return [{"id": str(row.id), "name": row.name} for row in s.execute(query)]


@dataclass(frozen=True)
class FieldBasis:
    scope: object
    purpose: str
    category_id: object
    owner_id: object
    visibility: str
    nature: str
    feedback_id: object
    feedback_version_id: object
    feedback_revision: int
    feedback_sha256: str
    sources: tuple
    required_source_read_set: list
    source_basis: dict


@dataclass(frozen=True)
class FieldIntent:
    intent_id: object
    intent_sha256: str
    executor_id: object


def load_basis(s, ctx, pid, target, item, request, scope, purpose, nature):
    require(type(target) is FieldIntentTarget, "INVALID_PAYLOAD", 422)
    ref = Ref(kind="field_feedback", id=target.feedback.id, revision=target.feedback.revision)
    require(ref in (*request.roots, *request.references), "ACTION_INTENT_SCOPE_MISMATCH", 403)
    row, view, actual_scope, actual_purpose = field_bridge.get(s, ctx, pid, ref)
    require(
        actual_scope == scope == request.scope and actual_purpose == purpose,
        "ACTION_INTENT_SCOPE_MISMATCH",
        403,
    )
    require(
        row.visibility != "private" or request.audience == (f"private:{row.owner_id}",),
        "AUDIENCE_USE_FORBIDDEN",
        403,
    )
    require(
        str(target.executor_id) in {person["id"] for person in executor_options(s, ctx)},
        "FORBIDDEN_SCOPE",
        403,
    )
    require(nature in {"real", "synthetic"}, "NATURE_MISMATCH")
    basis = FieldBasis(
        actual_scope,
        purpose,
        row.category_id,
        row.owner_id,
        row.visibility,
        nature,
        row.feedback_id,
        row.id,
        row.revision,
        row.body_sha256,
        tuple(SourceRef.model_validate(source) for source in view["sources"]),
        deepcopy(view["required_source_read_set"]),
        {
            "feedback_version_id": str(row.id),
            "feedback_sha256": row.body_sha256,
            "feedback_source_basis": deepcopy(row.source_basis),
        },
    )
    return basis, FieldIntent(item.intent.id, digest(item.intent), target.executor_id)


def material_for(ctx, request, item, target, basis, *, status, valid_until, reason):
    return FieldSelectionMaterial(
        schema_version="pdos-field-change-selection-v1",
        scope=basis.scope,
        purpose=basis.purpose,
        change_id=request.id,
        item=item,
        feedback=target.feedback,
        feedback_version_id=basis.feedback_version_id,
        feedback_sha256=basis.feedback_sha256,
        executor_id=target.executor_id,
        decider_id=ctx.actor_id,
        status=status,
        valid_until=valid_until,
        reason=reason,
        nature=basis.nature,
    )


def options(s, ctx, pid, request):
    result = []
    for ref in dict.fromkeys((*request.roots, *request.references)):
        if ref.kind != "field_feedback":
            continue
        row, view, scope, _ = field_bridge.get(s, ctx, pid, ref)
        require(scope == request.scope, "FORBIDDEN_SCOPE", 403)
        result.append(
            {
                "feedback": {"id": str(row.feedback_id), "revision": row.revision},
                "version_id": str(row.id),
                "sha256": row.body_sha256,
                "title": view["title"],
            }
        )
    return result
