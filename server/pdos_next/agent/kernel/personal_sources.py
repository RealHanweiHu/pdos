"""P91: a personal Run may pin its Human requester's currently readable registered sources.

Category stays the permission root. Every source is resolved by its actual
category under the requester's own ordinary RLS, then rechecked through the
existing category source guards; nothing here comes from model arguments.
"""

from dataclasses import replace

from sqlalchemy import select

from pdos_next.core.models import Artifact, Grant, Principal, now
from pdos_next.errors import DomainError

SCOPE_KEY = "personal_sources"


def _require_human_self(session, ctx):
    actor = session.get(Principal, ctx.actor_id)
    if (
        ctx.category_id is not None
        or ctx.run_id
        or getattr(ctx, "agent_run_id", None)
        or ctx.actor_id != ctx.requester_id
        or actor is None
        or actor.kind != "human"
        or not actor.active
    ):
        raise DomainError("FORBIDDEN_SCOPE", "个人来源只能由本人以人员身份绑定。", 403)


def category_context(ctx, artifact):
    return replace(ctx, category_id=artifact.category_id)


def resolve(session, ctx, artifact_id, expected_revision):
    """One exact active version the requester can read now, in its own category."""
    from pdos_next.core.service import source_for

    _require_human_self(session, ctx)
    # No category GUC: category_access() requires the requester's current grant,
    # and the artifact/model/original audience policies still apply.
    artifact = session.scalar(
        select(Artifact)
        .where(Artifact.id == artifact_id, Artifact.tenant_id == ctx.tenant_id)
        .execution_options(populate_existing=True)
        .with_for_update(read=True)
    )
    if artifact is None:
        raise DomainError("FORBIDDEN_SCOPE", "来源不在本人当前可读范围。", 403)
    return source_for(
        session,
        category_context(ctx, artifact),
        artifact.product_id,
        artifact.id,
        expected_revision,
    )


def _writer_reads(session, ctx, writer_id, category_id):
    # Same rule as a category Run: the AI identity must hold a current read grant there.
    grant = session.scalar(
        select(Grant)
        .where(
            Grant.tenant_id == ctx.tenant_id,
            Grant.category_id == category_id,
            Grant.principal_id == writer_id,
        )
        .execution_options(populate_existing=True)
        .with_for_update(read=True)
    )
    if grant is None or (grant.expires_at is not None and grant.expires_at <= now()):
        raise DomainError("FORBIDDEN_SCOPE", "小Pai当前没有该来源品类的读取授权。", 403)


def canonical(session, ctx, read_sources, writer_id=None):
    """Server read-set plus the receipt rows recorded on the Run (category, data class)."""
    from pdos_next.core.contracts import SourceRead

    reads, scopes = [], []
    for ref in read_sources:
        parsed = SourceRead.model_validate(
            {key: value for key, value in ref.items() if key != "product_id"}
        )
        actual = resolve(session, ctx, parsed.artifact_id, parsed.expected_revision)
        if writer_id is not None:
            _writer_reads(session, ctx, writer_id, actual.category_id)
        product = str(actual.product_id) if actual.product_id else None
        if "product_id" in ref and ref["product_id"] != product:
            raise DomainError("FORBIDDEN_SCOPE", "运行来源须保留原件的实际型号范围。", 403)
        read = {**parsed.model_dump(mode="json"), "product_id": product}
        reads.append(read)
        scopes.append(
            {
                **read,
                "category_id": str(actual.category_id),
                "data_category": "customer_original" if actual.original_id else "internal",
            }
        )
    order = sorted(range(len(reads)), key=lambda index: reads[index]["artifact_id"])
    return [reads[index] for index in order], [scopes[index] for index in order]
