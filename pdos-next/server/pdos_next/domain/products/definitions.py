from copy import deepcopy
from types import SimpleNamespace
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import func, select

from pdos_next.database import category_for_product
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Grant, Principal, now
from pdos_next.request_proof import batch_read
from pdos_next.schemas.products.definitions import DefinitionDraftPayload

from .models import DefinitionRevision, DefinitionSource, DefinitionSpecCurrent, DefinitionSpecRow

if TYPE_CHECKING:
    from pdos_next.contracts import Command
    from pdos_next.service import Context


def semantic(payload: DefinitionDraftPayload) -> dict:
    """Server validation retains exact pinned sources and parent, independent of request key."""
    if payload.mode == "inherit_parent":
        from . import definition_inherit

        return definition_inherit.semantic(payload)
    value = payload.model_dump(mode="json", exclude={"mode"})
    value["sources"] = sorted(
        value["sources"], key=lambda r: (r["artifact_id"], r["line"], r["quote"])
    )
    value["specs"] = sorted(value["specs"], key=lambda spec: spec["key"])
    for spec in value["specs"]:
        spec["sources"] = sorted(
            spec["sources"], key=lambda r: (r["artifact_id"], r["line"], r["quote"])
        )
    return value


def validate(s, ctx: "Context", command: "Command", product, payload: DefinitionDraftPayload):
    if payload.mode == "inherit_parent":
        from . import definition_inherit

        return definition_inherit.validate(s, ctx, command, product, payload)
    from pdos_next.service import require_access, source_for

    require_access(s, ctx, product.id, write=True, lock=True)
    actor = s.get(Principal, ctx.actor_id)
    if (
        ctx.run_id is not None
        or ctx.actor_id != ctx.requester_id
        or not actor
        or actor.kind != "human"
    ):
        raise DomainError("NAMED_DECISION_REQUIRED", "本轮定义草稿仅支持本人手工保存。", 403)
    if command.product_id != product.id or product.tenant_id != ctx.tenant_id:
        raise DomainError("FORBIDDEN_SCOPE", "定义不在当前型号范围。", 403)
    if command.expected_revision != product.revision:
        raise DomainError("VERSION_CONFLICT", "型号范围版本已变化，请重新读取。")
    reads = {r.artifact_id: r.expected_revision for r in command.source_read_set}
    for reference in payload.sources:
        if reads.get(reference.artifact_id) != reference.expected_revision:
            raise DomainError("MISSING_REQUIRED_EVIDENCE", "定义需要全部来源的明确版本。")
        source = source_for(s, ctx, product.id, reference.artifact_id, reference.expected_revision)
        lines = source.content.splitlines()
        if reference.line > len(lines) or reference.quote not in lines[reference.line - 1]:
            raise DomainError("MISSING_REQUIRED_EVIDENCE", "定义引用必须在指定原文行精确定位。")
        if source.visibility != "category" and payload.visibility == "category":
            raise DomainError("FORBIDDEN_SCOPE", "私人原件不能用于共享定义。", 403)
    for spec in payload.specs:
        if spec.owner_id is not None:
            owner = s.get(Principal, spec.owner_id)
            grant = s.scalar(
                select(Grant)
                .where(
                    Grant.tenant_id == ctx.tenant_id,
                    Grant.category_id == category_for_product(product.id),
                    Grant.principal_id == spec.owner_id,
                    Grant.can_write.is_(True),
                    (Grant.expires_at.is_(None) | (Grant.expires_at > now())),
                )
                .with_for_update()
            )
            if (
                not owner
                or owner.tenant_id != ctx.tenant_id
                or owner.kind != "human"
                or not owner.active
                or not grant
            ):
                raise DomainError("FORBIDDEN_SCOPE", "规格负责人须为当前型号内有效人类成员。", 403)
    if payload.parent_definition_id is not None:
        parent = s.scalar(
            select(DefinitionRevision).where(
                DefinitionRevision.tenant_id == ctx.tenant_id,
                DefinitionRevision.product_id == product.id,
                DefinitionRevision.id == payload.parent_definition_id,
            )
        )
        if not parent:
            raise DomainError("FORBIDDEN_SCOPE", "父定义不在当前授权范围。", 403)
        if parent.revision != payload.expected_parent_revision:
            raise DomainError("VERSION_CONFLICT", "父定义版本与所选固定版本不一致。")
        if parent.visibility != "category" and payload.visibility == "category":
            raise DomainError("FORBIDDEN_SCOPE", "私人父定义不能通过续版扩大受众。", 403)
        # Retaining a parent never permits inheriting withdrawn or inaccessible source material.
        for reference in s.scalars(
            select(DefinitionSource).where(
                DefinitionSource.tenant_id == ctx.tenant_id,
                DefinitionSource.definition_id == parent.id,
            )
        ):
            source_for(s, ctx, product.id, reference.artifact_id, reference.source_revision)


