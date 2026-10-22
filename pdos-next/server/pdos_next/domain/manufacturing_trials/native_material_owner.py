"""Actual fixed Pilot preparation inputs, with no start or resource grant.

A publication reference resolves the formal Publication ledger, never its T1
draft. Missing resource owners remain named gaps. The opaque read is consumed
only by refreshing it under the same real caller/Session/transaction.
"""

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha256
from typing import Literal
from uuid import UUID
from weakref import WeakKeyDictionary, ref

from pydantic import JsonValue
from pydantic_core import to_jsonable_python
from sqlalchemy import select
from sqlalchemy.types import JSON

from pdos_next.contracts import SourceRead
from pdos_next.database import require_context
from pdos_next.domain.build_execution import service as execution
from pdos_next.domain.build_execution.models import ActualConfiguration, BuildLot, SampleUnit
from pdos_next.domain.build_operational_facts.models import (
    BuildOperationalCurrent,
    BuildOperationalFact,
    OperationalAsset,
)
from pdos_next.domain.builds import service as builds
from pdos_next.domain.builds.models import Build
from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow, _uow
from pdos_next.domain.change_execution import service as evidence
from pdos_next.domain.configurations import service as configurations
from pdos_next.domain.configurations.models import EngineeringConfiguration, ProcessRevision
from pdos_next.domain.manufacturing_baseline import publication_service as publications
from pdos_next.domain.manufacturing_baseline import service as preparations
from pdos_next.domain.manufacturing_baseline.publication_models import (
    ManufacturingBaselinePublication,
    ManufacturingBaselinePublicationCurrent,
)
from pdos_next.domain.manufacturing_baseline.publication_schemas import Applicability
from pdos_next.domain.manufacturing_baseline.schemas import Source
from pdos_next.domain.preproject.baseline import validate_sources
from pdos_next.domain.products.models import DefinitionRevision
from pdos_next.domain.projects import service as projects
from pdos_next.domain.projects.models import Project, ProjectProductLink
from pdos_next.domain.quality_execution.models import QualityIssueCurrent, QualityIssueVersion
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, OriginalSecurity, Product, UploadedOriginal, now
from pdos_next.request_proof import snapshot_mappings
from pdos_next.schemas.manufacturing_trials.contracts import DTO, Gap, LotBasis, PilotCreate
from pdos_next.schemas.verification.contracts import Scope, SourceRef
from pdos_next.service import Context, digest, require_access


class NativePilotMaterial(DTO):
    scope: Scope
    category_id: UUID
    product_revision: int
    purpose: str
    basis: LotBasis
    build: dict[str, JsonValue]
    lot: dict[str, JsonValue]
    actual_configuration: dict[str, JsonValue]
    engineering_configuration: dict[str, JsonValue]
    process: dict[str, JsonValue]
    publication: dict[str, JsonValue] | None
    gaps: tuple[Gap, ...]
    qualification: Literal["unknown"] = "unknown"
    start_authorized: Literal[False] = False
    manufacturing_release: None = None


@dataclass(frozen=True, eq=False)
class PilotMaterialRead:
    material: NativePilotMaterial
    source_basis: dict
    sources: tuple[SourceRef, ...]
    required_source_read_set: tuple[SourceRead, ...]
    checked_at: datetime


def _require(test, detail, code="SOURCE_STALE", status=409):
    if not test:
        raise DomainError(code, detail, status)


def _values(row, fields):
    return to_jsonable_python({key: deepcopy(getattr(row, key)) for key in fields})


# Only direct persisted metadata is read here. Fixed content is protected by its
# immutable version/hash, not by replaying the owner's upstream proof. This is
# also the persisted T1 watermark format; it is not a client qualification DTO.
_MODELS = {
    model.__tablename__: model
    for model in (
        Product,
        Build,
        Project,
        ProjectProductLink,
        DefinitionRevision,
        ActualConfiguration,
        BuildLot,
        EngineeringConfiguration,
        ProcessRevision,
        ManufacturingBaselinePublication,
        ManufacturingBaselinePublicationCurrent,
        Artifact,
        UploadedOriginal,
        OriginalSecurity,
        SampleUnit,
        QualityIssueVersion,
        QualityIssueCurrent,
        BuildOperationalFact,
        BuildOperationalCurrent,
        OperationalAsset,
    )
}


