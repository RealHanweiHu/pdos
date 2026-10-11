"""Scoped evidence associations, named Claim withdrawal, and proposal sharing.

Evidence associations are independent rows. No operation here edits historical
item content or attribution. The common command owns authorization admission,
confirmation consumption, receipt persistence and the enclosing transaction.
"""

from collections import Counter
from dataclasses import dataclass, field
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import or_, select, text

from pdos_next.category_scope import category_scope
from pdos_next.models import (
    Artifact,
    Claim,
    ObjectAudience,
    Product,
    UploadedOriginal,
)
from pdos_next.request_proof import batch_read, command_inputs_once
from pdos_next.service import digest, require_access, source_for

from .access import fail, human, member, proposal
from .evidence_schemas import ClaimWithdraw, EvidenceLinkCreate, ProposalShare

# These rows can connect product originals to category consumers. The common
# entry must acquire Category before Product even with an empty read set.
category_lifecycle_fence = True


@dataclass
class ValidatedEvidence:
    subject: object
    provenance: dict = field(default_factory=dict)
    source_ref: object | None = None
    source_privacy: str | None = None
    proposal: object | None = None
    links: list = field(default_factory=list)
    affected: list = field(default_factory=list)
    changes: dict = field(default_factory=dict)
    checks: dict = field(default_factory=dict)
    watermark: dict = field(default_factory=dict)
    claims: list = field(default_factory=list)
    confirmation_id: UUID | None = None


def requires_category_write(command):
    # Private Claim withdrawal and proposal sharing are owner rights. Each target
    # resolver below separately proves write authority where the target needs it.
    return False


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"confirmation_token"})


def _row(s, ctx, model, identity, *, lock=True):
    row = batch_read(s, model, [identity], lock=lock).get(identity)
    if not row or row.tenant_id != ctx.tenant_id or row.category_id != ctx.category_id:
        fail("SOURCE_UNAVAILABLE", "source_unreadable", "对象不在当前可读品类范围。")
    return row


def _owner(ctx, row):
    if row.owner_id != ctx.requester_id:
        fail("NAMED_DECISION_REQUIRED", "owner_only", "仅由提案负责人办理。", 403)


def _editable(row):
    if row.status not in {"draft", "returned"}:
        fail("VERSION_CONFLICT", "proposal_locked", "此提案已锁定；退回后可继续编辑。")


def _version(actual, expected):
    if actual != expected:
        fail("VERSION_CONFLICT", "evidence_version_moved", "引用版本已变化，请重新核对。")


def _claim_private(row):
    return row.privacy == "private"


def _source(s, ctx, ref):
    """Return bottom-level source privacy, independent of a Claim's private run."""
    from pdos_next.agent_kernel.models import PublicWebSnapshot

    from .schemas import Reference

    typ = "artifact" if ref.type == "original" else ref.type
    if typ == "claim":
        from .claim_access import resolve, source_privacy, source_reference

        row = resolve(s, ctx, ref.id, ref.version, approved=True, lock=True)
        return source_reference(row), source_privacy(s, ctx, row), row
    if typ == "artifact":
        candidate = _row(s, ctx, Artifact, ref.id)
        row = source_for(s, ctx, candidate.product_id, ref.id, ref.version)
        parent = _row(s, ctx, Product, row.product_id) if row.product_id else None
        original = _row(s, ctx, UploadedOriginal, row.original_id) if row.original_id else None
        privacy = (
            "shared"
            if (
                row.visibility == "category"
                and (parent is None or parent.visibility == "category")
                and (original is None or original.visibility == "category")
            )
            else "private"
        )
    elif typ == "snapshot":
        row = _row(s, ctx, PublicWebSnapshot, ref.id)
        if ref.version != 1 or row.status not in {"ok", "partial"}:
            fail("SOURCE_STALE", "snapshot_unavailable", "网页快照不可用。")
        privacy = "shared" if row.visibility == "category" else "private"
    else:
        fail("VALIDATION_FAILED", "evidence_type_invalid", "证据类型不受支持。")
    return Reference(type=typ, id=ref.id, version=ref.version), privacy, row


