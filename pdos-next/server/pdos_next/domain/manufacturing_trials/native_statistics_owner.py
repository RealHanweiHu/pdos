"""Native original statistics/observations, without start or factory qualification.

The JSON projections below are fixture/publisher formats, never evidence by
themselves. Only this reader's actual original, physical and resource owners
bind them under the current caller transaction.
"""

import json
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID
from weakref import WeakKeyDictionary, ref

from pydantic import BaseModel
from pydantic_core import to_jsonable_python

from pdos_next.contracts import SourceRead
from pdos_next.database import require_context
from pdos_next.domain.build_execution import service as execution
from pdos_next.domain.build_execution.models import BuildLot
from pdos_next.domain.build_operational_facts.models import (
    BuildOperationalCurrent,
    BuildOperationalFact,
    OperationalAsset,
)
from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow, _uow
from pdos_next.domain.change_execution import service as evidence
from pdos_next.domain.configurations.service import _merge_reads
from pdos_next.domain.manufacturing_resource_owner import owner as resources
from pdos_next.domain.manufacturing_resource_owner.schemas import ResourceRequest
from pdos_next.domain.quality_execution import service as quality
from pdos_next.domain.quality_execution.models import QualityIssueCurrent
from pdos_next.errors import DomainError
from pdos_next.models import now
from pdos_next.schemas.manufacturing_trials.contracts import (
    Gap,
    PilotCreate,
    Ref,
    ResultRecord,
    YieldScope,
)
from pdos_next.schemas.manufacturing_trials.pilot_results import (
    FixedCohort,
    FixedPilotScope,
    PilotProjection,
    RecordedBatch,
)
from pdos_next.schemas.verification.contracts import SourceRef
from pdos_next.service import digest, require_access, source_for

from .native_material_owner import (
    ActualPilotMaterialOwner,
    _direct,
    _mark,
    _merge_marks,
    _source_watermarks,
    _watermarks_current,
)
from .native_schemas import StatisticsBasis
from .pilot_result_rules import project
from .rules import counts_from_units, validate_counts


def _require(test, detail, code="SOURCE_STALE", status=409):
    if not test:
        raise DomainError(code, detail, status)


def _issuer_material(value):
    value = deepcopy(value)
    value.pop("identity", None)
    if value.get("value") is not None:
        value["value"].pop("verifier_identity", None)
    return to_jsonable_python(value)


def _source_free(value):
    if isinstance(value, BaseModel):
        result = value.model_dump(mode="json")
        for key in type(value).model_fields:
            child = getattr(value, key)
            if isinstance(child, SourceRef) or (key in {"source", "disposition"} and child is None):
                result.pop(key)
            elif isinstance(child, (BaseModel, tuple)):
                result[key] = _source_free(child)
        return result
    if isinstance(value, tuple):
        return [_source_free(child) for child in value]
    return to_jsonable_python(value)


def statistics_declaration(pilot_id: UUID, statistics: StatisticsBasis):
    """Supported original JSON line, with its self-referential source omitted."""
    return {
        "schema_version": "pdos-pilot-statistics-declaration-v1",
        "pilot_id": str(pilot_id),
        "statistics": _source_free(StatisticsBasis.model_validate(statistics)),
    }


def result_values(pilot_id: UUID, record: ResultRecord):
    """All original fields/values; only recursive SourceRef metadata is omitted."""
    return {
        "schema_version": "pdos-pilot-result-values-v1",
        "pilot_id": str(pilot_id),
        "record": _source_free(ResultRecord.model_validate(record)),
    }


def _sources(value):
    if isinstance(value, SourceRef):
        return (value,)
    if isinstance(value, BaseModel):
        return tuple(
            dict.fromkeys(
                source
                for key in type(value).model_fields
                for source in _sources(getattr(value, key))
            )
        )
    if isinstance(value, tuple):
        return tuple(dict.fromkeys(source for child in value for source in _sources(child)))
    return ()


