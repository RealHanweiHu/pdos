"""Framework configuration is a named domain operation with immutable history."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import select, text

from pdos_next.core.schema_base import StrictModel
from pdos_next.domain.categories.preproject.access import human
from pdos_next.errors import DomainError

from .models import FrameworkRevision
from .rules import Framework, ProjectType

DRAFT = "work.framework.draft"
PUBLISH = "work.framework.publish"


class DraftPayload(StrictModel):
    project_type: ProjectType
    expected_framework_revision: int = Field(ge=0, strict=True)
    framework: Framework
    reason: str = Field(min_length=3, max_length=2000)
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)


class PublishPayload(StrictModel):
    project_type: ProjectType
    expected_framework_revision: int = Field(ge=1, strict=True)
    framework_id: UUID
    action: Literal["publish", "retire"]
    reason: str = Field(min_length=3, max_length=2000)
    approval_token: str | None = Field(default=None, min_length=20, max_length=128)


def versions(s, ctx, project_type):
    return (
        select(FrameworkRevision)
        .where(
            FrameworkRevision.tenant_id == ctx.tenant_id,
            FrameworkRevision.category_id == ctx.category_id,
            FrameworkRevision.project_type == project_type,
        )
        .order_by(FrameworkRevision.revision.desc())
    )


def effective(s, ctx, project_type):
    query = versions(s, ctx, project_type).where(FrameworkRevision.state != "draft")
    row = s.scalar(query.limit(1))
    return row if row and row.state == "published" else None


def project_type(project):
    return "derivative" if project.trigger_type == "parent_product" else "new_product"


def view(row):
    return {
        "id": str(row.id),
        "revision": row.revision,
        "project_type": row.project_type,
        "state": row.state,
        "framework": row.document,
        "reason": row.reason,
        "author_id": str(row.author_id),
        "receipt_id": str(row.receipt_id),
        "previous_id": str(row.previous_id) if row.previous_id else None,
    }


def history(s, ctx, kind, before_revision=None):
    query = versions(s, ctx, kind)
    if before_revision is not None:
        query = query.where(FrameworkRevision.revision < before_revision)
    return [view(row) for row in s.scalars(query.limit(100))]


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"approval_token", "confirmation_token"})


@dataclass
class Validated:
    latest: FrameworkRevision | None
    framework: Framework
    state: str
    confirmation_id: UUID | None = None


def validate(s, ctx, command, scope, payload):
    from pdos_next.domain.projects.team.roles import _administrator, current

    human(s, ctx)
    if scope.id is not None or not _administrator(s, ctx):
        raise DomainError("FORBIDDEN_SCOPE", "框架由具名租户管理员在所属品类维护。", 403)
    if command.expected_revision != scope.revision:
        raise DomainError("VERSION_CONFLICT", "品类版本已变化。")
    if s.info.get("read_snapshot") is not True:
        s.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"project-role-catalog:{ctx.tenant_id}"},
        )
    latest = s.scalar(versions(s, ctx, payload.project_type).limit(1))
    revision = latest.revision if latest else 0
    if revision != payload.expected_framework_revision:
        raise DomainError("VERSION_CONFLICT", "框架已变化，请刷新。")
    if isinstance(payload, DraftPayload):
        definition, state = payload.framework, "draft"
    else:
        target = latest if payload.action == "publish" else effective(s, ctx, payload.project_type)
        required = "draft" if payload.action == "publish" else "published"
        if target is None or target.id != payload.framework_id or target.state != required:
            raise DomainError("VERSION_CONFLICT", "请选择当前草稿或当前启用版本。")
        definition = Framework.model_validate(target.document)
        state = "published" if payload.action == "publish" else "retired"
    if state != "retired":
        keys = {role["key"] for role in current(s, ctx.tenant_id)["roles"]}
        missing = sorted({outcome.role for outcome in definition.outcomes} - keys)
        if missing:
            raise DomainError(
                "VALIDATION_FAILED", "框架引用未登记角色。", 422, detail={"role_keys": missing}
            )
    return Validated(latest, definition, state)


def preview_view(s, ctx, command, scope, payload):
    checked = validate(s, ctx, command, scope, payload)
    latest, definition, state = checked.latest, checked.framework, checked.state
    active = effective(s, ctx, payload.project_type)
    return {
        "operation": command.operation,
        "current": view(latest) if latest else None,
        "next_revision": payload.expected_framework_revision + 1,
        "state": state,
        "framework": definition.model_dump(mode="json"),
        "changes": difference(
            active.document if active else {}, definition.model_dump(mode="json")
        ),
        "reason": payload.reason,
    }


def apply_validated(s, ctx, command, scope, payload, value):
    latest, definition, state = value.latest, value.framework, value.state
    row = FrameworkRevision(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        project_type=payload.project_type,
        revision=payload.expected_framework_revision + 1,
        state=state,
        document=definition.model_dump(mode="json"),
        reason=payload.reason,
        author_id=ctx.actor_id,
        previous_id=latest.id if latest else None,
        receipt_id=uuid4(),
    )
    row.prepared_receipt_id = row.receipt_id
    row.confirmation_id = value.confirmation_id
    row.action_result = {"state": state, "project_type": row.project_type}
    s.add(row)
    return row, "npi_framework_revision", "category"


def difference(old, new):
    changes = []
    for section in ("stages", "outcomes", "metrics"):
        before = {entry["key"]: entry for entry in old.get(section, ())}
        after = {entry["key"]: entry for entry in new.get(section, ())}
        for key in sorted(before.keys() | after.keys()):
            if before.get(key) != after.get(key):
                changes.append(
                    {
                        "section": section,
                        "key": key,
                        "before": before.get(key),
                        "after": after.get(key),
                    }
                )
    return sorted(
        changes,
        key=lambda change: (
            not (change["before"] is None and (change["after"] or {}).get("redline", False))
        ),
    )