def _fields(model):
    return tuple(
        column.key
        for column in model.__table__.columns
        if not isinstance(column.type, JSON) and column.key not in {"lifecycle_epoch", "content"}
    )


def _mark(row):
    return {
        "table": row.__tablename__,
        "key": "id",
        "ids": [str(row.id)],
        "rows": [_values(row, _fields(type(row)))],
    }


def _merge_marks(marks):
    grouped = {}
    for mark in marks:
        key = mark["table"], mark["key"]
        target = grouped.setdefault(key, {"table": key[0], "key": key[1], "ids": [], "rows": []})
        target["ids"] = sorted(set((*target["ids"], *mark["ids"])))
        rows = {row["id"]: row for row in target["rows"]}
        for row in mark["rows"]:
            _require(
                row["id"] not in rows or rows[row["id"]] == row, "同一实际依赖在本次读取期间变化。"
            )
            rows[row["id"]] = row
        target["rows"] = sorted(rows.values(), key=lambda row: row["id"])
    return list(grouped.values())


def _direct(s, ctx, model, key, identities, *, scope_id=None):
    _require(
        key in {"id", "original_id", "series_id", "issue_id", "build_id"} and hasattr(model, key),
        "无效的固定材料水位。",
    )
    ids = sorted({UUID(str(value)) for value in identities}, key=str)
    columns = [getattr(model, field) for field in _fields(model)]
    rows = (
        snapshot_mappings(
            s,
            select(*columns)
            .where(model.tenant_id == ctx.tenant_id, getattr(model, key).in_(ids))
            .execution_options(autoflush=False),
            scope_id=scope_id,
        )
        if ids
        else []
    )
    return {
        "table": model.__tablename__,
        "key": key,
        "ids": [str(v) for v in ids],
        "rows": sorted((to_jsonable_python(dict(row)) for row in rows), key=lambda v: v["id"]),
    }


def _watermarks_current(s, ctx, pid, marks):
    _require(type(marks) is list and bool(marks), "缺少实际固定材料水位。")
    for mark in marks:
        _require(type(mark) is dict and mark.get("table") in _MODELS, "无效的固定材料水位。")
        model = _MODELS[mark["table"]]
        actual = _direct(s, ctx, model, mark["key"], mark["ids"], scope_id=pid)
        _require(
            {row["id"] for row in mark["rows"]} <= {row["id"] for row in actual["rows"]},
            "固定来源不在当前可读范围。",
            "SOURCE_UNAVAILABLE",
            403,
        )
        for row in actual["rows"]:
            _require(
                row.get("product_id") in (None, str(pid))
                and row.get("category_id") in (None, str(ctx.category_id))
                and (
                    model is Product
                    or row.get("visibility") != "private"
                    or row.get("owner_id") == str(ctx.requester_id)
                ),
                f"{model.__tablename__}固定材料的当前来源或权限不可读取。",
                "FORBIDDEN_SCOPE",
                403,
            )
            if model is Artifact:
                _require(row["status"] == "active", "固定原文已撤回。", "SOURCE_UNAVAILABLE")
            if model is OriginalSecurity:
                _require(
                    row["source_state"] == "active" and row["disposition"] == "active",
                    "固定原件已撤回或不可安全读取。",
                    "SOURCE_UNAVAILABLE",
                )
        _require(actual == mark, "固定材料的实际版本、Current或来源摘要已变化。")
    return True


def _source_watermarks(s, ctx, pid, artifacts):
    if not artifacts:
        return []
    artifacts = {str(key): value for key, value in artifacts.items()}
    artifact = _direct(s, ctx, Artifact, "id", artifacts, scope_id=pid)
    _require(len(artifact["rows"]) == len(artifacts), "固定原文缺失。")
    for row in artifact["rows"]:
        expected = artifacts[row["id"]]
        _require(row["status"] == "active", "固定原文已撤回。", "SOURCE_UNAVAILABLE")
        _require(
            row["revision"] == expected["revision"] and row["content_hash"] == expected["sha256"],
            "实际原文摘要已变化。",
        )
    originals = [row["original_id"] for row in artifact["rows"] if row["original_id"]]
    if not originals:
        return [artifact]
    original = _direct(s, ctx, UploadedOriginal, "id", originals, scope_id=pid)
    security = _direct(s, ctx, OriginalSecurity, "original_id", originals, scope_id=pid)
    original_rows = {row["id"]: row for row in original["rows"]}
    security_rows = {row["original_id"]: row for row in security["rows"]}
    _require(set(original_rows) == set(originals) == set(security_rows), "原件或安全水位缺失。")
    for row in artifact["rows"]:
        if row["original_id"]:
            expected = artifacts[row["id"]]
            raw, state = original_rows[row["original_id"]], security_rows[row["original_id"]]
            _require(
                raw["revision"] == expected["original_revision"]
                and raw["content_hash"] == expected["original_sha256"]
                and state["epoch"] == expected["security_epoch"],
                "原件摘要或安全水位已变化。",
            )
    return [artifact, original, security]


