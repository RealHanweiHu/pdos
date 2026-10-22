"""Read-only, source-checked distribution of visible fixed segments and price bands.

Breaks are display inputs, never policy. Empty cells are observations of this
readable set, never proof of a market gap. No source/segment is inferred.
"""

from collections import Counter
from copy import deepcopy
from decimal import Decimal, InvalidOperation

from sqlalchemy import select, tuple_

from pdos_next.category_scope import category_scope
from pdos_next.clock import now
from pdos_next.errors import DomainError
from pdos_next.models import Product
from pdos_next.service import digest, require_access

from . import category_reads, spec_compare
from .access import fail
from .category_models import KnowledgeCurrent, KnowledgeEntry, ProductTargetSegment
from .models import Proposal, ProposalDecision, ProposalSubmission

VERSION = "category-matrix/v1"
BASIS_FIELDS = (
    "currency",
    "as_of",
    "basis",
    "includes_tax",
    "includes_shipping",
    "region",
    "channel",
)
TARGET_FIELDS = ("currency", "basis", "includes_tax", "as_of")


def _decimal(value):
    if type(value) not in (Decimal, int, str):
        raise ValueError("Exact decimal required")
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError("Finite decimal required")
    return result


def _number(value):
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _breaks(values):
    try:
        if values is not None and not isinstance(values, (list, tuple)):
            raise TypeError
        result = [_decimal(value) for value in (("150", "300") if values is None else values)]
        if not result or len(result) > 10 or any(value <= 0 for value in result):
            raise ValueError
        if any(left >= right for left, right in zip(result, result[1:], strict=False)):
            raise ValueError
    except (TypeError, ValueError, InvalidOperation):
        fail(
            "VALIDATION_FAILED",
            "price_breaks_invalid",
            "价格分带须为一至十个严格递增的正十进制数，不接受浮点数。",
            422,
        )
    return result


def _bands(breaks):
    return [
        {
            "id": f"band:{index}",
            "lower": _number(lower) if lower is not None else None,
            "upper": _number(upper) if upper is not None else None,
            "lower_inclusive": lower is not None,
            "upper_inclusive": False,
        }
        for index, (lower, upper) in enumerate(zip([None, *breaks], [*breaks, None], strict=True))
    ]


def _basis(price):
    return {
        field: spec_compare._json(
            price.get(field, price.get({"as_of": "observed_on", "basis": "price_type"}.get(field)))
        )
        for field in BASIS_FIELDS
    }


