"""Actual category/model and explicitly Run-bound sources; no root raw-text projection."""

from functools import partial
from types import SimpleNamespace
from typing import Literal
from uuid import UUID

from pydantic import Field
from sqlalchemy import select, text

from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.models import Category
from pdos_next.schema_base import StrictModel
from pdos_next.service import require_access, source_for

from .extract_pages import located_page
from .extract_schemas import ArtifactReadInput
from .extract_sources import seal_for


class EmptyInput(StrictModel):
    pass


class SearchInput(StrictModel):
    query: str = ""


class PageInput(StrictModel):
    cursor: str | None = None
    page_size: int = Field(default=50, ge=1, le=200)


class KnowledgeInput(PageInput):
    kind: (
        Literal["boundary", "segment", "competitor", "voice", "regulation", "research_question"]
        | None
    ) = None
    status: Literal["active", "withdrawn"] | None = "active"
    origin: Literal["human", "ai_draft", "imported"] | None = None
    region: str | None = None
    include_history: bool = False


class ParameterInput(PageInput):
    parameter_ids: list[UUID] | None = None
    include_history: bool = False


class CompetitorInput(PageInput):
    parameter_ids: list[UUID] | None = None
    brand: str | None = None
    nature: Literal["measured", "claimed", "inferred", "unknown"] | None = None


BaselineArea = Literal["specification", "bom", "certification", "tooling", "platform"]
DiffArea = Literal["specification", "bom", "certification", "tooling"]


class BaselineInput(StrictModel):
    product_id: UUID | None = None
    variant_id: UUID | None = None
    definition_revision: int | None = Field(default=None, gt=0)
    areas: list[BaselineArea] = Field(
        default_factory=lambda: ["specification", "bom", "certification", "tooling", "platform"]
    )


class FixedBaseline(StrictModel):
    product_id: UUID
    definition_revision: int = Field(gt=0)
    definition_id: UUID | None = None


class ProposedProposal(StrictModel):
    proposal_id: UUID
    revision: int = Field(gt=0)


class DerivationDiffInput(StrictModel):
    """This port supports actual Run-bound proposals; other forms remain unavailable."""

    baseline: FixedBaseline
    proposed: ProposedProposal
    areas: list[DiffArea] = Field(
        default_factory=lambda: ["specification", "bom", "certification", "tooling"]
    )


SCHEMAS = {
    "category.read": EmptyInput,
    "category.list": EmptyInput,
    "product.baseline.read": BaselineInput,
    "calc.derivation_diff": DerivationDiffInput,
    "evidence.search": SearchInput,
    "evidence.artifact.read": ArtifactReadInput,
    "category.knowledge.list": KnowledgeInput,
    "category.competitors.list": CompetitorInput,
    "category.parameters.list": ParameterInput,
}


def _outbound_unavailable():
    from pdos_next.domain.preproject.access import fail

    # RLS readability alone is not authorization to introduce private customer
    # material into a model Run. No complete outbound-source binding exists yet.
    fail(
        "FORBIDDEN_SCOPE",
        "private_material_context_binding_required",
        "此工具尚未接入私有资料的完整运行出站绑定，请在页面读取并核对。",
        403,
    )


def _public_definition(session, ctx, definition):
    private = session.scalar(
        text("SELECT m3_definition_root_private(:tenant,:category,:definition,:version)"),
        {
            "tenant": ctx.tenant_id,
            "category": ctx.category_id,
            "definition": UUID(str(definition["id"])),
            "version": definition["revision"],
        },
    )
    if private is not False:
        _outbound_unavailable()


