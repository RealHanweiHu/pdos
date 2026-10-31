"""Category material handlers; caller owns common confirmation, receipt and transaction."""

from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import or_, select

from pdos_next.clock import now
from pdos_next.models import Artifact, Category, Principal, Product, UploadedOriginal
from pdos_next.service import source_for

from .access import fail, human, proposal
from .category_models import (
    KnowledgeCurrent,
    KnowledgeEntry,
    ParameterCurrent,
    ParameterVersion,
    PromotionProof,
)
from .category_schemas import KnowledgeAdd, KnowledgePromote, KnowledgeWithdraw, ParameterPublish
from .deidentification import check_content, strings
from .models import Proposal, ProposalItem, ProposalItemVersion, ProposalSource
from .schemas import Reference


def requires_category_write(command):
    return True


def supports_confirmation(command):
    return command.operation == "category.knowledge.add"


def needs_confirmation(payload):
    return isinstance(payload, KnowledgeAdd) and bool(payload.prepared_by_run_id)


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"confirmation_token"})


@dataclass
class ValidatedMaterial:
    provenance: dict
    current: object | None = None
    checks: dict | None = None
    source_proposal: object | None = None
    knowledge_review: dict | None = None


def _current(s, ctx, model, identity, expected):
    column = model.lineage_id if model is KnowledgeCurrent else model.parameter_id
    row = s.scalar(
        select(model)
        .where(
            model.tenant_id == ctx.tenant_id,
            model.category_id == ctx.category_id,
            column == identity,
        )
        .with_for_update()
    )
    if row is None:
        fail("NOT_FOUND", "material_not_found", "资料不存在或不可读。", 404)
    if row.current_version != expected:
        fail("VERSION_CONFLICT", "material_version_moved", "资料版本已变化，请重新读取。")
    return row


def parameter_version(s, ctx, identity, version):
    row = s.scalar(
        select(ParameterVersion).where(
            ParameterVersion.tenant_id == ctx.tenant_id,
            ParameterVersion.category_id == ctx.category_id,
            ParameterVersion.parameter_id == identity,
            ParameterVersion.version == version,
        )
    )
    if not row:
        fail("SOURCE_UNAVAILABLE", "parameter_unreadable", "参数版本不在当前品类内。")
    return row


def check_parameter(s, ctx, identity, version, unit, value_type=None):
    row = parameter_version(s, ctx, identity, version)
    if row.unit != unit:
        fail("VALIDATION_FAILED", "parameter_unit_mismatch", "单位与所引参数版本不一致。")
    if value_type is not None and row.value_type != value_type:
        fail("VALIDATION_FAILED", "parameter_type_mismatch", "值类型与参数版本不一致。")
    return row


def _references(payload):
    refs = list(getattr(payload, "source_refs", ()))
    content = getattr(payload, "content", {})
    if payload.kind == "voice":
        refs.extend(Reference.model_validate(r) for r in content["representative_refs"])
    if payload.kind == "competitor":
        for group in ("metrics", "features", "prices"):
            refs.extend(
                Reference.model_validate(i["source_ref"])
                for i in content[group]
                if i.get("source_ref") is not None
            )
    return refs


