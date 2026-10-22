from collections import Counter
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import func, select, text

from pdos_next.models import Artifact, Outbox, Principal
from pdos_next.service import digest, source_for

from .access import editable, fail, human, installed, member, proposal
from .models import (
    Proposal,
    ProposalDecision,
    ProposalItem,
    ProposalItemVersion,
    ProposalRevision,
    ProposalSource,
    ProposalSubmission,
)
from .schemas import G0Decide, G0Submit, ItemPatch, ProposalCreate, QuestionCreate
from .views import document, items, maturity, required_dispositions


@dataclass(frozen=True)
class ValidatedWrite:
    provenance: dict
    reference_privacy: dict
    baseline: dict | None = None
    initial_items: tuple = ()


def _lock_baseline(s, ctx, baseline):
    if (
        baseline
        and not s.execute(
            text("SELECT * FROM m3_lock_published_baseline(:t,:c,:p,:d,:v)"),
            {
                "t": ctx.tenant_id,
                "c": ctx.category_id,
                "p": baseline["product_id"],
                "d": baseline["id"],
                "v": baseline["revision"],
            },
        ).first()
    ):
        fail("SOURCE_UNAVAILABLE", "baseline_unreadable", "固定父版已不可读或发布事实不完整。")


def requires_category_write(command):
    return command.operation != "proposal.g0.decide"


def supports_confirmation(command):
    return command.operation == "proposal.item.patch"


def needs_confirmation(payload):
    return isinstance(payload, ItemPatch) and bool(payload.prepared_by_run_id)


def semantic(payload):
    data = payload.model_dump(mode="json")
    data.pop("confirmation_token", None)
    data.pop("approval_token", None)
    return data


def _references(s, ctx, refs, *, approved=False):
    from pdos_next.domain.products.models import DefinitionRevision

    from .root_sources import lock_claim_refs

    claims = lock_claim_refs(s, ctx, refs, approved=True)
    result = []
    for ref in refs:
        if ref.type == "claim":
            from .claim_access import source_privacy

            claim = claims[ref.id]
            if (ref.quote is not None and ref.quote not in claim.quote) or (
                ref.line is not None and ref.line != claim.line
            ):
                fail("VALIDATION_FAILED", "quote_not_in_source", "引用不在事实的固定来源定位处。")
            privacy = source_privacy(s, ctx, claim)
        elif ref.type == "human":
            person = s.get(Principal, ref.id)
            if not person or not person.active or person.kind != "human" or not ref.statement:
                fail(
                    "VALIDATION_FAILED", "human_source_invalid", "具名来源需有当前可读人员与陈述。"
                )
            privacy = "shared"
        elif ref.type in {"artifact", "original"}:
            source = s.get(Artifact, ref.id)
            if approved and (not source or source.status != "active"):
                fail(
                    "SOURCE_STALE",
                    "original_withdrawn",
                    "提交引用的原件已撤回，请退回处理后重新提交。",
                )
            if (
                not source
                or source.tenant_id != ctx.tenant_id
                or source.category_id != ctx.category_id
            ):
                fail("SOURCE_UNAVAILABLE", "source_unreadable", "来源不在当前可读范围。", 403)
            source = source_for(s, ctx, source.product_id, ref.id, ref.version)
            lines = source.content.splitlines()
            if (
                not ref.line
                or not ref.quote
                or ref.line > len(lines)
                or ref.quote not in lines[ref.line - 1]
            ):
                fail("VALIDATION_FAILED", "quote_not_in_source", "引用片段不在原件指定行内。")
            from .claim_access import source_privacy

            privacy = source_privacy(
                s, ctx, SimpleNamespace(source_kind="artifact", artifact_id=source.id)
            )
        elif ref.type == "definition":
            source = s.get(DefinitionRevision, ref.id)
            if (
                not source
                or source.category_id != ctx.category_id
                or source.revision != ref.version
            ):
                fail("SOURCE_UNAVAILABLE", "baseline_unreadable", "固定父版定义不可读。")
            private = s.scalar(
                text("SELECT m3_definition_root_private(:tenant,:category,:definition,:version)"),
                {
                    "tenant": ctx.tenant_id,
                    "category": ctx.category_id,
                    "definition": source.id,
                    "version": source.revision,
                },
            )
            if private is None:
                fail("SOURCE_UNAVAILABLE", "baseline_unreadable", "固定父版来源不可读。")
            privacy = "private" if private else "shared"
        elif ref.type == "knowledge":
            from .category_models import KnowledgeCurrent, KnowledgeEntry

            source = s.get(KnowledgeEntry, ref.id)
            current = (
                s.get(KnowledgeCurrent, (ctx.tenant_id, source.lineage_id)) if source else None
            )
            if (
                not source
                or source.category_id != ctx.category_id
                or source.version != ref.version
                or source.action == "withdraw"
                or not current
                or (not approved and current.status != "active")
            ):
                fail("SOURCE_UNAVAILABLE", "knowledge_unreadable", "所选知识固定版本不可读。")
            privacy = "shared"
        elif ref.type == "parameter":
            from .category_service import parameter_version

            parameter_version(s, ctx, ref.id, ref.version)
            privacy = "shared"
        elif ref.type == "snapshot":
            from pdos_next.agent_kernel.models import PublicWebSnapshot

            source = s.get(PublicWebSnapshot, ref.id)
            if not source or source.category_id != ctx.category_id or ref.version != 1:
                fail("SOURCE_UNAVAILABLE", "snapshot_unreadable", "快照版本不在当前可读范围内。")
            if source.status not in {"ok", "partial"}:
                fail("SOURCE_STALE", "snapshot_unavailable", "快照不可用。")
            if ref.line is not None or ref.quote is not None:
                lines = source.markdown.splitlines()
                if (
                    not ref.line
                    or not ref.quote
                    or ref.line > len(lines)
                    or ref.quote not in lines[ref.line - 1]
                ):
                    fail(
                        "VALIDATION_FAILED",
                        "quote_not_in_snapshot",
                        "引用须为快照指定行的逐字片段。",
                    )
            privacy = "shared" if source.visibility == "category" else "private"
        else:
            fail(
                "SOURCE_UNAVAILABLE",
                "category_material_pending",
                "知识和字典引用将在 M3 品类资料切片接入；此候选不能把未核对的引用当作事实。",
                503,
            )
        result.append((ref, privacy))
    return result