def _target(s, ctx, command, scope, target):
    from pdos_next.domain.products.models import (
        DefinitionRevision,
        DefinitionSpecCurrent,
        DefinitionSpecRow,
    )

    from .category_models import KnowledgeCurrent, KnowledgeEntry
    from .models import ProposalItem

    if target.type == "proposal_item":
        category_scope(s, ctx, write=True, lock=True)
        item = _row(s, ctx, ProposalItem, target.id)
        owner = proposal(s, ctx, item.proposal_id, lock=True)
        _owner(ctx, owner)
        _editable(owner)
        _version(item.current_version, target.version)
        if item.removed or command.product_id is not None:
            fail("FORBIDDEN_SCOPE", "evidence_target_scope", "条目不在当前提案范围。", 403)
        return item, owner, owner.effective_visibility != "private"
    if target.type == "knowledge_entry":
        category_scope(s, ctx, write=True, lock=True)
        # Entries are immutable and have no UPDATE privilege. The Category lock
        # above serializes current-pointer changes; a row write lock is neither
        # required nor available for the fixed entry.
        row = _row(s, ctx, KnowledgeEntry, target.id, lock=False)
        current = s.get(KnowledgeCurrent, (ctx.tenant_id, row.lineage_id))
        if command.product_id is not None or not current or current.category_id != ctx.category_id:
            fail("FORBIDDEN_SCOPE", "evidence_target_scope", "知识不在当前品类范围。", 403)
        _version(row.version, target.version)
        if current.current_entry_id != row.id or current.status != "active":
            fail("SOURCE_STALE", "knowledge_unreadable", "只能关联当前有效知识版本。")
        return row, None, True
    row = _row(s, ctx, DefinitionSpecRow, target.id, lock=False)
    if command.product_id != row.product_id or scope.id != row.product_id:
        fail("FORBIDDEN_SCOPE", "evidence_target_scope", "规格不在当前型号范围。", 403)
    product = require_access(s, ctx, row.product_id, write=True, lock=True)
    definition = _row(s, ctx, DefinitionRevision, row.definition_id)
    if definition.product_id != row.product_id:
        fail("FORBIDDEN_SCOPE", "evidence_target_scope", "规格与定义范围不一致。", 403)
    _version(definition.revision, target.version)
    pointer = s.scalar(
        select(DefinitionSpecCurrent).where(
            DefinitionSpecCurrent.tenant_id == ctx.tenant_id,
            DefinitionSpecCurrent.item_id == row.item_id,
            DefinitionSpecCurrent.current_row_id == row.id,
            DefinitionSpecCurrent.removed.is_(False),
        )
    )
    if not pointer:
        fail("VERSION_CONFLICT", "definition_item_moved", "只能关联当前有效规格版本。")
    if definition.sealed or definition.status != "draft":
        fail("VERSION_CONFLICT", "definition_sealed", "封存定义不能追加关联。")
    return row, None, definition.visibility != "private" and product.visibility != "private"


def _link_provenance(s, ctx, command, scope, target_proposal):
    if ctx.agent_run_id:
        from pdos_next.agent_kernel.execution import command_call, command_run

        run = command_run(s, ctx, scope.id)
        command_call(s, ctx, command.operation)
        if target_proposal and run.proposal_id != target_proposal.id:
            fail("FORBIDDEN_SCOPE", "proposal_run_mismatch", "关联不属于运行绑定的提案。", 403)
        if not target_proposal and run.private_context:
            fail("FORBIDDEN_SCOPE", "private_context_run", "私有上下文不能写入共享证据关联。", 403)
        return {
            "origin": "ai_draft",
            "writer_id": run.writer_id,
            "run_id": run.id,
            "confirmed_by": None,
        }
    human(s, ctx)
    return {"origin": "human", "writer_id": ctx.actor_id, "run_id": None, "confirmed_by": None}


def links_for_target(s, ctx, target_type, target_id, version=None, *, include_inactive=False):
    """RLS-scoped association rows. Callers must first prove the target readable."""
    from .evidence_models import EvidenceLink

    query = select(EvidenceLink).where(
        EvidenceLink.tenant_id == ctx.tenant_id,
        EvidenceLink.category_id == ctx.category_id,
        EvidenceLink.target_type == target_type,
        EvidenceLink.target_id == target_id,
    )
    if version is not None:
        query = query.where(EvidenceLink.target_version == version)
    if not include_inactive:
        query = query.where(EvidenceLink.reverted_by_receipt_id.is_(None))
    return list(s.scalars(query.order_by(EvidenceLink.id)))