def apply_draft(s, ctx, command, product, payload: DefinitionDraftPayload):
    if payload.mode == "inherit_parent":
        from . import definition_inherit

        return definition_inherit.apply_draft(s, ctx, command, product, payload)
    validate(s, ctx, command, product, payload)
    latest = s.scalar(
        select(DefinitionRevision)
        .where(
            DefinitionRevision.tenant_id == ctx.tenant_id,
            DefinitionRevision.product_id == product.id,
            DefinitionRevision.variant_id.is_(None),
        )
        .order_by(DefinitionRevision.revision.desc())
        .limit(1)
    )
    if latest and latest.id != payload.parent_definition_id:
        raise DomainError(
            "VERSION_CONFLICT", "当前已有新定义草稿，请读取最新可见版本并核对差异后续版。"
        )
    revision = (
        s.scalar(
            select(func.max(DefinitionRevision.revision)).where(
                DefinitionRevision.tenant_id == ctx.tenant_id,
                DefinitionRevision.product_id == product.id,
                DefinitionRevision.variant_id.is_(None),
            )
        )
        or 0
    ) + 1
    subject = create_revision(
        s,
        ctx,
        product,
        owner_id=ctx.requester_id,
        revision=revision,
        fields=payload.model_dump(exclude={"mode", "sources", "specs", "expected_parent_revision"}),
        specs=[spec.model_dump(exclude={"sources"}) for spec in payload.specs],
        sources=[
            {
                "artifact_id": reference.artifact_id,
                "source_revision": reference.expected_revision,
                "line": reference.line,
                "quote": reference.quote,
                "spec_keys": [
                    spec.key
                    for spec in payload.specs
                    if reference.model_dump(mode="json")
                    in [r.model_dump(mode="json") for r in spec.sources]
                ],
            }
            for reference in payload.sources
        ],
    )
    return subject, "definition_revision", subject.visibility


def create_revision(
    s,
    ctx,
    product,
    *,
    owner_id,
    revision,
    fields,
    specs,
    sources,
    definition_id=None,
    decision=None,
    spec_table=None,
):
    """B3's common writer; callers validate their command's schema and fixed sources."""
    from .service import require_creation

    require_creation(s, ctx, product_id=product.id, decision=decision)
    if decision and definition_id != decision.created_definition_id:
        raise DomainError("FORBIDDEN_SCOPE", "定义不属于本次 G0 结果。", 403)
    if fields["visibility"] == "category" and product.visibility != "category":
        raise DomainError("FORBIDDEN_SCOPE", "私人型号不能扩大为共享定义。", 403)
    if len({spec["key"] for spec in specs}) != len(specs):
        raise DomainError("VALIDATION_FAILED", "定义规格标识不能重复。")
    subject = DefinitionRevision(
        id=definition_id or uuid4(),
        tenant_id=ctx.tenant_id,
        product_id=product.id,
        owner_id=owner_id,
        revision=revision,
        status="draft",
        **fields,
    )
    s.add(subject)
    s.flush([subject])
    spec_rows = []
    for spec in specs:
        if spec_table is not None:
            # A versioned schema supplement supplies extra columns, while the B3
            # writer still owns identity, scope and the one immutable INSERT.
            identity = uuid4()
            s.execute(
                spec_table.insert().values(
                    id=identity,
                    tenant_id=ctx.tenant_id,
                    category_id=ctx.category_id,
                    product_id=product.id,
                    definition_id=subject.id,
                    created_at=now(),
                    **spec,
                )
            )
            spec_rows.append(SimpleNamespace(id=identity, key=spec["key"]))
            continue
        row = DefinitionSpecRow(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            product_id=product.id,
            definition_id=subject.id,
            **spec,
        )
        s.add(row)
        spec_rows.append(row)
    for reference in sources:
        s.add(
            DefinitionSource(
                id=uuid4(),
                tenant_id=ctx.tenant_id,
                product_id=product.id,
                definition_id=subject.id,
                **reference,
            )
        )
    s.flush()
    subject.created_specs = spec_rows
    return subject