def _all_refs(payload):
    if isinstance(payload, ProposalCreate):
        return [
            *payload.source_refs,
            *payload.context_refs,
            *(ref for item in payload.groups.items for ref in item.source_refs),
        ]
    if isinstance(payload, ItemPatch):
        return [*payload.source_refs, *(ref for item in payload.ops for ref in item.source_refs)]
    return []


def _check_items(s, ctx, candidate_items, *, question_owners=None):
    for item in candidate_items:
        if item.kind == "spec" and item.content.get("parameter_id"):
            from .category_service import check_parameter

            parameter = check_parameter(
                s,
                ctx,
                UUID(item.content["parameter_id"]),
                item.content["parameter_version"],
                item.content.get("unit"),
                item.content["value_type"],
            )
            if item.content["key"] != parameter.key:
                fail("VALIDATION_FAILED", "parameter_key_mismatch", "规格键须与参数版本一致。")
        if item.kind == "question":
            member(s, ctx, UUID(item.content["owner_id"]))
            if UUID(item.content["owner_id"]) not in (question_owners or {ctx.requester_id}):
                fail(
                    "VALIDATION_FAILED",
                    "assignee_not_audience",
                    "私有草稿的问题先由提案负责人承接。",
                )


def _submission(s, ctx, row, payload):
    sub = s.get(ProposalSubmission, payload.submission_id)
    if (
        not sub
        or row.status != "in_review"
        or row.current_submission_id != sub.id
        or sub.proposal_id != row.id
    ):
        fail("VERSION_CONFLICT", "submission_superseded", "提交副本已变化，请重新读取本次评审。")
    return sub


