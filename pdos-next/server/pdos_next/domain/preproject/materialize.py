"""G0 orchestration through B3 writers, sharing the common command's Session."""

import json
from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from pdos_next.domain.products import definitions
from pdos_next.domain.products.service import create_product, set_g0_targets
from pdos_next.domain.projects.service import create_project
from pdos_next.models import Artifact
from pdos_next.models import ObjectAudience as Audience
from pdos_next.models import UploadedOriginal as Original

from .category_models import KnowledgeEntry
from .models import ProjectOpenItem, ProposalSource


def audience(s, ctx, typ, subject_id, owner_id, people):
    for person in set(people):
        s.execute(
            insert(Audience)
            .values(
                id=uuid4(),
                tenant_id=ctx.tenant_id,
                category_id=ctx.category_id,
                object_type=typ,
                subject_id=subject_id,
                owner_id=owner_id,
                principal_id=person,
            )
            .on_conflict_do_nothing()
        )


def grant_review_sources(s, ctx, row, sub):
    for source in s.scalars(
        select(Artifact)
        .join(
            ProposalSource,
            (ProposalSource.source_id == Artifact.id)
            & (ProposalSource.tenant_id == Artifact.tenant_id),
        )
        .where(ProposalSource.proposal_id == row.id, ProposalSource.source_type == "original")
    ):
        audience(s, ctx, "artifact_versions", source.id, source.owner_id, [sub.reviewer_id])
        if source.original_id:
            original = s.get(Original, source.original_id)
            audience(
                s, ctx, "uploaded_originals", original.id, original.owner_id, [sub.reviewer_id]
            )