def check_shared_sources(s, ctx, refs):
    from pdos_next.agent_kernel.models import PublicWebSnapshot

    for ref in refs:
        if ref.type == "claim":
            from .claim_access import resolve, source_privacy

            row = resolve(s, ctx, ref.id, ref.version, approved=True, lock=True)
            if row.privacy == "private" or source_privacy(s, ctx, row) != "shared":
                fail("VALIDATION_FAILED", "private_source_in_shared", "私有事实不能进入共享知识。")
            if (ref.quote is not None and ref.quote not in row.quote) or (
                ref.line is not None and ref.line != row.line
            ):
                fail("VALIDATION_FAILED", "quote_not_in_source", "引用不在事实的固定来源定位处。")
            continue
        if ref.type == "human":
            person = s.get(Principal, ref.id)
            if (
                not person
                or person.tenant_id != ctx.tenant_id
                or not person.active
                or (person.kind != "human" or not ref.statement)
            ):
                fail("VALIDATION_FAILED", "human_source_invalid", "具名陈述须有可读人员及内容。")
            continue
        if ref.type == "snapshot":
            row = s.scalar(
                select(PublicWebSnapshot)
                .where(
                    PublicWebSnapshot.tenant_id == ctx.tenant_id,
                    PublicWebSnapshot.category_id == ctx.category_id,
                    PublicWebSnapshot.id == ref.id,
                )
                .with_for_update(read=True)
            )
            if not row or row.visibility != "category":
                fail(
                    "VALIDATION_FAILED",
                    "private_source_in_shared",
                    "共享知识只能引用品类可见来源。",
                )
            if ref.version != 1 or row.status not in {"ok", "partial"}:
                fail("SOURCE_STALE", "snapshot_unavailable", "快照版本不可用。")
            body, reason = row.markdown, "quote_not_in_snapshot"
        elif ref.type in {"artifact", "original"}:
            # Preserve existing scan/withdrawal/parent audience proof.
            candidate = s.get(Artifact, ref.id)
            if (
                not candidate
                or candidate.tenant_id != ctx.tenant_id
                or candidate.category_id != ctx.category_id
            ):
                fail("SOURCE_UNAVAILABLE", "source_unreadable", "来源不在当前品类内。")
            row = source_for(s, ctx, candidate.product_id, ref.id, ref.version)
            parent = s.get(Product, row.product_id) if row.product_id else None
            original = s.get(UploadedOriginal, row.original_id) if row.original_id else None
            if (
                row.visibility != "category"
                or (row.product_id and (not parent or parent.visibility != "category"))
                or (row.original_id and (not original or original.visibility != "category"))
            ):
                fail("VALIDATION_FAILED", "private_source_in_shared", "私有原件不能进入共享知识。")
            body, reason = row.content, "quote_not_in_source"
        else:
            fail("VALIDATION_FAILED", "private_source_in_shared", "此来源类型不能进入共享知识。")
        lines = body.splitlines()
        if (
            not ref.line
            or not ref.quote
            or ref.line > len(lines)
            or ref.quote not in lines[ref.line - 1]
        ):
            fail("VALIDATION_FAILED", reason, "引用须为指定行的逐字片段。")