def validate(s, ctx, command, scope, payload):
    installed(s)
    from .provenance import writing_path

    if isinstance(payload, (G0Submit, G0Decide)):
        human(s, ctx)
    path = writing_path(s, ctx, command, payload)
    reference_privacy = {}
    baseline = None

    def check_references(refs, *, approved=False):
        reference_privacy.update(
            (digest(ref.model_dump(mode="json")), privacy)
            for ref, privacy in _references(s, ctx, refs, approved=approved)
        )
        from pdos_next.models import Claim

        for ref in refs:
            if ref.type == "claim":
                claim = s.get(Claim, ref.id)
                if claim.privacy == "private" and claim.proposal_id != getattr(
                    payload, "proposal_id", None
                ):
                    fail(
                        "FORBIDDEN_SCOPE",
                        "claim_proposal_mismatch",
                        "私有事实只能用于所在提案。",
                        403,
                    )

    if command.product_id is not None:
        fail("FORBIDDEN_SCOPE", "proposal_category_scope", "立项前命令须使用品类范围。", 403)
    if isinstance(payload, ProposalCreate):
        if command.expected_revision != scope.revision:
            fail("VERSION_CONFLICT", "category_revision_moved", "品类范围版本已变化。")
        from .derivation import prepare_create
        from .schemas import Reference

        baseline, candidate_items = prepare_create(s, ctx, payload)
        _lock_baseline(s, ctx, baseline)
        if path["origin"] == "ai_draft" and any(
            item.kind == "spec" and item.content["item_status"] == "confirmed"
            for item in candidate_items
        ):
            fail("VALIDATION_FAILED", "ai_cannot_confirm", "AI 起草的初始规格不能冒充已确认值。")
        _check_items(s, ctx, candidate_items)
        ids = [item.item_id for item in candidate_items if item.item_id]
        if len(ids) != len(set(ids)):
            fail("VALIDATION_FAILED", "duplicate_item_id", "条目编号不能重复。")
        for question in payload.groups.questions:
            if question.owner_id != ctx.requester_id:
                fail("VALIDATION_FAILED", "assignee_not_audience", "私有草稿的问题先由负责人承接。")
        refs = [*_all_refs(payload), *(ref for item in candidate_items for ref in item.source_refs)]
        if baseline:
            refs.append(
                Reference(type="definition", id=baseline["id"], version=baseline["revision"])
            )
            refs.extend(
                Reference.model_validate(ref) for ref in baseline.get("baseline_claim_refs", [])
            )
        check_references(refs)
        return ValidatedWrite(path, reference_privacy, baseline, tuple(candidate_items))
    row = (
        proposal(s, ctx, payload.proposal_id, lock=True)
        if isinstance(payload, G0Decide)
        else editable(s, ctx, payload.proposal_id)
    )
    if not isinstance(payload, ItemPatch) and (
        payload.expected_revision != row.revision or command.expected_revision != row.revision
    ):
        fail("VERSION_CONFLICT", "proposal_revision_moved", "提案版本已变化。")
    if isinstance(payload, ItemPatch):
        ids = [op.item_id for op in payload.ops if op.item_id]
        if len(ids) != len(set(ids)):
            fail("VALIDATION_FAILED", "duplicate_item_id", "一个命令内不能重复修改同一条目。")
        current = {UUID(item["item_id"]): item for item in items(s, row, include_links=False)}
        for op in payload.ops:
            item = current.get(op.item_id)
            if ctx.agent_run_id and item and item["human_value"]:
                fail(
                    "CONFIRMATION_REQUIRED",
                    "human_value_protected",
                    "人工值受保护，请转为一次确认候选。",
                )
            if (
                ctx.agent_run_id
                and op.kind == "spec"
                and op.content.get("item_status") == "confirmed"
            ):
                fail("CONFIRMATION_REQUIRED", "human_value_protected", "规格确认须由人办理。")
            if op.kind == "question" and not item:
                fail(
                    "CONFIRMATION_REQUIRED",
                    "question_confirmation_required",
                    "新增问题需预览并确认一次。",
                )
            if (op.item_id and (not item or item["version"] != op.base_version)) or (
                not op.item_id and (op.base_version is not None or op.op == "remove")
            ):
                fail(
                    "VERSION_CONFLICT",
                    "base_version_moved",
                    "条目版本已变化；其他条目的修改不影响本条。",
                )
            if item and item["kind"] != op.kind:
                fail("VALIDATION_FAILED", "item_kind_immutable", "已有条目的种类不能改变。")
            if item and op.kind == "question":
                before = item["content"]
                if any(
                    op.content.get(key) != before.get(key)
                    for key in ("question", "owner_id", "due_date", "related_item_ids")
                ):
                    fail(
                        "VALIDATION_FAILED",
                        "question_assignment_requires_confirmation",
                        "问题改派请走新增问题的一次确认。",
                    )
        _check_items(
            s,
            ctx,
            payload.ops,
            question_owners=audience_members(
                s,
                row,
                {UUID(op.content["owner_id"]) for op in payload.ops if op.kind == "question"},
            ),
        )
        new_refs = []
        for op in payload.ops:
            before = current.get(op.item_id)
            old = {digest(ref) for ref in before["source_refs"]} if before else set()
            if op.op != "remove":
                new_refs += [
                    ref
                    for ref in [*op.source_refs, *payload.source_refs]
                    if digest(ref.model_dump(mode="json")) not in old
                ]
        check_references(new_refs)
    elif isinstance(payload, QuestionCreate):
        member(s, ctx, payload.owner_id)
        audience = audience_members(s, row, {payload.owner_id})
        if payload.owner_id not in audience:
            fail(
                "VALIDATION_FAILED", "assignee_not_audience", "G0 前的问题负责人须能读此私有提案。"
            )
        current = {UUID(item["item_id"]): item for item in items(s, row)}
        valid_ids = set(current)
        if set(payload.related_item_ids) - valid_ids:
            fail("VALIDATION_FAILED", "related_item_not_found", "关联条目须在本提案内。")
        if payload.supersedes_item_id and payload.supersedes_item_id not in valid_ids:
            fail("NOT_FOUND", "question_not_found", "被改派的问题不存在。", 404)
        if payload.supersedes_item_id and current[payload.supersedes_item_id]["kind"] != "question":
            fail("VALIDATION_FAILED", "not_a_question", "只能改派已有问题。")
        if payload.status != "open":
            fail("VALIDATION_FAILED", "new_question_open", "新增问题初始为待答。")
    elif isinstance(payload, G0Submit):
        if ctx.requester_id != row.owner_id:
            fail("NAMED_DECISION_REQUIRED", "owner_only", "提案由负责人本人提交评审。", 403)
        from pdos_next.agent_kernel.skill_qualification import is_pilot

        if payload.reviewer_id == row.owner_id and not is_pilot(s, ctx.tenant_id, lock=True):
            fail("VALIDATION_FAILED", "reviewer_is_owner", "非试点租户须由另一位产品经理评审。")
        member(s, ctx, payload.reviewer_id, reviewer=True)
        doc = document(s, row)
        from .derivation import validate_baseline

        baseline = validate_baseline(s, ctx, row, doc)
        _lock_baseline(s, ctx, baseline)
        _check_document_references(s, ctx, doc)
        checks = maturity(doc)["submission_checks"]
        if not checks["worth_it_present"]:
            fail("VALIDATION_FAILED", "narrative_missing", "请先写明为什么值得做。")
        if checks["alternative_or_reason_required"] and not payload.no_alternative_reason:
            fail(
                "VALIDATION_FAILED",
                "options_insufficient",
                "少于两个方案时请说明没有替代方案的理由。",
            )
    elif isinstance(payload, G0Decide):
        sub = _submission(s, ctx, row, payload)
        from pdos_next.agent_kernel.skill_qualification import is_pilot

        if ctx.requester_id != sub.reviewer_id or (
            ctx.requester_id == row.owner_id and not is_pilot(s, ctx.tenant_id, lock=True)
        ):
            fail(
                "NAMED_DECISION_REQUIRED", "reviewer_only", "只有本次具名评审人可作 G0 决定。", 403
            )
        member(s, ctx, ctx.requester_id, reviewer=True)
        if payload.outcome == "approved":
            from .derivation import validate_baseline

            baseline = validate_baseline(s, ctx, row, sub.frozen_document)
            _lock_baseline(s, ctx, baseline)
            prices = {
                digest(item["content"]["target_price"])
                for item in sub.frozen_document["items"]
                if item["kind"] == "commercial_target" and item["content"].get("target_price")
            }
            if len(prices) > 1:
                fail(
                    "VALIDATION_FAILED",
                    "target_price_conflicted",
                    "目标价口径冲突，请退回确定后重提。",
                )
            options = {
                UUID(item["item_id"])
                for item in sub.frozen_document["items"]
                if item["kind"] == "option"
            }
            if (options and payload.selected_option_item_id not in options) or (
                not options and payload.selected_option_item_id is not None
            ):
                fail("VALIDATION_FAILED", "option_not_selected", "请选择提交副本中的方案。")
            # P11 checks only approval, against the exact submitted copy; the
            # preview uses this same required_dispositions rule.
            needed = {
                (item["subject_type"], UUID(item["subject_id"]))
                for item in required_dispositions(sub.frozen_document)
            }
            given = [(item.subject_type, item.subject_id) for item in payload.dispositions]
            if set(given) != needed or len(given) != len(set(given)):
                fail(
                    "VALIDATION_FAILED",
                    "unknown_without_disposition",
                    "每项待决问题及未知、冲突或待专业确认的规格须逐条有负责人、期限和任务或风险处置。",
                )
            for item in payload.dispositions:
                member(s, ctx, item.owner_id)
            member(
                s,
                ctx,
                payload.project.owner_id
                if payload.project and payload.project.owner_id
                else row.owner_id,
            )
            _check_document_references(s, ctx, sub.frozen_document, approved=True)
    return ValidatedWrite(path, reference_privacy, baseline)


