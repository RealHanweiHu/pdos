"""Pure Build preparation from fixed server snapshots; never authorize or allocate.

Architecture 02 §§6–7 and 04 §§8,10–11 distinguish fixed configurations, demand,
actual usable stock, resource acceptance, methods and professional release. A
current draft is a calculation source, never evidence of formal qualification.
The caller owns scope, source validity and the immutable server-supplied as_of.
"""

from datetime import datetime
from typing import Literal

from pydantic import ConfigDict, Field, JsonValue, field_validator

from pdos_next.engines.supply_cost import calculate_coverage, expand_bom
from pdos_next.engines.supply_cost.common import (
    FrozenDTO,
    Positive,
    Quantity,
    SnapshotRef,
    Text,
    digest,
    issue,
    sorted_issues,
    source_issues,
)
from pdos_next.engines.supply_cost.dto import (
    BomItem,
    BomSnapshot,
    BuildSnapshot,
    CoverageRequest,
    FixedBasis,
)


class _Versioned(FrozenDTO):
    id: Text
    revision: int = Field(ge=1, strict=True)
    created_at: datetime
    source_state: Literal["current", "stale", "withdrawn", "unknown"] = "unknown"
    valid_until: datetime | None = None
    # Fixed purpose, design references, read sets and other server-loaded context.
    # They bind the snapshot/hash but never become resource or release authority.
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("created_at", "valid_until")
    @classmethod
    def aware_time(cls, value):
        return SnapshotRef.aware_time(value)


class _Build(_Versioned):
    quantity: Positive | None = None
    unit: Text | None = None


class _Line(FrozenDTO):
    key: Text
    part_id: Text | None = None
    quantity: Positive | None = None
    unit: Text | None = None
    # The domain may record a larger uplift; DTO v1 cannot calculate one above 1.
    # Preserve it in this snapshot and mark that line unknown instead of clipping it.
    loss_rate: Quantity | None = None
    critical: bool = Field(default=False, strict=True)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class _Bom(_Versioned):
    lines: tuple[_Line, ...] = ()


class _Engineering(_Versioned):
    definition_id: Text
    bom: _Bom | None = None


class _Operation(FrozenDTO):
    # Typed key with bounded JSON carried only as context, not qualification facts.
    model_config = ConfigDict(extra="allow", frozen=True, str_strip_whitespace=True)
    __pydantic_extra__: dict[str, JsonValue] = Field(init=False)
    key: Text


class _Manufacturing(_Versioned):
    operations: tuple[_Operation, ...] = ()


class _Input(FrozenDTO):
    schema_version: Literal["build-readiness-input.v1"] = "build-readiness-input.v1"
    as_of: datetime
    build: _Build
    engineering_configuration: _Engineering | None = None
    manufacturing_configuration: _Manufacturing | None = None

    @field_validator("as_of")
    @classmethod
    def aware_time(cls, value):
        return SnapshotRef.aware_time(value)


def _ref(kind, record):
    return SnapshotRef(
        source_id=f"{kind}:{record.id}",
        version=str(record.revision),
        sha256=digest(record),
        captured_at=record.created_at,
        valid_until=record.valid_until,
        state=record.source_state,
    )


def _source(kind, record):
    return {"kind": kind, "id": record.id, "revision": record.revision}


def _check(key, label, status, code, message, action, refs):
    return {
        "key": key,
        "label": label,
        "status": status,
        "blocking": status != "known",
        "reason_code": code,
        "message": message,
        "source_refs": refs,
        "recovery_action": action,
    }