def difference(previous: dict, current: dict) -> list[dict]:
    """Stable specification keys preserve precise before/after without inherited decisions."""
    old_specs = {item["key"]: item for item in previous.get("specs", [])}
    new_specs = {item["key"]: item for item in current.get("specs", [])}
    result = [
        {"path": name, "before": deepcopy(previous.get(name)), "after": deepcopy(current.get(name))}
        for name in (
            "title",
            "purpose",
            "use_cases",
            "requirements",
            "constraints",
            "unknowns",
            "exclusions",
            "visibility",
            "sources",
        )
        if previous.get(name) != current.get(name)
    ]
    result.extend(
        {
            "path": f"specs/{key}",
            "before": deepcopy(old_specs.get(key)),
            "after": deepcopy(new_specs.get(key)),
        }
        for key in sorted(old_specs.keys() | new_specs.keys())
        if old_specs.get(key) != new_specs.get(key)
    )
    return result


def definition_view(s, ctx, row) -> dict:
    from sqlalchemy import inspect
    from sqlalchemy.orm import Session, load_only

    from pdos_next.original_security import source_status
    from pdos_next.request_proof import snapshot_rows
    from pdos_next.service import require_access

    require_access(s, ctx, row.product_id)
    if isinstance(s, Session) and s.info.get("read_snapshot") and inspect(row).unloaded:
        # Baseline selection first reads a header and authorizes that exact row.
        # Load the requested body once, rather than lazy-loading each field.
        row = s.scalar(
            select(DefinitionRevision).where(
                DefinitionRevision.id == row.id,
                DefinitionRevision.tenant_id == ctx.tenant_id,
                DefinitionRevision.category_id == ctx.category_id,
                DefinitionRevision.product_id == row.product_id,
            )
        )
        if row is None:
            raise DomainError("SOURCE_UNAVAILABLE", "固定定义不在当前可读范围。", 403)

    refs = snapshot_rows(
        s,
        (DefinitionSource, row.product_id, row.id),
        select(DefinitionSource)
        .where(
            DefinitionSource.tenant_id == ctx.tenant_id,
            DefinitionSource.definition_id == row.id,
        )
        .order_by(DefinitionSource.artifact_id, DefinitionSource.line),
        scope_id=row.product_id,
    )
    sources = []
    source_rows = batch_read(s, Artifact, (ref.artifact_id for ref in refs))
    if isinstance(s, Session) and s.info.get("read_snapshot"):
        missing_titles = {
            identity for identity, source in source_rows.items()
            if source is not None and "title" in inspect(source).unloaded
        }
        if missing_titles:
            # Source watermarks already hold the authorized raw headers. Only
            # display titles are missing; never fetch their unused source bodies.
            list(
                s.scalars(
                    select(Artifact).where(
                        Artifact.tenant_id == ctx.tenant_id,
                        Artifact.category_id == ctx.category_id,
                        Artifact.id.in_(missing_titles),
                    ).options(load_only(Artifact.id, Artifact.title))
                )
            )
    for ref in refs:
        source = source_rows[ref.artifact_id]
        readable = bool(source and source.tenant_id == ctx.tenant_id)
        sources.append(
            {
                "artifact_id": str(ref.artifact_id),
                "expected_revision": ref.source_revision,
                "line": ref.line,
                "quote": ref.quote if readable else None,
                "title": source.title if readable else "来源权限需重核",
                "status": "unavailable"
                if not readable
                else "stale"
                if source.revision != ref.source_revision
                else source_status(s, source),
                "spec_keys": ref.spec_keys,
            }
        )
    if any(source["status"] == "unavailable" for source in sources):
        raise DomainError(
            "SOURCE_UNAVAILABLE", "此定义引用权限已变化，重新核对前不展示派生内容。", 403
        )
    specs, item_versions = [], []
    for spec in snapshot_rows(
        s,
        (DefinitionSpecRow, row.product_id, row.id),
        select(DefinitionSpecRow)
        .join(DefinitionSpecCurrent, DefinitionSpecCurrent.current_row_id == DefinitionSpecRow.id)
        .where(
            DefinitionSpecCurrent.removed.is_(False),
            DefinitionSpecRow.tenant_id == ctx.tenant_id,
            DefinitionSpecRow.definition_id == row.id,
        )
        .order_by(DefinitionSpecRow.key),
        scope_id=row.product_id,
    ):
        data = {
            column.name: getattr(spec, column.name)
            for column in spec.__table__.columns
            if column.name
            not in {
                "id",
                "tenant_id",
                "category_id",
                "product_id",
                "definition_id",
                "created_at",
                "item_id",
                "item_version",
                "removed",
                "prepared_candidate_id",
            }
        }
        from decimal import Decimal
        from uuid import UUID

        for name, value in data.items():
            if isinstance(value, (Decimal, UUID)):
                data[name] = str(value)
        data["sources"] = [
            {
                k: value
                for k, value in source.items()
                if k in {"artifact_id", "expected_revision", "line", "quote"}
            }
            for source in sources
            if spec.key in source["spec_keys"]
        ]
        specs.append(data)
        item_versions.append(
            {
                "item_id": str(spec.item_id),
                "item_version": spec.item_version,
                "row_id": str(spec.id),
                "key": spec.key,
            }
        )
    return {
        "item_versions": item_versions,
        "id": str(row.id),
        "category_id": str(row.category_id),
        "product_id": str(row.product_id),
        "variant_id": str(row.variant_id) if row.variant_id else None,
        "owner_id": str(row.owner_id),
        "parent_definition_id": str(row.parent_definition_id) if row.parent_definition_id else None,
        "revision": row.revision,
        "status": row.status,
        "sealed": row.sealed,
        "publication_receipt_id": str(row.publication_receipt_id)
        if row.publication_receipt_id
        else None,
        "derived_from_definition_id": str(row.derived_from_definition_id)
        if row.derived_from_definition_id
        else None,
        "derived_from_definition_revision": row.derived_from_definition_revision,
        "g0_decision_id": str(row.g0_decision_id) if row.g0_decision_id else None,
        "source_proposal_id": str(row.source_proposal_id) if row.source_proposal_id else None,
        "source_submission_id": str(row.source_submission_id) if row.source_submission_id else None,
        "source_proposal_revision": row.source_proposal_revision,
        "visibility": row.visibility,
        "title": row.title,
        "purpose": row.purpose,
        "use_cases": row.use_cases,
        "requirements": row.requirements,
        "constraints": row.constraints,
        "unknowns": row.unknowns,
        "exclusions": row.exclusions,
        "change_reason": row.change_reason,
        "sources": sources,
        "specs": specs,
        "created_at": row.created_at.isoformat(),
        "source_status": "current"
        if all(source["status"] == "active" for source in sources)
        else "needs_recheck",
    }