def confirmation_subject(s, ctx, command, scope, payload):
    if isinstance(payload, ProposalCreate):
        from pdos_next.models import Category

        # Common confirmation_subject expects a category row's category_id projection.
        row = s.get(Category, ctx.category_id)
        row.category_id = row.id
        return "category", row
    return "proposal", proposal(s, ctx, payload.proposal_id)


def audience_members(s, row, people):
    # Resolve only the proposed assignees. Hidden audience rows do not imply
    # absence, and readers do not need the complete category/member roster.
    return {
        person
        for person in people
        if s.scalar(
            select(
                func.m3_audience_member(
                    row.tenant_id,
                    row.category_id,
                    row.id,
                    person,
                )
            )
        )
    }


def _audience_changes(s, row, payload):
    owner = (
        payload.project.owner_id if payload.project and payload.project.owner_id else row.owner_id
    )
    original = audience_members(s, row, {owner, *(d.owner_id for d in payload.dispositions)})
    return (
        [
            {**d.model_dump(mode="json"), "audience_added": d.owner_id not in original}
            for d in payload.dispositions
        ],
        owner,
        owner not in original,
    )


def preview_view(s, ctx, command, scope, payload):
    if isinstance(payload, ProposalCreate):
        from .derivation import prepare_create

        baseline, initial_items = prepare_create(s, ctx, payload)
        result = {
            "operation": command.operation,
            "title": payload.title,
            "visibility": "private",
            "owner_id": str(ctx.requester_id),
            "groups": {
                **payload.groups.model_dump(mode="json"),
                "items": [item.model_dump(mode="json") for item in initial_items],
            },
            "effect": "保存私有立项提案；未建型号与项目。",
        }
        if baseline:
            result["baseline"] = {
                key: baseline[key]
                for key in ("id", "product_id", "revision", "title", "publication")
            }
        return result
    row = proposal(s, ctx, payload.proposal_id)
    result = {
        "operation": command.operation,
        "proposal_id": str(row.id),
        "revision": row.revision,
        "payload": semantic(payload),
    }
    if isinstance(payload, G0Submit):
        result["document_digest"] = digest(document(s, row))
    elif isinstance(payload, G0Decide):
        sub = _submission(s, ctx, row, payload)
        row.reviewer_for_decision = sub.reviewer_id
        dispositions, owner, added = _audience_changes(s, row, payload)
        result.update(
            document_digest=sub.document_digest,
            dispositions=dispositions,
            project_owner_id=str(owner),
            project_owner_audience_added=added,
            required_dispositions=required_dispositions(sub.frozen_document),
            target_kind=sub.frozen_document["target_kind"],
            identity_name=payload.new_identity.name if payload.new_identity else row.title,
            variant_kind=payload.new_identity.variant_kind
            if payload.new_identity
            else "configuration",
            effect=(
                "批准立项后将建立变体、封存定义 v1、项目和待办。"
                if sub.frozen_document["target_kind"] == "new_variant"
                else "批准立项后将建立型号、封存定义 v1、项目和待办。"
            )
            if payload.outcome == "approved"
            else "写入具名决定。",
        )
    return result