def _original(s, ctx, pid, source, expected):
    _require(
        source.kind == "artifact" and evidence.POSITION.fullmatch(source.position) is not None,
        "该试产原始声明路径尚无受控JSON原件读取适配。",
        "INTEGRATION_REQUIRED",
        503,
    )
    row = source_for(s, ctx, pid, source.id, source.revision)
    position = evidence.POSITION.fullmatch(source.position)

    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("重复JSON字段")
            result[key] = value
        return result

    def invalid_constant(_value):
        raise ValueError("非有限JSON数值")

    try:
        value = json.loads(
            row.content.splitlines()[int(position[1]) - 1],
            object_pairs_hook=pairs,
            parse_constant=invalid_constant,
        )
    except (ValueError, IndexError):
        raise DomainError(
            "INTEGRATION_REQUIRED", "试产原始资料须为支持格式的完整JSON行。", 503
        ) from None
    _require(
        isinstance(value, dict) and value.get("schema_version") == expected["schema_version"],
        "该试产原始资料格式尚未接入。",
        "INTEGRATION_REQUIRED",
        503,
    )
    _require(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        == json.dumps(expected, sort_keys=True, separators=(",", ":"), allow_nan=False),
        "原始JSON与本次Pilot完整统计声明或观察值不一致。",
        "MISSING_REQUIRED_EVIDENCE",
        422,
    )
    return value


@dataclass(frozen=True, eq=False)
class PilotStatisticsRead:
    fixed: FixedPilotScope | None
    batch: RecordedBatch | None
    projection: PilotProjection | None
    material: dict
    source_basis: dict
    sources: tuple[SourceRef, ...]
    required_source_read_set: tuple[SourceRead, ...]
    gaps: tuple[Gap, ...]
    checked_at: datetime


