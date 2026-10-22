from uuid import UUID

from sqlalchemy import select

from .access import proposal


def items(s, row, *, include_history=False, include_links=True):
    from .models import ProposalItem, ProposalItemVersion

    query = (
        select(ProposalItem, ProposalItemVersion)
        .join(
            ProposalItemVersion,
            (ProposalItemVersion.item_id == ProposalItem.id)
            & (ProposalItemVersion.tenant_id == ProposalItem.tenant_id),
        )
        .where(ProposalItem.proposal_id == row.id)
    )
    if not include_history:
        query = query.where(
            ProposalItemVersion.version == ProposalItem.current_version,
            ProposalItem.removed.is_(False),
        )
    result = [
        {
            "item_id": str(item.id),
            "version": version.version,
            "kind": version.kind,
            "content": version.content,
            "source_refs": version.source_refs,
            "origin": version.origin,
            "writer_id": str(version.writer_id),
            "run_id": str(version.run_id) if version.run_id else None,
            "confirmed_by": str(version.confirmed_by) if version.confirmed_by else None,
            "human_value": version.origin == "human" or version.confirmed_by is not None,
            "removed": version.removed,
        }
        for item, version in s.execute(
            query.order_by(ProposalItem.sort_key, ProposalItemVersion.version)
        )
    ]
    if include_links:
        from .root_sources import project_items

        return project_items(s, row, result)
    return result


def document(s, row):
    return {
        "title": row.title,
        "brief": row.brief,
        "entry_kind": row.entry_kind,
        "target_kind": row.target_kind,
        "baseline_product_id": str(row.baseline_product_id) if row.baseline_product_id else None,
        "baseline_definition_id": str(row.baseline_definition_id)
        if row.baseline_definition_id
        else None,
        "baseline_definition_revision": row.baseline_definition_revision,
        "items": items(s, row),
        "source_refs": row.source_refs,
        "context_refs": row.context_refs,
    }


def required_dispositions(doc):
    return [
        {
            "subject_type": "question" if item["kind"] == "question" else "spec_item",
            "subject_id": item["item_id"],
            "title": item["content"].get("question") or item["content"].get("parameter"),
            "content": item["content"],
        }
        for item in doc["items"]
        if (item["kind"] == "question" and item["content"]["status"] == "open")
        or (
            item["kind"] == "spec"
            and (
                item["content"]["item_status"] == "expert_pending"
                or (
                    item["content"]["availability"] != "not_applicable"
                    and (
                        item["content"]["item_status"] == "unknown"
                        or item["content"]["availability"] in {"unknown", "conflicted"}
                    )
                )
            )
        )
    ]


def maturity(doc):
    from collections import Counter

    specs = [item for item in doc["items"] if item["kind"] == "spec"]
    options = [item for item in doc["items"] if item["kind"] == "option"]
    worth_it = any(
        item["kind"] == "section"
        and item["content"].get("key") == "worth_it"
        and item["content"].get("text", "").strip()
        for item in doc["items"]
    )
    return {
        "spec_count": len(specs),
        "option_count": len(options),
        "item_status_counts": dict(Counter(item["content"]["item_status"] for item in specs)),
        "availability_counts": dict(Counter(item["content"]["availability"] for item in specs)),
        "required_dispositions": required_dispositions(doc),
        "submission_checks": {
            "worth_it_present": worth_it,
            "alternative_or_reason_required": len(options) < 2,
        },
        "freeze_blockers": [
            item
            for item in specs
            if item["content"]["item_status"] in {"unknown", "expert_pending"}
            or item["content"]["availability"] in {"unknown", "conflicted"}
            or (
                item["content"]["value_type"] in {"number", "range"}
                and (not item["content"].get("unit") or not item["content"].get("condition_note"))
            )
        ],
        "guidance": "10–20 条关键规格仅作提示；未知项可带入 G0 并逐条处置。",
    }