def _public_references(session, ctx, refs, seen=None):
    """Check real source metadata without returning source bodies or taking locks."""
    from pdos_next.agent_kernel.models import PublicWebSnapshot
    from pdos_next.domain.preproject.category_models import KnowledgeEntry
    from pdos_next.domain.preproject.claim_access import resolve, source_privacy
    from pdos_next.domain.preproject.schemas import Reference
    from pdos_next.domain.products.models import DefinitionRevision

    seen = set() if seen is None else seen
    for raw in refs:
        ref = raw if isinstance(raw, Reference) else Reference.model_validate(raw)
        key = (ref.type, ref.id, ref.version)
        if key in seen:
            continue
        seen.add(key)
        if ref.type in {"human", "parameter"}:
            continue  # Frozen public object facts; no new source body is projected.
        if ref.type == "definition":
            row = session.get(DefinitionRevision, ref.id)
            if not row or row.category_id != ctx.category_id or row.revision != ref.version:
                _outbound_unavailable()
            _public_definition(session, ctx, {"id": row.id, "revision": row.revision})
        elif ref.type == "knowledge":
            row = session.get(KnowledgeEntry, ref.id)
            if not row or row.category_id != ctx.category_id or row.version != ref.version:
                _outbound_unavailable()
            _public_references(session, ctx, row.source_refs, seen)
        elif ref.type == "claim":
            row = resolve(session, ctx, ref.id, ref.version, approved=True)
            if row.privacy == "private" or row.visibility != "category":
                _outbound_unavailable()
            if source_privacy(session, ctx, row) != "shared":
                _outbound_unavailable()
        elif ref.type in {"artifact", "original"}:
            source_for(session, ctx, None, ref.id, ref.version)
            root = SimpleNamespace(source_kind="artifact", artifact_id=ref.id)
            if source_privacy(session, ctx, root) != "shared":
                _outbound_unavailable()
        elif ref.type == "snapshot":
            row = session.get(PublicWebSnapshot, ref.id)
            if (
                not row
                or row.category_id != ctx.category_id
                or ref.version != 1
                or row.visibility != "category"
                or row.status not in {"ok", "partial"}
            ):
                _outbound_unavailable()
        else:
            _outbound_unavailable()


def _public_baseline_bom(session, ctx, product_id, result, *, objects=None):
    """Authorize the persisted BOM closure separately from its public definition.

    Ordinary RLS grants local reading, not model outbound consent. Resolve actual
    configurations, BOM lines, parts and their source roots in the same snapshot;
    projected visibility labels never supply this authorization.
    A Run-bound checker may authorize exact private targets and already-bound sources.
    """
    from pdos_next.domain.configurations.models import (
        BomLine,
        BomRevision,
        EngineeringConfiguration,
        PartIdentity,
    )
    from pdos_next.domain.preproject.claim_access import source_privacy

    checked_objects, checked_sources = set(), set()
    definition = result["definition"]
    private_objects = bool(
        objects is not None
        and objects.run.private_context
        and definition
        and (product_id, UUID(definition["variant_id"]) if definition.get("variant_id") else None)
        in objects.targets
    )

    def sources(value):
        if isinstance(value, list):
            for item in value:
                sources(item)
        elif isinstance(value, dict):
            if "artifact_id" in value:
                identity = UUID(str(value["artifact_id"]))
                version = value["expected_revision"]
                if (identity, version) not in checked_sources:
                    if objects is not None:
                        from pdos_next.domain.preproject.schemas import Reference

                        objects.refs([Reference(type="artifact", id=identity, version=version)])
                    source_for(session, ctx, product_id, identity, version)
                    root = SimpleNamespace(source_kind="artifact", artifact_id=identity)
                    if objects is None and source_privacy(session, ctx, root) != "shared":
                        _outbound_unavailable()
                    checked_sources.add((identity, version))
            for nested in value.values():
                sources(nested)

    def public_row(model, identity):
        row = session.get(model, identity)
        if (
            not row
            or row.tenant_id != ctx.tenant_id
            or row.category_id != ctx.category_id
            or row.product_id != product_id
            or row.visibility != "category"
            and not private_objects
        ):
            _outbound_unavailable()
        if (model, identity) not in checked_objects:
            sources(row.sources)
            sources(row.required_source_read_set)
            if model is PartIdentity:
                sources(row.external_design_refs)
            elif model is EngineeringConfiguration:
                sources(row.design_versions)
            checked_objects.add((model, identity))
        return row

    for item in result["blocks"].get("bom", {}).get("items", []):
        config = public_row(EngineeringConfiguration, UUID(item["configuration"]["id"]))
        definition = result["definition"]
        if (
            definition is None
            or str(config.definition_id) != str(definition["id"])
            or config.definition_revision != definition["revision"]
            or str(config.bom_id) != str(item["bom_id"])
            or config.bom_revision != item["bom_revision"]
        ):
            _outbound_unavailable()
        bom = public_row(BomRevision, config.bom_id)
        if bom.revision != config.bom_revision:
            _outbound_unavailable()
        for line in session.scalars(
            select(BomLine).where(
                BomLine.tenant_id == ctx.tenant_id,
                BomLine.category_id == ctx.category_id,
                BomLine.product_id == product_id,
                BomLine.bom_id == bom.id,
            )
        ):
            part = public_row(PartIdentity, line.part_id)
            if part.revision != line.part_revision:
                _outbound_unavailable()


