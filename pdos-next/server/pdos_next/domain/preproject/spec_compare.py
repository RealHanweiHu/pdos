"""Read-only comparisons of actual scoped objects, never caller-supplied values.

Competitor IDs are current KnowledgeEntry IDs, not lineage IDs. Exact historical
parameter versions remain meaningful. This result is not a computed Claim proof.
"""

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import select

from pdos_next.category_scope import category_scope
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Product
from pdos_next.schema_base import StrictModel
from pdos_next.schemas.spec_values import numeric_value_shape
from pdos_next.service import digest

from . import baseline, category_reads, category_service, root_sources
from .access import fail
from .category_models import KnowledgeCurrent, KnowledgeEntry
from .schemas import Reference

VERSION = "spec-compare/v2"


class Subject(StrictModel):
    type: Literal["proposal", "product", "competitor"]
    id: UUID


class SpecCompareInput(StrictModel):
    subjects: list[Subject] = Field(min_length=1)
    parameter_ids: list[UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_identities(self):
        identities = [(subject.type, subject.id) for subject in self.subjects]
        if len(identities) != len(set(identities)):
            raise ValueError("Subjects must be distinct")
        if len(self.parameter_ids) != len(set(self.parameter_ids)):
            raise ValueError("Parameter IDs must be distinct")
        return self


def _json(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: _json(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(child) for child in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _proposal(s, ctx, identity):
    from .proposal_views import read_document

    projected = read_document(s, ctx, identity)
    return {
        **projected,
        **projected["display_document"],
        "revision": projected["document_identity"]["revision"],
    }


def _competitor(s, ctx, identity):
    row = s.scalar(
        select(KnowledgeEntry)
        .join(
            KnowledgeCurrent,
            (KnowledgeCurrent.tenant_id == KnowledgeEntry.tenant_id)
            & (KnowledgeCurrent.category_id == KnowledgeEntry.category_id)
            & (KnowledgeCurrent.lineage_id == KnowledgeEntry.lineage_id)
            & (KnowledgeCurrent.current_entry_id == KnowledgeEntry.id)
            & (KnowledgeCurrent.current_version == KnowledgeEntry.version),
        )
        .where(
            KnowledgeEntry.tenant_id == ctx.tenant_id,
            KnowledgeEntry.category_id == ctx.category_id,
            KnowledgeEntry.id == identity,
            KnowledgeEntry.kind == "competitor",
            KnowledgeEntry.action != "withdraw",
            KnowledgeCurrent.status == "active",
        )
    )
    if not row:
        fail("NOT_FOUND", "competitor_not_found", "竞品当前记录不存在或不可读。", 404)
    return root_sources.project_knowledge(s, ctx, [category_reads._row(row)])[0]


def _check_reference(s, ctx, ref, *, product_id=None, visited=None):
    """Use ordinary source readers and recurse through actual persisted source edges."""
    from pdos_next.domain.products.definitions import definition_view
    from pdos_next.domain.products.models import DefinitionRevision

    from .claim_access import load_source, resolve
    from .service import _references

    visited = set() if visited is None else visited
    key = (ref.type, ref.id, ref.version)
    if key in visited:
        fail("SOURCE_UNAVAILABLE", "source_cycle", "来源引用存在循环。")
    visited = {*visited, key}
    if ref.type == "claim":
        claim = resolve(s, ctx, ref.id, ref.version, approved=True)
        if (ref.quote is not None and ref.quote not in claim.quote) or (
            ref.line is not None and ref.line != claim.line
        ):
            fail("SOURCE_UNAVAILABLE", "claim_quote_mismatch", "事实引用定位不一致。")
    elif ref.type in {"artifact", "original", "snapshot"}:
        if ref.type in {"artifact", "original"}:
            # Fixed typed references can point into another readable Product.
            # Derive that scope from the actual RLS-visible head, before loading
            # content through the ordinary version/Original/permission guard.
            source = (
                s.execute(
                    select(Artifact.id, Artifact.product_id).where(
                        Artifact.id == ref.id,
                        Artifact.tenant_id == ctx.tenant_id,
                        Artifact.category_id == ctx.category_id,
                    )
                )
                .mappings()
                .first()
            )
            if source is None or source["id"] != ref.id:
                fail("SOURCE_UNAVAILABLE", "source_unreadable", "固定来源不可读取。", 403)
            product_id = source["product_id"]
        load_source(
            s,
            ctx,
            ref.model_copy(update={"type": "artifact"}) if ref.type == "original" else ref,
            product_id=product_id,
        )
    elif ref.type == "definition":
        row = s.get(DefinitionRevision, ref.id)
        if (
            not row
            or row.tenant_id != ctx.tenant_id
            or row.category_id != ctx.category_id
            or row.revision != ref.version
        ):
            fail("SOURCE_UNAVAILABLE", "definition_unreadable", "固定定义来源不可读。")
        baseline.validate_sources(s, ctx, definition_view(s, ctx, row))
    elif ref.type == "knowledge":
        row = s.get(KnowledgeEntry, ref.id)
        if (
            not row
            or row.tenant_id != ctx.tenant_id
            or row.category_id != ctx.category_id
            or row.version != ref.version
            or row.action == "withdraw"
        ):
            fail("SOURCE_UNAVAILABLE", "knowledge_unreadable", "固定知识来源不可读。")
        from .category_service import _references as knowledge_references

        for child in knowledge_references(
            SimpleNamespace(
                kind=row.kind,
                content=row.content,
                source_refs=[Reference.model_validate(raw) for raw in row.source_refs],
            )
        ):
            _check_reference(s, ctx, child, visited=visited)
    else:
        _references(s, ctx, [ref])


def _sources(s, ctx, refs, *, product_id=None):
    result, reasons = [], []
    for raw in refs:
        fields = {key: value for key, value in raw.items() if key in Reference.model_fields}
        try:
            ref = Reference.model_validate(fields)
            _check_reference(s, ctx, ref, product_id=product_id)
        except (DomainError, ValueError):
            reasons.append("source_unavailable")
            result.append(
                {
                    **{key: raw[key] for key in ("type", "id", "version") if key in raw},
                    "status": "unavailable",
                }
            )
        else:
            result.append(fields)
    return result, sorted(set(reasons))


def _price(s, ctx, raw, refs, identity, *, product_id=None):
    sources, reasons = _sources(s, ctx, refs, product_id=product_id)
    value = {
        key: deepcopy(raw[key])
        for key in (
            "amount",
            "currency",
            "basis",
            "price_type",
            "as_of",
            "observed_on",
            "includes_tax",
            "includes_shipping",
            "channel",
            "region",
        )
        if key in raw
    }
    if value.get("amount") is None:
        reasons.append("price_unknown")
    for field, alternatives in (
        ("currency", ("currency",)),
        ("price_basis", ("basis", "price_type")),
        ("price_date", ("as_of", "observed_on")),
    ):
        if not any(value.get(key) not in (None, "", "unknown") for key in alternatives):
            reasons.append(f"{field}_missing")
    if not refs:
        reasons.append("price_source_unavailable")
    if "source_unavailable" in reasons:
        value["amount"] = None
    return {
        **value,
        "observation_id": identity,
        "source_refs": sources,
        "availability": "known"
        if value.get("amount") is not None and refs and "source_unavailable" not in reasons
        else "unknown",
        "comparable": not reasons,
        "reasons": sorted(set(reasons)),
    }


def _subject(s, ctx, subject, proposals, *, before_definition_read=None):
    identity = subject.model_dump(mode="json")
    meta = {**identity, "issues": [], "prices": [], "unmapped_features": []}
    observations = []
    if subject.type == "proposal":
        doc = proposals[subject.id]
        meta.update(
            label=doc["title"],
            revision=doc["revision"],
            document_identity=doc.get("document_identity"),
            baseline={
                key: doc.get(key)
                for key in (
                    "baseline_product_id",
                    "baseline_definition_id",
                    "baseline_definition_revision",
                )
            },
        )
        for item in doc["items"]:
            content = item["content"]
            if item["kind"] == "spec":
                observations.append((item["item_id"], "spec", content, item["source_refs"], None))
            elif item["kind"] == "commercial_target" and content.get("target_price"):
                price = content["target_price"]
                refs = [price["source"]] if price.get("source") else item["source_refs"]
                meta["prices"].append(_price(s, ctx, price, refs, item["item_id"]))
            elif item["kind"] == "section" and content.get("key") == "features_in_out":
                refs, reasons = _sources(s, ctx, item["source_refs"])
                if not refs:
                    reasons.append("feature_source_unavailable")
                meta["unmapped_features"].append(
                    {
                        "item_id": item["item_id"],
                        "text": None if reasons else content["text"],
                        "availability": "unknown" if reasons else "known",
                        "source_refs": refs,
                        "reasons": ["unmapped_feature_text", *reasons],
                    }
                )
    elif subject.type == "competitor":
        doc = _competitor(s, ctx, subject.id)
        content = doc["content"]
        meta.update(
            label=f"{content['brand']} {content['model']}",
            revision=doc["version"],
            lineage_id=doc["lineage_id"],
        )
        for field, kind in (("metrics", "metric"), ("features", "feature")):
            for index, item in enumerate(content.get(field, [])):
                refs = [item["source_ref"]] if item.get("source_ref") else doc["source_refs"]
                observations.append((f"{doc['id']}:{field}:{index}", kind, item, refs, None))
        for index, price in enumerate(content.get("prices", [])):
            refs = [price["source_ref"]] if price.get("source_ref") else doc["source_refs"]
            meta["prices"].append(_price(s, ctx, price, refs, f"{doc['id']}:prices:{index}"))
    else:
        fixed = {
            (doc.get("baseline_definition_id"), doc["baseline_definition_revision"])
            for doc in proposals.values()
            if str(doc.get("baseline_product_id")) == str(subject.id)
            and doc.get("baseline_definition_revision") is not None
        }
        if len(fixed) > 1:
            fail("VALIDATION_FAILED", "ambiguous_fixed_baseline", "提案引用了不同的固定基线版本。")
        chosen = next(iter(fixed), (None, None))
        guarded_read = (
            {"before_definition_read": before_definition_read, "include_blocks": False}
            if before_definition_read is not None
            else {}
        )
        read = baseline.read_baseline(
            s, ctx, subject.id, definition_revision=chosen[1], **guarded_read
        )
        doc = read["definition"]
        meta.update(
            baseline_kind=read["baseline_kind"],
            issues=read["source_issues"],
            unavailable_definition_count=read.get("unavailable_definition_count", 0),
        )
        product = s.get(Product, subject.id)
        if (
            not product
            or product.tenant_id != ctx.tenant_id
            or product.category_id != ctx.category_id
        ):
            fail("NOT_FOUND", "product_not_found", "型号不存在或不可读。", 404)
        meta.update(label=product.name, revision=product.revision)
        raw = {
            key: getattr(product, f"target_price_{key}")
            for key in ("currency", "basis", "includes_tax", "as_of")
        }
        raw["amount"] = product.target_price
        meta["prices"].append(_price(s, ctx, raw, [], f"{subject.id}:target_price"))
        if doc is None:
            meta["issues"].append({"reason": "definition_unavailable"})
        else:
            if chosen[0] is not None and str(doc["id"]) != chosen[0]:
                fail("VERSION_CONFLICT", "baseline_version_changed", "固定基线身份不一致。")
            meta.update(definition_id=doc["id"], definition_revision=doc["revision"])
            for index, item in enumerate(doc["specs"]):
                refs = [
                    *item.get("source_refs", []),
                    *(
                        {
                            "type": "artifact",
                            "id": ref["artifact_id"],
                            "version": ref["expected_revision"],
                            **{key: ref[key] for key in ("line", "quote") if key in ref},
                        }
                        for ref in item.get("sources", [])
                    ),
                ]
                observations.append((f"{doc['id']}:specs:{index}", "spec", item, refs, subject.id))
    return meta, observations


def _value(raw, value_type):
    values = {key: raw.get(key) for key in ("value", "lower", "upper")}
    values["text_value"] = raw.get("text_value", raw.get("text"))
    try:
        if value_type in {"number", "range"}:
            for field in ("value", "lower", "upper"):
                if values[field] is None:
                    continue
                if type(values[field]) not in (int, str, Decimal):
                    raise ValueError
                values[field] = Decimal(values[field])
                if not values[field].is_finite():
                    raise ValueError
            if not numeric_value_shape(
                value_type, values["value"], values["lower"], values["upper"], None
            ):
                raise ValueError
        else:
            value = values["text_value"] if values["text_value"] is not None else values["value"]
            if value_type == "boolean":
                if type(value) is bool:
                    pass
                elif value in ("true", "false"):
                    value = value == "true"
                else:
                    raise ValueError
                values = {"value": value, "lower": None, "upper": None, "text_value": None}
            elif value_type in {"text", "enum"} and isinstance(value, str):
                values = {"value": None, "lower": None, "upper": None, "text_value": value}
            else:
                raise ValueError
    except (ValueError, InvalidOperation):
        return {key: None for key in values}, ["value_missing_or_invalid"]
    return values, []


def compare(s, ctx, payload, *, before_definition_read=None):
    payload = (
        payload
        if isinstance(payload, SpecCompareInput)
        else SpecCompareInput.model_validate(payload)
    )
    category_scope(s, ctx)
    proposals = {
        subject.id: _proposal(s, ctx, subject.id)
        for subject in payload.subjects
        if subject.type == "proposal"
    }
    subjects, grouped, unmapped, unavailable = [], {}, [], []
    selected = set(payload.parameter_ids)
    parameters = {}
    for subject in payload.subjects:
        meta, rows = _subject(
            s, ctx, subject, proposals, before_definition_read=before_definition_read
        )
        subjects.append(meta)
        if meta["issues"]:
            unavailable.append(
                {"subject": subject.model_dump(mode="json"), "reasons": meta["issues"]}
            )
        for identity, kind, raw, refs, product_id in rows:
            parameter_id, version = raw.get("parameter_id"), raw.get("parameter_version")
            if selected and parameter_id and UUID(str(parameter_id)) not in selected:
                continue
            parameter = None
            reasons = []
            if parameter_id and version:
                key = (UUID(str(parameter_id)), version)
                if key not in parameters:
                    try:
                        parameters[key] = category_service.parameter_version(s, ctx, *key)
                    except DomainError:
                        parameters[key] = None
                parameter = parameters[key]
                if parameter is None:
                    reasons.append("parameter_version_unavailable")
            else:
                reasons.append("unmapped_parameter")
            value_type = raw.get("value_type") or (parameter.value_type if parameter else None)
            if parameter and value_type != parameter.value_type:
                reasons.append("value_type_mismatch")
            availability = raw.get("availability") or (
                "unknown" if raw.get("nature") == "unknown" else "known"
            )
            values, invalid = _value(raw, value_type)
            if availability != "known":
                values = {key: None for key in values}
                reasons.append(availability)
            else:
                reasons.extend(invalid)
            if parameter and value_type == "enum" and values["text_value"] is not None:
                if (
                    parameter.enum_values is not None
                    and values["text_value"] not in parameter.enum_values
                ):
                    reasons.append("enum_value_unmapped")
            sources, source_reasons = _sources(s, ctx, refs, product_id=product_id)
            reasons.extend(source_reasons)
            if source_reasons or meta["issues"]:
                reasons.append("source_unavailable")
                values = {key: None for key in values}
            if not refs and subject.type == "competitor":
                reasons.append("source_missing")
            note = raw.get("condition_note")
            effective_note = note if note else (parameter.standard_condition if parameter else None)
            conditions = raw.get("test_conditions", [])
            if value_type in {"number", "range"}:
                if not raw.get("unit"):
                    reasons.append("unit_missing")
                if not effective_note and not conditions:
                    reasons.append("condition_missing")
            nature = raw.get("nature")
            evidence_kind = {"measured": "observed", "claimed": "claimed"}.get(nature, nature)
            if availability != "known":
                evidence_kind = "unknown"
            elif subject.type == "proposal" and nature == "decided":
                evidence_kind = "target"
            evidence_kind = evidence_kind or "unspecified"
            evidence_label = {
                "observed": "实测",
                "claimed": "宣传",
                "inferred": "推断",
                "unknown": "未知",
                "target": "目标",
                "decided": "决定",
                "computed": "计算",
                "extracted": "原文抽取",
                "unspecified": "性质未标注",
            }.get(evidence_kind, str(evidence_kind))
            vendor_claimed = True if nature == "claimed" else None
            observation = {
                "subject": subject.model_dump(mode="json"),
                "observation_id": identity,
                "kind": kind,
                "key": raw.get("key"),
                "parameter": raw.get("parameter"),
                "parameter_id": str(parameter_id) if parameter_id else None,
                "parameter_version": version,
                "value_type": value_type,
                **values,
                "availability": availability,
                "nature": nature,
                "evidence_kind": evidence_kind,
                "evidence_label": evidence_label,
                "vendor_claimed": vendor_claimed,
                "unit": raw.get("unit"),
                "condition_note": note,
                "condition_source": "observation"
                if note
                else ("parameter_standard" if effective_note else "unspecified"),
                "test_conditions": conditions,
                "tolerance": raw.get("tolerance"),
                "verification_method": raw.get("verification_method", raw.get("method")),
                "acceptance_criterion": raw.get("acceptance_criterion"),
                "modality": raw.get("modality"),
                "exceptions": deepcopy(raw.get("exceptions", [])),
                "applicable_variants": deepcopy(raw.get("applicable_variants", [])),
                "source_refs": sources,
                "comparable": not reasons,
                "reasons": sorted(set(reasons)),
            }
            if not parameter:
                unmapped.append(observation)
                continue
            group_key = (
                str(parameter_id),
                version,
                raw.get("unit"),
                effective_note,
                tuple(conditions),
            )
            group = grouped.setdefault(
                group_key,
                {
                    "parameter_id": str(parameter_id),
                    "parameter_version": version,
                    "parameter": {
                        field: getattr(parameter, field)
                        for field in (
                            "key",
                            "name",
                            "value_type",
                            "direction",
                            "unit",
                            "standard_condition",
                        )
                    },
                    "unit": raw.get("unit"),
                    "condition_note": effective_note,
                    "test_conditions": conditions,
                    "observations": [],
                },
            )
            group["observations"].append(observation)
    groups = list(grouped.values())
    for group in groups:
        rows = group["observations"]
        group.update(
            sample_count=len(rows),
            comparable_count=sum(row["comparable"] for row in rows),
            unknown_count=sum(row["availability"] == "unknown" for row in rows),
        )
        others = [other for other in groups if other["parameter_id"] == group["parameter_id"]]
        group["separation_reasons"] = [
            reason
            for field, reason in (
                ("parameter_version", "parameter_version_differs"),
                ("unit", "unit_differs"),
                ("condition_note", "condition_differs"),
                ("test_conditions", "condition_differs"),
            )
            if any(other[field] != group[field] for other in others)
        ]
        group["separation_reasons"] = sorted(set(group["separation_reasons"]))
    requested_parameters = []
    if selected:
        cursor = None
        while True:
            page = category_reads.parameters(
                s, ctx, parameter_ids=sorted(selected, key=str), cursor=cursor, page_size=200
            )
            requested_parameters.extend(page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                break
    result = _json(
        {
            "engine_version": VERSION,
            "requested_parameters": requested_parameters,
            "subjects": subjects,
            "groups": groups,
            "unmapped": unmapped,
            "unavailable": unavailable,
            "unknown_count": sum(group["unknown_count"] for group in groups)
            + sum(row["availability"] == "unknown" for row in unmapped),
        }
    )
    result["input_digest"] = digest({"request": payload.model_dump(mode="json"), "read": result})
    return result