def compute(category_id, subjects, *, breaks=None, as_of=None):
    """Pure projection of already ACL/source-guarded subjects from ``read``."""
    breaks = _breaks(breaks)
    bands, groups, unplaced = _bands(breaks), {}, []
    all_segments = {}
    for subject in subjects:
        for segment in subject["segments"]:
            if not segment["reasons"]:
                key = (segment["lineage_id"], segment["version"])
                all_segments[key] = segment
    placed, blocked, reasons_by_subject = set(), set(), {}
    observations = 0
    for subject in subjects:
        identity = (subject["subject"]["type"], subject["subject"]["id"])
        prices = subject["prices"] or [{"amount": None, "reasons": ["price_unknown"]}]
        segments = subject["segments"] or [None]
        observations += len(prices)
        for price in prices:
            price_reasons = set(price.get("reasons", []))
            try:
                amount = _decimal(price.get("amount"))
            except (ValueError, InvalidOperation):
                amount = None
                price_reasons.add(
                    "price_unknown" if price.get("amount") is None else "price_invalid"
                )
            if not price.get("source_refs"):
                price_reasons.add("price_source_unavailable")
            basis = _basis(price)
            for field in ("currency", "as_of", "basis"):
                if basis[field] in (None, "", "unknown"):
                    price_reasons.add(
                        {"as_of": "price_date", "basis": "price_basis"}.get(field, field)
                        + "_missing"
                    )
            for segment in segments:
                reasons = price_reasons | set(
                    segment["reasons"] if segment else ["segment_missing"]
                )
                if reasons:
                    blocked.add(identity)
                    reasons_by_subject.setdefault(identity, set()).update(reasons)
                    unplaced.append(
                        {
                            "subject": deepcopy(subject["subject"]),
                            "fixed_segment": deepcopy(segment)
                            if segment and segment.get("lineage_id") is not None
                            else None,
                            **(
                                {
                                    "segment_reference": {
                                        "entry_id": segment["entry_id"],
                                        "version": segment["version"],
                                    }
                                }
                                if segment and segment.get("lineage_id") is None
                                else {}
                            ),
                            "price": deepcopy(price),
                            "source_refs": deepcopy(price.get("source_refs", [])),
                            "reasons": sorted(reasons),
                        }
                    )
                    continue
                key = digest(basis)
                group = groups.setdefault(key, {"id": key, "basis": basis, "rows": {}})
                segment_key = (segment["lineage_id"], segment["version"])
                row = group["rows"].setdefault(segment_key, {})
                band = sum(amount >= threshold for threshold in breaks)
                cell = row.setdefault(band, {"products": [], "competitors": []})
                cell["products" if identity[0] == "product" else "competitors"].append(
                    {
                        "subject": deepcopy(subject["subject"]),
                        "price": deepcopy(price),
                        "source_refs": deepcopy(price["source_refs"]),
                    }
                )
                placed.add(identity)
    result_groups, placements = [], 0
    for group in sorted(groups.values(), key=lambda value: value["id"]):
        rows = []
        for segment_key, segment in sorted(all_segments.items()):
            cells = []
            for index, band in enumerate(bands):
                entries = group["rows"].get(segment_key, {}).get(index, {})
                products, competitors = entries.get("products", []), entries.get("competitors", [])
                placements += len(products) + len(competitors)
                cells.append(
                    {
                        "band_id": band["id"],
                        "status": "observed"
                        if products or competitors
                        else "no_readable_observations",
                        "products": products,
                        "competitors": competitors,
                        "counts": {"products": len(products), "competitors": len(competitors)},
                    }
                )
            rows.append({"segment": deepcopy(segment), "cells": cells})
        result_groups.append({**group, "rows": rows})
    reason_counts = Counter(reason for reasons in reasons_by_subject.values() for reason in reasons)
    identities = {(row["subject"]["type"], row["subject"]["id"]) for row in subjects}
    return spec_compare._json(
        {
            "version": VERSION,
            "category_id": str(category_id),
            "as_of": as_of,
            "display": {
                "breaks": [_number(value) for value in breaks],
                "bands": bands,
                "semantics": "read_only_distribution",
            },
            "groups": result_groups,
            "unplaced": unplaced,
            "coverage": {
                "visible_products": sum(kind == "product" for kind, _ in identities),
                "visible_competitors": sum(kind == "competitor" for kind, _ in identities),
                "placed_subjects": len(placed),
                "unplaced_subjects": len(identities - placed),
                "partially_placed_subjects": len(placed & blocked),
                "placements": placements,
                "price_observations": observations,
                "reason_counts": dict(sorted(reason_counts.items())),
            },
            "limitations": [
                *(
                    ["competitor_segments_missing"]
                    if any(
                        subject["subject"]["type"] == "competitor" and not subject["segments"]
                        for subject in subjects
                    )
                    else []
                ),
                "empty_cells_are_not_market_gaps",
                "target_price_requires_readable_matching_g0_source",
                "unknown_basis_dimensions_are_separate_null_groups",
            ],
        }
    )


def _target_raw(product):
    return {
        "amount": product.target_price,
        **{field: getattr(product, f"target_price_{field}") for field in TARGET_FIELDS},
    }


