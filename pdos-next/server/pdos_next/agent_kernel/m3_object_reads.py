"""M3 object read ports: actual Run bindings, ordinary RLS, and no mutations."""

from collections import Counter
from functools import partial
from typing import Literal
from uuid import UUID

from pydantic import Field
from sqlalchemy import func, or_, select

from pdos_next.clock import now
from pdos_next.database import tenant_session
from pdos_next.domain.preproject import views
from pdos_next.domain.preproject.access import fail, proposal
from pdos_next.domain.preproject.category_models import KnowledgeCurrent, ParameterCurrent
from pdos_next.domain.preproject.models import (
    ProposalDecision,
    ProposalItem,
    ProposalItemVersion,
    ProposalSource,
    ProposalSubmission,
)
from pdos_next.domain.preproject.schemas import ItemInput, Reference
from pdos_next.models import Category, Grant, Principal, Product
from pdos_next.schema_base import StrictModel
from pdos_next.service import require_access

from .execution import check_run_binding
from .models import AgentRun

PAGE_SIZE = 100
KNOWLEDGE_KINDS = ("boundary", "segment", "competitor", "voice", "regulation", "research_question")
ItemKind = ItemInput.model_fields["kind"].annotation


class CategoryListInput(StrictModel):
    name_query: str | None = None
    status: Literal["active", "archived"] | None = None
    cursor: UUID | None = None


class CategoryReadInput(StrictModel):
    pass


class ProposalReadInput(StrictModel):
    proposal_id: UUID


class ProposalItemsInput(ProposalReadInput):
    kinds: list[ItemKind] | None = None
    item_ids: list[UUID] | None = None
    question_status: Literal["open", "answered", "carried"] | None = None
    include_history: bool = Field(default=False, strict=True)


SCHEMAS = {
    "category.list": CategoryListInput,
    "category.read": CategoryReadInput,
    "proposal.read": ProposalReadInput,
    "proposal.items.read": ProposalItemsInput,
}


def _category_query(ctx):
    count = (
        select(func.count(Product.id))
        .where(Product.tenant_id == ctx.tenant_id, Product.category_id == Category.id)
        .correlate(Category)
        .scalar_subquery()
    )
    return (
        select(Category, Grant, Principal, count.label("model_count"))
        .join(Grant, (Grant.tenant_id == Category.tenant_id) & (Grant.category_id == Category.id))
        .outerjoin(
            Principal,
            (Principal.tenant_id == Category.tenant_id) & (Principal.id == Category.owner_id),
        )
        .where(
            Category.tenant_id == ctx.tenant_id,
            Grant.principal_id == ctx.requester_id,
            or_(Grant.expires_at.is_(None), Grant.expires_at > now()),
            # This SQL function enforces both actual actor and requester grants,
            # including their current activity and the transaction category scope.
            func.category_access(Category.tenant_id, Category.id, False).is_(True),
        )
    )


def _category_view(record):
    row, grant, owner, model_count = record
    return {
        "id": str(row.id),
        "key": row.key,
        "name": row.name,
        "purpose": row.purpose,
        "status": row.status,
        "revision": row.revision,
        "owner_id": str(row.owner_id),
        "owner": {"id": str(row.owner_id), "name": owner.name if owner else None},
        "permissions": {
            "read": True,
            "write": grant.can_write,
            "product_manager": grant.product_manager,
        },
        "model_count": model_count,
    }