def _version(s, ctx, row, input_item, receipt_id, *, provenance, op="upsert", sort_key=0):
    pointer = s.get(ProposalItem, input_item.item_id) if input_item.item_id else None
    if pointer is None:
        pointer = ProposalItem(
            id=input_item.item_id or uuid4(),
            tenant_id=ctx.tenant_id,
            category_id=ctx.category_id,
            proposal_id=row.id,
            kind=input_item.kind,
            current_version=1,
            sort_key=sort_key,
        )
        s.add(pointer)
        s.flush([pointer])
    else:
        pointer.current_version += 1
    pointer.removed = op == "remove"
    version = ProposalItemVersion(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        proposal_id=row.id,
        item_id=pointer.id,
        version=pointer.current_version,
        kind=pointer.kind,
        content=input_item.content,
        source_refs=[ref.model_dump(mode="json") for ref in input_item.source_refs],
        **provenance,
        receipt_id=receipt_id,
        removed=pointer.removed,
    )
    s.add(version)
    return {"item_id": str(pointer.id), "version": version.version}


def _source_key(ref):
    if ref.type in {"human", "parameter"}:
        return None
    return ("original" if ref.type == "artifact" else ref.type, ref.id, ref.version)


def _source_counts(refs):
    # One link per source version; counts retain references from other unchanged items.
    return Counter(key for ref in refs if (key := _source_key(ref)) is not None)