def _target_price(s, ctx, product, candidates):
    raw, matched_prices, has_document = _target_raw(product), [], False
    for decision, submission in candidates:
        if digest(submission.frozen_document) != submission.document_digest:
            continue
        has_document = True
        for item in submission.frozen_document.get("items", []):
            value = item.get("content", {}).get("target_price")
            if item.get("kind") != "commercial_target" or not isinstance(value, dict):
                continue
            try:
                same_amount = _decimal(value.get("amount")) == _decimal(raw["amount"])
            except (ValueError, InvalidOperation):
                same_amount = value.get("amount") is None and raw["amount"] is None
            if not same_amount or any(
                spec_compare._json(value.get(field)) != spec_compare._json(raw[field])
                for field in TARGET_FIELDS
            ):
                continue
            refs = [value["source"]] if value.get("source") else item.get("source_refs", [])
            price = spec_compare._price(
                s,
                ctx,
                raw,
                refs,
                f"{product.id}:target_price",
                product_id=product.id,
            )
            price["g0_source"] = {
                "proposal_id": str(decision.proposal_id),
                "decision_id": str(decision.id),
                "submission_id": str(submission.id),
                "submission_revision": submission.revision,
                "document_digest": submission.document_digest,
                "item_id": item.get("item_id"),
            }
            if price["comparable"]:
                return price
            matched_prices.append(price)
    if matched_prices:
        return matched_prices[0]
    price = spec_compare._price(
        s, ctx, raw, [], f"{product.id}:target_price", product_id=product.id
    )
    price["reasons"] = sorted(
        {
            *price["reasons"],
            "g0_price_source_unavailable" if not has_document else "target_price_g0_mismatch",
        }
    )
    return price


def _fixed_segments(s, ctx, links):
    keys = {(link.segment_lineage_id, link.segment_version) for link in links}
    if not keys:
        return {}
    rows = s.execute(
        select(KnowledgeEntry, KnowledgeCurrent.status)
        .outerjoin(
            KnowledgeCurrent,
            (
                (KnowledgeCurrent.tenant_id == KnowledgeEntry.tenant_id)
                & (KnowledgeCurrent.category_id == KnowledgeEntry.category_id)
                & (KnowledgeCurrent.lineage_id == KnowledgeEntry.lineage_id)
            ),
        )
        .where(
            KnowledgeEntry.tenant_id == ctx.tenant_id,
            KnowledgeEntry.category_id == ctx.category_id,
            KnowledgeEntry.kind == "segment",
            tuple_(KnowledgeEntry.lineage_id, KnowledgeEntry.version).in_(keys),
        )
    ).all()
    result = {}
    for entry, current_status in rows:
        key = (entry.lineage_id, entry.version)
        ref = {"type": "knowledge", "id": str(entry.id), "version": entry.version}
        sources, reasons = spec_compare._sources(s, ctx, [ref])
        if current_status is None:
            reasons.append("segment_unavailable")
            sources = []
        elif current_status != "active" or entry.action == "withdraw":
            reasons.append("segment_withdrawn")
        result[key] = {
            "lineage_id": str(entry.lineage_id),
            "version": entry.version,
            "entry_id": str(entry.id) if current_status is not None else None,
            "label": entry.content.get("segment") if current_status is not None else None,
            "status": current_status,
            "source_refs": sources,
            "reasons": sorted(set(reasons)),
        }
    return result


def _g0_sources(s, ctx, product_ids):
    if not product_ids:
        return {}
    rows = s.execute(
        select(ProposalDecision, ProposalSubmission)
        .join(
            ProposalSubmission,
            (
                (ProposalSubmission.tenant_id == ProposalDecision.tenant_id)
                & (ProposalSubmission.category_id == ProposalDecision.category_id)
                & (ProposalSubmission.proposal_id == ProposalDecision.proposal_id)
                & (ProposalSubmission.id == ProposalDecision.submission_id)
            ),
        )
        .join(
            Proposal,
            (
                (Proposal.tenant_id == ProposalDecision.tenant_id)
                & (Proposal.category_id == ProposalDecision.category_id)
                & (Proposal.id == ProposalDecision.proposal_id)
            ),
        )
        .where(
            ProposalDecision.tenant_id == ctx.tenant_id,
            ProposalDecision.category_id == ctx.category_id,
            ProposalDecision.outcome == "approved",
            ProposalDecision.created_product_id.in_(product_ids),
            ProposalDecision.created_variant_id.is_(None),
        )
        .order_by(ProposalDecision.id)
    ).all()
    result = {}
    for decision, submission in rows:
        result.setdefault(decision.created_product_id, []).append((decision, submission))
    return result