def list_definitions(s, ctx, product_id):
    from pdos_next.service import require_access

    require_access(s, ctx, product_id)
    rows = s.scalars(
        select(DefinitionRevision)
        .where(
            DefinitionRevision.tenant_id == ctx.tenant_id,
            DefinitionRevision.product_id == product_id,
        )
        .order_by(DefinitionRevision.revision.desc())
        .limit(101)
    ).all()
    items = []
    unavailable_count = 0
    for row in rows[:100]:
        try:
            items.append(definition_view(s, ctx, row))
        except DomainError as error:
            if error.code != "SOURCE_UNAVAILABLE":
                raise
            unavailable_count += 1
    by_id = {item["id"]: item for item in items}
    for item in items:
        previous = by_id.get(item["parent_definition_id"])
        if previous is None and item["parent_definition_id"]:
            parent = s.get(DefinitionRevision, item["parent_definition_id"])
            if parent and parent.tenant_id == ctx.tenant_id and parent.product_id == product_id:
                try:
                    previous = definition_view(s, ctx, parent)
                except DomainError as error:
                    if error.code != "SOURCE_UNAVAILABLE":
                        raise
        item["differences"] = difference(previous, item) if previous else []
    return {"items": items, "has_more": len(rows) > 100, "unavailable_count": unavailable_count}