def _sources(s, ctx, row, added, removed=(), *, reference_privacy):
    from .root_sources import roots

    added, reference_privacy = roots(s, ctx, added, reference_privacy)
    removed, _ = roots(s, ctx, removed, {})
    delta = _source_counts(added)
    delta.subtract(_source_counts(removed))
    for key, amount in delta.items():
        if not amount:
            continue
        typ, source_id, version = key
        link = s.scalar(
            select(ProposalSource).where(
                ProposalSource.proposal_id == row.id,
                ProposalSource.source_type == typ,
                ProposalSource.source_id == source_id,
                ProposalSource.source_version == version,
            )
        )
        if link:
            link.ref_count += amount
            if link.ref_count == 0:
                row.private_source_count -= int(link.privacy == "private")
                s.delete(link)
            elif link.ref_count < 0:
                fail("VALIDATION_FAILED", "source_count_inconsistent", "来源计数不一致。")
        else:
            if amount < 0:
                fail("VALIDATION_FAILED", "source_count_inconsistent", "来源计数不一致。")
            ref = next(ref for ref in added if _source_key(ref) == key)
            privacy = reference_privacy[digest(ref.model_dump(mode="json"))]
            s.add(
                ProposalSource(
                    tenant_id=ctx.tenant_id,
                    category_id=ctx.category_id,
                    proposal_id=row.id,
                    source_type=typ,
                    source_id=source_id,
                    source_version=version,
                    privacy=privacy,
                    ref_count=amount,
                )
            )
            row.private_source_count += int(privacy == "private")
    row.effective_visibility = "private" if row.private_source_count else row.visibility
    s.flush()