def active_link_refs(s, ctx, target_type, target_id, version=None):
    """Append these reference dictionaries to a readable target's projection."""
    refs = []
    for link in links_for_target(s, ctx, target_type, target_id, version):
        if link.evidence_type == "claim":
            claim = _row(s, ctx, Claim, link.evidence_id, lock=False)
            if claim.status != "active" or claim.revision != link.evidence_version:
                continue
        refs.append(
            {
                "type": link.evidence_type,
                "id": str(link.evidence_id),
                "version": link.evidence_version,
            }
        )
    return refs


def _source_key(ref):
    return ("original" if ref.type == "artifact" else ref.type, ref.id, ref.version)


def _source_delta(s, ctx, row, ref, amount, privacy):
    """Update exactly one association's bottom-level source contribution."""
    from .models import ProposalSource

    kind, identity, version = _source_key(ref)
    pointer = s.scalar(
        select(ProposalSource)
        .where(
            ProposalSource.tenant_id == ctx.tenant_id,
            ProposalSource.category_id == ctx.category_id,
            ProposalSource.proposal_id == row.id,
            ProposalSource.source_type == kind,
            ProposalSource.source_id == identity,
            ProposalSource.source_version == version,
        )
        .with_for_update()
    )
    if pointer:
        remaining = pointer.ref_count + amount
        if remaining < 0:
            fail("VALIDATION_FAILED", "source_count_inconsistent", "来源计数不一致。")
        if remaining == 0:
            row.private_source_count -= int(pointer.privacy == "private")
            s.delete(pointer)
        else:
            row.private_source_count += int(privacy == "private") - int(
                pointer.privacy == "private"
            )
            pointer.privacy = privacy
            pointer.ref_count = remaining
    else:
        if amount < 0:
            fail("VALIDATION_FAILED", "source_count_inconsistent", "来源计数不一致。")
        s.add(
            ProposalSource(
                tenant_id=ctx.tenant_id,
                category_id=ctx.category_id,
                proposal_id=row.id,
                source_type=kind,
                source_id=identity,
                source_version=version,
                privacy=privacy,
                ref_count=amount,
            )
        )
        row.private_source_count += int(privacy == "private")
    row.effective_visibility = "private" if row.private_source_count else row.visibility


def _raw_document(s, row):
    """Read immutable inputs without the UI's association projection."""
    from .models import ProposalItem, ProposalItemVersion

    versions = list(
        s.scalars(
            select(ProposalItemVersion)
            .join(
                ProposalItem,
                (ProposalItem.tenant_id == ProposalItemVersion.tenant_id)
                & (ProposalItem.id == ProposalItemVersion.item_id)
                & (ProposalItem.current_version == ProposalItemVersion.version),
            )
            .where(
                ProposalItem.tenant_id == row.tenant_id,
                ProposalItem.proposal_id == row.id,
                ProposalItem.removed.is_(False),
            )
            .order_by(ProposalItem.id)
        )
    )
    refs = [
        *row.source_refs,
        *row.context_refs,
        *(ref for item in versions for ref in item.source_refs),
    ]
    return versions, refs


def _proposal_links(s, ctx, versions):
    from .evidence_models import EvidenceLink

    versions = {row.item_id: row.version for row in versions}
    if not versions:
        return []
    rows = s.scalars(
        select(EvidenceLink)
        .where(
            EvidenceLink.tenant_id == ctx.tenant_id,
            EvidenceLink.category_id == ctx.category_id,
            EvidenceLink.target_type == "proposal_item",
            EvidenceLink.target_id.in_(versions),
            EvidenceLink.reverted_by_receipt_id.is_(None),
        )
        .order_by(EvidenceLink.id)
        .with_for_update()
    )
    return [row for row in rows if row.target_version == versions[row.target_id]]


def _ref(ref):
    # Allows Claim refs before the shared Reference registry is activated.
    return SimpleNamespace(type=ref["type"], id=UUID(str(ref["id"])), version=ref["version"])