def _private_checks(s, ctx, row, content):
    from uuid import UUID

    from pdos_next.agent_kernel.models import AgentRun
    from pdos_next.models import Claim

    from .evidence_models import EvidenceLink
    from .models import ProposalRevision, ProposalSubmission

    # Source counters describe the current draft, not everything it has read.
    # Retained references remain identity evidence after an item is edited away.
    artifact_ids, claim_ids, private_refs = set(), set(), {str(row.id)}

    def collect(value):
        if isinstance(value, dict):
            kind = value.get("type")
            if kind in {"artifact", "original", "claim", "snapshot", "knowledge", "definition"}:
                try:
                    identity = UUID(str(value["id"]))
                except (KeyError, ValueError, TypeError):
                    pass
                else:
                    private_refs.add(str(identity))
                    if kind in {"artifact", "original"}:
                        artifact_ids.add(identity)
                    elif kind == "claim":
                        claim_ids.add(identity)
            for child in value.values():
                collect(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                collect(child)

    collect([row.source_refs, row.context_refs])
    for ref in s.scalars(
        select(ProposalSource).where(
            ProposalSource.tenant_id == ctx.tenant_id,
            ProposalSource.category_id == ctx.category_id,
            ProposalSource.proposal_id == row.id,
        )
    ):
        collect({"type": ref.source_type, "id": str(ref.source_id)})
    for model, fields in (
        (ProposalItemVersion, ("source_refs",)),
        (ProposalRevision, ("changed_items",)),
        (ProposalSubmission, ("frozen_document", "context_refs")),
    ):
        for history in s.scalars(
            select(model).where(
                model.tenant_id == ctx.tenant_id,
                model.category_id == ctx.category_id,
                model.proposal_id == row.id,
            )
        ):
            collect([getattr(history, field) for field in fields])
    item_ids = select(ProposalItem.id).where(
        ProposalItem.tenant_id == ctx.tenant_id,
        ProposalItem.category_id == ctx.category_id,
        ProposalItem.proposal_id == row.id,
    )
    for link in s.scalars(
        select(EvidenceLink).where(
            EvidenceLink.tenant_id == ctx.tenant_id,
            EvidenceLink.category_id == ctx.category_id,
            EvidenceLink.target_type == "proposal_item",
            EvidenceLink.target_id.in_(item_ids),
        )
    ):
        collect({"type": link.evidence_type, "id": str(link.evidence_id)})

    private_runs = set()
    for claim in s.scalars(
        select(Claim).where(
            Claim.tenant_id == ctx.tenant_id,
            Claim.category_id == ctx.category_id,
            or_(Claim.proposal_id == row.id, Claim.id.in_(claim_ids)),
        )
    ):
        if claim.artifact_id:
            artifact_ids.add(claim.artifact_id)
        if claim.proposal_id == row.id and claim.privacy == "private" and claim.run_id:
            private_runs.add(claim.run_id)
    if private_runs:
        for run in s.scalars(
            select(AgentRun).where(
                AgentRun.tenant_id == ctx.tenant_id,
                AgentRun.category_id == ctx.category_id,
                AgentRun.proposal_id == row.id,
                AgentRun.private_context.is_(True),
                AgentRun.id.in_(private_runs),
            )
        ):
            for reference in run.read_sources:
                if isinstance(reference, dict) and reference.get("artifact_id"):
                    collect({"type": "artifact", "id": reference["artifact_id"]})

    # Ordinary RLS reads are intentional: historical IDs do not confer new access.
    artifacts = (
        list(
            s.scalars(
                select(Artifact)
                .where(
                    Artifact.tenant_id == ctx.tenant_id,
                    Artifact.category_id == ctx.category_id,
                    Artifact.id.in_(artifact_ids),
                )
                .order_by(Artifact.id)
            )
        )
        if artifact_ids
        else []
    )
    original_ids = {artifact.original_id for artifact in artifacts if artifact.original_id}
    filenames = (
        list(
            s.scalars(
                select(UploadedOriginal.filename)
                .where(
                    UploadedOriginal.tenant_id == ctx.tenant_id,
                    UploadedOriginal.category_id == ctx.category_id,
                    UploadedOriginal.id.in_(original_ids),
                )
                .order_by(UploadedOriginal.id)
            )
        )
        if original_ids
        else []
    )
    return check_content(
        content,
        identities=list(strings(row.customer_identities, include_keys=False)),
        filenames=filenames,
        private_refs=sorted(private_refs),
        originals=[artifact.content for artifact in artifacts if artifact.original_id],
    )


def validate(s, ctx, command, scope, payload):
    from pdos_next.agent_kernel.models import AgentRun
    from pdos_next.category_scope import category_scope

    from .provenance import writing_path

    if command.product_id is not None:
        fail("FORBIDDEN_SCOPE", "category_material_scope", "资料命令须使用品类范围。", 403)
    category_scope(s, ctx, write=requires_category_write(command), lock=True)
    if not isinstance(payload, KnowledgeAdd):
        human(s, ctx)
    path = writing_path(s, ctx, command, payload)
    from .material_candidate_edits import effective

    if getattr(payload, "human_edits", None) is not None and isinstance(payload, KnowledgeAdd):
        check_shared_sources(s, ctx, _references(payload))
    payload = effective(payload)
    result = ValidatedMaterial(path)
    run = s.get(AgentRun, path["run_id"]) if path["run_id"] else None
    if run and (run.tenant_id != ctx.tenant_id or run.category_id != ctx.category_id):
        fail("FORBIDDEN_SCOPE", "candidate_binding_invalid", "运行范围不一致。", 403)
    if isinstance(payload, KnowledgeAdd):
        if run and run.private_context:
            fail("FORBIDDEN_SCOPE", "private_context_run", "私有上下文内容须经去标识沉淀。", 403)
        check_shared_sources(s, ctx, _references(payload))
        if payload.kind == "competitor":
            from .competitor_segments import validate_refs

            validate_refs(s, ctx, payload.content.get("segment_refs", []))
            for item in [*payload.content["metrics"], *payload.content["features"]]:
                check_parameter(
                    s, ctx, item["parameter_id"], item["parameter_version"], item["unit"]
                )
        if payload.supersedes:
            old = result.current = _current(
                s,
                ctx,
                KnowledgeCurrent,
                payload.supersedes.lineage_id,
                payload.supersedes.expected_version,
            )
            if old.kind != payload.kind:
                fail("VALIDATION_FAILED", "knowledge_kind_immutable", "谱系种类不能改变。")
            if ctx.agent_run_id:
                entry = s.get(KnowledgeEntry, old.current_entry_id)
                if old.origin != "ai_draft" or entry.confirmed_by:
                    fail("CONFIRMATION_REQUIRED", "human_value_protected", "人工值须经一次确认。")
    elif isinstance(payload, KnowledgeWithdraw):
        result.current = _current(
            s, ctx, KnowledgeCurrent, payload.lineage_id, payload.expected_version
        )
    elif isinstance(payload, ParameterPublish):
        # Lock the category also for new keys: absent Current rows cannot be row-locked.
        s.scalar(
            select(Category)
            .where(Category.id == ctx.category_id, Category.tenant_id == ctx.tenant_id)
            .with_for_update()
        )
        if payload.parameter_id:
            result.current = _current(
                s, ctx, ParameterCurrent, payload.parameter_id, payload.expected_current_version
            )
            if result.current.key != payload.key:
                fail("VALIDATION_FAILED", "parameter_key_immutable", "参数稳定键不能改变。")
        elif s.scalar(
            select(ParameterCurrent).where(
                ParameterCurrent.tenant_id == ctx.tenant_id,
                ParameterCurrent.category_id == ctx.category_id,
                ParameterCurrent.key == payload.key,
            )
        ):
            fail("VALIDATION_FAILED", "key_taken", "参数键已存在。")
        if run and run.private_context:
            if not run.proposal_id:
                fail(
                    "FORBIDDEN_SCOPE",
                    "private_context_run",
                    "私有上下文缺少可核对的来源提案。",
                    403,
                )
            result.source_proposal = proposal(s, ctx, run.proposal_id, lock=True)
            result.checks = _private_checks(
                s,
                ctx,
                result.source_proposal,
                {
                    key: getattr(payload, key)
                    for key in (
                        "key",
                        "name",
                        "enum_values",
                        "unit",
                        "standard_condition",
                        "method",
                        "acceptance_criterion",
                        "change_note",
                    )
                },
            )
    elif isinstance(payload, KnowledgePromote):
        if payload.supersedes:
            old = result.current = _current(
                s,
                ctx,
                KnowledgeCurrent,
                payload.supersedes.lineage_id,
                payload.supersedes.expected_version,
            )
            if old.kind != payload.kind:
                fail("VALIDATION_FAILED", "knowledge_kind_immutable", "谱系种类不能改变。")
        if payload.kind == "competitor":
            from .competitor_segments import validate_refs

            validate_refs(s, ctx, payload.content.get("segment_refs", []))
            for item in [*payload.content["metrics"], *payload.content["features"]]:
                check_parameter(
                    s, ctx, item["parameter_id"], item["parameter_version"], item["unit"]
                )
        row = result.source_proposal = proposal(s, ctx, payload.source_proposal_id, lock=True)
        if run and run.proposal_id and run.proposal_id != row.id:
            fail("FORBIDDEN_SCOPE", "proposal_run_mismatch", "去标识候选不属于源提案。", 403)
        if row.revision != payload.source_proposal_revision:
            fail("VERSION_CONFLICT", "proposal_revision_moved", "源提案版本已变化。")
        for ref in payload.source_item_refs:
            item = s.get(ProposalItem, ref.item_id)
            if not item or item.tenant_id != ctx.tenant_id or item.proposal_id != row.id:
                fail("NOT_FOUND", "source_item_not_found", "源条目不属于提案。", 404)
            if item.current_version != ref.version or item.removed:
                fail("VERSION_CONFLICT", "source_item_moved", "源条目已变化。")
        result.checks = _private_checks(s, ctx, row, payload.content)
        item_checks = check_content(
            payload.content, private_refs=[str(ref.item_id) for ref in payload.source_item_refs]
        )
        result.checks["hits"].extend(item_checks["hits"])
        result.checks["refs_clean"] &= item_checks["refs_clean"]
    else:
        fail("VALIDATION_FAILED", "unsupported_material_operation", "不支持的资料操作。")
    if isinstance(payload, (KnowledgeAdd, KnowledgePromote)):
        from pdos_next.domain.knowledge.assistant_reviews import prepare
        from pdos_next.domain.knowledge.assistant_sources import review_for

        previous = (
            review_for(s, "category", result.current.current_entry_id) if result.current else None
        )
        result.knowledge_review = prepare(
            s,
            ctx,
            payload,
            shared=True,
            previous=previous,
            promoted=isinstance(payload, KnowledgePromote),
        )
    return result


def confirmation_subject(s, ctx, command, scope, payload):
    if isinstance(payload, KnowledgePromote):
        return "proposal", proposal(s, ctx, payload.source_proposal_id)
    if isinstance(payload, KnowledgeWithdraw) or (
        isinstance(payload, KnowledgeAdd) and payload.supersedes
    ):
        identity = (
            payload.lineage_id
            if isinstance(payload, KnowledgeWithdraw)
            else payload.supersedes.lineage_id
        )
        row = s.get(KnowledgeCurrent, (ctx.tenant_id, identity))
        if not row or row.category_id != ctx.category_id:
            fail("NOT_FOUND", "material_not_found", "资料不可读。", 404)
        return "category_knowledge", row
    if isinstance(payload, ParameterPublish) and payload.parameter_id:
        row = s.get(ParameterCurrent, (ctx.tenant_id, payload.parameter_id))
        if not row or row.category_id != ctx.category_id:
            fail("NOT_FOUND", "material_not_found", "资料不可读。", 404)
        return "parameter", row
    row = s.get(Category, ctx.category_id)
    return "category", row


def preview_view(s, ctx, command, scope, payload):
    validated = validate(s, ctx, command, scope, payload)
    from .material_candidate_edits import effective

    return {
        "operation": command.operation,
        "payload": semantic(effective(payload)),
        **(
            {"human_edits": payload.human_edits}
            if getattr(payload, "human_edits", None) is not None
            else {}
        ),
        "checks": validated.checks,
        "effect": "追加共享品类资料；保留既有版本。",
    }


def apply_validated(s, ctx, command, scope, payload, validated):
    from .material_candidate_edits import effective

    edits = getattr(payload, "human_edits", None)
    payload = effective(payload)
    if validated.checks and validated.checks["hits"]:
        fail(
            "VALIDATION_FAILED",
            "identity_not_removed",
            "请移除客户身份和私有来源标识。",
            hits=validated.checks["hits"],
        )
    if isinstance(payload, KnowledgePromote) and not payload.deidentified_confirmed:
        fail("CONFIRMATION_REQUIRED", "deidentification_not_confirmed", "请确认内容已去客户身份。")
    receipt_id = uuid4()
    provenance = {
        key: validated.provenance[key]
        for key in ("origin", "writer_id", "run_id", "confirmed_by", "prepared_candidate_id")
    }
    current = validated.current
    if isinstance(payload, ParameterPublish):
        identity = payload.parameter_id or uuid4()
        version = payload.expected_current_version + 1
        fields = payload.model_dump(
            exclude={
                "parameter_id",
                "expected_current_version",
                "prepared_by_run_id",
                "candidate_digest",
                "confirmation_token",
                "human_edits",
            }
        )
        row = ParameterVersion(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            category_id=ctx.category_id,
            parameter_id=identity,
            version=version,
            replaces_version=version - 1 if version > 1 else None,
            receipt_id=receipt_id,
            **fields,
            **provenance,
        )
        s.add(row)
        s.flush([row])
        if current:
            current.current_version = version
        else:
            s.add(
                ParameterCurrent(
                    tenant_id=ctx.tenant_id,
                    category_id=ctx.category_id,
                    parameter_id=identity,
                    key=payload.key,
                    current_version=version,
                )
            )
        kind, status = "parameter", "active"
        result = {"parameter_id": str(identity), "version": version}
    else:
        identity = current.lineage_id if current else uuid4()
        version = current.current_version + 1 if current else 1
        withdrawal = isinstance(payload, KnowledgeWithdraw)
        old = s.get(KnowledgeEntry, current.current_entry_id) if current else None
        content = old.content if withdrawal else dict(payload.content)
        if not withdrawal and payload.kind == "voice":
            content["sample_size"] = len(
                {(str(r.id), r.version, r.line) for r in _references(payload)}
            )
        row = KnowledgeEntry(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            category_id=ctx.category_id,
            lineage_id=identity,
            version=version,
            action="withdraw" if withdrawal else "supersede" if current else "add",
            kind=old.kind if withdrawal else payload.kind,
            content=content,
            answer_sources=old.answer_sources
            if withdrawal
            else validated.knowledge_review["source_proof"]
            if validated.knowledge_review
            else None,
            regions=old.regions if withdrawal else getattr(payload, "regions", []),
            source_refs=old.source_refs
            if withdrawal
            else [r.model_dump(mode="json") for r in _references(payload)]
            if isinstance(payload, KnowledgeAdd)
            else [],
            withdraw_reason=payload.reason if withdrawal else None,
            receipt_id=receipt_id,
            **provenance,
        )
        s.add(row)
        s.flush([row])
        status = "withdrawn" if withdrawal else "active"
        if current:
            current.current_entry_id, current.current_version = row.id, version
            current.status, current.origin = status, provenance["origin"]
        else:
            s.add(
                KnowledgeCurrent(
                    tenant_id=ctx.tenant_id,
                    category_id=ctx.category_id,
                    lineage_id=identity,
                    kind=row.kind,
                    current_entry_id=row.id,
                    current_version=version,
                    status=status,
                    origin=provenance["origin"],
                )
            )
        if isinstance(payload, KnowledgePromote):
            proof_id = uuid4()
            s.add(
                PromotionProof(
                    id=proof_id,
                    tenant_id=ctx.tenant_id,
                    category_id=ctx.category_id,
                    knowledge_entry_id=row.id,
                    source_proposal_id=payload.source_proposal_id,
                    source_proposal_revision=payload.source_proposal_revision,
                    source_item_refs=[r.model_dump(mode="json") for r in payload.source_item_refs],
                    deidentified_by=ctx.requester_id,
                    deidentified_at=now(),
                    checks=validated.checks,
                    receipt_id=receipt_id,
                )
            )
        kind = "category_knowledge"
        result = {"lineage_id": str(identity), "version": version, "entry_id": str(row.id)}
        if isinstance(payload, KnowledgePromote):
            result["promotion_proof_id"] = str(proof_id)
    if not isinstance(payload, ParameterPublish) and validated.knowledge_review:
        from pdos_next.domain.knowledge.assistant_reviews import append

        append(
            s,
            ctx,
            command,
            "category",
            row.id,
            receipt_id,
            validated.knowledge_review,
            verified=True,
        )
    if current:
        _context_hints(s, ctx, kind, identity, version)
    if edits is not None:
        result["human_edits"] = edits
        result["edited_by"] = str(ctx.requester_id)
        result["prepared_candidate_id"] = str(provenance["prepared_candidate_id"])
    s.flush()
    subject = SimpleNamespace(
        id=identity,
        revision=version,
        category_id=ctx.category_id,
        status=status,
        prepared_receipt_id=receipt_id,
        prepared_by_run_id=provenance["run_id"],
        action_result=result,
    )
    return subject, kind, "category"


def apply(s, ctx, command, scope, payload):
    return apply_validated(
        s, ctx, command, scope, payload, validate(s, ctx, command, scope, payload)
    )


def _context_hints(s, ctx, kind, identity, new_version):
    """Hint only drafts actually referencing the changed lineage/parameter."""
    if kind == "parameter":
        versions = s.scalars(
            select(ParameterVersion.id).where(
                ParameterVersion.tenant_id == ctx.tenant_id,
                ParameterVersion.category_id == ctx.category_id,
                ParameterVersion.parameter_id == identity,
                ParameterVersion.version < new_version,
            )
        ).all()
        reference_type, referenced_ids = "parameter", [identity, *versions]
        item_match = ProposalItemVersion.content.contains({"parameter_id": str(identity)})
    else:
        versions = s.scalars(
            select(KnowledgeEntry.id).where(
                KnowledgeEntry.tenant_id == ctx.tenant_id,
                KnowledgeEntry.category_id == ctx.category_id,
                KnowledgeEntry.lineage_id == identity,
                KnowledgeEntry.version < new_version,
            )
        ).all()
        reference_type, referenced_ids = "knowledge", list(versions)
        item_match = or_(
            *(
                ProposalItemVersion.source_refs.contains(
                    [{"type": reference_type, "id": str(value)}]
                )
                for value in referenced_ids
            )
        )
    if not referenced_ids:
        return
    context_match = or_(
        *(
            Proposal.context_refs.contains([{"type": reference_type, "id": str(value)}])
            for value in referenced_ids
        )
    )
    items_match = (
        select(ProposalItemVersion.id)
        .join(
            ProposalItem,
            (
                (ProposalItem.tenant_id == ProposalItemVersion.tenant_id)
                & (ProposalItem.id == ProposalItemVersion.item_id)
                & (ProposalItem.current_version == ProposalItemVersion.version)
            ),
        )
        .where(
            ProposalItemVersion.tenant_id == ctx.tenant_id,
            ProposalItemVersion.category_id == ctx.category_id,
            ProposalItemVersion.proposal_id == Proposal.id,
            ProposalItem.removed.is_(False),
            item_match,
        )
        .exists()
    )
    source_match = (
        select(ProposalSource.id)
        .where(
            ProposalSource.tenant_id == ctx.tenant_id,
            ProposalSource.category_id == ctx.category_id,
            ProposalSource.proposal_id == Proposal.id,
            ProposalSource.source_type == reference_type,
            ProposalSource.source_id.in_(referenced_ids),
        )
        .exists()
    )
    rows = s.scalars(
        select(Proposal)
        .where(
            Proposal.tenant_id == ctx.tenant_id,
            Proposal.category_id == ctx.category_id,
            Proposal.status.in_(["draft", "returned"]),
            Proposal.context_hint.is_(False),
            or_(context_match, items_match, source_match),
        )
        .order_by(Proposal.id)
        .with_for_update()
    ).all()
    for row in rows:
        row.context_hint = True