def apply_validated(s, ctx, command, scope, payload, validated):
    provenance = validated.provenance
    receipt_id = uuid4()
    changed = []
    if isinstance(payload, ProposalCreate):
        from .schemas import Reference

        baseline = validated.baseline
        source_refs = list(payload.source_refs)
        if baseline:
            source_refs.append(
                Reference(type="definition", id=baseline["id"], version=baseline["revision"])
            )
            source_refs.extend(
                Reference.model_validate(ref) for ref in baseline.get("baseline_claim_refs", [])
            )
        row = Proposal(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            category_id=ctx.category_id,
            owner_id=ctx.requester_id,
            title=payload.title,
            brief=payload.brief,
            entry_kind=payload.entry_kind,
            target_kind=payload.target_kind,
            baseline_product_id=payload.baseline_product_id,
            baseline_definition_id=UUID(baseline["id"]) if baseline else None,
            baseline_definition_revision=baseline["revision"] if baseline else None,
            customer_identities=payload.customer_identities,
            context_refs=[r.model_dump(mode="json") for r in payload.context_refs],
            source_refs=[r.model_dump(mode="json") for r in source_refs],
            created_by_run_id=provenance["run_id"],
        )
        s.add(row)
        s.flush([row])
        from .schemas import ItemInput

        initial = [
            *validated.initial_items,
            *(
                ItemInput(kind="question", content=q.model_dump(mode="json"))
                for q in payload.groups.questions
            ),
        ]
        for index, item in enumerate(initial):
            changed.append(
                _version(
                    s,
                    ctx,
                    row,
                    item,
                    receipt_id,
                    sort_key=index,
                    provenance=provenance,
                )
            )
        refs = [
            *source_refs,
            *payload.context_refs,
            *(ref for item in initial for ref in item.source_refs),
        ]
        _sources(s, ctx, row, refs, reference_privacy=validated.reference_privacy)
    else:
        row = proposal(s, ctx, payload.proposal_id, lock=True)
        if isinstance(payload, ItemPatch):
            sort_key = (
                s.scalar(
                    select(func.max(ProposalItem.sort_key)).where(
                        ProposalItem.proposal_id == row.id
                    )
                )
                or 0
            )
            before = {UUID(i["item_id"]): i for i in items(s, row, include_links=False)}
            added, removed = [], []
            from .schemas import Reference

            for index, op in enumerate(payload.ops):
                if old := before.get(op.item_id):
                    removed += [Reference.model_validate(ref) for ref in old["source_refs"]]
                    from .evidence_service import active_link_refs

                    removed += [
                        Reference.model_validate(ref)
                        for ref in active_link_refs(
                            s, ctx, "proposal_item", op.item_id, old["version"]
                        )
                    ]
                op.source_refs = [*op.source_refs, *payload.source_refs]
                if op.op != "remove":
                    added += op.source_refs
                changed.append(
                    _version(
                        s,
                        ctx,
                        row,
                        op,
                        receipt_id,
                        op=op.op,
                        sort_key=sort_key + index + 1,
                        provenance=provenance,
                    )
                )
            _sources(s, ctx, row, added, removed, reference_privacy=validated.reference_privacy)
        elif isinstance(payload, QuestionCreate):
            from .schemas import ItemInput

            content = payload.model_dump(
                mode="json",
                include={
                    "question",
                    "owner_id",
                    "due_date",
                    "related_item_ids",
                    "status",
                    "answer",
                    "supersedes_item_id",
                },
            )
            changed.append(
                _version(
                    s,
                    ctx,
                    row,
                    ItemInput(kind="question", content=content),
                    receipt_id,
                    provenance=provenance,
                )
            )
            if payload.supersedes_item_id:
                from .views import items as current_items

                old = next(
                    item
                    for item in current_items(s, row, include_links=False)
                    if item["item_id"] == str(payload.supersedes_item_id)
                )
                if old["kind"] != "question":
                    fail("VALIDATION_FAILED", "not_a_question", "只能改派已有问题。")
                from .evidence_service import active_link_refs
                from .schemas import Reference

                _sources(
                    s,
                    ctx,
                    row,
                    [],
                    [
                        Reference.model_validate(ref)
                        for ref in [
                            *old["source_refs"],
                            *active_link_refs(
                                s, ctx, "proposal_item", UUID(old["item_id"]), old["version"]
                            ),
                        ]
                    ],
                    reference_privacy={},
                )
                changed.append(
                    _version(
                        s,
                        ctx,
                        row,
                        ItemInput(
                            item_id=UUID(old["item_id"]),
                            kind="question",
                            content=old["content"],
                        ),
                        receipt_id,
                        op="remove",
                        provenance=provenance,
                    )
                )
        elif isinstance(payload, G0Submit):
            doc = document(s, row)
            if validated.baseline:
                doc["baseline_claim_refs"] = validated.baseline.get("baseline_claim_refs", [])
            own_refs = [r.model_dump(mode="json") for r in _all_refs_from_document(doc)]
            doc["direct_source_refs"] = doc["source_refs"]
            doc["source_refs"] = own_refs
            doc["context_refs"] = [
                ref for ref in own_refs if ref["type"] in {"knowledge", "parameter"}
            ]
            sub = ProposalSubmission(
                id=uuid4(),
                tenant_id=ctx.tenant_id,
                category_id=ctx.category_id,
                proposal_id=row.id,
                revision=row.revision,
                owner_id=row.owner_id,
                reviewer_id=payload.reviewer_id,
                frozen_document=doc,
                document_digest=digest(doc),
                context_refs=doc["context_refs"],
                option_count=sum(item["kind"] == "option" for item in doc["items"]),
                no_alternative_reason=payload.no_alternative_reason,
                receipt_id=receipt_id,
            )
            s.add(sub)
            s.flush([sub])
            from .materialize import grant_review_sources

            grant_review_sources(s, ctx, row, sub)
            row.status, row.current_submission_id = "in_review", sub.id
            row.action_result = {"submission_id": str(sub.id), "reviewer_id": str(sub.reviewer_id)}
        else:
            sub = _submission(s, ctx, row, payload)
            row.reviewer_for_decision = sub.reviewer_id
            dispositions, owner, added = _audience_changes(s, row, payload)
            grant = member(s, ctx, ctx.requester_id, reviewer=True)
            approved = payload.outcome == "approved"
            decision = ProposalDecision(
                id=uuid4(),
                tenant_id=ctx.tenant_id,
                category_id=ctx.category_id,
                proposal_id=row.id,
                submission_id=sub.id,
                owner_id=row.owner_id,
                decided_by=ctx.requester_id,
                outcome=payload.outcome,
                rationale=payload.rationale,
                selected_option_item_id=payload.selected_option_item_id,
                dispositions=dispositions,
                project_owner_id=owner if approved else None,
                project_owner_audience_added=added if approved else False,
                signer_grant_snapshot={
                    "id": str(grant.id),
                    "access_epoch": grant.access_epoch,
                    "product_manager": grant.product_manager,
                    "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
                },
                review_digest=sub.document_digest,
                created_product_id=(
                    row.baseline_product_id if row.target_kind == "new_variant" else uuid4()
                )
                if approved
                else None,
                created_variant_id=uuid4()
                if approved and row.target_kind == "new_variant"
                else None,
                created_definition_id=uuid4() if approved else None,
                created_project_id=uuid4() if approved else None,
                creation={
                    "product_name": payload.new_identity.name
                    if payload.new_identity
                    else row.title,
                    "project_name": payload.project.name if payload.project else row.title,
                    "variant_kind": payload.new_identity.variant_kind
                    if payload.new_identity
                    else "configuration",
                },
                receipt_id=receipt_id,
            )
            s.add(decision)
            s.flush([decision])
            if approved:
                from .materialize import approve

                approve(
                    s, ctx, row, sub, decision, provenance=provenance, baseline=validated.baseline
                )
                from .baseline import validate_references
                from .root_sources import consume_claims

                consume_claims(
                    s,
                    ctx,
                    validate_references(s, ctx, _all_refs_from_document(sub.frozen_document)),
                    decision,
                )
            row.status = payload.outcome
            row.action_result = {
                "decision_id": str(decision.id),
                "product_id": str(decision.created_product_id) if approved else None,
                "variant_id": str(decision.created_variant_id)
                if approved and decision.created_variant_id
                else None,
                "definition_id": str(decision.created_definition_id) if approved else None,
                "project_id": str(decision.created_project_id) if approved else None,
                "dispositions": dispositions,
                "project_owner_id": str(owner) if approved else None,
                "project_owner_audience_added": added if approved else False,
            }
        row.revision += 1
    row.prepared_receipt_id = receipt_id
    row.prepared_by_run_id = provenance["run_id"]
    row.action_result = {
        **getattr(row, "action_result", {}),
        "proposal_url": f"/categories/{ctx.category_id}/proposals/{row.id}",
        **(
            {
                "prepared_candidate_id": str(provenance["prepared_candidate_id"]),
                "candidate_digest": payload.candidate_digest,
            }
            if provenance["prepared_candidate_id"]
            else {}
        ),
    }
    s.flush()
    s.add(
        ProposalRevision(
            tenant_id=ctx.tenant_id,
            category_id=ctx.category_id,
            proposal_id=row.id,
            revision=row.revision,
            changed_items=changed,
            actor_id=ctx.actor_id,
            run_id=provenance["run_id"],
            receipt_id=receipt_id,
            document_digest=digest(document(s, row)),
        )
    )
    return row, "proposal", row.effective_visibility


