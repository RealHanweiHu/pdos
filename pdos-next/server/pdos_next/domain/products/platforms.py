"""Platform links use the existing named T1 command/receipt transaction."""

from dataclasses import dataclass
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import select, text

from pdos_next.domain.preproject.access import fail, human
from pdos_next.domain.preproject.deidentification import check_content
from pdos_next.domain.preproject.provenance import writing_path
from pdos_next.models import Artifact, Product, UploadedOriginal
from pdos_next.service import require_access

from .platform_models import Platform, PlatformLink, PlatformLinkCurrent
from .platform_schemas import PlatformReadInput
from .variant_models import Variant

category_lifecycle_fence = True


@dataclass
class ValidatedLink:
    platform: object | None
    current: object | None
    variant: object | None
    provenance: dict
    confirmation_id: UUID | None = None


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"confirmation_token"})


def target(s, ctx, product_id, variant_id=None):
    product = require_access(s, ctx, product_id)
    variant = None
    if variant_id is not None:
        variant = s.scalar(
            select(Variant).where(
                Variant.tenant_id == ctx.tenant_id,
                Variant.category_id == ctx.category_id,
                Variant.product_id == product_id,
                Variant.id == variant_id,
            )
        )
        if variant is None:
            fail("NOT_FOUND", "variant_not_found", "变体不存在或不可读。", 404)
    return product, variant


def _shared_metadata(s, ctx, payload):
    if not payload.new_platform or not payload.prepared_by_run_id:
        return
    from pdos_next.agent_kernel.models import AgentRun

    run = s.get(AgentRun, payload.prepared_by_run_id)
    source_ids = [UUID(ref["artifact_id"]) for ref in run.read_sources]
    filenames = (
        s.scalars(
            select(UploadedOriginal.filename)
            .join(
                Artifact,
                (Artifact.tenant_id == UploadedOriginal.tenant_id)
                & (Artifact.original_id == UploadedOriginal.id),
            )
            .where(Artifact.id.in_(source_ids))
        )
        if source_ids
        else []
    )
    checks = check_content(
        payload.new_platform.model_dump(),
        identities=run.customer_identities,
        filenames=filenames,
        private_refs=[str(identity) for identity in source_ids],
    )
    if any(hit["kind"] in {"identity", "filename", "private_ref"} for hit in checks["hits"]):
        fail(
            "VALIDATION_FAILED",
            "private_platform_metadata",
            "平台共用信息须去除客户身份和私有来源标识。",
        )


def validate(s, ctx, command, product, payload):
    human(s, ctx)
    if product.id != payload.product_id or product.category_id != ctx.category_id:
        fail("FORBIDDEN_SCOPE", "platform_product_mismatch", "平台关联与当前型号不一致。", 403)
    if command.expected_revision != product.revision:
        fail("VERSION_CONFLICT", "product_version_changed", "型号版本已变化，请重新读取。")
    _, variant = target(s, ctx, product.id, payload.variant_id)
    if variant is not None and variant.g0_decision_id is None:
        # P23: a preparation draft carries no G0 decision, so no object may bind it.
        fail(
            "FORBIDDEN_SCOPE",
            "variant_without_g0_decision",
            "派生草稿不能被平台关联引用；可引用的变体身份由 G0 批准产生。",
            403,
        )
    provenance = writing_path(s, ctx, command, payload)
    provenance["confirmed_by"] = ctx.requester_id
    _shared_metadata(s, ctx, payload)
    platform = None
    current = None
    if payload.new_platform:
        # Serialize tenant/code creation across different Products. The common
        # command already owns the Category/Product locks before reaching here.
        s.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"platform:{ctx.tenant_id}:{payload.new_platform.code}"},
        )
        if s.scalar(
            select(Platform.id).where(
                Platform.tenant_id == ctx.tenant_id,
                Platform.code == payload.new_platform.code,
            )
        ):
            fail("VALIDATION_FAILED", "platform_code_taken", "平台编号已存在，请选择已有平台。")
    else:
        platform = s.scalar(
            select(Platform).where(
                Platform.tenant_id == ctx.tenant_id,
                Platform.id == payload.platform_id,
            )
        )
        if platform is None:
            fail("NOT_FOUND", "platform_not_found", "平台不存在或不可读。", 404)
        current = s.get(
            PlatformLinkCurrent,
            (
                ctx.tenant_id,
                product.id,
                platform.id,
                payload.variant_id or product.id,
            ),
        )
    version = current.current_version if current else 0
    if version != payload.expected_link_version:
        fail(
            "VERSION_CONFLICT", "platform_link_version_changed", "关联已有变化，请重新读取并核对。"
        )
    if payload.action == "detach" and (current is None or not current.attached):
        fail("VALIDATION_FAILED", "platform_link_not_attached", "当前没有可解除的关联。")
    return ValidatedLink(platform, current, variant, provenance)