def _line_sources(view):
    values = []
    for raw in view["sources"]:
        source = Source.model_validate({key: raw[key] for key in Source.model_fields})
        values.append(
            SourceRef(
                kind="artifact",
                id=source.artifact_id,
                revision=source.expected_revision,
                position=f"line:{source.line};quote_sha256:{sha256(source.quote.encode()).hexdigest()}",
            )
        )
    return tuple(values)


def _gaps(payload, publication):
    def gap(code, detail):
        return Gap(code=code, state="unknown", detail=detail, owner_role="npi")

    gaps = [
        gap(
            "PILOT_RESOURCE_READINESS_OWNER_UNCONNECTED",
            "本轮资源资格、物料与占用尚未由实际试产owner核对。",
        )
    ]
    if publication is None:
        gaps.append(gap("MANUFACTURING_PUBLICATION_MISSING", "尚未选择实际具名发布的制造基线。"))
    elif not publication["is_current"]:
        gaps.append(
            gap(
                "MANUFACTURING_PUBLICATION_REFERENCE_DRIFT",
                "固定发布已有后续版本，保留本次固定内容与本轮适用性缺项。",
            )
        )
    for field in (
        "line",
        "people",
        "material_lots",
        "fixtures",
        "equipment",
        "instructions",
        "control_plan",
        "risk",
        "reservation",
        "first_article",
    ):
        value = getattr(payload, field)
        if not value:
            gaps.append(gap(f"MISSING_{field.upper()}", f"本轮{field}尚无固定声明。"))
        elif field not in {"instructions", "control_plan"} or publication is None:
            values = value if isinstance(value, tuple) else (value,)
            for item in values:
                gaps.append(
                    gap(
                        "NATIVE_PILOT_REFERENCE_OWNER_UNCONNECTED",
                        f"{item.kind}:{item.id}:v{item.revision}尚未核对本轮实际资格/适用性。",
                    )
                )
    if publication is not None:
        declaration = publication["body"]["declaration"]
        for group in declaration["requirements"]:
            for requirement in group["requirements"]:
                resource = requirement.get("resource")
                label = (
                    "未指定固定资源"
                    if resource is None
                    else f"{resource['kind']}:{resource['id']}:v{resource['revision']}"
                )
                gaps.append(
                    gap(
                        "PUBLISHED_RESOURCE_REQUIREMENT_UNVERIFIED",
                        f"发布要求{requirement['text']}（{label}）尚未由本轮资源owner核对。",
                    )
                )
        if declaration["applicability"]["conditions"] is not None:
            gaps.append(
                gap(
                    "PUBLICATION_CONDITIONS_RECHECK_REQUIRED",
                    "发布声明的适用条件保留，尚未形成实际执行条件核对。",
                )
            )
    if not payload.parameters:
        gaps.append(gap("PARAMETERS_UNKNOWN", "本轮实际参数尚未固定。"))
    else:
        gaps.append(
            gap(
                "PARAMETER_ORIGINAL_VALUE_OWNER_UNCONNECTED",
                "参数引用保留，原始数值/单位语义尚未由实际参数owner核对。",
            )
        )
    return tuple(gaps)


