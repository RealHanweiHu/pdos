"""Read-only views of the actual visible proposal document; no stored facts."""

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from uuid import UUID

from pdos_next.service import digest

from . import views
from .access import fail

VERSION = "m3.proposal-views/v1"
VIEW_NAMES = {"positioning", "spec-benchmark", "feature-config", "definition-maturity"}
DOCUMENT_KEYS = (
    "title",
    "brief",
    "entry_kind",
    "target_kind",
    "baseline_product_id",
    "baseline_definition_id",
    "baseline_definition_revision",
    "items",
    "source_refs",
    "context_refs",
)


def read_document(s, ctx, proposal_id):
    # views.read owns RLS and withdraw/revert reference redaction, including the
    # frozen submission. Never project raw document() into a public view.
    result = views.read(s, ctx, proposal_id)
    submission = result.get("submission")
    frozen = (
        result["status"] == "in_review"
        and submission is not None
        and submission["reviewer_id"] == str(ctx.requester_id)
    )
    if frozen and submission.get("frozen_document") is None:
        fail("SOURCE_UNAVAILABLE", "frozen_source_unreadable", "提交副本的来源不在当前可读范围。")
    document = deepcopy(
        submission["frozen_document"] if frozen else {key: result[key] for key in DOCUMENT_KEYS}
    )
    identity = {
        "proposal_id": result["id"],
        "revision": submission["revision"] if frozen else result["revision"],
        "document_digest": submission["document_digest"] if frozen else digest(document),
        "submission_id": submission["id"] if frozen else None,
        "document_mode": "frozen" if frozen else "current",
    }
    return {
        **result,
        "display_document": document,
        "document_identity": identity,
        "maturity": views.maturity(document),
    }


def maturity(document):
    result = views.maturity(document)
    blockers = []
    for item in result["freeze_blockers"]:
        content, reasons = item["content"], []
        if content["item_status"] in {"unknown", "expert_pending"}:
            reasons.append("item_status_" + content["item_status"])
        if content["availability"] in {"unknown", "conflicted"}:
            reasons.append("availability_" + content["availability"])
        if content["value_type"] in {"number", "range"}:
            if not content.get("unit"):
                reasons.append("unit_missing")
            if not content.get("condition_note"):
                reasons.append("condition_missing")
        blockers.append({**item, "blocker_reasons": reasons})
    return {
        **result,
        "freeze_blockers": blockers,
        "questions": [item for item in document["items"] if item["kind"] == "question"],
    }