class DomainReads:
    def __init__(self, store, commands):
        self.store, self.commands = store, commands

    def call(self, scope, arguments, *, name):
        payload = SCHEMAS[name].model_validate(arguments)
        if scope.category_id is None:
            raise DomainError("FORBIDDEN_SCOPE", "业务读取须绑定当前品类。", 403)
        if name in {"product.baseline.read", "calc.derivation_diff"}:
            return self._baseline_call(scope, payload, name=name)
        with self.store.transaction(scope) as (session, run):
            ctx = self.commands.context(scope)
            if name in {
                "category.knowledge.list",
                "category.competitors.list",
                "category.parameters.list",
            }:
                from pdos_next.domain.preproject import category_reads

                values = payload.model_dump()
                if name == "category.parameters.list":
                    return category_reads.parameters(session, ctx, **values)
                if name == "category.competitors.list":
                    return category_reads.competitors(session, ctx, **values)
                return category_reads.knowledge(session, ctx, **values)
            if name in {"category.list", "category.read"}:
                require_access(session, ctx, scope.product_id)
                category = session.get(Category, scope.category_id)
                value = {
                    "id": str(category.id),
                    "key": category.key,
                    "name": category.name,
                    "purpose": category.purpose,
                    "revision": category.revision,
                }
                return [value] if name == "category.list" else value
            reads = {UUID(ref["artifact_id"]): ref for ref in run.read_sources}
            if name == "evidence.search":
                values = []
                # Search the complete explicit read set, returning only metadata to the root.
                for identity, ref in reads.items():
                    source = source_for(
                        session, ctx, scope.product_id, identity, ref["expected_revision"]
                    )
                    if payload.query.casefold() in source.title.casefold():
                        values.append(
                            {
                                "artifact_id": str(source.id),
                                "title": source.title,
                                "revision": source.revision,
                                "content_hash": source.content_hash,
                            }
                        )
                return values
            if (
                scope.isolation != "extract"
                or payload.artifact_version_id not in scope.artifact_ids
            ):
                raise DomainError("FORBIDDEN_SCOPE", "原文须在绑定来源的只读提取子任务读取。", 403)
            ref = reads.get(payload.artifact_version_id)
            if ref is None:
                raise DomainError("FORBIDDEN_SCOPE", "本次运行未绑定此原文。", 403)
            seal, _ = seal_for(
                session,
                ctx,
                scope.product_id,
                payload.artifact_version_id,
                ref["expected_revision"],
            )
            return located_page(seal, arguments)

    def _baseline_call(self, scope, payload, *, name, session=None):
        from contextlib import nullcontext

        from pdos_next.domain.preproject import baseline, derivation
        from pdos_next.domain.preproject.access import fail, proposal
        from pdos_next.domain.preproject.service import _all_refs_from_document
        from pdos_next.domain.preproject.views import document
        from pdos_next.service import digest

        from .execution import check_run_binding
        from .models import AgentRun

        transaction = (
            nullcontext(session)
            if session is not None
            else tenant_session(
                self.store.engine,
                scope.tenant_id,
                actor_id=scope.writer_id,
                requester_id=scope.requester_id,
                category_id=scope.category_id,
                read_snapshot=True,
            )
        )
        with transaction as session:
            run = session.get(AgentRun, scope.run_id)
            check_run_binding(run, scope, for_write=False)
            self.store.authority(session, scope)
            ctx = self.commands.context(scope)
            from .proposal_context import KEY

            objects = None
            if KEY in getattr(run, "versions", {}):
                from .m3_spec_compare import _objects

                objects = _objects(session, ctx, scope, run)
            product_id = (
                payload.product_id or scope.product_id
                if name == "product.baseline.read"
                else payload.baseline.product_id
            )
            if product_id is None:
                fail(
                    "MISSING_REQUIRED_EVIDENCE", "baseline_product_required", "请选择实际基线型号。"
                )
            if scope.product_id is not None and product_id != scope.product_id:
                fail("FORBIDDEN_SCOPE", "product_run_mismatch", "型号选择不属于本次运行。", 403)
            product = require_access(session, ctx, product_id)
            if objects is not None:
                objects.target(
                    product_id, payload.variant_id if name == "product.baseline.read" else None
                )
            elif product.visibility != "category":
                _outbound_unavailable()
            if name == "product.baseline.read":
                result = baseline.read_baseline(
                    session,
                    ctx,
                    product_id,
                    variant_id=payload.variant_id,
                    definition_revision=payload.definition_revision,
                    **(
                        {
                            "before_definition_read": objects.definition_head,
                            "sources_current": objects.baseline_sources_current,
                            "block_areas": payload.areas,
                        }
                        if objects
                        else {}
                    ),
                )
                if result["definition"] is not None:
                    if objects is not None:
                        from .m3_object_reads import _references

                        objects.refs(_references(result))
                        objects.parameters(result)
                    else:
                        _public_definition(session, ctx, result["definition"])
                if "bom" in payload.areas:
                    if objects is not None:
                        _public_baseline_bom(session, ctx, product_id, result, objects=objects)
                    else:
                        _public_baseline_bom(session, ctx, product_id, result)
                return {
                    **result,
                    "definition": result["definition"]
                    if "specification" in payload.areas
                    else None,
                    "blocks": {k: v for k, v in result["blocks"].items() if k in payload.areas},
                    "unavailable_blocks": [
                        k for k in result["unavailable_blocks"] if k in payload.areas
                    ],
                    "areas": payload.areas,
                }
            if run.proposal_id is None or payload.proposed.proposal_id != run.proposal_id:
                fail(
                    "FORBIDDEN_SCOPE",
                    "proposal_run_mismatch",
                    "比较须使用本次运行绑定的实际提案。",
                    403,
                )
            row = proposal(session, ctx, run.proposal_id)
            if row.revision != payload.proposed.revision:
                fail(
                    "VERSION_CONFLICT",
                    "proposal_revision_moved",
                    "提案版本已变化，请读取当前版本。",
                )
            if objects is None and (
                row.effective_visibility != "category"
                or row.private_source_count
                or row.customer_identities
            ):
                _outbound_unavailable()
            if (
                row.baseline_product_id != product_id
                or row.baseline_definition_revision != payload.baseline.definition_revision
                or (
                    payload.baseline.definition_id is not None
                    and row.baseline_definition_id != payload.baseline.definition_id
                )
            ):
                fail("VERSION_CONFLICT", "baseline_version_changed", "比较须使用提案固定的父版。")
            doc = objects.proposal(row.id) if objects is not None else document(session, row)
            parent = derivation.validate_baseline(session, ctx, row, doc)
            if parent is None:
                fail("VALIDATION_FAILED", "not_a_derivative", "本提案没有固定派生基线。", 422)
            refs = [
                *_all_refs_from_document(doc),
                *(
                    ref
                    for item in doc["items"]
                    if item["kind"] == "difference"
                    for ref in item["content"].get("sources", [])
                ),
            ]
            if objects is not None:
                objects.definition(UUID(str(parent["id"])), parent["revision"])
                objects.refs(refs)
            else:
                _public_definition(session, ctx, parent)
                _public_references(session, ctx, refs)
            result = derivation.calculation(parent, doc, proposal_id=row.id, revision=row.revision)
            selected = "specification" in payload.areas
            return {
                **result,
                "derivation_request_digest": result["request_digest"],
                "request_digest": digest(
                    {
                        "inputs": payload.model_dump(mode="json"),
                        "derivation": result["request_digest"],
                    }
                ),
                "engine": "products.variants.compare_snapshots",
                "differences": [
                    {"area": "specification", **item}
                    for item in result["differences"]
                    if selected and item["path"].startswith("specs/")
                ],
                "difference_traces": [
                    item
                    for item in result["difference_traces"]
                    if item["content"].get("area") in payload.areas
                ],
                "areas": payload.areas,
                "unavailable_blocks": [area for area in payload.areas if area != "specification"],
                "blocks": {
                    area: {
                        "status": "unknown",
                        "items": [],
                        "reason": "definition_binding_unavailable",
                    }
                    for area in payload.areas
                    if area != "specification"
                },
            }

    def handlers(self):
        return {name: partial(self.call, name=name) for name in SCHEMAS}