def _share_sources(s, ctx, row):
    from .models import ProposalSource
    from .schemas import Reference
    from .service import _references

    versions, refs = _raw_document(s, row)
    links = _proposal_links(s, ctx, versions)
    refs.extend(
        {"type": link.evidence_type, "id": str(link.evidence_id), "version": link.evidence_version}
        for link in links
    )
    counts, privacy, states = Counter(), {}, []
    for data in refs:
        ref = _ref(data)
        if ref.type in {"human", "parameter"}:
            continue
        if ref.type == "claim":
            claim = _row(s, ctx, Claim, ref.id)
            if claim.status in {"withdrawn", "reverted"}:
                states.append(
                    {"claim_id": str(claim.id), "revision": claim.revision, "status": claim.status}
                )
                continue
        if ref.type in {"claim", "artifact", "original", "snapshot"}:
            bottom, classification, source = _source(s, ctx, ref)
            states.append(
                {
                    "type": ref.type,
                    "id": str(ref.id),
                    "version": ref.version,
                    "status": getattr(source, "status", None),
                    "privacy": classification,
                    "content_hash": getattr(source, "content_hash", None),
                }
            )
        else:
            typed = Reference.model_validate(data)
            classification = _references(s, ctx, [typed])[0][1]
            bottom = typed
        key = _source_key(bottom)
        counts[key] += 1
        privacy[key] = classification
    pointers = list(
        s.scalars(
            select(ProposalSource)
            .where(
                ProposalSource.tenant_id == ctx.tenant_id,
                ProposalSource.category_id == ctx.category_id,
                ProposalSource.proposal_id == row.id,
            )
            .order_by(ProposalSource.id)
            .with_for_update()
        )
    )
    stored = Counter(
        {(p.source_type, p.source_id, p.source_version): p.ref_count for p in pointers}
    )
    private_count = sum(privacy[key] == "private" for key in counts)
    if (
        counts != stored
        or row.private_source_count != private_count
        or any(
            p.privacy != privacy[(p.source_type, p.source_id, p.source_version)] for p in pointers
        )
    ):
        fail("SOURCE_STALE", "source_count_inconsistent", "实际来源与来源计数不同，请刷新修复。")
    if private_count:
        fail("VALIDATION_FAILED", "private_sources_present", "仍引用私有来源，不能共享。")
    return {
        "sources": sorted(states, key=lambda value: digest(value)),
        "counts": sorted(
            [kind, str(identity), version, amount]
            for (kind, identity, version), amount in counts.items()
        ),
        "links": sorted(str(link.id) for link in links),
    }


def _share_claims(s, ctx, row):
    from .category_service import _private_checks
    from .claim_access import resolve, source_privacy

    claims = list(
        s.scalars(
            select(Claim)
            .where(
                Claim.tenant_id == ctx.tenant_id,
                Claim.category_id == ctx.category_id,
                Claim.proposal_id == row.id,
                Claim.status == "active",
                Claim.privacy == "private",
            )
            .order_by(Claim.id)
            .with_for_update()
        )
    )
    views, hits = [], []
    for claim in claims:
        resolve(s, ctx, claim.id, claim.revision, approved=True, lock=True)
        if source_privacy(s, ctx, claim) == "private":
            fail("VALIDATION_FAILED", "private_sources_present", "事实仍来自私有原件，不能共享。")
        material = {"content": claim.content, "quote": claim.quote, "statement": claim.statement}
        checked = _private_checks(s, ctx, row, material)
        views.append(
            {
                "id": str(claim.id),
                "version": claim.revision,
                "content": claim.content,
                "quote": claim.quote,
                "statement": claim.statement,
                "checks": checked,
            }
        )
        hits.extend({**hit, "claim_id": str(claim.id)} for hit in checked["hits"])
    return claims, {"claims": views, "hits": hits}


def _signed_consumptions(s, ctx, claim):
    # The scoped trusted predicate sees signed dependencies hidden by the
    # current reader's RLS, without disclosing their private proposal contents.
    if s.scalar(
        text("SELECT m3_claim_is_consumed(:tenant,:category,:claim)"),
        {"tenant": ctx.tenant_id, "category": ctx.category_id, "claim": claim.id},
    ):
        fail(
            "UNDO_BLOCKED_BY_DEPENDENCY",
            "consumed_by_decision",
            "已签署决定消费的事实不能撤回。",
        )