class ActualPilotStatisticsOwner:
    def __init__(self, engine, *, material_owner=None):
        self.engine = engine
        self._physical = material_owner or ActualPilotMaterialOwner(engine)
        _require(self._physical.engine is engine, "统计与物理材料须使用同一真实存储。")
        self._reads = WeakKeyDictionary()
        self._cache = WeakKeyDictionary()

    def _runtime(self, s):
        _require(s.get_bind() is self.engine, "试产统计owner与Session存储不同。")
        return (
            evidence._runtime_stamp(s),
            *(
                id(value)
                for value in (
                    execution.get_lot,
                    execution.get_sample,
                    quality.get_issue_for_change,
                    resources.inspect_resource,
                    evidence._evidence,
                    source_for,
                )
            ),
        )

    def _collect(self, s, ctx, pid, details, statistics, record, revision, previous_scope):
        physical = self._physical.read(s, ctx, pid, details)
        native = physical.material
        # The same actual material owner already read this immutable physical
        # object. Do not rebuild its project/configuration/original closure.
        lot = s.get(BuildLot, details.basis.lot.id)
        lot_view = native.lot
        _require(lot is not None, "实际批次不可读取。")
        marks = [_mark(lot)]
        nature = lot.observation_nature
        _require(
            nature in {"real", "synthetic"}
            and lot.revision == details.basis.lot.revision
            and lot.project_id == native.scope.project_id,
            "实际批次观察性质、版本或项目不能核对。",
        )
        gaps = []

        def gap(code, detail):
            gaps.append(Gap(code=code, state="unknown", owner_role="npi", detail=detail))

        reads = [[value.model_dump(mode="json") for value in physical.required_source_read_set]]
        refs = [*physical.sources, *_sources(statistics), *_sources(record)]
        declared_samples = statistics.samples if statistics is not None else ()
        observed_samples = (
            tuple(value.sample for value in record.units) if record is not None else ()
        )
        sample_refs = tuple(dict.fromkeys((*declared_samples, *observed_samples)))
        samples, issues = [], []
        for selected in sample_refs:
            row, view = execution.get_sample(s, ctx, pid, selected.id)
            marks.append(_mark(row))
            _require(
                row.revision == selected.revision
                and (row.lot_id, row.build_id, row.project_id, row.actual_configuration_id)
                == (lot.id, lot.build_id, lot.project_id, lot.actual_configuration_id),
                "统计成员须为同一真实批次/实际配置的固定SampleUnit。",
                "CONFIGURATION_MISMATCH",
            )
            samples.append(to_jsonable_python(view))
            reads.append(view["required_source_read_set"])
        if record is not None:
            validate_counts(
                record.counts if record.counts is not None else counts_from_units(record)
            )
            _require(
                record.expected_pilot_revision == revision
                and record.scope.basis == details.basis
                and record.scope.manufacturing_baseline == details.manufacturing_baseline
                and record.scope.line == details.line
                and record.scope.nature == nature,
                "原观察必须保留真实Pilot版本、物理批次、发布、产线及观察性质。",
                "CONFIGURATION_MISMATCH",
            )
            _require(
                record.counts is None
                or record.counts.input_count is None
                or record.counts.input_count <= lot.observed_unit_count,
                "原观察投入不得超过实际母批数量。",
                "FIXED_DENOMINATOR_CHANGED",
            )
            _require(
                len(record.units) <= lot.observed_unit_count,
                "逐件原观察不能超过真实母批数量。",
                "FIXED_DENOMINATOR_CHANGED",
            )
            for exception in record.exceptions:
                if exception.issue is None:
                    continue
                selected = exception.issue
                row, view = quality.get_issue_for_change(
                    s, ctx, pid, selected.id, selected.revision, write=False
                )
                marks.extend(
                    (
                        _mark(row),
                        _direct(
                            s, ctx, QualityIssueCurrent, "issue_id", [row.issue_id], scope_id=pid
                        ),
                    )
                )
                _require(
                    row.project_id == lot.project_id
                    and row.issue_id == selected.id
                    and row.revision == selected.revision
                    and view.is_current is True,
                    "异常Issue须为同项目的真实可读Current精确版本。",
                )
                if view.source_status != "current":
                    gap(
                        "PILOT_ISSUE_SOURCE_RECHECK_REQUIRED",
                        "实际当前Issue的依据仍需其owner重核。",
                    )
                issues.append(to_jsonable_python(view))
                reads.append(
                    [value.model_dump(mode="json") for value in view.required_source_read_set]
                )
                refs.extend(SourceRef.model_validate(value) for value in view.sources)
        resource = None
        expected_scope, cohort = None, None
        if statistics is None:
            gap("PILOT_STATISTICS_DECLARATION_MISSING", "本次尚无受控固定统计声明。")
        else:
            _require(
                native.process["site"] in (None, statistics.site),
                "原始统计场地与实际制造配置不一致。",
                "CONFIGURATION_MISMATCH",
            )
            _require(
                len(
                    [
                        v
                        for v in native.process["operations"]
                        if v["key"] == statistics.operation_key
                    ]
                )
                == 1,
                "原始统计工序不属于实际固定制造配置。",
                "CONFIGURATION_MISMATCH",
            )
            expected_scope = YieldScope(
                basis=details.basis,
                manufacturing_baseline=details.manufacturing_baseline,
                line=details.line,
                cohort_key=statistics.statistics_basis_key,
                window_start=statistics.window_start,
                window_end=statistics.window_end,
                criterion=Ref(kind="criterion", id=statistics.criterion_id, revision=1),
                nature=nature,
                minimum_sample=statistics.minimum_sample,
            )
            _require(
                record is None or record.scope == expected_scope,
                "原观察与受控声明的窗口、判据、分母口径或性质不一致。",
                "CONFIGURATION_MISMATCH",
            )
            members = tuple(statistics.samples) if statistics.samples else None
            if statistics.cohort_mode == "entire_lot":
                denominator = lot.observed_unit_count
                _require(
                    members is None or len(members) == denominator,
                    "全批声明的实际成员全集须等于真实母批数量。",
                    "FIXED_DENOMINATOR_CHANGED",
                )
            else:
                denominator = len(members) if members is not None else None
                if members is None:
                    gap("PILOT_FIXED_SAMPLE_MEMBERS_MISSING", "固定抽样子集尚无实际样件成员。")
            _require(
                denominator is None or denominator <= lot.observed_unit_count,
                "实际固定样本数不得超过母批数量。",
                "FIXED_DENOMINATOR_CHANGED",
            )
            cohort = FixedCohort(
                population_count=lot.observed_unit_count,
                fixed_input_count=denominator,
                mode=statistics.cohort_mode,
                statistics_basis_key=statistics.statistics_basis_key,
                unit_refs=members,
                source=statistics.source,
            )
            if record is not None and record.units:
                if members is None:
                    gap("PILOT_UNIT_COHORT_MEMBERS_MISSING", "逐件原观察尚无固定成员全集。")
                else:
                    _require(
                        {value.sample for value in record.units} == set(members),
                        "逐件观察不得增删或替换固定实际成员。",
                        "CONFIGURATION_MISMATCH",
                    )
            execution_scope = statistics.operational_scope
            if details.line is None or execution_scope is None:
                gap("PILOT_LINE_EXECUTION_BINDING_MISSING", "缺固定产线或实际操作/执行范围。")
            else:
                _require(
                    execution_scope.site == statistics.site
                    and execution_scope.window.start <= statistics.window_start
                    and statistics.window_end <= execution_scope.window.finish,
                    "原统计窗口或场地不在声明的真实执行范围。",
                    "CONFIGURATION_MISMATCH",
                )
                request = ResourceRequest(
                    scope=native.scope,
                    build=details.basis.build.model_dump(exclude={"kind"}),
                    process=details.basis.process_revision.model_dump(exclude={"kind"}),
                    execution=execution_scope,
                    operation_key=statistics.operation_key,
                    resource=details.line.model_dump(),
                )
                resource = resources.inspect_resource(s, ctx, pid, request=request)
                reads.append(
                    [
                        value.model_dump(mode="json")
                        for value in resource.view.required_source_read_set
                    ]
                )
                for code in resource.view.gaps:
                    gap(code, "本轮资源owner保留的真实资格/适用性缺项。")
        if details.manufacturing_baseline is None:
            gap("PILOT_STATISTICS_PUBLICATION_MISSING", "统计尚未绑定实际正式制造发布。")
        if resource is not None and not (
            resource.view.current
            and any(
                value.resource.model_dump() == details.line.model_dump()
                and value.current
                and value.lifecycle == "active"
                for value in resource.view.resources
            )
            and any(
                relation.resource.model_dump() == details.line.model_dump()
                for relation in resource.view.relations
            )
        ):
            gap("PILOT_STATISTICS_LINE_IDENTITY_UNKNOWN", "尚无实际固定产线与本轮工序的当前关系。")
        issuer_basis = None
        if resource is not None:
            marks.append(
                _direct(s, ctx, BuildOperationalCurrent, "build_id", [lot.build_id], scope_id=pid)
            )
            if resource.view.fact is not None:
                fact = s.get(BuildOperationalFact, resource.view.fact.id)
                _require(fact is not None, "实际资源事实不可读取。")
                marks.append(_mark(fact))
                for asset in resource._basis["assets"]:
                    actual_asset = s.get(OperationalAsset, UUID(str(asset["id"])))
                    _require(actual_asset is not None, "实际固定产线镜像不可读取。")
                    marks.append(_mark(actual_asset))
                issuer_basis = {
                    "fact_id": str(fact.id),
                    "request": resource.view.request.model_dump(mode="json"),
                    "value": _issuer_material(resource._basis["issuer"]),
                }
        all_refs = tuple(dict.fromkeys(refs))
        _require(
            all(value.kind == "artifact" for value in all_refs),
            "新增试产原始来源尚无精确原件读取端口。",
            "INTEGRATION_REQUIRED",
            503,
        )
        merged = _merge_reads(
            *reads,
            [
                {"artifact_id": str(value.id), "expected_revision": value.revision}
                for value in all_refs
            ],
        )
        # Reuse the real upstream owners' checked originals. Read bytes only for
        # newly introduced originals; a new line in an already read original
        # requires its direct line/metadata check, not a second byte read.
        artifacts = deepcopy(physical.source_basis["artifacts"])
        if resource is not None:
            for key, value in resource.source_basis.items():
                _require(
                    key not in artifacts or artifacts[key] == value,
                    "资源与物理材料的固定来源摘要不一致。",
                )
                artifacts[key] = deepcopy(value)
        verified = set(physical.source_basis["verified_sources"])
        extra_refs = tuple(v for v in all_refs if evidence.digest(v) not in verified)
        new_reads = [value for value in merged if value["artifact_id"] not in artifacts]
        new_refs = tuple(v for v in extra_refs if str(v.id) not in artifacts)
        added, _, checked_refs = evidence._evidence(s, ctx, pid, new_reads, new_refs, io=True)
        artifacts.update(added)
        verified.update(checked_refs)
        old_refs = tuple(v for v in extra_refs if str(v.id) not in added)
        if old_refs:
            old_reads = _merge_reads(
                [{"artifact_id": str(v.id), "expected_revision": v.revision} for v in old_refs]
            )
            checked_sources, _, checked_refs = evidence._evidence(
                s, ctx, pid, old_reads, old_refs, io=False
            )
            _require(
                all(artifacts[key] == value for key, value in checked_sources.items()),
                "固定原文在本次新增行核对时已变化。",
            )
            verified.update(checked_refs)
        _require(
            {evidence.digest(value) for value in all_refs} <= set(verified)
            and {(str(value["artifact_id"]), value["expected_revision"]) for value in merged}
            == {(str(key), value["revision"]) for key, value in artifacts.items()},
            "原始资料的完整行及摘要未由实际来源owner核对。",
            "MISSING_REQUIRED_EVIDENCE",
        )
        originals = {}
        if statistics is not None:
            originals["statistics"] = _original(
                s, ctx, pid, statistics.source, statistics_declaration(details.pilot_id, statistics)
            )
        if record is not None:
            originals["record"] = _original(
                s, ctx, pid, record.source, result_values(details.pilot_id, record)
            )
        require_access(s, ctx, pid)
        checked = now()
        _require(
            record is None or record.observed.occurred_at <= checked,
            "实际观察发生时间不得在当前时钟之后。",
            "FUTURE_OBSERVATION",
        )
        fixed, declared = None, None
        if (
            expected_scope is not None
            and cohort.fixed_input_count is not None
            and details.manufacturing_baseline is not None
            and details.line is not None
        ):
            # This structure only compares original immutable obligations. A
            # current line read below is separately required for a live fixed
            # statistics result; the declaration cannot attest that relation.
            declared = FixedPilotScope(
                scope=native.scope,
                pilot_id=details.pilot_id,
                pilot_revision=revision,
                purpose=native.purpose,
                site=statistics.site,
                original_timezone=statistics.original_timezone,
                yield_scope=expected_scope,
                cohort=cohort,
            )
            if (
                resource is not None
                and resource.view.current
                and "PILOT_STATISTICS_LINE_IDENTITY_UNKNOWN" not in {value.code for value in gaps}
                and "PILOT_UNIT_COHORT_MEMBERS_MISSING" not in {value.code for value in gaps}
            ):
                fixed = declared
        if previous_scope is not None:
            _require(
                declared is not None
                and previous_scope.model_copy(update={"pilot_revision": revision}) == declared,
                "已固定的窗口、场地、产线、判据、成员或物理范围不能在修正中更换。",
                "FIXED_SCOPE_CHANGED",
            )
        batch, projection = None, None
        if record is not None and fixed is not None:
            batch = RecordedBatch(fixed=fixed, record=record)
            if fixed.yield_scope.window_end > checked:
                gap("PILOT_STATISTICS_WINDOW_NOT_FINISHED", "已保存原始观察，固定窗口尚未结束。")
            else:
                projection = project(batch, checked_at=checked)
        material = to_jsonable_python(
            {
                "physical": physical.material.model_dump(mode="json"),
                "statistics": statistics,
                "record": record,
                "lot": lot_view,
                "samples": samples,
                "issues": issues,
                "resource": resource.view if resource is not None else None,
                "originals": originals,
                "qualification": "unknown",
                "start_authorized": False,
                "manufacturing_release": None,
            }
        )
        basis = to_jsonable_python(
            {
                "physical": physical.source_basis,
                "artifacts": artifacts,
                "verified_sources": sorted(verified),
                "resource": resource.source_basis if resource is not None else None,
                "watermarks": _merge_marks(
                    [
                        *marks,
                        *_source_watermarks(
                            s,
                            ctx,
                            pid,
                            {
                                key: value
                                for key, value in artifacts.items()
                                if key not in physical.source_basis["artifacts"]
                            },
                        ),
                    ]
                ),
                "issuer": issuer_basis,
            }
        )
        return PilotStatisticsRead(
            fixed,
            batch,
            projection,
            material,
            basis,
            all_refs,
            tuple(SourceRead.model_validate(value) for value in merged),
            tuple(gaps),
            checked,
        )

    @staticmethod
    def _snapshot(value):
        return deepcopy(
            tuple(
                to_jsonable_python(getattr(value, field))
                for field in PilotStatisticsRead.__dataclass_fields__
                if field != "checked_at"
            )
        )

    def read(
        self,
        s,
        ctx,
        pid,
        details,
        statistics,
        *,
        record=None,
        pilot_revision=1,
        previous_scope=None,
    ):
        details = PilotCreate.model_validate(details)
        statistics = StatisticsBasis.model_validate(statistics) if statistics is not None else None
        record = ResultRecord.model_validate(record) if record is not None else None
        _require(type(pilot_revision) is int and pilot_revision >= 1, "实际Pilot版本须为正整数。")
        previous_scope = (
            FixedPilotScope.model_validate(previous_scope) if previous_scope is not None else None
        )
        semantic = to_jsonable_python((details, statistics, record, pilot_revision, previous_scope))
        uow, caller, runtime = _uow(s), digest(vars(ctx)), self._runtime(s)
        key = digest({"caller": caller, "product": str(pid), "payload": semantic})
        cached = self._cache.get(s)
        if cached is not None and cached[0] == uow and key in cached[1]:
            self._binding(s, ctx, pid, semantic, cached[1][key])
            return cached[1][key]
        latest = self._collect(
            s, ctx, pid, details, statistics, record, pilot_revision, previous_scope
        )
        _same_uow(s, uow, ctx, caller)
        _require(runtime == self._runtime(s), "试产统计实际owner在读取期间变化。")
        self._reads[latest] = (
            ref(s),
            uow,
            caller,
            pid,
            semantic,
            self._snapshot(latest),
            latest.checked_at,
            runtime,
        )
        if cached is None or cached[0] != uow:
            self._cache[s] = (uow, {})
        self._cache[s][1][key] = latest
        return latest

    def current(self, s, ctx, pid, material, source_basis):
        """Check the actual saved atom/Confirmation's direct dependencies only.

        The host binds these two snapshots before calling. This does not issue
        an opaque read, rebuild originals, or requalify an earlier signer.
        """
        require_context(s, ctx)
        self._runtime(s)
        self._physical.current(s, ctx, pid, material["physical"], source_basis["physical"])
        _watermarks_current(s, ctx, pid, source_basis.get("watermarks"))
        issuer = source_basis.get("issuer")
        if issuer is not None:
            fact = s.get(BuildOperationalFact, UUID(issuer["fact_id"]))
            _require(fact is not None, "固定资源事实已缺失。")
            request = ResourceRequest.model_validate(issuer["request"])
            _require(
                _issuer_material(resources._issuer(s, ctx, request, fact)[1]) == issuer["value"],
                "当前资源发行者水位已变化。",
            )
        return True

    def _binding(self, s, ctx, pid, semantic, previous):
        saved = self._reads.get(previous) if type(previous) is PilotStatisticsRead else None
        _require(saved is not None, "须使用本owner实际发行的原统计封存读取。")
        session, uow, caller, product, original_semantic, snapshot, checked, runtime = saved
        _same_uow(s, uow, ctx, caller)
        _require(
            session() is s
            and product == pid
            and runtime == self._runtime(s)
            and previous.checked_at == checked
            and self._snapshot(previous) == snapshot,
            "原实际调用或统计封存材料已变化。",
        )
        _require(semantic == original_semantic, "刷新须保留同一统计、原始观察及修正固定范围。")
        return saved

    def refresh(
        self,
        s,
        ctx,
        pid,
        details,
        statistics,
        previous,
        *,
        record=None,
        pilot_revision=1,
        previous_scope=None,
    ):
        current_semantic = to_jsonable_python(
            (
                PilotCreate.model_validate(details),
                StatisticsBasis.model_validate(statistics) if statistics is not None else None,
                ResultRecord.model_validate(record) if record is not None else None,
                pilot_revision,
                FixedPilotScope.model_validate(previous_scope)
                if previous_scope is not None
                else None,
            )
        )
        saved = self._binding(s, ctx, pid, current_semantic, previous)
        self.current(s, ctx, pid, previous.material, previous.source_basis)
        require_access(s, ctx, pid)
        latest = replace(previous, checked_at=now())
        self._reads[latest] = (*saved[:6], latest.checked_at, saved[-1])
        return latest