def preview_view(s, ctx, command, product, payload):
    validated = validate(s, ctx, command, product, payload)
    return {
        "operation": command.operation,
        "payload": semantic(payload),
        "product_name": product.name,
        "variant_name": validated.variant.name if validated.variant else None,
        "platform": payload.new_platform.model_dump()
        if payload.new_platform
        else {
            "id": str(validated.platform.id),
            "code": validated.platform.code,
            "name": validated.platform.name,
            "description": validated.platform.description,
        },
        "next_link_version": payload.expected_link_version + 1,
        "effect": (
            "平台编号、名称和说明为租户共用；兼容范围、版本与原因仅随有权读取的型号或变体展示。"
        ),
    }


def apply_validated(s, ctx, command, product, payload, validated):
    receipt_id = uuid4()
    provenance = {
        **validated.provenance,
        "receipt_id": receipt_id,
        "confirmation_id": validated.confirmation_id,
    }
    platform = validated.platform
    if platform is None:
        platform = Platform(
            id=uuid4(), tenant_id=ctx.tenant_id, **payload.new_platform.model_dump(), **provenance
        )
        s.add(platform)
        s.flush([platform])
    link = PlatformLink(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        product_id=product.id,
        platform_id=platform.id,
        variant_id=payload.variant_id,
        target_id=payload.variant_id or product.id,
        version=payload.expected_link_version + 1,
        action=payload.action,
        compatibility=payload.compatibility,
        platform_version=payload.platform_version,
        reason=payload.reason,
        **provenance,
    )
    s.add(link)
    s.flush([link])
    current = validated.current
    if current:
        current.current_version, current.attached = link.version, payload.action == "attach"
    else:
        s.add(
            PlatformLinkCurrent(
                tenant_id=ctx.tenant_id,
                category_id=ctx.category_id,
                product_id=product.id,
                platform_id=platform.id,
                target_id=link.target_id,
                current_version=link.version,
                attached=payload.action == "attach",
            )
        )
    link.prepared_receipt_id = receipt_id
    link.prepared_by_run_id = link.run_id
    link.action_result = {
        "platform_id": str(platform.id),
        "platform_code": platform.code,
        "platform_created": payload.new_platform is not None,
        "variant_id": str(link.variant_id) if link.variant_id else None,
        "link_version": link.version,
    }
    shared = product.visibility == "category" and (
        validated.variant is None or validated.variant.visibility == "category"
    )
    return link, "platform_link", "category" if shared else "private"


def _provenance(row):
    # Tenant-shared platform metadata never exposes a private Run/receipt backlink.
    return {
        "origin": row.origin,
        "writer_id": str(row.writer_id),
        "confirmed_by": str(row.confirmed_by),
        "created_at": row.created_at.isoformat(),
    }