def _withdraw_impacts(s, ctx, claim):
    from .category_models import KnowledgeCurrent, KnowledgeEntry
    from .evidence_models import EvidenceLink
    from .models import Proposal, ProposalItem, ProposalItemVersion

    links = list(
        s.scalars(
            select(EvidenceLink)
            .where(
                EvidenceLink.tenant_id == ctx.tenant_id,
                EvidenceLink.category_id == ctx.category_id,
                EvidenceLink.evidence_type == "claim",
                EvidenceLink.evidence_id == claim.id,
                EvidenceLink.reverted_by_receipt_id.is_(None),
            )
            .order_by(EvidenceLink.id)
            .with_for_update()
        )
    )
    affected = [
        {"type": link.target_type, "id": str(link.target_id), "version": link.target_version}
        for link in links
    ]
    changes = {}
    needle = [{"type": "claim", "id": str(claim.id)}]
    linked_items = [link.target_id for link in links if link.target_type == "proposal_item"]
    item_reference = (
        select(ProposalItem.id)
        .join(
            ProposalItemVersion,
            (ProposalItemVersion.tenant_id == ProposalItem.tenant_id)
            & (ProposalItemVersion.item_id == ProposalItem.id)
            & (ProposalItemVersion.version == ProposalItem.current_version),
        )
        .where(
            ProposalItem.tenant_id == ctx.tenant_id,
            ProposalItem.category_id == ctx.category_id,
            ProposalItem.proposal_id == Proposal.id,
            ProposalItem.removed.is_(False),
            or_(
                ProposalItemVersion.source_refs.contains(needle), ProposalItem.id.in_(linked_items)
            ),
        )
        .exists()
    )
    # This RLS-scoped scan never exposes other members' private drafts. The SQL
    # receipt guard additionally invalidates their hidden source projections.
    for row in s.scalars(
        select(Proposal)
        .where(
            Proposal.tenant_id == ctx.tenant_id,
            Proposal.category_id == ctx.category_id,
            or_(
                Proposal.source_refs.contains(needle),
                Proposal.context_refs.contains(needle),
                item_reference,
            ),
        )
        .order_by(Proposal.id)
        .with_for_update()
    ):
        versions, refs = _raw_document(s, row)
        count = sum(ref["type"] == "claim" and str(ref["id"]) == str(claim.id) for ref in refs)
        current = {item.item_id: item.version for item in versions}
        count += sum(
            link.target_type == "proposal_item"
            and current.get(link.target_id) == link.target_version
            for link in links
        )
        if count:
            changes[row.id] = (row, count)
            affected.append({"type": "proposal", "id": str(row.id), "version": row.revision})
            affected.extend(
                {"type": "proposal_item", "id": str(item.item_id), "version": item.version}
                for item in versions
                if any(
                    ref["type"] == "claim" and str(ref["id"]) == str(claim.id)
                    for ref in item.source_refs
                )
            )
    knowledge = s.scalars(
        select(KnowledgeEntry)
        .join(
            KnowledgeCurrent,
            (KnowledgeCurrent.tenant_id == KnowledgeEntry.tenant_id)
            & (KnowledgeCurrent.current_entry_id == KnowledgeEntry.id),
        )
        .where(
            KnowledgeEntry.tenant_id == ctx.tenant_id,
            KnowledgeEntry.category_id == ctx.category_id,
            KnowledgeCurrent.status == "active",
            KnowledgeEntry.source_refs.contains([{"type": "claim", "id": str(claim.id)}]),
        )
    )
    affected.extend(
        {"type": "knowledge_entry", "id": str(row.id), "version": row.version} for row in knowledge
    )
    return links, changes, affected