def _all_refs_from_document(doc):
    from .schemas import Reference

    refs = [
        *doc.get("source_refs", []),
        *doc.get("context_refs", []),
        *doc.get("baseline_claim_refs", []),
        *(r for item in doc["items"] for r in item["source_refs"]),
        *(
            {
                "type": "parameter",
                "id": item["content"]["parameter_id"],
                "version": item["content"]["parameter_version"],
            }
            for item in doc["items"]
            if item["kind"] == "spec" and item["content"].get("parameter_id")
        ),
    ]
    typed = [Reference.model_validate(r) for r in refs]
    return list({digest(ref.model_dump(mode="json")): ref for ref in typed}.values())


def _check_document_references(s, ctx, doc, *, approved=False):
    from .baseline import validate_references
    from .root_sources import ordinary_refs, validate_document_links

    if any(
        link["status"] != "active"
        for item in doc["items"]
        for link in item.get("evidence_links", ())
    ):
        fail("SOURCE_STALE", "evidence_link_changed", "关联证据已失效，请重核当前条目来源。")
    refs = _all_refs_from_document(doc)
    if approved:
        # Preserve the G0 withdrawal reason using only caller-visible status.
        # Claim locks and body reads still follow the complete source union.
        identities = sorted(
            {ref.id for ref in refs if ref.type in {"artifact", "original"}}, key=str
        )
        for identity in identities:
            status = s.scalar(
                select(Artifact.status).where(
                    Artifact.id == identity,
                    Artifact.tenant_id == ctx.tenant_id,
                    Artifact.category_id == ctx.category_id,
                )
            )
            if status != "active":
                fail(
                    "SOURCE_STALE",
                    "original_withdrawn",
                    "提交引用的原件已撤回，请退回处理后重新提交。",
                )
    # The complete union is locked in UUID order once before per-reference work.
    validate_references(s, ctx, refs)
    _references(s, ctx, ordinary_refs(doc), approved=approved)
    validate_document_links(s, ctx, doc, approved=approved)


def finalize_receipt(s, ctx, command, scope, payload, subject, receipt):
    if isinstance(payload, G0Decide) and payload.outcome == "approved":
        s.add(
            Outbox(
                tenant_id=ctx.tenant_id,
                category_id=ctx.category_id,
                receipt_id=receipt.id,
                type="project.created",
                subject_id=UUID(subject.action_result["project_id"]),
                subject_revision=1,
                actor_id=ctx.actor_id,
                correlation_id=command.command_id,
            )
        )