def approve(s, ctx, row, sub, decision, *, provenance, baseline=None):
    from .schemas import ItemInput, Reference
    from .service import _version

    doc = sub.frozen_document
    from .derivation import calculation

    compared = (
        calculation(baseline, doc, proposal_id=row.id, revision=sub.revision) if baseline else None
    )
    people = {
        row.owner_id,
        sub.reviewer_id,
        decision.project_owner_id,
        *(UUID(d["owner_id"]) for d in decision.dispositions),
    }
    variant = None
    if decision.created_variant_id:
        from pdos_next.domain.products.variants import create_g0_variant
        from pdos_next.models import Product

        product = s.get(Product, decision.created_product_id)
        variant = create_g0_variant(
            s, ctx, product, decision, owner_id=row.owner_id, visibility=row.effective_visibility
        )
        audience(s, ctx, "product_variants", variant.id, row.owner_id, people)
    else:
        product = create_product(
            s,
            ctx,
            product_id=decision.created_product_id,
            owner_id=row.owner_id,
            name=decision.creation["product_name"],
            purpose=row.brief,
            visibility=row.effective_visibility,
            decision=decision,
            parent_product_id=row.baseline_product_id,
        )
        audience(s, ctx, "products", product.id, row.owner_id, people)
    prices = [
        i["content"].get("target_price")
        for i in doc["items"]
        if i["kind"] == "commercial_target" and i["content"].get("target_price")
    ]
    price = prices[0] if prices else {}
    if price.get("as_of"):
        price = {**price, "as_of": date.fromisoformat(price["as_of"])}
    segments = {}
    for ref in sub.context_refs:
        if ref["type"] == "knowledge":
            entry = s.get(KnowledgeEntry, UUID(ref["id"]))
            if entry and entry.kind == "segment":
                segments[entry.lineage_id] = entry
    if variant is None:
        set_g0_targets(s, ctx, product, decision, price=price, segments=segments.values())
    specs, supplements = [], []
    for item in doc["items"]:
        if item["kind"] != "spec":
            continue
        spec = item["content"]
        specs.append(
            {
                "key": spec["key"],
                "parameter": spec["parameter"],
                "value_type": spec["value_type"],
                "availability": spec["availability"],
                "value": spec.get("value"),
                "lower": spec.get("lower"),
                "upper": spec.get("upper"),
                "text": spec.get("text_value"),
                "unit": spec.get("unit"),
                "tolerance": spec.get("tolerance"),
                "test_conditions": spec.get("test_conditions", []),
                "method": spec.get("verification_method"),
                "acceptance_criterion": spec.get("acceptance_criterion"),
                "nature": spec["nature"],
                "state": "proposed",
                "owner_id": spec.get("owner_id"),
                "reason": spec.get("reason") or "",
            }
        )
        specs[-1].update(
            {
                **{
                    key: spec.get(key)
                    for key in (
                        "parameter_id",
                        "parameter_version",
                        "item_status",
                        "condition_note",
                        "modality",
                    )
                },
                **{key: item.get(key) for key in ("origin", "writer_id", "run_id", "confirmed_by")},
                "exceptions": spec["exceptions"],
                "applicable_variants": spec["applicable_variants"],
                "source_refs": item["source_refs"],
                "receipt_id": decision.receipt_id,
            }
        )
        supplements.append(item)
    references = {
        json.dumps(r, sort_keys=True): r
        for r in doc["source_refs"]
        if r["type"] in {"artifact", "original"}
    }
    from pdos_next.domain.products.models import DefinitionSpecRow

    definition = definitions.create_revision(
        s,
        ctx,
        product,
        owner_id=row.owner_id,
        revision=1,
        definition_id=decision.created_definition_id,
        decision=decision,
        fields={
            "variant_id": variant.id if variant else None,
            "derived_from_definition_id": UUID(baseline["id"]) if baseline else None,
            "derived_from_definition_revision": baseline["revision"] if baseline else None,
            "title": decision.creation["product_name"],
            "purpose": row.brief,
            "visibility": row.effective_visibility,
            "use_cases": [],
            "requirements": [],
            "constraints": [],
            "unknowns": [],
            "exclusions": [],
            "change_reason": decision.rationale,
        },
        spec_table=DefinitionSpecRow.__table__,
        specs=specs,
        sources=[
            {
                "artifact_id": UUID(ref["id"]),
                "source_revision": ref["version"],
                "line": ref["line"],
                "quote": ref["quote"],
                "spec_keys": [
                    i["content"]["key"]
                    for i in supplements
                    if any(
                        Reference.model_validate(source) == Reference.model_validate(ref)
                        for source in i["source_refs"]
                    )
                ],
            }
            for ref in references.values()
        ],
    )
    audience(s, ctx, "definition_revisions", definition.id, row.owner_id, people)
    # Children are assembled while unsealed. The parent lock in the INSERT guards
    # makes sealing and concurrent additions mutually exclusive.
    s.execute(
        text(
            "UPDATE definition_revisions SET sealed=true,source_proposal_id=:proposal,"
            "source_submission_id=:submission,source_proposal_revision=:revision,"
            "g0_decision_id=:decision WHERE id=:id AND tenant_id=:tenant"
        ),
        {
            "proposal": row.id,
            "submission": sub.id,
            "revision": sub.revision,
            "decision": decision.id,
            "id": definition.id,
            "tenant": ctx.tenant_id,
        },
    )
    if variant:
        from pdos_next.domain.products.variants import bind_g0_definition

        variant_revision = bind_g0_definition(
            s, ctx, variant, definition, baseline, decision, compared
        )
        audience(s, ctx, "variant_revisions", variant_revision.id, row.owner_id, people)
    project = create_project(
        s,
        ctx,
        product,
        project_id=decision.created_project_id,
        owner_id=decision.project_owner_id,
        name=decision.creation["project_name"],
        purpose=row.brief,
        scope=row.brief,
        visibility=row.effective_visibility,
        definition_id=definition.id,
        definition_revision=1,
        decision=decision,
        variant_id=variant.id if variant else None,
    )
    audience(s, ctx, "projects", project.id, project.owner_id, people)
    by_id = {i["item_id"]: i for i in doc["items"]}
    for disp in decision.dispositions:
        item = by_id[disp["subject_id"]]
        question = disp["subject_type"] == "question"
        s.add(
            ProjectOpenItem(
                tenant_id=ctx.tenant_id,
                category_id=ctx.category_id,
                product_id=product.id,
                project_id=project.id,
                kind=disp["kind"],
                title=item["content"]["question" if question else "parameter"],
                note=disp["note"],
                owner_id=UUID(disp["owner_id"]),
                due_date=date.fromisoformat(disp["due_date"]),
                status="assigned" if disp["kind"] == "task" else "open",
                g0_decision_id=decision.id,
                source_question_id=UUID(disp["subject_id"]) if question else None,
                source_spec_item_id=None if question else UUID(disp["subject_id"]),
            )
        )
        if question:
            input_item = ItemInput(
                item_id=UUID(item["item_id"]),
                kind="question",
                content=item["content"],
                source_refs=[Reference.model_validate(ref) for ref in item["source_refs"]],
            )
            input_item.content = {**input_item.content, "status": "carried"}
            # Carrying is a human decision about state; it does not rewrite the
            # origin of the question's text or impersonate its original writer.
            carry_provenance = provenance
            if item["origin"] == "ai_draft":
                carry_provenance = {
                    "origin": item["origin"],
                    "writer_id": UUID(item["writer_id"]),
                    "run_id": UUID(item["run_id"]),
                    "confirmed_by": ctx.requester_id,
                    "prepared_candidate_id": None,
                }
            _version(s, ctx, row, input_item, decision.receipt_id, provenance=carry_provenance)
    s.flush()