@command_inputs_once
def validate(s, ctx, command, scope, payload):
    category_scope(s, ctx, lock=True)
    if isinstance(payload, EvidenceLinkCreate):
        target, owner, shared = _target(s, ctx, command, scope, payload.target)
        source, privacy, evidence = _source(s, ctx, payload.evidence)
        if payload.evidence.type != "claim":
            from .root_sources import validate_locator

            validate_locator(
                payload.evidence.locator,
                evidence.markdown if payload.evidence.type == "snapshot" else evidence.content,
            )
        private = privacy == "private" or (
            payload.evidence.type == "claim" and _claim_private(evidence)
        )
        if private and shared:
            fail("VALIDATION_FAILED", "private_source_in_shared", "私有证据不能关联共享目标。")
        if (
            payload.evidence.type == "claim"
            and _claim_private(evidence)
            and (not owner or evidence.proposal_id != owner.id)
        ):
            fail("FORBIDDEN_SCOPE", "claim_proposal_mismatch", "私有事实只能关联所在提案。", 403)
        return ValidatedEvidence(
            target, _link_provenance(s, ctx, command, scope, owner), source, privacy, owner
        )
    if isinstance(payload, ProposalShare) and (
        ctx.run_id or ctx.agent_run_id or ctx.actor_id != ctx.requester_id
    ):
        fail("NAMED_DECISION_REQUIRED", "owner_only", "共享只由提案负责人本人办理。", 403)
    human(s, ctx)
    if isinstance(payload, ClaimWithdraw):
        from .claim_access import resolve, source_privacy, source_reference

        row = resolve(s, ctx, payload.claim_id, payload.expected_version)
        if row.product_id != command.product_id:
            fail("FORBIDDEN_SCOPE", "claim_scope_mismatch", "事实不在当前命令范围。", 403)
        if _claim_private(row):
            if row.proposal_id is None:
                if row.human_owner_id != ctx.requester_id:
                    fail("NAMED_DECISION_REQUIRED", "owner_only", "仅事实负责人可撤回。", 403)
            else:
                _owner(ctx, proposal(s, ctx, row.proposal_id, lock=True))
        else:
            category_scope(s, ctx, write=True, lock=True)
        links, changes, affected = _withdraw_impacts(s, ctx, row)
        # Proposal/G0 commands lock their proposal before Claim dependencies.
        # Match that order, then recheck the exact Claim version under its lock.
        _row(s, ctx, Claim, payload.claim_id)
        row = resolve(s, ctx, payload.claim_id, payload.expected_version)
        _signed_consumptions(s, ctx, row)
        return ValidatedEvidence(
            row,
            source_ref=source_reference(row),
            source_privacy=source_privacy(s, ctx, row),
            links=links,
            changes=changes,
            affected=affected,
        )
    if not isinstance(payload, ProposalShare):
        fail("VALIDATION_FAILED", "evidence_operation_invalid", "不支持的证据操作。")
    if command.product_id is not None:
        fail("FORBIDDEN_SCOPE", "proposal_scope_mismatch", "提案共享使用品类范围。", 403)
    row = proposal(s, ctx, payload.proposal_id, lock=True)
    _owner(ctx, row)
    _version(row.revision, payload.expected_revision)
    audiences = []
    for identity in sorted(payload.audience_ids, key=str):
        grant = member(s, ctx, identity)
        audiences.append(
            {
                "id": str(identity),
                "access_epoch": grant.access_epoch,
                "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
            }
        )
    sources = _share_sources(s, ctx, row)
    claims, checks = _share_claims(s, ctx, row)
    return ValidatedEvidence(
        row, checks=checks, claims=claims, watermark={**sources, "audiences": audiences}
    )


def confirmation_subject(s, ctx, command, scope, payload):
    assessed = validate(s, ctx, command, scope, payload)
    if isinstance(payload, ClaimWithdraw):
        return "claim", assessed.subject
    if isinstance(payload, ProposalShare):
        return "proposal", assessed.subject
    fail("VALIDATION_FAILED", "confirmation_not_supported", "证据关联无需人工确认。")


def preview_view(s, ctx, command, scope, payload):
    assessed = validate(s, ctx, command, scope, payload)
    if isinstance(payload, ProposalShare):
        return {
            "operation": command.operation,
            "payload": semantic(payload),
            "proposal_revision": assessed.subject.revision,
            "checks": assessed.checks,
            "watermark": assessed.watermark,
            "effect": "共享提案及列出的有效私有上下文事实。",
        }
    return {
        "operation": command.operation,
        "payload": semantic(payload),
        "claim_revision": assessed.subject.revision,
        "affected_targets": sorted(assessed.affected, key=lambda value: digest(value)),
        "links": sorted(str(link.id) for link in assessed.links),
        "effect": "撤回事实并失效其证据关联；历史条目值保留。",
    }


def _confirmation_id(s, assessed):
    identity = assessed.confirmation_id or s.info.get("evidence_confirmation_id")
    if not identity:
        fail("CONFIRMATION_REQUIRED", "confirmation_missing", "缺少本事务已消费的确认。")
    return identity


