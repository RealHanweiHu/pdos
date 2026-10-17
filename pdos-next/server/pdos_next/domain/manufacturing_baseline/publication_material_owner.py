"""Read actual fixed publication content; never attest publication or readiness.

The opaque handle belongs to one owner, caller and active transaction. Its DTO
is only an output projection: a consumer must refresh through this owner before
using it. Current publication, named T2, asset acceptance and manufacturing
release remain separate owners' responsibilities.
"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from uuid import UUID
from weakref import WeakKeyDictionary, ref

from sqlalchemy import select

from pdos_next.database import require_context
from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow, _uow
from pdos_next.domain.capa_effectiveness.facts import json_value
from pdos_next.domain.configurations import service as configurations
from pdos_next.domain.configurations.models import EngineeringConfiguration, ProcessRevision
from pdos_next.domain.preproject.baseline import validate_sources
from pdos_next.domain.projects import service as projects
from pdos_next.models import Product, now
from pdos_next.schemas.verification.contracts import Scope, SourceRef
from pdos_next.service import Context, digest, require_access

from . import publication_rules, service
from .publication_schemas import PublicationMaterial, PublishPayload
from .rules import require
from .schemas import BaselinePayload, PreparationView, ProcessRef, RequiredRead, Source, sources_of


@dataclass(frozen=True, eq=False)
class PublicationMaterialRead:
    material: PublicationMaterial
    source_basis: dict
    sources: tuple[Source, ...]
    required_source_read_set: tuple[RequiredRead, ...]
    checked_at: datetime


def _values(row, fields):
    return {name: deepcopy(getattr(row, name)) for name in fields}


def _fixed_preparation(row, view):
    return {
        "ref": {"id": str(view.id), "revision": view.revision, "kind": view.kind},
        "receipt_id": str(view.receipt_id),
        "body_sha256": row.body_sha256,
        "source_basis": deepcopy(row.source_basis),
        "shared_proof_id": str(row.shared_proof_id),
        "material_sha256": row.material_sha256,
        "read_set_sha256": row.read_set_sha256,
        "authority_snapshot": deepcopy(row.authority_snapshot),
    }


class ActualPublicationMaterialOwner:
    def __init__(self, engine):
        self.engine = engine
        self._reads = WeakKeyDictionary()

    def _runtime(self, s):
        require(s.get_bind() is self.engine, "FORBIDDEN_SCOPE", "材料owner与当前存储不一致。", 403)
        return (
            service._runtime(s),
            id(service.get_preparation),
            id(projects._project),
            id(configurations.get_process),
            id(service.evidence._evidence),
            id(validate_sources),
        )

    def _collect(self, s, ctx, pid, payload):
        require_context(s, ctx)
        configurations._human(s, ctx, pid)
        products = list(
            s.scalars(
                select(Product)
                .where(Product.tenant_id == ctx.tenant_id, Product.id == pid)
                .limit(2)
                .execution_options(populate_existing=True, autoflush=False)
            )
        )
        require(len(products) == 1, "FORBIDDEN_SCOPE", "当前型号不可读取。", 403)
        product = products[0]
        require(
            type(product.revision) is int
            and product.revision > 0
            and isinstance(product.category_id, UUID)
            and (ctx.category_id is None or product.category_id == ctx.category_id),
            "FORBIDDEN_SCOPE",
            "型号与当前品类范围不一致。",
            403,
        )
        product_basis = _values(
            product, ("id", "tenant_id", "category_id", "revision", "visibility")
        )
        baseline_row, raw = service.get_preparation(s, ctx, pid, payload.baseline)
        baseline = PreparationView.model_validate(raw)
        require(
            baseline.kind == "manufacturing_baseline"
            and baseline.id == payload.baseline.id
            and baseline.revision == payload.baseline.revision
            and baseline.project_id == payload.project_id
            and baseline.visibility == payload.visibility,
            "FORBIDDEN_SCOPE",
            "发布须绑定实际基线、项目与原受众。",
            403,
        )
        baseline_basis = _fixed_preparation(baseline_row, baseline)
        project, link, definition = projects._project(s, ctx, pid, baseline.project_id)
        require(
            project.id == payload.project_id
            and project.tenant_id == ctx.tenant_id
            and project.product_id == pid
            and project.purpose == baseline.purpose == payload.purpose,
            "FORBIDDEN_SCOPE",
            "发布用途须绑定当前真实项目与固定基线。",
            403,
        )
        validate_sources(s, ctx, definition)
        definition_reads = service._definition_reads(definition)
        project_basis = _values(
            project,
            (
                "id",
                "tenant_id",
                "product_id",
                "owner_id",
                "visibility",
                "status",
                "revision",
                "scope",
                "purpose",
            ),
        )
        link_basis = _values(link, ("definition_id", "definition_revision", "scope", "variant_id"))
        definition_basis = deepcopy(definition)
        process_row, process = configurations.get_process(s, ctx, pid, baseline.process.id)
        process = deepcopy(process)
        engineering = configurations._row(
            s, ctx, pid, EngineeringConfiguration, process_row.engineering_configuration_id
        )
        require(
            process_row.revision == baseline.process.revision
            and process.get("id") == str(baseline.process.id)
            and process.get("revision") == baseline.process.revision
            and engineering.revision == process_row.engineering_revision
            and engineering.definition_id == link.definition_id
            and engineering.definition_revision == link.definition_revision,
            "SOURCE_STALE",
            "固定制造配置与本项目实际工程/定义版本不一致。",
        )
        require(
            payload.visibility == "private"
            or all(row.visibility != "private" for row in (project, process_row, engineering))
            and definition["visibility"] != "private",
            "FORBIDDEN_SCOPE",
            "私人项目或配置不能扩大为共享发布。",
            403,
        )
        engineering_basis = _values(
            engineering,
            (
                "id",
                "revision",
                "definition_id",
                "definition_revision",
                "bom_id",
                "bom_revision",
                "visibility",
                "required_source_read_set",
            ),
        )
        latest = s.scalar(
            select(ProcessRevision)
            .where(
                ProcessRevision.tenant_id == ctx.tenant_id,
                ProcessRevision.product_id == pid,
                ProcessRevision.series_id == process_row.series_id,
            )
            .order_by(ProcessRevision.revision.desc())
            .limit(1)
            .execution_options(populate_existing=True, autoflush=False)
        )
        require(latest is not None, "SOURCE_STALE", "固定制造配置系列不可读取。")
        current_process = ProcessRef(id=latest.id, revision=latest.revision)
        declaration = BaselinePayload.model_validate(baseline.body.get("input"))
        documents, document_basis = [], []
        groups = [
            baseline.required_source_read_set,
            process.get("required_source_read_set", ()),
            engineering_basis["required_source_read_set"],
            definition_reads,
        ]
        for operation in declaration.operations:
            for kind in ("work_instruction", "control_plan"):
                selected = getattr(operation, kind)
                if selected is None:
                    continue
                row, raw = service.get_preparation(s, ctx, pid, selected)
                view = PreparationView.model_validate(raw)
                require(
                    view.id == selected.id
                    and view.revision == selected.revision
                    and view.kind == kind
                    and view.operation_key == operation.operation_key
                    and view.project_id == baseline.project_id
                    and view.process == baseline.process
                    and view.purpose == baseline.purpose
                    and not (baseline.visibility != "private" and view.visibility == "private"),
                    "FORBIDDEN_SCOPE",
                    "工序固定资料不能替换项目、用途、工序或受众。",
                    403,
                )
                documents.append(view)
                document_basis.append(_fixed_preparation(row, view))
                groups.append(view.required_source_read_set)
        definition_sources = tuple(
            Source.model_validate({key: value[key] for key in Source.model_fields})
            for value in definition["sources"]
        )
        additional = tuple(dict.fromkeys((*sources_of(payload), *definition_sources)))
        sources = tuple(
            dict.fromkeys(
                (
                    *additional,
                    *baseline.sources,
                    *(Source.model_validate(value) for value in process.get("sources", ())),
                    *(source for view in documents for source in view.sources),
                )
            )
        )
        groups.append(
            tuple(
                RequiredRead(artifact_id=v.artifact_id, expected_revision=v.expected_revision)
                for v in sources
            )
        )
        reads = publication_rules.canonical_reads(groups)
        raw_reads = [value.model_dump(mode="json") for value in reads]
        # Check every declared whole line as well as every upstream read. The
        # source owner resolves native registration/original bytes and ACL; a
        # saved "current" label is never evidence for this new consumption.
        refs = tuple(
            SourceRef(
                kind="artifact",
                id=v.artifact_id,
                revision=v.expected_revision,
                position=f"line:{v.line};quote_sha256:{sha256(v.quote.encode()).hexdigest()}",
            )
            for v in sources
        )
        artifacts, private, verified = service.evidence._evidence(
            s, ctx, pid, raw_reads, refs, io=True
        )
        require(
            not private or payload.visibility == "private",
            "FORBIDDEN_SCOPE",
            "私人来源不能扩大为共享发布。",
            403,
        )
        require(
            {(str(v.artifact_id), v.expected_revision) for v in reads}
            == {(str(key), value.get("revision")) for key, value in artifacts.items()}
            and {service.evidence.digest(value) for value in refs} <= set(verified),
            "MISSING_REQUIRED_EVIDENCE",
            "实际原文核验未覆盖完整固定来源与行。",
        )
        material = PublicationMaterial(
            scope=Scope(tenant_id=ctx.tenant_id, product_id=pid, project_id=project.id),
            category_id=product.category_id,
            product_revision=product.revision,
            baseline=baseline,
            process_snapshot=process,
            current_process=current_process,
            documents=tuple(documents),
            additional_sources=additional,
            required_source_read_set=reads,
        )
        basis = {
            "artifact_sources": [
                {"id": str(key), **deepcopy(value), "status": "active"}
                for key, value in sorted(artifacts.items())
            ],
            "owners": {
                "product": product_basis,
                "project": project_basis,
                "project_link": link_basis,
                "definition": definition_basis,
                "baseline": baseline_basis,
                "engineering": engineering_basis,
                "process": deepcopy(process),
                "documents": document_basis,
            },
            "verified_sources": sorted(verified),
        }
        require_access(s, ctx, pid)
        return material, json_value(basis), sources

    def read(self, s, ctx, pid, payload):
        require(
            isinstance(ctx, Context)
            and ctx.actor_id == ctx.requester_id
            and ctx.run_id is None
            and isinstance(pid, UUID),
            "NAMED_DECISION_REQUIRED",
            "材料须由当前普通具名caller读取。",
            403,
        )
        payload = PublishPayload.model_validate(payload)
        uow, caller, runtime = _uow(s), digest(vars(ctx)), self._runtime(s)
        with service._fresh_selects(s):
            first = self._collect(s, ctx, pid, payload)
            latest = self._collect(s, ctx, pid, payload)
        require(first == latest, "SOURCE_STALE", "完整读取期间固定资料、范围或来源已改变。")
        _same_uow(s, uow, ctx, caller)
        require(runtime == self._runtime(s), "SOURCE_STALE", "实际材料owner在读取期间发生变化。")
        material, basis, sources = latest
        value = PublicationMaterialRead(
            material, deepcopy(basis), sources, material.required_source_read_set, now()
        )
        self._reads[value] = (
            ref(s),
            uow,
            caller,
            pid,
            publication_rules.semantic(payload),
            material.model_dump(mode="json"),
            deepcopy(basis),
            sources,
            value.checked_at,
            runtime,
        )
        return value

    def refresh(self, s, ctx, pid, payload, previous):
        saved = self._reads.get(previous) if type(previous) is PublicationMaterialRead else None
        require(saved is not None, "SOURCE_STALE", "须重新核对本owner实际读取的原封存对象。")
        session, uow, caller, old_pid, semantic, material, basis, sources, checked_at, runtime = (
            saved
        )
        _same_uow(s, uow, ctx, caller)
        require(
            session() is s
            and old_pid == pid
            and runtime == self._runtime(s)
            and publication_rules.semantic(PublishPayload.model_validate(payload)) == semantic
            and previous.material.model_dump(mode="json") == material
            and previous.source_basis == basis
            and previous.sources == sources
            and previous.required_source_read_set == previous.material.required_source_read_set
            and previous.checked_at == checked_at,
            "SOURCE_STALE",
            "原封存范围、实质输入、材料或实际调用事务发生变化。",
        )
        latest = self.read(s, ctx, pid, payload)
        require(
            latest.material.model_dump(mode="json") == material
            and latest.source_basis == basis
            and latest.sources == sources,
            "SOURCE_STALE",
            "当前实际材料或来源与原封存读取不一致。",
        )
        return latest