def feature_config(comparison):
    return {
        "groups": [
            group
            for group in comparison["groups"]
            if group["parameter"]["value_type"] in {"boolean", "enum"}
        ],
        "unmapped": comparison["unmapped"],
        "subjects": comparison["subjects"],
        "unavailable": comparison["unavailable"],
    }


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
        return str(result) if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def positioning(comparison):
    subjects = {(row["type"], row["id"]): row for row in comparison["subjects"]}
    facets, unknowns = {}, []
    for group in comparison["groups"]:
        for observation in group["observations"]:
            subject = subjects[(observation["subject"]["type"], observation["subject"]["id"])]
            y = _number(observation.get("value"))
            reasons = list(observation.get("reasons", []))
            if not observation.get("comparable") or y is None:
                if y is None:
                    reasons.append("numeric_point_unavailable")
                unknowns.append(
                    {
                        "subject": observation["subject"],
                        "label": subject["label"],
                        "observation_id": observation["observation_id"],
                        "reasons": sorted(set(reasons)),
                        "source_refs": observation.get("source_refs", []),
                    }
                )
                continue
            prices = subject.get("prices", [])
            if not prices:
                unknowns.append(
                    {
                        "subject": observation["subject"],
                        "label": subject["label"],
                        "observation_id": observation["observation_id"],
                        "reasons": ["price_missing"],
                        "source_refs": observation.get("source_refs", []),
                    }
                )
                continue
            for price_index, price in enumerate(prices):
                x = _number(price.get("amount"))
                price_reasons = list(price.get("reasons", []))
                context = {
                    "currency": price.get("currency"),
                    "basis": price.get("basis", price.get("price_type")),
                    "as_of": price.get("as_of", price.get("observed_on")),
                    **{
                        key: price.get(key)
                        for key in (
                            "includes_tax",
                            "includes_shipping",
                            "channel",
                            "region",
                        )
                    },
                }
                if (
                    price_reasons
                    or x is None
                    or price.get("availability") != "known"
                    or not context["currency"]
                    or context["basis"] in {None, "unknown"}
                    or not context["as_of"]
                ):
                    if x is None:
                        price_reasons.append("price_amount_unknown")
                    if not context["currency"]:
                        price_reasons.append("price_currency_unknown")
                    if context["basis"] in {None, "unknown"}:
                        price_reasons.append("price_basis_unknown")
                    if not context["as_of"]:
                        price_reasons.append("price_date_unknown")
                    unknowns.append(
                        {
                            "subject": observation["subject"],
                            "label": subject["label"],
                            "observation_id": observation["observation_id"],
                            "price_index": price_index,
                            "reasons": sorted(set(price_reasons or ["price_unavailable"])),
                            "source_refs": [
                                *observation.get("source_refs", []),
                                *price.get("source_refs", []),
                            ],
                        }
                    )
                    continue
                key = digest(
                    [
                        group["parameter_id"],
                        group["parameter_version"],
                        group["unit"],
                        group["condition_note"],
                        group.get("test_conditions"),
                        context,
                    ]
                )
                facet = facets.setdefault(
                    key,
                    {
                        "key": key,
                        "parameter_id": group["parameter_id"],
                        "parameter_version": group["parameter_version"],
                        "parameter": group["parameter"],
                        "unit": group["unit"],
                        "condition_note": group["condition_note"],
                        "test_conditions": group.get("test_conditions"),
                        "price_context": context,
                        "points": [],
                        "sample_count": 0,
                    },
                )
                facet["points"].append(
                    {
                        "subject": observation["subject"],
                        "label": subject["label"],
                        "x": x,
                        "y": y,
                        "observation_id": observation["observation_id"],
                        "price_index": price_index,
                        "evidence_kind": observation.get(
                            "evidence_kind", observation.get("nature")
                        ),
                        "source_refs": [
                            *observation.get("source_refs", []),
                            *price.get("source_refs", []),
                        ],
                    }
                )
                facet["sample_count"] = len(facet["points"])
    return {
        "groups": list(facets.values()),
        "unknowns": unknowns,
        "unmapped": comparison["unmapped"],
        "unavailable": comparison["unavailable"],
        "unknown_count": len(unknowns),
    }


def read(s, ctx, name, proposal_id, parameter_ids=None):
    if name not in VIEW_NAMES:
        fail("NOT_FOUND", "view_unknown", "立项视图不存在。", 404)
    record = read_document(s, ctx, proposal_id)
    identity = record["document_identity"]
    document = record["display_document"]
    if name == "definition-maturity":
        data = maturity(document)
        input_digest = digest([identity, data])
    else:
        from sqlalchemy import select

        from .category_models import KnowledgeCurrent, KnowledgeEntry
        from .spec_compare import SpecCompareInput, compare

        # Only current shared competitors under the actual category RLS join.
        competitors = s.scalars(
            select(KnowledgeEntry.id)
            .join(
                KnowledgeCurrent,
                (KnowledgeCurrent.tenant_id == KnowledgeEntry.tenant_id)
                & (KnowledgeCurrent.category_id == KnowledgeEntry.category_id)
                & (KnowledgeCurrent.lineage_id == KnowledgeEntry.lineage_id)
                & (KnowledgeCurrent.current_version == KnowledgeEntry.version)
                & (KnowledgeCurrent.current_entry_id == KnowledgeEntry.id),
            )
            .where(
                KnowledgeEntry.tenant_id == ctx.tenant_id,
                KnowledgeEntry.category_id == ctx.category_id,
                KnowledgeEntry.kind == "competitor",
                KnowledgeEntry.action != "withdraw",
                KnowledgeCurrent.status == "active",
            )
            .order_by(KnowledgeEntry.id)
        ).all()
        subjects = [{"type": "proposal", "id": proposal_id}]
        if document.get("baseline_product_id"):
            subjects.append({"type": "product", "id": UUID(document["baseline_product_id"])})
        subjects.extend({"type": "competitor", "id": identity} for identity in competitors)
        comparison = compare(
            s,
            ctx,
            SpecCompareInput(
                subjects=subjects,
                parameter_ids=list(dict.fromkeys(parameter_ids or [])),
            ),
        )
        if name == "positioning":
            data = positioning(comparison)
        elif name == "feature-config":
            data = feature_config(comparison)
        else:
            data = comparison
        input_digest = digest([identity, comparison["input_digest"], name])
    return {
        "view": name,
        **identity,
        "context_changes": record["context_changes"],
        "engine_version": VERSION,
        "input_digest": input_digest,
        "data": data,
    }