def read(s, ctx, payload, *, shared_only=False):
    try:
        payload = PlatformReadInput.model_validate(payload)
    except ValidationError:
        fail("VALIDATION_FAILED", "invalid_platform_filters", "平台读取条件无效。", 422)
    require_access(s, ctx, None)
    if payload.category_id is not None and payload.category_id != ctx.category_id:
        fail("FORBIDDEN_SCOPE", "platform_category_mismatch", "读取品类由当前入口绑定。", 403)
    if payload.product_id:
        product, variant = target(s, ctx, payload.product_id, payload.variant_id)
        if shared_only and (
            product.visibility != "category"
            or (variant is not None and variant.visibility != "category")
        ):
            fail(
                "SOURCE_UNAVAILABLE",
                "private_material_context_binding_required",
                "此平台读取尚未绑定私有型号内容的模型出站范围。",
                403,
            )
    query = select(Platform).where(Platform.tenant_id == ctx.tenant_id)
    if payload.platform_id:
        query = query.where(Platform.id == payload.platform_id)
    if payload.code is not None:
        query = query.where(Platform.code == payload.code)
    if payload.name_query:
        query = query.where(Platform.name.icontains(payload.name_query, autoescape=True))
    if payload.product_id:
        query = query.where(
            select(PlatformLinkCurrent.platform_id)
            .where(
                PlatformLinkCurrent.tenant_id == ctx.tenant_id,
                PlatformLinkCurrent.product_id == payload.product_id,
                PlatformLinkCurrent.platform_id == Platform.id,
                PlatformLinkCurrent.target_id == (payload.variant_id or payload.product_id),
            )
            .exists()
        )
    if payload.cursor:
        query = query.where(Platform.id > payload.cursor)
    rows = list(s.scalars(query.order_by(Platform.id).limit(payload.page_size + 1)))
    page = rows[: payload.page_size]
    if payload.platform_id and not page:
        fail("NOT_FOUND", "platform_not_found", "平台不存在或不可读。", 404)
    links = (
        select(PlatformLink, Product, Variant, PlatformLinkCurrent)
        .join(
            Product,
            (Product.tenant_id == PlatformLink.tenant_id) & (Product.id == PlatformLink.product_id),
        )
        .outerjoin(
            Variant,
            (Variant.tenant_id == PlatformLink.tenant_id) & (Variant.id == PlatformLink.variant_id),
        )
        .join(
            PlatformLinkCurrent,
            (PlatformLinkCurrent.tenant_id == PlatformLink.tenant_id)
            & (PlatformLinkCurrent.product_id == PlatformLink.product_id)
            & (PlatformLinkCurrent.platform_id == PlatformLink.platform_id)
            & (PlatformLinkCurrent.target_id == PlatformLink.target_id),
        )
        .where(PlatformLink.platform_id.in_([row.id for row in page]))
    )
    if not payload.include_history:
        links = links.where(PlatformLink.version == PlatformLinkCurrent.current_version)
    if payload.product_id:
        links = links.where(
            PlatformLink.product_id == payload.product_id,
            PlatformLink.target_id == (payload.variant_id or payload.product_id),
        )
    if shared_only:
        links = links.where(
            Product.visibility == "category",
            (PlatformLink.variant_id.is_(None)) | (Variant.visibility == "category"),
        )
    grouped = {row.id: [] for row in page}
    for link, product, variant, current in s.execute(
        links.order_by(
            PlatformLink.platform_id,
            PlatformLink.target_id,
            PlatformLink.version,
        )
    ):
        grouped[link.platform_id].append(
            {
                "id": str(link.id),
                "category_id": str(link.category_id),
                "product_id": str(link.product_id),
                "product_name": product.name,
                "variant_id": str(link.variant_id) if link.variant_id else None,
                "variant_name": variant.name if variant else None,
                "version": link.version,
                "action": link.action,
                "current_version": current.current_version,
                "attached": current.attached,
                "compatibility": link.compatibility,
                "platform_version": link.platform_version,
                "reason": link.reason,
                "provenance": _provenance(link),
            }
        )
    return {
        "items": [
            {
                "id": str(row.id),
                "code": row.code,
                "name": row.name,
                "description": row.description,
                "provenance": _provenance(row),
                "links": grouped[row.id],
            }
            for row in page
        ],
        "next_cursor": str(page[-1].id) if len(rows) > payload.page_size else None,
        "link_scope": "category_shared" if shared_only else "current_audience",
    }