def read(s, ctx, *, breaks=None):
    category_scope(s, ctx)
    validated_breaks = _breaks(breaks)
    products = []
    for product in s.scalars(
        select(Product)
        .where(
            Product.tenant_id == ctx.tenant_id,
            Product.category_id == ctx.category_id,
        )
        .order_by(Product.id)
    ):
        try:
            require_access(s, ctx, product.id)
        except DomainError as error:
            if error.status not in (403, 404):
                raise
            continue
        products.append(product)
    product_ids = {product.id for product in products}
    links = (
        list(
            s.scalars(
                select(ProductTargetSegment).where(
                    ProductTargetSegment.tenant_id == ctx.tenant_id,
                    ProductTargetSegment.category_id == ctx.category_id,
                    ProductTargetSegment.product_id.in_(product_ids),
                )
            )
        )
        if product_ids
        else []
    )
    segments, candidates = _fixed_segments(s, ctx, links), _g0_sources(s, ctx, product_ids)
    subjects = []
    for product in products:
        fixed = []
        for link in links:
            if link.product_id != product.id:
                continue
            fixed.append(
                segments.get(
                    (link.segment_lineage_id, link.segment_version),
                    {
                        "lineage_id": str(link.segment_lineage_id),
                        "version": link.segment_version,
                        "entry_id": None,
                        "label": None,
                        "status": "unavailable",
                        "source_refs": [],
                        "reasons": ["segment_unavailable"],
                    },
                )
            )
        subjects.append(
            {
                "subject": {
                    "type": "product",
                    "id": str(product.id),
                    "label": product.name,
                    "revision": product.revision,
                },
                "segments": fixed,
                "prices": [_target_price(s, ctx, product, candidates.get(product.id, []))],
            }
        )
    cursor, seen = None, set()
    while True:
        page = category_reads.knowledge(s, ctx, kind="competitor", cursor=cursor, page_size=200)
        for doc in page["items"]:
            from .competitor_segments import resolve_fixed

            content, prices = doc["content"], []
            fixed = resolve_fixed(s, ctx, content.get("segment_refs", []))
            for index, price in enumerate(content.get("prices", [])):
                refs = [price["source_ref"]] if price.get("source_ref") else doc["source_refs"]
                prices.append(
                    spec_compare._price(s, ctx, price, refs, f"{doc['id']}:prices:{index}")
                )
            subjects.append(
                {
                    "subject": {
                        "type": "competitor",
                        "id": doc["id"],
                        "label": f"{content['brand']} {content['model']}",
                        "revision": doc["version"],
                        "origin": doc["origin"],
                    },
                    "segments": [
                        {
                            "lineage_id": value["lineage_id"],
                            "version": value["version"],
                            "entry_id": value["entry_id"],
                            "label": value["label"],
                            "status": "active" if value["status"] == "available" else "unavailable",
                            "source_refs": value["source_refs"],
                            "reasons": value["reasons"],
                        }
                        for value in fixed
                    ],
                    "prices": prices,
                }
            )
        cursor = page["next_cursor"]
        if not cursor:
            break
        if cursor in seen:
            fail("SOURCE_UNAVAILABLE", "matrix_cursor_not_advanced", "品类矩阵分页未推进。", 503)
        seen.add(cursor)
    return compute(ctx.category_id, subjects, breaks=validated_breaks, as_of=now())