def compute_readiness(snapshot: dict) -> dict:
    """Return reproducible demand and explicit hard unknowns; raise on malformed DTO.

    All quantities stay Decimal strings in JSON. Supply pools, reservations and
    alternates are deliberately absent: this adapter has no authority to supply
    them. It neither changes Build state nor produces a score or start permission.
    """
    data = _Input.model_validate(snapshot)
    fixed_snapshot = data.model_dump(mode="json")
    engineering, manufacturing = data.engineering_configuration, data.manufacturing_configuration
    bom = engineering.bom if engineering else None
    records = [("build", data.build)]
    if engineering:
        records.append(("engineering_configuration", engineering))
    if bom:
        records.append(("bom", bom))
    if manufacturing:
        records.append(("manufacturing_configuration", manufacturing))
    refs = [_source(kind, record) for kind, record in records]
    source_notes = [
        note
        for kind, record in records
        for note in source_issues(_ref(kind, record), data.as_of, kind)
    ]
    source_blocked = any(
        record.source_state in {"stale", "withdrawn"}
        or record.created_at > data.as_of
        or (record.valid_until is not None and record.valid_until <= data.as_of)
        for _, record in records
    )
    checks = [
        _check(
            "fixed_sources",
            "固定版本与来源",
            "blocked" if source_blocked else "unknown" if source_notes else "known",
            "SOURCE_NOT_CURRENT" if source_notes else "FIXED_SOURCES_CURRENT",
            "来源已失效或有效性未知，不能把它当成本轮可用依据。"
            if source_notes
            else "本次计算绑定固定版本；来源有效不代表工程或制造已放行。",
            "核对来源有效性并选定适用版本，再按新的固定快照计算。",
            refs,
        )
    ]
    demands, demand_notes, coverage = (), [], None
    if engineering is not None and bom is not None:
        unsupported = [
            line for line in bom.lines if line.loss_rate is not None and line.loss_rate > 1
        ]
        demand_notes.extend(
            issue("loss_rate_unsupported", line.key, "Loss uplift is outside DTO v1 [0,1]")
            for line in unsupported
        )
        basis = FixedBasis(
            build=BuildSnapshot(
                build_id=data.build.id,
                ref=_ref("build", data.build),
                quantity=data.build.quantity,
                product_unit=data.build.unit,
            ),
            bom=BomSnapshot(
                ref=_ref("bom", bom),
                engineering_configuration=_ref("configuration", engineering),
                items=tuple(
                    BomItem(
                        item_id=line.key,
                        parent_item_id=None,
                        material_id=line.part_id,
                        quantity_per_parent=line.quantity,
                        unit=line.unit,
                        loss_rate=line.loss_rate
                        if line.loss_rate is None or line.loss_rate <= 1
                        else None,
                        supply_required=True,
                        critical=line.critical,
                    )
                    for line in bom.lines
                ),
            ),
        )
        demands, expansion_notes = expand_bom(basis, data.as_of)
        demand_notes.extend(expansion_notes)
        demand_notes.extend(note for line in demands for note in line.issues)
        # This ref declares an absent connection; it is not an inventory observation.
        supply = SnapshotRef(
            source_id="unconnected-supply",
            version="unconnected.v1",
            sha256=digest(data),
            captured_at=data.as_of,
            state="unknown",
        )
        computed = calculate_coverage(
            CoverageRequest(
                as_of=data.as_of,
                basis=basis,
                supply_snapshot=supply,
                supply_scope_complete=False,
                pools=(),
                reservations=(),
                alternates=(),
            )
        )
        coverage = computed.model_dump(mode="json")
        demand_notes.extend(
            note for note in computed.issues if note.code == "material_mapping_unknown"
        )
    else:
        demand_notes.append(issue("bom_missing", "engineering_configuration", "No fixed BOM"))
    notes = sorted_issues(demand_notes)
    demand_blocked = any(note.kind == "conflict" for note in notes)
    demand_known = (
        bool(demands)
        and not notes
        and all(
            line.required_quantity is not None and line.material_id is not None for line in demands
        )
    )
    checks.append(
        _check(
            "material_demand",
            "物料需求量",
            "blocked" if demand_blocked else "known" if demand_known else "unknown",
            "DEMAND_CONFLICT"
            if demand_blocked
            else "DEMAND_COMPUTED"
            if demand_known
            else "DEMAND_INPUT_INCOMPLETE",
            "已按本轮数量、固定 BOM 和加损比例计算需求；没有推定库存或到货。"
            if demand_known
            else "BOM、数量、单位、损耗或来源不完整，受影响需求保持未知。",
            "补齐适用 BOM、正数计划数量、单位和明确加损比例，解决版本或行标识冲突。",
            [ref for ref in refs if ref["kind"] != "manufacturing_configuration"],
        )
    )
    checks[-1]["issues"] = [note.model_dump(mode="json") for note in notes]
    for key, label, code, message, action, kinds in (
        (
            "supply_coverage",
            "供应与齐套",
            "SUPPLY_SCOPE_UNCONNECTED",
            "尚无权威供应池及完整占用记录；承诺、在途和需求量都不能证明已齐套。",
            "接入有来源的实际可用量、质量限制和跨 Build 占用，再计算齐套。",
            {"build", "bom"},
        ),
        (
            "resources",
            "工装、设备与人员资源",
            "RESOURCE_ACCEPTANCE_UNKNOWN",
            "工序记录不能证明工装验收、设备校准、岗位资格和本轮时段可用。",
            "核对适用工装设备的验收与校准、人员资格及真实资源预约。",
            {"build", "manufacturing_configuration"},
        ),
        (
            "quality_method",
            "品质方法与验证准备",
            "QUALITY_METHOD_UNKNOWN",
            "尚无具名确认的方法、判据、验证范围及品质接收条件。",
            "由品质确认适用规程、判据、样件和资料要求，保留未覆盖范围。",
            {"build", "engineering_configuration", "manufacturing_configuration"},
        ),
        (
            "engineering_release",
            "工程适用性与正式放行",
            "ENGINEERING_RELEASE_UNKNOWN",
            "固定工程草稿不代表本轮用途已获工程批准。",
            "按本轮用途核对适用工程决定、偏差和必需证据。",
            {"engineering_configuration", "bom"},
        ),
        (
            "manufacturing_release",
            "制造适用性与正式放行",
            "MANUFACTURING_RELEASE_UNKNOWN",
            "制造工序草稿不代表工艺、资源和质量条件已获制造放行。",
            "按本轮用途核对制造基线、资格、控制要求与具名决定。",
            {"manufacturing_configuration"},
        ),
    ):
        checks.append(
            _check(
                key,
                label,
                "unknown",
                code,
                message,
                action,
                [ref for ref in refs if ref["kind"] in kinds],
            )
        )
    return {
        "schema_version": "build-readiness-result.v1",
        "algorithm": "fixed-build-readiness.v1",
        "as_of": fixed_snapshot["as_of"],
        "input_sha256": digest(data),
        "input_snapshot": fixed_snapshot,
        "build_id": data.build.id,
        "build_revision": data.build.revision,
        "status": "blocked" if any(check["status"] == "blocked" for check in checks) else "unknown",
        "ready": None,
        "hard_blocking": True,
        "checks": checks,
        "demands": [line.model_dump(mode="json") for line in demands],
        "coverage": coverage,
        "notice": "准备计算只呈现固定快照中的需求与缺项；不占用库存、不批准开工、不代替专业放行。",
    }