class ActualPilotMaterialOwner:
    def __init__(self, engine):
        self.engine, self._reads = engine, WeakKeyDictionary()
        self._cache = WeakKeyDictionary()

    def _runtime(self, s):
        _require(
            s.get_bind() is self.engine,
            "试产材料owner与当前Session存储不同。",
            "FORBIDDEN_SCOPE",
            403,
        )
        return (
            evidence._runtime_stamp(s),
            id(getattr(self.engine, "_pdos_manufacturing_publication", None)),
            *(
                id(value)
                for value in (
                    execution.get_lot,
                    execution.get_actual_configuration,
                    builds._build,
                    builds._linked,
                    configurations.get_engineering,
                    configurations.get_process,
                    projects._project,
                    publications.get_publication_fact,
                    evidence._evidence,
                    validate_sources,
                )
            ),
        )

    def _collect(self, s, ctx, pid, payload):
        require_context(s, ctx)
        execution._human(s, ctx, pid)
        products = list(
            s.scalars(
                select(Product)
                .where(Product.tenant_id == ctx.tenant_id, Product.id == pid)
                .limit(2)
                .execution_options(populate_existing=True, autoflush=False)
            )
        )
        _require(len(products) == 1, "当前型号不可读取。", "FORBIDDEN_SCOPE", 403)
        product = products[0]
        _require(
            product.category_id == ctx.category_id
            and type(product.revision) is int
            and product.revision > 0,
            "当前品类与型号不一致。",
            "FORBIDDEN_SCOPE",
            403,
        )
        product_basis = _values(product, ("id", "tenant_id", "category_id", "revision"))
        marks = [_mark(product)]
        build = builds._build(s, ctx, pid, payload.basis.build.id)
        marks.append(_mark(build))
        project, _, _, planned_reads = builds._linked(s, ctx, pid, build, new_consumption=True)
        project, link, definition = projects._project(s, ctx, pid, build.project_id)
        marks.extend((_mark(project), _mark(link)))
        fixed_definition = s.get(DefinitionRevision, link.definition_id)
        _require(fixed_definition is not None, "固定型号定义不可读取。")
        marks.append(_mark(fixed_definition))
        validate_sources(s, ctx, definition)
        _require(build.revision == payload.basis.build.revision, "固定Build版本不一致。")
        _require(
            project.purpose == payload.purpose,
            "本轮用途须固定到真实项目用途。",
            "FORBIDDEN_SCOPE",
            403,
        )
        scope = Scope(tenant_id=ctx.tenant_id, product_id=pid, project_id=project.id)
        build_view = _values(
            build,
            (
                "id",
                "revision",
                "project_id",
                "project_revision",
                "name",
                "type",
                "purpose",
                "planned_quantity",
                "unit",
                "status",
                "owner_id",
                "visibility",
                "engineering_configuration_id",
                "manufacturing_configuration_id",
            ),
        )
        project_basis = _values(
            project, ("id", "revision", "owner_id", "visibility", "purpose", "scope", "status")
        )
        lot, lot_view = execution.get_lot(s, ctx, pid, payload.basis.lot.id)
        marks.append(_mark(lot))
        lot_view = deepcopy(lot_view)
        actual, actual_view = execution.get_actual_configuration(
            s, ctx, pid, payload.basis.actual_configuration.id
        )
        marks.append(_mark(actual))
        actual_view = deepcopy(actual_view)
        engineering, engineering_view = configurations.get_engineering(
            s, ctx, pid, payload.basis.engineering_configuration.id
        )
        marks.append(_mark(engineering))
        process, process_view = configurations.get_process(
            s, ctx, pid, payload.basis.process_revision.id
        )
        marks.append(_mark(process))
        engineering_view, process_view = deepcopy(engineering_view), deepcopy(process_view)
        _require(
            (
                lot.revision,
                lot.build_id,
                lot.project_id,
                lot.build_revision,
                lot.actual_configuration_id,
                lot.actual_configuration_revision,
                lot.unit,
            )
            == (
                payload.basis.lot.revision,
                build.id,
                project.id,
                build.revision,
                actual.id,
                actual.revision,
                payload.basis.unit,
            )
            and (actual.revision, actual.build_id, actual.project_id, actual.build_revision)
            == (payload.basis.actual_configuration.revision, build.id, project.id, build.revision)
            and (
                actual.actual_engineering_configuration_id,
                actual.actual_engineering_revision,
                actual.actual_manufacturing_configuration_id,
                actual.actual_manufacturing_revision,
            )
            == (engineering.id, engineering.revision, process.id, process.revision)
            and engineering.revision == payload.basis.engineering_configuration.revision
            and process.revision == payload.basis.process_revision.revision
            and (process.engineering_configuration_id, process.engineering_revision)
            == (engineering.id, engineering.revision)
            and (engineering.definition_id, engineering.definition_revision)
            == (link.definition_id, link.definition_revision),
            "试产须绑定同一真实Build、批次、实际双配置与项目固定定义。",
            "CONFIGURATION_MISMATCH",
        )
        _require(
            lot.observation_nature in {"real", "synthetic"}
            and lot_view["observation"]["nature"] == lot.observation_nature,
            "实际批次观察性质不能核对。",
        )
        publication, publication_basis, applicability = None, None, None
        if payload.manufacturing_baseline is not None:
            selected = payload.manufacturing_baseline
            # This function resolves the formal Publication table and its actual
            # common group, never a draft selected by the same kind label.
            row, publication = publications.get_publication_fact(
                s, ctx, pid, selected.id, selected.revision
            )
            marks.extend(
                (
                    _mark(row),
                    _direct(
                        s,
                        ctx,
                        ManufacturingBaselinePublicationCurrent,
                        "series_id",
                        [row.series_id],
                        scope_id=pid,
                    ),
                )
            )
            publication = deepcopy(publication)
            _require(
                row.project_id == project.id
                and row.purpose == payload.purpose
                and publication["process"] == {"id": str(process.id), "revision": process.revision},
                "固定发布与本轮项目、用途或实际工艺不相容。",
                "FORBIDDEN_SCOPE",
                403,
            )
            _require(
                publication["source_status"] == "current", "所选发布的实际来源或专业依据需重核。"
            )
            applicability = Applicability.model_validate(
                publication["body"]["declaration"]["applicability"]
            )
            _require(
                applicability.site is None or process.site == applicability.site,
                "发布场地与实际制造配置不一致。",
                "FORBIDDEN_SCOPE",
                403,
            )
            if payload.line is not None and applicability.lines is not None:
                _require(
                    any(
                        (v.id, v.revision) == (payload.line.id, payload.line.revision)
                        for v in applicability.lines
                    ),
                    "所选实际产线不在固定发布适用范围。",
                    "FORBIDDEN_SCOPE",
                    403,
                )
            documents = publication["body"]["documents"]
            for selected_document in (
                *payload.instructions,
                *((payload.control_plan,) if payload.control_plan is not None else ()),
            ):
                _require(
                    any(
                        v["id"] == str(selected_document.id)
                        and v["revision"] == selected_document.revision
                        and v["kind"] == selected_document.kind
                        for v in documents
                    ),
                    "本轮工序资料不属于该发布的固定文档。",
                    "FORBIDDEN_SCOPE",
                    403,
                )
            publication_basis = _values(
                row,
                (
                    "id",
                    "revision",
                    "receipt_id",
                    "body_sha256",
                    "source_basis",
                    "authority_snapshot",
                ),
            )
        groups = [planned_reads, preparations._definition_reads(definition)]
        sources = [payload.source, *(v.source for v in payload.parameters if v.source is not None)]
        for view in (
            lot_view,
            actual_view,
            engineering_view,
            process_view,
            definition,
            *((publication,) if publication is not None else ()),
        ):
            if "required_source_read_set" in view:
                groups.append(view["required_source_read_set"])
            sources.extend(_line_sources(view))
        sources = tuple(dict.fromkeys(sources))
        _require(
            all(value.kind == "artifact" for value in sources),
            "所选非原文来源尚无精确试产来源owner。",
            "INTEGRATION_REQUIRED",
            503,
        )
        groups.append(
            [{"artifact_id": str(v.id), "expected_revision": v.revision} for v in sources]
        )
        reads = configurations._merge_reads(*groups)
        artifacts, _, verified = evidence._evidence(s, ctx, pid, reads, sources, io=True)
        _require(
            {evidence.digest(v) for v in sources} <= set(verified)
            and {(str(v["artifact_id"]), v["expected_revision"]) for v in reads}
            == {(str(key), value["revision"]) for key, value in artifacts.items()},
            "实际来源owner未覆盖完整读集及原文。",
            "MISSING_REQUIRED_EVIDENCE",
        )
        require_access(s, ctx, pid)
        checked = now()
        if applicability is not None:
            _require(
                (applicability.valid_from is None or applicability.valid_from <= checked)
                and (applicability.valid_until is None or checked < applicability.valid_until),
                "完整读取后发布适用期限尚未开始或已过期。",
            )
        material = NativePilotMaterial(
            scope=scope,
            category_id=product.category_id,
            product_revision=product.revision,
            purpose=project.purpose,
            basis=payload.basis,
            build=build_view,
            lot=to_jsonable_python(lot_view),
            actual_configuration=to_jsonable_python(actual_view),
            engineering_configuration=to_jsonable_python(engineering_view),
            process=to_jsonable_python(process_view),
            publication=to_jsonable_python(publication),
            gaps=_gaps(payload, publication),
        )
        basis = to_jsonable_python(
            {
                "artifacts": artifacts,
                "verified_sources": sorted(verified),
                "product": product_basis,
                "project": project_basis,
                "definition": definition,
                "publication": publication_basis,
                "watermarks": _merge_marks([*marks, *_source_watermarks(s, ctx, pid, artifacts)]),
            }
        )
        return material, basis, sources, tuple(SourceRead.model_validate(v) for v in reads)

    def read(self, s, ctx, pid, payload):
        _require(
            isinstance(ctx, Context)
            and ctx.actor_id == ctx.requester_id
            and ctx.run_id is None
            and isinstance(pid, UUID),
            "试产材料须由当前具名本人读取。",
            "NAMED_DECISION_REQUIRED",
            403,
        )
        payload = PilotCreate.model_validate(payload)
        uow, caller, runtime = _uow(s), digest(vars(ctx)), self._runtime(s)
        semantic = payload.model_dump(mode="json")
        key = digest({"caller": caller, "product": str(pid), "payload": semantic})
        cached = self._cache.get(s)
        if cached is not None and cached[0] == uow and key in cached[1]:
            self._binding(s, ctx, pid, payload, cached[1][key])
            return cached[1][key]
        # The host's real product gate/read snapshot protects this single read.
        # A second complete pass is neither a lock nor a concurrency proof.
        latest = self._collect(s, ctx, pid, payload)
        _same_uow(s, uow, ctx, caller)
        _require(runtime == self._runtime(s), "实际试产材料owner在读取期间发生变化。")
        value = PilotMaterialRead(*latest, now())
        self._reads[value] = (
            ref(s),
            uow,
            caller,
            pid,
            semantic,
            self._snapshot(value),
            value.checked_at,
            runtime,
        )
        if cached is None or cached[0] != uow:
            self._cache[s] = (uow, {})
        self._cache[s][1][key] = value
        return value

    def current(self, s, ctx, pid, material_snapshot, source_basis):
        """Compare persisted T1 direct watermarks under the host's actual gate.

        The host must first bind this snapshot to its real saved Confirmation or
        immutable atom. This read grants no signer/resource/start qualification.
        """
        require_context(s, ctx)
        self._runtime(s)
        material = NativePilotMaterial.model_validate(material_snapshot)
        _require(
            material.scope.tenant_id == ctx.tenant_id
            and material.scope.product_id == pid
            and material.category_id == ctx.category_id,
            "固定材料不属于当前品类或型号。",
            "FORBIDDEN_SCOPE",
            403,
        )
        return _watermarks_current(s, ctx, pid, source_basis.get("watermarks"))

    @staticmethod
    def _snapshot(value):
        return (
            value.material.model_dump(mode="json"),
            deepcopy(value.source_basis),
            value.sources,
            value.required_source_read_set,
        )

    def _binding(self, s, ctx, pid, payload, previous):
        saved = self._reads.get(previous) if type(previous) is PilotMaterialRead else None
        _require(saved is not None, "须刷新本owner实际发行的封存材料。")
        session, uow, caller, product, semantic, snapshot, checked_at, runtime = saved
        _same_uow(s, uow, ctx, caller)
        _require(
            session() is s
            and product == pid
            and runtime == self._runtime(s)
            and PilotCreate.model_validate(payload).model_dump(mode="json") == semantic
            and self._snapshot(previous) == snapshot
            and previous.checked_at == checked_at,
            "原实际调用、实质载荷或封存材料发生变化。",
        )
        return saved

    def refresh(self, s, ctx, pid, payload, previous):
        saved = self._binding(s, ctx, pid, payload, previous)
        self.current(s, ctx, pid, previous.material.model_dump(mode="json"), previous.source_basis)
        require_access(s, ctx, pid)
        latest = replace(previous, checked_at=now())
        self._reads[latest] = (*saved[:6], latest.checked_at, saved[-1])
        return latest