def _references(value):
    """Extract actual persisted refs, including difference traces and linked evidence."""
    if isinstance(value, dict):
        if {"type", "id", "version"} <= value.keys() and value["type"] in {
            "human",
            "artifact",
            "original",
            "snapshot",
            "knowledge",
            "parameter",
            "definition",
            "claim",
        }:
            yield Reference.model_validate(
                {key: value[key] for key in Reference.model_fields if key in value}
            )
        elif {"artifact_id", "expected_revision"} <= value.keys():
            yield Reference(
                type="artifact", id=value["artifact_id"], version=value["expected_revision"]
            )
        for nested in value.values():
            yield from _references(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _references(nested)


def _public_sources(session, ctx, refs, seen=None):
    from pdos_next.domain.preproject.category_models import KnowledgeEntry
    from pdos_next.domain.preproject.claim_access import source_privacy
    from pdos_next.models import Artifact
    from pdos_next.service import source_for

    from .domain_reads import _outbound_unavailable, _public_references

    seen = set() if seen is None else seen
    for ref in refs:
        key = (ref.type, ref.id, ref.version)
        if key in seen:
            continue
        seen.add(key)
        if ref.type in {"artifact", "original"}:
            source = session.get(Artifact, ref.id)
            if (
                not source
                or source.tenant_id != ctx.tenant_id
                or source.category_id != ctx.category_id
            ):
                _outbound_unavailable()
            # The actual row, not a model-supplied product selector, supplies the
            # source product; normal source_for still checks permission/version.
            source_for(session, ctx, source.product_id, source.id, ref.version)
            from types import SimpleNamespace

            if (
                source_privacy(
                    session, ctx, SimpleNamespace(source_kind="artifact", artifact_id=source.id)
                )
                != "shared"
            ):
                _outbound_unavailable()
        elif ref.type == "knowledge":
            row = session.get(KnowledgeEntry, ref.id)
            if (
                not row
                or row.tenant_id != ctx.tenant_id
                or row.category_id != ctx.category_id
                or row.version != ref.version
            ):
                _outbound_unavailable()
            _public_sources(session, ctx, _references(row.source_refs), seen)
        else:
            _public_references(session, ctx, [ref])


def _public_proposal(session, ctx, row, document):
    from .domain_reads import _outbound_unavailable, _public_definition

    if (
        row.effective_visibility != "category"
        or row.private_source_count
        or row.customer_identities
    ):
        _outbound_unavailable()
    # The registry covers mounted roots independently of the selected item filter.
    roots = list(
        session.scalars(
            select(ProposalSource).where(
                ProposalSource.tenant_id == ctx.tenant_id,
                ProposalSource.category_id == ctx.category_id,
                ProposalSource.proposal_id == row.id,
            )
        )
    )
    if any(root.privacy != "shared" for root in roots):
        _outbound_unavailable()
    refs = [
        *_references(document),
        *(
            Reference(type=root.source_type, id=root.source_id, version=root.source_version)
            for root in roots
        ),
    ]
    if row.baseline_definition_id:
        _public_definition(
            session,
            ctx,
            {"id": row.baseline_definition_id, "revision": row.baseline_definition_revision},
        )
    _public_sources(session, ctx, refs)


def _item_views(session, ctx, row, payload):
    from pdos_next.domain.preproject.root_sources import project_items

    query = (
        select(ProposalItem, ProposalItemVersion)
        .join(
            ProposalItemVersion,
            (ProposalItemVersion.tenant_id == ProposalItem.tenant_id)
            & (ProposalItemVersion.item_id == ProposalItem.id),
        )
        .where(
            ProposalItem.tenant_id == ctx.tenant_id,
            ProposalItem.category_id == ctx.category_id,
            ProposalItem.proposal_id == row.id,
        )
    )
    if not payload.include_history:
        query = query.where(
            ProposalItemVersion.version == ProposalItem.current_version,
            ProposalItem.removed.is_(False),
        )
    if payload.kinds is not None:
        query = query.where(ProposalItemVersion.kind.in_(payload.kinds))
    if payload.item_ids is not None:
        query = query.where(ProposalItem.id.in_(payload.item_ids))
    if payload.question_status is not None:
        query = query.where(
            ProposalItemVersion.kind == "question",
            ProposalItemVersion.content["status"].astext == payload.question_status,
        )
    result = []
    for item, version in session.execute(
        query.order_by(ProposalItem.sort_key, ProposalItem.id, ProposalItemVersion.version)
    ):
        result.append(
            {
                "item_id": str(item.id),
                "version": version.version,
                "current_version": item.current_version,
                "kind": version.kind,
                "content": version.content,
                "source_refs": version.source_refs,
                "origin": version.origin,
                "writer_id": str(version.writer_id),
                "run_id": str(version.run_id) if version.run_id else None,
                "confirmed_by": str(version.confirmed_by) if version.confirmed_by else None,
                "receipt_id": str(version.receipt_id) if version.receipt_id else None,
                "prepared_candidate_id": str(version.prepared_candidate_id)
                if version.prepared_candidate_id
                else None,
                "human_value": version.origin == "human" or version.confirmed_by is not None,
                "removed": version.removed,
                "created_at": version.created_at.isoformat(),
            }
        )
    return project_items(session, row, result)


class M3ObjectReads:
    def __init__(self, store, commands):
        self.store, self.commands = store, commands

    def call(self, scope, args, *, name):
        payload = SCHEMAS[name].model_validate(args)
        if name != "category.list" and scope.category_id is None:
            fail("FORBIDDEN_SCOPE", "category_run_required", "此读取须绑定当前品类。", 403)
        with tenant_session(
            self.store.engine,
            scope.tenant_id,
            actor_id=scope.writer_id,
            requester_id=scope.requester_id,
            category_id=scope.category_id,
            read_snapshot=True,
        ) as session:
            run = session.get(AgentRun, scope.run_id)
            check_run_binding(run, scope, for_write=False)
            self.store.authority(session, scope)
            ctx = self.commands.context(scope)
            if name == "category.list":
                query = _category_query(ctx)
                if scope.category_id is not None:
                    query = query.where(Category.id == scope.category_id)
                if payload.name_query:
                    query = query.where(
                        or_(
                            Category.name.icontains(payload.name_query, autoescape=True),
                            Category.key.icontains(payload.name_query, autoescape=True),
                        )
                    )
                if payload.status:
                    query = query.where(Category.status == payload.status)
                if payload.cursor:
                    query = query.where(Category.id > payload.cursor)
                rows = session.execute(query.order_by(Category.id).limit(PAGE_SIZE + 1)).all()
                return {
                    "items": [_category_view(row) for row in rows[:PAGE_SIZE]],
                    "next_cursor": str(rows[PAGE_SIZE - 1][0].id)
                    if len(rows) > PAGE_SIZE
                    else None,
                }
            require_access(session, ctx, scope.product_id)
            if name == "category.read":
                record = session.execute(
                    _category_query(ctx).where(Category.id == scope.category_id)
                ).first()
                if not record:
                    fail("FORBIDDEN_SCOPE", "category_unavailable", "品类不在当前授权范围。", 403)
                counts = dict(
                    session.execute(
                        select(KnowledgeCurrent.kind, func.count())
                        .where(
                            KnowledgeCurrent.tenant_id == ctx.tenant_id,
                            KnowledgeCurrent.category_id == ctx.category_id,
                            KnowledgeCurrent.status == "active",
                        )
                        .group_by(KnowledgeCurrent.kind)
                    ).all()
                )
                parameter_count = session.scalar(
                    select(func.count())
                    .select_from(ParameterCurrent)
                    .where(
                        ParameterCurrent.tenant_id == ctx.tenant_id,
                        ParameterCurrent.category_id == ctx.category_id,
                    )
                )
                return {
                    **_category_view(record),
                    "knowledge_counts": {kind: counts.get(kind, 0) for kind in KNOWLEDGE_KINDS},
                    "parameter_count": parameter_count,
                }
            if run.proposal_id is None or payload.proposal_id != run.proposal_id:
                fail(
                    "FORBIDDEN_SCOPE",
                    "proposal_run_mismatch",
                    "读取须使用本次运行绑定的提案。",
                    403,
                )
            row = proposal(session, ctx, run.proposal_id)
            from .proposal_context import bound_head, validate

            bound_context = bound_head(run, row)
            doc = views.document(session, row)
            if bound_context:
                validate(session, scope, run, extra_value=doc)
            else:
                _public_proposal(session, ctx, row, doc)
            if name == "proposal.items.read":
                items = _item_views(session, ctx, row, payload)
                # History can retain formerly private evidence after current items
                # were deidentified. Every returned version has its own check.
                if bound_context:
                    validate(session, scope, run, extra_value=items)
                else:
                    _public_sources(session, ctx, _references(items))
                return {
                    "proposal_id": str(row.id),
                    "revision": row.revision,
                    "items": items,
                    "questions": [item for item in items if item["kind"] == "question"],
                }
            submission = (
                session.get(ProposalSubmission, row.current_submission_id)
                if row.current_submission_id
                else None
            )
            decision = session.scalar(
                select(ProposalDecision)
                .where(
                    ProposalDecision.tenant_id == ctx.tenant_id,
                    ProposalDecision.category_id == ctx.category_id,
                    ProposalDecision.proposal_id == row.id,
                )
                .order_by(ProposalDecision.created_at.desc(), ProposalDecision.id.desc())
                .limit(1)
            )
            changes = views.context_changes(session, ctx, row, doc)
            return {
                "id": str(row.id),
                "category_id": str(row.category_id),
                "owner_id": str(row.owner_id),
                "title": row.title,
                "brief": row.brief,
                "entry_kind": row.entry_kind,
                "target_kind": row.target_kind,
                "status": row.status,
                "revision": row.revision,
                "visibility": row.visibility,
                "effective_visibility": row.effective_visibility,
                "visibility_reasons": [
                    "private_sources"
                    if row.private_source_count
                    else "proposal_private"
                    if row.effective_visibility != "category"
                    else "category_shared"
                ],
                "private_source_count": row.private_source_count,
                "baseline_product_id": str(row.baseline_product_id)
                if row.baseline_product_id
                else None,
                "baseline_definition_id": str(row.baseline_definition_id)
                if row.baseline_definition_id
                else None,
                "baseline_definition_revision": row.baseline_definition_revision,
                "item_counts": dict(Counter(item["kind"] for item in doc["items"])),
                "question_counts": dict(
                    Counter(
                        item["content"]["status"]
                        for item in doc["items"]
                        if item["kind"] == "question"
                    )
                ),
                "questions": [item for item in doc["items"] if item["kind"] == "question"],
                "submission": {
                    "id": str(submission.id),
                    "revision": submission.revision,
                    "reviewer_id": str(submission.reviewer_id),
                    "option_count": submission.option_count,
                    "created_at": submission.created_at.isoformat(),
                }
                if submission
                else None,
                "decision": {
                    "id": str(decision.id),
                    "submission_id": str(decision.submission_id),
                    "outcome": decision.outcome,
                    "decided_by": str(decision.decided_by),
                    "created_at": decision.created_at.isoformat(),
                }
                if decision
                else None,
                "context_hint": bool(changes),
                "context_changes": changes,
            }

    def handlers(self):
        return {name: partial(self.call, name=name) for name in SCHEMAS}