def apply_validated(s, ctx, command, scope, payload, validated):
    from .evidence_models import ClaimWithdrawal, EvidenceLink

    receipt_id = uuid4()
    if isinstance(payload, EvidenceLinkCreate):
        row = EvidenceLink(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            category_id=ctx.category_id,
            evidence_type=payload.evidence.type,
            evidence_id=payload.evidence.id,
            evidence_version=payload.evidence.version,
            evidence_locator=payload.evidence.locator,
            target_type=payload.target.type,
            target_id=payload.target.id,
            target_version=payload.target.version,
            relation=payload.relation,
            receipt_id=receipt_id,
            **validated.provenance,
        )
        s.add(row)
        if validated.proposal:
            _source_delta(
                s, ctx, validated.proposal, validated.source_ref, 1, validated.source_privacy
            )
            validated.proposal.revision += 1
        identity, revision, status = row.id, 1, "active"
        result = {"link_id": str(row.id), "target": payload.target.model_dump(mode="json")}
        kind, visibility = (
            "evidence_link",
            (validated.proposal.effective_visibility if validated.proposal else "category"),
        )
    elif isinstance(payload, ClaimWithdraw):
        row = validated.subject
        s.add(
            ClaimWithdrawal(
                id=uuid4(),
                tenant_id=ctx.tenant_id,
                category_id=ctx.category_id,
                claim_id=row.id,
                expected_version=payload.expected_version,
                reason=payload.reason,
                actor_id=ctx.actor_id,
                confirmation_id=_confirmation_id(s, validated),
                receipt_id=receipt_id,
            )
        )
        # The transaction-bound withdrawal trigger reconciles every affected
        # source projection, including private drafts hidden from this caller.
        row.status, row.revision = "withdrawn", row.revision + 1
        identity, revision, status = row.id, row.revision, row.status
        kind, visibility = "claim", "private" if _claim_private(row) else "category"
        result = {
            "claim_id": str(row.id),
            "status": row.status,
            "affected_targets": validated.affected,
        }
    else:
        row = validated.subject
        if validated.checks["hits"]:
            fail(
                "VALIDATION_FAILED",
                "identity_not_removed",
                "请先撤回含客户身份的事实。",
                hits=validated.checks["hits"],
            )
        if validated.claims and not payload.deidentified_confirmed:
            fail(
                "CONFIRMATION_REQUIRED", "deidentification_not_confirmed", "请确认已去除客户身份。"
            )
        audiences = list(
            s.scalars(
                select(ObjectAudience)
                .where(
                    ObjectAudience.tenant_id == ctx.tenant_id,
                    ObjectAudience.category_id == ctx.category_id,
                    ObjectAudience.object_type == "proposals",
                    ObjectAudience.subject_id == row.id,
                )
                .with_for_update()
            )
        )
        wanted = set(payload.audience_ids)
        # The designated reviewer remains entitled to the submitted review.
        if row.current_submission_id:
            from .models import ProposalSubmission

            current = _row(s, ctx, ProposalSubmission, row.current_submission_id)
            wanted.add(current.reviewer_id)
        for audience in audiences:
            if audience.principal_id not in wanted:
                s.delete(audience)
        present = {audience.principal_id for audience in audiences}
        for identity in wanted - present:
            s.add(
                ObjectAudience(
                    tenant_id=ctx.tenant_id,
                    category_id=ctx.category_id,
                    object_type="proposals",
                    subject_id=row.id,
                    owner_id=row.owner_id,
                    principal_id=identity,
                )
            )
        row.visibility = row.effective_visibility = payload.visibility
        row.revision += 1
        identity, revision, status = row.id, row.revision, row.status
        kind, visibility = "proposal", row.effective_visibility
        result = {
            "proposal_id": str(row.id),
            "visibility": row.visibility,
            "audience_ids": sorted(str(person) for person in wanted),
            "shared_claim_ids": [str(claim.id) for claim in validated.claims],
        }
    s.flush()
    revised = (
        validated.proposal
        if isinstance(payload, EvidenceLinkCreate)
        else (validated.subject if isinstance(payload, ProposalShare) else None)
    )
    if revised:
        from .models import ProposalRevision
        from .views import document

        s.add(
            ProposalRevision(
                tenant_id=ctx.tenant_id,
                category_id=ctx.category_id,
                proposal_id=revised.id,
                revision=revised.revision,
                changed_items=[],
                actor_id=ctx.actor_id,
                run_id=ctx.agent_run_id,
                receipt_id=receipt_id,
                document_digest=digest(document(s, revised)),
            )
        )
    subject = SimpleNamespace(
        id=identity,
        revision=revision,
        category_id=ctx.category_id,
        status=status,
        prepared_receipt_id=receipt_id,
        prepared_by_run_id=validated.provenance.get("run_id"),
        action_result=result,
    )
    return subject, kind, visibility


def apply(s, ctx, command, scope, payload):
    return apply_validated(
        s, ctx, command, scope, payload, validate(s, ctx, command, scope, payload)
    )
