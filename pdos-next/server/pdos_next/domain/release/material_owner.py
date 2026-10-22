"""Actual fixed release inputs in one caller UOW; no release or qualification.

Immutable owner versions/Current pointers are read directly, not through their
write-capability or historical-signature reproof paths. Direct new originals
perform byte IO once; upstream originals use persisted summaries/current
metadata. Policy/exception owners are not invented here.
"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from uuid import UUID
from weakref import WeakKeyDictionary, ref

from pydantic import BaseModel
from pydantic_core import to_jsonable_python
from sqlalchemy import and_, func, inspect, or_, select

from pdos_next.contracts import SourceRead
from pdos_next.database import require_context
from pdos_next.domain.build_execution.models import ActualConfiguration, BuildLot
from pdos_next.domain.build_operational_facts import service as operational
from pdos_next.domain.build_operational_facts.models import (
    BuildOperationalCurrent,
    BuildOperationalFact,
    OperationalAsset,
)
from pdos_next.domain.build_operational_facts.schemas import FactInput
from pdos_next.domain.builds.models import Build
from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow, _uow
from pdos_next.domain.change_execution import service as changes
from pdos_next.domain.change_execution import service as evidence
from pdos_next.domain.change_execution.models import ChangeCurrent, ChangeRequestVersion
from pdos_next.domain.configurations.models import (
    BomRevision,
    EngineeringConfiguration,
    ProcessRevision,
)
from pdos_next.domain.manufacturing_baseline import publication_service as publications
from pdos_next.domain.manufacturing_baseline.models import PreparationCurrent, PreparationVersion
from pdos_next.domain.manufacturing_baseline.publication_models import (
    ManufacturingBaselinePublicationCurrent,
)
from pdos_next.domain.manufacturing_trials import native_material_owner as direct
from pdos_next.domain.manufacturing_trials import native_service as pilots
from pdos_next.domain.manufacturing_trials.native_models import (
    NativePilotCurrent,
    NativePilotObservation,
)
from pdos_next.domain.products.models import DefinitionRevision, DefinitionSource
from pdos_next.domain.professional_authority.signature_watermarks import signature_current
from pdos_next.domain.projects.models import Project, ProjectProductLink
from pdos_next.domain.quality_execution import service as quality
from pdos_next.domain.quality_execution.models import QualityIssueCurrent, QualityIssueVersion
from pdos_next.domain.release_exceptions.owner import ActualReleaseExceptionOwner
from pdos_next.domain.verification_launch.models import (
    VerificationRunCurrent,
    VerificationRunVersion,
)
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Product, now
from pdos_next.request_proof import snapshot_get, snapshot_mappings, snapshot_rows
from pdos_next.schemas.verification.contracts import Scope, SourceRef, TestRun
from pdos_next.service import digest, require_access

from . import rules
from .policy_owner import ActualReleasePolicyOwner
from .schemas import FixedObject, PackageAssemblePayload, ReleaseMaterial


@dataclass(frozen=True, eq=False)
class ReleaseMaterialRead:
    material: ReleaseMaterial
    source_basis: dict
    sources: tuple[SourceRef, ...]
    required_source_read_set: tuple[SourceRead, ...]
    gaps: tuple[str, ...]
    checked_at: datetime


_EXTRA = (
    BomRevision,
    DefinitionSource,
    ChangeCurrent,
    ChangeRequestVersion,
    PreparationVersion,
    PreparationCurrent,
    NativePilotCurrent,
    NativePilotObservation,
    pilots.Pilot,
    VerificationRunCurrent,
    VerificationRunVersion,
)
_MODELS = {**direct._MODELS, **{model.__tablename__: model for model in _EXTRA}}


def _require(test, detail, code="SOURCE_STALE", status=409):
    if not test:
        raise DomainError(code, detail, status)


def _json(row):
    return to_jsonable_python(
        {
            column.key: deepcopy(getattr(row, column.key))
            for column in inspect(type(row)).column_attrs
        }
    )


def _mark(row):
    value = direct._mark(row)
    if isinstance(row, DefinitionSource):
        # A direct Current check needs its fingerprint, not private quote text.
        value["rows"][0].pop("quote")
        value["rows"][0]["quote_sha256"] = sha256(row.quote.encode()).hexdigest()
    return value


def _accessible(row, ctx, pid, project_id=None):
    return (
        row is not None
        and row.tenant_id == ctx.tenant_id
        and getattr(row, "product_id", pid) in (None, pid)
        and getattr(row, "category_id", ctx.category_id) in (None, ctx.category_id)
        and (project_id is None or getattr(row, "project_id", project_id) in (None, project_id))
        and (
            isinstance(row, Product)
            or getattr(row, "visibility", None) != "private"
            or row.owner_id == ctx.requester_id
        )
    )


def _refs(value):
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        if {"kind", "id", "revision", "position"} <= set(value):
            return (SourceRef.model_validate({key: value[key] for key in SourceRef.model_fields}),)
        if {"artifact_id", "expected_revision", "line", "quote"} <= set(value):
            _require(
                isinstance(value["quote"], str),
                "固定原文的引用权限不可读取。",
                "FORBIDDEN_SCOPE",
                403,
            )
            return (
                SourceRef(
                    kind="artifact",
                    id=value["artifact_id"],
                    revision=value["expected_revision"],
                    position=f"line:{value['line']};quote_sha256:{sha256(value['quote'].encode()).hexdigest()}",
                ),
            )
        return tuple(dict.fromkeys(source for child in value.values() for source in _refs(child)))
    if isinstance(value, (tuple, list)):
        return tuple(dict.fromkeys(source for child in value for source in _refs(child)))
    return ()


def _query_mark(s, ctx, pid, model, key, ids):
    _require(
        model.__tablename__ in _MODELS and key in model.__table__.columns, "无效的固定来源水位。"
    )
    ids = sorted({UUID(str(value)) for value in ids}, key=str)
    columns = [
        getattr(model, key)
        for key in direct._fields(model)
        if model is not DefinitionSource or key != "quote"
    ]
    if model is DefinitionSource:
        columns.append(
            func.encode(func.sha256(func.convert_to(model.quote, "UTF8")), "hex").label(
                "quote_sha256"
            )
        )
    rows = (
        snapshot_mappings(
            s,
            select(*columns)
            .where(model.tenant_id == ctx.tenant_id, getattr(model, key).in_(ids))
            .execution_options(autoflush=False),
            scope_id=pid,
        )
        if ids
        else []
    )
    return {
        "table": model.__tablename__,
        "key": key,
        "ids": [str(value) for value in ids],
        "rows": sorted(
            (to_jsonable_python(dict(row)) for row in rows), key=lambda value: value["id"]
        ),
    }


class ActualReleaseMaterialOwner:
    def __init__(self, engine):
        self.engine = engine
        self.policy_owner = ActualReleasePolicyOwner(engine)
        self.exception_owner = ActualReleaseExceptionOwner(engine)
        self._reads, self._cache = WeakKeyDictionary(), WeakKeyDictionary()

    def _runtime(self, s):
        _require(
            s.get_bind() is self.engine,
            "发布材料须使用本owner的实际Session存储。",
            "FORBIDDEN_SCOPE",
            403,
        )
        return (
            evidence._runtime_stamp(s),
            id(publications.get_publication_fact),
            id(pilots._retained),
            id(quality._snapshot),
            id(changes._snapshot),
            id(evidence._evidence),
            id(operational._fact_hash),
            id(type(self.policy_owner).read),
            id(type(self.policy_owner).current),
            id(type(self.exception_owner).read),
            id(type(self.exception_owner).current),
        )

    def _collect(self, s, ctx, pid, payload):
        product = require_access(s, ctx, pid)
        _require(
            product.category_id == ctx.category_id, "品类与实际型号不一致。", "FORBIDDEN_SCOPE", 403
        )
        marks, objects, reads, sources, signatures, links = (
            [_mark(product)],
            {},
            [],
            list(_refs(payload)),
            [],
            [],
        )
        gaps = []
        policy_facts = []
        cache, builds = {}, set()

        def row(model, identity, revision=None, *, project=True):
            key = model, identity
            if key not in cache:
                actual = snapshot_get(s, model, identity, scope_id=pid)
                _require(
                    _accessible(actual, ctx, pid, payload.project_id if project else None),
                    "所选实际发布材料不可读取。",
                    "FORBIDDEN_SCOPE",
                    403,
                )
                cache[key] = actual
                marks.append(_mark(actual))
                reads.extend(getattr(actual, "required_source_read_set", ()) or ())
                sources.extend(_refs(getattr(actual, "sources", ())))
                _require(
                    payload.visibility == "private"
                    or getattr(actual, "visibility", None) != "private",
                    "私有对象不能借发布包扩大共享。",
                    "FORBIDDEN_SCOPE",
                    403,
                )
            actual = cache[key]
            _require(
                revision is None or actual.revision == revision,
                "所选固定版本不一致。",
                "VERSION_CONFLICT",
            )
            return actual

        def selected(model, refs, key):
            refs = tuple(refs)
            if not refs:
                return {}
            clauses = [
                and_(getattr(model, key) == value.id, model.revision == value.revision)
                for value in refs
            ]
            values = snapshot_rows(
                s,
                ("release-fixed", model, tuple((v.id, v.revision) for v in refs)),
                select(model).where(
                    model.tenant_id == ctx.tenant_id, model.product_id == pid, or_(*clauses)
                ),
                scope_id=pid,
            )
            result = {}
            for value in values:
                _require(
                    _accessible(value, ctx, pid, payload.project_id),
                    "固定领域版本不可访问。",
                    "FORBIDDEN_SCOPE",
                    403,
                )
                cache[model, value.id] = value
                marks.append(_mark(value))
                reads.extend(value.required_source_read_set)
                sources.extend(_refs(value.sources))
                _require(
                    payload.visibility == "private" or value.visibility != "private",
                    "私有领域证据不能随包共享。",
                    "FORBIDDEN_SCOPE",
                    403,
                )
                result[getattr(value, key), value.revision] = value
            _require(
                set(result) == {(value.id, value.revision) for value in refs},
                "所选精确领域版本缺失或不可读。",
                "FORBIDDEN_SCOPE",
                403,
            )
            return result

        def pointer(model, key, ids):
            mark = _query_mark(s, ctx, pid, model, key, ids)
            marks.append(mark)
            return mark["rows"]

        project = row(Project, payload.project_id)
        _require(
            payload.purpose == project.purpose,
            "发布用途须绑定实际项目用途。",
            "FORBIDDEN_SCOPE",
            403,
        )
        link_rows = snapshot_rows(
            s,
            (ProjectProductLink, pid, project.id),
            select(ProjectProductLink).where(
                ProjectProductLink.tenant_id == ctx.tenant_id,
                ProjectProductLink.product_id == pid,
                ProjectProductLink.project_id == project.id,
            ),
            scope_id=pid,
        )
        _require(len(link_rows) == 1, "项目须有真实固定定义关联。")
        marks.append(_mark(link_rows[0]))
        eng = row(
            EngineeringConfiguration,
            payload.subject_config.engineering_configuration.id,
            payload.subject_config.engineering_configuration.revision,
        )
        process = row(
            ProcessRevision,
            payload.subject_config.manufacturing_configuration.id,
            payload.subject_config.manufacturing_configuration.revision,
        )
        defined = row(
            DefinitionRevision,
            payload.subject_config.definition.id,
            payload.subject_config.definition.revision,
        )
        _require(
            (eng.definition_id, eng.definition_revision) == (defined.id, defined.revision)
            and (process.engineering_configuration_id, process.engineering_revision)
            == (eng.id, eng.revision),
            "固定定义与实际双配置的关联不一致。",
            "CONFIGURATION_MISMATCH",
        )
        row(BomRevision, eng.bom_id, eng.bom_revision)
        definition_sources = snapshot_rows(
            s,
            (DefinitionSource, pid, defined.id),
            select(DefinitionSource).where(
                DefinitionSource.tenant_id == ctx.tenant_id,
                DefinitionSource.definition_id == defined.id,
            ),
            scope_id=pid,
        )
        for value in definition_sources:
            marks.append(_mark(value))
            sources.extend(
                _refs(
                    {
                        "artifact_id": value.artifact_id,
                        "expected_revision": value.source_revision,
                        "line": value.line,
                        "quote": value.quote,
                    }
                )
            )
        selected_refs = rules.selected_objects(payload)
        kinds = {
            kind: tuple(value for value in selected_refs if value.kind == kind)
            for kind in {value.kind for value in selected_refs}
        }

        def add(ref_value, actual, snapshot=None, *, project_id=None, current=False):
            policy_facts.append(
                {
                    "ref": ref_value,
                    "value": {
                        "snapshot": to_jsonable_python(
                            snapshot if snapshot is not None else _json(actual)
                        ),
                        "_release_current": current,
                    },
                }
            )
            objects[ref_value] = FixedObject(
                ref=ref_value,
                product_id=pid,
                project_id=project_id
                if project_id is not None
                else getattr(actual, "project_id", None),
                sha256=digest(
                    to_jsonable_python(snapshot if snapshot is not None else _json(actual))
                ),
            )

        for kind, model in (
            ("definition", DefinitionRevision),
            ("engineering_configuration", EngineeringConfiguration),
            ("process_revision", ProcessRevision),
            ("artifact", Artifact),
            ("build_lot", BuildLot),
            ("work_instruction", PreparationVersion),
            ("control_plan", PreparationVersion),
        ):
            for value in kinds.get(kind, ()):
                actual = row(model, value.id, value.revision)
                if kind == "build_lot":
                    actual_config = row(
                        ActualConfiguration,
                        actual.actual_configuration_id,
                        actual.actual_configuration_revision,
                    )
                    build = row(Build, actual.build_id, actual.build_revision)
                    _require(
                        actual_config.build_id == build.id
                        and actual_config.project_id == project.id
                        and actual_config.build_revision == build.revision
                        and actual.unit == build.unit,
                        "批次与实际配置及Build关联不一致。",
                        "CONFIGURATION_MISMATCH",
                    )
                    if (value.id, value.revision) in {
                        (selected_lot.id, selected_lot.revision)
                        for selected_lot in payload.release_scope.lots or ()
                    }:
                        _require(
                            (
                                actual_config.actual_engineering_configuration_id,
                                actual_config.actual_engineering_revision,
                                actual_config.actual_manufacturing_configuration_id,
                                actual_config.actual_manufacturing_revision,
                            )
                            == (eng.id, eng.revision, process.id, process.revision),
                            "放行数量范围须属于实际所选双配置。",
                            "CONFIGURATION_MISMATCH",
                        )
                    builds.add(build.id)
                if kind in {"work_instruction", "control_plan"}:
                    _require(
                        actual.kind == kind and digest(actual.body) == actual.body_sha256,
                        "固定制造资料类型或内容摘要不一致。",
                        "INTEGRITY_MISMATCH",
                    )
                    pointer(PreparationCurrent, "series_id", [actual.series_id])
                    if (actual.process_id, actual.process_revision) != (
                        process.id,
                        process.revision,
                    ):
                        gaps.append("DOCUMENT_CONFIGURATION_APPLICABILITY_UNKNOWN")
                if kind == "artifact":
                    reads.append(
                        {"artifact_id": str(actual.id), "expected_revision": actual.revision}
                    )
                add(value, actual, current=kind == "artifact" and actual.status == "active")
        if payload.release_scope.quantity is not None and payload.release_scope.lots:
            lots = [cache[BuildLot, value.id] for value in payload.release_scope.lots]
            _require(
                all(value.unit == payload.release_scope.unit for value in lots)
                and payload.release_scope.quantity
                <= sum(value.observed_unit_count for value in lots),
                "数量不得超过同单位真实批次的实际产出。",
                "FIXED_DENOMINATOR_CHANGED",
            )
        for value in kinds.get("manufacturing_publication", ()):
            actual, view = publications.get_publication_fact(s, ctx, pid, value.id, value.revision)
            _require(
                _accessible(actual, ctx, pid, project.id)
                and actual.purpose == payload.purpose
                and (actual.process_id, actual.process_revision) == (process.id, process.revision),
                "正式制造发布不属于固定项目/用途/配置。",
                "CONFIGURATION_MISMATCH",
            )
            _require(
                payload.visibility == "private" or actual.visibility != "private",
                "私有发布不能扩大共享。",
                "FORBIDDEN_SCOPE",
                403,
            )
            marks.append(_mark(actual))
            pointer(ManufacturingBaselinePublicationCurrent, "series_id", [actual.series_id])
            reads.extend(actual.required_source_read_set)
            sources.extend(_refs(view["sources"]))
            signatures.append(
                {"project_id": str(project.id), "snapshot": deepcopy(actual.authority_snapshot)}
            )
            if view["source_status"] != "current":
                gaps.append("PUBLICATION_RECHECK_REQUIRED")
            add(
                value,
                actual,
                {"body": actual.body_sha256, "payload": actual.payload_sha256},
                current=view["source_status"] == "current",
            )
        for kind, model, key in (
            ("test_run", VerificationRunVersion, "run_id"),
            ("issue", QualityIssueVersion, "issue_id"),
            ("change", ChangeRequestVersion, "change_id"),
        ):
            values = selected(model, kinds.get(kind, ()), key)
            if values:
                pointer(
                    {
                        "test_run": VerificationRunCurrent,
                        "issue": QualityIssueCurrent,
                        "change": ChangeCurrent,
                    }[kind],
                    key,
                    [value[0] for value in values],
                )
            for value in kinds.get(kind, ()):
                actual = values[value.id, value.revision]
                if kind == "test_run":
                    snapshot = TestRun.model_validate(actual.run_snapshot)
                    _require(
                        digest(snapshot.model_dump(mode="json")) == actual.snapshot_sha256
                        and digest(actual.execution_plan) == actual.plan_sha256
                        and snapshot.id == actual.run_id
                        and snapshot.revision == actual.revision
                        and snapshot.status == actual.status
                        and (snapshot.build.id, snapshot.build.revision)
                        == (actual.build_id, actual.build_revision)
                        and (snapshot.request_id, snapshot.request_revision)
                        == (actual.request_id, actual.request_revision)
                        and snapshot.scope
                        == Scope(tenant_id=ctx.tenant_id, product_id=pid, project_id=project.id),
                        "测试固定版本及范围摘要不一致。",
                        "INTEGRITY_MISMATCH",
                    )
                    builds.add(actual.build_id)
                else:
                    snapshot = (
                        quality._snapshot(actual) if kind == "issue" else changes._snapshot(actual)
                    )
                add(
                    value,
                    actual,
                    {
                        "snapshot": snapshot.model_dump(mode="json"),
                        **({"plan_sha256": actual.plan_sha256} if kind == "test_run" else {}),
                    },
                )
        for value in kinds.get("pilot_run", ()):
            actual = pilots._root(s, ctx, pid, value.id)
            _require(
                _accessible(actual, ctx, pid, project.id)
                and (payload.visibility == "private" or actual.visibility != "private"),
                "所选Pilot不属于当前项目或共享范围。",
                "FORBIDDEN_SCOPE",
                403,
            )
            pilots._retained(s, ctx, pid, actual)
            marks.append(_mark(actual))
            reads.extend(actual.required_source_read_set)
            sources.extend(_refs(actual.sources))
            signatures.append(
                {"project_id": str(project.id), "snapshot": deepcopy(actual.authority_snapshot)}
            )
            pointer(NativePilotCurrent, "pilot_id", [actual.id])
            selected_row = actual
            if value.revision != 1:
                found = selected(NativePilotObservation, (value,), "pilot_id")
                selected_row = found[value.id, value.revision]
                pilots._retained(s, ctx, pid, selected_row)
            reads.extend(selected_row.required_source_read_set)
            sources.extend(_refs(selected_row.sources))
            builds.add(actual.build_id)
            signatures.append(
                {
                    "project_id": str(project.id),
                    "snapshot": deepcopy(selected_row.authority_snapshot),
                }
            )
            add(
                value,
                actual,
                {
                    "root": actual.payload_sha256,
                    "observation": selected_row.payload_sha256,
                    "fixed_scope": getattr(selected_row, "fixed_scope", None),
                    "projection": getattr(selected_row, "projection", None),
                },
            )

        if kinds.get("line"):
            _require(
                builds,
                "当前真实产线读取须有批次/Pilot/Run的Build资源事实上下文。",
                "INTEGRATION_REQUIRED",
                503,
            )
            current = pointer(BuildOperationalCurrent, "build_id", builds)
            facts = [
                row(BuildOperationalFact, UUID(value["fact_id"]), value["fact_revision"])
                for value in current
            ]
            for value in kinds["line"]:
                asset = row(OperationalAsset, value.id, value.revision)
                matches = []
                for fact in facts:
                    _require(
                        operational._fact_hash(fact) == fact.fact_sha256,
                        "实际产线资源事实摘要不一致。",
                        "INTEGRITY_MISMATCH",
                    )
                    if (
                        fact.binding.get("manufacturing_configuration_id"),
                        fact.binding.get("manufacturing_configuration_revision"),
                    ) != (str(process.id), process.revision):
                        continue
                    data = FactInput.model_validate(fact.data)
                    for kind, aid, key, identity, revision, physical in operational._assets(
                        data, ctx.tenant_id
                    ):
                        if (kind, aid, revision) == ("resource", value.id, value.revision):
                            _require(
                                identity == {"kind": "line", "id": str(value.id)}
                                and asset.identity == identity
                                and asset.external_key == key
                                and asset.data_sha256 == digest(physical)
                                and asset.data == {"value": physical, "state": "active"},
                                "实际产线固定身份、版本或物理镜像不一致。",
                                "INTEGRITY_MISMATCH",
                            )
                            matches.append(
                                {
                                    "fact_id": str(fact.id),
                                    "fact_sha256": fact.fact_sha256,
                                    "build_id": str(fact.build_id),
                                    "scope": data.scope.model_dump(mode="json"),
                                }
                            )
                _require(
                    matches,
                    "缺所选真实产线与该项目/制造配置的实际资源事实。",
                    "INTEGRATION_REQUIRED",
                    503,
                )
                links.append({"line_id": str(value.id), "facts": matches})
                add(
                    value,
                    asset,
                    {"asset": asset.data_sha256, "facts": matches},
                    project_id=project.id,
                )
            gaps.append("RESOURCE_QUALIFICATION_OWNER_UNCONNECTED")
        exceptions, exception_basis = (), ()
        if payload.exceptions:
            from .policy_owner import _fact as policy_fact
            from .policy_owner import _pointer as policy_pointer
            from .schemas import VersionRef

            scope = Scope(tenant_id=ctx.tenant_id, product_id=pid, project_id=project.id)
            policy_row = policy_fact(
                s,
                ctx,
                pid,
                scope,
                payload.purpose,
                policy_pointer(s, ctx, pid, scope, payload.purpose),
            )
            exceptions, fixed_exceptions, exception_basis, extra_sources, extra_reads = (
                self.exception_owner.read(
                    s,
                    ctx,
                    pid,
                    payload.exceptions,
                    scope=scope,
                    config=payload.subject_config,
                    purpose=payload.purpose,
                    policy_version=policy_row.policy_version if policy_row else None,
                    policy_fact=VersionRef(id=policy_row.id, revision=policy_row.revision)
                    if policy_row
                    else None,
                    visibility=payload.visibility,
                )
            )
            for fixed, actual in zip(fixed_exceptions, exceptions, strict=True):
                objects[fixed.ref] = fixed
                policy_facts.append(
                    {
                        "ref": fixed.ref,
                        "value": {
                            "snapshot": actual.model_dump(mode="json"),
                            "_release_current": actual.state == "current",
                        },
                    }
                )
            sources.extend(extra_sources)
            reads.extend(extra_reads)
        policy = self.policy_owner.read(
            s,
            ctx,
            pid,
            scope=Scope(tenant_id=ctx.tenant_id, product_id=pid, project_id=project.id),
            purpose=payload.purpose,
            subject_config=payload.subject_config,
            release_scope=payload.release_scope,
            facts=tuple(policy_facts),
            at=now(),
        )
        _require(
            payload.visibility == "private" or policy.visibility != "private",
            "私有政策不能借固定包扩大共享。",
            "FORBIDDEN_SCOPE",
            403,
        )
        gaps.extend(policy.gaps)
        sources.extend(policy.sources)
        reads.extend(policy.required_source_read_set)
        all_sources = tuple(dict.fromkeys(sources))
        direct_reads = [
            {"artifact_id": str(value.id), "expected_revision": value.revision}
            for value in all_sources
            if value.kind == "artifact"
        ]
        merged = rules._canonical_reads((*reads, *direct_reads))
        byte_ids = {value.id for value in _refs(payload)} | {
            value.id for value in selected_refs if value.kind == "artifact"
        }
        artifacts, private, verified = {}, False, set()
        # Each source occurs in one partition. Signed upstream material does not
        # force this new package to reread all of its historical original bytes.
        for io in (True, False):
            group = [
                value.model_dump(mode="json")
                for value in merged
                if (value.artifact_id in byte_ids) is io
            ]
            if not group:
                continue
            refs = tuple(
                value
                for value in all_sources
                if value.kind == "artifact" and (value.id in byte_ids) is io
            )
            checked, is_private, checked_refs = evidence._evidence(s, ctx, pid, group, refs, io=io)
            artifacts.update(checked)
            private |= is_private
            verified.update(checked_refs)
        _require(
            payload.visibility == "private" or not private,
            "私有原文不能随发布包扩大共享。",
            "FORBIDDEN_SCOPE",
            403,
        )
        _require(
            {evidence.digest(value) for value in all_sources if value.kind == "artifact"}
            <= set(verified),
            "实际原文owner没有覆盖所选完整引用。",
            "MISSING_REQUIRED_EVIDENCE",
            422,
        )
        marks.extend(direct._source_watermarks(s, ctx, pid, artifacts))
        material = ReleaseMaterial(
            scope=Scope(tenant_id=ctx.tenant_id, product_id=pid, project_id=project.id),
            category_id=product.category_id,
            product_revision=product.revision,
            purpose=project.purpose,
            subject_config=payload.subject_config,
            release_scope=payload.release_scope,
            objects=tuple(objects[value] for value in selected_refs),
            policy=policy.policy,
            checks=policy.checks,
            exceptions=exceptions,
            sources=all_sources,
            required_source_read_set=merged,
        )
        # Actual fixed content does not grant resource qualification;
        # policy and independent exception applicability remain explicit owner facts.
        basis = to_jsonable_python(
            {
                "watermarks": direct._merge_marks(marks),
                "artifacts": artifacts,
                "verified_sources": sorted(verified),
                "signatures": signatures,
                "line_links": links,
                "policy": deepcopy(policy.source_basis),
                "exceptions": deepcopy(exception_basis),
                "project_definition": {
                    "id": link_rows[0].definition_id,
                    "revision": link_rows[0].definition_revision,
                },
            }
        )
        return ReleaseMaterialRead(
            material, basis, all_sources, merged, tuple(dict.fromkeys(gaps)), now()
        )

    @staticmethod
    def _snapshot(value):
        return deepcopy(
            to_jsonable_python(
                {
                    key: getattr(value, key)
                    for key in ReleaseMaterialRead.__dataclass_fields__
                    if key != "checked_at"
                }
            )
        )

    def _binding(self, s, ctx, pid, value):
        saved = self._reads.get(value) if type(value) is ReleaseMaterialRead else None
        _require(saved is not None, "须使用本owner实际发行的材料。")
        session, uow, caller, product, runtime, snapshot, checked = saved
        _same_uow(s, uow, ctx, caller)
        _require(
            session() is s
            and product == pid
            and runtime == self._runtime(s)
            and snapshot == self._snapshot(value)
            and checked == value.checked_at,
            "实际发布读取的调用、运行时或封存材料已改变。",
        )

    def read(self, s, ctx, pid, payload):
        require_context(s, ctx)
        payload = PackageAssemblePayload.model_validate(payload)
        uow, caller, runtime = _uow(s), digest(vars(ctx)), self._runtime(s)
        key = digest(
            {"caller": caller, "product": str(pid), "payload": payload.model_dump(mode="json")}
        )
        cache = self._cache.get(s)
        if cache is not None and cache[0] == uow and key in cache[1]:
            self._binding(s, ctx, pid, cache[1][key])
            return cache[1][key]
        value = self._collect(s, ctx, pid, payload)
        _same_uow(s, uow, ctx, caller)
        _require(runtime == self._runtime(s), "实际读取期间来源owner发生变化。")
        self._reads[value] = (
            ref(s),
            uow,
            caller,
            pid,
            runtime,
            self._snapshot(value),
            value.checked_at,
        )
        if cache is None or cache[0] != uow:
            self._cache[s] = (uow, {})
        self._cache[s][1][key] = value
        return value

    def current(self, s, ctx, pid, read_or_material, source_basis=None):
        """Direct watermark comparison; persisted inputs require the host's real atom binding."""
        require_context(s, ctx)
        self._runtime(s)
        if type(read_or_material) is ReleaseMaterialRead:
            self._binding(s, ctx, pid, read_or_material)
            material, source_basis = read_or_material.material, read_or_material.source_basis
        else:
            material = ReleaseMaterial.model_validate(read_or_material)
        _require(
            material.scope.tenant_id == ctx.tenant_id
            and material.scope.product_id == pid
            and material.category_id == ctx.category_id,
            "发布材料不属于当前实际品类型号。",
            "FORBIDDEN_SCOPE",
            403,
        )
        _require(
            type(source_basis) is dict and bool(source_basis.get("watermarks")),
            "缺实际直接材料水位。",
        )
        known = [
            mark
            for mark in source_basis["watermarks"]
            if mark["table"] in direct._MODELS
            and mark["key"] in {"id", "original_id", "series_id", "issue_id", "build_id"}
        ]
        if known:
            direct._watermarks_current(s, ctx, pid, known)
        for mark in source_basis["watermarks"]:
            if mark in known:
                continue
            _require(mark.get("table") in _MODELS, "未知的材料水位类型。")
            actual = _query_mark(s, ctx, pid, _MODELS[mark["table"]], mark["key"], mark["ids"])
            for value in actual["rows"]:
                _require(
                    value.get("product_id") in (None, str(pid))
                    and value.get("category_id") in (None, str(ctx.category_id))
                    and value.get("project_id") in (None, str(material.scope.project_id))
                    and (
                        value.get("visibility") != "private"
                        or value.get("owner_id") == str(ctx.requester_id)
                    ),
                    "固定领域材料当前不可读取。",
                    "FORBIDDEN_SCOPE",
                    403,
                )
            _require(actual == mark, "发布材料实际固定版本或Current已变化。")
        for signature in source_basis.get("signatures", ()):
            _require(
                signature_current(
                    s, ctx, pid, UUID(signature["project_id"]), signature["snapshot"]
                ),
                "已保存签署的当前水位需要重核。",
            )
        if "policy" in source_basis:
            _require(
                self.policy_owner.current(s, ctx, pid, source_basis["policy"]),
                "受控发布政策或当前签发依据已变化。",
            )
        elif material.policy is not None:
            _require(False, "固定政策缺实际来源水位。")
        if material.exceptions:
            _require(bool(source_basis.get("exceptions")), "例外缺实际固定决定水位。")
            self.exception_owner.current(s, ctx, pid, source_basis["exceptions"])
        return True