def context_changes(s, ctx, row, doc):
    """Resolve changes under the reader's RLS scope, including private drafts."""
    from .category_models import KnowledgeCurrent, KnowledgeEntry, ParameterCurrent

    refs = [*row.context_refs, *row.source_refs]
    for item in doc["items"]:
        refs.extend(item["source_refs"])
        refs.extend(link["evidence"] for link in item.get("evidence_links", []))
        content = item["content"]
        if item["kind"] == "spec" and content.get("parameter_id"):
            refs.append(
                {
                    "type": "parameter",
                    "id": content["parameter_id"],
                    "version": content["parameter_version"],
                }
            )
    parameter_refs = {
        (UUID(ref["id"]), ref["version"]) for ref in refs if ref["type"] == "parameter"
    }
    knowledge_refs = {
        (UUID(ref["id"]), ref["version"]) for ref in refs if ref["type"] == "knowledge"
    }
    changes = []
    if parameter_refs:
        current = {
            value.parameter_id: value.current_version
            for value in s.scalars(
                select(ParameterCurrent).where(
                    ParameterCurrent.tenant_id == ctx.tenant_id,
                    ParameterCurrent.category_id == ctx.category_id,
                    ParameterCurrent.parameter_id.in_([ref[0] for ref in parameter_refs]),
                )
            )
        }
        for identity, version in sorted(parameter_refs, key=lambda item: (str(item[0]), item[1])):
            if current.get(identity) != version:
                changes.append(
                    {
                        "type": "parameter",
                        "id": str(identity),
                        "version": version,
                        "current_version": current.get(identity),
                    }
                )
    if knowledge_refs:
        rows = s.execute(
            select(KnowledgeEntry, KnowledgeCurrent)
            .join(
                KnowledgeCurrent,
                (KnowledgeCurrent.tenant_id == KnowledgeEntry.tenant_id)
                & (KnowledgeCurrent.category_id == KnowledgeEntry.category_id)
                & (KnowledgeCurrent.lineage_id == KnowledgeEntry.lineage_id),
            )
            .where(
                KnowledgeEntry.tenant_id == ctx.tenant_id,
                KnowledgeEntry.category_id == ctx.category_id,
                KnowledgeEntry.id.in_([ref[0] for ref in knowledge_refs]),
            )
        ).all()
        current = {entry.id: pointer for entry, pointer in rows}
        for identity, version in sorted(knowledge_refs, key=lambda item: (str(item[0]), item[1])):
            pointer = current.get(identity)
            if not pointer or pointer.current_version != version or pointer.status != "active":
                changes.append(
                    {
                        "type": "knowledge",
                        "id": str(identity),
                        "version": version,
                        "current_version": pointer.current_version if pointer else None,
                        "status": pointer.status if pointer else "unavailable",
                    }
                )
    from .root_sources import claim_states, source_changes

    return [*changes, *source_changes(refs, claim_states(s, ctx, refs))]


def read(s, ctx, proposal_id):
    from .models import ProposalDecision, ProposalSubmission

    row = proposal(s, ctx, proposal_id)
    doc = document(s, row)
    changes = context_changes(s, ctx, row, doc)
    submission = (
        s.get(ProposalSubmission, row.current_submission_id) if row.current_submission_id else None
    )
    frozen_document = None
    if submission:
        from pdos_next.errors import DomainError

        from .baseline import validate_sources
        from .schemas import Reference

        document_refs = [
            *submission.frozen_document.get("source_refs", []),
            *submission.frozen_document.get("context_refs", []),
            *(
                ref
                for item in submission.frozen_document.get("items", [])
                for ref in item.get("source_refs", [])
            ),
        ]
        if submission.frozen_document.get("baseline_definition_id"):
            document_refs.append(
                {
                    "type": "definition",
                    "id": submission.frozen_document["baseline_definition_id"],
                    "version": submission.frozen_document["baseline_definition_revision"],
                }
            )
        try:
            # A later share authorizes the current proposal, not old private
            # bodies in a retained submission. Read the full fixed tree through
            # the actual caller's ordinary audience before returning that copy.
            validate_sources(
                s,
                ctx,
                None,
                extra_refs=[Reference.model_validate(ref) for ref in document_refs],
                history_permissions=True,
            )
        except DomainError:
            pass
        else:
            frozen_document = submission.frozen_document
    decision = s.scalar(
        select(ProposalDecision)
        .where(ProposalDecision.proposal_id == row.id)
        .order_by(ProposalDecision.created_at.desc())
        .limit(1)
    )
    result = {
        "id": str(row.id),
        "category_id": str(row.category_id),
        "owner_id": str(row.owner_id),
        "revision": row.revision,
        "status": row.status,
        "visibility": row.effective_visibility,
        "private_source_count": row.private_source_count,
        "context_hint": bool(changes),
        "context_changes": changes,
        **doc,
        "maturity": maturity(doc),
        "submission": {
            "id": str(submission.id),
            "revision": submission.revision,
            "reviewer_id": str(submission.reviewer_id),
            "document_digest": submission.document_digest,
            "context_refs": submission.context_refs
            if frozen_document is not None
            else [
                {key: ref[key] for key in ("type", "id", "version") if key in ref}
                for ref in submission.context_refs
            ],
            "frozen_document": frozen_document,
            "frozen_document_available": frozen_document is not None,
        }
        if submission
        else None,
        "decision": {
            "id": str(decision.id),
            "outcome": decision.outcome,
            "rationale": decision.rationale,
            "decided_by": str(decision.decided_by),
            "decided_at": decision.created_at.isoformat(),
            "receipt_id": str(decision.receipt_id) if decision.receipt_id else None,
            "product_id": str(decision.created_product_id) if decision.created_product_id else None,
            "variant_id": str(decision.created_variant_id) if decision.created_variant_id else None,
            "definition_id": str(decision.created_definition_id)
            if decision.created_definition_id
            else None,
            "project_id": str(decision.created_project_id) if decision.created_project_id else None,
            "dispositions": decision.dispositions,
            "project_owner_audience_added": decision.project_owner_audience_added,
        }
        if decision
        else None,
    }
    from .root_sources import claim_states, nested_claim_refs, redact_references

    return redact_references(result, claim_states(s, ctx, list(nested_claim_refs(result))))
