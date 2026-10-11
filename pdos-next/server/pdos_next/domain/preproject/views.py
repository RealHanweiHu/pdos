from sqlalchemy import select

from .access import proposal


def items(s, row, *, include_history=False):
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
    return [
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


def document(s, row):
    return {
        "title": row.title,
        "brief": row.brief,
        "entry_kind": row.entry_kind,
        "target_kind": row.target_kind,
        "items": items(s, row),
        "source_refs": row.source_refs,
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


def read(s, ctx, proposal_id):
    from .models import ProposalDecision, ProposalSubmission

    row = proposal(s, ctx, proposal_id)
    doc = document(s, row)
    submission = (
        s.get(ProposalSubmission, row.current_submission_id) if row.current_submission_id else None
    )
    decision = s.scalar(
        select(ProposalDecision)
        .where(ProposalDecision.proposal_id == row.id)
        .order_by(ProposalDecision.created_at.desc())
        .limit(1)
    )
    return {
        "id": str(row.id),
        "category_id": str(row.category_id),
        "owner_id": str(row.owner_id),
        "revision": row.revision,
        "status": row.status,
        "visibility": row.effective_visibility,
        "private_source_count": row.private_source_count,
        "context_hint": row.context_hint,
        **doc,
        "maturity": maturity(doc),
        "submission": {
            "id": str(submission.id),
            "revision": submission.revision,
            "reviewer_id": str(submission.reviewer_id),
            "document_digest": submission.document_digest,
            "context_refs": submission.context_refs,
            "frozen_document": submission.frozen_document,
        }
        if submission
        else None,
        "decision": {
            "id": str(decision.id),
            "outcome": decision.outcome,
            "rationale": decision.rationale,
            "product_id": str(decision.created_product_id) if decision.created_product_id else None,
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
